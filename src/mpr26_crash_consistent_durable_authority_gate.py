"""MPR-26 crash-consistent durable authority evidence gate.

This module is intentionally offline and side-effect free. It defines the
acceptance contract for the V11 MPR-26 durable authority cutover: one economic
authority for attempts, capital, leases, events, outbox, projections and
recovery. It never opens a database, reads secrets, signs, submits, calls
providers or enables live execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence

SCHEMA_VERSION = "mpr26.crash-consistent-durable-authority-gate.v1"
PRODUCT_ID = "studious-pancake.mpr26.crash-consistent-durable-authority"

REQUIRED_FINDINGS: tuple[str, ...] = tuple(f"F-{number}" for number in range(374, 390))
REQUIRED_FAULT_BOUNDARIES: tuple[str, ...] = (
    "reserve_attempt",
    "commit_event",
    "materialize_projection",
    "outbox_enqueue",
    "outbox_claim",
    "terminal_commit",
    "backup_publish",
    "restore_cutover",
)
REQUIRED_RACE_PROBES: tuple[str, ...] = (
    "duplicate_opportunity",
    "same_wallet_capital",
    "same_outbox_claim",
    "stale_fence_write",
)
REQUIRED_RESTORE_PROBES: tuple[str, ...] = (
    "stale_wal",
    "stale_shm",
    "partial_backup",
    "corrupt_manifest",
    "failed_restore",
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+=-]{0,159}$")


class MPR26State(str, Enum):
    READY_FOR_DURABLE_CUTOVER_REVIEW = "ready-for-durable-cutover-review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class MPR26Violation:
    code: str
    subject: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class AuthorityTopologyEvidence:
    authority_generation: str
    schema_manifest_sha256: str
    transaction_api_sha256: str
    one_durable_authority_api: bool
    attempt_capital_lease_event_outbox_recovery_in_one_authority: bool
    independent_terminal_stores_disabled: bool
    projection_truth_derived_from_events_only: bool
    readiness_reads_replayed_authority_state: bool


@dataclass(frozen=True, slots=True)
class TransactionProtocolEvidence:
    explicit_begin_immediate_or_serial_writer: bool
    no_autocommit_multi_statement_paths: bool
    no_connection_context_manager_transaction_assumption: bool
    every_conditional_update_checks_rowcount: bool
    rereads_committed_row_before_external_effect: bool
    fault_injection_after_each_sql_statement: bool


@dataclass(frozen=True, slots=True)
class IdentityDomainEvidence:
    canonical_identity_codec_sha256: str
    length_prefixed_attempt_cycle_outbox_keys: bool
    rejects_nul_delimiter_collisions: bool
    rejects_bool_as_int: bool
    rejects_nan_and_float_money: bool
    rejects_malformed_pubkeys: bool
    collision_corpus_sha256: str


@dataclass(frozen=True, slots=True)
class EventLogEvidence:
    event_schema_sha256: str
    append_only_event_log_authoritative: bool
    payload_digest_recomputed_from_stored_payload: bool
    hash_chain_or_signed_checkpoints: bool
    materialized_rows_replay_equal_events: bool
    child_table_tamper_detected_before_readiness: bool
    projection_tamper_detected_before_readiness: bool
    startup_blocks_on_integrity_failure: bool


@dataclass(frozen=True, slots=True)
class OutboxRecoveryEvidence:
    outbox_fsm_sha256: str
    has_queued_claimed_delivered_dead_letter_states: bool
    renewable_claim_leases: bool
    fencing_token_required_on_every_claim_write: bool
    stale_owner_after_expiry_rejected: bool
    retry_history_backoff_and_poison_quarantine: bool
    unknown_has_durable_reconciliation_owner: bool
    no_orphaned_outbox_claim_after_restart: bool


@dataclass(frozen=True, slots=True)
class StorageRecoveryEvidence:
    storage_policy_sha256: str
    parent_directories_0700: bool
    database_files_0600: bool
    no_symlink_traversal: bool
    ownership_and_inode_checked: bool
    wal_and_shm_included_in_backup_protocol: bool
    generation_backup_and_atomic_restore_pointer: bool
    previous_generation_preserved_on_restore_failure: bool
    restore_rehearses_required_failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CrashRaceEvidence:
    statement_crash_matrix_sha256: str
    two_process_race_report_sha256: str
    fault_boundaries_tested: tuple[str, ...]
    race_probes_tested: tuple[str, ...]
    kill_at_every_write_boundary_proves_exactly_one_terminal: bool
    duplicate_opportunities_do_not_overreserve_capital: bool
    no_split_attempt_projection_or_outbox_truth: bool
    restart_releases_or_reconciles_leases_and_reservations: bool


@dataclass(frozen=True, slots=True)
class MPR26Evidence:
    release_id: str
    finding_coverage: tuple[str, ...]
    topology: AuthorityTopologyEvidence
    transaction_protocol: TransactionProtocolEvidence
    identity_domain: IdentityDomainEvidence
    event_log: EventLogEvidence
    outbox_recovery: OutboxRecoveryEvidence
    storage_recovery: StorageRecoveryEvidence
    crash_race: CrashRaceEvidence
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False
    provider_network_requested: bool = False


@dataclass(frozen=True, slots=True)
class MPR26Report:
    schema_version: str
    product_id: str
    state: MPR26State
    evidence_hash: str
    violations: tuple[MPR26Violation, ...]
    required_findings: tuple[str, ...] = REQUIRED_FINDINGS
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_allowed: bool = False
    provider_network_allowed: bool = False

    @property
    def ready(self) -> bool:
        return self.state is MPR26State.READY_FOR_DURABLE_CUTOVER_REVIEW

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_id": self.product_id,
            "state": self.state.value,
            "ready": self.ready,
            "evidence_hash": self.evidence_hash,
            "violation_count": len(self.violations),
            "violations": [violation.to_dict() for violation in self.violations],
            "required_findings": list(self.required_findings),
            "safety_boundary": {
                "live_execution_allowed": self.live_execution_allowed,
                "signer_allowed": self.signer_allowed,
                "sender_allowed": self.sender_allowed,
                "provider_network_allowed": self.provider_network_allowed,
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"


def evaluate_mpr26_evidence(evidence: MPR26Evidence) -> MPR26Report:
    """Return a deterministic fail-closed MPR-26 durable-authority report."""

    violations: list[MPR26Violation] = []
    _validate_safe_id(evidence.release_id, "release_id", violations)
    _validate_findings(evidence.finding_coverage, violations)
    _validate_topology(evidence.topology, violations)
    _validate_transaction_protocol(evidence.transaction_protocol, violations)
    _validate_identity_domain(evidence.identity_domain, violations)
    _validate_event_log(evidence.event_log, violations)
    _validate_outbox_recovery(evidence.outbox_recovery, violations)
    _validate_storage_recovery(evidence.storage_recovery, violations)
    _validate_crash_race(evidence.crash_race, violations)
    _validate_safety_boundary(evidence, violations)

    ordered = tuple(sorted(_dedupe(violations), key=lambda item: (item.code, item.subject, item.detail)))
    state = MPR26State.BLOCKED if ordered else MPR26State.READY_FOR_DURABLE_CUTOVER_REVIEW
    return MPR26Report(
        schema_version=SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        state=state,
        evidence_hash=_stable_hash(evidence),
        violations=ordered,
    )


def blockers_by_code(report: MPR26Report) -> Mapping[str, tuple[MPR26Violation, ...]]:
    grouped: dict[str, list[MPR26Violation]] = {}
    for violation in report.violations:
        grouped.setdefault(violation.code, []).append(violation)
    return {code: tuple(items) for code, items in grouped.items()}


def _validate_findings(
    finding_coverage: Sequence[str],
    violations: list[MPR26Violation],
) -> None:
    normalized = tuple(finding_coverage)
    if len(normalized) != len(set(normalized)):
        _add(violations, "MPR26_DUPLICATE_FINDING", "findings", "coverage is duplicated")
    missing = [finding for finding in REQUIRED_FINDINGS if finding not in normalized]
    extra = [finding for finding in normalized if finding not in REQUIRED_FINDINGS]
    if missing:
        _add(
            violations,
            "MPR26_MISSING_FINDING",
            "findings",
            f"missing required V11 durable findings: {missing}",
        )
    if extra:
        _add(violations, "MPR26_UNKNOWN_FINDING", "findings", f"unknown findings: {extra}")


def _validate_topology(
    topology: AuthorityTopologyEvidence,
    violations: list[MPR26Violation],
) -> None:
    _validate_safe_id(topology.authority_generation, "authority_generation", violations)
    _validate_hashes(
        violations,
        "MPR26_BAD_TOPOLOGY_HASH",
        schema_manifest_sha256=topology.schema_manifest_sha256,
        transaction_api_sha256=topology.transaction_api_sha256,
    )
    _require_all(
        violations,
        "MPR26_TOPOLOGY_INCOMPLETE",
        "topology",
        one_durable_authority_api=topology.one_durable_authority_api,
        attempt_capital_lease_event_outbox_recovery_in_one_authority=(
            topology.attempt_capital_lease_event_outbox_recovery_in_one_authority
        ),
        independent_terminal_stores_disabled=topology.independent_terminal_stores_disabled,
        projection_truth_derived_from_events_only=topology.projection_truth_derived_from_events_only,
        readiness_reads_replayed_authority_state=topology.readiness_reads_replayed_authority_state,
    )


def _validate_transaction_protocol(
    protocol: TransactionProtocolEvidence,
    violations: list[MPR26Violation],
) -> None:
    _require_all(
        violations,
        "MPR26_TRANSACTION_PROTOCOL_INCOMPLETE",
        "transactions",
        explicit_begin_immediate_or_serial_writer=protocol.explicit_begin_immediate_or_serial_writer,
        no_autocommit_multi_statement_paths=protocol.no_autocommit_multi_statement_paths,
        no_connection_context_manager_transaction_assumption=(
            protocol.no_connection_context_manager_transaction_assumption
        ),
        every_conditional_update_checks_rowcount=protocol.every_conditional_update_checks_rowcount,
        rereads_committed_row_before_external_effect=protocol.rereads_committed_row_before_external_effect,
        fault_injection_after_each_sql_statement=protocol.fault_injection_after_each_sql_statement,
    )


def _validate_identity_domain(
    identity: IdentityDomainEvidence,
    violations: list[MPR26Violation],
) -> None:
    _validate_hashes(
        violations,
        "MPR26_BAD_IDENTITY_HASH",
        canonical_identity_codec_sha256=identity.canonical_identity_codec_sha256,
        collision_corpus_sha256=identity.collision_corpus_sha256,
    )
    _require_all(
        violations,
        "MPR26_IDENTITY_DOMAIN_INCOMPLETE",
        "identity",
        length_prefixed_attempt_cycle_outbox_keys=identity.length_prefixed_attempt_cycle_outbox_keys,
        rejects_nul_delimiter_collisions=identity.rejects_nul_delimiter_collisions,
        rejects_bool_as_int=identity.rejects_bool_as_int,
        rejects_nan_and_float_money=identity.rejects_nan_and_float_money,
        rejects_malformed_pubkeys=identity.rejects_malformed_pubkeys,
    )


def _validate_event_log(
    event_log: EventLogEvidence,
    violations: list[MPR26Violation],
) -> None:
    _validate_hashes(violations, "MPR26_BAD_EVENT_LOG_HASH", event_schema_sha256=event_log.event_schema_sha256)
    _require_all(
        violations,
        "MPR26_EVENT_LOG_INCOMPLETE",
        "event_log",
        append_only_event_log_authoritative=event_log.append_only_event_log_authoritative,
        payload_digest_recomputed_from_stored_payload=event_log.payload_digest_recomputed_from_stored_payload,
        hash_chain_or_signed_checkpoints=event_log.hash_chain_or_signed_checkpoints,
        materialized_rows_replay_equal_events=event_log.materialized_rows_replay_equal_events,
        child_table_tamper_detected_before_readiness=event_log.child_table_tamper_detected_before_readiness,
        projection_tamper_detected_before_readiness=event_log.projection_tamper_detected_before_readiness,
        startup_blocks_on_integrity_failure=event_log.startup_blocks_on_integrity_failure,
    )


def _validate_outbox_recovery(
    outbox: OutboxRecoveryEvidence,
    violations: list[MPR26Violation],
) -> None:
    _validate_hashes(violations, "MPR26_BAD_OUTBOX_HASH", outbox_fsm_sha256=outbox.outbox_fsm_sha256)
    _require_all(
        violations,
        "MPR26_OUTBOX_RECOVERY_INCOMPLETE",
        "outbox",
        has_queued_claimed_delivered_dead_letter_states=outbox.has_queued_claimed_delivered_dead_letter_states,
        renewable_claim_leases=outbox.renewable_claim_leases,
        fencing_token_required_on_every_claim_write=outbox.fencing_token_required_on_every_claim_write,
        stale_owner_after_expiry_rejected=outbox.stale_owner_after_expiry_rejected,
        retry_history_backoff_and_poison_quarantine=outbox.retry_history_backoff_and_poison_quarantine,
        unknown_has_durable_reconciliation_owner=outbox.unknown_has_durable_reconciliation_owner,
        no_orphaned_outbox_claim_after_restart=outbox.no_orphaned_outbox_claim_after_restart,
    )


def _validate_storage_recovery(
    storage: StorageRecoveryEvidence,
    violations: list[MPR26Violation],
) -> None:
    _validate_hashes(violations, "MPR26_BAD_STORAGE_HASH", storage_policy_sha256=storage.storage_policy_sha256)
    _require_all(
        violations,
        "MPR26_STORAGE_RECOVERY_INCOMPLETE",
        "storage",
        parent_directories_0700=storage.parent_directories_0700,
        database_files_0600=storage.database_files_0600,
        no_symlink_traversal=storage.no_symlink_traversal,
        ownership_and_inode_checked=storage.ownership_and_inode_checked,
        wal_and_shm_included_in_backup_protocol=storage.wal_and_shm_included_in_backup_protocol,
        generation_backup_and_atomic_restore_pointer=storage.generation_backup_and_atomic_restore_pointer,
        previous_generation_preserved_on_restore_failure=storage.previous_generation_preserved_on_restore_failure,
    )
    _require_subset(
        storage.restore_rehearses_required_failures,
        REQUIRED_RESTORE_PROBES,
        violations,
        "MPR26_RESTORE_MATRIX_INCOMPLETE",
        "restore",
    )


def _validate_crash_race(
    crash_race: CrashRaceEvidence,
    violations: list[MPR26Violation],
) -> None:
    _validate_hashes(
        violations,
        "MPR26_BAD_CRASH_RACE_HASH",
        statement_crash_matrix_sha256=crash_race.statement_crash_matrix_sha256,
        two_process_race_report_sha256=crash_race.two_process_race_report_sha256,
    )
    _require_subset(
        crash_race.fault_boundaries_tested,
        REQUIRED_FAULT_BOUNDARIES,
        violations,
        "MPR26_FAULT_MATRIX_INCOMPLETE",
        "fault_matrix",
    )
    _require_subset(
        crash_race.race_probes_tested,
        REQUIRED_RACE_PROBES,
        violations,
        "MPR26_RACE_MATRIX_INCOMPLETE",
        "race_matrix",
    )
    _require_all(
        violations,
        "MPR26_CRASH_RACE_INCOMPLETE",
        "crash_race",
        kill_at_every_write_boundary_proves_exactly_one_terminal=(
            crash_race.kill_at_every_write_boundary_proves_exactly_one_terminal
        ),
        duplicate_opportunities_do_not_overreserve_capital=crash_race.duplicate_opportunities_do_not_overreserve_capital,
        no_split_attempt_projection_or_outbox_truth=crash_race.no_split_attempt_projection_or_outbox_truth,
        restart_releases_or_reconciles_leases_and_reservations=(
            crash_race.restart_releases_or_reconciles_leases_and_reservations
        ),
    )


def _validate_safety_boundary(
    evidence: MPR26Evidence,
    violations: list[MPR26Violation],
) -> None:
    forbidden = {
        "live_execution_requested": evidence.live_execution_requested,
        "signer_requested": evidence.signer_requested,
        "sender_requested": evidence.sender_requested,
        "provider_network_requested": evidence.provider_network_requested,
    }
    enabled = [name for name, value in forbidden.items() if value]
    if enabled:
        _add(
            violations,
            "MPR26_FORBIDDEN_RUNTIME_CAPABILITY",
            "safety",
            f"MPR-26 must remain offline/sender-free: {enabled}",
        )


def _require_all(
    violations: list[MPR26Violation],
    code: str,
    subject: str,
    **flags: bool,
) -> None:
    missing = [name for name, value in flags.items() if value is not True]
    if missing:
        _add(violations, code, subject, f"missing required evidence flags: {missing}")


def _require_subset(
    observed: Iterable[str],
    required: Sequence[str],
    violations: list[MPR26Violation],
    code: str,
    subject: str,
) -> None:
    observed_set = set(observed)
    missing = [item for item in required if item not in observed_set]
    extra = sorted(item for item in observed_set if item not in required)
    if missing:
        _add(violations, code, subject, f"missing probes: {missing}")
    if extra:
        _add(violations, code, subject, f"unknown probes: {extra}")


def _validate_hashes(
    violations: list[MPR26Violation],
    code: str,
    **values: str,
) -> None:
    bad = [name for name, value in values.items() if not _is_sha256(value)]
    if bad:
        _add(violations, code, "hashes", f"invalid or placeholder sha256: {bad}")


def _validate_safe_id(value: object, field_name: str, violations: list[MPR26Violation]) -> None:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        _add(violations, "MPR26_BAD_IDENTIFIER", "identity", f"bad {field_name}")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(_HASH_RE.fullmatch(value))
        and value not in {"0" * 64, "f" * 64}
    )


def _stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(_to_json(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _to_json(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _to_json(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_to_json(item) for item in value]
    return value


def _dedupe(violations: Iterable[MPR26Violation]) -> Iterable[MPR26Violation]:
    seen: set[tuple[str, str, str]] = set()
    for violation in violations:
        key = (violation.code, violation.subject, violation.detail)
        if key not in seen:
            seen.add(key)
            yield violation


def _add(
    violations: list[MPR26Violation],
    code: str,
    subject: str,
    detail: str,
) -> None:
    violations.append(MPR26Violation(code=code, subject=subject, detail=detail))
