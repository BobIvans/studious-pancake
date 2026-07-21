"""PR-101 MarginFi complete protocol evidence boundary.

This module does not fetch RPC data, assemble MarginFi instructions, sign, or
submit transactions. It evaluates whether already-materialized evidence is
complete enough to promote the MarginFi dependency to sender-free shadow
execution capability. Live execution remains denied.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from src.providers.marginfi.deployment_conformance import (
    EXPECTED_MAIN_GROUP,
    EXPECTED_PROGRAM_ID,
    EXPECTED_VERIFIED_BUILD_HASH,
    PINNED_SOURCE_COMMIT,
    evaluate_marginfi_execution_conformance,
    load_marginfi_deployment_manifest,
)

SCHEMA_VERSION = "pr101.marginfi-complete-evidence.v1"
RESULT_SCHEMA_VERSION = "pr101.marginfi-complete-evidence-result.v1"
MAXIMUM_SHADOW_CAPABILITY = "shadow-execution-capable"

_DECISIVE_NONNULL_FIELDS: tuple[str, ...] = (
    "idl.sha256",
    "sdk_golden_vectors.account_vectors_sha256",
    "sdk_golden_vectors.instruction_vectors_sha256",
    "rpc_evidence.sha256",
    "rpc_evidence.min_context_slot",
    "complete_protocol_evidence.source_release_pin_sha256",
    "complete_protocol_evidence.canonical_idl_layout_sha256",
    "complete_protocol_evidence.account_vector_bundle_sha256",
    "complete_protocol_evidence.instruction_vector_bundle_sha256",
    "complete_protocol_evidence.flashloan_meta_vector_sha256",
    "complete_protocol_evidence.token_2022_vector_sha256",
    "complete_protocol_evidence.repayment_math_sha256",
    "complete_protocol_evidence.deployment_metadata_provenance_sha256",
    "complete_protocol_evidence.human_review_sha256",
    "complete_protocol_evidence.signature_reference",
    "complete_protocol_evidence.min_context_slot",
)

_DECISIVE_TRUE_FIELDS: tuple[str, ...] = (
    "idl.canonical_program_metadata_verified",
    "rpc_evidence.program_executable_verified",
    "rpc_evidence.group_relationships_verified",
    "rpc_evidence.bank_relationships_verified",
    "rpc_evidence.oracle_relationships_verified",
    "rpc_evidence.fee_pause_config_verified",
    "rpc_evidence.flashloan_metas_verified",
    "rpc_evidence.token_2022_paths_verified",
    "complete_protocol_evidence.full_idl_layout_verified",
    "complete_protocol_evidence.source_sdk_vectors_verified",
    "complete_protocol_evidence.flashloan_instruction_vectors_verified",
    "complete_protocol_evidence.conservative_repayment_math_verified",
    "complete_protocol_evidence.deployment_metadata_provenance_verified",
    "complete_protocol_evidence.human_reviewed",
    "protocol_conformance.shadow_execution_capable",
    "promotion.execution_conformance_verified",
    "promotion.human_reviewed",
)

_LIVE_DENIAL_FIELDS: tuple[str, ...] = (
    "complete_protocol_evidence.live_allowed",
    "protocol_conformance.live_allowed",
    "promotion.live_allowed",
)


class MarginfiCompleteEvidenceError(ValueError):
    """Raised when PR-101 complete evidence is missing or unsafe."""


@dataclass(frozen=True, slots=True)
class MarginfiCompleteEvidenceEvaluation:
    schema_version: str
    complete: bool
    shadow_execution_capable: bool
    live_execution_allowed: bool
    state: str
    blockers: tuple[str, ...]
    decisive_missing_fields: tuple[str, ...]
    decisive_false_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_hash: str
    checks_evaluated: int
    metrics_summary: Mapping[str, int | str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "complete": self.complete,
            "shadow_execution_capable": self.shadow_execution_capable,
            "live_execution_allowed": self.live_execution_allowed,
            "state": self.state,
            "blockers": list(self.blockers),
            "decisive_missing_fields": list(self.decisive_missing_fields),
            "decisive_false_fields": list(self.decisive_false_fields),
            "warnings": list(self.warnings),
            "evidence_hash": self.evidence_hash,
            "checks_evaluated": self.checks_evaluated,
            "metrics_summary": dict(self.metrics_summary),
        }


def load_marginfi_complete_evidence_manifest(
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load the MarginFi evidence manifest without promoting execution."""

    if manifest is not None:
        return dict(manifest)
    return load_marginfi_deployment_manifest()


