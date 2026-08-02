"""Canonical MPR-SYS-02 execution-truth authority."""

from .runtime import (
    CompiledMessageRef,
    DurableAttemptRef,
    EXECUTION_TRUTH_EVIDENCE_SCHEMA_ID,
    EXECUTION_TRUTH_SCHEMA_ID,
    ExecutionStage,
    ExecutionTruthBundle,
    ExecutionTruthError,
    PlanRef,
    ReconciliationRef,
    RootedCandidateRef,
    SimulationRef,
    TerminalState,
    compute_plan_hash,
    evaluate_bundle,
    terminalize_ambiguous,
    validate_transition,
)

__all__ = [
    "CompiledMessageRef",
    "DurableAttemptRef",
    "EXECUTION_TRUTH_EVIDENCE_SCHEMA_ID",
    "EXECUTION_TRUTH_SCHEMA_ID",
    "ExecutionStage",
    "ExecutionTruthBundle",
    "ExecutionTruthError",
    "PlanRef",
    "ReconciliationRef",
    "RootedCandidateRef",
    "SimulationRef",
    "TerminalState",
    "compute_plan_hash",
    "evaluate_bundle",
    "terminalize_ambiguous",
    "validate_transition",
]
