"""PR-289 / NF-841..844: consent-bound solver orderflow."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega808Error, Result, require_int, require_nonnegative, result, stable_hash


def register_solver_orderflow(*, solver_id: str, order_schema_hash: str, settlement_contract: str, consent_required: bool) -> Result:
    if not solver_id or not order_schema_hash or not settlement_contract:
        raise Mega808Error("SOLVER_IDENTITY_UNVERIFIED")
    return result("register_solver_orderflow", {"solver_id":solver_id,"order_schema_hash":order_schema_hash,"settlement_contract":settlement_contract,"consent_required":consent_required})


def normalize_intent_constraints(*, expiry: int, now: int, min_output: int, allowed_recipients: Sequence[str], consent_present: bool) -> Result:
    expiry=require_nonnegative(expiry,"expiry")
    now=require_nonnegative(now,"now")
    floor=require_nonnegative(min_output,"min_output")
    if expiry<=now:
        raise Mega808Error("INTENT_EXPIRED")
    if not consent_present:
        raise Mega808Error("CONSENT_REQUIRED")
    recipients=tuple(dict.fromkeys(str(x) for x in allowed_recipients if str(x)))
    if not recipients:
        raise Mega808Error("RECIPIENT_REQUIRED")
    return result("normalize_intent_constraints", {"expiry":expiry,"min_output":floor,"allowed_recipients":recipients,"consent_present":True})


def price_solver_fill(*, offered_output: int, user_min_output: int, solver_fee: int, gas_or_execution_fee: int) -> Result:
    offered=require_nonnegative(offered_output,"offered_output")
    floor=require_nonnegative(user_min_output,"user_min_output")
    solver_fee=require_nonnegative(solver_fee,"solver_fee")
    exec_fee=require_nonnegative(gas_or_execution_fee,"gas_or_execution_fee")
    user_net=max(0,offered-solver_fee)
    if user_net<floor:
        raise Mega808Error("USER_FLOOR_VIOLATION")
    return result("price_solver_fill", {"offered_output":offered,"user_net_output":user_net,"user_floor":floor,"solver_fee":solver_fee,"execution_fee":exec_fee})


def qualify_solver_adapter(profile: Mapping[str, object], *, signature_domain_verified: bool, callback_verified: bool, settlement_simulated: bool) -> Result:
    blockers=tuple(code for ok,code in ((signature_domain_verified,"SIGNATURE_DOMAIN_UNVERIFIED"),(callback_verified,"CALLBACK_UNVERIFIED"),(settlement_simulated,"SETTLEMENT_NOT_SIMULATED")) if not ok)
    return result("qualify_solver_adapter", {"profile_hash":stable_hash("solver-profile",dict(profile)),"qualified":not blockers,"submission":False}, status="OK" if not blockers else "BLOCKED", blockers=blockers)
