"""PR-267 / MEV-02: adversarial ordering counterfactuals."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega806Error, require_int, require_nonnegative_int


def inject_competing_transactions(
    baseline: Sequence[Mapping[str, object]],
    competitors: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    rows = [dict(row) for row in baseline] + [
        dict(row, counterfactual=True) for row in competitors
    ]
    return tuple(
        sorted(
            rows,
            key=lambda row: (int(row.get("order", 0)), str(row.get("id", ""))),
        )
    )


def simulate_adversarial_ordering(
    route_net: int, competing_deltas: Sequence[int]
) -> tuple[int, ...]:
    route_net = require_int(route_net, "route_net")
    outcomes = [route_net]
    cumulative = route_net
    for delta in competing_deltas:
        cumulative += require_int(delta, "competing_delta")
        outcomes.append(cumulative)
    return tuple(outcomes)


def estimate_mev_loss_envelope(
    route_net: int, counterfactual_outcomes: Sequence[int]
) -> int:
    route_net = require_int(route_net, "route_net")
    if not counterfactual_outcomes:
        raise Mega806Error("counterfactual outcomes are required")
    worst = min(require_int(x, "outcome") for x in counterfactual_outcomes)
    return max(0, route_net - worst)


def gate_ordering_fragility(
    route_net: int,
    counterfactual_outcomes: Sequence[int],
    *,
    max_loss: int,
) -> bool:
    max_loss = require_nonnegative_int(max_loss, "max_loss")
    loss = estimate_mev_loss_envelope(route_net, counterfactual_outcomes)
    if loss > max_loss or min(counterfactual_outcomes) <= 0:
        raise Mega806Error("ORDERING_FRAGILITY")
    return True
