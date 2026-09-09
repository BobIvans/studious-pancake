"""MPR-2611 semantic evidence validation for production qualification.

This module is an evidence consumer only. It does not implement shadow, signer,
canary, economics, runtime, debt, or release-promotion authorities.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

MPR2611_SCHEMA = "mpr-2611.production-evidence-validation.v1"

# Evidence whose mere existence must never close production debt.
SEMANTIC_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "database_schema_fingerprint": ("database-schema", "mpr-"),
    "backup_restore_report_digest": ("backup-restore", "mpr-"),
    "fault_injection_report_digest": ("fault-injection", "mpr-"),
    "provider_drift_probe_report_digest": ("provider-drift", "mpr-2605", "mpr-2611"),
    "shadow_campaign_report_digest": ("shadow-soak", "mpr-2607", "mpr2607"),
    "finalized_economics_report_digest": ("finalized-economics", "mpr-2610", "mpr2610"),
    "signer_canary_approval_bundle_digest": ("canary", "mpr-2609", "mpr2609"),
    "wheelhouse_manifest": ("wheelhouse", "dependency"),
    "sbom_digest": ("sbom",),
    "config_generation_digest": ("config-generation", "mpr-"),
}

_TRUE_VERDICTS = {"accepted", "passed", "qualified", "success", "succeeded", "settled"}
_FALSE_VERDICTS = {
    "ambiguous",
    "blocked",
    "failed",
    "failure",
    "fixture",
    "invalid",
    "pending",
    "planned",
    "rejected",
    "synthetic",
    "unknown",
}


@dataclass(frozen=True, slots=True)
class EvidenceValidation:
    accepted: bool
    artifact_id: str
    raw_sha256: str
    semantic_sha256: str | None
    reason_codes: tuple[str, ...]
    schema_version: str | None = None
    producer: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MPR2611_SCHEMA,
            "accepted": self.accepted,
            "artifact_id": self.artifact_id,
            "raw_sha256": self.raw_sha256,
            "semantic_sha256": self.semantic_sha256,
            "reason_codes": list(self.reason_codes),
            "evidence_schema_version": self.schema_version,
            "producer": self.producer,
        }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number forbidden: {value}")


def load_strict_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise ValueError("evidence symlink forbidden")
    raw = path.read_bytes()
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("evidence root must be an object")
    if not value:
        raise ValueError("empty evidence object forbidden")
    return value


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _schema_matches(schema: str, prefixes: tuple[str, ...]) -> bool:
    lowered = schema.lower()
    return any(lowered.startswith(prefix) for prefix in prefixes)


def _string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _bool_true(payload: Mapping[str, Any], key: str) -> bool:
    return payload.get(key) is True


def _verdict(payload: Mapping[str, Any]) -> str | None:
    for key in ("verdict", "qualification_status", "status", "result"):
        value = payload.get(key)
        if isinstance(value, str):
            return value.strip().lower().replace("_", "-")
    for key in ("qualified", "accepted", "passed", "success"):
        if payload.get(key) is True:
            return "passed"
        if payload.get(key) is False:
            return "failed"
    return None


def validate_semantic_evidence(
    path: Path,
    *,
    artifact_id: str,
    source_commit: str | None,
    release_id: str,
) -> EvidenceValidation:
    raw = path.read_bytes()
    raw_sha = _sha256_bytes(raw)
    prefixes = SEMANTIC_ARTIFACTS.get(artifact_id)
    if prefixes is None:
        return EvidenceValidation(True, artifact_id, raw_sha, raw_sha, ())

    reasons: list[str] = []
    try:
        payload = load_strict_json(path)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return EvidenceValidation(
            False,
            artifact_id,
            raw_sha,
            None,
            ("INVALID_JSON_EVIDENCE", type(exc).__name__),
        )

    schema = _string(payload, "schema_version")
    if schema is None:
        reasons.append("MISSING_SCHEMA_VERSION")
    elif not _schema_matches(schema, prefixes):
        reasons.append("WRONG_SCHEMA_VERSION")

    evidence_source = _string(payload, "source_commit")
    if source_commit is None:
        reasons.append("SOURCE_COMMIT_UNAVAILABLE")
    elif evidence_source != source_commit:
        reasons.append("SOURCE_COMMIT_MISMATCH")

    evidence_release = _string(payload, "release_id")
    if evidence_release != release_id:
        reasons.append("RELEASE_ID_MISMATCH")

    producer = _string(payload, "producer") or _string(payload, "evidence_producer")
    if producer is None:
        reasons.append("MISSING_EVIDENCE_PRODUCER")

    if not _bool_true(payload, "production_evidence"):
        reasons.append("NOT_PRODUCTION_EVIDENCE")

    for key in ("synthetic", "fixture", "dry_run", "documentation_only", "source_vector_offline"):
        if payload.get(key) is True:
            reasons.append("NON_PRODUCTION_EVIDENCE")
            break

    evidence_kind = _string(payload, "evidence_kind")
    if evidence_kind and evidence_kind.lower() in {
        "fixture",
        "example",
        "dry-run",
        "documentation-review",
        "source-vector-offline",
        "synthetic",
    }:
        reasons.append("NON_PRODUCTION_EVIDENCE")

    verdict = _verdict(payload)
    if verdict is None:
        reasons.append("MISSING_POSITIVE_VERDICT")
    elif verdict in _FALSE_VERDICTS or verdict not in _TRUE_VERDICTS:
        reasons.append("NON_SUCCESS_VERDICT")

    if artifact_id == "finalized_economics_report_digest":
        realized = payload.get("realized_pnl_atomic_units")
        if isinstance(realized, bool) or not isinstance(realized, int):
            reasons.append("MISSING_REALIZED_INTEGER_PNL")
        reconciliation = _string(payload, "reconciliation_status")
        if reconciliation not in {"reconciled", "settled", "finalized-settled"}:
            reasons.append("ECONOMICS_NOT_RECONCILED")
        if payload.get("transaction_finalized") is not True:
            reasons.append("TRANSACTION_NOT_FINALIZED")

    if artifact_id == "shadow_campaign_report_digest":
        if payload.get("synthetic") is not False:
            reasons.append("SHADOW_SYNTHETIC_STATE_UNPROVEN")
        duration = payload.get("eligible_duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            reasons.append("INVALID_SHADOW_DURATION")

    if artifact_id == "signer_canary_approval_bundle_digest":
        if payload.get("second_human_approval") is not True:
            reasons.append("SECOND_HUMAN_APPROVAL_MISSING")
        if payload.get("auto_rearm") is not False:
            reasons.append("AUTO_REARM_NOT_DISABLED")
        if payload.get("unknown_outcome") is True:
            reasons.append("CANARY_UNKNOWN_OUTCOME")

    semantic_sha = None if reasons else _sha256_bytes(_canonical_json(payload))
    return EvidenceValidation(
        not reasons,
        artifact_id,
        raw_sha,
        semantic_sha,
        tuple(sorted(set(reasons))),
        schema,
        producer,
    )
