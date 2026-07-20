"""Offline/shadow decision intelligence package for PR-022/PR-051.

This package is intentionally read-only and must not import sender, signer, RPC,
Jito, live permit, execution journal writer, or config mutation modules.
"""

from .advisory import (
    AdvisoryDecisionEnvelope,
    DeterministicCandidateDecision,
    apply_advisory_guard,
    assert_no_ai_control_surface,
)
from .contracts import (
    DecisionStage,
    ModelStatus,
    RankingRecommendation,
    RecommendedBand,
)
from .model import baseline_priority, recommend
from .model_registry import ModelRegistryManifest, build_model_registry
from .shadow_ab import build_shadow_ab_report

__all__ = [
    "AdvisoryDecisionEnvelope",
    "DecisionStage",
    "DeterministicCandidateDecision",
    "ModelRegistryManifest",
    "ModelStatus",
    "RankingRecommendation",
    "RecommendedBand",
    "apply_advisory_guard",
    "assert_no_ai_control_surface",
    "baseline_priority",
    "build_model_registry",
    "build_shadow_ab_report",
    "recommend",
]
