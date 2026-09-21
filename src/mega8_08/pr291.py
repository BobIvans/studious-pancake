"""PR-291 / NF-849..852: term-market maturity and fixed-rate parity."""

from __future__ import annotations
from typing import Mapping
from .core import Mega808Error, Result, require_int, require_nonnegative, require_positive, result, stable_hash


def register_term_market(*, market_id: str, maturity: int, underlying: str, pt_asset: str, yt_asset: str, deployment_verified: bool) -> Result:
    if not deployment_verified or not all((market_id,underlying,pt_asset,yt_asset)):
        raise Mega808Error("TERM_MARKET_UNVERIFIED")
    return result("register_term_market", {"market_id":market_id,"maturity":require_nonnegative(maturity,"maturity"),"underlying":underlying,"pt_asset":pt_asset,"yt_asset":yt_asset,"deployment_verified":True})


def normalize_pt_yt_cashflows(*, pt_principal: int, yt_cashflows: Mapping[int,int], maturity: int) -> Result:
    principal=require_nonnegative(pt_principal,"pt_principal")
    maturity=require_nonnegative(maturity,"maturity")
    flows=[]
    for ts,amount in sorted(yt_cashflows.items()):
        ts=require_nonnegative(int(ts),"cashflow_time")
        if ts>maturity:
            raise Mega808Error("CASHFLOW_AFTER_MATURITY")
        flows.append((ts,require_int(amount,"cashflow_amount")))
    return result("normalize_pt_yt_cashflows", {"pt_principal_at_maturity":principal,"yt_cashflows":tuple(flows),"maturity":maturity})


def solve_fixed_rate_parity(*, pt_ask: int, yt_ask: int, underlying_spot: int, fees: int) -> Result:
    pt=require_nonnegative(pt_ask,"pt_ask")
    yt=require_nonnegative(yt_ask,"yt_ask")
    spot=require_nonnegative(underlying_spot,"underlying_spot")
    fee=require_nonnegative(fees,"fees")
    strip_cost=pt+yt+fee
    edge=spot-strip_cost
    return result("solve_fixed_rate_parity", {"strip_cost":strip_cost,"underlying_spot":spot,"edge":edge,"executable_positive":edge>0})


def qualify_term_market_route(route: Mapping[str,object], *, capacity: int, required_capacity: int, exact_simulation_passed: bool) -> Result:
    cap=require_nonnegative(capacity,"capacity")
    required=require_nonnegative(required_capacity,"required_capacity")
    blockers=()
    if cap<required:
        blockers+=("CAPACITY_SHORTFALL",)
    if not exact_simulation_passed:
        blockers+=("EXACT_SIMULATION_FAILED",)
    return result("qualify_term_market_route", {"route_hash":stable_hash("term-route",dict(route)),"capacity":cap,"required_capacity":required,"qualified":not blockers}, status="OK" if not blockers else "BLOCKED", blockers=blockers)
