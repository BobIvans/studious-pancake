"""Compatibility alias for the canonical MPR-4X-02 runtime authority.

The semantic owner moved to :mod:`src.runtime_authority`. Keep this module thin
so existing imports and historical verification remain compatible while no
second runtime-authority implementation exists.
"""

from src.runtime_authority import (
    AttemptGeneration,
    RuntimeAuthorityError,
    RuntimeAuthorityReport,
    SemanticCommandIdentity,
    SemanticIdempotencyLedger,
    TerminalState,
    TerminalTransitionTable,
    TransitionDecision,
    evaluate_runtime_authority_map,
    load_default_authority_map,
)

__all__ = [
    "AttemptGeneration",
    "RuntimeAuthorityError",
    "RuntimeAuthorityReport",
    "SemanticCommandIdentity",
    "SemanticIdempotencyLedger",
    "TerminalState",
    "TerminalTransitionTable",
    "TransitionDecision",
    "evaluate_runtime_authority_map",
    "load_default_authority_map",
]
