"""PR-262 / ECON-02: endogenous alpha capacity and saturation."""

from __future__ import annotations
from typing import Sequence
from .core import Mega806Error, require_int, require_nonnegative_int, require_ppm


def estimate_alpha_capacity(observations: Sequence[tuple[int, int]]) -> int:
    if not observations:
        raise Mega806Error("observations are required")
    feasible = []
    for size, realized_net in observations:
        size = require_nonnegative_int(size, "size")
        realized_net = require_int(realized_net, "realized_net")
        if size > 0 and realized_net > 0:
            feasible.append(size)
    return max(feasible, default=0)


def model_self_crowding_decay(baseline_net: int, *, overlap_ppm: int) -> int:
    baseline_net = require_int(baseline_net, "baseline_net")
    overlap_ppm = require_ppm(overlap_ppm, "overlap_ppm")
    if baseline_net <= 0:
        return baseline_net
    return baseline_net * (1_000_000 - overlap_ppm) // 1_000_000


def detect_strategy_saturation(observations: Sequence[tuple[int, int]]) -> bool:
    if len(observations) < 3:
        return False
    ordered = sorted(observations)
    recent = [require_int(net, "net") for _, net in ordered[-3:]]
    return recent[0] >= recent[1] >= recent[2]


def throttle_capacity_usage(
    requested: int,
    *,
    qualified_capacity: int,
    saturation: bool,
    reduction_ppm: int = 500_000,
) -> int:
    requested = require_nonnegative_int(requested, "requested")
    qualified_capacity = require_nonnegative_int(
        qualified_capacity, "qualified_capacity"
    )
    reduction_ppm = require_ppm(reduction_ppm, "reduction_ppm")
    cap = qualified_capacity
    if saturation:
        cap = cap * (1_000_000 - reduction_ppm) // 1_000_000
    return min(requested, cap)
