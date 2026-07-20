"""Snapshot-driven detector primitives for PR-033."""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any

from src.market.snapshots import MarketQuoteSnapshot, SnapshotSet

from .domain import Opportunity


@dataclass(frozen=True, slots=True)
class DetectorPair:
    """Configured two-leg circular route universe entry."""

    pair_id: str
    base_mint: str
    intermediate_mint: str
    probe_amount_base_units: int
    min_gross_profit_base_units: int = 1
    max_snapshot_age_seconds: float = 5.0
    ttl_seconds: float = 2.0
    cooldown_seconds: float = 1.0
    max_slot_skew: int = 0

    def __post_init__(self) -> None:
        if not self.pair_id:
            raise ValueError("detector pair_id is required")
        if self.base_mint == self.intermediate_mint:
            raise ValueError("detector pair mints must differ")
        if self.probe_amount_base_units <= 0:
            raise ValueError("probe_amount_base_units must be positive")
        if self.min_gross_profit_base_units < 0:
            raise ValueError("min_gross_profit_base_units must not be negative")
        if self.max_snapshot_age_seconds <= 0:
            raise ValueError("max_snapshot_age_seconds must be positive")
        if self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must not be negative")
        if self.max_slot_skew < 0:
            raise ValueError("max_slot_skew must not be negative")


@dataclass(frozen=True, slots=True)
class DetectionRejection:
    pair_id: str
    reason_code: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _RouteCandidate:
    first: MarketQuoteSnapshot
    second: MarketQuoteSnapshot
    intermediate_amount: int
    final_amount: int

    @property
    def gross_profit_base_units(self) -> int:
        return self.final_amount - self.first.in_amount


class CircularArbitrageDetector:
    """Detect two-leg circular candidates from already-fetched snapshots."""

    def __init__(self, pairs: tuple[DetectorPair, ...]) -> None:
        self.pairs = pairs
        self.last_rejections: dict[str, DetectionRejection] = {}
        self._last_emit_at: dict[str, float] = {}

    def detect(
        self,
        snapshots: SnapshotSet,
        *,
        now: float | None = None,
    ) -> tuple[Opportunity, ...]:
        observed_at = time.time() if now is None else now
        opportunities: list[Opportunity] = []
        self.last_rejections = {}
        for pair in self.pairs:
            candidate = self._best_candidate(pair, snapshots, now=observed_at)
            if candidate is None:
                continue
            if candidate.gross_profit_base_units < pair.min_gross_profit_base_units:
                self.last_rejections[pair.pair_id] = DetectionRejection(
                    pair.pair_id,
                    "below_min_gross_profit",
                    {
                        "gross_profit_base_units": candidate.gross_profit_base_units,
                        "min_gross_profit_base_units": (
                            pair.min_gross_profit_base_units
                        ),
                    },
                )
                continue
            last_emit = self._last_emit_at.get(pair.pair_id)
            if (
                last_emit is not None
                and observed_at - last_emit < pair.cooldown_seconds
            ):
                self.last_rejections[pair.pair_id] = DetectionRejection(
                    pair.pair_id,
                    "cooldown_active",
                    {"cooldown_seconds": pair.cooldown_seconds},
                )
                continue
            self._last_emit_at[pair.pair_id] = observed_at
            opportunities.append(self._opportunity(pair, candidate, now=observed_at))
        return tuple(opportunities)

    def _best_candidate(
        self,
        pair: DetectorPair,
        snapshots: SnapshotSet,
        *,
        now: float,
    ) -> _RouteCandidate | None:
        first_legs = snapshots.matching_quotes(
            input_mint=pair.base_mint,
            output_mint=pair.intermediate_mint,
            now=now,
            max_age_seconds=pair.max_snapshot_age_seconds,
        )
        second_legs = snapshots.matching_quotes(
            input_mint=pair.intermediate_mint,
            output_mint=pair.base_mint,
            now=now,
            max_age_seconds=pair.max_snapshot_age_seconds,
        )
        if not first_legs or not second_legs:
            self.last_rejections[pair.pair_id] = DetectionRejection(
                pair.pair_id,
                "missing_route_leg",
                {
                    "first_leg_count": len(first_legs),
                    "second_leg_count": len(second_legs),
                },
            )
            return None
        candidates: list[_RouteCandidate] = []
        for first in first_legs:
            for second in second_legs:
                if abs(first.slot - second.slot) > pair.max_slot_skew:
                    continue
                intermediate_amount = first.project_output(pair.probe_amount_base_units)
                final_amount = second.project_output(intermediate_amount)
                candidates.append(
                    _RouteCandidate(
                        first=first,
                        second=second,
                        intermediate_amount=intermediate_amount,
                        final_amount=final_amount,
                    )
                )
        if not candidates:
            self.last_rejections[pair.pair_id] = DetectionRejection(
                pair.pair_id,
                "cross_slot_or_stale_snapshot",
                {"max_slot_skew": pair.max_slot_skew},
            )
            return None
        return max(candidates, key=lambda candidate: candidate.gross_profit_base_units)

    def _opportunity(
        self,
        pair: DetectorPair,
        candidate: _RouteCandidate,
        *,
        now: float,
    ) -> Opportunity:
        gross_profit = candidate.gross_profit_base_units
        metadata = {
            "schema_version": "pr033.snapshot-opportunity.v1",
            "detector_pair_id": pair.pair_id,
            "gross_profit_base_units": gross_profit,
            "projected_final_base_units": candidate.final_amount,
            "intermediate_amount_base_units": candidate.intermediate_amount,
            "route": [
                {
                    "provider": candidate.first.provider,
                    "input_mint": candidate.first.input_mint,
                    "output_mint": candidate.first.output_mint,
                    "slot": candidate.first.slot,
                    "source": candidate.first.source,
                    "quote_id": candidate.first.quote_id,
                },
                {
                    "provider": candidate.second.provider,
                    "input_mint": candidate.second.input_mint,
                    "output_mint": candidate.second.output_mint,
                    "slot": candidate.second.slot,
                    "source": candidate.second.source,
                    "quote_id": candidate.second.quote_id,
                },
            ],
            "features": {
                "gross_profit_base_units": gross_profit,
                "probe_amount_base_units": pair.probe_amount_base_units,
                "route_slot_skew": abs(candidate.first.slot - candidate.second.slot),
            },
            "reason_code": "candidate_detected",
        }
        return Opportunity.create(
            strategy_name="circular_arbitrage",
            opportunity_type="two_leg_circular_snapshot",
            detection_slot=min(candidate.first.slot, candidate.second.slot),
            input_mint=pair.base_mint,
            output_mint=pair.base_mint,
            proposed_amount_base_units=pair.probe_amount_base_units,
            expected_gross_profit=float(gross_profit),
            ttl_seconds=pair.ttl_seconds,
            metadata=metadata,
            detected_at=now,
        )
