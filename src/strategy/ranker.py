"""Opportunity rankers.

PR-022 quarantines the legacy ArbitrageScorer adapter away from the active queue
path. The default ranker below uses only advisory, offline-safe decision
intelligence baseline/model recommendations and never imports sender/Jito/RPC.
"""

from __future__ import annotations

from src.decision.model import baseline_priority, recommend
from src.decision.contracts import ModelStatus, RankingRecommendation

from .domain import Opportunity
from .interfaces import OpportunityRanker


class DecisionIntelligenceRanker(OpportunityRanker):
    """Read-only advisory ranker with deterministic baseline fallback."""

    def __init__(
        self, artifact_path: str | None = None, shadow_only: bool = True
    ) -> None:
        self.artifact_path = artifact_path
        self.shadow_only = shadow_only
        self.last_recommendation: RankingRecommendation | None = None

    async def priority(self, opportunity: Opportunity) -> float:
        features = dict(
            opportunity.metadata.get("features_pre_quote")
            or opportunity.metadata.get("features")
            or {}
        )
        rec = recommend(features, self.artifact_path)
        self.last_recommendation = rec
        if (
            self.shadow_only
            or rec.model_status is not ModelStatus.SHADOW_CHALLENGER
            or rec.probability is None
        ):
            return rec.baseline_priority * 1.0
        return rec.baseline_priority * 1.0 + rec.probability


class ArbitrageScorerRanker(DecisionIntelligenceRanker):
    """Compatibility alias: legacy float-money scorer is quarantined and unused."""
