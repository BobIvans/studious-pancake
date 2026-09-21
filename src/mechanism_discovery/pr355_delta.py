"""PR-355 current-head delta ownership and non-duplication contracts."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import stable_hash
from .evidence_native_core import EvidenceNativeError, record, require_text

ALLOWED_OWNER_DECISIONS = {
    "SATISFIED_BY_EXISTING",
    "SPECIALIZE_EXISTING",
    "NEW_OUTCOME",
    "BLOCKED_EXTERNAL",
}


def map_delta_to_current_owners(rows: Sequence[Mapping[str, Any]]):
    mapped = []
    seen = set()
    for row in rows:
        requirement_id = require_text(row.get("requirement_id"), "requirement_id")
        if requirement_id in seen:
            raise EvidenceNativeError("DELTA_REQUIREMENT_DUPLICATE")
        seen.add(requirement_id)
        decision = require_text(row.get("decision"), "decision")
        if decision not in ALLOWED_OWNER_DECISIONS:
            raise EvidenceNativeError("DELTA_OWNER_DECISION_INVALID")
        mapped.append(
            {
                "requirement_id": requirement_id,
                "decision": decision,
                "owner": require_text(row.get("owner"), "owner"),
                "symbol": require_text(row.get("symbol"), "symbol"),
            }
        )
    return record("map_delta_to_current_owners", {"rows": tuple(mapped), "count": len(mapped)})


def classify_delta_non_duplication(payload: Mapping[str, Any]):
    existing_owner = payload.get("existing_owner")
    equivalent = bool(payload.get("equivalent_contract", False))
    specialization = bool(payload.get("specialization_needed", False))
    external_blocker = payload.get("external_blocker")
    if external_blocker:
        decision = "BLOCKED_EXTERNAL"
    elif existing_owner and equivalent and not specialization:
        decision = "SATISFIED_BY_EXISTING"
    elif existing_owner and specialization:
        decision = "SPECIALIZE_EXISTING"
    else:
        decision = "NEW_OUTCOME"
    return record("classify_delta_non_duplication", {"decision": decision, "existing_owner": existing_owner})


def bind_delta_source_provenance(payload: Mapping[str, Any]):
    required = ("source", "version", "license_decision", "terms_decision", "cost_decision", "finality_evidence")
    missing = tuple(field for field in required if not payload.get(field))
    return record(
        "bind_delta_source_provenance",
        {
            "complete": not missing,
            "missing": missing,
            "source": str(payload.get("source", "")),
            "source_copy_allowed": False,
        },
    )


def register_delta_marketpack(payload: Mapping[str, Any]):
    return record(
        "register_delta_marketpack",
        {
            "marketpack_id": require_text(payload.get("marketpack_id"), "marketpack_id"),
            "mode": require_text(payload.get("mode"), "mode"),
            "state": "DISABLED",
            "execution_permissions_changed": False,
        },
    )


def audit_delta_effect_boundary(payload: Mapping[str, Any]):
    unsafe = tuple(
        field
        for field in (
            "signer_access", "submission_access", "wallet_access",
            "remote_mutation", "automatic_promotion", "automatic_capital_increase",
        )
        if payload.get(field) is not False
    )
    if unsafe:
        raise EvidenceNativeError("DELTA_EFFECT_BOUNDARY_UNSAFE")
    return record("audit_delta_effect_boundary", {"safe": True, "unsafe_fields": ()})


def publish_delta_coverage_receipt(payload: Mapping[str, Any]):
    coverage = payload.get("coverage")
    blockers = tuple(str(x) for x in payload.get("blockers", ()))
    if not isinstance(coverage, Mapping):
        raise EvidenceNativeError("DELTA_COVERAGE_REQUIRED")
    digest = stable_hash("pr355:coverage-receipt", {"coverage": coverage, "blockers": blockers})
    return record(
        "publish_delta_coverage_receipt",
        {"coverage_hash": digest, "blockers": blockers, "qualification_claim": False},
    )
