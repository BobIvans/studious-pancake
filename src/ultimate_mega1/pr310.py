"""PR-310 / NF-931..935: asynchronous vault claim lifecycle."""

from __future__ import annotations

from typing import Any, Mapping

from .core import ContractResult, UltimateMegaError, record, require_id, require_int, require_nonnegative, require_positive, stable_hash


def normalize_async_vault_claim(
    *,
    vault: str,
    controller: str,
    request_id: str,
    requested_shares: int,
    pending_shares: int,
    claimable_shares: int,
    claimable_assets: int,
) -> ContractResult:
    key = (
        require_id(vault, "vault"),
        require_id(controller, "controller"),
        require_id(request_id, "request_id"),
    )
    requested = require_nonnegative(requested_shares, "requested_shares")
    pending = require_nonnegative(pending_shares, "pending_shares")
    claimable = require_nonnegative(claimable_shares, "claimable_shares")
    assets = require_nonnegative(claimable_assets, "claimable_assets")
    if pending + claimable > requested:
        raise UltimateMegaError("ILLEGAL_TRANSITION")
    return record(
        "normalize_async_vault_claim",
        {
            "claim_key": key,
            "requested_shares": requested,
            "pending_shares": pending,
            "claimable_shares": claimable,
            "claimable_assets": assets,
        },
    )


_ALLOWED = {
    "REQUESTED": {"PENDING", "CLAIMABLE", "CANCELLED"},
    "PENDING": {"CLAIMABLE", "CANCELLED"},
    "CLAIMABLE": {"CLAIMED", "PARTIAL_CLAIM"},
    "PARTIAL_CLAIM": {"CLAIMED", "PARTIAL_CLAIM"},
    "CANCELLED": set(),
    "CLAIMED": set(),
}


def advance_async_claim_state(
    *,
    prior_state: str,
    next_state: str,
    event_id: str,
    extension_attested: bool = True,
) -> ContractResult:
    require_id(event_id, "event_id")
    if next_state not in _ALLOWED.get(prior_state, set()):
        raise UltimateMegaError("ILLEGAL_TRANSITION")
    if next_state == "CANCELLED" and not extension_attested:
        raise UltimateMegaError("UNATTESTED_EXTENSION")
    return record(
        "advance_async_claim_state",
        {"prior_state": prior_state, "next_state": next_state, "event_id": event_id},
    )


def price_claim_liquidity_discount(
    *,
    future_assets: int,
    holding_cost: int,
    funding_cost: int,
    custody_cost: int,
    executable_bid: int | None,
) -> ContractResult:
    future = require_nonnegative(future_assets, "future_assets")
    costs = sum(
        require_nonnegative(v, name)
        for v, name in (
            (holding_cost, "holding_cost"),
            (funding_cost, "funding_cost"),
            (custody_cost, "custody_cost"),
        )
    )
    if executable_bid is None:
        return record(
            "price_claim_liquidity_discount",
            {"future_assets": future, "costs": costs, "realizable_now": None},
            status="BLOCKED",
            blockers=("NO_REALIZABLE_EXIT",),
        )
    bid = require_nonnegative(executable_bid, "executable_bid")
    conservative = min(bid, max(0, future - costs))
    return record(
        "price_claim_liquidity_discount",
        {"future_assets": future, "costs": costs, "realizable_now": conservative},
    )


def plan_claim_acquisition_and_settlement(
    claim: Mapping[str, Any],
    *,
    transferable: bool,
    capital_lock: int,
    outstanding_flash_debt: int = 0,
) -> ContractResult:
    if not transferable:
        raise UltimateMegaError("CLAIM_NOT_TRANSFERABLE")
    if require_nonnegative(outstanding_flash_debt, "outstanding_flash_debt"):
        raise UltimateMegaError("FLASH_DEBT_WOULD_PERSIST")
    lock = require_nonnegative(capital_lock, "capital_lock")
    return record(
        "plan_claim_acquisition_and_settlement",
        {
            "claim_hash": stable_hash("async-claim", claim),
            "phases": ("ACQUIRE", "WAIT_CLAIMABLE", "CLAIM", "RECONCILE"),
            "capital_lock": lock,
            "atomic": False,
        },
    )


def reconcile_async_claim_cashflows(
    *,
    principal_paid: int,
    claimed_assets: int,
    fees: int,
    holding_time_seconds: int,
    complete: bool,
) -> ContractResult:
    principal = require_nonnegative(principal_paid, "principal_paid")
    assets = require_nonnegative(claimed_assets, "claimed_assets")
    fee = require_nonnegative(fees, "fees")
    hold = require_nonnegative(holding_time_seconds, "holding_time_seconds")
    pnl = assets - principal - fee
    blockers = () if complete else ("PARTIAL_CLAIM",)
    return record(
        "reconcile_async_claim_cashflows",
        {"principal": principal, "assets": assets, "fees": fee, "holding_time_seconds": hold, "realized_pnl": pnl},
        status="OK" if complete else "INCOMPLETE",
        blockers=blockers,
    )
