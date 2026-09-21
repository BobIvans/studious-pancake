"""PR-283 / CREDIT-01: lending-rate spread research."""
from __future__ import annotations

from typing import Sequence

from .core import Mega807Error, RatePoint, require_nonnegative, stable_hash


def collect_lending_rate_curves(
    points: Sequence[RatePoint], *, cutoff: int
) -> tuple[RatePoint, ...]:
    require_nonnegative(cutoff, "cutoff")
    rows = [point for point in points if point.available_at <= cutoff]
    return tuple(
        sorted(rows, key=lambda point: (point.asset_id, point.market_id, point.available_at))
    )


def detect_borrow_supply_spread(
    supply: RatePoint, borrow: RatePoint
) -> int:
    if supply.asset_id != borrow.asset_id:
        raise Mega807Error("RATE_ASSET_MISMATCH")
    capacity = min(supply.capacity, borrow.capacity)
    if capacity <= 0:
        raise Mega807Error("RATE_CAPACITY_UNAVAILABLE")
    return supply.supply_rate_ppm - borrow.borrow_rate_ppm


def build_rate_arbitrage_plan(
    *,
    supply: RatePoint,
    borrow: RatePoint,
    amount: int,
    rebalance_cost: int,
) -> dict[str, int | str]:
    spread = detect_borrow_supply_spread(supply, borrow)
    if spread <= 0:
        raise Mega807Error("NO_POSITIVE_RATE_SPREAD")
    if amount <= 0 or amount > min(supply.capacity, borrow.capacity):
        raise Mega807Error("RATE_PLAN_CAPACITY_EXCEEDED")
    gross = amount * spread // 1_000_000
    net = gross - require_nonnegative(rebalance_cost, "rebalance_cost")
    return {
        "asset_id": supply.asset_id,
        "amount": amount,
        "spread_ppm": spread,
        "net_carry": net,
        "plan_sha256": stable_hash(
            "mega8-07-rate-plan",
            {
                "supply": supply.market_id,
                "borrow": borrow.market_id,
                "amount": amount,
                "spread": spread,
                "net": net,
            },
        ),
    }


def qualify_rate_strategy(
    plan: dict[str, int | str], *, minimum_net_carry: int, inventory_permission: bool
) -> bool:
    if not inventory_permission:
        raise Mega807Error("INVENTORY_PERMISSION_REQUIRED")
    net = int(plan["net_carry"])
    if net < minimum_net_carry:
        raise Mega807Error("RATE_STRATEGY_BELOW_MINIMUM")
    return True
