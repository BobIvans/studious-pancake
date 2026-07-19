"""Opportunity rankers."""
from __future__ import annotations

from src.ingest.arbitrage_scorer import ArbitrageOpportunity, ArbitrageScorer

from .domain import Opportunity
from .interfaces import OpportunityRanker


class ArbitrageScorerRanker(OpportunityRanker):
    """Adapter that keeps legacy ArbitrageScorer behind OpportunityRanker."""

    def __init__(self, scorer: ArbitrageScorer | None = None) -> None:
        self.scorer = scorer or ArbitrageScorer()

    async def priority(self, opportunity: Opportunity) -> float:
        features = dict(opportunity.metadata.get("features", {}))
        legacy = ArbitrageOpportunity(
            pair=f"{opportunity.input_mint}/{opportunity.output_mint}",
            expected_profit_sol=float(opportunity.expected_gross_profit),
            slippage_pct=float(features.get("slippage_pct", 0.0)),
            liquidity_depth_usd=float(features.get("liquidity_depth_usd", 0.0)),
            network_congestion=float(features.get("network_congestion", 0.0)),
            gas_cost_sol=float(features.get("gas_cost_sol", 0.0)),
            execution_time_ms=float(features.get("execution_time_ms", 0.0)),
            timestamp=opportunity.detected_at,
            metadata=dict(opportunity.metadata),
        )
        return await self.scorer.score_opportunity(legacy)
