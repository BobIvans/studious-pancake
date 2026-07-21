"""Snapshot-driven detector primitives for PR-033."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
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
        first_amount_mismatches = 0
        second_amount_mismatches = 0
        exact_amount_pairs = 0
        cross_slot_pairs = 0

        for first in first_legs:
            if first.in_amount != pair.probe_amount_base_units:
                first_amount_mismatches += 1
                continue

            intermediate_amount = first.exact_output_for(pair.probe_amount_base_units)
            exact_second_legs = tuple(
                second
                for second in second_legs
                if second.in_amount == intermediate_amount
            )
            if not exact_second_legs:
                second_amount_mismatches += 1
                continue

            for second in exact_second_legs:
                exact_amount_pairs += 1
                if abs(first.slot - second.slot) > pair.max_slot_skew:
                    cross_slot_pairs += 1
                    continue
                final_amount = second.exact_output_for(intermediate_amount)
                candidates.append(
                    _RouteCandidate(
                        first=first,
                        second=second,
                        intermediate_amount=intermediate_amount,
                        final_amount=final_amount,
                    )
                )

        if not candidates:
            reason_code = (
                "second_leg_amount_mismatch"
                if second_amount_mismatches
                else "cross_slot_or_stale_snapshot"
            )
            self.last_rejections[pair.pair_id] = DetectionRejection(
                pair.pair_id,
                reason_code,
                {
                    "first_leg_count": len(first_legs),
                    "second_leg_count": len(second_legs),
                    "first_leg_amount_mismatches": first_amount_mismatches,
                    "second_leg_amount_mismatches": second_amount_mismatches,
                    "exact_amount_pairs": exact_amount_pairs,
                    "cross_slot_pairs": cross_slot_pairs,
                    "probe_amount_base_units": pair.probe_amount_base_units,
                    "max_slot_skew": pair.max_slot_skew,
                },
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
        route_identity = self._route_identity(pair, candidate)
        metadata = {
            "schema_version": "pr113.amount-coupled-route.v1",
            "detector_pair_id": pair.pair_id,
            "route_identity": route_identity,
            "amount_coupled_quotes": True,
            "gross_profit_base_units": gross_profit,
            "projected_final_base_units": candidate.final_amount,
            "intermediate_amount_base_units": candidate.intermediate_amount,
            "second_leg_request_amount_base_units": candidate.second.in_amount,
            "final_requote_required_before_planning": True,
            "route": [
                self._route_leg_metadata(candidate.first),
                self._route_leg_metadata(candidate.second),
            ],
            "features": {
                "gross_profit_base_units": gross_profit,
                "probe_amount_base_units": pair.probe_amount_base_units,
                "route_slot_skew": abs(candidate.first.slot - candidate.second.slot),
                "route_identity": route_identity,
            },
            "reason_code": "candidate_detected_amount_coupled",
        }
        return Opportunity.create(
            strategy_name="circular_arbitrage",
            opportunity_type="two_leg_circular_amount_coupled_snapshot",
            detection_slot=min(candidate.first.slot, candidate.second.slot),
            input_mint=pair.base_mint,
            output_mint=pair.base_mint,
            proposed_amount_base_units=pair.probe_amount_base_units,
            expected_gross_profit=gross_profit,
            ttl_seconds=pair.ttl_seconds,
            metadata=metadata,
            detected_at=now,
        )

    @staticmethod
    def _route_leg_metadata(snapshot: MarketQuoteSnapshot) -> dict[str, Any]:
        return {
            "provider": snapshot.provider,
            "input_mint": snapshot.input_mint,
            "output_mint": snapshot.output_mint,
            "in_amount": snapshot.in_amount,
            "out_amount": snapshot.out_amount,
            "slot": snapshot.slot,
            "commitment": snapshot.commitment,
            "observed_at": snapshot.observed_at,
            "expires_at": snapshot.expires_at,
            "source": snapshot.source,
            "quote_id": snapshot.quote_id,
            "request_fingerprint": snapshot.request_fingerprint,
            "response_hash": snapshot.response_hash,
            "provider_timestamp": snapshot.provider_timestamp,
            "correlation_labels": list(snapshot.correlation_labels),
        }

    @staticmethod
    def _route_identity(pair: DetectorPair, candidate: _RouteCandidate) -> str:
        payload = {
            "schema_version": "pr113.route-identity.v1",
            "pair_id": pair.pair_id,
            "base_mint": pair.base_mint,
            "intermediate_mint": pair.intermediate_mint,
            "probe_amount_base_units": pair.probe_amount_base_units,
            "first": {
                "provider": candidate.first.provider,
                "request_fingerprint": candidate.first.request_fingerprint,
                "response_hash": candidate.first.response_hash,
                "in_amount": candidate.first.in_amount,
                "out_amount": candidate.first.out_amount,
                "slot": candidate.first.slot,
                "quote_id": candidate.first.quote_id,
            },
            "second": {
                "provider": candidate.second.provider,
                "request_fingerprint": candidate.second.request_fingerprint,
                "response_hash": candidate.second.response_hash,
                "in_amount": candidate.second.in_amount,
                "out_amount": candidate.second.out_amount,
                "slot": candidate.second.slot,
                "quote_id": candidate.second.quote_id,
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
