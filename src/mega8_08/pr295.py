"""PR-295 / NF-865..868: immutable evidence/query API contract."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega808Error, Result, require_nonnegative, require_positive, result, stable_hash


def expose_evidence_query_api(records: Sequence[Mapping[str,object]], *, immutable_source: bool, max_rows: int=1000) -> Result:
    if not immutable_source:
        raise Mega808Error("MUTABLE_EVIDENCE_SOURCE")
    limit=require_positive(max_rows,"max_rows")
    rows=tuple(dict(row) for row in records[:limit])
    return result("expose_evidence_query_api", {"rows":rows,"row_count":len(rows),"truncated":len(records)>limit,"source_immutable":True})


def expose_execution_quality_metrics(*, attempts: int, finalized: int, total_cost: int, total_realized_net: int) -> Result:
    attempts=require_nonnegative(attempts,"attempts")
    finalized=require_nonnegative(finalized,"finalized")
    if finalized>attempts:
        raise Mega808Error("FINALIZED_COUNT_INVALID")
    cost=require_nonnegative(total_cost,"total_cost")
    return result("expose_execution_quality_metrics", {"attempts":attempts,"finalized":finalized,"total_cost":cost,"total_realized_net":int(total_realized_net),"finalization_fraction":(finalized,attempts) if attempts else (0,1)})


def enforce_api_scope(*, role: str, allowed_roles: Sequence[str], requested_rows: int, row_quota: int) -> Result:
    if role not in set(allowed_roles):
        raise Mega808Error("API_SCOPE_DENIED")
    requested=require_nonnegative(requested_rows,"requested_rows")
    quota=require_nonnegative(row_quota,"row_quota")
    if requested>quota:
        raise Mega808Error("QUERY_QUOTA_EXCEEDED")
    return result("enforce_api_scope", {"role":role,"requested_rows":requested,"row_quota":quota,"allowed":True})


def publish_api_contract(*, version: str, schema: Mapping[str,object], breaking_change: bool=False) -> Result:
    if not version or not schema:
        raise Mega808Error("API_SCHEMA_REQUIRED")
    return result("publish_api_contract", {"version":version,"schema_hash":stable_hash("api-schema",dict(schema)),"breaking_change":breaking_change,"live_enabled":False})
