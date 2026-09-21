"""PR-287 / NF-833..836: LLAMMA soft-liquidation research contracts."""

from __future__ import annotations
from typing import Mapping
from .core import Mega808Error, Result, require_int, require_nonnegative, require_positive, result, stable_hash


def decode_llamma_state(state: Mapping[str, int | str], *, expected_market: str) -> Result:
    if state.get("market") != expected_market:
        raise Mega808Error("MARKET_IDENTITY_MISMATCH")
    band = require_int(int(state.get("active_band", 0)), "active_band")
    oracle = require_positive(int(state.get("oracle_price", 0)), "oracle_price")
    collateral = require_nonnegative(int(state.get("collateral", 0)), "collateral")
    debt = require_nonnegative(int(state.get("debt", 0)), "debt")
    return result("decode_llamma_state", {"market": expected_market, "active_band": band, "oracle_price": oracle, "collateral": collateral, "debt": debt, "state_hash": stable_hash("llamma-state", dict(state))})


def model_soft_liquidation_band(*, active_band: int, lower_price: int, upper_price: int, oracle_price: int) -> Result:
    band = require_int(active_band, "active_band")
    lower = require_positive(lower_price, "lower_price")
    upper = require_positive(upper_price, "upper_price")
    oracle = require_positive(oracle_price, "oracle_price")
    if lower >= upper:
        raise Mega808Error("INVALID_BAND_RANGE")
    phase = "BELOW" if oracle < lower else "ABOVE" if oracle > upper else "IN_BAND"
    return result("model_soft_liquidation_band", {"active_band": band, "lower_price": lower, "upper_price": upper, "oracle_price": oracle, "phase": phase})


def quote_llamma_exit(*, collateral_units: int, execution_price: int, fee_ppm: int, executable_capacity: int) -> Result:
    collateral = require_nonnegative(collateral_units, "collateral_units")
    price = require_positive(execution_price, "execution_price")
    fee = require_nonnegative(fee_ppm, "fee_ppm")
    if fee > 1_000_000:
        raise Mega808Error("FEE_OUT_OF_RANGE")
    capacity = require_nonnegative(executable_capacity, "executable_capacity")
    sold = min(collateral, capacity)
    gross = sold * price
    net = gross - gross * fee // 1_000_000
    return result("quote_llamma_exit", {"collateral_sold": sold, "gross": gross, "net": net, "capacity_shortfall": collateral - sold})


def qualify_llamma_route(quote: Mapping[str, object], *, fork_simulation_passed: bool, deployment_verified: bool) -> Result:
    blockers=()
    if not deployment_verified:
        blockers+=("DEPLOYMENT_UNVERIFIED",)
    if not fork_simulation_passed:
        blockers+=("EVM_SIMULATION_FAILED",)
    return result("qualify_llamma_route", {"quote_hash": stable_hash("llamma-quote", dict(quote)), "qualified": not blockers, "research_only": True}, status="OK" if not blockers else "BLOCKED", blockers=blockers)
