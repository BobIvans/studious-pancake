"""PR-172 / SOLVER-04: bounded mixed route/flow allocation."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from .core import Mega802Error, require_nonnegative_int, require_positive_int


@dataclass(frozen=True, slots=True)
class MixedRoute:
    route_id: str
    unit_net: int
    capacity: int


def formulate_mixed_route_problem(
    routes: Sequence[MixedRoute], *, amount: int
) -> tuple[tuple[MixedRoute, ...], int]:
    require_positive_int(amount, "amount")
    if not routes:
        raise Mega802Error("NO_ROUTE_VARIANTS")
    return tuple(sorted(routes, key=lambda item: item.route_id)), amount


def solve_discrete_route_choice(routes: Sequence[MixedRoute]) -> tuple[MixedRoute, ...]:
    eligible = [route for route in routes if route.unit_net > 0 and route.capacity > 0]
    if not eligible:
        raise Mega802Error("NO_FEASIBLE_ROUTE")
    return tuple(sorted(eligible, key=lambda r: (-r.unit_net, r.route_id)))


def solve_continuous_flow_allocation(
    routes: Sequence[MixedRoute], *, amount: int
) -> tuple[tuple[str, int], ...]:
    remaining = require_positive_int(amount, "amount")
    allocations: list[tuple[str, int]] = []
    for route in solve_discrete_route_choice(routes):
        take = min(remaining, require_nonnegative_int(route.capacity, "capacity"))
        if take:
            allocations.append((route.route_id, take))
            remaining -= take
        if not remaining:
            break
    if remaining:
        raise Mega802Error("INSUFFICIENT_ROUTE_CAPACITY")
    return tuple(allocations)


def verify_solver_optimality_gap(
    achieved_net: int, upper_bound_net: int, *, max_gap: int
) -> int:
    if upper_bound_net < achieved_net:
        raise Mega802Error("INVALID_UPPER_BOUND")
    gap = upper_bound_net - achieved_net
    if gap > max_gap:
        raise Mega802Error("OPTIMALITY_GAP_TOO_LARGE")
    return gap
