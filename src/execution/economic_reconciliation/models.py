"""Immutable PR-037 economic-reconciliation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.config.chain_registry import TOKEN_2022_PROGRAM_ADDRESS, TOKEN_PROGRAM_ADDRESS
from src.domain.money import NATIVE_SOL_MINT

NATIVE_PROGRAM = "native"
NATIVE_DECIMALS = 9
MARGINFI_ACCOUNT_IN_FLASHLOAN = 1 << 1
SUPPORTED_TOKEN_PROGRAMS = frozenset(
    {TOKEN_PROGRAM_ADDRESS, TOKEN_2022_PROGRAM_ADDRESS}
)


class ReconciliationStatus(str, Enum):
    PROVEN_PROFIT = "proven_profit"
    PROVEN_LOSS = "proven_loss"
    REPAYMENT_FAILED = "repayment_failed"
    INDETERMINATE = "indeterminate"


class ReconciliationReason(str, Enum):
    RECONCILED_PROFIT = "reconciled_profit"
    RECONCILED_LOSS = "reconciled_loss"
    SIMULATION_FAILED = "simulation_failed"
    MESSAGE_HASH_MISMATCH = "message_hash_mismatch"
    EVIDENCE_HASH_INVALID = "evidence_hash_invalid"
    SLOT_MISMATCH = "slot_mismatch"
    DUPLICATE_ACCOUNT = "duplicate_account"
    REQUIRED_ACCOUNT_MISSING = "required_account_missing"
    ACCOUNT_STATE_MISSING = "account_state_missing"
    ACCOUNT_IDENTITY_MISMATCH = "account_identity_mismatch"
    ACCOUNT_OWNER_CHANGED = "account_owner_changed"
    TOKEN_PROGRAM_UNSUPPORTED = "token_program_unsupported"
    TOKEN_EXTENSION_UNSUPPORTED = "token_extension_unsupported"
    TOKEN_METADATA_MISMATCH = "token_metadata_mismatch"
    FEE_EVIDENCE_INVALID = "fee_evidence_invalid"
    SETTLEMENT_ASSET_MISSING = "settlement_asset_missing"
    MARGINFI_EVIDENCE_MISSING = "marginfi_evidence_missing"
    MARGINFI_OWNER_MISMATCH = "marginfi_owner_mismatch"
    MARGINFI_STATE_INVALID = "marginfi_state_invalid"
    MARGINFI_VAULT_MISMATCH = "marginfi_vault_mismatch"
    REPAYMENT_NOT_PROVEN = "repayment_not_proven"
    DECOMPOSITION_MISMATCH = "decomposition_mismatch"


class AccountLifecycle(str, Enum):
    STABLE = "stable"
    CREATED = "created"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True, order=True)
class AssetKey:
    mint: str
    token_program: str
    decimals: int

    def __post_init__(self) -> None:
        if not self.mint or not self.token_program:
            raise ValueError("asset identity is incomplete")
        if isinstance(self.decimals, bool) or not isinstance(self.decimals, int):
            raise ValueError("asset decimals must be an integer")
        if not 0 <= self.decimals <= 255:
            raise ValueError("asset decimals outside u8 range")

    @property
    def is_native(self) -> bool:
        return self == NATIVE_SOL_ASSET

    def stable_id(self) -> str:
        return f"{self.token_program}:{self.mint}:{self.decimals}"


NATIVE_SOL_ASSET = AssetKey(NATIVE_SOL_MINT, NATIVE_PROGRAM, NATIVE_DECIMALS)


@dataclass(frozen=True, slots=True)
class AssetQuantity:
    asset: AssetKey
    base_units: int

    def __post_init__(self) -> None:
        non_negative(self.base_units, "base_units")


@dataclass(frozen=True, slots=True)
class NativeState:
    address: str
    owner: str
    lamports: int
    slot: int

    def __post_init__(self) -> None:
        if not self.address or not self.owner:
            raise ValueError("native account identity is incomplete")
        non_negative(self.lamports, "lamports")
        positive(self.slot, "slot")


@dataclass(frozen=True, slots=True)
class TokenState:
    address: str
    program_owner: str
    authority: str
    asset: AssetKey
    amount: int
    account_lamports: int
    slot: int
    extensions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.address or not self.program_owner or not self.authority:
            raise ValueError("token account identity is incomplete")
        non_negative(self.amount, "amount")
        non_negative(self.account_lamports, "account_lamports")
        positive(self.slot, "slot")
        normalized = tuple(
            sorted(
                {value.strip().lower() for value in self.extensions if value.strip()}
            )
        )
        object.__setattr__(self, "extensions", normalized)


@dataclass(frozen=True, slots=True)
class NativeObservation:
    address: str
    pre: NativeState | None
    post: NativeState | None
    lifecycle: AccountLifecycle = AccountLifecycle.STABLE
    include_in_wallet_delta: bool = True


@dataclass(frozen=True, slots=True)
class TokenObservation:
    address: str
    authority: str
    asset: AssetKey
    pre: TokenState | None
    post: TokenState | None
    lifecycle: AccountLifecycle = AccountLifecycle.STABLE
    include_in_wallet_delta: bool = True


@dataclass(frozen=True, slots=True)
class FeeEvidence:
    base_network_fee_lamports: int
    priority_fee_lamports: int
    tip_lamports: int
    protocol_fees: tuple[AssetQuantity, ...] = ()

    def __post_init__(self) -> None:
        non_negative(self.base_network_fee_lamports, "base_network_fee_lamports")
        non_negative(self.priority_fee_lamports, "priority_fee_lamports")
        non_negative(self.tip_lamports, "tip_lamports")


@dataclass(frozen=True, slots=True)
class MarginfiRepaymentObservation:
    program_id: str
    margin_account: str
    bank: str
    liquidity_vault: str
    asset: AssetKey
    slot: int
    margin_owner_before: str
    margin_owner_after: str
    bank_owner_before: str
    bank_owner_after: str
    flags_before: int
    flags_after: int
    liability_before: int
    liability_after: int
    borrowed: int
    required_repayment: int
    vault_before: int
    vault_after: int

    def __post_init__(self) -> None:
        names = (
            "program_id",
            "margin_account",
            "bank",
            "liquidity_vault",
            "margin_owner_before",
            "margin_owner_after",
            "bank_owner_before",
            "bank_owner_after",
        )
        for name in names:
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        positive(self.slot, "slot")
        integer_names = (
            "flags_before",
            "flags_after",
            "liability_before",
            "liability_after",
            "borrowed",
            "required_repayment",
            "vault_before",
            "vault_after",
        )
        for name in integer_names:
            non_negative(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class ReconciliationEvidence:
    expected_message_hash: str
    simulated_message_hash: str
    simulation_slot: int
    snapshot_slot: int
    min_context_slot: int
    simulation_succeeded: bool
    response_hash: str
    logs_hash: str
    settlement_asset: AssetKey
    native: tuple[NativeObservation, ...]
    tokens: tuple[TokenObservation, ...]
    fees: FeeEvidence
    marginfi: MarginfiRepaymentObservation | None
    required_accounts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepaymentProof:
    proven: bool
    borrowed: int
    required: int
    vault_return: int
    protocol_fee: int
    reason: ReconciliationReason | None = None


@dataclass(frozen=True, slots=True)
class AssetBreakdown:
    asset: AssetKey
    gross: int
    protocol_fee: int
    network_fee: int
    priority_fee: int
    tip: int
    rent_locked: int
    rent_refunded: int
    net: int


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    status: ReconciliationStatus
    reason: ReconciliationReason
    complete: bool
    message_hash: str
    slot: int
    settlement_asset: AssetKey
    settlement_net: int | None
    breakdowns: tuple[AssetBreakdown, ...]
    repayment: RepaymentProof
    response_hash: str
    logs_hash: str
    reconciliation_hash: str
    diagnostic: str = ""


@dataclass(frozen=True, slots=True)
class TokenValidationPolicy:
    token_2022_extensions: frozenset[str] = frozenset({"immutable_owner"})


class RejectedEvidence(Exception):
    def __init__(self, reason: ReconciliationReason, diagnostic: str):
        super().__init__(diagnostic)
        self.reason = reason
        self.diagnostic = diagnostic


def non_negative(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def positive(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
