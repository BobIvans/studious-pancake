"""Canonical execution lifecycle models for generic Solana v0 compilation."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import time
from typing import Any, Protocol

from solders.hash import Hash
from solders.instruction import Instruction
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction
from solders.address_lookup_table_account import AddressLookupTableAccount, ADDRESS_LOOKUP_TABLE_ID
from solders.compute_budget import ID as COMPUTE_BUDGET_ID

SOLANA_WIRE_TRANSACTION_LIMIT_BYTES = 1232
DEFAULT_BLOCKHASH = Hash.default()
COMPUTE_BUDGET_PROGRAM_ID = COMPUTE_BUDGET_ID
ADDRESS_LOOKUP_TABLE_PROGRAM_ID = ADDRESS_LOOKUP_TABLE_ID


class ExecutionState(str, Enum):
    CREATED = "created"; PLANNED = "planned"; COMPILED = "compiled"; STRUCTURALLY_VALIDATED = "structurally_validated"; SIMULATED = "simulated"; REJECTED = "rejected"; APPROVED = "approved"; SIGNED = "signed"; SUBMITTED = "submitted"; PENDING = "pending"; LANDED = "landed"; FAILED = "failed"; EXPIRED = "expired"; RECONCILED = "reconciled"


class ExecutionErrorCode(str, Enum):
    INVALID_PLAN = "invalid_plan"; UNRESOLVED_ALT = "unresolved_alt"; TRANSACTION_TOO_LARGE = "transaction_too_large"; INVALID_BLOCKHASH = "invalid_blockhash"; BLOCKHASH_EXPIRED = "blockhash_expired"; MISSING_SIGNER = "missing_signer"; SIMULATION_RPC_ERROR = "simulation_rpc_error"; SIMULATION_PROGRAM_ERROR = "simulation_program_error"; COMPUTE_LIMIT_EXCEEDED = "compute_limit_exceeded"; ACCOUNT_DATA_LIMIT_EXCEEDED = "account_data_limit_exceeded"; INSUFFICIENT_FUNDS = "insufficient_funds"; MARGINFI_FLASHLOAN_REJECTED = "marginfi_flashloan_rejected"; SLIPPAGE_REJECTED = "slippage_rejected"; PROFIT_REJECTED = "profit_rejected"; SUBMISSION_REJECTED = "submission_rejected"; BUNDLE_PENDING = "bundle_pending"; BUNDLE_FAILED = "bundle_failed"; BUNDLE_INVALID = "bundle_invalid"; SIGNATURE_FAILED = "signature_failed"; RECONCILIATION_FAILED = "reconciliation_failed"


@dataclass(frozen=True, slots=True)
class PlannedInstruction:
    instruction: Instruction
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


@dataclass(frozen=True, slots=True)
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

    @property
    def min_context_slot(self) -> int:
        return max(self.quote_slot or 0, self.market_state_slot or 0, self.oracle_slot or 0)


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
    instructions: tuple[Instruction, ...]
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
    address: str; lamports: int; owner: str; data: bytes = b""; executable: bool = False; rent_epoch: int | None = None

@dataclass(frozen=True, slots=True)
class TokenDelta:
    mint: str; account: str; amount: int; decimals: int = 0

@dataclass(frozen=True, slots=True)
class SimulationReport:
    success: bool; error: object | None; logs: tuple[str, ...]; inner_instructions: object | None; units_consumed: int | None; loaded_accounts_data_size: int | None; return_data: object | None; pre_account_states: tuple[AccountSnapshot, ...]; post_account_states: tuple[AccountSnapshot, ...]; token_deltas: tuple[TokenDelta, ...]; native_delta_before_fee: int; estimated_network_fee: int; simulated_net_profit: TokenDelta | None; simulation_slot: int; min_context_slot: int; transaction_message_hash: str

@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    opportunity_id: str; attempt_number: int; transaction_message_hash: str; state: ExecutionState; blockhash_context: BlockhashContext; created_at: float = field(default_factory=time.time)
    @property
    def idempotency_key(self) -> str: return f"{self.opportunity_id}:{self.attempt_number}:{self.transaction_message_hash}"

@dataclass(frozen=True, slots=True)
class SubmissionResult:
    submitted: bool; mode: str; reason: str | None = None; bundle_id: str | None = None; transaction_signatures: tuple[str, ...] = (); accepted: bool = False; landed: bool = False

@dataclass(frozen=True, slots=True)
class ExecutionJournalEntry:
    opportunity_id: str; attempt_number: int; transaction_message_hash: str; compiled: bool = False; simulated: bool = False; approved: bool = False; signed: bool = False; submitted: bool = False; bundle_id: str | None = None; transaction_signatures: tuple[str, ...] = (); landed_slot: int | None = None; reconciled: bool = False

class RpcClient(Protocol):
    async def call(self, method: str, params: list[Any]) -> Any: ...

def compute_message_hash(message: bytes) -> str:
    return hashlib.sha256(message).hexdigest()
