"""PR-256 / IMPACT-01: empirical market impact and capacity frontiers."""

from __future__ import annotations
from typing import Sequence
from .core import (
    Mega806Error,
    require_nonnegative_int,
    require_positive_int,
    require_ppm,
)


def fit_market_impact_curve(
    samples: Sequence[tuple[int, int]],
) -> tuple[tuple[int, int], ...]:
    if not samples:
        raise Mega806Error("impact samples are required")
    by_size: dict[int, list[int]] = {}
    for size, impact_ppm in samples:
        size = require_positive_int(size, "size")
        impact_ppm = require_nonnegative_int(impact_ppm, "impact_ppm")
        by_size.setdefault(size, []).append(impact_ppm)
    curve = []
    floor = 0
    for size in sorted(by_size):
        estimate = sum(by_size[size]) // len(by_size[size])
        floor = max(floor, estimate)
        curve.append((size, floor))
    return tuple(curve)


def estimate_capacity_frontier(
    curve: Sequence[tuple[int, int]],
    *,
    expected_edge_ppm: int,
    uncertainty_ppm: int = 0,
) -> int:
    expected_edge_ppm = require_nonnegative_int(expected_edge_ppm, "expected_edge_ppm")
    uncertainty_ppm = require_ppm(uncertainty_ppm, "uncertainty_ppm")
    budget = expected_edge_ppm - uncertainty_ppm
    if budget <= 0:
        return 0
    feasible = [size for size, impact in curve if impact < budget]
    return max(feasible, default=0)


def simulate_self_impact(
    size: int,
    curve: Sequence[tuple[int, int]],
    *,
    external_reaction_ppm: int = 0,
) -> int:
    size = require_positive_int(size, "size")
    external_reaction_ppm = require_nonnegative_int(
        external_reaction_ppm, "external_reaction_ppm"
    )
    eligible = [impact for bucket, impact in curve if bucket <= size]
    if not eligible:
        raise Mega806Error("OUTSIDE_IMPACT_SUPPORT")
    return max(eligible) + external_reaction_ppm


def cap_route_size_by_impact(requested_size: int, capacity_frontier: int) -> int:
    requested_size = require_positive_int(requested_size, "requested_size")
    capacity_frontier = require_nonnegative_int(capacity_frontier, "capacity_frontier")
    return min(requested_size, capacity_frontier)
