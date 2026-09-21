"""PR-171 / SOLVER-03: multi-objective Pareto route selection."""

from __future__ import annotations
from typing import Iterable, Mapping
from .core import Mega802Error, ObjectiveVector, pareto_frontier_core


def score_route_objectives(
    *,
    candidate_id: str,
    conservative_net: int,
    duration_us: int,
    resource_cost: int,
    uncertainty: int,
    contention_ppm: int,
) -> ObjectiveVector:
    return ObjectiveVector(
        candidate_id,
        conservative_net,
        duration_us,
        resource_cost,
        uncertainty,
        contention_ppm,
    )


def build_pareto_frontier(
    rows: Iterable[ObjectiveVector],
) -> tuple[ObjectiveVector, ...]:
    return pareto_frontier_core(rows)


def select_policy_constrained_route(
    frontier: Iterable[ObjectiveVector],
    *,
    max_duration_us: int,
    max_uncertainty: int,
    max_contention_ppm: int,
) -> ObjectiveVector:
    eligible = [
        row
        for row in frontier
        if row.duration_us <= max_duration_us
        and row.uncertainty <= max_uncertainty
        and row.contention_ppm <= max_contention_ppm
        and row.conservative_net > 0
    ]
    if not eligible:
        raise Mega802Error("NO_POLICY_ELIGIBLE_ROUTE")
    return max(
        eligible,
        key=lambda row: (
            row.conservative_net,
            -row.resource_cost,
            -row.duration_us,
            row.candidate_id,
        ),
    )


def explain_tradeoff_selection(
    selected: ObjectiveVector, frontier: Iterable[ObjectiveVector]
) -> Mapping[str, object]:
    return {
        "selected": selected.candidate_id,
        "frontier": tuple(sorted(row.candidate_id for row in frontier)),
        "conservative_net": selected.conservative_net,
        "duration_us": selected.duration_us,
        "resource_cost": selected.resource_cost,
        "uncertainty": selected.uncertainty,
        "contention_ppm": selected.contention_ppm,
    }
