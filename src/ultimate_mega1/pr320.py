"""PR-320 / NF-981..985: short-borrow entitlement, expiry and recall risk."""

from __future__ import annotations

from typing import Any, Mapping

from .core import ContractResult, UltimateMegaError, record, require_nonnegative, require_positive, stable_hash


def capture_short_borrow_entitlement(
    *,
    account_scope: str,
    asset: str,
    borrowable_limit: int,
    utilised_amount: int,
    available_at: int,
    valid_until: int,
    read_only_authorized: bool,
) -> ContractResult:
    if not read_only_authorized:
        raise UltimateMegaError("PRIVATE_ACCESS_NOT_AUTHORIZED")
    limit = require_nonnegative(borrowable_limit, "borrowable_limit")
    used = require_nonnegative(utilised_amount, "utilised_amount")
    if used > limit:
        raise UltimateMegaError("NO_BORROW_CAPACITY")
    available = limit - used
    if available <= 0:
        raise UltimateMegaError("NO_BORROW_CAPACITY")
    start = require_nonnegative(available_at, "available_at")
    end = require_nonnegative(valid_until, "valid_until")
    if end <= start:
        raise UltimateMegaError("ENTITLEMENT_EXPIRED")
    return record(
        "capture_short_borrow_entitlement",
        {"account_scope": account_scope, "asset": asset, "borrowable_limit": limit, "utilised_amount": used, "available_amount": available, "available_at": start, "valid_until": end, "borrow_call_made": False},
    )


def bind_short_leg_to_borrow_window(
    entitlement: Mapping[str, Any],
    *,
    hedge_amount: int,
    hedge_close_time: int,
) -> ContractResult:
    amount = require_nonnegative(hedge_amount, "hedge_amount")
    if amount > int(entitlement.get("available_amount", 0)):
        raise UltimateMegaError("NO_BORROW_CAPACITY")
    close_time = require_nonnegative(hedge_close_time, "hedge_close_time")
    if close_time > int(entitlement.get("valid_until", -1)):
        raise UltimateMegaError("ENTITLEMENT_EXPIRED")
    return record(
        "bind_short_leg_to_borrow_window",
        {"entitlement_hash": stable_hash("borrow-entitlement", entitlement), "hedge_amount": amount, "hedge_close_time": close_time, "venue_reservation_guaranteed": False},
    )


def simulate_borrow_recall_path(
    *,
    open_exposure: int,
    executable_cover_capacity: int,
    cover_price_per_unit: int,
    collateral_buffer: int,
) -> ContractResult:
    exposure = require_nonnegative(open_exposure, "open_exposure")
    capacity = require_nonnegative(executable_cover_capacity, "executable_cover_capacity")
    if capacity < exposure:
        raise UltimateMegaError("NO_EXECUTABLE_COVER")
    price = require_nonnegative(cover_price_per_unit, "cover_price_per_unit")
    buffer = require_nonnegative(collateral_buffer, "collateral_buffer")
    cost = exposure * price
    return record(
        "simulate_borrow_recall_path",
        {"exposure": exposure, "cover_capacity": capacity, "cover_cost": cost, "collateral_buffer": buffer, "buffer_after_cover": buffer - cost},
    )


def invalidate_short_admission_on_recall(
    *,
    entitlement_id: str,
    recall_observed: bool,
    recall_semantics_known: bool,
) -> ContractResult:
    if not recall_semantics_known:
        raise UltimateMegaError("UNKNOWN_RECALL_SEMANTICS")
    return record(
        "invalidate_short_admission_on_recall",
        {"entitlement_id": entitlement_id, "new_short_admission": not recall_observed, "oms_handoff_required": recall_observed, "trade_submitted": False},
        status="BLOCKED" if recall_observed else "OK",
        blockers=("BORROW_RECALLED",) if recall_observed else (),
    )


def reconcile_borrow_term_costs(
    *,
    principal: int,
    accrued_interest: int,
    fees: int,
    repaid: int,
    repayment_verified: bool,
) -> ContractResult:
    if not repayment_verified:
        raise UltimateMegaError("REPAYMENT_UNVERIFIED")
    principal = require_nonnegative(principal, "principal")
    interest = require_nonnegative(accrued_interest, "accrued_interest")
    fee = require_nonnegative(fees, "fees")
    repaid = require_nonnegative(repaid, "repaid")
    liability = max(0, principal + interest + fee - repaid)
    return record(
        "reconcile_borrow_term_costs",
        {"principal": principal, "interest": interest, "fees": fee, "repaid": repaid, "outstanding_liability": liability, "realised_cost": interest + fee},
    )
