"""Canonical execution lifecycle models.

These models intentionally keep provider instructions normalized before any
blockhash, signature, RPC simulation, or submission concern is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import time
from typing import Any, Protocol

SOLANA_WIRE_TRANSACTION_LIMIT_BYTES = 1232
DEFAULT_BLOCKHASH = "11111111111111111111111111111111"
COMPUTE_BUDGET_PROGRAM_ID = "ComputeBudget111111111111111111111111111111"
ADDRESS_LOOKUP_TABLE_PROGRAM_ID = "AddressLookupTab1e1111111111111111111111111"


class ExecutionState(str, Enum):
    CREATED = "created"
    PLANNED = "planned"
    COMPILED = "compiled"
    STRUCTURALLY_VALIDATED = "structurally_validated"
    SIMULATED = "simulated"
    REJECTED = "rejected"
    APPROVED = "approved"
    SIGNED = "signed"
    SUBMITTED = "submitted"
    PENDING = "pending"
    LANDED = "landed"
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


@dataclass(frozen=True, slots=True)
class Instruction:
    program_id: str
    accounts: tuple[str, ...] = ()
    data: bytes = b""
    name: str = "instruction"
    kind: str = "generic"

    def stable_bytes(self) -> bytes:
        return "|".join((self.program_id, self.name, self.kind, ",".join(self.accounts))).encode() + self.data


@dataclass(frozen=True, slots=True)
class ComputeBudgetPolicy:
    unit_limit: int
    micro_lamports_per_cu: int
    simulation_unit_limit: int = 1_400_000
    safety_margin_bps: int = 1_000


@dataclass(frozen=True, slots=True)
class TipPolicy:
    lamports: int = 0
    tip_account: str | None = None


@dataclass(frozen=True, slots=True)
class FlashLoanPlan:
    marginfi_account: str
    authority: str
    group: str
    borrow_instruction: Instruction
    repay_instruction: Instruction
    end_instruction_template: Instruction
    projected_active_balances: tuple[str, ...]
    risk_engine_accounts: tuple[str, ...]
    marginfi_bank_slot: int | None = None
    token_2022_mint: str | None = None


@dataclass(frozen=True, slots=True)
class TransactionPlan:
    opportunity_id: str
    payer: str
    compute_budget_policy: ComputeBudgetPolicy
    setup_instructions: tuple[Instruction, ...]
    flash_loan_plan: FlashLoanPlan
    strategy_instructions: tuple[Instruction, ...]
    cleanup_instructions: tuple[Instruction, ...]
    tip_policy: TipPolicy
    required_signers: tuple[str, ...]
    lookup_table_addresses: tuple[str, ...]
    quote_slot: int | None
    market_state_slot: int | None
    oracle_slot: int | None
    monitored_accounts: tuple[str, ...]

    @property
    def min_context_slot(self) -> int:
        return max(self.quote_slot or 0, self.market_state_slot or 0, self.oracle_slot or 0, self.flash_loan_plan.marginfi_bank_slot or 0)


@dataclass(frozen=True, slots=True)
class BlockhashContext:
    blockhash: str
    last_valid_block_height: int
    source_slot: int
    fetched_at: float
    commitment: str

    def validate(self) -> None:
        if not self.blockhash or self.blockhash == DEFAULT_BLOCKHASH or set(self.blockhash) == {"0"}:
            raise ValueError(ExecutionErrorCode.INVALID_BLOCKHASH.value)


@dataclass(frozen=True, slots=True)
class ResolvedAddressLookupTable:
    address: str
    owner: str
    addresses: tuple[str, ...]
    deactivation_slot: int | None
    source_slot: int
    data_hash: str
    library_deserialized: bool = True


@dataclass(frozen=True, slots=True)
class CompiledTransaction:
    opportunity_id: str
    payer: str
    instructions: tuple[Instruction, ...]
    blockhash_context: BlockhashContext
    lookup_tables: tuple[ResolvedAddressLookupTable, ...]
    serialized_message: bytes
    serialized_transaction: bytes
    message_hash: str
    marginfi_end_index: int
    min_context_slot: int
    required_signers: tuple[str, ...]


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


class RpcClient(Protocol):
    async def call(self, method: str, params: list[Any]) -> Any: ...


def compute_message_hash(message: bytes) -> str:
    return hashlib.sha256(message).hexdigest()
