"""Pinned binary decoders for the MarginFi deployment used by PR-028.

The layouts in this module are derived from the exact upstream source commit
declared in ``src/resources/marginfi_pr028.json``. They intentionally decode
only fields required for read-only conformance and flash-loan planning. Unknown
sizes, owners, discriminators, enum values, or fixed-point values fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Any, Mapping

from solders.pubkey import Pubkey

from .errors import MarginfiRejection, MarginfiRejectionCode


ZERO_PUBKEY = bytes(32)


@dataclass(frozen=True, slots=True)
class DecodedGroup:
    admin: str
    group_flags: int
    paused: bool
    pause_start_timestamp: int
    pause_cache_updated_at: int


@dataclass(frozen=True, slots=True)
class DecodedMarginAccount:
    group: str
    authority: str
    active_balances: tuple[str, ...]
    account_flags: int


@dataclass(frozen=True, slots=True)
class DecodedBank:
    mint: str
    mint_decimals: int
    group: str
    liquidity_vault: str
    liquidity_vault_authority: str
    token_program: str
    oracle_keys: tuple[str, ...]
    operational_state: int
    origination_fee_raw_i80f48: int
    borrow_limit: int
    flags: int


@dataclass(frozen=True, slots=True)
class DecodedTokenAccount:
    mint: str
    authority: str
    amount: int


def _slice(body: bytes, offset: int, size: int, label: str) -> bytes:
    end = offset + size
    if offset < 0 or size < 0 or end > len(body):
        raise MarginfiRejection(
            MarginfiRejectionCode.DATA_LENGTH_MISMATCH,
            f"{label} field exceeds pinned binary layout",
        )
    return body[offset:end]


def _u8(body: bytes, offset: int, label: str) -> int:
    return _slice(body, offset, 1, label)[0]


def _u64(body: bytes, offset: int, label: str) -> int:
    return struct.unpack("<Q", _slice(body, offset, 8, label))[0]


def _i64(body: bytes, offset: int, label: str) -> int:
    return struct.unpack("<q", _slice(body, offset, 8, label))[0]


def _i128(body: bytes, offset: int, label: str) -> int:
    return int.from_bytes(_slice(body, offset, 16, label), "little", signed=True)


def _pubkey(body: bytes, offset: int, label: str) -> str:
    raw = _slice(body, offset, 32, label)
    try:
        return str(Pubkey.from_bytes(raw))
    except ValueError as exc:
        raise MarginfiRejection(
            MarginfiRejectionCode.PIN_MISMATCH,
            f"{label} contains an invalid public key",
        ) from exc


def _account_body(
    account: Any,
    *,
    expected_owner: str,
    discriminator: bytes,
    struct_size: int,
    label: str,
) -> bytes:
    if account is None:
        raise MarginfiRejection(
            MarginfiRejectionCode.ACCOUNT_MISSING,
            f"{label} account missing",
        )
    if str(account.owner) != expected_owner:
        raise MarginfiRejection(
            MarginfiRejectionCode.OWNER_MISMATCH,
            f"{label} owner mismatch",
        )
    data = bytes(account.data)
    expected_size = 8 + struct_size
    if len(data) != expected_size:
        raise MarginfiRejection(
            MarginfiRejectionCode.DATA_LENGTH_MISMATCH,
            f"{label} length {len(data)} != pinned {expected_size}",
        )
    if data[:8] != discriminator:
        raise MarginfiRejection(
            MarginfiRejectionCode.DISCRIMINATOR_MISMATCH,
            f"{label} discriminator mismatch",
        )
    return data[8:]


def _layout(pin: Any, name: str) -> Mapping[str, Any]:
    try:
        value = pin.raw["account_layouts"][name]
        if not isinstance(value, dict):
            raise TypeError
        return value
    except (KeyError, TypeError) as exc:
        raise MarginfiRejection(
            MarginfiRejectionCode.PIN_MISMATCH,
            f"missing pinned layout: {name}",
        ) from exc


def decode_group(account: Any, pin: Any, *, now_timestamp: int) -> DecodedGroup:
    layout = _layout(pin, "marginfi_group")
    body = _account_body(
        account,
        expected_owner=pin.program_id,
        discriminator=bytes.fromhex(str(layout["discriminator_hex"])),
        struct_size=int(layout["struct_size"]),
        label="marginfi group",
    )
    offsets = layout["offsets"]
    pause_flags = _u8(body, int(offsets["panic_pause_flags"]), "pause flags")
    pause_start = _i64(
        body,
        int(offsets["panic_pause_start_timestamp"]),
        "pause start timestamp",
    )
    cache_updated = _i64(
        body,
        int(offsets["panic_last_cache_update"]),
        "pause cache update timestamp",
    )
    duration = int(pin.raw["constants"]["panic_pause_duration_seconds"])
    paused = bool(pause_flags & 1) and (
        now_timestamp < pause_start or now_timestamp - pause_start < duration
    )
    return DecodedGroup(
        admin=_pubkey(body, int(offsets["admin"]), "group admin"),
        group_flags=_u64(body, int(offsets["group_flags"]), "group flags"),
        paused=paused,
        pause_start_timestamp=pause_start,
        pause_cache_updated_at=cache_updated,
    )


def decode_margin_account(account: Any, pin: Any) -> DecodedMarginAccount:
    layout = _layout(pin, "marginfi_account")
    body = _account_body(
        account,
        expected_owner=pin.program_id,
        discriminator=bytes.fromhex(str(layout["discriminator_hex"])),
        struct_size=int(layout["struct_size"]),
        label="marginfi account",
    )
    offsets = layout["offsets"]
    lending_offset = int(offsets["lending_account"])
    balance_size = int(offsets["balance_size"])
    balance_count = int(offsets["balance_count"])
    active_offset = int(offsets["balance_active"])
    bank_offset = int(offsets["balance_bank"])
    balances: list[str] = []
    seen: set[str] = set()
    for index in range(balance_count):
        base = lending_offset + index * balance_size
        if _u8(body, base + active_offset, f"balance[{index}].active") == 0:
            continue
        bank = _pubkey(body, base + bank_offset, f"balance[{index}].bank")
        if bank in seen:
            raise MarginfiRejection(
                MarginfiRejectionCode.DUPLICATE_RISK_ACCOUNT,
                "margin account contains a duplicate active bank",
            )
        seen.add(bank)
        balances.append(bank)
    canonical = tuple(
        sorted(balances, key=lambda value: bytes(Pubkey.from_string(value)))
    )
    if tuple(balances) != canonical:
        raise MarginfiRejection(
            MarginfiRejectionCode.ACCOUNT_STATE_INVALID,
            "active balances are not bytewise sorted as required by the pinned layout",
        )
    return DecodedMarginAccount(
        group=_pubkey(body, int(offsets["group"]), "margin account group"),
        authority=_pubkey(body, int(offsets["authority"]), "margin account authority"),
        active_balances=canonical,
        account_flags=_u64(
            body,
            int(offsets["account_flags"]),
            "margin account flags",
        ),
    )


def decode_bank(account: Any, pin: Any, *, bank_address: str) -> DecodedBank:
    layout = _layout(pin, "bank")
    body = _account_body(
        account,
        expected_owner=pin.program_id,
        discriminator=bytes.fromhex(str(layout["discriminator_hex"])),
        struct_size=int(layout["struct_size"]),
        label="bank",
    )
    offsets = layout["offsets"]
    flags = _u64(body, int(offsets["flags"]), "bank flags")
    token_2022_flag = int(pin.raw["flags"]["bank_is_token_2022"])
    programs = pin.raw["programs"]
    token_program = (
        str(programs["token_2022"])
        if flags & token_2022_flag
        else str(programs["token"])
    )
    oracle_offset = int(offsets["oracle_keys"])
    oracle_count = int(offsets["oracle_key_count"])
    oracle_keys: list[str] = []
    for index in range(oracle_count):
        raw = _slice(body, oracle_offset + index * 32, 32, f"oracle[{index}]")
        if raw == ZERO_PUBKEY:
            continue
        oracle_keys.append(str(Pubkey.from_bytes(raw)))
    if not oracle_keys:
        raise MarginfiRejection(
            MarginfiRejectionCode.ORACLE_INVALID,
            "bank has no configured oracle keys",
        )
    program_id = Pubkey.from_string(pin.program_id)
    bank_key = Pubkey.from_string(bank_address)
    vault_authority, _ = Pubkey.find_program_address(
        [
            str(pin.raw["constants"]["liquidity_vault_authority_seed"]).encode(),
            bytes(bank_key),
        ],
        program_id,
    )
    fee_raw = _i128(
        body,
        int(offsets["protocol_origination_fee"]),
        "protocol origination fee",
    )
    if fee_raw < 0:
        raise MarginfiRejection(
            MarginfiRejectionCode.UNPROVEN_FEE,
            "negative origination fee is not supported",
        )
    return DecodedBank(
        mint=_pubkey(body, int(offsets["mint"]), "bank mint"),
        mint_decimals=_u8(body, int(offsets["mint_decimals"]), "bank mint decimals"),
        group=_pubkey(body, int(offsets["group"]), "bank group"),
        liquidity_vault=_pubkey(
            body,
            int(offsets["liquidity_vault"]),
            "bank liquidity vault",
        ),
        liquidity_vault_authority=str(vault_authority),
        token_program=token_program,
        oracle_keys=tuple(oracle_keys),
        operational_state=_u8(
            body,
            int(offsets["operational_state"]),
            "bank operational state",
        ),
        origination_fee_raw_i80f48=fee_raw,
        borrow_limit=_u64(body, int(offsets["borrow_limit"]), "bank borrow limit"),
        flags=flags,
    )


def decode_token_account(
    account: Any,
    *,
    token_program: str,
    expected_mint: str,
) -> DecodedTokenAccount:
    if account is None:
        raise MarginfiRejection(
            MarginfiRejectionCode.ACCOUNT_MISSING,
            "liquidity vault account missing",
        )
    if str(account.owner) != token_program:
        raise MarginfiRejection(
            MarginfiRejectionCode.TOKEN_PROGRAM_MISMATCH,
            "liquidity vault token-program owner mismatch",
        )
    data = bytes(account.data)
    if len(data) < 165:
        raise MarginfiRejection(
            MarginfiRejectionCode.DATA_LENGTH_MISMATCH,
            "liquidity vault is shorter than the SPL token-account base layout",
        )
    mint = str(Pubkey.from_bytes(data[0:32]))
    if mint != expected_mint:
        raise MarginfiRejection(
            MarginfiRejectionCode.LIQUIDITY_VAULT_MISMATCH,
            "liquidity vault mint does not match bank mint",
        )
    return DecodedTokenAccount(
        mint=mint,
        authority=str(Pubkey.from_bytes(data[32:64])),
        amount=struct.unpack("<Q", data[64:72])[0],
    )


def ceil_i80f48_product(
    amount: int,
    raw_rate: int,
    *,
    fractional_bits: int = 48,
) -> int:
    if amount < 0 or raw_rate < 0:
        raise MarginfiRejection(
            MarginfiRejectionCode.UNPROVEN_FEE,
            "fee inputs must be non-negative integers",
        )
    denominator = 1 << fractional_bits
    product = amount * raw_rate
    return (product + denominator - 1) // denominator
