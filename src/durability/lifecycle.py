"""PR-041 single-node durable lifecycle journal and crash recovery."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
from uuid import uuid4

from src.execution.models import ExecutionState
from src.execution.state_machine import ExecutionStateMachine, TERMINAL_STATES
from src.observability.redaction import REDACTION_VERSION, sanitized_with_stats

MIGRATION_VERSION = 41
SCHEMA_NAME = "pr041.durable-lifecycle.v1"
ZERO_HASH = "0" * 64

PRE_SUBMISSION = frozenset(
    {
        ExecutionState.CREATED,
        ExecutionState.PLANNED,
        ExecutionState.COMPILED,
        ExecutionState.STRUCTURALLY_VALIDATED,
        ExecutionState.SIMULATED,
        ExecutionState.APPROVED,
        ExecutionState.SIGNED,
        ExecutionState.PROVEN_EXPIRED,
        ExecutionState.REBUILD_ELIGIBLE,
    }
)
MAY_HAVE_SUBMITTED = frozenset(
    {
        ExecutionState.SUBMISSION_INTENT_RECORDED,
        ExecutionState.SUBMISSION_UNCERTAIN,
        ExecutionState.ACCEPTED,
        ExecutionState.PENDING,
        ExecutionState.LANDED,
        ExecutionState.RECONCILING,
        ExecutionState.SUBMITTED,
    }
)


class DurableLifecycleError(RuntimeError):
    pass


class CorruptJournalError(DurableLifecycleError):
    pass


class LeaseLostError(DurableLifecycleError):
    pass


class UnsupportedTopologyError(DurableLifecycleError):
    pass


class DuplicateSubmissionError(DurableLifecycleError):
    pass


class RecoveryAction(StrEnum):
    RESUME_PRE_SUBMISSION = "resume_pre_submission"
    REBUILD = "rebuild"
    RECONCILE_NO_RESUBMIT = "reconcile_no_resubmit"
    MANUAL_REVIEW = "manual_review"


class ReservationState(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    CONSUMED = "consumed"


@dataclass(frozen=True, slots=True)
class AttemptKey:
    logical_opportunity_id: str
    plan_hash: str
    generation: int

    def __post_init__(self) -> None:
        if not self.logical_opportunity_id or not self.plan_hash:
            raise ValueError("opportunity and plan hash are required")
        if self.generation < 1:
            raise ValueError("generation must be positive")

    @property
    def attempt_id(self) -> str:
        value = (
            f"{self.logical_opportunity_id}\0{self.plan_hash}\0{self.generation}"
        )
        return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class LeaseToken:
    resource_key: str
    owner_id: str
    fencing_token: int
    expires_at_ns: int


@dataclass(frozen=True, slots=True)
class DurableAttempt:
    attempt_id: str
    key: AttemptKey
    state: ExecutionState
    revision: int
    message_hash: str | None
    reservation_id: str | None
    reserved_lamports: int
    reservation_state: ReservationState | None
    transport: str | None
    submission_signature: str | None
    jito_bundle_id: str | None
    updated_at_ns: int


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    attempt: DurableAttempt
    action: RecoveryAction
    reservation_active: bool
    reason: str


@dataclass(frozen=True, slots=True)
class BackupManifest:
    schema: str
    migration_version: int
    database_path: str
    sha256: str
    size_bytes: int
    created_at_ns: int


@dataclass(frozen=True, slots=True)
class OutboxItem:
    outbox_id: int
    event_id: str
    attempt_id: str
    topic: str
    payload: Mapping[str, object]
    fencing_token: int


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lifecycle_migrations(
 version INTEGER PRIMARY KEY, schema_name TEXT NOT NULL,
 checksum TEXT NOT NULL, applied_at_ns INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS durable_attempts(
 attempt_id TEXT PRIMARY KEY, logical_opportunity_id TEXT NOT NULL,
 plan_hash TEXT NOT NULL, generation INTEGER NOT NULL CHECK(generation>=1),
 state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
 message_hash TEXT, reservation_id TEXT, reserved_lamports INTEGER NOT NULL DEFAULT 0,
 reservation_state TEXT, transport TEXT, submission_signature TEXT, jito_bundle_id TEXT,
 terminal_at_ns INTEGER, created_at_ns INTEGER NOT NULL, updated_at_ns INTEGER NOT NULL,
 UNIQUE(logical_opportunity_id,plan_hash,generation));
CREATE UNIQUE INDEX IF NOT EXISTS uq_durable_message ON durable_attempts(message_hash)
 WHERE message_hash IS NOT NULL;
CREATE TABLE IF NOT EXISTS durable_reservations(
 reservation_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE
 REFERENCES durable_attempts(attempt_id) ON DELETE RESTRICT,
 candidate_id TEXT NOT NULL, amount_lamports INTEGER NOT NULL CHECK(amount_lamports>=0),
 state TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, release_reason TEXT,
 created_at_ns INTEGER NOT NULL, updated_at_ns INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS durable_events(
 event_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL
 REFERENCES durable_attempts(attempt_id) ON DELETE RESTRICT,
 sequence_no INTEGER NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
 event_type TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL, reason_code TEXT,
 payload_json TEXT NOT NULL, payload_digest TEXT NOT NULL,
 redaction_version TEXT NOT NULL, redaction_hits INTEGER NOT NULL,
 previous_chain_hash TEXT NOT NULL, chain_hash TEXT NOT NULL, created_at_ns INTEGER NOT NULL,
 UNIQUE(attempt_id,sequence_no));
CREATE TABLE IF NOT EXISTS durable_outbox(
 outbox_id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE
 REFERENCES durable_events(event_id) ON DELETE RESTRICT,
 attempt_id TEXT NOT NULL, topic TEXT NOT NULL, payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending', owner_id TEXT, fencing_token INTEGER,
 available_at_ns INTEGER NOT NULL, claimed_until_ns INTEGER,
 attempt_count INTEGER NOT NULL DEFAULT 0, created_at_ns INTEGER NOT NULL,
 completed_at_ns INTEGER);
CREATE TABLE IF NOT EXISTS durable_leases(
 resource_key TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
 fencing_token INTEGER NOT NULL CHECK(fencing_token>=1),
 expires_at_ns INTEGER NOT NULL, updated_at_ns INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS retention_ledger(
 retention_id INTEGER PRIMARY KEY, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
 action TEXT NOT NULL, cutoff_ns INTEGER NOT NULL, created_at_ns INTEGER NOT NULL,
 UNIQUE(target_type,target_id,action));
CREATE TRIGGER IF NOT EXISTS durable_events_no_update BEFORE UPDATE ON durable_events
 BEGIN SELECT RAISE(ABORT,'durable audit events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS durable_events_no_delete BEFORE DELETE ON durable_events
 BEGIN SELECT RAISE(ABORT,'durable audit events are immutable'); END;
"""


