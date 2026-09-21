"""PR-282 / MARGIN-01: non-atomic collateral and leverage research."""
from __future__ import annotations

from typing import Mapping, Sequence

from .core import MarginRequirement, Mega807Error, require_nonnegative


def normalize_margin_requirements(
    requirements: Sequence[MarginRequirement],
) -> tuple[MarginRequirement, ...]:
    if not requirements:
        raise Mega807Error("MARGIN_REQUIREMENTS_REQUIRED")
    return tuple(
        sorted(requirements, key=lambda item: (item.venue_id, item.asset_id))
    )


def optimize_collateral_allocation(
    requirements: Sequence[MarginRequirement],
    collateral: Mapping[str, int],
) -> tuple[tuple[str, int], ...]:
    remaining = {
        asset: require_nonnegative(amount, asset)
        for asset, amount in collateral.items()
    }
    allocations: list[tuple[str, int]] = []
    for req in normalize_margin_requirements(requirements):
        available = remaining.get(req.asset_id, 0)
        if available <= 0:
            continue
        required = max(1, available * req.initial_margin_ppm // 1_000_000)
        take = min(available, required)
        remaining[req.asset_id] = available - take
        allocations.append((f"{req.venue_id}:{req.asset_id}", take))
    if not allocations:
        raise Mega807Error("NO_MARGIN_ALLOCATION")
    return tuple(allocations)


def simulate_margin_liquidation(
    *, collateral_value: int, debt_value: int, maintenance_margin_ppm: int,
    stress_loss: int,
) -> dict[str, int | bool]:
    collateral = require_nonnegative(collateral_value, "collateral_value")
    debt = require_nonnegative(debt_value, "debt_value")
    maintenance = require_nonnegative(
        maintenance_margin_ppm, "maintenance_margin_ppm"
    )
    loss = require_nonnegative(stress_loss, "stress_loss")
    stressed = max(0, collateral - loss)
    required = debt + debt * maintenance // 1_000_000
    return {
        "stressed_collateral": stressed,
        "required_collateral": required,
        "liquidatable": stressed < required,
    }


def gate_non_atomic_leverage(
    *, gross_exposure: int, equity: int, max_leverage_ppm: int
) -> bool:
    gross = require_nonnegative(gross_exposure, "gross_exposure")
    equity_value = require_nonnegative(equity, "equity")
    cap = require_nonnegative(max_leverage_ppm, "max_leverage_ppm")
    if equity_value == 0:
        raise Mega807Error("ZERO_EQUITY")
    leverage_ppm = gross * 1_000_000 // equity_value
    if leverage_ppm > cap:
        raise Mega807Error("NON_ATOMIC_LEVERAGE_BLOCKED")
    return True
