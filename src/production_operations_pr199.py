"""PR-199 operations, signed-release and disaster-recovery evidence gate.

The V3 roadmap defines PR-199 as the operations boundary: readiness,
observability, signed release provenance, authenticated backup/restore, SLO
evidence and incident drills.  This module is intentionally offline and
sender-free: it validates evidence only and cannot enable live trading, deploy
cutover or signing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping

PR199_SCHEMA_VERSION = "pr199.operations-release-dr.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_ARTIFACT_HASHES = (
    "source_commit_sha",
    "wheel_sha256",
    "runtime_image_digest",
    "sbom_sha256",
    "provenance_sha256",
    "config_generation_hash",
    "policy_bundle_hash",
    "capability_manifest_hash",
    "database_schema_hash",
)
_REQUIRED_READINESS_CLOSURES = (
    "dead_strategy",
    "stale_rooted_data",
    "db_degraded",
    "admission_latch",
    "outbox_backlog",
)
_REQUIRED_OBSERVABILITY = (
    "low_cardinality_labels",
    "secrets_redacted",
    "trace_binds_attempt_release_config",
    "alerts_cover_readiness_slo_and_dr",
)
_REQUIRED_DR = (
    "backup_manifest_signed",
    "backup_generation_bound",
    "restore_uses_temp_sibling",
    "previous_generation_preserved",
    "overwrite_open_db_prevented",
    "event_replay_matches_materialized_state",
    "restore_hashes_match",
)
_REQUIRED_SLO_BUDGETS = (
    "event_loop_lag_p99_ms",
    "db_commit_p99_ms",
    "recovery_rto_seconds",
    "unknown_submission_max_seconds",
    "memory_fd_growth",
)
_REQUIRED_FAULT_DRILLS = (
    "kill_9_during_state_transition",
    "disk_full",
    "clock_jump",
    "dns_failure",
    "provider_outage",
    "signer_outage",
    "backup_during_wal_writes",
)
_REQUIRED_DEPLOYMENT = (
    "immutable_image_digest",
    "non_root",
    "read_only_rootfs",
    "no_new_privileges",
    "capabilities_dropped",
    "egress_deny_default",
    "secrets_externalized",
)


class PR199OperationsError(ValueError):
    """Raised when PR-199 evidence has an invalid shape."""


class DiagnosticSeverity(StrEnum):
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class OperationsDiagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class OperationsReadinessReport:
    schema_version: str
    ok: bool
    evidence_hash: str
    diagnostics: tuple[OperationsDiagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "evidence_hash": self.evidence_hash,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "live_capability_allowed": live_capability_allowed(),
            "cutover_capability_allowed": cutover_capability_allowed(),
        }


def validate_operations_evidence(evidence: Mapping[str, Any]) -> OperationsReadinessReport:
    """Validate a PR-199 release/DR/readiness evidence document.

    The input is a plain mapping so the gate can run in CI, local scripts,
    release checks and offline incident drills without importing deployment,
    signer, RPC or sender modules.
    """

    if not isinstance(evidence, Mapping):
        raise PR199OperationsError("evidence root must be an object")
    schema = _string(evidence.get("schema_version"), "schema_version")
    if schema != PR199_SCHEMA_VERSION:
        raise PR199OperationsError("unsupported PR-199 operations schema")

    diagnostics: list[OperationsDiagnostic] = []
    release = _section(evidence, "release")
    diagnostics.extend(_validate_release(release))
    diagnostics.extend(_validate_readiness(_section(evidence, "readiness")))
    diagnostics.extend(_validate_observability(_section(evidence, "observability")))
    diagnostics.extend(_require_true_map(_section(evidence, "dr"), "dr", _REQUIRED_DR))
    diagnostics.extend(_validate_qualification(_section(evidence, "qualification")))
    diagnostics.extend(_validate_deployment(_section(evidence, "deployment")))

    return OperationsReadinessReport(
        schema_version=schema,
        ok=not diagnostics,
        evidence_hash=_stable_hash(evidence),
        diagnostics=tuple(diagnostics),
    )


def live_capability_allowed() -> bool:
    """PR-199 operations qualification cannot enable live trading."""

    return False


def cutover_capability_allowed() -> bool:
    """PR-199 validates evidence but cannot perform deployment cutover."""

    return False


def _validate_release(release: Mapping[str, Any]) -> tuple[OperationsDiagnostic, ...]:
    diagnostics: list[OperationsDiagnostic] = []
    _sha256(release.get("release_manifest_hash"), "release.release_manifest_hash")
    signer_identity = _string(release.get("signer_identity"), "release.signer_identity")
    if signer_identity.lower() in {"self", "operator", "placeholder", "example"}:
        diagnostics.append(
            _diag(
                "RELEASE_SIGNER_NOT_INDEPENDENT",
                "release signer identity must be a concrete independent reviewer",
                "release.signer_identity",
            )
        )
    if release.get("signed") is not True:
        diagnostics.append(
            _diag("RELEASE_NOT_SIGNED", "release manifest must be signed", "release.signed")
        )
    if release.get("independent_reviewed") is not True:
        diagnostics.append(
            _diag(
                "RELEASE_NOT_REVIEWED",
                "release manifest must have independent review evidence",
                "release.independent_reviewed",
            )
        )
    artifacts = _section(release, "artifact_hashes", path="release.artifact_hashes")
    for key in _REQUIRED_ARTIFACT_HASHES:
        value = artifacts.get(key)
        if value is None:
            diagnostics.append(
                _diag(
                    "ARTIFACT_HASH_MISSING",
                    f"required artifact hash {key!r} is missing",
                    f"release.artifact_hashes.{key}",
                )
            )
        elif not isinstance(value, str) or not _SHA256_RE.fullmatch(value.lower()):
            diagnostics.append(
                _diag(
                    "ARTIFACT_HASH_INVALID",
                    f"artifact hash {key!r} must be sha256 hex",
                    f"release.artifact_hashes.{key}",
                )
            )
    return tuple(diagnostics)


def _validate_readiness(readiness: Mapping[str, Any]) -> tuple[OperationsDiagnostic, ...]:
    diagnostics: list[OperationsDiagnostic] = []
    livez = _string(readiness.get("liveness_endpoint"), "readiness.liveness_endpoint")
    readyz = _string(readiness.get("readiness_endpoint"), "readiness.readiness_endpoint")
    if livez == readyz:
        diagnostics.append(
            _diag(
                "READINESS_LIVENESS_NOT_SEPARATED",
                "liveness and readiness must be separate signals",
                "readiness.readiness_endpoint",
            )
        )
    checks = {
        "liveness_uses_process_health_only": "LIVENESS_OVERLOADS_READINESS",
        "readiness_uses_durable_dependencies": "READINESS_NOT_DURABLE",
        "readiness_uses_active_task_health": "READINESS_IGNORES_TASK_HEALTH",
        "management_auth_required": "MANAGEMENT_PLANE_UNAUTHENTICATED",
    }
    for field, code in checks.items():
        if readiness.get(field) is not True:
            diagnostics.append(
                _diag(code, f"readiness.{field} must be true", f"readiness.{field}")
            )
    closures = _section(
        readiness, "readiness_closes_on", path="readiness.readiness_closes_on"
    )
    diagnostics.extend(
        _require_true_map(
            closures,
            "readiness.readiness_closes_on",
            _REQUIRED_READINESS_CLOSURES,
            code="READINESS_CLOSURE_MISSING",
        )
    )
    return tuple(diagnostics)


def _validate_observability(
    observability: Mapping[str, Any]
) -> tuple[OperationsDiagnostic, ...]:
    diagnostics = list(
        _require_true_map(
            observability,
            "observability",
            _REQUIRED_OBSERVABILITY,
            code="OBSERVABILITY_EVIDENCE_MISSING",
        )
    )
    _sha256(observability.get("audit_export_hash"), "observability.audit_export_hash")
    return tuple(diagnostics)


def _validate_qualification(
    qualification: Mapping[str, Any]
) -> tuple[OperationsDiagnostic, ...]:
    slo = _section(qualification, "slo_budgets", path="qualification.slo_budgets")
    fault = _section(qualification, "fault_drills", path="qualification.fault_drills")
    return tuple(
        list(
            _require_true_map(
                slo,
                "qualification.slo_budgets",
                _REQUIRED_SLO_BUDGETS,
                code="SLO_BUDGET_MISSING",
            )
        )
        + list(
            _require_true_map(
                fault,
                "qualification.fault_drills",
                _REQUIRED_FAULT_DRILLS,
                code="FAULT_DRILL_MISSING",
            )
        )
    )


def _validate_deployment(deployment: Mapping[str, Any]) -> tuple[OperationsDiagnostic, ...]:
    diagnostics = list(_require_true_map(deployment, "deployment", _REQUIRED_DEPLOYMENT))
    if deployment.get("live_enabled") is not False:
        diagnostics.append(
            _diag(
                "LIVE_ENABLEMENT_OUT_OF_SCOPE",
                "PR-199 qualifies operations and cannot enable live",
                "deployment.live_enabled",
            )
        )
    return tuple(diagnostics)


def _require_true_map(
    raw: Mapping[str, Any],
    prefix: str,
    keys: tuple[str, ...],
    *,
    code: str = "REQUIRED_EVIDENCE_MISSING",
) -> tuple[OperationsDiagnostic, ...]:
    diagnostics = []
    for key in keys:
        if raw.get(key) is not True:
            diagnostics.append(
                _diag(code, f"required evidence {key!r} must be true", f"{prefix}.{key}")
            )
    return tuple(diagnostics)


def _section(raw: Mapping[str, Any], key: str, *, path: str | None = None) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise PR199OperationsError(f"{path or key} must be an object")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR199OperationsError(f"{path} must be a non-empty string")
    return value.strip()


def _sha256(value: object, path: str) -> str:
    text = _string(value, path)
    if not _SHA256_RE.fullmatch(text.lower()):
        raise PR199OperationsError(f"{path} must be sha256 hex")
    return text.lower()


def _stable_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _diag(code: str, message: str, path: str) -> OperationsDiagnostic:
    return OperationsDiagnostic(code, DiagnosticSeverity.ERROR, message, path)


__all__ = [
    "DiagnosticSeverity",
    "OperationsDiagnostic",
    "OperationsReadinessReport",
    "PR199OperationsError",
    "PR199_SCHEMA_VERSION",
    "cutover_capability_allowed",
    "live_capability_allowed",
    "validate_operations_evidence",
]