def evaluate_marginfi_complete_evidence(
    manifest: Mapping[str, Any] | None = None,
) -> MarginfiCompleteEvidenceEvaluation:
    """Evaluate PR-101 evidence completeness while keeping live impossible."""

    raw = load_marginfi_complete_evidence_manifest(manifest)
    base = evaluate_marginfi_execution_conformance(raw)
    blockers: list[str] = [f"PR055:{reason}" for reason in base.blockers]
    warnings: list[str] = []
    missing_fields: list[str] = []
    false_fields: list[str] = []
    checks = 0

    def check(condition: bool, reason: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(reason)

    check(
        raw.get("schema_version") == "pr055.marginfi-authoritative-conformance.v1",
        "PR055_MANIFEST_SCHEMA_MISMATCH",
    )
    check(_field(raw, "program_id") == EXPECTED_PROGRAM_ID, "PROGRAM_ID_MISMATCH")
    check(_field(raw, "main_group") == EXPECTED_MAIN_GROUP, "MAIN_GROUP_MISMATCH")
    check(
        _field(raw, "source.source_commit") == PINNED_SOURCE_COMMIT,
        "SOURCE_COMMIT_MISMATCH",
    )
    check(
        _field(raw, "deployment.expected_verified_build_hash_sha256")
        == EXPECTED_VERIFIED_BUILD_HASH,
        "VERIFIED_BUILD_HASH_MISMATCH",
    )

    for path in _DECISIVE_NONNULL_FIELDS:
        value = _field(raw, path)
        checks += 1
        if _is_missing(value):
            missing_fields.append(path)
            blockers.append(f"DECISIVE_FIELD_MISSING:{path}")

    for path in _DECISIVE_TRUE_FIELDS:
        value = _field(raw, path)
        checks += 1
        if _is_missing(value):
            missing_fields.append(path)
            blockers.append(f"DECISIVE_FIELD_MISSING:{path}")
        elif value is not True:
            false_fields.append(path)
            blockers.append(f"DECISIVE_FIELD_FALSE:{path}")

    for path in _LIVE_DENIAL_FIELDS:
        value = _field(raw, path)
        checks += 1
        if value is True:
            blockers.append(f"LIVE_DENIAL_VIOLATED:{path}")

    capability = _field(raw, "complete_protocol_evidence.maximum_capability")
    checks += 1
    if capability != MAXIMUM_SHADOW_CAPABILITY:
        blockers.append("MAXIMUM_CAPABILITY_NOT_SHADOW_EXECUTION_CAPABLE")

    manifest_schema = _field(raw, "complete_protocol_evidence.schema_version")
    checks += 1
    if manifest_schema != SCHEMA_VERSION:
        blockers.append("PR101_SCHEMA_MISMATCH")

    min_context = _field(raw, "complete_protocol_evidence.min_context_slot")
    rpc_min_context = _field(raw, "rpc_evidence.min_context_slot")
    checks += 1
    if isinstance(min_context, int) and isinstance(rpc_min_context, int):
        if min_context < rpc_min_context:
            blockers.append("PR101_CONTEXT_SLOT_BELOW_RPC_EVIDENCE")
    else:
        blockers.append("PR101_CONTEXT_SLOT_MISSING")

    unique_blockers = tuple(dict.fromkeys(blockers))
    complete = not unique_blockers
    if not complete and not missing_fields:
        warnings.append("PR101_BLOCKED_BY_FALSE_OR_MISMATCHED_EVIDENCE")

    return MarginfiCompleteEvidenceEvaluation(
        schema_version=RESULT_SCHEMA_VERSION,
        complete=complete,
        shadow_execution_capable=complete,
        live_execution_allowed=False,
        state=MAXIMUM_SHADOW_CAPABILITY if complete else "blocked",
        blockers=unique_blockers,
        decisive_missing_fields=tuple(dict.fromkeys(missing_fields)),
        decisive_false_fields=tuple(dict.fromkeys(false_fields)),
        warnings=tuple(dict.fromkeys(warnings)),
        evidence_hash=_canonical_hash(raw),
        checks_evaluated=checks,
        metrics_summary={
            "program_id": str(_field(raw, "program_id") or ""),
            "main_group": str(_field(raw, "main_group") or ""),
            "source_commit": str(_field(raw, "source.source_commit") or ""),
            "missing_decisive_fields": len(set(missing_fields)),
            "false_decisive_fields": len(set(false_fields)),
            "base_blockers": len(base.blockers),
        },
    )


def assert_marginfi_complete_evidence(
    manifest: Mapping[str, Any] | None = None,
) -> MarginfiCompleteEvidenceEvaluation:
    """Return complete PR-101 evidence or fail closed with stable blocker codes."""

    evaluation = evaluate_marginfi_complete_evidence(manifest)
    if not evaluation.complete:
        blockers = ",".join(evaluation.blockers)
        raise MarginfiCompleteEvidenceError(
            f"PR101_MARGINFI_COMPLETE_EVIDENCE_BLOCKED:{blockers}"
        )
    return evaluation


def _field(payload: Mapping[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
