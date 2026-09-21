"""PR-261 / COUNTERPARTY-01: counterparty dependency graph."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega806Error, require_nonnegative_int, require_ppm, require_text


def register_counterparty_exposure(
    *,
    exposure_id: str,
    party: str,
    kind: str,
    amount: int,
    dependencies: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "id": require_text(exposure_id, "exposure_id"),
        "party": require_text(party, "party"),
        "kind": require_text(kind, "kind"),
        "amount": require_nonnegative_int(amount, "amount"),
        "dependencies": tuple(sorted(set(dependencies))),
    }


def propagate_dependency_failure(
    graph: Mapping[str, Sequence[str]], failed: Sequence[str]
) -> tuple[str, ...]:
    affected = set(failed)
    changed = True
    while changed:
        changed = False
        for node, deps in graph.items():
            if node not in affected and affected.intersection(deps):
                affected.add(node)
                changed = True
    return tuple(sorted(affected))


def score_bridge_custody_risk(
    exposures: Sequence[Mapping[str, object]], risk_ppm: Mapping[str, int]
) -> int:
    total = weighted = 0
    for row in exposures:
        amount = require_nonnegative_int(row.get("amount"), "amount")
        party = require_text(row.get("party"), "party")
        risk = require_ppm(risk_ppm.get(party, 1_000_000), f"risk:{party}")
        total += amount
        weighted += amount * risk
    if total == 0:
        raise Mega806Error("NO_EXPOSURE")
    return weighted // total


def enforce_counterparty_limits(
    exposures: Sequence[Mapping[str, object]], *, max_party_amount: int
) -> bool:
    max_party_amount = require_nonnegative_int(max_party_amount, "max_party_amount")
    totals: dict[str, int] = {}
    for row in exposures:
        party = require_text(row.get("party"), "party")
        totals[party] = totals.get(party, 0) + require_nonnegative_int(
            row.get("amount"), "amount"
        )
    if any(amount > max_party_amount for amount in totals.values()):
        raise Mega806Error("COUNTERPARTY_LIMIT_EXCEEDED")
    return True
