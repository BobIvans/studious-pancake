"""PR-195 durable lifecycle and recovery acceptance gate.

This module is deliberately offline and sender-free.  It validates evidence for
the PR-195 control-plane boundary: one durable lifecycle authority, fenced
state transitions, durable idempotency, capital reservation atomicity, outbox
recovery, and crash-consistent restore semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

PR195_SCHEMA_VERSION = "pr195.durable-lifecycle-recovery.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MIN_RETENTION_DAYS = 1
_MIN_BUSY_TIMEOUT_MS = 250
_ALLOWED_AUTHORITY_ROLES = {
    "canonical_lifecycle",
    "legacy_reader",
    "test_fixture",
    "quarantine",
}
_ALLOWED_FAULT_RESULTS = {"passed", "blocked", "not_run", "failed"}
_REQUIRED_FAULT_DRILLS = (
    "kill_9_after_state_before_event",
    "kill_9_after_event_before_projection",
    "two_process_duplicate_opportunity",
    "stale_fencing_token_commit",
    "disk_full_admission_latch",
    "read_only_db_admission_latch",
    "corrupt_wal_startup_refusal",
    "backup_restore_chain_hash",
)


class PR195LifecycleError(ValueError):
    """Raised when PR-195 evidence has an invalid shape."""


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class LifecycleDiagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class LifecycleAuthority:
    name: str
    role: str
    storage: str
    write_enabled: bool
    production_surface: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], *, index: int) -> "LifecycleAuthority":
        path = f"authorities[{index}]"
        role = _non_empty(raw.get("role"), field=f"{path}.role")
        if role not in _ALLOWED_AUTHORITY_ROLES:
            raise PR195LifecycleError(f"{path}.role is unsupported: {role}")
        return cls(
            name=_non_empty(raw.get("name"), field=f"{path}.name"),
            role=role,
            storage=_non_empty(raw.get("storage"), field=f"{path}.storage"),
            write_enabled=_bool(raw.get("write_enabled"), f"{path}.write_enabled"),
            production_surface=_bool(
                raw.get("production_surface"), f"{path}.production_surface"
            ),
        )

    def validate(self) -> tuple[LifecycleDiagnostic, ...]:
        diagnostics: list[LifecycleDiagnostic] = []
        storage = self.storage.lower()
        path = f"authorities.{self.name}"
        if "jsonl" in storage and self.write_enabled:
            diagnostics.append(
                LifecycleDiagnostic(
                    "JSONL_AUTHORITY_WRITE_ENABLED",
                    DiagnosticSeverity.ERROR,
                    "JSONL may not be a production lifecycle authority",
                    f"{path}.write_enabled",
                )
            )
        if self.role != "canonical_lifecycle" and self.write_enabled:
            diagnostics.append(
                LifecycleDiagnostic(
                    "NON_CANONICAL_WRITER",
                    DiagnosticSeverity.ERROR,
                    "only the canonical lifecycle authority may write",
                    f"{path}.role",
                )
            )
        if self.role == "test_fixture" and self.production_surface:
            diagnostics.append(
                LifecycleDiagnostic(
                    "TEST_FIXTURE_ON_PRODUCTION_SURFACE",
                    DiagnosticSeverity.ERROR,
                    "test fixtures must not be on the production surface",
                    f"{path}.production_surface",
                )
            )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class DatabaseEvidence:
    engine: str
    schema_fingerprint: str
    forward_only_migrations: bool
    unknown_schema_blocks_startup: bool
    begin_immediate_required: bool
    fsync_on_commit: bool
    busy_timeout_ms: int
    shared_connection_serialized: bool
    disk_full_latch_enabled: bool
    corruption_latch_enabled: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DatabaseEvidence":
        return cls(
            engine=_non_empty(raw.get("engine"), field="database.engine"),
            schema_fingerprint=_hash(
                raw.get("schema_fingerprint"), "database.schema_fingerprint"
            ),
            forward_only_migrations=_bool(
                raw.get("forward_only_migrations"),
                "database.forward_only_migrations",
            ),
            unknown_schema_blocks_startup=_bool(
                raw.get("unknown_schema_blocks_startup"),
                "database.unknown_schema_blocks_startup",
            ),
            begin_immediate_required=_bool(
                raw.get("begin_immediate_required"),
                "database.begin_immediate_required",
            ),
            fsync_on_commit=_bool(raw.get("fsync_on_commit"), "database.fsync_on_commit"),
            busy_timeout_ms=_int(raw.get("busy_timeout_ms"), "database.busy_timeout_ms"),
            shared_connection_serialized=_bool(
                raw.get("shared_connection_serialized"),
                "database.shared_connection_serialized",
            ),
            disk_full_latch_enabled=_bool(
                raw.get("disk_full_latch_enabled"),
                "database.disk_full_latch_enabled",
            ),
            corruption_latch_enabled=_bool(
                raw.get("corruption_latch_enabled"),
                "database.corruption_latch_enabled",
            ),
        )

    def validate(self) -> tuple[LifecycleDiagnostic, ...]:
        diagnostics: list[LifecycleDiagnostic] = []
        if self.engine not in {"sqlite-wal", "postgres-serializable"}:
            diagnostics.append(
                LifecycleDiagnostic(
                    "UNSUPPORTED_LIFECYCLE_ENGINE",
                    DiagnosticSeverity.ERROR,
                    "lifecycle authority must use sqlite-wal or postgres-serializable",
                    "database.engine",
                )
            )
        for field, code, message in (
            (
                self.forward_only_migrations,
                "MIGRATIONS_NOT_FORWARD_ONLY",
                "schema migrations must be forward-only",
            ),
            (
                self.unknown_schema_blocks_startup,
                "UNKNOWN_SCHEMA_DOES_NOT_BLOCK",
                "unknown schema version must block startup",
            ),
            (
                self.begin_immediate_required,
                "WRITE_TRANSACTION_NOT_EXCLUSIVE",
                "writes must acquire an explicit transactional writer boundary",
            ),
            (
                self.fsync_on_commit,
                "FSYNC_POLICY_MISSING",
                "durable commits require an explicit fsync policy",
            ),
            (
                self.shared_connection_serialized,
                "SHARED_CONNECTION_NOT_SERIALIZED",
                "shared lifecycle connections must be serialized by the authority",
            ),
            (
                self.disk_full_latch_enabled,
                "DISK_FULL_LATCH_MISSING",
                "disk-full/read-only storage must close admission through a latch",
            ),
            (
                self.corruption_latch_enabled,
                "CORRUPTION_LATCH_MISSING",
                "corruption detection must close admission through a latch",
            ),
        ):
            if not field:
                diagnostics.append(
                    LifecycleDiagnostic(code, DiagnosticSeverity.ERROR, message)
                )
        if self.busy_timeout_ms < _MIN_BUSY_TIMEOUT_MS:
            diagnostics.append(
                LifecycleDiagnostic(
                    "BUSY_TIMEOUT_TOO_LOW",
                    DiagnosticSeverity.ERROR,
                    "busy timeout must be explicit and high enough for WAL contention",
                    "database.busy_timeout_ms",
                )
            )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class StateMachineEvidence:
    single_append_transition_primitive: bool
    revision_unique: bool
    event_id_unique: bool
    event_chain_hash: str
    materialized_projection_replay_verified: bool
    terminal_states_are_irreversible: bool
    partial_transition_impossible: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "StateMachineEvidence":
        return cls(
            single_append_transition_primitive=_bool(
                raw.get("single_append_transition_primitive"),
                "state_machine.single_append_transition_primitive",
            ),
            revision_unique=_bool(raw.get("revision_unique"), "state_machine.revision_unique"),
            event_id_unique=_bool(raw.get("event_id_unique"), "state_machine.event_id_unique"),
            event_chain_hash=_hash(
                raw.get("event_chain_hash"), "state_machine.event_chain_hash"
            ),
            materialized_projection_replay_verified=_bool(
                raw.get("materialized_projection_replay_verified"),
                "state_machine.materialized_projection_replay_verified",
            ),
            terminal_states_are_irreversible=_bool(
                raw.get("terminal_states_are_irreversible"),
                "state_machine.terminal_states_are_irreversible",
            ),
            partial_transition_impossible=_bool(
                raw.get("partial_transition_impossible"),
                "state_machine.partial_transition_impossible",
            ),
        )

    def validate(self) -> tuple[LifecycleDiagnostic, ...]:
        checks = (
            (
                self.single_append_transition_primitive,
                "MULTIPLE_TRANSITION_PRIMITIVES",
                "one append-state-plus-event primitive is required",
                "state_machine.single_append_transition_primitive",
            ),
            (
                self.revision_unique,
                "REVISION_NOT_UNIQUE",
                "attempt/opportunity revisions must be unique",
                "state_machine.revision_unique",
            ),
            (
                self.event_id_unique,
                "EVENT_ID_NOT_UNIQUE",
                "event IDs must be unique and durable",
                "state_machine.event_id_unique",
            ),
            (
                self.materialized_projection_replay_verified,
                "PROJECTION_REPLAY_NOT_VERIFIED",
                "materialized state must be replay-checked against the event chain",
                "state_machine.materialized_projection_replay_verified",
            ),
            (
                self.terminal_states_are_irreversible,
                "TERMINAL_STATE_REVERSIBLE",
                "terminal lifecycle states must be irreversible",
                "state_machine.terminal_states_are_irreversible",
            ),
            (
                self.partial_transition_impossible,
                "PARTIAL_TRANSITION_POSSIBLE",
                "state row and event row must not be separable after crashes",
                "state_machine.partial_transition_impossible",
            ),
        )
        return _boolean_diagnostics(checks)


@dataclass(frozen=True, slots=True)
class IdempotencyEvidence:
    durable_unique_keys: bool
    retention_days: int
    expiry_releases_pending: bool
    terminal_compaction_bounded: bool
    duplicate_policy: str
    pending_release_is_atomic_with_queue_expiry: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "IdempotencyEvidence":
        return cls(
            durable_unique_keys=_bool(
                raw.get("durable_unique_keys"), "idempotency.durable_unique_keys"
            ),
            retention_days=_int(raw.get("retention_days"), "idempotency.retention_days"),
            expiry_releases_pending=_bool(
                raw.get("expiry_releases_pending"),
                "idempotency.expiry_releases_pending",
            ),
            terminal_compaction_bounded=_bool(
                raw.get("terminal_compaction_bounded"),
                "idempotency.terminal_compaction_bounded",
            ),
            duplicate_policy=_non_empty(
                raw.get("duplicate_policy"), field="idempotency.duplicate_policy"
            ),
            pending_release_is_atomic_with_queue_expiry=_bool(
                raw.get("pending_release_is_atomic_with_queue_expiry"),
                "idempotency.pending_release_is_atomic_with_queue_expiry",
            ),
        )

    def validate(self) -> tuple[LifecycleDiagnostic, ...]:
        diagnostics = list(
            _boolean_diagnostics(
                (
                    (
                        self.durable_unique_keys,
                        "IDEMPOTENCY_KEYS_NOT_DURABLE",
                        "dedupe/idempotency keys must be durable",
                        "idempotency.durable_unique_keys",
                    ),
                    (
                        self.expiry_releases_pending,
                        "EXPIRY_DOES_NOT_RELEASE_PENDING",
                        "expired opportunities must release PENDING lifecycle state",
                        "idempotency.expiry_releases_pending",
                    ),
                    (
                        self.terminal_compaction_bounded,
                        "TERMINAL_DEDUPE_UNBOUNDED",
                        "terminal dedupe retention must be bounded",
                        "idempotency.terminal_compaction_bounded",
                    ),
                    (
                        self.pending_release_is_atomic_with_queue_expiry,
                        "EXPIRY_NOT_ATOMIC_WITH_QUEUE",
                        "queue expiry and pending-release must happen atomically",
                        "idempotency.pending_release_is_atomic_with_queue_expiry",
                    ),
                )
            )
        )
        if self.retention_days < _MIN_RETENTION_DAYS:
            diagnostics.append(
                LifecycleDiagnostic(
                    "RETENTION_TOO_SHORT",
                    DiagnosticSeverity.ERROR,
                    "idempotency retention must be at least one day",
                    "idempotency.retention_days",
                )
            )
        if self.duplicate_policy not in {"reject", "same-outcome-idempotent"}:
            diagnostics.append(
                LifecycleDiagnostic(
                    "DUPLICATE_POLICY_UNSAFE",
                    DiagnosticSeverity.ERROR,
                    "duplicate policy must reject or return the same durable outcome",
                    "idempotency.duplicate_policy",
                )
            )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class LeaseEvidence:
    monotonic_time_domain: bool
    fencing_tokens: bool
    cas_renewal: bool
    stale_owner_rejected: bool
    side_effects_require_fence: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "LeaseEvidence":
        return cls(
            monotonic_time_domain=_bool(
                raw.get("monotonic_time_domain"), "leases.monotonic_time_domain"
            ),
            fencing_tokens=_bool(raw.get("fencing_tokens"), "leases.fencing_tokens"),
            cas_renewal=_bool(raw.get("cas_renewal"), "leases.cas_renewal"),
            stale_owner_rejected=_bool(
                raw.get("stale_owner_rejected"), "leases.stale_owner_rejected"
            ),
            side_effects_require_fence=_bool(
                raw.get("side_effects_require_fence"),
                "leases.side_effects_require_fence",
            ),
        )

    def validate(self) -> tuple[LifecycleDiagnostic, ...]:
        return _boolean_diagnostics(
            (
                (
                    self.monotonic_time_domain,
                    "LEASE_USES_WALL_CLOCK",
                    "leases must use a trusted monotonic time domain",
                    "leases.monotonic_time_domain",
                ),
                (
                    self.fencing_tokens,
                    "FENCING_TOKEN_MISSING",
                    "lease ownership requires fencing tokens",
                    "leases.fencing_tokens",
                ),
                (
                    self.cas_renewal,
                    "LEASE_RENEWAL_NOT_CAS",
                    "lease renewal must be compare-and-swap protected",
                    "leases.cas_renewal",
                ),
                (
                    self.stale_owner_rejected,
                    "STALE_OWNER_NOT_REJECTED",
                    "stale owners must be rejected before commit",
                    "leases.stale_owner_rejected",
                ),
                (
                    self.side_effects_require_fence,
                    "SIDE_EFFECT_WITHOUT_FENCE",
                    "every side-effect transaction must verify the current fence",
                    "leases.side_effects_require_fence",
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class CapitalEvidence:
    wallet_revision_fencing: bool
    aggregate_balance_constraint: bool
    attempt_and_reservation_atomic: bool
    negative_headroom_latches: bool
    deterministic_or_unique_reservation_ids: bool
    recovery_snapshot_is_single_transaction: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CapitalEvidence":
        return cls(
            wallet_revision_fencing=_bool(
                raw.get("wallet_revision_fencing"),
                "capital.wallet_revision_fencing",
            ),
            aggregate_balance_constraint=_bool(
                raw.get("aggregate_balance_constraint"),
                "capital.aggregate_balance_constraint",
            ),
            attempt_and_reservation_atomic=_bool(
                raw.get("attempt_and_reservation_atomic"),
                "capital.attempt_and_reservation_atomic",
            ),
            negative_headroom_latches=_bool(
                raw.get("negative_headroom_latches"),
                "capital.negative_headroom_latches",
            ),
            deterministic_or_unique_reservation_ids=_bool(
                raw.get("deterministic_or_unique_reservation_ids"),
                "capital.deterministic_or_unique_reservation_ids",
            ),
            recovery_snapshot_is_single_transaction=_bool(
                raw.get("recovery_snapshot_is_single_transaction"),
                "capital.recovery_snapshot_is_single_transaction",
            ),
        )

    def validate(self) -> tuple[LifecycleDiagnostic, ...]:
        return _boolean_diagnostics(
            (
                (
                    self.wallet_revision_fencing,
                    "WALLET_REVISION_FENCE_MISSING",
                    "wallet capital must be fenced by revision",
                    "capital.wallet_revision_fencing",
                ),
                (
                    self.aggregate_balance_constraint,
                    "AGGREGATE_BALANCE_CONSTRAINT_MISSING",
                    "aggregate reservations must not exceed wallet balance",
                    "capital.aggregate_balance_constraint",
                ),
                (
                    self.attempt_and_reservation_atomic,
                    "RESERVATION_NOT_ATOMIC_WITH_ATTEMPT",
                    "attempt creation and capital reservation must be one transaction",
                    "capital.attempt_and_reservation_atomic",
                ),
                (
                    self.negative_headroom_latches,
                    "NEGATIVE_HEADROOM_NOT_LATCHED",
                    "negative capital headroom must close admission",
                    "capital.negative_headroom_latches",
                ),
                (
                    self.deterministic_or_unique_reservation_ids,
                    "RESERVATION_ID_NOT_STABLE",
                    "reservation IDs must be deterministic or cryptographically unique",
                    "capital.deterministic_or_unique_reservation_ids",
                ),
                (
                    self.recovery_snapshot_is_single_transaction,
                    "CAPITAL_RECOVERY_SNAPSHOT_SPLIT",
                    "capital recovery evidence must be read in one transaction",
                    "capital.recovery_snapshot_is_single_transaction",
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class OutboxEvidence:
    durable_before_ack: bool
    claim_fenced: bool
    nack_supported: bool
    max_attempts: int
    dlq_supported: bool
    poison_event_alerts: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "OutboxEvidence":
        return cls(
            durable_before_ack=_bool(
                raw.get("durable_before_ack"), "outbox.durable_before_ack"
            ),
            claim_fenced=_bool(raw.get("claim_fenced"), "outbox.claim_fenced"),
            nack_supported=_bool(raw.get("nack_supported"), "outbox.nack_supported"),
            max_attempts=_int(raw.get("max_attempts"), "outbox.max_attempts"),
            dlq_supported=_bool(raw.get("dlq_supported"), "outbox.dlq_supported"),
            poison_event_alerts=_bool(
                raw.get("poison_event_alerts"), "outbox.poison_event_alerts"
            ),
        )

    def validate(self) -> tuple[LifecycleDiagnostic, ...]:
        diagnostics = list(
            _boolean_diagnostics(
                (
                    (
                        self.durable_before_ack,
                        "ACK_BEFORE_DURABLE_COMMIT",
                        "external ACK must happen only after durable commit",
                        "outbox.durable_before_ack",
                    ),
                    (
                        self.claim_fenced,
                        "OUTBOX_CLAIM_NOT_FENCED",
                        "outbox claims must carry an owner/fencing token",
                        "outbox.claim_fenced",
                    ),
                    (
                        self.nack_supported,
                        "OUTBOX_NACK_MISSING",
                        "outbox must support nack/retry classification",
                        "outbox.nack_supported",
                    ),
                    (
                        self.dlq_supported,
                        "OUTBOX_DLQ_MISSING",
                        "poison events require a dead-letter state",
                        "outbox.dlq_supported",
                    ),
                    (
                        self.poison_event_alerts,
                        "POISON_EVENT_ALERT_MISSING",
                        "dead-letter transitions must alert operators",
                        "outbox.poison_event_alerts",
                    ),
                )
            )
        )
        if self.max_attempts < 1:
            diagnostics.append(
                LifecycleDiagnostic(
                    "OUTBOX_MAX_ATTEMPTS_INVALID",
                    DiagnosticSeverity.ERROR,
                    "outbox max_attempts must be at least one",
                    "outbox.max_attempts",
                )
            )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class RestoreEvidence:
    validates_temp_sibling_before_replace: bool
    previous_generation_preserved: bool
    authenticated_backup_manifest_required: bool
    restored_chain_hash_matches: bool
    open_database_overwrite_forbidden: bool

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RestoreEvidence":
        return cls(
            validates_temp_sibling_before_replace=_bool(
                raw.get("validates_temp_sibling_before_replace"),
                "restore.validates_temp_sibling_before_replace",
            ),
            previous_generation_preserved=_bool(
                raw.get("previous_generation_preserved"),
                "restore.previous_generation_preserved",
            ),
            authenticated_backup_manifest_required=_bool(
                raw.get("authenticated_backup_manifest_required"),
                "restore.authenticated_backup_manifest_required",
            ),
            restored_chain_hash_matches=_bool(
                raw.get("restored_chain_hash_matches"),
                "restore.restored_chain_hash_matches",
            ),
            open_database_overwrite_forbidden=_bool(
                raw.get("open_database_overwrite_forbidden"),
                "restore.open_database_overwrite_forbidden",
            ),
        )

    def validate(self) -> tuple[LifecycleDiagnostic, ...]:
        return _boolean_diagnostics(
            (
                (
                    self.validates_temp_sibling_before_replace,
                    "RESTORE_NOT_TEMP_VALIDATED",
                    "restore must validate a temporary sibling before replacement",
                    "restore.validates_temp_sibling_before_replace",
                ),
                (
                    self.previous_generation_preserved,
                    "RESTORE_DESTROYS_PREVIOUS_GENERATION",
                    "restore must preserve the previous generation until validation passes",
                    "restore.previous_generation_preserved",
                ),
                (
                    self.authenticated_backup_manifest_required,
                    "BACKUP_MANIFEST_NOT_AUTHENTICATED",
                    "production restore must require authenticated backup identity",
                    "restore.authenticated_backup_manifest_required",
                ),
                (
                    self.restored_chain_hash_matches,
                    "RESTORED_CHAIN_HASH_MISMATCH",
                    "restored DB must match event-chain/schema verification evidence",
                    "restore.restored_chain_hash_matches",
                ),
                (
                    self.open_database_overwrite_forbidden,
                    "OPEN_DB_OVERWRITE_ALLOWED",
                    "restore must not overwrite an open lifecycle DB",
                    "restore.open_database_overwrite_forbidden",
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class FaultDrill:
    scenario: str
    result: str
    evidence_hash: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any], *, index: int) -> "FaultDrill":
        path = f"fault_drills[{index}]"
        result = _non_empty(raw.get("result"), field=f"{path}.result")
        if result not in _ALLOWED_FAULT_RESULTS:
            raise PR195LifecycleError(f"{path}.result is unsupported: {result}")
        return cls(
            scenario=_non_empty(raw.get("scenario"), field=f"{path}.scenario"),
            result=result,
            evidence_hash=_hash(raw.get("evidence_hash"), f"{path}.evidence_hash"),
        )


@dataclass(frozen=True, slots=True)
class DurableLifecycleEvidence:
    schema_version: str
    release_hash: str
    authorities: tuple[LifecycleAuthority, ...]
    database: DatabaseEvidence
    state_machine: StateMachineEvidence
    idempotency: IdempotencyEvidence
    leases: LeaseEvidence
    capital: CapitalEvidence
    outbox: OutboxEvidence
    restore: RestoreEvidence
    fault_drills: tuple[FaultDrill, ...]
    live_enabled: bool
    signer_enabled: bool
    sender_enabled: bool
    raw: Mapping[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DurableLifecycleEvidence":
        if not isinstance(raw, Mapping):
            raise PR195LifecycleError("evidence root must be an object")
        schema_version = _non_empty(raw.get("schema_version"), field="schema_version")
        if schema_version != PR195_SCHEMA_VERSION:
            raise PR195LifecycleError("unsupported PR-195 lifecycle evidence schema")
        authorities = _mapping_list(raw.get("authorities"), "authorities")
        fault_drills = _mapping_list(raw.get("fault_drills"), "fault_drills")
        return cls(
            schema_version=schema_version,
            release_hash=_hash(raw.get("release_hash"), "release_hash"),
            authorities=tuple(
                LifecycleAuthority.from_dict(item, index=index)
                for index, item in enumerate(authorities)
            ),
            database=DatabaseEvidence.from_dict(_mapping(raw.get("database"), "database")),
            state_machine=StateMachineEvidence.from_dict(
                _mapping(raw.get("state_machine"), "state_machine")
            ),
            idempotency=IdempotencyEvidence.from_dict(
                _mapping(raw.get("idempotency"), "idempotency")
            ),
            leases=LeaseEvidence.from_dict(_mapping(raw.get("leases"), "leases")),
            capital=CapitalEvidence.from_dict(_mapping(raw.get("capital"), "capital")),
            outbox=OutboxEvidence.from_dict(_mapping(raw.get("outbox"), "outbox")),
            restore=RestoreEvidence.from_dict(_mapping(raw.get("restore"), "restore")),
            fault_drills=tuple(
                FaultDrill.from_dict(item, index=index)
                for index, item in enumerate(fault_drills)
            ),
            live_enabled=_bool(raw.get("live_enabled"), "live_enabled"),
            signer_enabled=_bool(raw.get("signer_enabled"), "signer_enabled"),
            sender_enabled=_bool(raw.get("sender_enabled"), "sender_enabled"),
            raw=dict(raw),
        )

    def evidence_hash(self) -> str:
        encoded = json.dumps(
            self.raw,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def validate(self) -> tuple[LifecycleDiagnostic, ...]:
        diagnostics: list[LifecycleDiagnostic] = []
        diagnostics.extend(self._validate_authorities())
        diagnostics.extend(self.database.validate())
        diagnostics.extend(self.state_machine.validate())
        diagnostics.extend(self.idempotency.validate())
        diagnostics.extend(self.leases.validate())
        diagnostics.extend(self.capital.validate())
        diagnostics.extend(self.outbox.validate())
        diagnostics.extend(self.restore.validate())
        diagnostics.extend(self._validate_fault_drills())
        if self.live_enabled:
            diagnostics.append(
                LifecycleDiagnostic(
                    "LIVE_ENABLED_IN_PR195",
                    DiagnosticSeverity.ERROR,
                    "PR-195 is a sender-free durable lifecycle gate",
                    "live_enabled",
                )
            )
        if self.signer_enabled:
            diagnostics.append(
                LifecycleDiagnostic(
                    "SIGNER_ENABLED_IN_PR195",
                    DiagnosticSeverity.ERROR,
                    "PR-195 must not enable signing",
                    "signer_enabled",
                )
            )
        if self.sender_enabled:
            diagnostics.append(
                LifecycleDiagnostic(
                    "SENDER_ENABLED_IN_PR195",
                    DiagnosticSeverity.ERROR,
                    "PR-195 must not enable transaction submission",
                    "sender_enabled",
                )
            )
        return tuple(diagnostics)

    def _validate_authorities(self) -> tuple[LifecycleDiagnostic, ...]:
        diagnostics: list[LifecycleDiagnostic] = []
        canonical_writers = [
            authority
            for authority in self.authorities
            if authority.role == "canonical_lifecycle" and authority.write_enabled
        ]
        if len(canonical_writers) != 1:
            diagnostics.append(
                LifecycleDiagnostic(
                    "CANONICAL_WRITER_COUNT_INVALID",
                    DiagnosticSeverity.ERROR,
                    "exactly one canonical lifecycle writer is required",
                    "authorities",
                )
            )
        for authority in self.authorities:
            diagnostics.extend(authority.validate())
        return tuple(diagnostics)

    def _validate_fault_drills(self) -> tuple[LifecycleDiagnostic, ...]:
        diagnostics: list[LifecycleDiagnostic] = []
        by_scenario = {drill.scenario: drill for drill in self.fault_drills}
        for scenario in _REQUIRED_FAULT_DRILLS:
            drill = by_scenario.get(scenario)
            if drill is None:
                diagnostics.append(
                    LifecycleDiagnostic(
                        "FAULT_DRILL_MISSING",
                        DiagnosticSeverity.ERROR,
                        f"required fault drill {scenario!r} is missing",
                        "fault_drills",
                    )
                )
            elif drill.result != "passed":
                diagnostics.append(
                    LifecycleDiagnostic(
                        "FAULT_DRILL_NOT_PASSED",
                        DiagnosticSeverity.ERROR,
                        f"required fault drill {scenario!r} did not pass",
                        f"fault_drills.{scenario}",
                    )
                )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class DurableLifecycleReport:
    schema_version: str
    ok: bool
    evidence_hash: str
    diagnostics: tuple[LifecycleDiagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "evidence_hash": self.evidence_hash,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


def validate_durable_lifecycle_evidence(
    evidence: Mapping[str, Any],
) -> DurableLifecycleReport:
    parsed = DurableLifecycleEvidence.from_dict(evidence)
    diagnostics = parsed.validate()
    return DurableLifecycleReport(
        schema_version=parsed.schema_version,
        ok=not any(item.severity is DiagnosticSeverity.ERROR for item in diagnostics),
        evidence_hash=parsed.evidence_hash(),
        diagnostics=diagnostics,
    )


def live_capability_allowed() -> bool:
    """PR-195 is a durable control-plane gate and never enables live trading."""

    return False


def signer_capability_allowed() -> bool:
    """PR-195 does not expose signer capability."""

    return False


def sender_capability_allowed() -> bool:
    """PR-195 does not expose submission capability."""

    return False


def _boolean_diagnostics(
    checks: Sequence[tuple[bool, str, str, str]],
) -> tuple[LifecycleDiagnostic, ...]:
    return tuple(
        LifecycleDiagnostic(code, DiagnosticSeverity.ERROR, message, path)
        for ok, code, message, path in checks
        if not ok
    )


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PR195LifecycleError(f"{field} must be an object")
    return value


def _mapping_list(value: object, field: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        raise PR195LifecycleError(f"{field} must be a list")
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise PR195LifecycleError(f"{field}[{index}] must be an object")
    return tuple(value)


def _hash(value: object, field: str) -> str:
    text = _non_empty(value, field=field).lower()
    if not _SHA256_RE.fullmatch(text):
        raise PR195LifecycleError(f"{field} must be a sha256 hex string")
    return text


def _bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise PR195LifecycleError(f"{field} must be boolean")
    return value


def _int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PR195LifecycleError(f"{field} must be an integer")
    return value


def _non_empty(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR195LifecycleError(f"{field} must be a non-empty string")
    return value.strip()


__all__ = [
    "DiagnosticSeverity",
    "DurableLifecycleEvidence",
    "DurableLifecycleReport",
    "LifecycleAuthority",
    "LifecycleDiagnostic",
    "PR195LifecycleError",
    "PR195_SCHEMA_VERSION",
    "validate_durable_lifecycle_evidence",
    "live_capability_allowed",
    "sender_capability_allowed",
    "signer_capability_allowed",
]
