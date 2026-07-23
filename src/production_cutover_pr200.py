"""PR-200 production cutover operations evidence gate.

This module is intentionally offline and sender-free.  It consumes proposed
release/cutover evidence and returns deterministic diagnostics.  It does not
deploy, read secrets, sign transactions, open sockets, or enable live trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from src.production_sandbox_pr200 import (
    DiagnosticSeverity,
    ProductionSandboxReport,
    SandboxDiagnostic,
    validate_production_sandbox_manifest,
)

PR200_CUTOVER_SCHEMA_VERSION = "pr200.production-cutover-ops.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_REQUIRED_RELEASE_FLAGS = (
    "release_manifest_signed",
    "wheel_digest_bound",
    "image_digest_pinned",
    "sbom_attached",
    "provenance_attached",
    "config_hash_bound",
    "capability_manifest_bound",
    "program_idl_hashes_bound",
)

_REQUIRED_READINESS_FLAGS = (
    "liveness_endpoint_separate",
    "readiness_endpoint_separate",
    "readiness_closes_on_dead_strategy",
    "readiness_closes_on_stale_rooted_data",
    "readiness_closes_on_db_degradation",
    "readiness_closes_on_latch",
)

_REQUIRED_BACKUP_FLAGS = (
    "rehearsed",
    "restored_in_clean_env",
    "event_chain_verified",
    "schema_verified",
    "outstanding_intents_verified",
    "rpo_zero_for_signed_intents",
)

_REQUIRED_ROLLBACK_FLAGS = (
    "drain_only_runbook",
    "rehearsed",
    "preserves_db_source_of_truth",
    "no_legacy_writer_after_cutover",
    "outstanding_intents_reconciled",
)

_REQUIRED_LEGACY_FLAGS = (
    "legacy_arb_bot_unavailable",
    "alternative_live_writers_unavailable",
    "source_only_live_paths_unavailable",
    "production_image_excludes_legacy_entrypoints",
)

_REQUIRED_SLO_BUDGETS = (
    "event_loop_lag",
    "queue_age",
    "provider_latency",
    "db_transition_latency",
    "recovery_time",
    "memory_fd_growth",
)

_REQUIRED_FAULT_DRILLS = (
    "kill_9",
    "disk_full",
    "clock_jump",
    "dns_failure",
    "provider_outage",
    "signer_outage",
    "backup_during_wal",
)


class PR200CutoverError(ValueError):
    """Raised when cutover evidence is structurally malformed."""


class CutoverPhase(StrEnum):
    SHADOW = "shadow"
    DRAIN = "drain"
    CANARY = "canary"
    PROMOTE = "promote"


@dataclass(frozen=True, slots=True)
class PR200CutoverReport:
    schema_version: str
    phase: CutoverPhase
    ok: bool
    evidence_hash: str
    sandbox_manifest_hash: str
    diagnostics: tuple[SandboxDiagnostic, ...]
    live_capability_allowed: bool = False
    cutover_capability_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "phase": self.phase.value,
            "ok": self.ok,
            "evidence_hash": self.evidence_hash,
            "sandbox_manifest_hash": self.sandbox_manifest_hash,
            "live_capability_allowed": self.live_capability_allowed,
            "cutover_capability_allowed": self.cutover_capability_allowed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


def validate_pr200_cutover_evidence(evidence: Mapping[str, Any]) -> PR200CutoverReport:
    """Validate PR-200 cutover evidence without performing a cutover."""

    if not isinstance(evidence, Mapping):
        raise PR200CutoverError("evidence root must be an object")
    schema = _non_empty(evidence.get("schema_version"), "schema_version")
    if schema != PR200_CUTOVER_SCHEMA_VERSION:
        raise PR200CutoverError("unsupported PR-200 cutover schema")
    phase = _phase(evidence.get("phase"))
    sandbox_report = _sandbox_report(evidence.get("sandbox_manifest"))
    diagnostics: list[SandboxDiagnostic] = list(sandbox_report.diagnostics)
    if not sandbox_report.ok:
        diagnostics.append(
            _diagnostic(
                "SANDBOX_MANIFEST_NOT_READY",
                "PR-200 sandbox manifest must be clean before cutover evidence can pass",
                "sandbox_manifest",
            )
        )
    diagnostics.extend(
        _missing_true_flags(
            evidence.get("release"),
            _REQUIRED_RELEASE_FLAGS,
            section="release",
            code="RELEASE_EVIDENCE_INCOMPLETE",
        )
    )
    diagnostics.extend(
        _missing_true_flags(
            evidence.get("readiness"),
            _REQUIRED_READINESS_FLAGS,
            section="readiness",
            code="READINESS_EVIDENCE_INCOMPLETE",
        )
    )
    diagnostics.extend(
        _missing_true_flags(
            evidence.get("backup_restore"),
            _REQUIRED_BACKUP_FLAGS,
            section="backup_restore",
            code="BACKUP_RESTORE_EVIDENCE_INCOMPLETE",
        )
    )
    diagnostics.extend(
        _missing_true_flags(
            evidence.get("rollback"),
            _REQUIRED_ROLLBACK_FLAGS,
            section="rollback",
            code="ROLLBACK_EVIDENCE_INCOMPLETE",
        )
    )
    diagnostics.extend(
        _missing_true_flags(
            evidence.get("legacy_surfaces"),
            _REQUIRED_LEGACY_FLAGS,
            section="legacy_surfaces",
            code="LEGACY_SURFACE_NOT_QUARANTINED",
        )
    )
    diagnostics.extend(_validate_slo_budgets(evidence.get("slo_budgets")))
    diagnostics.extend(_validate_fault_drills(evidence.get("fault_drills")))
    if _bool(evidence.get("live_enabled"), "live_enabled"):
        diagnostics.append(
            _diagnostic(
                "LIVE_ENABLEMENT_OUT_OF_SCOPE",
                "PR-200 evidence gate cannot enable live trading",
                "live_enabled",
            )
        )
    if _bool(evidence.get("automatic_cutover_enabled"), "automatic_cutover_enabled"):
        diagnostics.append(
            _diagnostic(
                "AUTOMATIC_CUTOVER_FORBIDDEN",
                "cutover must stay manual and explicitly promoted outside this gate",
                "automatic_cutover_enabled",
            )
        )
    ok = not any(item.severity is DiagnosticSeverity.ERROR for item in diagnostics)
    return PR200CutoverReport(
        schema_version=schema,
        phase=phase,
        ok=ok,
        evidence_hash=_hash_mapping(evidence),
        sandbox_manifest_hash=sandbox_report.manifest_hash,
        diagnostics=tuple(diagnostics),
    )


def live_capability_allowed() -> bool:
    """This PR-200 continuation remains an offline validator only."""

    return False


def cutover_capability_allowed() -> bool:
    """This module never performs deployment, promotion, rollback, or send."""

    return False


def _sandbox_report(value: object) -> ProductionSandboxReport:
    if not isinstance(value, Mapping):
        raise PR200CutoverError("sandbox_manifest must be an object")
    return validate_production_sandbox_manifest(value)


def _validate_slo_budgets(value: object) -> tuple[SandboxDiagnostic, ...]:
    if not isinstance(value, Mapping):
        return (
            _diagnostic(
                "SLO_BUDGETS_MISSING",
                "cutover evidence must include named SLO budget proofs",
                "slo_budgets",
            ),
        )
    diagnostics: list[SandboxDiagnostic] = []
    for name in _REQUIRED_SLO_BUDGETS:
        raw = value.get(name)
        path = f"slo_budgets.{name}"
        if not isinstance(raw, Mapping):
            diagnostics.append(
                _diagnostic(
                    "SLO_BUDGET_MISSING",
                    f"required SLO budget {name!r} is missing",
                    path,
                )
            )
            continue
        if not _bool(raw.get("passed_under_fault"), f"{path}.passed_under_fault"):
            diagnostics.append(
                _diagnostic(
                    "SLO_BUDGET_NOT_PROVEN",
                    f"SLO budget {name!r} did not pass under fault load",
                    f"{path}.passed_under_fault",
                )
            )
        _append_hash_diagnostic(
            diagnostics,
            raw.get("evidence_hash"),
            f"{path}.evidence_hash",
            code="SLO_EVIDENCE_HASH_INVALID",
        )
    return tuple(diagnostics)


def _validate_fault_drills(value: object) -> tuple[SandboxDiagnostic, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return (
            _diagnostic(
                "FAULT_DRILLS_MISSING",
                "cutover evidence must include required fault drills",
                "fault_drills",
            ),
        )
    drills: dict[str, Mapping[str, Any]] = {}
    diagnostics: list[SandboxDiagnostic] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            diagnostics.append(
                _diagnostic(
                    "FAULT_DRILL_MALFORMED",
                    "fault drill entries must be objects",
                    f"fault_drills[{index}]",
                )
            )
            continue
        name = _non_empty(item.get("name"), f"fault_drills[{index}].name")
        drills[name] = item
    for name in _REQUIRED_FAULT_DRILLS:
        raw = drills.get(name)
        path = f"fault_drills.{name}"
        if raw is None:
            diagnostics.append(
                _diagnostic(
                    "FAULT_DRILL_MISSING",
                    f"required fault drill {name!r} is missing",
                    path,
                )
            )
            continue
        if not _bool(raw.get("passed"), f"{path}.passed"):
            diagnostics.append(
                _diagnostic(
                    "FAULT_DRILL_FAILED",
                    f"fault drill {name!r} did not pass",
                    f"{path}.passed",
                )
            )
        if not _non_empty(raw.get("invariant"), f"{path}.invariant"):
            diagnostics.append(
                _diagnostic(
                    "FAULT_INVARIANT_MISSING",
                    f"fault drill {name!r} must bind an expected invariant",
                    f"{path}.invariant",
                )
            )
        _append_hash_diagnostic(
            diagnostics,
            raw.get("evidence_hash"),
            f"{path}.evidence_hash",
            code="FAULT_EVIDENCE_HASH_INVALID",
        )
    return tuple(diagnostics)


def _missing_true_flags(
    value: object,
    required: tuple[str, ...],
    *,
    section: str,
    code: str,
) -> tuple[SandboxDiagnostic, ...]:
    if not isinstance(value, Mapping):
        return (
            _diagnostic(
                code,
                f"{section} evidence must be an object",
                section,
            ),
        )
    diagnostics: list[SandboxDiagnostic] = []
    for name in required:
        if value.get(name) is not True:
            diagnostics.append(
                _diagnostic(
                    code,
                    f"{section}.{name} must be true",
                    f"{section}.{name}",
                )
            )
    return tuple(diagnostics)


def _append_hash_diagnostic(
    diagnostics: list[SandboxDiagnostic],
    value: object,
    path: str,
    *,
    code: str,
) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.lower()):
        diagnostics.append(
            _diagnostic(
                code,
                f"{path} must be a sha256 evidence hash",
                path,
            )
        )


def _diagnostic(code: str, message: str, path: str) -> SandboxDiagnostic:
    return SandboxDiagnostic(code, DiagnosticSeverity.ERROR, message, path)


def _phase(value: object) -> CutoverPhase:
    text = _non_empty(value, "phase")
    try:
        return CutoverPhase(text)
    except ValueError as exc:
        raise PR200CutoverError(f"unsupported cutover phase: {text}") from exc


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise PR200CutoverError(f"{field} must be boolean")
    return value


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR200CutoverError(f"{field} must be a non-empty string")
    return value.strip()


def _hash_mapping(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = [
    "CutoverPhase",
    "PR200_CUTOVER_SCHEMA_VERSION",
    "PR200CutoverError",
    "PR200CutoverReport",
    "cutover_capability_allowed",
    "live_capability_allowed",
    "validate_pr200_cutover_evidence",
]
