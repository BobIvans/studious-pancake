"""PR-314 / NF-951..955: Clipper auction clock/reset/callback accounting."""

from __future__ import annotations

from typing import Any, Mapping

from .core import ContractResult, UltimateMegaError, record, require_int, require_nonnegative, require_positive, stable_hash


def read_clipper_sale_envelope(
    *,
    auction_id: str,
    lot_wad: int,
    tab_rad: int,
    top_ray: int,
    tic: int,
    current_price_ray: int,
    status_current: bool,
) -> ContractResult:
    if not status_current:
        raise UltimateMegaError("STATE_INCOMPLETE")
    lot = require_nonnegative(lot_wad, "lot_wad")
    tab = require_nonnegative(tab_rad, "tab_rad")
    price = require_positive(current_price_ray, "current_price_ray")
    if lot == 0 or tab == 0:
        raise UltimateMegaError("SALE_FINISHED")
    return record(
        "read_clipper_sale_envelope",
        {"auction_id": auction_id, "lot_wad": lot, "tab_rad": tab, "top_ray": require_positive(top_ray, "top_ray"), "tic": require_nonnegative(tic, "tic"), "current_price_ray": price},
    )


def classify_clipper_take_or_reset(
    *,
    needs_redo: bool,
    current_price_ray: int,
    max_price_ray: int,
) -> ContractResult:
    price = require_positive(current_price_ray, "current_price_ray")
    cap = require_positive(max_price_ray, "max_price_ray")
    if needs_redo:
        return record(
            "classify_clipper_take_or_reset",
            {"action": "REDO", "price": price},
            status="BLOCKED",
            blockers=("RESET_REQUIRED",),
        )
    if price > cap:
        raise UltimateMegaError("PRICE_LIMIT_EXCEEDED")
    return record("classify_clipper_take_or_reset", {"action": "TAKE", "price": price, "max_price": cap})


def size_clipper_collateral_bid(
    *,
    lot_wad: int,
    tab_rad: int,
    price_ray: int,
    max_collateral_wad: int,
    exit_value_rad_per_wad: int,
    chost_rad: int = 0,
) -> ContractResult:
    lot = require_nonnegative(lot_wad, "lot_wad")
    tab = require_nonnegative(tab_rad, "tab_rad")
    price = require_positive(price_ray, "price_ray")
    cap = min(lot, require_nonnegative(max_collateral_wad, "max_collateral_wad"))
    exit_value = require_positive(exit_value_rad_per_wad, "exit_value_rad_per_wad")
    cost = cap * price
    proceeds = cap * exit_value
    remaining = max(0, tab - cost)
    dust = require_nonnegative(chost_rad, "chost_rad")
    if remaining and remaining < dust:
        raise UltimateMegaError("DUST_CONSTRAINT")
    if proceeds <= cost:
        raise UltimateMegaError("EXIT_NOT_PROFITABLE")
    return record(
        "size_clipper_collateral_bid",
        {"collateral_wad": cap, "cost_rad": cost, "exit_proceeds_rad": proceeds, "remaining_tab_rad": remaining},
    )


def compose_clipper_callback_settlement(
    bid: Mapping[str, Any],
    *,
    callback_caller: str,
    expected_caller: str,
    payment_rad: int,
) -> ContractResult:
    if callback_caller != expected_caller:
        raise UltimateMegaError("CALLBACK_SPOOF")
    required = require_nonnegative(int(bid.get("cost_rad", 0)), "cost_rad")
    payment = require_nonnegative(payment_rad, "payment_rad")
    if payment < required:
        raise UltimateMegaError("INCOMPLETE_PAYMENT")
    return record(
        "compose_clipper_callback_settlement",
        {"bid_hash": stable_hash("clipper-bid", bid), "payment_rad": payment, "unsigned": True, "callback_bound": True},
    )


def reconcile_clipper_sale_attempt(
    *,
    collateral_value: int,
    payment: int,
    keeper_reward: int,
    fees: int,
    finalized: bool,
) -> ContractResult:
    value = require_nonnegative(collateral_value, "collateral_value")
    paid = require_nonnegative(payment, "payment")
    reward = require_nonnegative(keeper_reward, "keeper_reward")
    fee = require_nonnegative(fees, "fees")
    residual = value + reward - paid - fee
    return record(
        "reconcile_clipper_sale_attempt",
        {"collateral_value": value, "payment": paid, "keeper_reward": reward, "fees": fee, "realized_residual": residual},
        status="OK" if finalized else "UNKNOWN",
        blockers=() if finalized else ("OUTCOME_UNKNOWN",),
    )
