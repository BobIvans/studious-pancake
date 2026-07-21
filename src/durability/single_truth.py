"""PR-121 single durable lifecycle truth review gate.

Offline only: this evaluates the evidence required before runtime can migrate to
one transactional SQLite lifecycle store.  It never writes a database, imports a
sender, submits a transaction, or enables paper/live execution.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

PR121_SCHEMA_VERSION = "pr121.single-durable-lifecycle-truth.v1"
PR121_RESULT_SCHEMA_VERSION = "pr121.single-durable-lifecycle-truth-result.v1"
PR121_READY_STATE = "single-durable-lifecycle-truth-review-ready"
PR121_BLOCKED_STATE = "blocked"

REQUIRED_STATE_COMPONENTS = (
    "candidate",
    "attempt",
    "reservation",
    "plan",
    "compile",
    "simulation",
    "reconciliation",
    "outcome",
    "sender_state",
)
REQUIRED_TRANSACTION_BINDINGS = (
    "state_transition",
    "reservation_update",
    "audit_event",
    "outbox_event",
)
REQUIRED_OUTBOX_FEATURES = (
    "claim",
    "complete",
    "fail",
    "reschedule",
    "exponential_backoff",
    "jitter",
    "max_attempts",
    "dead_letter",
    "poison_quarantine",
    "operator_replay",
)
REQUIRED_BACKUP_FEATURES = (
    "sqlite_online_backup",
    "temporary_destination",
    "fsync_file",
    "fsync_directory",
    "atomic_rename",
    "signed_manifest",
)
REQUIRED_RESTORE_FEATURES = (
    "validate_before_overwrite",
    "integrity_check",
    "schema_version_check",
    "checksum_check",
    "rollback_plan",
)
REQUIRED_FAILURE_INJECTIONS = (
    "partial_write",
    "disk_full",
    "corrupt_page",
    "process_kill",
    "poison_outbox_item",
    "concurrent_runner",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SingleTruthReadinessState(StrEnum):
    BLOCKED = PR121_BLOCKED_STATE
    REVIEW_READY = PR121_READY_STATE


class SingleTruthError(ValueError):
    """Raised when PR-121 evidence is malformed or blocked."""


@dataclass(frozen=True, slots=True)
class SingleTruthPackage:
    authoritative_store: str
    state_components: Mapping[str, bool]
    transaction_bindings: Mapping[str, bool]
    outbox_features: Mapping[str, bool]
    backup_features: Mapping[str, bool]
    restore_features: Mapping[str, bool]
    failure_scenarios: Mapping[str, bool]
    jsonl_authoritative: bool
    legacy_shadow_store_authoritative: bool
    process_lock_enforced: bool
    process_epoch_recorded: bool
    busy_retry_bounds: bool
    thread_safety_reviewed: bool
    outbox_lease_fencing_enforced: bool
    outbox_retry_schedule_persisted: bool
    outbox_dead_letter_reviewed: bool
    outbox_poison_quarantine: bool
    backup_destination_overwrite_atomic: bool
    backup_manifest_signed: bool
    backup_external_anchor_recorded: bool
    retention_policy_reviewed: bool
    concurrent_runner_tested: bool
    recovery_replay_tested: bool
    dirty_tail_jsonl_regression_tested: bool
    pr100_canonical_execution_evidence_sha256: str
    lifecycle_store_sha256: str
    outbox_schema_sha256: str
    backup_restore_sha256: str
    failure_corpus_sha256: str
    pr121_review_sha256: str
    human_reviewed: bool
    live_execution_allowed: bool
    paper_runtime_migration_enabled: bool
    schema_version: str = PR121_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR121_SCHEMA_VERSION:
            raise SingleTruthError("unsupported PR-121 schema")
        for field in _SHA_FIELDS:
            _sha(str(getattr(self, field)), field)
        for field in _BOOL_FIELDS:
            if not isinstance(getattr(self, field), bool):
                raise SingleTruthError(f"{field} must be boolean")

    @property
    def package_sha256(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class SingleTruthReadiness:
    schema_version: str
    state: SingleTruthReadinessState
    review_ready: bool
    live_execution_allowed: bool
    paper_runtime_migration_enabled: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    package_sha256: str
    checks_evaluated: int
    metrics_summary: Mapping[str, int | str | bool]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_single_durable_lifecycle_truth(
    package: SingleTruthPackage,
) -> SingleTruthReadiness:
    """Evaluate PR-121 readiness while runtime migration remains disabled."""

    blockers: list[str] = []
    checks = 0

    def check(condition: bool, reason: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(reason)

    check(package.authoritative_store == "sqlite", "AUTHORITATIVE_STORE_NOT_SQLITE")
    check(not package.jsonl_authoritative, "JSONL_STILL_AUTHORITATIVE")
    check(
        not package.legacy_shadow_store_authoritative,
        "LEGACY_SHADOW_STORE_STILL_AUTHORITATIVE",
    )
    _check_map(
        check,
        package.state_components,
        REQUIRED_STATE_COMPONENTS,
        "STATE_COMPONENT_MISSING",
    )
    _check_map(
        check,
        package.transaction_bindings,
        REQUIRED_TRANSACTION_BINDINGS,
        "TRANSACTION_BINDING_MISSING",
    )
    _check_map(
        check,
        package.outbox_features,
        REQUIRED_OUTBOX_FEATURES,
        "OUTBOX_FEATURE_MISSING",
    )
    _check_map(
        check,
        package.backup_features,
        REQUIRED_BACKUP_FEATURES,
        "BACKUP_FEATURE_MISSING",
    )
    _check_map(
        check,
        package.restore_features,
        REQUIRED_RESTORE_FEATURES,
        "RESTORE_FEATURE_MISSING",
    )
    _check_map(
        check,
        package.failure_scenarios,
        REQUIRED_FAILURE_INJECTIONS,
        "FAILURE_INJECTION_MISSING",
    )
    check(package.process_lock_enforced, "PROCESS_LOCK_NOT_ENFORCED")
    check(package.process_epoch_recorded, "PROCESS_EPOCH_NOT_RECORDED")
    check(package.busy_retry_bounds, "BUSY_RETRY_BOUNDS_MISSING")
    check(package.thread_safety_reviewed, "THREAD_SAFETY_NOT_REVIEWED")
    check(package.outbox_lease_fencing_enforced, "OUTBOX_LEASE_FENCING_NOT_ENFORCED")
    check(
        package.outbox_retry_schedule_persisted, "OUTBOX_RETRY_SCHEDULE_NOT_PERSISTED"
    )
    check(package.outbox_dead_letter_reviewed, "OUTBOX_DEAD_LETTER_REVIEW_MISSING")
    check(package.outbox_poison_quarantine, "OUTBOX_POISON_QUARANTINE_MISSING")
    check(package.backup_destination_overwrite_atomic, "BACKUP_DESTINATION_NOT_ATOMIC")
    check(package.backup_manifest_signed, "BACKUP_MANIFEST_NOT_SIGNED")
    check(package.backup_external_anchor_recorded, "BACKUP_EXTERNAL_ANCHOR_MISSING")
    check(package.retention_policy_reviewed, "RETENTION_POLICY_NOT_REVIEWED")
    check(package.concurrent_runner_tested, "CONCURRENT_RUNNER_NOT_TESTED")
    check(package.recovery_replay_tested, "RECOVERY_REPLAY_NOT_TESTED")
    check(
        package.dirty_tail_jsonl_regression_tested,
        "DIRTY_TAIL_JSONL_REGRESSION_NOT_TESTED",
    )
    check(package.human_reviewed, "PR121_NOT_HUMAN_REVIEWED")
    check(not package.live_execution_allowed, "LIVE_EXECUTION_ALLOWED")
    check(
        not package.paper_runtime_migration_enabled,
        "PAPER_RUNTIME_MIGRATION_ENABLED_IN_REVIEW_GATE",
    )

    unique = tuple(dict.fromkeys(blockers))
    ready = not unique
    return SingleTruthReadiness(
        schema_version=PR121_RESULT_SCHEMA_VERSION,
        state=(
            SingleTruthReadinessState.REVIEW_READY
            if ready
            else SingleTruthReadinessState.BLOCKED
        ),
        review_ready=ready,
        live_execution_allowed=False,
        paper_runtime_migration_enabled=False,
        blockers=unique,
        warnings=("PR121_REVIEW_ONLY_RUNTIME_MIGRATION_DISABLED",),
        package_sha256=package.package_sha256,
        checks_evaluated=checks,
        metrics_summary={
            "state_components": len(REQUIRED_STATE_COMPONENTS),
            "transaction_bindings": len(REQUIRED_TRANSACTION_BINDINGS),
            "outbox_features": len(REQUIRED_OUTBOX_FEATURES),
            "backup_features": len(REQUIRED_BACKUP_FEATURES),
            "restore_features": len(REQUIRED_RESTORE_FEATURES),
            "failure_injections": len(REQUIRED_FAILURE_INJECTIONS),
            "authoritative_store": package.authoritative_store,
            "jsonl_authoritative": package.jsonl_authoritative,
        },
    )


def assert_single_durable_lifecycle_truth(
    package: SingleTruthPackage,
) -> SingleTruthReadiness:
    result = evaluate_single_durable_lifecycle_truth(package)
    if not result.review_ready:
        raise SingleTruthError(
            f"PR121_SINGLE_TRUTH_BLOCKED:{','.join(result.blockers)}"
        )
    return result


def _check_map(
    check: Any, values: Mapping[str, bool], names: tuple[str, ...], prefix: str
) -> None:
    for name in names:
        check(values.get(name) is True, f"{prefix}:{name}")


def _sha(value: str, field: str) -> None:
    value = value.lower()
    if not _SHA256_RE.fullmatch(value) or value in {"0" * 64, "f" * 64}:
        raise SingleTruthError(f"{field} must be a non-placeholder sha256")


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            item.name: _jsonable(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _digest(payload: Any) -> str:
    encoded = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


_SHA_FIELDS = (
    "pr100_canonical_execution_evidence_sha256",
    "lifecycle_store_sha256",
    "outbox_schema_sha256",
    "backup_restore_sha256",
    "failure_corpus_sha256",
    "pr121_review_sha256",
)
_BOOL_FIELDS = (
    "jsonl_authoritative",
    "legacy_shadow_store_authoritative",
    "process_lock_enforced",
    "process_epoch_recorded",
    "busy_retry_bounds",
    "thread_safety_reviewed",
    "outbox_lease_fencing_enforced",
    "outbox_retry_schedule_persisted",
    "outbox_dead_letter_reviewed",
    "outbox_poison_quarantine",
    "backup_destination_overwrite_atomic",
    "backup_manifest_signed",
    "backup_external_anchor_recorded",
    "retention_policy_reviewed",
    "concurrent_runner_tested",
    "recovery_replay_tested",
    "dirty_tail_jsonl_regression_tested",
    "human_reviewed",
    "live_execution_allowed",
    "paper_runtime_migration_enabled",
)

__all__ = [
    "PR121_BLOCKED_STATE",
    "PR121_READY_STATE",
    "PR121_RESULT_SCHEMA_VERSION",
    "PR121_SCHEMA_VERSION",
    "REQUIRED_BACKUP_FEATURES",
    "REQUIRED_FAILURE_INJECTIONS",
    "REQUIRED_OUTBOX_FEATURES",
    "REQUIRED_RESTORE_FEATURES",
    "REQUIRED_STATE_COMPONENTS",
    "REQUIRED_TRANSACTION_BINDINGS",
    "SingleTruthError",
    "SingleTruthPackage",
    "SingleTruthReadiness",
    "SingleTruthReadinessState",
    "assert_single_durable_lifecycle_truth",
    "evaluate_single_durable_lifecycle_truth",
]
