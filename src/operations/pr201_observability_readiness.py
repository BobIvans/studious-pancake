"""PR-201 observability, readiness, deployment and release-image evidence.

This module is intentionally sender-free.  It does not import wallet, signer,
transaction builder, sender, Jito, or live execution code.  It gives the PR-201
vertical a small fail-closed authority for operator-facing readiness, bounded
observability labels, backup/restore rehearsals and immutable release-image
identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

PR201_SCHEMA_VERSION = "pr201.ops-readiness-release.v1"
_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|auth[_-]?header|bearer|keypair|passphrase|"
    r"password|private[_-]?key|secret|seed|token)",
    re.IGNORECASE,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST_RE = re.compile(r"^[a-z0-9._/-]+@sha256:[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class PR201EvidenceError(ValueError):
    """Fail-closed PR-201 validation error with a stable reason code."""

    def __init__(self, reason_code: str, message: str | None = None) -> None:
        self.reason_code = reason_code
        super().__init__(message or reason_code)


class ReadinessStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ReadinessSignal:
    name: str
    healthy: bool
    mandatory: bool
    stale: bool
    evidence_hash: str

    def __post_init__(self) -> None:
        _require_safe_id(self.name, "name")
        _require_sha256(self.evidence_hash, "evidence_hash")


@dataclass(frozen=True, slots=True)
class ManagementReadinessSnapshot:
    """One explicit management/readiness plane snapshot.

    Liveness, safe-idle, data, paper workload, protocol, DB/outbox and live gate
    are separate fields so a green management listener cannot mask dead workload.
    """

    run_id: str
    source_commit: str
    image_digest: str
    config_hash: str
    contract_evidence_hash: str
    observed_at_ms: int
    liveness_healthy: bool
    safe_idle_allowed: bool
    data_ready: bool
    paper_worker_alive: bool
    paper_workload_fresh: bool
    protocol_ready: bool
    db_healthy: bool
    outbox_healthy: bool
    live_enabled: bool = False
    signals: tuple[ReadinessSignal, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        _require_safe_id(self.run_id, "run_id")
        _require_sha256(self.source_commit, "source_commit")
        _require_image_digest(self.image_digest, "image_digest")
        _require_sha256(self.config_hash, "config_hash")
        _require_sha256(self.contract_evidence_hash, "contract_evidence_hash")
        _require_nonnegative_int(self.observed_at_ms, "observed_at_ms")
        if self.live_enabled:
            raise PR201EvidenceError("PR201_LIVE_MUST_REMAIN_DISABLED")
        names: set[str] = set()
        for signal in self.signals:
            if signal.name in names:
                raise PR201EvidenceError("PR201_DUPLICATE_READINESS_SIGNAL")
            names.add(signal.name)

    def evaluate(self) -> dict[str, object]:
        blockers: list[str] = []
        degraded: list[str] = []
        if not self.liveness_healthy:
            blockers.append("PR201_LIVENESS_UNHEALTHY")
        if not self.paper_worker_alive:
            blockers.append("PR201_MANDATORY_PAPER_WORKER_DEAD")
        if not self.paper_workload_fresh:
            blockers.append("PR201_PAPER_WORKLOAD_STALE")
        if not self.data_ready:
            blockers.append("PR201_DATA_NOT_READY")
        if not self.protocol_ready:
            blockers.append("PR201_PROTOCOL_NOT_READY")
        if not self.db_healthy:
            blockers.append("PR201_DB_UNHEALTHY")
        if not self.outbox_healthy:
            blockers.append("PR201_OUTBOX_UNHEALTHY")
        for signal in self.signals:
            if signal.stale and signal.mandatory:
                blockers.append(f"PR201_STALE_MANDATORY_SIGNAL:{signal.name}")
            elif signal.stale:
                degraded.append(f"PR201_STALE_OPTIONAL_SIGNAL:{signal.name}")
            if not signal.healthy and signal.mandatory:
                blockers.append(f"PR201_UNHEALTHY_MANDATORY_SIGNAL:{signal.name}")
            elif not signal.healthy:
                degraded.append(f"PR201_UNHEALTHY_OPTIONAL_SIGNAL:{signal.name}")

        healthy = not blockers and not degraded
        status = (
            ReadinessStatus.HEALTHY
            if healthy
            else ReadinessStatus.BLOCKED
            if blockers
            else ReadinessStatus.DEGRADED
        )
        return {
            "schema_version": PR201_SCHEMA_VERSION,
            "status": status.value,
            "healthy": healthy,
            "liveness": self.liveness_healthy,
            "safe_idle": self.liveness_healthy
            and self.safe_idle_allowed
            and not self.live_enabled,
            "data_readiness": self.data_ready,
            "paper_workload_readiness": self.paper_worker_alive
            and self.paper_workload_fresh,
            "protocol_readiness": self.protocol_ready,
            "db_outbox_health": self.db_healthy and self.outbox_healthy,
            "live_gate": False,
            "live_enabled": False,
            "signer_reachable": False,
            "sender_reachable": False,
            "submission_allowed": False,
            "blockers": tuple(blockers),
            "degraded_reasons": tuple(degraded),
            "signal_count": len(self.signals),
        }


@dataclass(frozen=True, slots=True)
class SloBudget:
    max_cycle_freshness_ms: int
    max_durable_inbox_lag_ms: int
    max_queue_age_ms: int
    min_provider_success_ratio: float
    min_reconciliation_completeness_ratio: float
    max_shutdown_ms: int
    max_recovery_ms: int
    max_db_contention_ms: int

    def __post_init__(self) -> None:
        _require_positive_int(self.max_cycle_freshness_ms, "max_cycle_freshness_ms")
        _require_positive_int(
            self.max_durable_inbox_lag_ms, "max_durable_inbox_lag_ms"
        )
        _require_positive_int(self.max_queue_age_ms, "max_queue_age_ms")
        _require_ratio(self.min_provider_success_ratio, "min_provider_success_ratio")
        _require_ratio(
            self.min_reconciliation_completeness_ratio,
            "min_reconciliation_completeness_ratio",
        )
        _require_positive_int(self.max_shutdown_ms, "max_shutdown_ms")
        _require_positive_int(self.max_recovery_ms, "max_recovery_ms")
        _require_positive_int(self.max_db_contention_ms, "max_db_contention_ms")


@dataclass(frozen=True, slots=True)
class SloMeasurement:
    cycle_freshness_ms: int
    durable_inbox_lag_ms: int
    queue_age_ms: int
    provider_success_ratio: float
    reconciliation_completeness_ratio: float
    shutdown_ms: int
    recovery_ms: int
    db_contention_ms: int
    data_loss_detected: bool

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.cycle_freshness_ms, "cycle_freshness_ms")
        _require_nonnegative_int(self.durable_inbox_lag_ms, "durable_inbox_lag_ms")
        _require_nonnegative_int(self.queue_age_ms, "queue_age_ms")
        _require_ratio(self.provider_success_ratio, "provider_success_ratio")
        _require_ratio(
            self.reconciliation_completeness_ratio,
            "reconciliation_completeness_ratio",
        )
        _require_nonnegative_int(self.shutdown_ms, "shutdown_ms")
        _require_nonnegative_int(self.recovery_ms, "recovery_ms")
        _require_nonnegative_int(self.db_contention_ms, "db_contention_ms")


def evaluate_slos(budget: SloBudget, measurement: SloMeasurement) -> dict[str, object]:
    blockers: list[str] = []
    if measurement.data_loss_detected:
        blockers.append("PR201_DATA_LOSS_INVARIANT_VIOLATED")
    if measurement.cycle_freshness_ms > budget.max_cycle_freshness_ms:
        blockers.append("PR201_CYCLE_FRESHNESS_SLO_VIOLATED")
    if measurement.durable_inbox_lag_ms > budget.max_durable_inbox_lag_ms:
        blockers.append("PR201_DURABLE_INBOX_LAG_SLO_VIOLATED")
    if measurement.queue_age_ms > budget.max_queue_age_ms:
        blockers.append("PR201_QUEUE_AGE_SLO_VIOLATED")
    if measurement.provider_success_ratio < budget.min_provider_success_ratio:
        blockers.append("PR201_PROVIDER_SUCCESS_SLO_VIOLATED")
    if (
        measurement.reconciliation_completeness_ratio
        < budget.min_reconciliation_completeness_ratio
    ):
        blockers.append("PR201_RECONCILIATION_COMPLETENESS_SLO_VIOLATED")
    if measurement.shutdown_ms > budget.max_shutdown_ms:
        blockers.append("PR201_SHUTDOWN_SLO_VIOLATED")
    if measurement.recovery_ms > budget.max_recovery_ms:
        blockers.append("PR201_RECOVERY_SLO_VIOLATED")
    if measurement.db_contention_ms > budget.max_db_contention_ms:
        blockers.append("PR201_DB_CONTENTION_SLO_VIOLATED")
    return {
        "schema_version": PR201_SCHEMA_VERSION,
        "status": ReadinessStatus.HEALTHY.value
        if not blockers
        else ReadinessStatus.BLOCKED.value,
        "slo_passed": not blockers,
        "blockers": tuple(blockers),
    }


def sanitize_observability_event(
    event: Mapping[str, object],
    *,
    label_budget: int = 32,
    max_value_length: int = 128,
) -> dict[str, object]:
    """Redact secrets and bound high-cardinality labels before evidence export."""

    _require_positive_int(label_budget, "label_budget")
    _require_positive_int(max_value_length, "max_value_length")
    sanitized: dict[str, object] = {}
    label_count = 0
    for raw_key, raw_value in sorted(event.items()):
        key = str(raw_key)
        _require_safe_label_key(key)
        if key.startswith("label."):
            label_count += 1
            if label_count > label_budget:
                raise PR201EvidenceError("PR201_LABEL_CARDINALITY_BUDGET_EXCEEDED")
        if _SECRET_KEY_RE.search(key):
            sanitized[key] = "[REDACTED]"
            continue
        sanitized[key] = _sanitize_value(raw_value, max_value_length=max_value_length)
    return sanitized


@dataclass(frozen=True, slots=True)
class DeploymentHardeningSnapshot:
    image_digest: str
    sbom_sha256: str
    attestation_sha256: str
    seccomp_profile_sha256: str
    resource_limits_sha256: str
    non_root_user: bool
    read_only_rootfs: bool
    cap_drop_all: bool
    no_new_privileges: bool
    persistent_volume_owner_uid: int

    def __post_init__(self) -> None:
        _require_image_digest(self.image_digest, "image_digest")
        _require_sha256(self.sbom_sha256, "sbom_sha256")
        _require_sha256(self.attestation_sha256, "attestation_sha256")
        _require_sha256(self.seccomp_profile_sha256, "seccomp_profile_sha256")
        _require_sha256(self.resource_limits_sha256, "resource_limits_sha256")
        _require_nonnegative_int(
            self.persistent_volume_owner_uid, "persistent_volume_owner_uid"
        )

    def evaluate(self) -> dict[str, object]:
        blockers: list[str] = []
        if not self.non_root_user:
            blockers.append("PR201_CONTAINER_ROOT_USER")
        if not self.read_only_rootfs:
            blockers.append("PR201_ROOTFS_NOT_READ_ONLY")
        if not self.cap_drop_all:
            blockers.append("PR201_CAPABILITIES_NOT_DROPPED")
        if not self.no_new_privileges:
            blockers.append("PR201_NO_NEW_PRIVILEGES_DISABLED")
        if self.persistent_volume_owner_uid == 0:
            blockers.append("PR201_PERSISTENT_VOLUME_ROOT_OWNED")
        return {
            "schema_version": PR201_SCHEMA_VERSION,
            "status": ReadinessStatus.HEALTHY.value
            if not blockers
            else ReadinessStatus.BLOCKED.value,
            "deployment_hardened": not blockers,
            "blockers": tuple(blockers),
            "image_digest": self.image_digest,
        }


@dataclass(frozen=True, slots=True)
class BackupRestoreRehearsal:
    before_state_hash: str
    before_outbox_hash: str
    before_accounting_hash: str
    restored_state_hash: str
    restored_outbox_hash: str
    restored_accounting_hash: str
    migration_rehearsed: bool
    integrity_check_passed: bool
    destructive_test_id: str
    rto_ms: int
    rpo_ms: int

    def __post_init__(self) -> None:
        for field_name in (
            "before_state_hash",
            "before_outbox_hash",
            "before_accounting_hash",
            "restored_state_hash",
            "restored_outbox_hash",
            "restored_accounting_hash",
        ):
            _require_sha256(str(getattr(self, field_name)), field_name)
        _require_safe_id(self.destructive_test_id, "destructive_test_id")
        _require_nonnegative_int(self.rto_ms, "rto_ms")
        _require_nonnegative_int(self.rpo_ms, "rpo_ms")

    def evaluate(self, *, max_rto_ms: int, max_rpo_ms: int) -> dict[str, object]:
        _require_positive_int(max_rto_ms, "max_rto_ms")
        _require_nonnegative_int(max_rpo_ms, "max_rpo_ms")
        blockers: list[str] = []
        if self.before_state_hash != self.restored_state_hash:
            blockers.append("PR201_RESTORED_STATE_HASH_MISMATCH")
        if self.before_outbox_hash != self.restored_outbox_hash:
            blockers.append("PR201_RESTORED_OUTBOX_HASH_MISMATCH")
        if self.before_accounting_hash != self.restored_accounting_hash:
            blockers.append("PR201_RESTORED_ACCOUNTING_HASH_MISMATCH")
        if not self.migration_rehearsed:
            blockers.append("PR201_MIGRATION_REHEARSAL_MISSING")
        if not self.integrity_check_passed:
            blockers.append("PR201_INTEGRITY_CHECK_FAILED")
        if self.rto_ms > max_rto_ms:
            blockers.append("PR201_RTO_EXCEEDED")
        if self.rpo_ms > max_rpo_ms:
            blockers.append("PR201_RPO_EXCEEDED")
        return {
            "schema_version": PR201_SCHEMA_VERSION,
            "status": ReadinessStatus.HEALTHY.value
            if not blockers
            else ReadinessStatus.BLOCKED.value,
            "backup_restore_passed": not blockers,
            "blockers": tuple(blockers),
            "destructive_test_id": self.destructive_test_id,
        }


@dataclass(frozen=True, slots=True)
class ReleaseImageManifest:
    source_commit: str
    lock_hash: str
    wheel_hash: str
    image_digest: str
    config_hash: str
    contract_evidence_hash: str
    soak_artifact_hash: str

    def __post_init__(self) -> None:
        _require_sha256(self.source_commit, "source_commit")
        _require_sha256(self.lock_hash, "lock_hash")
        _require_sha256(self.wheel_hash, "wheel_hash")
        _require_image_digest(self.image_digest, "image_digest")
        _require_sha256(self.config_hash, "config_hash")
        _require_sha256(self.contract_evidence_hash, "contract_evidence_hash")
        _require_sha256(self.soak_artifact_hash, "soak_artifact_hash")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": PR201_SCHEMA_VERSION,
            "source_commit": self.source_commit,
            "lock_hash": self.lock_hash,
            "wheel_hash": self.wheel_hash,
            "image_digest": self.image_digest,
            "config_hash": self.config_hash,
            "contract_evidence_hash": self.contract_evidence_hash,
            "soak_artifact_hash": self.soak_artifact_hash,
            "manifest_hash": self.manifest_hash,
        }

    @property
    def manifest_hash(self) -> str:
        return _sha256_json(
            {
                "schema_version": PR201_SCHEMA_VERSION,
                "source_commit": self.source_commit,
                "lock_hash": self.lock_hash,
                "wheel_hash": self.wheel_hash,
                "image_digest": self.image_digest,
                "config_hash": self.config_hash,
                "contract_evidence_hash": self.contract_evidence_hash,
                "soak_artifact_hash": self.soak_artifact_hash,
            }
        )


def operator_readiness_report(
    *,
    readiness: ManagementReadinessSnapshot,
    slo: Mapping[str, object],
    deployment: Mapping[str, object],
    backup_restore: Mapping[str, object],
    release_manifest: ReleaseImageManifest,
) -> dict[str, object]:
    readiness_report = readiness.evaluate()
    components = (readiness_report, slo, deployment, backup_restore)
    blockers: list[str] = []
    for component in components:
        blockers.extend(str(item) for item in component.get("blockers", ()))
    return {
        "schema_version": PR201_SCHEMA_VERSION,
        "status": ReadinessStatus.HEALTHY.value
        if not blockers
        else ReadinessStatus.BLOCKED.value,
        "operator_ready": not blockers,
        "blockers": tuple(blockers),
        "readiness": readiness_report,
        "slo": dict(slo),
        "deployment": dict(deployment),
        "backup_restore": dict(backup_restore),
        "release_manifest": release_manifest.to_dict(),
        "live_enabled": False,
        "signer_reachable": False,
        "sender_reachable": False,
        "submission_allowed": False,
    }


def _sanitize_value(value: object, *, max_value_length: int) -> object:
    if isinstance(value, str):
        if len(value) > max_value_length:
            return {
                "truncated": True,
                "sha256": _sha256_text(value),
                "prefix": value[: min(16, max_value_length)],
            }
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return sanitize_observability_event(
            value, label_budget=64, max_value_length=max_value_length
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(
            _sanitize_value(item, max_value_length=max_value_length)
            for item in value[:16]
        )
    return {"type": type(value).__name__, "sha256": _sha256_text(repr(value))}


def _require_safe_label_key(value: str) -> None:
    if not re.match(r"^[A-Za-z0-9_.:-]{1,128}$", value):
        raise PR201EvidenceError("PR201_UNSAFE_OBSERVABILITY_KEY")


def _require_safe_id(value: str, field_name: str) -> None:
    if not _SAFE_ID_RE.match(value):
        raise PR201EvidenceError(f"PR201_INVALID_{field_name.upper()}")


def _require_sha256(value: str, field_name: str) -> None:
    if not _SHA256_RE.match(value):
        raise PR201EvidenceError(f"PR201_INVALID_{field_name.upper()}")


def _require_image_digest(value: str, field_name: str) -> None:
    if not _IMAGE_DIGEST_RE.match(value):
        raise PR201EvidenceError(f"PR201_INVALID_{field_name.upper()}")


def _require_positive_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PR201EvidenceError(f"PR201_INVALID_{field_name.upper()}")


def _require_nonnegative_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PR201EvidenceError(f"PR201_INVALID_{field_name.upper()}")


def _require_ratio(value: float, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PR201EvidenceError(f"PR201_INVALID_{field_name.upper()}")
    if float(value) < 0.0 or float(value) > 1.0:
        raise PR201EvidenceError(f"PR201_INVALID_{field_name.upper()}")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
