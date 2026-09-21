"""PR-311 / NF-936..940: matured-principal redemption routes."""

from __future__ import annotations

from typing import Any, Mapping

from .core import ContractResult, UltimateMegaError, record, require_nonnegative, require_positive, stable_hash


def classify_term_redemption_phase(
    *,
    block_timestamp: int,
    expiry_timestamp: int,
    contract_version: str,
) -> ContractResult:
    now = require_nonnegative(block_timestamp, "block_timestamp")
    expiry = require_nonnegative(expiry_timestamp, "expiry_timestamp")
    if not contract_version:
        raise UltimateMegaError("EXPIRY_BOUNDARY_UNKNOWN")
    phase = "POST_EXPIRY" if now >= expiry else "PRE_EXPIRY"
    return record(
        "classify_term_redemption_phase",
        {"phase": phase, "block_timestamp": now, "expiry_timestamp": expiry, "contract_version": contract_version},
    )


def bind_matured_principal_index(
    *,
    phase: str,
    stored_index_num: int,
    stored_index_den: int,
    refreshed_index_num: int | None = None,
    refreshed_index_den: int | None = None,
) -> ContractResult:
    if phase != "POST_EXPIRY":
        raise UltimateMegaError("POST_EXPIRY_DATA_MISSING")
    num = require_positive(stored_index_num, "stored_index_num")
    den = require_positive(stored_index_den, "stored_index_den")
    if (refreshed_index_num is None) != (refreshed_index_den is None):
        raise UltimateMegaError("POST_EXPIRY_DATA_MISSING")
    if refreshed_index_num is not None:
        num = require_positive(refreshed_index_num, "refreshed_index_num")
        den = require_positive(int(refreshed_index_den), "refreshed_index_den")
    return record(
        "bind_matured_principal_index",
        {"phase": phase, "index_fraction": (num, den), "refreshed": refreshed_index_num is not None},
    )


def quote_matured_pt_cash_exit(
    *,
    pt_amount: int,
    index_num: int,
    index_den: int,
    sy_exit_num: int,
    sy_exit_den: int,
    exit_capacity: int,
    async_exit: bool = False,
) -> ContractResult:
    if async_exit:
        raise UltimateMegaError("ASYNC_SY_EXIT")
    pt = require_nonnegative(pt_amount, "pt_amount")
    idx_num = require_positive(index_num, "index_num")
    idx_den = require_positive(index_den, "index_den")
    sy_num = require_positive(sy_exit_num, "sy_exit_num")
    sy_den = require_positive(sy_exit_den, "sy_exit_den")
    cap = require_nonnegative(exit_capacity, "exit_capacity")
    sy = pt * idx_num // idx_den
    cash = sy * sy_num // sy_den
    if cash > cap:
        raise UltimateMegaError("CAPACITY_SHORTFALL")
    return record(
        "quote_matured_pt_cash_exit",
        {"pt_amount": pt, "sy_amount": sy, "cash_output": cash, "interest_counted_as_principal": False},
    )


def build_matured_pt_route(
    quote: Mapping[str, Any],
    *,
    abi_verified: bool,
    deployment_verified: bool,
    license_allowed: bool,
) -> ContractResult:
    if not (abi_verified and deployment_verified and license_allowed):
        raise UltimateMegaError("REDEMPTION_UNSUPPORTED")
    return record(
        "build_matured_pt_route",
        {"quote_hash": stable_hash("matured-pt-quote", quote), "unsigned": True, "all_legs_immediate": True},
    )


def evaluate_maturity_boundary_episode(
    *,
    pre_refresh_edge: int,
    post_refresh_edge: int,
    fees: int,
    competition_cost: int,
) -> ContractResult:
    post = post_refresh_edge - require_nonnegative(fees, "fees") - require_nonnegative(competition_cost, "competition_cost")
    status = "OK" if post > 0 else "BLOCKED"
    return record(
        "evaluate_maturity_boundary_episode",
        {"pre_refresh_edge": pre_refresh_edge, "post_refresh_edge": post_refresh_edge, "net_after_refresh": post},
        status=status,
        blockers=() if post > 0 else ("THEORETICAL_ONLY_PARITY",),
    )
