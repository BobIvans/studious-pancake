"""PR-220 durable control-plane, trusted-time and recovery authority gate.

Side-effect-free evidence contract for the PR-220 rollback boundary: one
transactional source of truth for lifecycle, idempotency, reservations, leases,
events, projections, outbox/recovery and backup/restore.

This gate never opens databases, reads secrets, signs, submits, starts workers,
runs network I/O or enables live trading.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import math
import re
from typing import Iterable, Mapping, Sequence

SCHEMA_VERSION = "pr220.durable-control-plane-recovery-authority.v1"
REQUIRED_FINDINGS: tuple[str, ...] = (
    "F-019","F-020","F-021","F-023","F-024","F-026","F-029","F-030","F-035",
    "F-046","F-047","F-051","F-052","F-061","F-063","F-064","F-074","F-075",
    "F-076","F-092","F-093","F-094","F-095","F-096","F-097","F-098","F-099",
    "F-100","F-101","F-102","F-103","F-104","F-105","F-106","F-107","F-108",
    "F-109","F-110","F-111","F-112","F-113","F-163","F-164","F-166","F-167",
    "F-168","F-171","F-173","F-174","F-191","F-192","F-193","F-194","F-209",
    "F-210","F-211","F-212","F-213","F-214","F-215","F-216","F-275","F-283",
    "F-289","F-290","F-291","F-292","F-293","F-294","F-295","F-360","F-364",
    "F-407","F-408",
)
REQUIRED_FAULT_CASES: tuple[str, ...] = (
    "kill_after_intent_before_event",
    "kill_after_event_before_projection",
    "kill_after_reservation_before_outbox",
    "kill_after_outbox_before_ack",
    "writer_thread_death",
    "reboot_time_jump_forward",
    "reboot_time_jump_backward",
    "wal_backup_during_writer",
    "torn_manifest_restore",
    "semantic_idempotency_conflict",
    "stale_fencing_token_write",
    "manual_db_tampering",
)
HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


class PR220GateState(str, Enum):
    DURABLE_CONTROL_PLANE_QUALIFIED = "durable_control_plane_qualified"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class PR220Evidence:
    release_artifact_hash: str
    control_plane_manifest_hash: str
    findings_covered: tuple[str, ...]
    component_hashes: Mapping[str, str]
    persistence_topology: Mapping[str, bool]
    canonical_state_machine: Mapping[str, bool]
    semantic_idempotency: Mapping[str, bool]
    fencing_and_leases: Mapping[str, bool]
    trusted_time: Mapping[str, bool]
    queues_reservations_outbox: Mapping[str, bool]
    async_durability: Mapping[str, bool]
    projection_archive_backup: Mapping[str, bool]
    fault_cases_covered: tuple[str, ...]
    accelerated_soak_hours: int
    event_loop_lag_p99_ms: float
    event_loop_lag_budget_ms: float
    replay_mismatch_count: int
    duplicate_terminal_count: int
    double_side_effect_count: int
    lost_reservation_count: int
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False
    private_key_material_present: bool = False


@dataclass(frozen=True)
class PR220Violation:
    code: str
    message: str


@dataclass(frozen=True)
class PR220Report:
    schema_version: str
    state: PR220GateState
    blockers: tuple[PR220Violation, ...]
    evidence_hash: str
    covered_findings: tuple[str, ...]
    transaction_signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool
    private_key_material_allowed: bool


REQUIRED_COMPONENT_HASHES: tuple[str, ...] = (
    "system_of_record_identity",
    "schema_manifest",
    "migration_chain",
    "transition_function",
    "idempotency_registry",
    "lease_protocol",
    "process_boot_identity",
    "clock_authority",
    "portable_deadline_schema",
    "queue_schema",
    "outbox_schema",
    "writer_actor",
    "projection_schema",
    "backup_manifest",
)

REQUIRED_GROUP_PROOFS: Mapping[str, tuple[str, ...]] = {
    "persistence_topology": (
        "one_authoritative_database",
        "one_transaction_api_for_lifecycle",
        "attempts_opportunities_reservations_leases_outbox_in_same_authority",
        "jsonl_or_memory_terminal_truth_retired",
        "alternate_lifecycle_stores_quarantined",
        "sqlite_pragmas_uniform_and_durable",
        "no_autocommit_multi_statement_transitions",
        "writer_owner_identity_not_default",
    ),
    "canonical_state_machine": (
        "every_transition_appends_event",
        "recovery_is_event_sourced",
        "terminal_states_immutable",
        "terminal_transition_rowcount_checked",
        "recovery_cannot_overwrite_terminal_truth",
        "state_replay_matches_materialized_hash",
        "manual_tamper_detected_by_event_chain_hash",
        "readiness_derived_from_replayed_state_not_boolean_claim",
    ),
    "semantic_idempotency": (
        "operation_namespaces_bound",
        "attempt_wallet_generation_bound",
        "canonical_request_digest_persisted",
        "replay_same_request_returns_same_outcome",
        "conflicting_payload_returns_typed_conflict",
        "conflict_never_terminalizes_success",
        "callback_semantics_bound_to_operation_id",
    ),
    "fencing_and_leases": (
        "non_stealable_leases",
        "process_generation_strictly_increases",
        "fencing_token_required_on_every_write",
        "stale_owner_write_rejected",
        "claim_ack_nack_are_cas_rowcount_checked",
        "expired_reserved_operation_has_reconciliation_owner",
        "duplicate_claim_leaves_terminal_audit_evidence",
    ),
    "trusted_time": (
        "persistent_deadlines_use_utc_upper_bound",
        "persisted_monotonic_deadlines_forbidden",
        "monotonic_durations_scoped_to_process_generation",
        "not_before_expiry_freshness_share_one_clock_authority",
        "maximum_ttl_enforced_by_verifier",
        "future_issued_authorization_rejected",
        "reboot_time_jump_does_not_extend_deadlines",
        "suspend_resume_requalification_required",
    ),
    "queues_reservations_outbox": (
        "queue_dedupe_persistent_and_bounded",
        "expiry_terminalizes_or_releases_lifecycle",
        "expired_opportunity_can_be_readmitted_safely",
        "reservations_recovered_without_double_reserve",
        "callback_timeout_not_treated_as_side_effect_cancellation",
        "outbox_claim_renew_ack_nack_retry_dlq_implemented",
        "unknown_has_durable_reconciliation_owner",
        "jito_uncled_and_status_gap_recovery_owner_exists",
        "secret_lifecycle_not_development_friendly_by_default",
    ),
    "async_durability": (
        "sqlite_and_file_io_off_event_loop",
        "writer_queue_has_backpressure_bound",
        "writer_failure_closes_readiness",
        "blocking_callback_has_deadline_and_worker_isolation",
        "resource_close_failure_is_not_reported_closed",
    ),
    "projection_archive_backup": (
        "projections_append_only_versioned",
        "projection_rebuild_atomic_and_totally_ordered",
        "changed_evidence_same_outcome_is_conflict",
        "archive_remote_ack_append_only",
        "archive_published_bytes_rehashed",
        "backup_uses_sqlite_backup_api_and_wal_discipline",
        "backup_manifest_published_atomically_with_fsync",
        "restore_requires_process_quiescence",
        "restore_has_rollback_and_directory_fsync",
        "previous_generation_available_for_rollback",
    ),
}


def evaluate_pr220_evidence(evidence: PR220Evidence) -> PR220Report:
    blockers: list[PR220Violation] = []
    _validate_hash("release_artifact_hash", evidence.release_artifact_hash, blockers)
    _validate_hash(
        "control_plane_manifest_hash", evidence.control_plane_manifest_hash, blockers
    )
    for key in REQUIRED_COMPONENT_HASHES:
        _validate_hash(f"component_hashes.{key}", evidence.component_hashes.get(key), blockers)

    _validate_findings(evidence.findings_covered, blockers)
    for group_name, required_keys in REQUIRED_GROUP_PROOFS.items():
        group = getattr(evidence, group_name)
        for key in required_keys:
            if group.get(key) is not True:
                _add(
                    blockers,
                    f"PR220_{group_name.upper()}_INCOMPLETE",
                    f"{group_name}.{key} is not proven",
                )

    _validate_fault_matrix(evidence, blockers)
    _validate_safety_boundary(evidence, blockers)

    unique = tuple(_dedupe(blockers))
    return PR220Report(
        schema_version=SCHEMA_VERSION,
        state=(
            PR220GateState.BLOCKED
            if unique
            else PR220GateState.DURABLE_CONTROL_PLANE_QUALIFIED
        ),
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        covered_findings=tuple(sorted(set(evidence.findings_covered))),
        transaction_signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
        private_key_material_allowed=False,
    )


def _validate_findings(findings: Sequence[str], blockers: list[PR220Violation]) -> None:
    missing = [finding for finding in REQUIRED_FINDINGS if finding not in findings]
    if missing:
        _add(
            blockers,
            "PR220_FINDINGS_INCOMPLETE",
            f"missing required findings: {', '.join(missing)}",
        )


def _validate_fault_matrix(
    evidence: PR220Evidence, blockers: list[PR220Violation]
) -> None:
    missing = [case for case in REQUIRED_FAULT_CASES if case not in evidence.fault_cases_covered]
    if missing:
        _add(
            blockers,
            "PR220_FAULT_MATRIX_INCOMPLETE",
            f"missing fault cases: {', '.join(missing)}",
        )
    if evidence.accelerated_soak_hours < 24:
        _add(blockers, "PR220_SOAK_TOO_SHORT", "soak must cover at least 24 hours")
    counters = (
        ("replay_mismatch_count", evidence.replay_mismatch_count),
        ("duplicate_terminal_count", evidence.duplicate_terminal_count),
        ("double_side_effect_count", evidence.double_side_effect_count),
        ("lost_reservation_count", evidence.lost_reservation_count),
    )
    for name, value in counters:
        if value != 0:
            _add(blockers, "PR220_FAULT_COUNTER_NONZERO", f"{name} must be zero")
    if not _finite_nonnegative(evidence.event_loop_lag_p99_ms):
        _add(blockers, "PR220_BAD_EVENT_LOOP_LAG", "event-loop lag must be finite")
    if not _finite_positive(evidence.event_loop_lag_budget_ms):
        _add(blockers, "PR220_BAD_EVENT_LOOP_BUDGET", "event-loop budget must be positive")
    if (
        _finite_nonnegative(evidence.event_loop_lag_p99_ms)
        and _finite_positive(evidence.event_loop_lag_budget_ms)
        and evidence.event_loop_lag_p99_ms > evidence.event_loop_lag_budget_ms
    ):
        _add(
            blockers,
            "PR220_EVENT_LOOP_LAG_BUDGET_EXCEEDED",
            "p99 event-loop lag exceeds the control-plane budget",
        )


def _validate_safety_boundary(
    evidence: PR220Evidence, blockers: list[PR220Violation]
) -> None:
    if evidence.live_execution_requested:
        _add(blockers, "PR220_LIVE_REQUESTED", "PR-220 cannot enable live execution")
    if evidence.signer_requested:
        _add(blockers, "PR220_SIGNER_REQUESTED", "PR-220 cannot enable signer access")
    if evidence.sender_requested:
        _add(blockers, "PR220_SENDER_REQUESTED", "PR-220 cannot enable sender IO")
    if evidence.private_key_material_present:
        _add(blockers, "PR220_PRIVATE_KEY_PRESENT", "private key material is forbidden")


def _validate_hash(name: str, value: object, blockers: list[PR220Violation]) -> None:
    if not isinstance(value, str) or not HEX_64_RE.fullmatch(value):
        _add(blockers, "PR220_BAD_HASH", f"{name} must be a lowercase sha256")


def _add(blockers: list[PR220Violation], code: str, message: str) -> None:
    blockers.append(PR220Violation(code=code, message=message))


def _finite_nonnegative(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _finite_positive(value: object) -> bool:
    return _finite_nonnegative(value) and value > 0


def _dedupe(blockers: Iterable[PR220Violation]) -> Iterable[PR220Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key in seen:
            continue
        seen.add(key)
        yield blocker


def _stable_hash(value: object) -> str:
    payload = json.dumps(asdict(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
