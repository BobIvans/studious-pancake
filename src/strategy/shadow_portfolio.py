"""Conflict mapping into the existing finite PR356 portfolio owner."""

from __future__ import annotations
from dataclasses import dataclass
from src.research.pr356_allocation import solve_opportunity_portfolio
from src.strategy.conflict_scheduler import WorkResourceSet


@dataclass(frozen=True, slots=True)
class ShadowPortfolioCandidate:
    candidate_id: str
    expected_utility_units: int
    tail_loss_units: int
    resource_usage: tuple[tuple[str, int], ...]
    resources: WorkResourceSet


def allocate_shadow_portfolio(
    candidates: tuple[ShadowPortfolioCandidate, ...],
    *,
    budget: dict[str, int],
    max_selected: int,
    max_tail_loss_units: int,
):
    if type(max_selected) is not int or max_selected < 0:
        raise ValueError("max_selected requires nonnegative integer")
    if "shadow:selected-count" in budget:
        raise ValueError("reserved resource dimension")
    ids = [row.candidate_id for row in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate candidate")
    conflicts: dict[str, list[str]] = {row.candidate_id: [] for row in candidates}
    for i, left in enumerate(candidates):
        for right in candidates[i + 1 :]:
            if left.resources.conflicts_with(right.resources):
                key = "pair:" + repr(
                    tuple(sorted((left.candidate_id, right.candidate_id)))
                )
                conflicts[left.candidate_id].append(key)
                conflicts[right.candidate_id].append(key)
    rows = []
    for row in candidates:
        if len(dict(row.resource_usage)) != len(row.resource_usage):
            raise ValueError("duplicate resource dimension")
        rows.append(
            {
                "candidate_id": row.candidate_id,
                "expected_utility_units": row.expected_utility_units,
                "tail_loss_units": row.tail_loss_units,
                "resource_usage": {
                    **dict(row.resource_usage),
                    "shadow:selected-count": 1,
                },
                "conflict_keys": conflicts[row.candidate_id],
            }
        )
    return solve_opportunity_portfolio(
        {
            "candidates": rows,
            "budget": {**budget, "shadow:selected-count": max_selected},
            "max_tail_loss_units": max_tail_loss_units,
        }
    )
