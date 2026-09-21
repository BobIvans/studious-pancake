"""PR-259 / RUIN-01: microcapital survival and risk-of-ruin controls."""

from __future__ import annotations
from typing import Sequence
from .core import (
    Mega806Error,
    require_int,
    require_nonnegative_int,
    require_positive_int,
)


def estimate_bankroll_survival(
    reserve: int, costs: Sequence[int], *, horizon_attempts: int
) -> int:
    reserve = require_nonnegative_int(reserve, "reserve")
    horizon_attempts = require_positive_int(horizon_attempts, "horizon_attempts")
    if not costs:
        raise Mega806Error("cost samples are required")
    conservative_cost = max(require_nonnegative_int(x, "cost") for x in costs)
    if conservative_cost == 0:
        return horizon_attempts
    return min(horizon_attempts, reserve // conservative_cost)


def compute_risk_of_ruin(
    reserve: int, outcome_samples: Sequence[int], *, attempts: int
) -> int:
    reserve = require_nonnegative_int(reserve, "reserve")
    attempts = require_positive_int(attempts, "attempts")
    if not outcome_samples:
        raise Mega806Error("outcome samples are required")
    losses = [max(0, -require_int(x, "outcome")) for x in outcome_samples]
    worst = max(losses)
    if worst == 0:
        return 0
    required = worst * attempts
    if reserve >= required:
        return 0
    return min(1_000_000, (required - reserve) * 1_000_000 // required)


def allocate_microcapital_budget(
    reserve: int, *, protected_floor: int, max_spend_ppm: int
) -> int:
    reserve = require_nonnegative_int(reserve, "reserve")
    protected_floor = require_nonnegative_int(protected_floor, "protected_floor")
    if protected_floor > reserve:
        raise Mega806Error("PROTECTED_FLOOR_EXCEEDS_RESERVE")
    if not 0 <= max_spend_ppm <= 1_000_000:
        raise Mega806Error("invalid max_spend_ppm")
    return (reserve - protected_floor) * max_spend_ppm // 1_000_000


def trigger_survival_stop(
    reserve: int, *, protected_floor: int, unknown_cost: int = 0
) -> bool:
    reserve = require_nonnegative_int(reserve, "reserve")
    protected_floor = require_nonnegative_int(protected_floor, "protected_floor")
    unknown_cost = require_nonnegative_int(unknown_cost, "unknown_cost")
    return reserve - unknown_cost <= protected_floor
