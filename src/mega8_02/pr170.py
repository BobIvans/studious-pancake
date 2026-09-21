"""PR-170 / FEE-01: empirical inclusion-cost curves."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from .core import Mega802Error, require_nonnegative_int


@dataclass(frozen=True, slots=True)
class FeeObservation:
    cost: int
    included: bool


def ingest_priority_fee_market(
    observations: Sequence[FeeObservation],
) -> tuple[FeeObservation, ...]:
    return tuple(sorted(observations, key=lambda item: (item.cost, not item.included)))


def ingest_tip_floor_market(
    observations: Sequence[FeeObservation],
) -> tuple[FeeObservation, ...]:
    return ingest_priority_fee_market(observations)


def estimate_inclusion_cost_curve(
    observations: Sequence[FeeObservation],
) -> tuple[tuple[int, int], ...]:
    if not observations:
        raise Mega802Error("FEE_OBSERVATIONS_REQUIRED")
    costs = sorted({require_nonnegative_int(o.cost, "cost") for o in observations})
    curve: list[tuple[int, int]] = []
    for cost in costs:
        eligible = [o for o in observations if o.cost <= cost]
        probability_ppm = sum(o.included for o in eligible) * 1_000_000 // len(eligible)
        curve.append((cost, probability_ppm))
    return tuple(curve)


def select_economic_fee_bid(
    curve: Sequence[tuple[int, int]], *, target_inclusion_ppm: int, hard_cap: int
) -> int:
    require_nonnegative_int(target_inclusion_ppm, "target_inclusion_ppm")
    require_nonnegative_int(hard_cap, "hard_cap")
    for cost, probability in sorted(curve):
        if cost <= hard_cap and probability >= target_inclusion_ppm:
            return cost
    raise Mega802Error("NO_FEE_BID_WITHIN_CAP")
