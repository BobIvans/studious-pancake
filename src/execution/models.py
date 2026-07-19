"""Canonical execution lifecycle models for generic Solana v0 compilation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import time
from typing import Any, Protocol

from solders.hash import Hash
from solders.instruction import Instruction as SoldersInstruction
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction
from solders.address_lookup_table_account import (
    AddressLookupTableAccount,
    ID as ADDRESS_LOOKUP_TABLE_ID,
)
from solders.compute_budget import ID as COMPUTE_BUDGET_ID

SOLANA_WIRE_TRANSACTION_LIMIT_BYTES = 1232
DEFAULT_BLOCKHASH = Hash.default()
COMPUTE_BUDGET_PROGRAM_ID = COMPUTE_BUDGET_ID
ADDRESS_LOOKUP_TABLE_PROGRAM_ID = ADDRESS_LOOKUP_TABLE_ID


class ExecutionState(str, Enum):
    CREATED = "created"
    PLANNED = "planned"
    COMPILED = "compiled"
    STRUCTURALLY_VALIDATED = "structurally_validated"
    SIMULATED = "simulated"
    REJECTED = "rejected"
    APPROVED = "approved"
    SIGNED = "signed"
    SUBMISSION_INTENT_RECORDED = "submission_intent_recorded"
    SUBMISSION_UNCERTAIN = "submission_uncertain"
    ACCEPTED = "accepted"
    REJECTED_PRE_SEND = "rejected_pre_send"
    PENDING = "pending"
    LANDED = "landed"
    RECONCILING = "reconciling"
    RECONCILED_SUCCESS = "reconciled_success"
    RECONCILED_FAILURE = "reconciled_failure"
    AMBIGUOUS_MANUAL_REVIEW = "ambiguous_manual_review"
    PROVEN_EXPIRED = "proven_expired"
    REBUILD_ELIGIBLE = "rebuild_eligible"
    # Backward-compatible aliases for pre-PR-014 tests/imports.
    SUBMITTED = "submitted"
    FAILED = "failed"
    EXPIRED = "expired"
    RECONCILED = "reconciled"


class ExecutionErrorCode(str, Enum):
    INVALID_PLAN = "invalid_plan"
    UNRESOLVED_ALT = "unresolved_alt"
    TRANSACTION_TOO_LARGE = "transaction_too_large"
    INVALID_BLOCKHASH = "invalid_blockhash"
    BLOCKHASH_EXPIRED = "blockhash_expired"
    MISSING_SIGNER = "missing_signer"
    SIMULATION_RPC_ERROR = "simulation_rpc_error"
    SIMULATION_PROGRAM_ERROR = "simulation_program_error"
    COMPUTE_LIMIT_EXCEEDED = "compute_limit_exceeded"
    ACCOUNT_DATA_LIMIT_EXCEEDED = "account_data_limit_exceeded"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    MARGINFI_FLASHLOAN_REJECTED = "marginfi_flashloan_rejected"
    SLIPPAGE_REJECTED = "slippage_rejected"
    PROFIT_REJECTED = "profit_rejected"
    SUBMISSION_REJECTED = "submission_rejected"
    BUNDLE_PENDING = "bundle_pending"
    BUNDLE_FAILED = "bundle_failed"
    BUNDLE_INVALID = "bundle_invalid"
    SIGNATURE_FAILED = "signature_failed"
    RECONCILIATION_FAILED = "reconciliation_failed"
    LIVE_GATE_NOT_OPEN = "live_gate_not_open"
    AMBIGUOUS_SUBMISSION = "ambiguous_submission"
    TIP_POLICY_REJECTED = "tip_policy_rejected"


@dataclass(frozen=True, slots=True)
class Instruction:
    """Legacy string instruction descriptor kept for older planner tests."""

    program_id: str
    accounts: tuple[str, ...] = ()
    data: bytes = b""
    name: str = ""
    kind: str = "generic"

    def stable_bytes(self) -> bytes:
        return b"|".join(
            [
                self.program_id.encode(),
                b",".join(account.encode() for account in self.accounts),
                self.name.encode(),
                self.kind.encode(),
                self.data,
            ]
        )


@dataclass(frozen=True, slots=True)
class FlashLoanPlan:
    """Legacy MarginFi flash-loan descriptor kept as a compatibility shim."""

    marginfi_account: str
    authority: str
    group: str
    borrow_instruction: Instruction
    repay_instruction: Instruction
    end_instruction_template: Instruction
    projected_active_balances: tuple[str, ...]
    risk_engine_accounts: tuple[str, ...]
    marginfi_bank_slot: int
    token_2022_mint: str | None = None


@dataclass(frozen=True, slots=True)
class PlannedInstruction:
    instruction: SoldersInstruction
    role: str = "application"
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ComputeBudgetPolicy:
    unit_limit: int | None = None
    micro_lamports_per_cu: int | None = None
    simulation_unit_limit: int = 1_400_000
    safety_margin_bps: int = 1_000


@dataclass(frozen=True, slots=True)
class TipPolicy:
    lamports: int = 0
    tip_account: Pubkey | None = None


@dataclass(frozen=True, slots=True, init=False)
class TransactionPlan:
    opportunity_id: str
    payer: Pubkey
    instructions: tuple[PlannedInstruction, ...]
    compute_budget_policy: ComputeBudgetPolicy
    tip_policy: TipPolicy = TipPolicy()
    required_signers: tuple[Pubkey, ...] = ()
    lookup_table_addresses: tuple[Pubkey, ...] = ()
    required_lookup_addresses: tuple[Pubkey, ...] = ()
    quote_slot: int | None = None
    market_state_slot: int | None = None
    oracle_slot: int | None = None
    monitored_accounts: tuple[Pubkey, ...] = ()

    def __init__(self, opportunity_id: str, payer, *args, **kwargs) -> None:
        object.__setattr__(self, "opportunity_id", opportunity_id)
        object.__setattr__(self, "payer", payer)
        if args and isinstance(args[0], ComputeBudgetPolicy):
            # Legacy positional layout:
            # opportunity, payer, compute, setup, flash, strategy, cleanup, tip,
            # required_signers, lookup_tables, quote_slot, market_slot, oracle_slot, monitored
            compute = args[0]
            setup = args[1] if len(args) > 1 else ()
            flash = args[2] if len(args) > 2 else None
            strategy = args[3] if len(args) > 3 else ()
            cleanup = args[4] if len(args) > 4 else ()
            tip = args[5] if len(args) > 5 else TipPolicy()
            required = args[6] if len(args) > 6 else ()
            lookup = args[7] if len(args) > 7 else ()
            quote = args[8] if len(args) > 8 else None
            market = args[9] if len(args) > 9 else None
            oracle = args[10] if len(args) > 10 else None
            monitored = args[11] if len(args) > 11 else ()
            object.__setattr__(self, "instructions", compute)
            object.__setattr__(self, "compute_budget_policy", tuple(setup))
            object.__setattr__(self, "tip_policy", flash)
            object.__setattr__(self, "required_signers", tuple(strategy))
            object.__setattr__(self, "lookup_table_addresses", tuple(cleanup))
            object.__setattr__(self, "required_lookup_addresses", tip)
            object.__setattr__(self, "quote_slot", tuple(required))
            object.__setattr__(self, "market_state_slot", tuple(lookup))
            object.__setattr__(self, "oracle_slot", quote)
            object.__setattr__(self, "monitored_accounts", market if monitored == () else monitored)
            return
        instructions = args[0] if len(args) > 0 else kwargs.pop("instructions", ())
        compute = args[1] if len(args) > 1 else kwargs.pop("compute_budget_policy", ComputeBudgetPolicy())
        tip = args[2] if len(args) > 2 else kwargs.pop("tip_policy", TipPolicy())
        required = args[3] if len(args) > 3 else kwargs.pop("required_signers", ())
        lookup = args[4] if len(args) > 4 else kwargs.pop("lookup_table_addresses", ())
        required_lookup = args[5] if len(args) > 5 else kwargs.pop("required_lookup_addresses", ())
        quote = args[6] if len(args) > 6 else kwargs.pop("quote_slot", None)
        market = args[7] if len(args) > 7 else kwargs.pop("market_state_slot", None)
        oracle = args[8] if len(args) > 8 else kwargs.pop("oracle_slot", None)
        monitored = args[9] if len(args) > 9 else kwargs.pop("monitored_accounts", ())
        object.__setattr__(self, "instructions", tuple(instructions))
        object.__setattr__(self, "compute_budget_policy", compute)
        object.__setattr__(self, "tip_policy", tip)
        object.__setattr__(self, "required_signers", tuple(required))
        object.__setattr__(self, "lookup_table_addresses", tuple(lookup))
        object.__setattr__(self, "required_lookup_addresses", tuple(required_lookup))
        object.__setattr__(self, "quote_slot", quote)
        object.__setattr__(self, "market_state_slot", market)
        object.__setattr__(self, "oracle_slot", oracle)
        object.__setattr__(self, "monitored_accounts", tuple(monitored))
        if kwargs:
            raise TypeError(f"unexpected TransactionPlan fields: {sorted(kwargs)}")

    @property
    def min_context_slot(self) -> int:
        return max(
            self.quote_slot or 0, self.market_state_slot or 0, self.oracle_slot or 0
        )


@dataclass(frozen=True, slots=True)
class BlockhashContext:
    blockhash: Hash
    last_valid_block_height: int
    source_slot: int
    fetched_at: float
    commitment: str

    def validate(self) -> None:
        if not isinstance(self.blockhash, Hash) or self.blockhash == DEFAULT_BLOCKHASH:
            raise ValueError(ExecutionErrorCode.INVALID_BLOCKHASH.value)


@dataclass(frozen=True, slots=True)
class ResolvedAddressLookupTable:
    address: Pubkey
    owner: Pubkey
    addresses: tuple[Pubkey, ...]
    deactivation_slot: int | None
    last_extended_slot: int | None
    last_extended_slot_start_index: int | None
    source_slot: int
    data_hash: str
    account: AddressLookupTableAccount
    library_deserialized: bool = True


@dataclass(frozen=True, slots=True)
class TransactionDiagnostics:
    wire_size: int
    required_signature_count: int
    static_account_count: int
    lookup_writable_count: int
    lookup_readonly_count: int
    total_resolved_account_count: int
    used_alt_pubkeys: tuple[Pubkey, ...]


@dataclass(frozen=True, slots=True)
class CompiledTransaction:
    opportunity_id: str
    payer: Pubkey
    instructions: tuple[SoldersInstruction, ...]
    message: MessageV0
    blockhash_context: BlockhashContext
    lookup_tables: tuple[ResolvedAddressLookupTable, ...]
    serialized_message: bytes
    serialized_transaction: bytes
    versioned_transaction: VersionedTransaction
    message_hash: str
    min_context_slot: int
    required_signers: tuple[Pubkey, ...]
    diagnostics: TransactionDiagnostics
    monitored_accounts: tuple[Pubkey, ...] = ()
    is_fully_signed: bool = False


@dataclass(frozen=True, slots=True)
class SignedTransaction:
    compiled: CompiledTransaction
    versioned_transaction: VersionedTransaction
    serialized_transaction: bytes
    signatures: tuple[Signature, ...]
    message_hash: str
    is_fully_signed: bool = True


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    address: str
    lamports: int
    owner: str
    data: bytes = b""
    executable: bool = False
    rent_epoch: int | None = None


@dataclass(frozen=True, slots=True)
class TokenDelta:
    mint: str
    account: str
    amount: int
    decimals: int = 0


@dataclass(frozen=True, slots=True)
class SimulationReport:
    success: bool
    error: object | None
    logs: tuple[str, ...]
    inner_instructions: object | None
    units_consumed: int | None
    loaded_accounts_data_size: int | None
    return_data: object | None
    pre_account_states: tuple[AccountSnapshot, ...]
    post_account_states: tuple[AccountSnapshot, ...]
    token_deltas: tuple[TokenDelta, ...]
    native_delta_before_fee: int
    estimated_network_fee: int
    simulated_net_profit: TokenDelta | None
    simulation_slot: int
    min_context_slot: int
    transaction_message_hash: str


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    opportunity_id: str
    attempt_number: int
    transaction_message_hash: str
    state: ExecutionState
    blockhash_context: BlockhashContext
    created_at: float = field(default_factory=time.time)

    @property
    def idempotency_key(self) -> str:
        return f"{self.opportunity_id}:{self.attempt_number}:{self.transaction_message_hash}"


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    submitted: bool
    mode: str
    reason: str | None = None
    bundle_id: str | None = None
    transaction_signatures: tuple[str, ...] = ()
    accepted: bool = False
    landed: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    trace_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionJournalEntry:
    opportunity_id: str
    attempt_number: int
    transaction_message_hash: str
    compiled: bool = False
    simulated: bool = False
    approved: bool = False
    signed: bool = False
    submitted: bool = False
    bundle_id: str | None = None
    transaction_signatures: tuple[str, ...] = ()
    landed_slot: int | None = None
    reconciled: bool = False


@dataclass(frozen=True, slots=True)
class AttemptIdentity:
    logical_opportunity_id: str
    plan_hash: str
    attempt_generation: int


@dataclass(frozen=True, slots=True)
class JournalAttemptRecord:
    logical_opportunity_id: str
    plan_hash: str
    attempt_generation: int
    state: ExecutionState
    revision: int
    message_digest: str | None = None
    signed_transaction_digest: str | None = None
    transaction_signatures: tuple[str, ...] = ()
    blockhash: str | None = None
    last_valid_block_height: int | None = None
    source_slot: int | None = None
    min_context_slot: int | None = None
    commitment: str | None = None
    transport: str | None = None
    bundle_id: str | None = None
    claim_owner: str | None = None
    lease_expires_at: float | None = None


class RpcClient(Protocol):
    async def call(self, method: str, params: list[Any]) -> Any: ...


def compute_message_hash(message: bytes) -> str:
    return hashlib.sha256(message).hexdigest()
