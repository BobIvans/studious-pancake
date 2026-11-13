"""AGG-03 low-level Jupiter Lend flashloan instruction contract.

This module intentionally avoids an unverified npm/runtime dependency. It
implements unsigned instruction encoding from the official public Jupiter Lend
IDL pinned below. Account discovery, deployed-state admission, fee-state
qualification, signing and submission are separate responsibilities and are not
claimed here.

Pinned upstream:
- repository: https://github.com/jup-ag/jupiter-lend
- commit: 33a22cf7a5bfdd32ab1712dda4adfbeb9b348ad9
- target/idl/flashloan.json git blob:
  0d0ae6d624b33355315e98baaf0a5d00d317beb8
- IDL version: 0.1.4

R02-CAP-A addition: a strictly read-only TokenReserve capacity reader for the
pinned Liquidity program (see the reader section below). It decodes
caller-supplied offline account bytes only; it performs no I/O, holds no
signer/sender authority, and never qualifies a FlashCapitalEdge. Effective
flash borrow capacity stays UNKNOWN (never zero) until audited program math
is proven against a live rooted-RPC snapshot with independent quorum.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields as dataclass_fields
from dataclasses import is_dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Sequence

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from src.lending.financing import FinancingEvidence

JUPITER_LEND_UPSTREAM_REPOSITORY = "https://github.com/jup-ag/jupiter-lend"
JUPITER_LEND_UPSTREAM_COMMIT = "33a22cf7a5bfdd32ab1712dda4adfbeb9b348ad9"
JUPITER_LEND_FLASHLOAN_IDL_BLOB = "0d0ae6d624b33355315e98baaf0a5d00d317beb8"
JUPITER_LEND_FLASHLOAN_IDL_VERSION = "0.1.4"

JUPITER_LEND_FLASHLOAN_PROGRAM_ID = Pubkey.from_string(
    "jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS"
)
JUPITER_FLASHLOAN_ADMIN_SEED = b"flashloan_admin"
JUPITER_FLASHLOAN_ADMIN_PDA, JUPITER_FLASHLOAN_ADMIN_BUMP = Pubkey.find_program_address(
    [JUPITER_FLASHLOAN_ADMIN_SEED],
    JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
)
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string(
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
)
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
INSTRUCTIONS_SYSVAR_ID = Pubkey.from_string(
    "Sysvar1nstructions1111111111111111111111111"
)

FLASHLOAN_BORROW_DISCRIMINATOR = bytes((103, 19, 78, 24, 240, 9, 135, 63))
FLASHLOAN_PAYBACK_DISCRIMINATOR = bytes((213, 47, 153, 137, 84, 243, 94, 232))
FLASHLOAN_ADMIN_DISCRIMINATOR = bytes((162, 161, 45, 28, 131, 91, 202, 88))
FLASHLOAN_ADMIN_ACCOUNT_LEN = 93
_U64_MAX = (1 << 64) - 1
_EXPECTED_META_FLAGS = (
    (True, True),
    (False, True),
    (False, True),
    (False, False),
    (False, True),
    (False, True),
    (False, False),
    (False, True),
    (False, False),
    (False, False),
    (False, False),
    (False, False),
    (False, False),
    (False, False),
)


class JupiterLendRejectionCode(StrEnum):
    INVALID_AMOUNT = "AGG03_JUP_LEND_INVALID_AMOUNT"
    INVALID_FIXED_ACCOUNT = "AGG03_JUP_LEND_INVALID_FIXED_ACCOUNT"
    ORDER_INVARIANT = "AGG03_JUP_LEND_ORDER_INVARIANT"
    AMOUNT_MISMATCH = "AGG03_JUP_LEND_AMOUNT_MISMATCH"
    ACCOUNT_MISMATCH = "AGG03_JUP_LEND_ACCOUNT_MISMATCH"


class JupiterLendCapacityRejectionCode(StrEnum):
    """Typed R02-CAP-A fail-closed negatives (structural and admission)."""

    TOKEN_RESERVE_UNKNOWN_DISCRIMINATOR = "R02CAPA_TOKEN_RESERVE_UNKNOWN_DISCRIMINATOR"
    TOKEN_RESERVE_LAYOUT_MISMATCH = "R02CAPA_TOKEN_RESERVE_LAYOUT_MISMATCH"
    TOKEN_RESERVE_UNKNOWN_FIELD = "R02CAPA_TOKEN_RESERVE_UNKNOWN_FIELD"
    TOKEN_RESERVE_OWNER_MISMATCH = "R02CAPA_TOKEN_RESERVE_OWNER_MISMATCH"
    TOKEN_RESERVE_PDA_MISMATCH = "R02CAPA_TOKEN_RESERVE_PDA_MISMATCH"
    TOKEN_RESERVE_MINT_BINDING_MISMATCH = "R02CAPA_TOKEN_RESERVE_MINT_BINDING_MISMATCH"
    TOKEN_RESERVE_INTERACTING = "R02CAPA_RESERVE_INTERACTING_STATE_SET"
    CAPACITY_STATE_INVALID = "R02CAPA_CAPACITY_STATE_INVALID"
    VAULT_ADDRESS_BINDING_MISMATCH = "R02CAPA_VAULT_ADDRESS_BINDING_MISMATCH"
    VAULT_LAYOUT_MISMATCH = "R02CAPA_VAULT_TOKEN_ACCOUNT_LAYOUT_MISMATCH"
    VAULT_TOKEN_PROGRAM_MISMATCH = "R02CAPA_VAULT_TOKEN_PROGRAM_MISMATCH"
    VAULT_MINT_BINDING_MISMATCH = "R02CAPA_VAULT_MINT_BINDING_MISMATCH"
    VAULT_FROZEN = "R02CAPA_VAULT_FROZEN"
    VAULT_DELEGATE_UNPROVEN = "R02CAPA_VAULT_DELEGATE_UNPROVEN"
    VAULT_CLOSE_AUTHORITY_UNPROVEN = "R02CAPA_VAULT_CLOSE_AUTHORITY_UNPROVEN"
    FINANCING_MINT_BINDING_MISMATCH = "R02CAPA_FINANCING_MINT_BINDING_MISMATCH"
    FINANCING_RESERVE_BINDING_MISMATCH = "R02CAPA_FINANCING_RESERVE_BINDING_MISMATCH"
    FINANCING_VAULT_BINDING_MISMATCH = "R02CAPA_FINANCING_VAULT_BINDING_MISMATCH"
    FINANCING_LIQUIDITY_PROGRAM_MISMATCH = "R02CAPA_FINANCING_LIQUIDITY_PROGRAM_MISMATCH"
    MISSING_EFFECTIVE_FLASH_CAP = "MISSING_EFFECTIVE_FLASH_CAP"
    LIVE_ROOTED_RPC_NOT_AUTHORIZED = "LIVE_ROOTED_RPC_NOT_AUTHORIZED"
    GRAPH_ALLOWANCE_PENDING = (
        "R02CAPA_FLASH_CAPITAL_GRAPH_ALLOWANCE_PENDING_INDEPENDENT_QUORUM"
    )


class JupiterLendAdapterError(ValueError):
    def __init__(
        self,
        code: JupiterLendRejectionCode | JupiterLendCapacityRejectionCode,
        message: str,
    ) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class JupiterLendFlashloanAccounts:
    """Ordered account contract from the pinned flashloan IDL."""

    signer: Pubkey
    flashloan_admin: Pubkey
    signer_borrow_token_account: Pubkey
    mint: Pubkey
    flashloan_token_reserves_liquidity: Pubkey
    flashloan_borrow_position_on_liquidity: Pubkey
    rate_model: Pubkey
    vault: Pubkey
    liquidity: Pubkey
    liquidity_program: Pubkey
    token_program: Pubkey
    associated_token_program: Pubkey = ASSOCIATED_TOKEN_PROGRAM_ID
    system_program: Pubkey = SYSTEM_PROGRAM_ID
    instruction_sysvar: Pubkey = INSTRUCTIONS_SYSVAR_ID

    def __post_init__(self) -> None:
        if self.flashloan_admin != JUPITER_FLASHLOAN_ADMIN_PDA:
            raise JupiterLendAdapterError(
                JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
                "flashloan_admin does not match the pinned PDA seed/program",
            )
        expected = (
            (
                self.associated_token_program,
                ASSOCIATED_TOKEN_PROGRAM_ID,
                "ATA program",
            ),
            (self.system_program, SYSTEM_PROGRAM_ID, "system program"),
            (
                self.instruction_sysvar,
                INSTRUCTIONS_SYSVAR_ID,
                "instructions sysvar",
            ),
        )
        for actual, required, label in expected:
            if actual != required:
                raise JupiterLendAdapterError(
                    JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
                    f"{label} differs from pinned IDL",
                )

    def metas(self) -> list[AccountMeta]:
        return [
            AccountMeta(self.signer, True, True),
            AccountMeta(self.flashloan_admin, False, True),
            AccountMeta(self.signer_borrow_token_account, False, True),
            AccountMeta(self.mint, False, False),
            AccountMeta(self.flashloan_token_reserves_liquidity, False, True),
            AccountMeta(self.flashloan_borrow_position_on_liquidity, False, True),
            AccountMeta(self.rate_model, False, False),
            AccountMeta(self.vault, False, True),
            AccountMeta(self.liquidity, False, False),
            AccountMeta(self.liquidity_program, False, False),
            AccountMeta(self.token_program, False, False),
            AccountMeta(self.associated_token_program, False, False),
            AccountMeta(self.system_program, False, False),
            AccountMeta(self.instruction_sysvar, False, False),
        ]


@dataclass(frozen=True, slots=True)
class JupiterLendFlashloanAdminState:
    authority: Pubkey
    liquidity_program: Pubkey
    status: bool
    flashloan_fee: int
    flashloan_timestamp: int
    is_flashloan_active: bool
    active_flashloan_amount: int
    bump: int

    def __post_init__(self) -> None:
        if not 0 <= self.flashloan_fee <= 0xFFFF:
            raise JupiterLendAdapterError(
                JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
                "flashloan fee is outside u16 range",
            )
        if not 0 <= self.flashloan_timestamp <= _U64_MAX:
            raise JupiterLendAdapterError(
                JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
                "flashloan timestamp is outside u64 range",
            )
        if not 0 <= self.active_flashloan_amount <= _U64_MAX:
            raise JupiterLendAdapterError(
                JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
                "active amount is outside u64 range",
            )
        if self.bump != JUPITER_FLASHLOAN_ADMIN_BUMP:
            raise JupiterLendAdapterError(
                JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
                "flashloan admin bump differs from pinned PDA",
            )


def _decode_bool(value: int, label: str) -> bool:
    if value not in (0, 1):
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
            f"{label} is not canonical borsh bool",
        )
    return bool(value)


def decode_flashloan_admin_state(data: bytes) -> JupiterLendFlashloanAdminState:
    """Decode exact Anchor/Borsh FlashloanAdmin layout from pinned IDL v0.1.4."""

    raw = bytes(data)
    if len(raw) != FLASHLOAN_ADMIN_ACCOUNT_LEN:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
            "flashloan admin account length differs from pinned IDL",
        )
    if raw[:8] != FLASHLOAN_ADMIN_DISCRIMINATOR:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
            "flashloan admin discriminator differs from pinned IDL",
        )
    offset = 8
    authority = Pubkey.from_bytes(raw[offset : offset + 32])
    offset += 32
    liquidity_program = Pubkey.from_bytes(raw[offset : offset + 32])
    offset += 32
    status = _decode_bool(raw[offset], "status")
    offset += 1
    flashloan_fee = int.from_bytes(raw[offset : offset + 2], "little")
    offset += 2
    flashloan_timestamp = int.from_bytes(raw[offset : offset + 8], "little")
    offset += 8
    is_flashloan_active = _decode_bool(raw[offset], "is_flashloan_active")
    offset += 1
    active_flashloan_amount = int.from_bytes(raw[offset : offset + 8], "little")
    offset += 8
    bump = raw[offset]
    return JupiterLendFlashloanAdminState(
        authority=authority,
        liquidity_program=liquidity_program,
        status=status,
        flashloan_fee=flashloan_fee,
        flashloan_timestamp=flashloan_timestamp,
        is_flashloan_active=is_flashloan_active,
        active_flashloan_amount=active_flashloan_amount,
        bump=bump,
    )


# ---------------------------------------------------------------------------
# R02-CAP-A read-only TokenReserve capacity reader (offline, fail-closed).
#
# Pinned upstream (docs/roadmap/r02-capacity-recovery-2026-10-08):
# - Liquidity IDL: jup-ag/jupiter-lend@a484ddcf9b34ef6f6d575ad10b0673a18d9c8f31,
#   target/idl/liquidity.json blob 09209f553900df7da61f84a106ad85767fdac71d,
#   version 0.1.8. TokenReserve: 8-byte Anchor discriminator, 17 fixed fields,
#   exact decoded length 192 (offline/jupiter_token_reserve_layout.json).
# - TokenReserve PDA seeds [b"reserve", mint_pubkey] with the Liquidity program
#   id, per Instadapp/fluid-solana-programs@626b177f235224bc5d074d39439cd2558f542886
#   ts-sdk/liquidity/context/pda.ts get_reserve(mint) (R02_UNBLOCK_MATRIX.md;
#   read-only reference, BSL-1.1 upstream, not vendored).
#
# Scope: R02-STRUCT only. Capacity is derived from actual decoded resource
# state (never TVL, never off-chain asset lists, never admin flags), but the
# effective flash borrow cap requires audited program math for utilization
# scales, exchange-price valuation, claim semantics and the flash borrow
# position debt ceiling that this pinned layout does not prove. Those fields
# are therefore reported raw, and the observation carries typed blockers;
# unknown is not zero. Zero network, zero signing, zero sending.
# ---------------------------------------------------------------------------

JUPITER_LEND_LIQUIDITY_UPSTREAM_COMMIT = "a484ddcf9b34ef6f6d575ad10b0673a18d9c8f31"
JUPITER_LEND_LIQUIDITY_IDL_NAME = "liquidity"
JUPITER_LEND_LIQUIDITY_IDL_BLOB = "09209f553900df7da61f84a106ad85767fdac71d"
JUPITER_LEND_LIQUIDITY_IDL_VERSION = "0.1.8"
JUPITER_LEND_LIQUIDITY_PROGRAM_ID = Pubkey.from_string(
    "jupeiUmn818Jg1ekPURTpr4mFo29p46vygyykFJ3wZC"
)
JUPITER_TOKEN_RESERVE_SEED = b"reserve"
JUPITER_TOKEN_RESERVE_SEED_SOURCE = (
    "Instadapp/fluid-solana-programs@"
    "626b177f235224bc5d074d39439cd2558f542886"
    " ts-sdk/liquidity/context/pda.ts get_reserve(mint)"
)
TOKEN_RESERVE_DISCRIMINATOR = bytes((21, 18, 59, 135, 120, 20, 31, 12))
TOKEN_RESERVE_ACCOUNT_LEN = 192
SPL_TOKEN_PROGRAM_ID = Pubkey.from_string(
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
)
SPL_TOKEN_2022_PROGRAM_ID = Pubkey.from_string(
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
)
SPL_TOKEN_ACCOUNT_LEN = 165
READER_DECODER_IDENTITY = "jupiter-lend.tokenreserve.capacity-reader.v1"
READER_DECODER_GENERATION = 1
READER_EXECUTION_AUTHORITY = "NONE"

_ZERO_PUBKEY = Pubkey.from_bytes(bytes(32))
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Raw token amounts decoded from resource state (exact sums of decoded u64
# fields) are recorded with UNAUDITED_SEMANTICS markers: their exchange-price
# valuation and claim semantics are not pinned, so they are never capacity.

_UNPINNED_CAPACITY_GAPS: tuple[str, ...] = (
    "UTILIZATION_SCALE_UNPINNED",
    "MAX_UTILIZATION_SEMANTICS_UNPINNED",
    "EXCHANGE_PRICE_VALUATION_UNAUDITED",
    "FLASH_BORROW_POSITION_DEBT_CEILING_UNDECODED",
    "FEE_ROUNDING_RULE_UNPINNED",
    "TOTAL_CLAIM_SEMANTICS_UNPINNED",
    "VAULT_AUTHORITY_BINDING_UNPROVEN",
)


class JupiterLendCapacityDerivation(StrEnum):
    """How an effective capacity value was proven. Only UNPROVEN exists today.

    A future live reader must add an explicit proven-derivation member and a
    pinned deployed-source proof before any integer effective capacity may be
    carried. Until then, carrying an effective capacity is structurally
    impossible (enforced in JupiterLendReserveCapacityObservation).
    """

    UNPROVEN = "R02CAPA_CAPACITY_DERIVATION_UNPROVEN"


class JupiterLendSlotProvenance(StrEnum):
    OFFLINE_FIXTURE_NOT_ROOTED = "OFFLINE_FIXTURE_NOT_ROOTED"
    LIVE_ROOTED_RPC = "LIVE_ROOTED_RPC"


def derive_token_reserve_pda(mint: Pubkey) -> tuple[Pubkey, int]:
    """Canonical TokenReserve PDA from pinned seeds [b"reserve", mint]."""

    if bytes(mint) == bytes(_ZERO_PUBKEY):
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.CAPACITY_STATE_INVALID,
            "zero mint cannot bind a TokenReserve PDA",
        )
    return Pubkey.find_program_address(
        [JUPITER_TOKEN_RESERVE_SEED, bytes(mint)],
        JUPITER_LEND_LIQUIDITY_PROGRAM_ID,
    )


@dataclass(frozen=True, slots=True)
class JupiterLendTokenReserveState:
    """Exact 192-byte/17-field TokenReserve decode from the pinned IDL."""

    mint: Pubkey
    vault: Pubkey
    borrow_rate: int
    fee_on_interest: int
    last_utilization: int
    last_update_timestamp: int
    supply_exchange_price: int
    borrow_exchange_price: int
    max_utilization: int
    total_supply_with_interest: int
    total_supply_interest_free: int
    total_borrow_with_interest: int
    total_borrow_interest_free: int
    total_claim_amount: int
    interacting_protocol: Pubkey
    interacting_timestamp: int
    interacting_balance: int


def _decode_u16(raw: bytes, offset: int, label: str) -> int:
    if len(raw) < offset + 2:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.TOKEN_RESERVE_LAYOUT_MISMATCH,
            f"truncated TokenReserve field {label}",
        )
    return int.from_bytes(raw[offset : offset + 2], "little")


def _decode_u64(raw: bytes, offset: int, label: str) -> int:
    if len(raw) < offset + 8:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.TOKEN_RESERVE_LAYOUT_MISMATCH,
            f"truncated TokenReserve field {label}",
        )
    return int.from_bytes(raw[offset : offset + 8], "little")


def decode_token_reserve_state(
    data: bytes,
    *,
    owner: Pubkey,
    address: Pubkey,
) -> JupiterLendTokenReserveState:
    """Fail-closed decode of one caller-supplied TokenReserve account.

    ``owner`` is the observed on-chain account owner program and ``address``
    the observed account address; both must match the pinned Liquidity program
    and the canonical [b"reserve", mint] PDA exactly. Any unknown byte range
    (longer account), truncated account, wrong discriminator or wrong owner
    fails closed instead of decoding a prefix.
    """

    raw = bytes(data)
    if len(raw) < TOKEN_RESERVE_ACCOUNT_LEN:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.TOKEN_RESERVE_LAYOUT_MISMATCH,
            "TokenReserve account is shorter than the pinned 192-byte layout",
        )
    if len(raw) > TOKEN_RESERVE_ACCOUNT_LEN:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.TOKEN_RESERVE_UNKNOWN_FIELD,
            "TokenReserve account carries bytes outside the pinned layout",
        )
    if raw[:8] != TOKEN_RESERVE_DISCRIMINATOR:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.TOKEN_RESERVE_UNKNOWN_DISCRIMINATOR,
            "TokenReserve discriminator differs from pinned IDL 0.1.8",
        )
    if owner != JUPITER_LEND_LIQUIDITY_PROGRAM_ID:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.TOKEN_RESERVE_OWNER_MISMATCH,
            "TokenReserve owner differs from the pinned Liquidity program",
        )
    state = JupiterLendTokenReserveState(
        mint=Pubkey.from_bytes(raw[8:40]),
        vault=Pubkey.from_bytes(raw[40:72]),
        borrow_rate=_decode_u16(raw, 72, "borrow_rate"),
        fee_on_interest=_decode_u16(raw, 74, "fee_on_interest"),
        last_utilization=_decode_u16(raw, 76, "last_utilization"),
        last_update_timestamp=_decode_u64(raw, 78, "last_update_timestamp"),
        supply_exchange_price=_decode_u64(raw, 86, "supply_exchange_price"),
        borrow_exchange_price=_decode_u64(raw, 94, "borrow_exchange_price"),
        max_utilization=_decode_u16(raw, 102, "max_utilization"),
        total_supply_with_interest=_decode_u64(raw, 104, "total_supply_with_interest"),
        total_supply_interest_free=_decode_u64(raw, 112, "total_supply_interest_free"),
        total_borrow_with_interest=_decode_u64(raw, 120, "total_borrow_with_interest"),
        total_borrow_interest_free=_decode_u64(raw, 128, "total_borrow_interest_free"),
        total_claim_amount=_decode_u64(raw, 136, "total_claim_amount"),
        interacting_protocol=Pubkey.from_bytes(raw[144:176]),
        interacting_timestamp=_decode_u64(raw, 176, "interacting_timestamp"),
        interacting_balance=_decode_u64(raw, 184, "interacting_balance"),
    )
    expected_address, _ = derive_token_reserve_pda(state.mint)
    if address != expected_address:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.TOKEN_RESERVE_PDA_MISMATCH,
            "TokenReserve address is not the canonical [reserve, mint] PDA "
            "of the pinned Liquidity program",
        )
    if state.mint == _ZERO_PUBKEY:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.CAPACITY_STATE_INVALID,
            "decoded TokenReserve mint is zero; reserve is not initialized",
        )
    return state


@dataclass(frozen=True, slots=True)
class JupiterLendVaultTokenAccountState:
    """Exact 165-byte SPL token account decode of the reserve vault."""

    address: Pubkey
    owner_program: Pubkey
    mint: Pubkey
    authority: Pubkey
    amount: int
    account_state: int
    is_native: bool
    delegated_amount: int
    delegate: Pubkey | None = None
    close_authority: Pubkey | None = None


def decode_vault_token_account(
    data: bytes,
    *,
    address: Pubkey,
    owner_program: Pubkey,
    expected_mint: Pubkey,
) -> JupiterLendVaultTokenAccountState:
    """Fail-closed decode of the reserve vault SPL token account.

    The vault must bind the reserve mint exactly; delegation, close authority
    and unknown account states fail closed because they can silently change
    which party may move the reserve resource.
    """

    raw = bytes(data)
    if len(raw) != SPL_TOKEN_ACCOUNT_LEN:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.VAULT_LAYOUT_MISMATCH,
            "vault token account length differs from the 165-byte SPL layout",
        )
    if owner_program not in (SPL_TOKEN_PROGRAM_ID, SPL_TOKEN_2022_PROGRAM_ID):
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.VAULT_TOKEN_PROGRAM_MISMATCH,
            "vault owner program is not a pinned SPL token program",
        )
    mint = Pubkey.from_bytes(raw[0:32])
    if mint != expected_mint:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.VAULT_MINT_BINDING_MISMATCH,
            "vault token account mint differs from the reserve mint",
        )
    delegate_tag = int.from_bytes(raw[72:76], "little")
    if delegate_tag != 0:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.VAULT_DELEGATE_UNPROVEN,
            "vault carries an unproven delegate authority",
        )
    account_state = raw[108]
    if account_state == 2:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.VAULT_FROZEN,
            "vault token account is frozen",
        )
    if account_state != 1:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.CAPACITY_STATE_INVALID,
            "vault token account state is unknown",
        )
    is_native_tag = int.from_bytes(raw[109:113], "little")
    close_tag = int.from_bytes(raw[129:133], "little")
    if close_tag != 0:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.VAULT_CLOSE_AUTHORITY_UNPROVEN,
            "vault carries an unproven close authority",
        )
    return JupiterLendVaultTokenAccountState(
        address=address,
        owner_program=owner_program,
        mint=mint,
        authority=Pubkey.from_bytes(raw[32:64]),
        amount=int.from_bytes(raw[64:72], "little"),
        account_state=account_state,
        is_native=is_native_tag != 0,
        delegated_amount=int.from_bytes(raw[121:129], "little"),
        delegate=None,
        close_authority=None,
    )


@dataclass(frozen=True, slots=True)
class JupiterLendReserveCapacityObservation:
    """Typed read-only capacity observation for one TokenReserve resource.

    ``raw_vault_amount_base_units`` is the only amount proven from actual
    resource state (the decoded vault SPL balance). ``effective_capacity``
    stays ``None`` while the derivation is UNPROVEN: unknown is not zero.
    """

    mint: str
    reserve_pda: str
    reserve_owner: str
    state: JupiterLendTokenReserveState
    vault: JupiterLendVaultTokenAccountState
    reserve_data_sha256: str
    vault_data_sha256: str
    raw_vault_amount_base_units: int
    raw_total_supply_base_units: int
    raw_total_borrow_base_units: int
    capacity_derivation: JupiterLendCapacityDerivation
    effective_capacity_base_units: int | None
    constraint_gaps: tuple[str, ...]
    blockers: tuple[str, ...]
    mint_decimals: int | None = None
    slot: int | None = None
    slot_rooted: bool = False
    slot_provenance: str = JupiterLendSlotProvenance.OFFLINE_FIXTURE_NOT_ROOTED.value
    fee_rounding: str = "UNPINNED"
    decoder_identity: str = READER_DECODER_IDENTITY
    decoder_generation: int = READER_DECODER_GENERATION
    execution_authority: str = READER_EXECUTION_AUTHORITY
    sign_enabled: bool = False
    send_enabled: bool = False

    def __post_init__(self) -> None:
        for name in ("mint", "reserve_pda", "reserve_owner"):
            value = getattr(self, name)
            try:
                Pubkey.from_string(value)
            except Exception as exc:
                raise ValueError(f"{name} is not a base58 pubkey") from exc
        for name in ("reserve_data_sha256", "vault_data_sha256"):
            if not _SHA256_RE.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be lowercase sha256")
        if type(self.raw_vault_amount_base_units) is not int:
            raise ValueError("raw vault amount must be an integer")
        if self.capacity_derivation is JupiterLendCapacityDerivation.UNPROVEN:
            if self.effective_capacity_base_units is not None:
                raise ValueError(
                    "effective capacity without proven derivation is forbidden; "
                    "unknown is not zero"
                )
            if "MISSING_EFFECTIVE_FLASH_CAP" not in self.blockers:
                raise ValueError(
                    "unproven capacity must carry MISSING_EFFECTIVE_FLASH_CAP"
                )
            if not self.constraint_gaps:
                raise ValueError("unproven capacity must enumerate constraint gaps")
        if not self.slot_rooted:
            if self.slot is not None:
                raise ValueError("unrooted observation cannot claim a slot")
            if self.slot_provenance != JupiterLendSlotProvenance.OFFLINE_FIXTURE_NOT_ROOTED:
                raise ValueError("unrooted observation must use offline provenance")
            if "LIVE_ROOTED_RPC_NOT_AUTHORIZED" not in self.blockers:
                raise ValueError(
                    "unrooted observation must carry LIVE_ROOTED_RPC_NOT_AUTHORIZED"
                )
        else:
            if (
                self.slot is None
                or type(self.slot) is not int
                or self.slot < 0
                or self.slot_provenance != JupiterLendSlotProvenance.LIVE_ROOTED_RPC.value
            ):
                raise ValueError("rooted observation requires an integer rooted slot")
        if self.status not in ("PARTIAL_DECODED", "BLOCKED_LIVE_STATE"):
            raise ValueError("unknown observation status")

    @property
    def status(self) -> str:
        return "BLOCKED_LIVE_STATE" if self.blockers else "PARTIAL_DECODED"

    @property
    def evidence_digest(self) -> str:
        return hashlib.sha256(_canonical_json(self).encode("utf-8")).hexdigest()

    def evidence_record(self) -> dict:
        return {
            "decoder_identity": self.decoder_identity,
            "decoder_generation": self.decoder_generation,
            "evidence_sha256": self.evidence_digest,
            "status": self.status,
            "observation": json.loads(_canonical_json(self)),
        }


def _canonical_json(value: object) -> str:
    def normalize(node: object) -> object:
        if is_dataclass(node) and not isinstance(node, type):
            return {
                field.name: normalize(getattr(node, field.name))
                for field in dataclass_fields(node)
            }
        if isinstance(node, Pubkey):
            return str(node)
        if isinstance(node, StrEnum):
            return str(node.value)
        if isinstance(node, (tuple, list)):
            return [normalize(item) for item in node]
        if isinstance(node, dict):
            return {key: normalize(item) for key, item in node.items()}
        return node

    return json.dumps(
        normalize(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def observe_token_reserve_capacity(
    *,
    mint: Pubkey,
    reserve_bytes: bytes,
    reserve_owner: Pubkey,
    reserve_address: Pubkey,
    vault_bytes: bytes,
    vault_address: Pubkey,
    vault_owner_program: Pubkey,
    mint_decimals: int | None = None,
) -> JupiterLendReserveCapacityObservation:
    """Decode reserve + vault offline and return typed capacity evidence.

    Every input is caller-supplied (offline fixture or, in a later authorized
    wave, a live rooted read). No network, no signing, no account creation.
    """

    state = decode_token_reserve_state(
        reserve_bytes, owner=reserve_owner, address=reserve_address
    )
    if state.mint != mint:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.TOKEN_RESERVE_MINT_BINDING_MISMATCH,
            "reviewed mint differs from the decoded TokenReserve mint",
        )
    if state.vault != vault_address:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.VAULT_ADDRESS_BINDING_MISMATCH,
            "observed vault address differs from the decoded reserve vault",
        )
    vault = decode_vault_token_account(
        vault_bytes,
        address=vault_address,
        owner_program=vault_owner_program,
        expected_mint=mint,
    )
    if mint_decimals is not None and (
        type(mint_decimals) is not int or not 0 <= mint_decimals <= 255
    ):
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.CAPACITY_STATE_INVALID,
            "mint decimals must be an integer in [0, 255] when supplied",
        )
    if state.interacting_protocol != _ZERO_PUBKEY:
        if state.interacting_balance == 0 and state.interacting_timestamp == 0:
            raise JupiterLendAdapterError(
                JupiterLendCapacityRejectionCode.CAPACITY_STATE_INVALID,
                "interacting protocol set without interacting state",
            )
    elif state.interacting_balance != 0 or state.interacting_timestamp != 0:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.CAPACITY_STATE_INVALID,
            "interacting state set without an interacting protocol",
        )
    gaps = list(_UNPINNED_CAPACITY_GAPS)
    if mint_decimals is None:
        gaps.append("MINT_DECIMALS_UNPROVEN")
    if state.interacting_protocol != _ZERO_PUBKEY:
        gaps.append(JupiterLendCapacityRejectionCode.TOKEN_RESERVE_INTERACTING.value)
    blockers = [
        JupiterLendCapacityRejectionCode.MISSING_EFFECTIVE_FLASH_CAP.value,
        JupiterLendCapacityRejectionCode.LIVE_ROOTED_RPC_NOT_AUTHORIZED.value,
    ]
    return JupiterLendReserveCapacityObservation(
        mint=str(mint),
        reserve_pda=str(reserve_address),
        reserve_owner=str(reserve_owner),
        state=state,
        vault=vault,
        reserve_data_sha256=hashlib.sha256(bytes(reserve_bytes)).hexdigest(),
        vault_data_sha256=hashlib.sha256(bytes(vault_bytes)).hexdigest(),
        raw_vault_amount_base_units=vault.amount,
        raw_total_supply_base_units=(
            state.total_supply_with_interest + state.total_supply_interest_free
        ),
        raw_total_borrow_base_units=(
            state.total_borrow_with_interest + state.total_borrow_interest_free
        ),
        capacity_derivation=JupiterLendCapacityDerivation.UNPROVEN,
        effective_capacity_base_units=None,
        constraint_gaps=tuple(sorted(gaps)),
        blockers=tuple(sorted(blockers)),
        mint_decimals=mint_decimals,
    )


@dataclass(frozen=True, slots=True)
class JupiterLendFinancingAdmission:
    """Typed outcome of wiring an observation into the financing snapshot port."""

    observation_digest: str
    snapshot: object | None
    available_liquidity_base_units: int | None
    blockers: tuple[str, ...]


def admit_reserve_financing_snapshot(
    *,
    observation: JupiterLendReserveCapacityObservation,
    accounts: JupiterLendFlashloanAccounts,
    admin_state: JupiterLendFlashloanAdminState,
    asset_id: str,
    state_fingerprint: str,
) -> JupiterLendFinancingAdmission:
    """Bind a capacity observation to JupiterLendFinancingSnapshot fail-closed.

    The snapshot's ``available_liquidity_base_units`` may only come from a
    proven effective capacity. Offline the admission is therefore typed
    BLOCKED with unknown (``None``), never zero, liquidity.
    """

    from src.lending.agg03_financing_ports import (
        JupiterLendFinancingPort,
        JupiterLendFinancingSnapshot,
    )

    blockers: list[str] = list(observation.blockers)
    if str(accounts.mint) != observation.mint:
        blockers.append(
            JupiterLendCapacityRejectionCode.FINANCING_MINT_BINDING_MISMATCH.value
        )
    if str(accounts.flashloan_token_reserves_liquidity) != observation.reserve_pda:
        blockers.append(
            JupiterLendCapacityRejectionCode.FINANCING_RESERVE_BINDING_MISMATCH.value
        )
    if str(accounts.vault) != str(observation.vault.address):
        blockers.append(
            JupiterLendCapacityRejectionCode.FINANCING_VAULT_BINDING_MISMATCH.value
        )
    if str(accounts.liquidity_program) != observation.reserve_owner:
        blockers.append(
            JupiterLendCapacityRejectionCode.FINANCING_LIQUIDITY_PROGRAM_MISMATCH.value
        )
    if not admin_state.status:
        blockers.append("JUPITER_LEND_PROTOCOL_PAUSED")
    if admin_state.is_flashloan_active:
        blockers.append("JUPITER_LEND_FLASHLOAN_ALREADY_ACTIVE")
    if admin_state.active_flashloan_amount != 0:
        blockers.append("JUPITER_LEND_ACTIVE_AMOUNT_NOT_ZERO")
    if admin_state.flashloan_fee != 0:
        blockers.append("JUPITER_LEND_NONZERO_FEE_UNQUALIFIED")

    digest = observation.evidence_digest
    if blockers:
        return JupiterLendFinancingAdmission(
            observation_digest=digest,
            snapshot=None,
            available_liquidity_base_units=None,
            blockers=tuple(sorted(set(blockers))),
        )
    effective = observation.effective_capacity_base_units
    if type(effective) is not int or effective <= 0 or observation.slot is None:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.MISSING_EFFECTIVE_FLASH_CAP,
            "qualified admission requires proven positive capacity and a slot",
        )
    evidence = FinancingEvidence(
        lender_id="jupiter-lend",
        program_id=str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID),
        deployment_generation=1,
        evidence_sha256=digest,
        decoder_identity=observation.decoder_identity,
        decoder_generation=observation.decoder_generation,
    )
    if evidence.lender_id != JupiterLendFinancingPort.lender_id:
        raise JupiterLendAdapterError(
            JupiterLendCapacityRejectionCode.FINANCING_LIQUIDITY_PROGRAM_MISMATCH,
            "lender identity drift between reader and financing port",
        )
    snapshot = JupiterLendFinancingSnapshot(
        accounts=accounts,
        admin_state=admin_state,
        asset_id=asset_id,
        available_liquidity_base_units=effective,
        required_repayment_base_units=effective,
        slot=observation.slot,
        evidence_sha256=digest,
        state_fingerprint=state_fingerprint,
        monitored_accounts=(observation.mint, observation.reserve_pda),
    )
    return JupiterLendFinancingAdmission(
        observation_digest=digest,
        snapshot=snapshot,
        available_liquidity_base_units=effective,
        blockers=(),
    )


@dataclass(frozen=True, slots=True)
class JupiterLendCapitalEdgeGate:
    """Capacity-edge emission verdict; ``edge`` is None until fully proven."""

    edge: None
    blocker: str
    blockers: tuple[str, ...]
    note: str


def reserve_capital_edge_gate(
    observation: JupiterLendReserveCapacityObservation,
) -> JupiterLendCapitalEdgeGate:
    """Gate edge emission behind rooted-RPC proof and the frozen graph owner.

    The FlashCapitalGraph whitelist (frozen this wave) does not accept a
    Jupiter Lend provider, and CAP-A requires full evidence plus independent
    quorum before a narrow allowance. This gate therefore never returns an
    edge; it returns the typed blocker that still applies.
    """

    if "LIVE_ROOTED_RPC_NOT_AUTHORIZED" in observation.blockers:
        return JupiterLendCapitalEdgeGate(
            edge=None,
            blocker="LIVE_ROOTED_RPC_NOT_AUTHORIZED",
            blockers=observation.blockers,
            note=(
                "no live rooted-RPC snapshot with independent quorum was "
                "authorized; offline fixture evidence never qualifies an edge"
            ),
        )
    if observation.effective_capacity_base_units is None:
        return JupiterLendCapitalEdgeGate(
            edge=None,
            blocker="MISSING_EFFECTIVE_FLASH_CAP",
            blockers=observation.blockers,
            note="effective flash borrow cap is unknown, not zero",
        )
    return JupiterLendCapitalEdgeGate(
        edge=None,
        blocker=(
            JupiterLendCapacityRejectionCode.GRAPH_ALLOWANCE_PENDING.value
        ),
        blockers=observation.blockers,
        note=(
            "FlashCapitalGraph provider allowance for jupiter-lend requires "
            "full evidence and independent quorum; graph owner is frozen"
        ),
    )


@dataclass(frozen=True, slots=True)
class JupiterLendOrderCertificate:
    borrow_index: int
    payback_index: int
    amount: int


def _encode_amount(amount: int) -> bytes:
    if type(amount) is not int or not 0 < amount <= _U64_MAX:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.INVALID_AMOUNT,
            "flashloan amount must be a positive u64",
        )
    return amount.to_bytes(8, "little", signed=False)


def build_flashloan_borrow_instruction(
    accounts: JupiterLendFlashloanAccounts,
    amount: int,
) -> Instruction:
    return Instruction(
        JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
        FLASHLOAN_BORROW_DISCRIMINATOR + _encode_amount(amount),
        accounts.metas(),
    )


def build_flashloan_payback_instruction(
    accounts: JupiterLendFlashloanAccounts,
    amount: int,
) -> Instruction:
    return Instruction(
        JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
        FLASHLOAN_PAYBACK_DISCRIMINATOR + _encode_amount(amount),
        accounts.metas(),
    )


def _decode_amount(instruction: Instruction, discriminator: bytes) -> int:
    data = bytes(instruction.data)
    if len(data) != 16 or not data.startswith(discriminator):
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.ORDER_INVARIANT,
            "instruction data does not match pinned Jupiter Lend flashloan ABI",
        )
    amount = int.from_bytes(data[8:], "little", signed=False)
    if amount <= 0:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.INVALID_AMOUNT,
            "decoded flashloan amount must be positive",
        )
    return amount


def _account_fingerprint(
    instruction: Instruction,
) -> tuple[tuple[Pubkey, bool, bool], ...]:
    return tuple(
        (meta.pubkey, meta.is_signer, meta.is_writable) for meta in instruction.accounts
    )


def _validate_account_shape(instruction: Instruction) -> None:
    accounts = tuple(instruction.accounts)
    if len(accounts) != len(_EXPECTED_META_FLAGS):
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.ACCOUNT_MISMATCH,
            "flashloan instruction must contain exactly 14 ordered account metas",
        )

    actual_flags = tuple((meta.is_signer, meta.is_writable) for meta in accounts)
    if actual_flags != _EXPECTED_META_FLAGS:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.ACCOUNT_MISMATCH,
            "flashloan account signer/writable flags differ from pinned IDL",
        )

    fixed = (
        (1, JUPITER_FLASHLOAN_ADMIN_PDA, "flashloan_admin"),
        (11, ASSOCIATED_TOKEN_PROGRAM_ID, "associated_token_program"),
        (12, SYSTEM_PROGRAM_ID, "system_program"),
        (13, INSTRUCTIONS_SYSVAR_ID, "instruction_sysvar"),
    )
    for index, expected, label in fixed:
        if accounts[index].pubkey != expected:
            raise JupiterLendAdapterError(
                JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
                f"{label} differs from pinned IDL",
            )


def validate_jupiter_lend_order(
    instructions: Sequence[Instruction],
) -> JupiterLendOrderCertificate:
    """Require one ABI-valid, account-bound Borrow before matching Payback."""

    borrow: list[tuple[int, int, tuple[tuple[Pubkey, bool, bool], ...]]] = []
    payback: list[tuple[int, int, tuple[tuple[Pubkey, bool, bool], ...]]] = []
    for index, instruction in enumerate(instructions):
        if instruction.program_id != JUPITER_LEND_FLASHLOAN_PROGRAM_ID:
            continue
        data = bytes(instruction.data)
        if data.startswith(FLASHLOAN_BORROW_DISCRIMINATOR):
            _validate_account_shape(instruction)
            borrow.append(
                (
                    index,
                    _decode_amount(
                        instruction,
                        FLASHLOAN_BORROW_DISCRIMINATOR,
                    ),
                    _account_fingerprint(instruction),
                )
            )
        elif data.startswith(FLASHLOAN_PAYBACK_DISCRIMINATOR):
            _validate_account_shape(instruction)
            payback.append(
                (
                    index,
                    _decode_amount(
                        instruction,
                        FLASHLOAN_PAYBACK_DISCRIMINATOR,
                    ),
                    _account_fingerprint(instruction),
                )
            )

    if len(borrow) != 1 or len(payback) != 1:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.ORDER_INVARIANT,
            "exactly one Jupiter Lend Borrow and Payback are required",
        )
    if borrow[0][0] >= payback[0][0]:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.ORDER_INVARIANT,
            "Jupiter Lend Payback must succeed Borrow",
        )
    if borrow[0][1] != payback[0][1]:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.AMOUNT_MISMATCH,
            "Borrow and Payback amount arguments differ",
        )
    if borrow[0][2] != payback[0][2]:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.ACCOUNT_MISMATCH,
            "Borrow and Payback must bind the same ordered account metas",
        )
    return JupiterLendOrderCertificate(
        borrow_index=borrow[0][0],
        payback_index=payback[0][0],
        amount=borrow[0][1],
    )


__all__ = [
    "ASSOCIATED_TOKEN_PROGRAM_ID",
    "FLASHLOAN_ADMIN_ACCOUNT_LEN",
    "FLASHLOAN_ADMIN_DISCRIMINATOR",
    "FLASHLOAN_BORROW_DISCRIMINATOR",
    "FLASHLOAN_PAYBACK_DISCRIMINATOR",
    "INSTRUCTIONS_SYSVAR_ID",
    "JUPITER_FLASHLOAN_ADMIN_BUMP",
    "JUPITER_FLASHLOAN_ADMIN_PDA",
    "JUPITER_FLASHLOAN_ADMIN_SEED",
    "JUPITER_LEND_FLASHLOAN_IDL_BLOB",
    "JUPITER_LEND_FLASHLOAN_IDL_VERSION",
    "JUPITER_LEND_FLASHLOAN_PROGRAM_ID",
    "JUPITER_LEND_LIQUIDITY_IDL_BLOB",
    "JUPITER_LEND_LIQUIDITY_IDL_NAME",
    "JUPITER_LEND_LIQUIDITY_IDL_VERSION",
    "JUPITER_LEND_LIQUIDITY_PROGRAM_ID",
    "JUPITER_LEND_LIQUIDITY_UPSTREAM_COMMIT",
    "JUPITER_LEND_UPSTREAM_COMMIT",
    "JUPITER_LEND_UPSTREAM_REPOSITORY",
    "JUPITER_TOKEN_RESERVE_SEED",
    "JUPITER_TOKEN_RESERVE_SEED_SOURCE",
    "READER_DECODER_GENERATION",
    "READER_DECODER_IDENTITY",
    "READER_EXECUTION_AUTHORITY",
    "SPL_TOKEN_2022_PROGRAM_ID",
    "SPL_TOKEN_ACCOUNT_LEN",
    "SPL_TOKEN_PROGRAM_ID",
    "SYSTEM_PROGRAM_ID",
    "TOKEN_RESERVE_ACCOUNT_LEN",
    "TOKEN_RESERVE_DISCRIMINATOR",
    "JupiterLendAdapterError",
    "JupiterLendCapacityDerivation",
    "JupiterLendCapacityRejectionCode",
    "JupiterLendCapitalEdgeGate",
    "JupiterLendFinancingAdmission",
    "JupiterLendFlashloanAccounts",
    "JupiterLendFlashloanAdminState",
    "JupiterLendOrderCertificate",
    "JupiterLendRejectionCode",
    "JupiterLendReserveCapacityObservation",
    "JupiterLendSlotProvenance",
    "JupiterLendTokenReserveState",
    "JupiterLendVaultTokenAccountState",
    "admit_reserve_financing_snapshot",
    "build_flashloan_borrow_instruction",
    "build_flashloan_payback_instruction",
    "decode_flashloan_admin_state",
    "decode_token_reserve_state",
    "decode_vault_token_account",
    "derive_token_reserve_pda",
    "observe_token_reserve_capacity",
    "reserve_capital_edge_gate",
    "validate_jupiter_lend_order",
]
