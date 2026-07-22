from __future__ import annotations

import importlib
from typing import Any

from .models import (
    ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
    COMPUTE_BUDGET_PROGRAM_ID,
    SOLANA_WIRE_TRANSACTION_LIMIT_BYTES,
    AccountSnapshot,
    AttemptIdentity,
    BlockhashContext,
    CompiledTransaction,
    ComputeBudgetPolicy,
    ExecutionAttempt,
    ExecutionErrorCode,
    ExecutionJournalEntry,
    ExecutionState,
    JournalAttemptRecord,
    PlannedInstruction,
    ResolvedAddressLookupTable,
    RpcClient,
    SignedTransaction,
    SimulationReport,
    SubmissionResult,
    TipPolicy,
    TokenDelta,
    TransactionDiagnostics,
    TransactionPlan,
    compute_message_hash,
)
from .transaction_compiler import AltValidator, TransactionCompileError
from .canonical_domain import (
    CanonicalExecutionContractError,
    CanonicalTransactionCompiler,
    ExecutionReceipt,
    TransactionCompiler,
    sign_fully,
    validate_canonical_plan,
    validate_compiled_identity,
)
from .v0_hardening import (
    CompilationFingerprints,
    CompileRuntimeContext,
    HardenedCompilation,
    HardenedV0Compiler,
    V0CompileFailureReason,
    V0CompilePolicy,
    V0HardeningError,
    blockhash_fingerprint,
    instruction_fingerprint,
    lookup_tables_fingerprint,
    plan_fingerprint,
)
from .state_machine import ExecutionStateMachine
from .transaction_simulator import (
    CompilerDiagnostics,
    CanonicalSimulator,
    SimulationRequest,
    TransactionSimulator,
    get_fee_for_message,
    parse_simulation_response,
    simulate_exact,
)
from .exact_simulation import (
    BlockhashValidityEvidence,
    ExactSimulationError,
    ExactSimulationErrorCode,
    ExactSimulationFinalizer,
    ExactSimulationPolicy,
    ExactSimulationReport,
    FailureDisposition,
    FinalizedSimulation,
    RpcSimulationEvidence,
    validate_exact_submission_binding,
)
from .state_evidence_pr115 import (
    PR115DecodePolicy,
    PR115NativeLamportDelta,
    PR115RawAccountSnapshot,
    PR115SimulationOwnedEconomicProof,
    PR115StateEvidenceCode,
    PR115StateEvidenceError,
    PR115TokenAccountDelta,
    build_pr115_proof_from_report,
    build_pr115_simulation_owned_economic_proof,
)
from .journal import InMemoryExecutionJournal, MIGRATION_VERSION, SQLiteAttemptJournal
from .lifecycle import SubmissionEnvelope, TransactionLifecycleService
from .live_gate import LiveSubmissionGate
from .reconciliation import (
    ReconciliationEvidence,
    ReconciliationOutcome,
    classify_reconciliation,
)
from .tip_validation import validate_exactly_one_tip

_PR191_LAZY_EXPORTS = frozenset(
    {
        "ImmutableLiveControlStore",
        "PR191_ACCOUNTING_SCHEMA",
        "TerminalAccountingConflict",
        "TerminalOutcomeCommit",
        "TerminalOutcomeIdentity",
        "record_actual_outcome",
    }
)


def __getattr__(name: str) -> Any:
    """Load source-only PR-191 live accounting only when explicitly requested.

    ``src.execution.live_control`` is intentionally excluded from the production
    wheel.  Eagerly importing the PR-191 compatibility cutover therefore broke
    installed CLI smoke even though normal paper execution never uses that surface.
    """

    if name in _PR191_LAZY_EXPORTS:
        module = importlib.import_module("src.execution.immutable_accounting_pr191")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ADDRESS_LOOKUP_TABLE_PROGRAM_ID",
    "COMPUTE_BUDGET_PROGRAM_ID",
    "SOLANA_WIRE_TRANSACTION_LIMIT_BYTES",
    "AccountSnapshot",
    "AltValidator",
    "AttemptIdentity",
    "BlockhashContext",
    "BlockhashValidityEvidence",
    "CanonicalExecutionContractError",
    "CanonicalSimulator",
    "CanonicalTransactionCompiler",
    "CompilationFingerprints",
    "CompileRuntimeContext",
    "CompiledTransaction",
    "CompilerDiagnostics",
    "ComputeBudgetPolicy",
    "ExactSimulationError",
    "ExactSimulationErrorCode",
    "ExactSimulationFinalizer",
    "ExactSimulationPolicy",
    "ExactSimulationReport",
    "ExecutionAttempt",
    "ExecutionErrorCode",
    "ExecutionJournalEntry",
    "ExecutionReceipt",
    "ExecutionState",
    "ExecutionStateMachine",
    "FailureDisposition",
    "FinalizedSimulation",
    "HardenedCompilation",
    "HardenedV0Compiler",
    "ImmutableLiveControlStore",
    "InMemoryExecutionJournal",
    "JournalAttemptRecord",
    "LiveSubmissionGate",
    "MIGRATION_VERSION",
    "PR115DecodePolicy",
    "PR115NativeLamportDelta",
    "PR115RawAccountSnapshot",
    "PR115SimulationOwnedEconomicProof",
    "PR115StateEvidenceCode",
    "PR115StateEvidenceError",
    "PR115TokenAccountDelta",
    "PR191_ACCOUNTING_SCHEMA",
    "PlannedInstruction",
    "ReconciliationEvidence",
    "ReconciliationOutcome",
    "ResolvedAddressLookupTable",
    "RpcClient",
    "RpcSimulationEvidence",
    "SQLiteAttemptJournal",
    "SignedTransaction",
    "SimulationReport",
    "SimulationRequest",
    "SubmissionEnvelope",
    "SubmissionResult",
    "TerminalAccountingConflict",
    "TerminalOutcomeCommit",
    "TerminalOutcomeIdentity",
    "TipPolicy",
    "TokenDelta",
    "TransactionCompileError",
    "TransactionCompiler",
    "TransactionDiagnostics",
    "TransactionLifecycleService",
    "TransactionPlan",
    "TransactionSimulator",
    "V0CompileFailureReason",
    "V0CompilePolicy",
    "V0HardeningError",
    "blockhash_fingerprint",
    "build_pr115_proof_from_report",
    "build_pr115_simulation_owned_economic_proof",
    "classify_reconciliation",
    "compute_message_hash",
    "get_fee_for_message",
    "instruction_fingerprint",
    "lookup_tables_fingerprint",
    "parse_simulation_response",
    "plan_fingerprint",
    "record_actual_outcome",
    "sign_fully",
    "simulate_exact",
    "validate_canonical_plan",
    "validate_compiled_identity",
    "validate_exact_submission_binding",
    "validate_exactly_one_tip",
]
