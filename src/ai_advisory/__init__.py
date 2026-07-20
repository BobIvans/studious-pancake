"""AI advisory-only evidence gates.

This package is intentionally advisory-only.  It contains no trade execution,
signing, provider, RPC, Jito, or sender integrations.
"""

from .evidence_gate import (
    AIAdvisoryEvidencePackage,
    AIAdvisoryGatePolicy,
    AIAdvisoryReadinessGate,
    AIAdvisoryReadinessResult,
    AdvisoryFailureCode,
    DriftMonitorReport,
    EvaluationSplitKind,
    ModelEvaluationReport,
    ModelRegistryEntry,
    PromotionState,
    ShadowABReport,
)

__all__ = [
    "AIAdvisoryEvidencePackage",
    "AIAdvisoryGatePolicy",
    "AIAdvisoryReadinessGate",
    "AIAdvisoryReadinessResult",
    "AdvisoryFailureCode",
    "DriftMonitorReport",
    "EvaluationSplitKind",
    "ModelEvaluationReport",
    "ModelRegistryEntry",
    "PromotionState",
    "ShadowABReport",
]
