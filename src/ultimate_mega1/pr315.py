"""PR-315 / NF-956..960: opt-in Morpho pre-liquidation qualification."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_nonnegative, require_positive, stable_hash


def resolve_borrower_preliquidation_rights(
    *,
    borrower: str,
    position_id: str,
    authorized_positions: Sequence[str],
    revoked: bool = False,
) -> ContractResult:
    if revoked:
        raise UltimateMegaError("REVOKED_AUTHORIZATION")
    if position_id not in set(authorized_positions):
        raise UltimateMegaError("NOT_OPTED_IN")
    return record(
        "resolve_borrower_preliquidation_rights",
        {"borrower": borrower, "position_id": position_id, "authorized": True},
    )


def evaluate_preliquidation_band(
    *,
    collateral_value: int,
    debt_value: int,
    pre_lltv_ppm: int,
    market_lltv_ppm: int,
    oracle_valid: bool,
) -> ContractResult:
    if not oracle_valid:
        raise UltimateMegaError("ORACLE_INVALID")
    collateral = require_positive(collateral_value, "collateral_value")
    debt = require_nonnegative(debt_value, "debt_value")
    pre = require_nonnegative(pre_lltv_ppm, "pre_lltv_ppm")
    market = require_nonnegative(market_lltv_ppm, "market_lltv_ppm")
    if not 0 <= pre < market <= 1_000_000:
        raise UltimateMegaError("INVALID_LTV_CONFIG")
    observed = debt * 1_000_000 // collateral
    eligible = pre <= observed < market
    if not eligible:
        raise UltimateMegaError("OUTSIDE_PRELIQ_BAND")
    return record(
        "evaluate_preliquidation_band",
        {"observed_ltv_ppm": observed, "pre_lltv_ppm": pre, "market_lltv_ppm": market, "eligible": True},
    )


def size_authorized_preliquidation(
    *,
    debt: int,
    close_factor_ppm: int,
    collateral_exit_capacity: int,
    seizure_value_per_debt_ppm: int,
) -> ContractResult:
    debt = require_nonnegative(debt, "debt")
    close = require_nonnegative(close_factor_ppm, "close_factor_ppm")
    if close > 1_000_000:
        raise UltimateMegaError("CLOSE_FACTOR_VIOLATION")
    repay = debt * close // 1_000_000
    seized = repay * require_nonnegative(seizure_value_per_debt_ppm, "seizure_value_per_debt_ppm") // 1_000_000
    cap = require_nonnegative(collateral_exit_capacity, "collateral_exit_capacity")
    if seized > cap:
        raise UltimateMegaError("INSUFFICIENT_EXIT")
    return record("size_authorized_preliquidation", {"debt_repaid": repay, "seized_value": seized, "close_factor_ppm": close})


def bind_preliquidation_callback(
    quote: Mapping[str, Any],
    *,
    callback_identity: str,
    expected_callback_identity: str,
    collateral_received: int,
    debt_repaid: int,
) -> ContractResult:
    if callback_identity != expected_callback_identity:
        raise UltimateMegaError("UNTRUSTED_CALLBACK")
    required = require_nonnegative(int(quote.get("debt_repaid", 0)), "required_repayment")
    repaid = require_nonnegative(debt_repaid, "debt_repaid")
    if repaid < required:
        raise UltimateMegaError("REPAYMENT_SHORTFALL")
    return record(
        "bind_preliquidation_callback",
        {"quote_hash": stable_hash("preliq-quote", quote), "collateral_received": require_nonnegative(collateral_received, "collateral_received"), "debt_repaid": repaid, "callback_bound": True},
    )


def publish_preliquidation_class_evidence(
    episodes: Sequence[Mapping[str, Any]],
    *,
    authorization_coverage_complete: bool,
) -> ContractResult:
    if not authorization_coverage_complete:
        raise UltimateMegaError("AUTHORIZATION_COVERAGE_MISSING")
    market_configs = tuple(sorted({str((x.get("market_id"), x.get("config_hash"))) for x in episodes}))
    return record(
        "publish_preliquidation_class_evidence",
        {"episode_count": len(episodes), "market_config_classes": market_configs, "ordinary_liquidation_labels_reused": False},
    )
