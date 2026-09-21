"""PR-292 / NF-853..856: Sui flash primitive and PTB qualification."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega808Error, Result, require_nonnegative, result, stable_hash


def register_sui_flash_primitive(*, package_id: str, pool_object: str, fee_bps: int, hot_potato_repayment: bool, package_verified: bool) -> Result:
    if not package_verified or not package_id or not pool_object:
        raise Mega808Error("SUI_PACKAGE_UNVERIFIED")
    fee=require_nonnegative(fee_bps,"fee_bps")
    if fee>10_000:
        raise Mega808Error("FEE_OUT_OF_RANGE")
    if not hot_potato_repayment:
        raise Mega808Error("REPAYMENT_OBJECT_REQUIRED")
    return result("register_sui_flash_primitive", {"package_id":package_id,"pool_object":pool_object,"fee_bps":fee,"hot_potato_repayment":True})


def normalize_sui_pool_capacity(*, borrow_capacity: int, swap_capacity: int, shared_pool: bool) -> Result:
    borrow=require_nonnegative(borrow_capacity,"borrow_capacity")
    swap=require_nonnegative(swap_capacity,"swap_capacity")
    effective=min(borrow,swap) if shared_pool else borrow
    return result("normalize_sui_pool_capacity", {"borrow_capacity":borrow,"swap_capacity":swap,"shared_pool":shared_pool,"effective_flash_capacity":effective})


def build_sui_atomic_route(*, objects: Sequence[tuple[str,int]], operations: Sequence[str], repayment_present: bool) -> Result:
    if not repayment_present:
        raise Mega808Error("REPAYMENT_OBJECT_REQUIRED")
    seen=set()
    normalized=[]
    for object_id,version in objects:
        key=(str(object_id),require_nonnegative(version,"object_version"))
        if key in seen:
            raise Mega808Error("OBJECT_VERSION_REUSED")
        seen.add(key); normalized.append(key)
    if not operations:
        raise Mega808Error("PTB_OPERATIONS_REQUIRED")
    return result("build_sui_atomic_route", {"objects":tuple(normalized),"operations":tuple(operations),"repayment_present":True,"unsigned":True})


def qualify_sui_primitive(route: Mapping[str,object], *, simulation_passed: bool, object_versions_match: bool, gas_budget_sufficient: bool) -> Result:
    blockers=tuple(code for ok,code in ((simulation_passed,"SIMULATION_FAILED"),(object_versions_match,"OBJECT_VERSION_MISMATCH"),(gas_budget_sufficient,"GAS_BUDGET_SHORTFALL")) if not ok)
    return result("qualify_sui_primitive", {"route_hash":stable_hash("sui-route",dict(route)),"qualified":not blockers,"submission":False}, status="OK" if not blockers else "BLOCKED", blockers=blockers)
