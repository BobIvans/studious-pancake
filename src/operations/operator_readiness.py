"""PR-077 operator readiness evidence boundary.

This module composes the already-existing data-plane, lifecycle and health
primitives into a single offline operator-readiness decision.  It deliberately
does not open sockets, call RPC, read keys, sign, submit, or mutate runtime
state.  A passing result means "operator evidence is coherent for review", not
"live trading is enabled".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "pr077.operator-readiness.v1"
RESULT_SCHEMA_VERSION = "pr077.operator-readiness-result.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_TRACE_STAGES = (
    "discovery",
    "quota",
    "candidate",
    "planner",
    "simulation",
    "reconciliation",
)
REQUIRED_LIFECYCLE_STAGES = (
    "discovery",
    "capital_reservation",
    "planner",
    "final_simulation",
    "reconciliation",
    "paper_outcome",
)


class OperatorReadinessBlocker(StrEnum):
    """Machine-stable blockers for PR-077 readiness."""

    TRACE_ID_MISSING = "TRACE_ID_MISSING"
    TRACE_STAGE_MISSING = "TRACE_STAGE_MISSING"
    TRACE_STAGE_FAILED = "TRACE_STAGE_FAILED"
    METRIC_STAGE_MISSING = "METRIC_STAGE_MISSING"
    DATA_PLANE_NOT_READY = "DATA_PLANE_NOT_READY"
    RPC_STALE_OR_INCONSISTENT = "RPC_STALE_OR_INCONSISTENT"
    WEBSOCKET_GAP_OR_STALE = "WEBSOCKET_GAP_OR_STALE"
    ORACLE_STALE_OR_LOW_CONFIDENCE = "ORACLE_STALE_OR_LOW_CONFIDENCE"
    RECONCILIATION_INDETERMINATE = "RECONCILIATION_INDETERMINATE"
    HTTP_HEALTH_UNHEALTHY = "HTTP_HEALTH_UNHEALTHY"
    HTTP_READY_NOT_READY = "HTTP_READY_NOT_READY"
    LIFECYCLE_STAGE_MISSING = "LIFECYCLE_STAGE_MISSING"
    LIFECYCLE_RECOVERY_UNSAFE = "LIFECYCLE_RECOVERY_UNSAFE"
    LIFECYCLE_DUPLICATE_OUTCOME = "LIFECYCLE_DUPLICATE_OUTCOME"
    LIFECYCLE_DUPLICATE_RESERVATION = "LIFECYCLE_DUPLICATE_RESERVATION"
    BACKUP_RESTORE_ARTIFACT_MISSING = "BACKUP_RESTORE_ARTIFACT_MISSING"
    BACKUP_RESTORE_NOT_REVIEWED = "BACKUP_RESTORE_NOT_REVIEWED"
    MIGRATION_OR_CORRUPTION_DRILL_MISSING = "MIGRATION_OR_CORRUPTION_DRILL_MISSING"
    LOG_REDACTION_MISSING = "LOG_REDACTION_MISSING"
    RAW_PRIVATE_DATA_LOGGED = "RAW_PRIVATE_DATA_LOGGED"
    LIVE_MUTATION_PRESENT = "LIVE_MUTATION_PRESENT"


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def sha256_json(value: Any) -> str:
    payload = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _is_real_sha256(value: str) -> bool:
    lowered = value.lower()
    return bool(_SHA256_RE.fullmatch(lowered)) and lowered != "0" * 64


def _require_real_sha256(value: str, field_name: str) -> str:
    lowered = _require_non_empty(value, field_name).lower()
    if not _is_real_sha256(lowered):
        raise ValueError(f"{field_name} must be a non-placeholder SHA-256 digest")
    return lowered


@dataclass(frozen=True, slots=True)
class TraceStageEvidence:
    """One stage participating in the end-to-end operator trace."""

    stage: str
    trace_id: str
    status: str
    evidence_hash: str
    started_at_unix_ns: int
    ended_at_unix_ns: int
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", _require_non_empty(self.stage, "stage"))
        object.__setattr__(
            self, "trace_id", _require_non_empty(self.trace_id, "trace_id")
        )
        object.__setattr__(self, "status", _require_non_empty(self.status, "status"))
        object.__setattr__(
            self,
            "evidence_hash",
            _require_real_sha256(self.evidence_hash, "evidence_hash"),
        )
        if self.started_at_unix_ns < 0 or self.ended_at_unix_ns < 0:
            raise ValueError("trace timestamps must be non-negative")
        if self.ended_at_unix_ns < self.started_at_unix_ns:
            raise ValueError("trace stage end must not precede start")
        object.__setattr__(
            self,
            "labels",
            {str(key): str(value) for key, value in dict(self.labels).items()},
        )


@dataclass(frozen=True, slots=True)
class StageMetricEvidence:
    """Metrics emitted by an active runner stage."""

    stage: str
    counters: Mapping[str, int]
    gauges: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", _require_non_empty(self.stage, "stage"))
        for field_name in ("counters", "gauges"):
            values = dict(getattr(self, field_name))
            for key, value in values.items():
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise ValueError(f"{field_name}.{key} must be a non-negative int")
            object.__setattr__(self, field_name, values)


@dataclass(frozen=True, slots=True)
class LifecycleRecoveryEvidence:
    """Restart/idempotency proof for one lifecycle stage."""

    stage: str
    recovery_state: str
    idempotency_key: str
    evidence_hash: str
    replay_safe: bool
    duplicate_outcome: bool = False
    duplicate_reservation: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage", _require_non_empty(self.stage, "stage"))
        object.__setattr__(
            self,
            "recovery_state",
            _require_non_empty(self.recovery_state, "recovery_state"),
        )
        object.__setattr__(
            self,
            "idempotency_key",
            _require_non_empty(self.idempotency_key, "idempotency_key"),
        )
        object.__setattr__(
            self,
            "evidence_hash",
            _require_real_sha256(self.evidence_hash, "evidence_hash"),
        )


@dataclass(frozen=True, slots=True)
class BackupRestoreEvidence:
    """Operator-reviewed backup/restore, migration and corruption drill proof."""

    artifact_path: str
    artifact_sha256: str
    restored_sha256: str
    migration_checked: bool
    corruption_handled: bool
    reviewed: bool
    reviewer: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact_path", _require_non_empty(self.artifact_path, "path")
        )
        object.__setattr__(
            self,
            "artifact_sha256",
            _require_real_sha256(self.artifact_sha256, "artifact_sha256"),
        )
        object.__setattr__(
            self,
            "restored_sha256",
            _require_real_sha256(self.restored_sha256, "restored_sha256"),
        )
        object.__setattr__(
            self, "reviewer", _require_non_empty(self.reviewer, "reviewer")
        )


@dataclass(frozen=True, slots=True)
class OperatorRuntimeEvidence:
    """Composed snapshot from data-plane, lifecycle and HTTP status primitives."""

    trace_id: str
    data_plane_ready: bool
    data_plane_reasons: tuple[str, ...]
    http_health_ok: bool
    http_ready_ok: bool
    trace_stages: tuple[TraceStageEvidence, ...]
    metrics: tuple[StageMetricEvidence, ...]
    lifecycle_recovery: tuple[LifecycleRecoveryEvidence, ...]
    backup_restore: BackupRestoreEvidence | None
    logs_redacted: bool
    raw_private_data_logged: bool = False
    indeterminate_reconciliation: bool = False
    live_mutation_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "trace_id", _require_non_empty(self.trace_id, "trace_id")
        )
        object.__setattr__(
            self, "data_plane_reasons", tuple(sorted(set(self.data_plane_reasons)))
        )

    @property
    def evidence_hash(self) -> str:
        return sha256_json(self)


@dataclass(frozen=True, slots=True)
class OperatorReadinessResult:
    schema_version: str
    ready: bool
    state: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_hash: str
    trace_id: str
    checks_evaluated: int
    live_mutation_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class OperatorReadinessGate:
    """Offline PR-077 gate for operator/runbook readiness evidence."""

    required_trace_stages: frozenset[str] = frozenset(REQUIRED_TRACE_STAGES)
    required_lifecycle_stages: frozenset[str] = frozenset(REQUIRED_LIFECYCLE_STAGES)

    def evaluate(self, evidence: OperatorRuntimeEvidence) -> OperatorReadinessResult:
        blockers: list[str] = []
        warnings: list[str] = []
        checks = 0

        def check(condition: bool, reason: OperatorReadinessBlocker) -> None:
            nonlocal checks
            checks += 1
            if not condition:
                blockers.append(reason.value)

        check(bool(evidence.trace_id), OperatorReadinessBlocker.TRACE_ID_MISSING)
        trace_by_stage = {item.stage: item for item in evidence.trace_stages}
        metric_stages = {item.stage for item in evidence.metrics}
        lifecycle_by_stage = {item.stage: item for item in evidence.lifecycle_recovery}

        check(
            self.required_trace_stages <= set(trace_by_stage),
            OperatorReadinessBlocker.TRACE_STAGE_MISSING,
        )
        for stage in sorted(self.required_trace_stages & set(trace_by_stage)):
            item = trace_by_stage[stage]
            check(
                item.trace_id == evidence.trace_id and item.status == "ok",
                OperatorReadinessBlocker.TRACE_STAGE_FAILED,
            )
        check(
            self.required_trace_stages <= metric_stages,
            OperatorReadinessBlocker.METRIC_STAGE_MISSING,
        )

        check(evidence.data_plane_ready, OperatorReadinessBlocker.DATA_PLANE_NOT_READY)
        reasons = set(evidence.data_plane_reasons)
        check(
            not any("RPC" in reason and "OK" not in reason for reason in reasons),
            OperatorReadinessBlocker.RPC_STALE_OR_INCONSISTENT,
        )
        check(
            not any(
                reason.startswith("PR040_WS_") or "SLOT_GAP" in reason
                for reason in reasons
            ),
            OperatorReadinessBlocker.WEBSOCKET_GAP_OR_STALE,
        )
        check(
            not any("ORACLE" in reason and "OK" not in reason for reason in reasons),
            OperatorReadinessBlocker.ORACLE_STALE_OR_LOW_CONFIDENCE,
        )
        check(
            not evidence.indeterminate_reconciliation,
            OperatorReadinessBlocker.RECONCILIATION_INDETERMINATE,
        )
        check(evidence.http_health_ok, OperatorReadinessBlocker.HTTP_HEALTH_UNHEALTHY)
        check(evidence.http_ready_ok, OperatorReadinessBlocker.HTTP_READY_NOT_READY)

        check(
            self.required_lifecycle_stages <= set(lifecycle_by_stage),
            OperatorReadinessBlocker.LIFECYCLE_STAGE_MISSING,
        )
        for stage in sorted(self.required_lifecycle_stages & set(lifecycle_by_stage)):
            item = lifecycle_by_stage[stage]
            check(
                item.replay_safe,
                OperatorReadinessBlocker.LIFECYCLE_RECOVERY_UNSAFE,
            )
            check(
                not item.duplicate_outcome,
                OperatorReadinessBlocker.LIFECYCLE_DUPLICATE_OUTCOME,
            )
            check(
                not item.duplicate_reservation,
                OperatorReadinessBlocker.LIFECYCLE_DUPLICATE_RESERVATION,
            )

        backup = evidence.backup_restore
        check(
            backup is not None,
            OperatorReadinessBlocker.BACKUP_RESTORE_ARTIFACT_MISSING,
        )
        if backup is not None:
            check(
                backup.reviewed,
                OperatorReadinessBlocker.BACKUP_RESTORE_NOT_REVIEWED,
            )
            check(
                backup.migration_checked and backup.corruption_handled,
                OperatorReadinessBlocker.MIGRATION_OR_CORRUPTION_DRILL_MISSING,
            )
            if backup.artifact_sha256 != backup.restored_sha256:
                warnings.append("BACKUP_RESTORE_DIGEST_DIFFERS_AFTER_RESTORE")

        check(evidence.logs_redacted, OperatorReadinessBlocker.LOG_REDACTION_MISSING)
        check(
            not evidence.raw_private_data_logged,
            OperatorReadinessBlocker.RAW_PRIVATE_DATA_LOGGED,
        )
        check(
            not evidence.live_mutation_allowed,
            OperatorReadinessBlocker.LIVE_MUTATION_PRESENT,
        )

        unique_blockers = tuple(dict.fromkeys(blockers))
        ready = not unique_blockers
        return OperatorReadinessResult(
            schema_version=RESULT_SCHEMA_VERSION,
            ready=ready,
            state=("operator-ready-for-shadow-soak-review" if ready else "blocked"),
            blockers=unique_blockers,
            warnings=tuple(dict.fromkeys(warnings)),
            evidence_hash=evidence.evidence_hash,
            trace_id=evidence.trace_id,
            checks_evaluated=checks,
            live_mutation_allowed=False,
        )


def build_operator_evidence_from_status(
    *,
    trace_id: str,
    status_payload: Mapping[str, Any],
    data_plane_ready: bool,
    data_plane_reasons: Iterable[str],
    trace_stages: Iterable[TraceStageEvidence],
    metrics: Iterable[StageMetricEvidence],
    lifecycle_recovery: Iterable[LifecycleRecoveryEvidence],
    backup_restore: BackupRestoreEvidence | None,
    logs_redacted: bool,
    indeterminate_reconciliation: bool = False,
) -> OperatorRuntimeEvidence:
    """Build PR-077 evidence from a redacted `/status` payload and stage data."""

    health = status_payload.get("health")
    readiness = status_payload.get("readiness")
    if not isinstance(health, Mapping):
        health = {}
    if not isinstance(readiness, Mapping):
        readiness = {}
    safety = status_payload.get("safety")
    if not isinstance(safety, Mapping):
        safety = {}
    return OperatorRuntimeEvidence(
        trace_id=trace_id,
        data_plane_ready=data_plane_ready,
        data_plane_reasons=tuple(str(item) for item in data_plane_reasons),
        http_health_ok=health.get("ok") is True,
        http_ready_ok=readiness.get("ok") is True,
        trace_stages=tuple(trace_stages),
        metrics=tuple(metrics),
        lifecycle_recovery=tuple(lifecycle_recovery),
        backup_restore=backup_restore,
        logs_redacted=logs_redacted,
        raw_private_data_logged=False,
        indeterminate_reconciliation=indeterminate_reconciliation,
        live_mutation_allowed=(
            safety.get("live_enabled") is True
            or safety.get("submitted") is True
            or safety.get("signing_enabled") is True
        ),
    )
