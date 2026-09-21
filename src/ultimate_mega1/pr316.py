"""PR-316 / NF-961..965: seized LP/vault collateral basket unwind."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_int, require_nonnegative, require_positive, stable_hash


def attest_liquidatable_wrapper_family(
    *,
    lender_id: str,
    wrapper_id: str,
    lender_allowlist: Sequence[str],
    deployment_verified: bool,
) -> ContractResult:
    if wrapper_id not in set(lender_allowlist) or not deployment_verified:
        raise UltimateMegaError("UNSUPPORTED_COLLATERAL_TYPE")
    return record(
        "attest_liquidatable_wrapper_family",
        {"lender_id": lender_id, "wrapper_id": wrapper_id, "supported": True, "deployment_verified": True},
    )


def expand_seized_collateral_outputs(
    *,
    seized_shares: int,
    outputs_per_share: Mapping[str, tuple[int, int]],
    fees: Mapping[str, int] | None = None,
    delayed_assets: Sequence[str] = (),
) -> ContractResult:
    shares = require_nonnegative(seized_shares, "seized_shares")
    fee_map = dict(fees or {})
    outputs: dict[str, int] = {}
    delayed = set(delayed_assets)
    if delayed:
        raise UltimateMegaError("DELAYED_REDEMPTION")
    for asset, ratio in outputs_per_share.items():
        if len(ratio) != 2:
            raise UltimateMegaError("RESTRICTED_UNWRAP")
        num = require_nonnegative(ratio[0], f"{asset}_num")
        den = require_positive(ratio[1], f"{asset}_den")
        gross = shares * num // den
        fee = require_nonnegative(fee_map.get(asset, 0), f"{asset}_fee")
        outputs[asset] = max(0, gross - fee)
    return record("expand_seized_collateral_outputs", {"seized_shares": shares, "outputs": outputs})


def solve_basket_to_debt_unwind(
    basket: Mapping[str, int],
    quotes: Mapping[str, Mapping[str, Any]],
    *,
    debt_required: int,
) -> ContractResult:
    required = require_nonnegative(debt_required, "debt_required")
    proceeds = 0
    resource_usage: dict[str, int] = defaultdict(int)
    legs = []
    for asset, amount in sorted(basket.items()):
        amount = require_nonnegative(amount, f"basket_{asset}")
        quote = quotes.get(asset)
        if quote is None:
            continue
        capacity = require_nonnegative(int(quote.get("capacity", 0)), f"capacity_{asset}")
        use = min(amount, capacity)
        resource = str(quote.get("resource_id", asset))
        max_resource = require_nonnegative(int(quote.get("resource_capacity", capacity)), f"resource_capacity_{asset}")
        resource_usage[resource] += use
        if resource_usage[resource] > max_resource:
            raise UltimateMegaError("SHARED_LIQUIDITY_DOUBLE_COUNT")
        rate_num = require_nonnegative(int(quote.get("rate_num", 0)), f"rate_num_{asset}")
        rate_den = require_positive(int(quote.get("rate_den", 1)), f"rate_den_{asset}")
        out = use * rate_num // rate_den
        proceeds += out
        legs.append((asset, use, out, resource))
    if proceeds < required:
        raise UltimateMegaError("UNFUNDED_INTERMEDIATE")
    return record(
        "solve_basket_to_debt_unwind",
        {"legs": tuple(legs), "proceeds": proceeds, "debt_required": required, "residual_proceeds": proceeds - required},
    )


def compile_liquidation_basket_obligations(
    plan: Mapping[str, Any],
    *,
    debt_repayment: int,
    cleanup_obligations: Sequence[str],
    own_inventory_floor: int,
    own_inventory_after: int,
) -> ContractResult:
    repayment = require_nonnegative(debt_repayment, "debt_repayment")
    floor = require_nonnegative(own_inventory_floor, "own_inventory_floor")
    after = require_nonnegative(own_inventory_after, "own_inventory_after")
    if after < floor:
        raise UltimateMegaError("NATIVE_BUDGET_SHORTFALL")
    return record(
        "compile_liquidation_basket_obligations",
        {"plan_hash": stable_hash("basket-unwind-plan", plan), "debt_repayment": repayment, "cleanup_obligations": tuple(cleanup_obligations), "own_inventory_floor": floor, "unsigned": True},
    )


def verify_basket_liquidation_conservation(
    *,
    inputs: Mapping[str, int],
    outputs: Mapping[str, int],
    fees: Mapping[str, int],
    unexplained: Mapping[str, int] | None = None,
) -> ContractResult:
    unexplained = dict(unexplained or {})
    if any(v for v in unexplained.values()):
        raise UltimateMegaError("INCOMPLETE_WITNESS")
    currencies = sorted(set(inputs) | set(outputs) | set(fees))
    residuals = {}
    for asset in currencies:
        residuals[asset] = require_int(outputs.get(asset, 0), f"out_{asset}") - require_int(inputs.get(asset, 0), f"in_{asset}") - require_nonnegative(fees.get(asset, 0), f"fee_{asset}")
    return record(
        "verify_basket_liquidation_conservation",
        {"residuals": residuals, "nav_only_profit": False, "conservation_evidence_hash": stable_hash("basket-conservation", residuals)},
    )
