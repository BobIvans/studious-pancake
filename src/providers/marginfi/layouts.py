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

# ---------------------------------------------------------------------------
# N07 rebind: marginfi 0.1.12 IDL-pinned Bank layout. Vendored byte-exact as
# docs/integrations/offline/p0-flashloan-rebind-2026-11-21/vendor-reference/
# idl/marginfi_0.1.12.json (from 0dotxyz/p0-ts-sdk@8a8353bb..., MIT). All
# offsets are body-relative (after the 8-byte Anchor discriminator), borsh
# sequential. Cross-checks that prove the rebind is coherent:
# - every offset that PR-028 also pins matches exactly (mint 0, mint_decimals
#   32, group 33, liquidity_vault 104, operational_state 600, oracle_setup
#   601, oracle_keys 602, borrow_limit 768, risk_tier 776, asset_tag 777,
#   flags 832);
# - the PR-028 bank struct_size 1856 equals the 0.1.12 IDL body (3904) minus
#   the trailing `_padding_1` array `[[u64; 8]; 32]` (2048 bytes).
# ---------------------------------------------------------------------------
P0_BANK_0_1_12_CORE_BODY_LEN = 1856
P0_BANK_0_1_12_FULL_BODY_LEN = 3904
P0_BANK_0_1_12_TRAILING_PADDING_LEN = 2048
P0_BANK_ASSET_SHARE_VALUE_OFFSET = 72  # WrappedI80F48 (16 bytes, signed)
P0_BANK_LIABILITY_SHARE_VALUE_OFFSET = 88  # WrappedI80F48
P0_BANK_TOTAL_LIABILITY_SHARES_OFFSET = 248  # WrappedI80F48
P0_BANK_TOTAL_ASSET_SHARES_OFFSET = 264  # WrappedI80F48
P0_BANK_LAST_UPDATE_OFFSET = 280  # i64
P0_BANK_CONFIG_OFFSET = 288  # BankConfig (544 bytes)
P0_BANK_CONFIG_DEPOSIT_LIMIT_OFFSET = 352  # config + 64: depositLimit u64
P0_BANK_CONFIG_BORROW_LIMIT_OFFSET = 768  # config + 480 (matches PR-028)
P0_BANK_CONFIG_OPERATIONAL_STATE_OFFSET = 600  # config + 312 (matches PR-028)
P0_BANK_EMISSIONS_RATE_OFFSET = 840  # u64
P0_BANK_EMISSIONS_REMAINING_OFFSET = 848  # WrappedI80F48
P0_BANK_EMISSIONS_MINT_OFFSET = 864  # pubkey
# BankOperationalState variants pinned from the 0.1.12 IDL (unit enum, u8):
P0_BANK_OPERATIONAL_STATE_NAMES = {
    0: "Paused",
    1: "Operational",
    2: "ReduceOnly",
    3: "KilledByBankruptcy",
    4: "Uninitialized",
    5: "ReduceOnlyWithBorrowingPower",
    6: "CircuitBroken",
}
P0_BANK_RISK_TIER_NAMES = {0: "Collateral", 1: "Isolated"}


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
    oracle_setup: int
    asset_tag: int
    operational_state: int
    origination_fee_raw_i80f48: int
    borrow_limit: int
    flags: int
    # N07 rebind additions (marginfi 0.1.12 IDL-pinned fields; additive with
    # defaults so legacy PR-028 callers stay valid):
    asset_share_value_raw_i80f48: int | None = None
    liability_share_value_raw_i80f48: int | None = None
    total_asset_shares_raw_i80f48: int | None = None
    total_liability_shares_raw_i80f48: int | None = None
    last_update_i64: int | None = None
    deposit_limit: int | None = None
    emissions_rate: int | None = None
    emissions_remaining_raw_i80f48: int | None = None
    emissions_mint: str | None = None
    body_len: int | None = None


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
    accepted_total_sizes: tuple[int, ...] = (),
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
    if len(data) != expected_size and len(data) not in accepted_total_sizes:
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
        sorted(
            balances,
            key=lambda value: bytes(Pubkey.from_string(value)),
            reverse=True,
        )
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
        # N07 rebind: the 0.1.12 IDL bank carries the same core layout plus a
        # trailing `_padding_1` array; accept the full-length deployment too.
        accepted_total_sizes=(
            8 + P0_BANK_0_1_12_CORE_BODY_LEN + P0_BANK_0_1_12_TRAILING_PADDING_LEN,
        ),
    )
    body_len = len(body)
    offsets = layout["offsets"]
    flags = _u64(body, int(offsets["flags"]), "bank flags")
    token_2022_flag = int(pin.raw["flags"]["bank_is_token_2022"])
    programs = pin.raw["programs"]
    token_program = (
        str(programs["token_2022"])
        if flags & token_2022_flag
        else str(programs["token"])
    )
    oracle_setup = _u8(body, int(offsets["oracle_setup"]), "oracle setup")
    asset_tag = _u8(body, int(offsets["asset_tag"]), "asset tag")
    supported_setups = {
        int(value) for value in pin.raw["conformance"]["supported_oracle_setups"]
    }
    supported_tags = {
        int(value) for value in pin.raw["conformance"]["supported_asset_tags"]
    }
    if oracle_setup not in supported_setups or asset_tag not in supported_tags:
        raise MarginfiRejection(
            MarginfiRejectionCode.ORACLE_INVALID,
            "bank oracle setup or asset tag is outside the first supported vertical",
        )
    oracle_offset = int(offsets["oracle_keys"])
    raw_oracle = _slice(body, oracle_offset, 32, "oracle[0]")
    if raw_oracle == ZERO_PUBKEY:
        raise MarginfiRejection(
            MarginfiRejectionCode.ORACLE_INVALID,
            "bank has no primary oracle key",
        )
    oracle_keys = [str(Pubkey.from_bytes(raw_oracle))]
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
    asset_share_raw = _i128(
        body, P0_BANK_ASSET_SHARE_VALUE_OFFSET, "bank asset_share_value"
    )
    liability_share_raw = _i128(
        body, P0_BANK_LIABILITY_SHARE_VALUE_OFFSET, "bank liability_share_value"
    )
    total_asset_shares_raw = _i128(
        body, P0_BANK_TOTAL_ASSET_SHARES_OFFSET, "bank total_asset_shares"
    )
    total_liability_shares_raw = _i128(
        body, P0_BANK_TOTAL_LIABILITY_SHARES_OFFSET, "bank total_liability_shares"
    )
    if (
        min(
            asset_share_raw,
            liability_share_raw,
            total_asset_shares_raw,
            total_liability_shares_raw,
        )
        < 0
    ):
        raise MarginfiRejection(
            MarginfiRejectionCode.SHARE_MATH_INVALID,
            "negative share or share-value field is invalid for a bank",
        )
    deposit_limit = _u64(
        body, P0_BANK_CONFIG_DEPOSIT_LIMIT_OFFSET, "bank config deposit_limit"
    )
    emissions_rate = _u64(body, P0_BANK_EMISSIONS_RATE_OFFSET, "bank emissions_rate")
    emissions_mint_raw = _slice(
        body, P0_BANK_EMISSIONS_MINT_OFFSET, 32, "bank emissions_mint"
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
        oracle_setup=oracle_setup,
        asset_tag=asset_tag,
        operational_state=_u8(
            body,
            int(offsets["operational_state"]),
            "bank operational state",
        ),
        origination_fee_raw_i80f48=fee_raw,
        borrow_limit=_u64(body, int(offsets["borrow_limit"]), "bank borrow limit"),
        flags=flags,
        asset_share_value_raw_i80f48=asset_share_raw,
        liability_share_value_raw_i80f48=liability_share_raw,
        total_asset_shares_raw_i80f48=total_asset_shares_raw,
        total_liability_shares_raw_i80f48=total_liability_shares_raw,
        last_update_i64=_i64(body, P0_BANK_LAST_UPDATE_OFFSET, "bank last_update"),
        deposit_limit=deposit_limit,
        emissions_rate=emissions_rate,
        emissions_remaining_raw_i80f48=_i128(
            body, P0_BANK_EMISSIONS_REMAINING_OFFSET, "bank emissions_remaining"
        ),
        emissions_mint=(
            None
            if emissions_mint_raw == ZERO_PUBKEY
            else str(Pubkey.from_bytes(emissions_mint_raw))
        ),
        body_len=body_len,
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
    amount: int, raw_rate: int, *, fractional_bits: int = 48
) -> int:
    if amount < 0 or raw_rate < 0:
        raise MarginfiRejection(
            MarginfiRejectionCode.UNPROVEN_FEE,
            "fee inputs must be non-negative integers",
        )
    denominator = 1 << fractional_bits
    product = amount * raw_rate
    return (product + denominator - 1) // denominator
