"""MPR-02 unified durable authority acceptance gate.

The V4 roadmap defines MPR-02 as one transactional authority for attempts,
capital, leases, outbox, evidence pointers and recovery. This module is an
offline, sender-free evidence validator for that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping, Sequence

SCHEMA_VERSION = "mpr02.unified-durable-authority-gate.v1"
PRODUCT_ID = "studious-pancake.mpr02.unified-durable-authority"

REQUIRED_OUTBOX_STATES: tuple[str, ...] = ("PENDING", "CLAIMED", "PUBLISHED", "DLQ")
REQUIRED_DOMAIN_CHECKS: tuple[str, ...] = (
    "attempts",
    "capital",
    "leases",
    "outbox",
    "terminal_hash",
)
REQUIRED_RECOVERY_PROBES: tuple[str, ...] = (
    "crash_after_attempt_insert",
    "crash_after_capital_reservation",
    "crash_after_lease_claim",
    "crash_after_outbox_claim",
    "crash_after_backup_replace",
    "crash_during_restore",
    "timeout_after_lease_expiry",
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MPR02GateState(StrEnum):
    """Final MPR-02 evidence state."""

    READY_FOR_DURABLE_RUNTIME_INTEGRATION = "ready-for-durable-runtime-integration"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class MPR02AuthorityEvidence:
    """Already-materialized evidence for the MPR-02 authority boundary."""

    release_id: str
    database_identity_hash: str
    schema_fingerprint: str
    one_transactional_authority: bool
    renewable_leases: bool
    claim_generation_monotonic: bool
    fence_checked_before_side_effect: bool
    owner_boot_epoch_bound: bool
    stale_owner_rejected: bool
    heartbeat_timeout_ms: int
    lease_ttl_ms: int
    worst_case_protected_section_ms: int
    outbox_states: Sequence[str]
    outbox_claim_has_owner: bool
    outbox_claim_has_deadline: bool
    expired_outbox_claim_reclaimed: bool
    outbox_publish_idempotent: bool
    outbox_dlq_after_bounded_attempts: bool
    recovery_scans_claimed_and_pending: bool
    wallet_scope_serializable: bool
    reservation_cas_revision: bool
    double_reservation_race_rejected: bool
    failed_attempt_releases_or_settles_fee: bool
    aggregate_reserved_lamports: int
    wallet_available_lamports: int
    minimum_required_available_lamports: int
    append_only_events: bool
    prev_hash_chain: bool
    event_sequence_unique: bool
    materialized_state_rebuilds_from_events: bool
    domain_integrity_checks: Sequence[str]
    replay_hash: str
    atomic_backup_bundle: bool
    backup_manifest_bound_to_db_wal: bool
    backup_files_and_directory_fsynced: bool
    staged_restore_handles_wal_shm: bool
    previous_generation_preserved_on_failure: bool
    post_restore_semantic_replay: bool
    structured_concurrency: bool
    cancellation_safe_terminal_state: bool
    readiness_unready_before_cancel: bool
    no_owned_tasks_after_shutdown: bool
    timeout_cause_preserved: bool
    max_shutdown_ms: int
    recovery_probes: Sequence[str]
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_allowed: bool = False

    def __post_init__(self) -> None:
        _identifier(self.release_id, "release_id")
        _sha256(self.database_identity_hash, "database_identity_hash")
        _sha256(self.schema_fingerprint, "schema_fingerprint")
        _sha256(self.replay_hash, "replay_hash")
        for value in self.outbox_states:
            _identifier(value, "outbox_state")
        for value in self.domain_integrity_checks:
            _identifier(value, "domain_integrity_check")
        for value in self.recovery_probes:
            _identifier(value, "recovery_probe")
        for name in _BOOL_FIELDS:
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be boolean")
        for name in _NON_NEGATIVE_INT_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class MPR02Violation:
    """One deterministic MPR-02 violation."""

    code: str
    subject: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class MPR02GateReport:
    """Deterministic MPR-02 gate report."""

    schema_version: str
    product_id: str
    state: MPR02GateState
    evidence_hash: str
    violations: tuple[MPR02Violation, ...]
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_allowed: bool = False

    @property
    def ready(self) -> bool:
        return self.state is MPR02GateState.READY_FOR_DURABLE_RUNTIME_INTEGRATION

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_id": self.product_id,
            "state": self.state.value,
            "ready": self.ready,
            "evidence_hash": self.evidence_hash,
            "violation_count": len(self.violations),
            "violations": [violation.to_dict() for violation in self.violations],
            "safety_boundary": {
                "live_execution_allowed": self.live_execution_allowed,
                "signer_allowed": self.signer_allowed,
                "sender_allowed": self.sender_allowed,
            },
        }


def evaluate_mpr02_authority(evidence: MPR02AuthorityEvidence) -> MPR02GateReport:
    """Return a fail-closed report for MPR-02 durable authority evidence."""

    violations: list[MPR02Violation] = []
    _require_true(evidence, "one_transactional_authority", violations)
    for name in _LEASE_BOOL_FIELDS:
        _require_true(evidence, name, violations, code="lease_incomplete")
    if evidence.lease_ttl_ms <= evidence.worst_case_protected_section_ms:
        violations.append(
            _violation(
                "lease_ttl_too_short",
                "lease_ttl_ms",
                "lease TTL must exceed the worst protected section",
            )
        )
    if evidence.heartbeat_timeout_ms >= evidence.lease_ttl_ms:
        violations.append(
            _violation(
                "heartbeat_not_inside_lease",
                "heartbeat_timeout_ms",
                "heartbeat timeout must be below lease TTL",
            )
        )

    for state in sorted(set(REQUIRED_OUTBOX_STATES).difference(evidence.outbox_states)):
        violations.append(_violation("missing_outbox_state", state))
    for name in _OUTBOX_BOOL_FIELDS:
        _require_true(evidence, name, violations, code="outbox_incomplete")

    for name in _CAPITAL_BOOL_FIELDS:
        _require_true(evidence, name, violations, code="capital_incomplete")
    available_after_reserve = (
        evidence.wallet_available_lamports - evidence.aggregate_reserved_lamports
    )
    if available_after_reserve < evidence.minimum_required_available_lamports:
        violations.append(
            _violation(
                "capital_over_reserved",
                "aggregate_reserved_lamports",
                "aggregate reservations leave wallet below required balance",
            )
        )

    for name in _EVENT_BOOL_FIELDS:
        _require_true(evidence, name, violations, code="event_history_incomplete")
    for item in sorted(set(REQUIRED_DOMAIN_CHECKS).difference(evidence.domain_integrity_checks)):
        violations.append(_violation("missing_domain_integrity_check", item))

    for name in _BACKUP_BOOL_FIELDS:
        _require_true(evidence, name, violations, code="backup_restore_incomplete")
    for name in _CANCELLATION_BOOL_FIELDS:
        _require_true(evidence, name, violations, code="cancellation_incomplete")
    if evidence.max_shutdown_ms > 60_000:
        violations.append(
            _violation(
                "shutdown_deadline_too_large",
                "max_shutdown_ms",
                "shutdown deadline must remain bounded",
            )
        )

    for probe in sorted(set(REQUIRED_RECOVERY_PROBES).difference(evidence.recovery_probes)):
        violations.append(_violation("missing_recovery_probe", probe))

    if evidence.live_execution_allowed:
        violations.append(_violation("live_enabled", "live_execution_allowed"))
    if evidence.signer_allowed:
        violations.append(_violation("signer_enabled", "signer_allowed"))
    if evidence.sender_allowed:
        violations.append(_violation("sender_enabled", "sender_allowed"))

    ordered = tuple(sorted(violations, key=lambda item: (item.code, item.subject)))
    return MPR02GateReport(
        schema_version=SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        state=(
            MPR02GateState.BLOCKED
            if ordered
            else MPR02GateState.READY_FOR_DURABLE_RUNTIME_INTEGRATION
        ),
        evidence_hash=_evidence_hash(evidence),
        violations=ordered,
    )


def _require_true(
    evidence: MPR02AuthorityEvidence,
    name: str,
    violations: list[MPR02Violation],
    *,
    code: str = "authority_incomplete",
) -> None:
    if not getattr(evidence, name):
        violations.append(_violation(code, name))


def _violation(
    code: str,
    subject: str,
    detail: str = "MPR-02 durable authority evidence is incomplete",
) -> MPR02Violation:
    return MPR02Violation(code=code, subject=subject, detail=detail)


def _evidence_hash(evidence: MPR02AuthorityEvidence) -> str:
    payload = {
        name: _jsonable(getattr(evidence, name))
        for name in sorted(evidence.__dataclass_fields__)
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a stable identifier")
    return value


def _sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return value


_LEASE_BOOL_FIELDS = (
    "renewable_leases",
    "claim_generation_monotonic",
    "fence_checked_before_side_effect",
    "owner_boot_epoch_bound",
    "stale_owner_rejected",
)
_OUTBOX_BOOL_FIELDS = (
    "outbox_claim_has_owner",
    "outbox_claim_has_deadline",
    "expired_outbox_claim_reclaimed",
    "outbox_publish_idempotent",
    "outbox_dlq_after_bounded_attempts",
    "recovery_scans_claimed_and_pending",
)
_CAPITAL_BOOL_FIELDS = (
    "wallet_scope_serializable",
    "reservation_cas_revision",
    "double_reservation_race_rejected",
    "failed_attempt_releases_or_settles_fee",
)
_EVENT_BOOL_FIELDS = (
    "append_only_events",
    "prev_hash_chain",
    "event_sequence_unique",
    "materialized_state_rebuilds_from_events",
)
_BACKUP_BOOL_FIELDS = (
    "atomic_backup_bundle",
    "backup_manifest_bound_to_db_wal",
    "backup_files_and_directory_fsynced",
    "staged_restore_handles_wal_shm",
    "previous_generation_preserved_on_failure",
    "post_restore_semantic_replay",
)
_CANCELLATION_BOOL_FIELDS = (
    "structured_concurrency",
    "cancellation_safe_terminal_state",
    "readiness_unready_before_cancel",
    "no_owned_tasks_after_shutdown",
    "timeout_cause_preserved",
)
_BOOL_FIELDS = (
    "one_transactional_authority",
    *_LEASE_BOOL_FIELDS,
    *_OUTBOX_BOOL_FIELDS,
    *_CAPITAL_BOOL_FIELDS,
    *_EVENT_BOOL_FIELDS,
    *_BACKUP_BOOL_FIELDS,
    *_CANCELLATION_BOOL_FIELDS,
    "live_execution_allowed",
    "signer_allowed",
    "sender_allowed",
)
_NON_NEGATIVE_INT_FIELDS = (
    "heartbeat_timeout_ms",
    "lease_ttl_ms",
    "worst_case_protected_section_ms",
    "aggregate_reserved_lamports",
    "wallet_available_lamports",
    "minimum_required_available_lamports",
    "max_shutdown_ms",
)
