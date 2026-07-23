"""PR-220 crash-consistency and recovery matrix gate.

This module is intentionally side-effect free. It does not open SQLite files,
spawn processes, read secrets, run migrations, dispatch outbox payloads, or
perform recovery.  It defines a deterministic evidence contract for the PR-220
Durable Control Plane / Trusted Time / Recovery Authority rollback boundary.

The gate is designed for follow-up implementation PRs: any missing or
self-attested crash, race, replay, migration, outbox, or backup evidence keeps
PR-220 blocked.  Live execution, signing, sender submission and private keys are
structurally unavailable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Sequence

SCHEMA_VERSION = "pr220.crash-consistency-recovery-matrix.v1"

REQUIRED_CRASH_POINTS: tuple[str, ...] = (
    "attempt_identity_allocated_before_event_append",
    "event_appended_before_materialized_projection",
    "reservation_created_before_capital_projection",
    "terminal_transition_before_outbox_enqueue",
    "outbox_claimed_before_publish_handoff",
    "outbox_delivered_before_ack_record",
    "backup_manifest_written_before_pointer_swap",
    "restore_pointer_swap_before_replay_verification",
)

REQUIRED_RACE_SCENARIOS: tuple[str, ...] = (
    "two_process_same_attempt_identity",
    "stale_owner_after_lease_expiry",
    "wallet_over_reservation_race",
    "duplicate_outbox_claim_race",
    "semantic_idempotency_conflict",
    "writer_death_during_blocking_callback",
)

REQUIRED_RECOVERY_SCENARIOS: tuple[str, ...] = (
    "kill9_between_intent_event_projection",
    "kill9_between_reservation_outbox_terminal",
    "reboot_time_jump_deadline_expiry",
    "stale_wal_restore",
    "torn_backup_manifest",
    "manual_event_payload_tamper",
    "manual_materialized_projection_tamper",
)

REQUIRED_OUTBOX_TRANSITIONS: tuple[str, ...] = (
    "queued_to_claimed",
    "claimed_to_delivered",
    "claimed_to_dead_letter",
    "claimed_to_queued_retry",
    "claim_renewed",
    "stale_claim_rejected",
    "operator_redrive_from_dead_letter",
)

REQUIRED_SAFETY_BOUNDARIES: tuple[str, ...] = (
    "transaction_signer_forbidden",
    "sender_forbidden",
    "live_execution_forbidden",
    "private_key_material_forbidden",
)

HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


class PR220GateState(str, Enum):
    """Qualification result for the PR-220 crash/recovery matrix."""

    QUALIFIED = "qualified"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class TransactionAtomicityEvidence:
    """Evidence that persistence uses one explicit atomic transaction boundary."""

    explicit_begin_immediate_or_serializable_writer: bool
    no_autocommit_multi_statement_paths: bool
    single_writer_authority: bool
    rowcount_checked_for_all_cas: bool
    committed_row_reread_before_external_effect: bool
    bool_float_nan_identity_rejected: bool
    canonical_length_prefixed_identity_hash: str
    statement_level_crash_points: Sequence[str]


@dataclass(frozen=True)
class StateReplayEvidence:
    """Evidence that materialized state is derived from an append-only event log."""

    append_only_event_log_authoritative: bool
    recovery_never_mutates_state_without_event: bool
    terminal_states_immutable: bool
    rejected_is_terminal_with_policy: bool
    payload_digest_recomputed_from_stored_payload: bool
    hash_chain_verified: bool
    replay_reconstructs_materialized_tables: bool
    manual_tamper_detected: bool
    replay_equality_report_hash: str


@dataclass(frozen=True)
class IdempotencyLeaseEvidence:
    """Evidence for semantic idempotency, lease fencing and race safety."""

    idempotency_namespace_bound: bool
    request_digest_bound_to_attempt_wallet_generation: bool
    conflicting_replay_returns_typed_conflict: bool
    process_boot_identity_persisted: bool
    non_stealable_lease: bool
    non_expired_fence_required_on_write: bool
    stale_owner_write_rejected: bool
    race_scenarios_passed: Sequence[str]


@dataclass(frozen=True)
class TrustedTimeEvidence:
    """Evidence that persisted deadlines survive reboot/time jumps correctly."""

    portable_wall_epoch_deadlines: bool
    no_persisted_monotonic_reuse_across_boot: bool
    monotonic_duration_only_inside_process: bool
    maximum_ttl_revalidated: bool
    future_issued_authorization_rejected: bool
    reboot_time_jump_scenarios_passed: Sequence[str]


@dataclass(frozen=True)
class OutboxRecoveryEvidence:
    """Evidence for durable outbox and UNKNOWN recovery ownership."""

    durable_outbox_fsm: bool
    renewable_claim_lease: bool
    claim_fencing_token_required: bool
    retry_history_persisted: bool
    poison_messages_dead_lettered: bool
    operator_redrive_audited: bool
    unknown_has_durable_reconciliation_owner: bool
    callback_timeout_not_cancellation_proof: bool
    transitions_proven: Sequence[str]


@dataclass(frozen=True)
class BackupRestoreEvidence:
    """Evidence for crash-safe generation backup and restore."""

    sqlite_backup_api_or_equivalent_online_safe_copy: bool
    wal_shm_handled: bool
    staged_generation_directory: bool
    manifest_published_atomically: bool
    directory_fsync_barrier: bool
    process_wide_quiescence_proven: bool
    semantic_replay_verified_before_pointer_swap: bool
    n_minus_one_generation_retained_for_rollback: bool
    restore_failure_boundaries_passed: Sequence[str]
    disaster_recovery_transcript_hash: str


@dataclass(frozen=True)
class AsyncDurabilityEvidence:
    """Evidence that persistence cannot block or falsely greenlight readiness."""

    sqlite_file_io_outside_event_loop: bool
    bounded_writer_queue: bool
    writer_failure_closes_readiness: bool
    event_loop_lag_budget_ms: int
    measured_max_event_loop_lag_ms: int
    blocking_callback_deadline_enforced: bool
    callback_result_bound_to_operation_id_and_payload_hash: bool


@dataclass(frozen=True)
class PR220CrashRecoveryEvidence:
    """Complete follow-up PR-220 crash-consistency evidence contract."""

    prior_pr220_gate_accepted: bool
    prior_pr220_gate_evidence_hash: str
    release_generation_hash: str
    transaction_atomicity: TransactionAtomicityEvidence
    state_replay: StateReplayEvidence
    idempotency_leases: IdempotencyLeaseEvidence
    trusted_time: TrustedTimeEvidence
    outbox_recovery: OutboxRecoveryEvidence
    backup_restore: BackupRestoreEvidence
    async_durability: AsyncDurabilityEvidence
    recovery_scenarios_passed: Sequence[str]
    safety_boundaries: Sequence[str]


@dataclass(frozen=True)
class PR220Violation:
    code: str
    message: str


@dataclass(frozen=True)
class PR220CrashRecoveryReport:
    """Deterministic gate report."""

    schema_version: str
    state: PR220GateState
    evidence_hash: str
    violations: tuple[PR220Violation, ...]
    durable_control_plane_qualified: bool
    transaction_signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool
    private_key_material_allowed: bool

    @property
    def blocked(self) -> bool:
        return self.state is PR220GateState.BLOCKED


def evaluate_pr220_crash_recovery_evidence(
    evidence: PR220CrashRecoveryEvidence,
) -> PR220CrashRecoveryReport:
    """Evaluate PR-220 crash-consistency/recovery evidence fail-closed."""

    violations: list[PR220Violation] = []

    _validate_dependency(evidence, violations)
    _validate_transaction_atomicity(evidence.transaction_atomicity, violations)
    _validate_state_replay(evidence.state_replay, violations)
    _validate_idempotency_leases(evidence.idempotency_leases, violations)
    _validate_trusted_time(evidence.trusted_time, violations)
    _validate_outbox_recovery(evidence.outbox_recovery, violations)
    _validate_backup_restore(evidence.backup_restore, violations)
    _validate_async_durability(evidence.async_durability, violations)
    _require_all(
        "RECOVERY_SCENARIO_MISSING",
        REQUIRED_RECOVERY_SCENARIOS,
        evidence.recovery_scenarios_passed,
        "recovery scenario",
        violations,
    )
    _require_all(
        "SAFETY_BOUNDARY_MISSING",
        REQUIRED_SAFETY_BOUNDARIES,
        evidence.safety_boundaries,
        "safety boundary",
        violations,
    )

    deduped = _dedupe(violations)
    state = PR220GateState.QUALIFIED if not deduped else PR220GateState.BLOCKED
    return PR220CrashRecoveryReport(
        schema_version=SCHEMA_VERSION,
        state=state,
        evidence_hash=_stable_hash(evidence),
        violations=tuple(deduped),
        durable_control_plane_qualified=not deduped,
        transaction_signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
        private_key_material_allowed=False,
    )


def _validate_dependency(
    evidence: PR220CrashRecoveryEvidence,
    violations: list[PR220Violation],
) -> None:
    if not evidence.prior_pr220_gate_accepted:
        _add(violations, "PR220_BASE_GATE_NOT_ACCEPTED", "prior PR-220 gate must be accepted")
    if not _is_sha256(evidence.prior_pr220_gate_evidence_hash):
        _add(violations, "PR220_BASE_GATE_HASH_INVALID", "prior PR-220 evidence hash must be sha256")
    if not _is_sha256(evidence.release_generation_hash):
        _add(violations, "RELEASE_GENERATION_HASH_INVALID", "release generation hash must be sha256")


def _validate_transaction_atomicity(
    evidence: TransactionAtomicityEvidence,
    violations: list[PR220Violation],
) -> None:
    required = (
        ("explicit_begin_immediate_or_serializable_writer", "TRANSACTION_BOUNDARY_MISSING"),
        ("no_autocommit_multi_statement_paths", "AUTOCOMMIT_PATH_PRESENT"),
        ("single_writer_authority", "SINGLE_WRITER_AUTHORITY_MISSING"),
        ("rowcount_checked_for_all_cas", "CAS_ROWCOUNT_NOT_PROVEN"),
        ("committed_row_reread_before_external_effect", "COMMITTED_REREAD_MISSING"),
        ("bool_float_nan_identity_rejected", "UNSAFE_IDENTITY_TYPES_ACCEPTED"),
    )
    _require_booleans(evidence, required, violations)
    if not _is_sha256(evidence.canonical_length_prefixed_identity_hash):
        _add(violations, "CANONICAL_IDENTITY_HASH_INVALID", "canonical identity evidence must be sha256")
    _require_all(
        "CRASH_POINT_MISSING",
        REQUIRED_CRASH_POINTS,
        evidence.statement_level_crash_points,
        "statement-level crash point",
        violations,
    )


def _validate_state_replay(
    evidence: StateReplayEvidence,
    violations: list[PR220Violation],
) -> None:
    required = (
        ("append_only_event_log_authoritative", "EVENT_LOG_NOT_AUTHORITATIVE"),
        ("recovery_never_mutates_state_without_event", "RECOVERY_MUTATES_WITHOUT_EVENT"),
        ("terminal_states_immutable", "TERMINAL_STATE_MUTABLE"),
        ("rejected_is_terminal_with_policy", "REJECTED_DEAD_END"),
        ("payload_digest_recomputed_from_stored_payload", "PAYLOAD_DIGEST_NOT_RECOMPUTED"),
        ("hash_chain_verified", "HASH_CHAIN_NOT_VERIFIED"),
        ("replay_reconstructs_materialized_tables", "REPLAY_EQUALITY_NOT_PROVEN"),
        ("manual_tamper_detected", "MANUAL_TAMPER_NOT_DETECTED"),
    )
    _require_booleans(evidence, required, violations)
    if not _is_sha256(evidence.replay_equality_report_hash):
        _add(violations, "REPLAY_REPORT_HASH_INVALID", "replay equality report must be sha256")


def _validate_idempotency_leases(
    evidence: IdempotencyLeaseEvidence,
    violations: list[PR220Violation],
) -> None:
    required = (
        ("idempotency_namespace_bound", "IDEMPOTENCY_NAMESPACE_MISSING"),
        ("request_digest_bound_to_attempt_wallet_generation", "REQUEST_DIGEST_BINDING_MISSING"),
        ("conflicting_replay_returns_typed_conflict", "IDEMPOTENCY_CONFLICT_MASKED"),
        ("process_boot_identity_persisted", "BOOT_IDENTITY_NOT_PERSISTED"),
        ("non_stealable_lease", "LEASE_STEALABLE"),
        ("non_expired_fence_required_on_write", "FENCE_NOT_REQUIRED_ON_WRITE"),
        ("stale_owner_write_rejected", "STALE_OWNER_WRITE_ACCEPTED"),
    )
    _require_booleans(evidence, required, violations)
    _require_all(
        "RACE_SCENARIO_MISSING",
        REQUIRED_RACE_SCENARIOS,
        evidence.race_scenarios_passed,
        "race scenario",
        violations,
    )


def _validate_trusted_time(
    evidence: TrustedTimeEvidence,
    violations: list[PR220Violation],
) -> None:
    required = (
        ("portable_wall_epoch_deadlines", "PORTABLE_DEADLINE_MISSING"),
        ("no_persisted_monotonic_reuse_across_boot", "PERSISTED_MONOTONIC_REUSED"),
        ("monotonic_duration_only_inside_process", "MONOTONIC_SCOPE_NOT_PROCESS_LOCAL"),
        ("maximum_ttl_revalidated", "MAX_TTL_NOT_REVALIDATED"),
        ("future_issued_authorization_rejected", "FUTURE_AUTHORIZATION_ACCEPTED"),
    )
    _require_booleans(evidence, required, violations)
    if "reboot_time_jump_deadline_expiry" not in set(evidence.reboot_time_jump_scenarios_passed):
        _add(violations, "REBOOT_TIME_JUMP_SCENARIO_MISSING", "reboot/time-jump deadline scenario is required")


def _validate_outbox_recovery(
    evidence: OutboxRecoveryEvidence,
    violations: list[PR220Violation],
) -> None:
    required = (
        ("durable_outbox_fsm", "OUTBOX_FSM_MISSING"),
        ("renewable_claim_lease", "OUTBOX_LEASE_NOT_RENEWABLE"),
        ("claim_fencing_token_required", "OUTBOX_FENCE_MISSING"),
        ("retry_history_persisted", "OUTBOX_RETRY_HISTORY_MISSING"),
        ("poison_messages_dead_lettered", "POISON_NOT_DEAD_LETTERED"),
        ("operator_redrive_audited", "OPERATOR_REDRIVE_NOT_AUDITED"),
        ("unknown_has_durable_reconciliation_owner", "UNKNOWN_RECONCILIATION_OWNER_MISSING"),
        ("callback_timeout_not_cancellation_proof", "TIMEOUT_FALSE_CANCELLATION_PROOF"),
    )
    _require_booleans(evidence, required, violations)
    _require_all(
        "OUTBOX_TRANSITION_MISSING",
        REQUIRED_OUTBOX_TRANSITIONS,
        evidence.transitions_proven,
        "outbox transition",
        violations,
    )


def _validate_backup_restore(
    evidence: BackupRestoreEvidence,
    violations: list[PR220Violation],
) -> None:
    required = (
        ("sqlite_backup_api_or_equivalent_online_safe_copy", "ONLINE_SAFE_BACKUP_MISSING"),
        ("wal_shm_handled", "WAL_SHM_NOT_HANDLED"),
        ("staged_generation_directory", "STAGED_GENERATION_MISSING"),
        ("manifest_published_atomically", "MANIFEST_NOT_ATOMIC"),
        ("directory_fsync_barrier", "DIRECTORY_FSYNC_MISSING"),
        ("process_wide_quiescence_proven", "QUIESCENCE_NOT_PROVEN"),
        ("semantic_replay_verified_before_pointer_swap", "RESTORE_POINTER_SWAP_BEFORE_REPLAY"),
        ("n_minus_one_generation_retained_for_rollback", "ROLLBACK_GENERATION_MISSING"),
    )
    _require_booleans(evidence, required, violations)
    required_restore = {
        "stale_wal_restore",
        "torn_backup_manifest",
        "restore_pointer_swap_before_replay_verification",
    }
    missing = required_restore.difference(evidence.restore_failure_boundaries_passed)
    for scenario in sorted(missing):
        _add(violations, "RESTORE_FAILURE_BOUNDARY_MISSING", f"restore failure boundary missing: {scenario}")
    if not _is_sha256(evidence.disaster_recovery_transcript_hash):
        _add(violations, "DR_TRANSCRIPT_HASH_INVALID", "DR transcript must be sha256")


def _validate_async_durability(
    evidence: AsyncDurabilityEvidence,
    violations: list[PR220Violation],
) -> None:
    required = (
        ("sqlite_file_io_outside_event_loop", "SQLITE_BLOCKS_EVENT_LOOP"),
        ("bounded_writer_queue", "WRITER_QUEUE_UNBOUNDED"),
        ("writer_failure_closes_readiness", "WRITER_FAILURE_DOES_NOT_CLOSE_READINESS"),
        ("blocking_callback_deadline_enforced", "CALLBACK_DEADLINE_NOT_ENFORCED"),
        ("callback_result_bound_to_operation_id_and_payload_hash", "CALLBACK_RESULT_NOT_PAYLOAD_BOUND"),
    )
    _require_booleans(evidence, required, violations)
    if isinstance(evidence.event_loop_lag_budget_ms, bool) or evidence.event_loop_lag_budget_ms <= 0:
        _add(violations, "EVENT_LOOP_LAG_BUDGET_INVALID", "event loop lag budget must be positive")
        return
    if isinstance(evidence.measured_max_event_loop_lag_ms, bool) or evidence.measured_max_event_loop_lag_ms < 0:
        _add(violations, "EVENT_LOOP_LAG_MEASUREMENT_INVALID", "measured lag must be non-negative")
        return
    if evidence.measured_max_event_loop_lag_ms > evidence.event_loop_lag_budget_ms:
        _add(
            violations,
            "EVENT_LOOP_LAG_BUDGET_EXCEEDED",
            "measured event loop lag exceeds the configured budget",
        )


def _require_booleans(
    evidence: object,
    fields: Iterable[tuple[str, str]],
    violations: list[PR220Violation],
) -> None:
    for field, code in fields:
        if getattr(evidence, field) is not True:
            _add(violations, code, f"{field} must be true")


def _require_all(
    code: str,
    required: Sequence[str],
    actual: Sequence[str],
    noun: str,
    violations: list[PR220Violation],
) -> None:
    actual_set = set(actual)
    for item in required:
        if item not in actual_set:
            _add(violations, code, f"missing {noun}: {item}")


def _add(violations: list[PR220Violation], code: str, message: str) -> None:
    violations.append(PR220Violation(code=code, message=message))


def _dedupe(violations: Sequence[PR220Violation]) -> list[PR220Violation]:
    seen: set[tuple[str, str]] = set()
    deduped: list[PR220Violation] = []
    for violation in violations:
        key = (violation.code, violation.message)
        if key not in seen:
            seen.add(key)
            deduped.append(violation)
    return deduped


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and HEX_64_RE.fullmatch(value) is not None


def _stable_hash(value: object) -> str:
    payload = json.dumps(_to_jsonable(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _to_jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    return value
