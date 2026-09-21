"""PR-293 / NF-857..860: generic Move execution dialect."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega808Error, Result, require_nonnegative, result, stable_hash


def define_move_execution_dialect(*, chain_id: str, type_system: str, gas_asset: str, resource_model: str) -> Result:
    if not all((chain_id,type_system,gas_asset,resource_model)):
        raise Mega808Error("MOVE_DIALECT_REQUIRED")
    return result("define_move_execution_dialect", {"chain_id":chain_id,"type_system":type_system,"gas_asset":gas_asset,"resource_model":resource_model})


def decode_move_resource_state(*, resource_type: str, version: int, fields: Mapping[str,object], schema_hash: str) -> Result:
    if not resource_type or not schema_hash:
        raise Mega808Error("RESOURCE_SCHEMA_UNVERIFIED")
    return result("decode_move_resource_state", {"resource_type":resource_type,"version":require_nonnegative(version,"version"),"fields":dict(fields),"schema_hash":schema_hash,"state_hash":stable_hash("move-resource",dict(fields))})


def plan_move_object_dependencies(resources: Sequence[tuple[str,int,str]]) -> Result:
    locks={}
    for resource,version,access in resources:
        if access not in {"read","write","consume"}:
            raise Mega808Error("INVALID_RESOURCE_ACCESS")
        version=require_nonnegative(version,"version")
        prior=locks.get(resource)
        if prior and prior[0]!=version:
            raise Mega808Error("RESOURCE_VERSION_CONFLICT")
        if prior and ("write" in {prior[1],access} or "consume" in {prior[1],access}):
            raise Mega808Error("RESOURCE_LOCK_CONFLICT")
        locks[str(resource)]=(version,access)
    return result("plan_move_object_dependencies", {"locks":tuple(sorted((k,*v) for k,v in locks.items()))})


def simulate_move_transaction(*, plan_hash: str, adapter_chain_id: str, expected_chain_id: str, simulated: bool, deltas: Mapping[str,int]) -> Result:
    if adapter_chain_id!=expected_chain_id:
        raise Mega808Error("CHAIN_DIALECT_MISMATCH")
    if not simulated:
        raise Mega808Error("SIMULATION_REQUIRED")
    return result("simulate_move_transaction", {"plan_hash":plan_hash,"chain_id":adapter_chain_id,"deltas":dict(deltas),"simulated":True,"submission":False})
