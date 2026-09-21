"""PR-298 / NF-877..880: tenant data/query isolation."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega808Error, Result, require_nonnegative, result, stable_hash


def define_tenant_policy(*, tenant_id: str, allowed_datasets: Sequence[str], query_quota: int, storage_quota_bytes: int) -> Result:
    if not tenant_id:
        raise Mega808Error("TENANT_ID_REQUIRED")
    return result("define_tenant_policy", {"tenant_id":tenant_id,"allowed_datasets":tuple(sorted(set(allowed_datasets))),"query_quota":require_nonnegative(query_quota,"query_quota"),"storage_quota_bytes":require_nonnegative(storage_quota_bytes,"storage_quota_bytes")})


def isolate_tenant_data(*, tenant_id: str, row_tenant_ids: Sequence[str], requested_dataset: str, allowed_datasets: Sequence[str]) -> Result:
    if requested_dataset not in set(allowed_datasets):
        raise Mega808Error("TENANT_DATASET_DENIED")
    leaks=tuple(i for i,value in enumerate(row_tenant_ids) if value!=tenant_id)
    return result("isolate_tenant_data", {"tenant_id":tenant_id,"dataset":requested_dataset,"row_count":len(row_tenant_ids),"cross_tenant_rows":leaks}, status="OK" if not leaks else "BLOCKED", blockers=("CROSS_TENANT_DATA_LEAK",) if leaks else ())


def enforce_tenant_quota(*, queries_used: int, query_quota: int, storage_used_bytes: int, storage_quota_bytes: int) -> Result:
    used=require_nonnegative(queries_used,"queries_used"); qcap=require_nonnegative(query_quota,"query_quota"); storage=require_nonnegative(storage_used_bytes,"storage_used_bytes"); scap=require_nonnegative(storage_quota_bytes,"storage_quota_bytes")
    blockers=tuple(code for cond,code in ((used>qcap,"QUERY_QUOTA_EXCEEDED"),(storage>scap,"STORAGE_QUOTA_EXCEEDED")) if cond)
    return result("enforce_tenant_quota", {"queries_used":used,"query_quota":qcap,"storage_used_bytes":storage,"storage_quota_bytes":scap,"allowed":not blockers}, status="OK" if not blockers else "BLOCKED", blockers=blockers)


def audit_tenant_boundary(*, tenant_id: str, resource_owners: Mapping[str,str]) -> Result:
    cross=tuple(sorted(resource for resource,owner in resource_owners.items() if owner!=tenant_id))
    return result("audit_tenant_boundary", {"tenant_id":tenant_id,"resource_count":len(resource_owners),"cross_tenant_resources":cross,"boundary_hash":stable_hash("tenant-boundary",dict(resource_owners))}, status="OK" if not cross else "BLOCKED", blockers=("CROSS_TENANT_RESOURCE",) if cross else ())
