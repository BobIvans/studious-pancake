"""PR-286 / LIQ-04: cross-protocol liquidation portfolio research."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .core import Mega807Error, require_nonnegative, stable_hash


@dataclass(frozen=True, slots=True)
class LiquidationMechanism:
    mechanism_id: str
    protocol_id: str
    collateral_asset: str
    gross_value: int
    unwind_value: int
    failure_cost: int
    capital_required: int
    resource_id: str


def index_cross_protocol_liquidations(
    mechanisms: Sequence[LiquidationMechanism],
) -> tuple[LiquidationMechanism, ...]:
    ids = [item.mechanism_id for item in mechanisms]
    if len(ids) != len(set(ids)):
        raise Mega807Error("DUPLICATE_LIQUIDATION_MECHANISM")
    return tuple(
        sorted(mechanisms, key=lambda item: (item.protocol_id, item.mechanism_id))
    )


def value_protocol_owned_collateral(
    mechanism: LiquidationMechanism,
) -> int:
    gross = require_nonnegative(mechanism.gross_value, "gross_value")
    unwind = require_nonnegative(mechanism.unwind_value, "unwind_value")
    failure = require_nonnegative(mechanism.failure_cost, "failure_cost")
    return min(gross, unwind) - failure


def allocate_liquidation_capital(
    mechanisms: Sequence[LiquidationMechanism], *, capital_budget: int
) -> tuple[str, ...]:
    mechanisms = index_cross_protocol_liquidations(mechanisms)
    remaining = require_nonnegative(capital_budget, "capital_budget")
    selected: list[str] = []
    used_resources: set[str] = set()
    ranked = sorted(
        mechanisms,
        key=lambda item: (-value_protocol_owned_collateral(item), item.mechanism_id),
    )
    for item in ranked:
        required = require_nonnegative(item.capital_required, "capital_required")
        if item.resource_id in used_resources or required > remaining:
            continue
        if value_protocol_owned_collateral(item) <= 0:
            continue
        selected.append(item.mechanism_id)
        used_resources.add(item.resource_id)
        remaining -= required
    return tuple(selected)


def reconcile_liquidation_portfolio(
    selected_ids: Sequence[str],
    finalized_outcomes: Mapping[str, int],
) -> dict[str, int | str]:
    if len(selected_ids) != len(set(selected_ids)):
        raise Mega807Error("DUPLICATE_SELECTED_LIQUIDATION")
    if set(selected_ids) != set(finalized_outcomes):
        raise Mega807Error("LIQUIDATION_PORTFOLIO_OUTCOME_GAP")
    total = sum(int(finalized_outcomes[item]) for item in selected_ids)
    payload = {"selected": tuple(sorted(selected_ids)), "finalized_total": total}
    return {
        "finalized_total": total,
        "portfolio_sha256": stable_hash("mega8-07-liquidation-portfolio", payload),
    }
