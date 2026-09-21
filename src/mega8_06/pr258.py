"""PR-258 / PORTFOLIO-02: bounded opportunity portfolio allocation."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega806Error, require_int, require_nonnegative_int, require_text


def build_opportunity_portfolio(
    candidates: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    rows = []
    seen = set()
    for candidate in candidates:
        cid = require_text(candidate.get("id"), "id")
        if cid in seen:
            raise Mega806Error("DUPLICATE_CANDIDATE")
        seen.add(cid)
        row = dict(candidate)
        row["capital"] = require_nonnegative_int(candidate.get("capital"), "capital")
        row["tail_loss"] = require_nonnegative_int(
            candidate.get("tail_loss", 0), "tail_loss"
        )
        row["expected_net"] = require_int(candidate.get("expected_net"), "expected_net")
        row["resources"] = tuple(sorted(set(candidate.get("resources", ()))))
        row["book"] = require_text(candidate.get("book", "atomic"), "book")
        rows.append(row)
    return tuple(sorted(rows, key=lambda row: str(row["id"])))


def estimate_cross_strategy_dependencies(
    candidates: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    rows = []
    for index, left in enumerate(candidates):
        left_resources = set(left.get("resources", ()))
        for right in candidates[index + 1 :]:
            shared = tuple(sorted(left_resources & set(right.get("resources", ()))))
            if shared:
                rows.append((str(left["id"]), str(right["id"]), shared))
    return tuple(rows)


def solve_portfolio_admission(
    candidates: Sequence[Mapping[str, object]],
    *,
    capital_budget: int,
    tail_budget: int,
) -> tuple[str, ...]:
    capital_budget = require_nonnegative_int(capital_budget, "capital_budget")
    tail_budget = require_nonnegative_int(tail_budget, "tail_budget")
    selected = []
    used_capital = used_tail = 0
    used_resources: set[str] = set()
    ordered = sorted(
        candidates,
        key=lambda row: (
            -int(row["expected_net"]),
            int(row["capital"]),
            str(row["id"]),
        ),
    )
    for row in ordered:
        capital = int(row["capital"])
        tail = int(row["tail_loss"])
        resources = set(row.get("resources", ()))
        if int(row["expected_net"]) <= 0 or resources & used_resources:
            continue
        if used_capital + capital > capital_budget or used_tail + tail > tail_budget:
            continue
        selected.append(str(row["id"]))
        used_capital += capital
        used_tail += tail
        used_resources |= resources
    return tuple(selected)


def reconcile_portfolio_outcomes(
    selected: Sequence[str], outcomes: Mapping[str, int | None]
) -> dict[str, object]:
    missing = tuple(sorted(cid for cid in selected if outcomes.get(cid) is None))
    realized = sum(
        int(outcomes[cid]) for cid in selected if outcomes.get(cid) is not None
    )
    return {
        "realized_net": realized,
        "unknown_children": missing,
        "freeze_conflicting_capital": bool(missing),
    }