class DurableLifecycleStore:
    """Atomic state, reservation, audit, outbox, lease, and recovery store."""

    TABLES = (
        "durable_attempts",
        "durable_reservations",
        "durable_events",
        "durable_outbox",
        "durable_leases",
        "retention_ledger",
    )

    def __init__(
        self,
        path: str | Path,
        *,
        topology: str = "single-node",
        busy_timeout_ms: int = 5_000,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if topology != "single-node":
            raise UnsupportedTopologyError(
                "SQLite supports single-node topology only"
            )
        self.path = str(path)
        self.clock_ns = clock_ns
        self.machine = ExecutionStateMachine()
        self.db = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=busy_timeout_ms / 1000,
            check_same_thread=False,
        )
        self.db.row_factory = sqlite3.Row
        for pragma in (
            f"PRAGMA busy_timeout={busy_timeout_ms}",
            "PRAGMA foreign_keys=ON",
            "PRAGMA synchronous=FULL",
            "PRAGMA trusted_schema=OFF",
        ):
            self.db.execute(pragma)
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self._migrate()
        self.integrity_check()

    def __enter__(self) -> "DurableLifecycleStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    def _migrate(self) -> None:
        checksum = hashlib.sha256(SCHEMA_SQL.encode()).hexdigest()
        now = self.clock_ns()
        with self.db:
            self.db.executescript(SCHEMA_SQL)
            row = self.db.execute(
                "SELECT checksum FROM lifecycle_migrations WHERE version=?",
                (MIGRATION_VERSION,),
            ).fetchone()
            if row and row["checksum"] != checksum:
                raise CorruptJournalError("migration checksum mismatch")
            self.db.execute(
                "INSERT OR IGNORE INTO lifecycle_migrations VALUES(?,?,?,?)",
                (MIGRATION_VERSION, SCHEMA_NAME, checksum, now),
            )
            self.db.execute(f"PRAGMA user_version={MIGRATION_VERSION}")

    @staticmethod
    def _payload(
        payload: Mapping[str, object] | None,
    ) -> tuple[str, str, int]:
        safe, hits = sanitized_with_stats(dict(payload or {}))
        encoded = json.dumps(
            safe,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return encoded, hashlib.sha256(encoded.encode()).hexdigest(), hits

    @staticmethod
    def _chain(
        previous: str,
        attempt_id: str,
        sequence: int,
        event_type: str,
        from_state: str | None,
        to_state: str,
        reason: str | None,
        payload_digest: str,
        created_at_ns: int,
    ) -> str:
        value = json.dumps(
            [
                previous,
                attempt_id,
                sequence,
                event_type,
                from_state,
                to_state,
                reason,
                payload_digest,
                created_at_ns,
            ],
            separators=(",", ":"),
        )
        return hashlib.sha256(value.encode()).hexdigest()

    def _event(
        self,
        *,
        attempt_id: str,
        sequence: int,
        idempotency_key: str,
        event_type: str,
        from_state: ExecutionState | None,
        to_state: ExecutionState,
        reason: str | None,
        payload: Mapping[str, object] | None,
        topic: str | None,
        now: int,
    ) -> str:
        found = self.db.execute(
            "SELECT event_id,attempt_id FROM durable_events "
            "WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if found:
            if found["attempt_id"] != attempt_id:
                raise DurableLifecycleError(
                    "idempotency key belongs to another attempt"
                )
            return str(found["event_id"])
        last = self.db.execute(
            "SELECT chain_hash FROM durable_events WHERE attempt_id=? "
            "ORDER BY sequence_no DESC LIMIT 1",
            (attempt_id,),
        ).fetchone()
        previous = str(last["chain_hash"]) if last else ZERO_HASH
        payload_json, payload_digest, hits = self._payload(payload)
        chain = self._chain(
            previous,
            attempt_id,
            sequence,
            event_type,
            from_state.value if from_state else None,
            to_state.value,
            reason,
            payload_digest,
            now,
        )
        event_id = uuid4().hex
        self.db.execute(
            "INSERT INTO durable_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                attempt_id,
                sequence,
                idempotency_key,
                event_type,
                from_state.value if from_state else None,
                to_state.value,
                reason,
                payload_json,
                payload_digest,
                REDACTION_VERSION,
                hits,
                previous,
                chain,
                now,
            ),
        )
        if topic:
            self.db.execute(
                "INSERT INTO durable_outbox(event_id,attempt_id,topic,"
                "payload_json,available_at_ns,created_at_ns) "
                "VALUES(?,?,?,?,?,?)",
                (event_id, attempt_id, topic, payload_json, now, now),
            )
        return event_id

    def _attempt(self, row: sqlite3.Row) -> DurableAttempt:
        value = row["reservation_state"]
        return DurableAttempt(
            str(row["attempt_id"]),
            AttemptKey(
                str(row["logical_opportunity_id"]),
                str(row["plan_hash"]),
                int(row["generation"]),
            ),
            ExecutionState(str(row["state"])),
            int(row["revision"]),
            row["message_hash"],
            row["reservation_id"],
            int(row["reserved_lamports"]),
            ReservationState(str(value)) if value else None,
            row["transport"],
            row["submission_signature"],
            row["jito_bundle_id"],
            int(row["updated_at_ns"]),
        )

    def get_attempt(self, attempt_id: str) -> DurableAttempt | None:
        row = self.db.execute(
            "SELECT * FROM durable_attempts WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
        return self._attempt(row) if row else None

    def create_attempt(
        self,
        key: AttemptKey,
        *,
        idempotency_key: str,
        state: ExecutionState = ExecutionState.PLANNED,
        reservation_id: str | None = None,
        candidate_id: str | None = None,
        reserved_lamports: int = 0,
        payload: Mapping[str, object] | None = None,
    ) -> DurableAttempt:
        if reserved_lamports < 0 or bool(reservation_id) != bool(candidate_id):
            raise ValueError("invalid reservation fields")
        if reserved_lamports and not reservation_id:
            raise ValueError("positive reservation requires an id")
        now, attempt_id = self.clock_ns(), key.attempt_id
        with self.db:
            row = self.db.execute(
                "SELECT * FROM durable_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row:
                event = self.db.execute(
                    "SELECT attempt_id FROM durable_events "
                    "WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if event and event["attempt_id"] == attempt_id:
                    return self._attempt(row)
                raise DurableLifecycleError("attempt already exists")
            rstate = ReservationState.ACTIVE.value if reservation_id else None
            self.db.execute(
                "INSERT INTO durable_attempts(attempt_id,"
                "logical_opportunity_id,plan_hash,generation,state,revision,"
                "reservation_id,reserved_lamports,reservation_state,"
                "created_at_ns,updated_at_ns) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id,
                    key.logical_opportunity_id,
                    key.plan_hash,
                    key.generation,
                    state.value,
                    0,
                    reservation_id,
                    reserved_lamports,
                    rstate,
                    now,
                    now,
                ),
            )
            if reservation_id:
                self.db.execute(
                    "INSERT INTO durable_reservations("
                    "reservation_id,attempt_id,candidate_id,amount_lamports,"
                    "state,idempotency_key,release_reason,created_at_ns,"
                    "updated_at_ns) VALUES(?,?,?,?,?,?,NULL,?,?)",
                    (
                        reservation_id,
                        attempt_id,
                        candidate_id,
                        reserved_lamports,
                        ReservationState.ACTIVE.value,
                        f"reservation:{idempotency_key}",
                        now,
                        now,
                    ),
                )
            self._event(
                attempt_id=attempt_id,
                sequence=0,
                idempotency_key=idempotency_key,
                event_type="attempt_created",
                from_state=None,
                to_state=state,
                reason=None,
                payload=payload,
                topic="lifecycle.event",
                now=now,
            )
        result = self.get_attempt(attempt_id)
        if result is None:
            raise DurableLifecycleError("attempt disappeared")
        return result

    def acquire_lease(
        self,
        resource_key: str,
        *,
        owner_id: str,
        ttl_ns: int,
    ) -> LeaseToken:
        if not resource_key or not owner_id or ttl_ns <= 0:
            raise ValueError("resource, owner and positive ttl are required")
        now = self.clock_ns()
        expires = now + ttl_ns
        with self.db:
            row = self.db.execute(
                "SELECT * FROM durable_leases WHERE resource_key=?",
                (resource_key,),
            ).fetchone()
            if (
                row
                and int(row["expires_at_ns"]) > now
                and row["owner_id"] != owner_id
            ):
                raise LeaseLostError("resource has another live owner")
            fence = int(row["fencing_token"]) + 1 if row else 1
            self.db.execute(
                "INSERT INTO durable_leases VALUES(?,?,?,?,?) "
                "ON CONFLICT(resource_key) DO UPDATE SET "
                "owner_id=excluded.owner_id,"
                "fencing_token=excluded.fencing_token,"
                "expires_at_ns=excluded.expires_at_ns,"
                "updated_at_ns=excluded.updated_at_ns",
                (resource_key, owner_id, fence, expires, now),
            )
        return LeaseToken(resource_key, owner_id, fence, expires)

    def _verify_lease(self, token: LeaseToken, resource: str) -> None:
        now = self.clock_ns()
        row = self.db.execute(
            "SELECT * FROM durable_leases WHERE resource_key=?",
            (resource,),
        ).fetchone()
        if (
            not row
            or row["owner_id"] != token.owner_id
            or int(row["fencing_token"]) != token.fencing_token
            or int(row["expires_at_ns"]) <= now
        ):
            raise LeaseLostError("stale or expired fencing token")

    def transition(
        self,
        attempt_id: str,
        *,
        expected_revision: int,
        target: ExecutionState,
        idempotency_key: str,
        lease: LeaseToken,
        reason_code: str | None = None,
        payload: Mapping[str, object] | None = None,
        release_reservation: bool = False,
    ) -> DurableAttempt:
        now = self.clock_ns()
        with self.db:
            self._verify_lease(lease, f"attempt:{attempt_id}")
            row = self.db.execute(
                "SELECT * FROM durable_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if not row:
                raise DurableLifecycleError("attempt not found")
            duplicate = self.db.execute(
                "SELECT attempt_id FROM durable_events "
                "WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if duplicate:
                if duplicate["attempt_id"] != attempt_id:
                    raise DurableLifecycleError("idempotency collision")
                result = self.get_attempt(attempt_id)
                if result is None:
                    raise DurableLifecycleError("attempt disappeared")
                return result
            current = ExecutionState(str(row["state"]))
            revision = int(row["revision"])
            if revision != expected_revision:
                raise DurableLifecycleError("optimistic revision conflict")
            self.machine.transition(current, target)
            next_revision = revision + 1
            terminal_at = now if target in TERMINAL_STATES else None
            cur = self.db.execute(
                "UPDATE durable_attempts SET state=?,revision=?,"
                "terminal_at_ns=?,updated_at_ns=? WHERE attempt_id=? "
                "AND revision=?",
                (
                    target.value,
                    next_revision,
                    terminal_at,
                    now,
                    attempt_id,
                    revision,
                ),
            )
            if cur.rowcount != 1:
                raise DurableLifecycleError("optimistic revision conflict")
            if release_reservation:
                self._release_reservation(
                    attempt_id,
                    reason_code or "transition",
                    now,
                )
            self._event(
                attempt_id=attempt_id,
                sequence=next_revision,
                idempotency_key=idempotency_key,
                event_type="state_transition",
                from_state=current,
                to_state=target,
                reason=reason_code,
                payload=payload,
                topic="lifecycle.event",
                now=now,
            )
        result = self.get_attempt(attempt_id)
        if result is None:
            raise DurableLifecycleError("attempt disappeared")
        return result

    def record_submission_intent(
        self,
        attempt_id: str,
        *,
        expected_revision: int,
        message_hash: str,
        transport: str,
        idempotency_key: str,
        lease: LeaseToken,
        submission_signature: str | None = None,
        jito_bundle_id: str | None = None,
    ) -> DurableAttempt:
        if len(message_hash) != 64:
            raise ValueError("message_hash must be sha256 hex")
        int(message_hash, 16)
        now = self.clock_ns()
        with self.db:
            self._verify_lease(lease, f"attempt:{attempt_id}")
            row = self.db.execute(
                "SELECT * FROM durable_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if not row:
                raise DurableLifecycleError("attempt not found")
            duplicate = self.db.execute(
                "SELECT attempt_id FROM durable_events "
                "WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if duplicate:
                if duplicate["attempt_id"] != attempt_id:
                    raise DuplicateSubmissionError("submission key collision")
                result = self.get_attempt(attempt_id)
                if result is None:
                    raise DurableLifecycleError("attempt disappeared")
                return result
            owner = self.db.execute(
                "SELECT attempt_id FROM durable_attempts WHERE message_hash=? "
                "AND attempt_id<>?",
                (message_hash, attempt_id),
            ).fetchone()
            if owner:
                raise DuplicateSubmissionError(
                    "canonical message already owned"
                )
            current = ExecutionState(str(row["state"]))
            revision = int(row["revision"])
            if current is not ExecutionState.SIGNED or revision != expected_revision:
                raise DurableLifecycleError(
                    "signed state and exact revision required"
                )
            self.machine.transition(
                current,
                ExecutionState.SUBMISSION_INTENT_RECORDED,
            )
            next_revision = revision + 1
            try:
                self.db.execute(
                    "UPDATE durable_attempts SET state=?,revision=?,"
                    "message_hash=?,transport=?,submission_signature=?,"
                    "jito_bundle_id=?,updated_at_ns=? WHERE attempt_id=? "
                    "AND revision=?",
                    (
                        ExecutionState.SUBMISSION_INTENT_RECORDED.value,
                        next_revision,
                        message_hash,
                        transport,
                        submission_signature,
                        jito_bundle_id,
                        now,
                        attempt_id,
                        revision,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateSubmissionError(
                    "canonical message already recorded"
                ) from exc
            self._event(
                attempt_id=attempt_id,
                sequence=next_revision,
                idempotency_key=idempotency_key,
                event_type="submission_intent_recorded",
                from_state=current,
                to_state=ExecutionState.SUBMISSION_INTENT_RECORDED,
                reason="SUBMISSION_INTENT_RECORDED",
                payload={
                    "message_hash": message_hash,
                    "transport": transport,
                    "submission_signature": submission_signature,
                    "jito_bundle_id": jito_bundle_id,
                },
                topic="submission.reconcile",
                now=now,
            )
        result = self.get_attempt(attempt_id)
        if result is None:
            raise DurableLifecycleError("attempt disappeared")
        return result

    def _release_reservation(
        self,
        attempt_id: str,
        reason: str,
        now: int,
    ) -> bool:
        cur = self.db.execute(
            "UPDATE durable_reservations SET state=?,release_reason=?,"
            "updated_at_ns=? WHERE attempt_id=? AND state=?",
            (
                ReservationState.RELEASED.value,
                reason,
                now,
                attempt_id,
                ReservationState.ACTIVE.value,
            ),
        )
        if cur.rowcount:
            self.db.execute(
                "UPDATE durable_attempts SET reservation_state=?,"
                "updated_at_ns=? WHERE attempt_id=?",
                (
                    ReservationState.RELEASED.value,
                    now,
                    attempt_id,
                ),
            )
        return cur.rowcount == 1

    def release_abandoned_reservation(
        self,
        attempt_id: str,
        *,
        idempotency_key: str,
        lease: LeaseToken,
        reason: str = "RECOVERY_PRE_SUBMISSION_RELEASED",
    ) -> bool:
        now = self.clock_ns()
        with self.db:
            self._verify_lease(lease, f"attempt:{attempt_id}")
            row = self.db.execute(
                "SELECT * FROM durable_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if not row:
                raise DurableLifecycleError("attempt not found")
            state = ExecutionState(str(row["state"]))
            if state not in PRE_SUBMISSION:
                raise DurableLifecycleError(
                    "submitted or ambiguous reservation cannot be auto-released"
                )
            duplicate = self.db.execute(
                "SELECT 1 FROM durable_events WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if duplicate:
                return False
            released = self._release_reservation(attempt_id, reason, now)
            if released:
                revision = int(row["revision"]) + 1
                self.db.execute(
                    "UPDATE durable_attempts SET revision=?,updated_at_ns=? "
                    "WHERE attempt_id=?",
                    (revision, now, attempt_id),
                )
                self._event(
                    attempt_id=attempt_id,
                    sequence=revision,
                    idempotency_key=idempotency_key,
                    event_type="reservation_released",
                    from_state=state,
                    to_state=state,
                    reason=reason,
                    payload={"reservation_id": row["reservation_id"]},
                    topic="capital.reservation",
                    now=now,
                )
            return released

    def scan_startup_recovery(self) -> tuple[RecoveryDecision, ...]:
        self.integrity_check()
        rows = self.db.execute(
            "SELECT * FROM durable_attempts WHERE terminal_at_ns IS NULL "
            "ORDER BY created_at_ns,attempt_id"
        ).fetchall()
        output = []
        for row in rows:
            attempt = self._attempt(row)
            if attempt.state is ExecutionState.REBUILD_ELIGIBLE:
                action = RecoveryAction.REBUILD
                reason = "explicitly rebuild eligible"
            elif attempt.state in PRE_SUBMISSION:
                action = RecoveryAction.RESUME_PRE_SUBMISSION
                reason = "no durable submission intent"
            elif attempt.state in MAY_HAVE_SUBMITTED:
                action = RecoveryAction.RECONCILE_NO_RESUBMIT
                reason = "submission may have occurred"
            else:
                action = RecoveryAction.MANUAL_REVIEW
                reason = "unknown state"
            output.append(
                RecoveryDecision(
                    attempt,
                    action,
                    attempt.reservation_state is ReservationState.ACTIVE,
                    reason,
                )
            )
        return tuple(output)

    def claim_outbox(
        self,
        *,
        topic: str,
        owner_id: str,
        limit: int = 100,
        lease_ns: int = 30_000_000_000,
    ) -> tuple[OutboxItem, ...]:
        if limit < 1 or lease_ns <= 0:
            raise ValueError("positive limit and lease required")
        now = self.clock_ns()
        lease = self.acquire_lease(
            f"outbox:{topic}",
            owner_id=owner_id,
            ttl_ns=lease_ns,
        )
        claimed_until = now + lease_ns
        output = []
        with self.db:
            rows = self.db.execute(
                "SELECT * FROM durable_outbox WHERE topic=? "
                "AND status='pending' AND available_at_ns<=? AND "
                "(claimed_until_ns IS NULL OR claimed_until_ns<=?) "
                "ORDER BY outbox_id LIMIT ?",
                (topic, now, now, limit),
            ).fetchall()
            for row in rows:
                cur = self.db.execute(
                    "UPDATE durable_outbox SET owner_id=?,fencing_token=?,"
                    "claimed_until_ns=?,attempt_count=attempt_count+1 "
                    "WHERE outbox_id=? AND status='pending' AND "
                    "(claimed_until_ns IS NULL OR claimed_until_ns<=?)",
                    (
                        owner_id,
                        lease.fencing_token,
                        claimed_until,
                        row["outbox_id"],
                        now,
                    ),
                )
                if cur.rowcount:
                    output.append(
                        OutboxItem(
                            int(row["outbox_id"]),
                            str(row["event_id"]),
                            str(row["attempt_id"]),
                            str(row["topic"]),
                            json.loads(str(row["payload_json"])),
                            lease.fencing_token,
                        )
                    )
        return tuple(output)

    def complete_outbox(
        self,
        item: OutboxItem,
        *,
        owner_id: str,
    ) -> bool:
        with self.db:
            cur = self.db.execute(
                "UPDATE durable_outbox SET status='completed',"
                "completed_at_ns=?,claimed_until_ns=NULL WHERE outbox_id=? "
                "AND status='pending' AND owner_id=? AND fencing_token=?",
                (
                    self.clock_ns(),
                    item.outbox_id,
                    owner_id,
                    item.fencing_token,
                ),
            )
            return cur.rowcount == 1

    def record_retention_eligibility(self, *, cutoff_ns: int) -> int:
        with self.db:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO retention_ledger(target_type,target_id,"
                "action,cutoff_ns,created_at_ns) SELECT 'attempt',attempt_id,"
                "'archive_terminal',?,? FROM durable_attempts WHERE "
                "terminal_at_ns IS NOT NULL AND terminal_at_ns<?",
                (cutoff_ns, self.clock_ns(), cutoff_ns),
            )
            return cur.rowcount

    def purge_completed_outbox(self, *, cutoff_ns: int) -> int:
        now = self.clock_ns()
        with self.db:
            rows = self.db.execute(
                "SELECT outbox_id FROM durable_outbox WHERE "
                "status='completed' AND completed_at_ns<?",
                (cutoff_ns,),
            ).fetchall()
            for row in rows:
                self.db.execute(
                    "INSERT OR IGNORE INTO retention_ledger("
                    "target_type,target_id,action,cutoff_ns,created_at_ns) "
                    "VALUES('outbox',?,'purge_completed',?,?)",
                    (str(row["outbox_id"]), cutoff_ns, now),
                )
            cur = self.db.execute(
                "DELETE FROM durable_outbox WHERE status='completed' "
                "AND completed_at_ns<?",
                (cutoff_ns,),
            )
            return cur.rowcount

    def integrity_check(self) -> None:
        check = self.db.execute("PRAGMA quick_check").fetchone()
        if not check or str(check[0]).lower() != "ok":
            raise CorruptJournalError(
                f"sqlite quick_check failed: {check}"
            )
        if self.db.execute("PRAGMA foreign_key_check").fetchall():
            raise CorruptJournalError("sqlite foreign key check failed")
        for attempt in self.db.execute(
            "SELECT attempt_id FROM durable_attempts ORDER BY attempt_id"
        ):
            previous = ZERO_HASH
            sequence = 0
            rows = self.db.execute(
                "SELECT * FROM durable_events WHERE attempt_id=? "
                "ORDER BY sequence_no",
                (attempt["attempt_id"],),
            ).fetchall()
            for row in rows:
                if int(row["sequence_no"]) != sequence:
                    raise CorruptJournalError("audit sequence gap")
                expected = self._chain(
                    previous,
                    str(row["attempt_id"]),
                    sequence,
                    str(row["event_type"]),
                    row["from_state"],
                    str(row["to_state"]),
                    row["reason_code"],
                    str(row["payload_digest"]),
                    int(row["created_at_ns"]),
                )
                if (
                    row["previous_chain_hash"] != previous
                    or row["chain_hash"] != expected
                ):
                    raise CorruptJournalError("audit chain mismatch")
                previous = expected
                sequence += 1

    def backup_to(self, destination: str | Path) -> BackupManifest:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.integrity_check()
        target = sqlite3.connect(str(path))
        try:
            self.db.backup(target)
        finally:
            target.close()
        raw = path.read_bytes()
        return BackupManifest(
            SCHEMA_NAME,
            MIGRATION_VERSION,
            str(path),
            hashlib.sha256(raw).hexdigest(),
            len(raw),
            self.clock_ns(),
        )

    @classmethod
    def restore_from(
        cls,
        backup_path: str | Path,
        destination_path: str | Path,
        *,
        expected_sha256: str | None = None,
    ) -> "DurableLifecycleStore":
        source = Path(backup_path)
        destination = Path(destination_path)
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if expected_sha256 and actual != expected_sha256:
            raise CorruptJournalError("backup checksum mismatch")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        try:
            store = cls(destination)
            store.integrity_check()
            return store
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def rollback_empty_schema(self) -> None:
        if any(self.count_rows(table) for table in self.TABLES):
            raise DurableLifecycleError(
                "populated durable schema requires backup restore, not rollback"
            )
        with self.db:
            self.db.executescript(
                """
                DROP TRIGGER IF EXISTS durable_events_no_update;
                DROP TRIGGER IF EXISTS durable_events_no_delete;
                DROP TABLE IF EXISTS retention_ledger;
                DROP TABLE IF EXISTS durable_leases;
                DROP TABLE IF EXISTS durable_outbox;
                DROP TABLE IF EXISTS durable_events;
                DROP TABLE IF EXISTS durable_reservations;
                DROP TABLE IF EXISTS durable_attempts;
                DELETE FROM lifecycle_migrations WHERE version=41;
                PRAGMA user_version=0;
                """
            )

    def count_rows(self, table: str) -> int:
        if table not in self.TABLES:
            raise ValueError("unsupported table")
        return int(
            self.db.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        )

    def events_for(
        self,
        attempt_id: str,
    ) -> tuple[Mapping[str, object], ...]:
        rows = self.db.execute(
            "SELECT * FROM durable_events WHERE attempt_id=? "
            "ORDER BY sequence_no",
            (attempt_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)
