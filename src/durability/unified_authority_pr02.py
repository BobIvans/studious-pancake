"""Roadmap PR-02 unified lifecycle, handoff, terminal, and outbox authority.

This module extends the public PR-041/PR-182 lifecycle SQLite database.  It does
not create a second lifecycle database.  Provider admission, cycle intent,
reservation terminalization, lifecycle transition, terminal evidence, and the
canonical PR-02 outbox are committed through one connection and one transaction.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Protocol

from src.database_schema_authority_pr195 import (
    DatabaseProductSpec,
    DatabaseSchemaAuthority,
    DatabaseSchemaAuthorityError,
    canonical_schema_manifest,
)
from src.durability.trusted_time_store import ClockSafeDurableLifecycleStore
from src.execution.models import ExecutionState
from src.time_authority import (
    SystemTimeAuthority,
    TimeAuthority,
    TimeSnapshot,
    TimeSourceStatus,
)

PR02_SCHEMA_VERSION = "roadmap-pr02.unified-lifecycle-authority.v1"
PR02_PRODUCT_ID = "studious-pancake.unified-paper-lifecycle"
PR02_APPLICATION_SCHEMA_VERSION = 2
PR02_DATABASE_EPOCH = 2
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pr02_intents(
 intent_id TEXT PRIMARY KEY,
 intent_kind TEXT NOT NULL,
 source_identity TEXT NOT NULL,
 run_id TEXT,
 sequence INTEGER,
 attempt_id TEXT,
 attempt_generation INTEGER,
 provider_evidence_hash TEXT,
 release_digest TEXT NOT NULL,
 policy_bundle_hash TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 payload_hash TEXT NOT NULL,
 status TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 fencing_token INTEGER NOT NULL CHECK(fencing_token>=1),
 boot_id TEXT NOT NULL,
 process_generation INTEGER NOT NULL CHECK(process_generation>=1),
 issued_utc_ns INTEGER NOT NULL,
 expires_utc_ns INTEGER NOT NULL,
 issued_monotonic_ns INTEGER NOT NULL,
 expires_monotonic_ns INTEGER NOT NULL,
 terminal_id TEXT,
 created_utc_ns INTEGER NOT NULL,
 updated_utc_ns INTEGER NOT NULL,
 UNIQUE(intent_kind, source_identity, release_digest, policy_bundle_hash),
 CHECK(expires_utc_ns>issued_utc_ns),
 CHECK(expires_monotonic_ns>issued_monotonic_ns));
CREATE TABLE IF NOT EXISTS pr02_terminal_records(
 terminal_id TEXT PRIMARY KEY,
 intent_id TEXT NOT NULL UNIQUE
  REFERENCES pr02_intents(intent_id) ON DELETE RESTRICT,
 attempt_id TEXT,
 attempt_generation INTEGER,
 outcome TEXT NOT NULL,
 reason_code TEXT NOT NULL,
 report_hash TEXT NOT NULL,
 lifecycle_event_id TEXT,
 reservation_id TEXT,
 reservation_terminal_state TEXT,
 release_digest TEXT NOT NULL,
 policy_bundle_hash TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 payload_hash TEXT NOT NULL,
 committed_utc_ns INTEGER NOT NULL,
 UNIQUE(attempt_id, attempt_generation));
CREATE TABLE IF NOT EXISTS pr02_outbox_event(
 event_id TEXT PRIMARY KEY,
 intent_id TEXT NOT NULL UNIQUE
  REFERENCES pr02_intents(intent_id) ON DELETE RESTRICT,
 topic TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 payload_hash TEXT NOT NULL,
 created_utc_ns INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS pr02_outbox_delivery(
 event_id TEXT PRIMARY KEY
  REFERENCES pr02_outbox_event(event_id) ON DELETE RESTRICT,
 status TEXT NOT NULL,
 owner_id TEXT,
 fencing_token INTEGER,
 boot_id TEXT,
 process_generation INTEGER,
 claimed_until_utc_ns INTEGER,
 claimed_until_monotonic_ns INTEGER,
 attempt_count INTEGER NOT NULL DEFAULT 0,
 acknowledged_utc_ns INTEGER,
 last_reason TEXT);
CREATE TABLE IF NOT EXISTS pr02_outbox_attempt(
 attempt_no INTEGER PRIMARY KEY,
 event_id TEXT NOT NULL
  REFERENCES pr02_outbox_event(event_id) ON DELETE RESTRICT,
 owner_id TEXT NOT NULL,
 fencing_token INTEGER NOT NULL,
 boot_id TEXT NOT NULL,
 process_generation INTEGER NOT NULL,
 result TEXT NOT NULL,
 reason_code TEXT NOT NULL,
 observed_utc_ns INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS pr02_dead_letter_history(
 dead_letter_id TEXT PRIMARY KEY,
 intent_id TEXT NOT NULL
  REFERENCES pr02_intents(intent_id) ON DELETE RESTRICT,
 reason_code TEXT NOT NULL,
 evidence_hash TEXT,
 attempt_count INTEGER NOT NULL CHECK(attempt_count>=1),
 owner_id TEXT NOT NULL,
 fencing_token INTEGER NOT NULL,
 boot_id TEXT NOT NULL,
 process_generation INTEGER NOT NULL,
 created_utc_ns INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS a3_paper_service_cycles(
 cycle_id TEXT PRIMARY KEY,
 run_id TEXT NOT NULL,
 sequence INTEGER NOT NULL CHECK(sequence>=1),
 schema_version TEXT NOT NULL,
 status TEXT NOT NULL,
 terminal_reason TEXT NOT NULL,
 ready_for_next_cycle INTEGER NOT NULL CHECK(ready_for_next_cycle IN (0,1)),
 provider_evidence_hash TEXT NOT NULL,
 report_hash TEXT NOT NULL,
 source_surface TEXT NOT NULL,
 owner_id TEXT NOT NULL,
 fencing_token INTEGER NOT NULL CHECK(fencing_token>=1),
 lease_expires_at_ns INTEGER NOT NULL,
 started_at_ns INTEGER NOT NULL,
 completed_at_ns INTEGER NOT NULL,
 sender_imported INTEGER NOT NULL CHECK(sender_imported IN (0,1)),
 submission_allowed INTEGER NOT NULL CHECK(submission_allowed IN (0,1)),
 live_enabled INTEGER NOT NULL CHECK(live_enabled IN (0,1)),
 report_json TEXT NOT NULL,
 UNIQUE(run_id, sequence));
CREATE TABLE IF NOT EXISTS a3_paper_service_outbox(
 outbox_id INTEGER PRIMARY KEY,
 cycle_id TEXT NOT NULL UNIQUE
  REFERENCES a3_paper_service_cycles(cycle_id) ON DELETE RESTRICT,
 topic TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',
 owner_id TEXT NOT NULL,
 fencing_token INTEGER NOT NULL CHECK(fencing_token>=1),
 created_at_ns INTEGER NOT NULL,
 completed_at_ns INTEGER);
CREATE TRIGGER IF NOT EXISTS pr02_terminal_no_update
 BEFORE UPDATE ON pr02_terminal_records
 BEGIN SELECT RAISE(ABORT,'PR02_TERMINAL_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS pr02_terminal_no_delete
 BEFORE DELETE ON pr02_terminal_records
 BEGIN SELECT RAISE(ABORT,'PR02_TERMINAL_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS pr02_outbox_event_no_update
 BEFORE UPDATE ON pr02_outbox_event
 BEGIN SELECT RAISE(ABORT,'PR02_OUTBOX_EVENT_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS pr02_outbox_event_no_delete
 BEFORE DELETE ON pr02_outbox_event
 BEGIN SELECT RAISE(ABORT,'PR02_OUTBOX_EVENT_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS pr02_dead_letter_no_update
 BEFORE UPDATE ON pr02_dead_letter_history
 BEGIN SELECT RAISE(ABORT,'PR02_DEAD_LETTER_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS pr02_dead_letter_no_delete
 BEFORE DELETE ON pr02_dead_letter_history
 BEGIN SELECT RAISE(ABORT,'PR02_DEAD_LETTER_IMMUTABLE'); END;
"""


class UnifiedAuthorityError(RuntimeError):
    """A PR-02 identity, ownership, or atomicity invariant failed."""


class IntentKind(StrEnum):
    PROVIDER_HANDOFF = "provider_handoff"
    PAPER_CYCLE = "paper_cycle"
    PAPER_ATTEMPT = "paper_attempt"


class IntentStatus(StrEnum):
    RECORDED = "recorded"
    EVIDENCE_BOUND = "evidence_bound"
    TERMINAL = "terminal"
    INDETERMINATE = "indeterminate"
    DEAD_LETTER = "dead_letter"


class ReservationTerminalState(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    CONSUMED = "consumed"
    RELEASED = "released"
    FROZEN = "active"


@dataclass(frozen=True, slots=True)
class AuthorityFence:
    intent_id: str
    owner_id: str
    fencing_token: int
    boot_id: str
    process_generation: int
    release_digest: str
    policy_bundle_hash: str
    expires_utc_ns: int
    expires_monotonic_ns: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class TerminalCommit:
    terminal_id: str
    intent_id: str
    outcome: str
    report_hash: str
    outbox_event_id: str
    lifecycle_event_id: str | None
    replayed: bool


class VerifiedProviderEventLike(Protocol):
    event_identity: str
    provider_evidence_hash: str
    release_digest: str
    policy_bundle_hash: str
    evidence_hash: str
    expires_at_monotonic_ns: int


class UnifiedLifecycleAuthority:
    """One versioned SQLite authority for PR-02 paper lifecycle effects."""

    def __init__(
        self,
        path: str | Path,
        *,
        release_digest: str,
        policy_bundle_hash: str,
        time_authority: TimeAuthority | None = None,
        owner_id: str = "pr02-unified-authority",
        lease_ttl_ns: int = 30_000_000_000,
        environment: str = "paper",
        cluster_genesis: str = "mainnet-beta",
    ) -> None:
        _digest(release_digest, "release_digest")
        _digest(policy_bundle_hash, "policy_bundle_hash")
        if not owner_id.strip() or lease_ttl_ns <= 0:
            raise ValueError("owner_id and positive lease_ttl_ns are required")
        if not environment.strip() or not cluster_genesis.strip():
            raise ValueError("environment and cluster_genesis are required")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.release_digest = release_digest
        self.policy_bundle_hash = policy_bundle_hash
        self.owner_id = owner_id
        self.lease_ttl_ns = lease_ttl_ns
        self.environment = environment
        self.cluster_genesis = cluster_genesis
        self.time_authority = time_authority or SystemTimeAuthority()
        self.lifecycle = ClockSafeDurableLifecycleStore(
            self.path,
            time_authority=self.time_authority,
        )
        self.db = self.lifecycle.db
        self.db.row_factory = sqlite3.Row
        with self.db:
            DatabaseSchemaAuthority.install_authority_schema(self.db)
            self.db.executescript(_SCHEMA)
            self._install_or_verify_identity()

    def __enter__(self) -> "UnifiedLifecycleAuthority":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.lifecycle.close()

    def _snapshot(self) -> TimeSnapshot:
        snapshot = self.time_authority.snapshot()
        if snapshot.time_source_status is TimeSourceStatus.ANOMALOUS:
            raise UnifiedAuthorityError("PR02_TRUSTED_TIME_ANOMALOUS")
        return snapshot

    def _install_or_verify_identity(self) -> None:
        manifest = canonical_schema_manifest(self.db)
        legacy_digest = self._legacy_migrations_digest()
        authority = DatabaseSchemaAuthority(
            DatabaseProductSpec(
                product_id=PR02_PRODUCT_ID,
                schema_family=PR02_SCHEMA_VERSION,
                application_schema_version=PR02_APPLICATION_SCHEMA_VERSION,
                current_epoch=PR02_DATABASE_EPOCH,
                reader_min_epoch=PR02_DATABASE_EPOCH,
                reader_max_epoch=PR02_DATABASE_EPOCH,
                writer_min_epoch=PR02_DATABASE_EPOCH,
                writer_max_epoch=PR02_DATABASE_EPOCH,
                expected_schema_manifest_sha256=manifest.sha256,
            ),
            now_utc_ns=lambda: self._snapshot().utc_ns,
        )
        try:
            fence = authority.acquire_fence(
                self.db,
                owner_id=f"{self.owner_id}:migration",
                expected_epoch=PR02_DATABASE_EPOCH,
            )
            identity = authority.bootstrap_identity(
                self.db,
                environment=self.environment,
                cluster_genesis=self.cluster_genesis,
                release_id=self.release_digest,
                legacy_migrations_sha256=legacy_digest,
            )
            authority.append_migration(
                self.db,
                migration_id=PR02_SCHEMA_VERSION,
                from_epoch=0,
                to_epoch=PR02_DATABASE_EPOCH,
                script_sha256=hashlib.sha256(_SCHEMA.encode()).hexdigest(),
                applied_schema_sha256=manifest.sha256,
                release_id=self.release_digest,
                fence=fence,
            )
            authority.release_fence(self.db, fence)
            authority.verify_runtime(
                self.db,
                environment=self.environment,
                cluster_genesis=self.cluster_genesis,
                legacy_migrations_sha256=legacy_digest,
            )
        except DatabaseSchemaAuthorityError as exc:
            raise UnifiedAuthorityError(str(exc)) from exc
        if identity.product_id != PR02_PRODUCT_ID:
            raise UnifiedAuthorityError("PR02_FOREIGN_DATABASE_PRODUCT")

    def _legacy_migrations_digest(self) -> str:
        rows = self.db.execute(
            "SELECT version,schema_name,checksum FROM lifecycle_migrations "
            "ORDER BY version"
        ).fetchall()
        return _hash_json(tuple(tuple(row) for row in rows))

    @staticmethod
    def assert_connection_is_authority(connection: sqlite3.Connection) -> None:
        try:
            row = connection.execute(
                "SELECT product_id,schema_family,application_schema_version "
                "FROM database_identity_pr195 WHERE singleton=1"
            ).fetchone()
        except sqlite3.Error as exc:
            raise UnifiedAuthorityError("PR02_AUTHORITY_METADATA_MISSING") from exc
        expected = (
            PR02_PRODUCT_ID,
            PR02_SCHEMA_VERSION,
            PR02_APPLICATION_SCHEMA_VERSION,
        )
        if row is None or tuple(row) != expected:
            raise UnifiedAuthorityError("PR02_FOREIGN_TRANSACTION_CONNECTION")

    def next_cycle_sequence(self, run_id: str) -> int:
        if not run_id.strip():
            raise ValueError("run_id is required")
        row = self.db.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM pr02_intents "
            "WHERE intent_kind=? AND run_id=?",
            (IntentKind.PAPER_CYCLE.value, run_id),
        ).fetchone()
        return int(row[0])

    def begin_cycle_intent(
        self,
        *,
        run_id: str,
        sequence: int,
        config_fingerprint: str,
        source_surface: str,
    ) -> AuthorityFence:
        if sequence < 1 or not run_id.strip() or not source_surface.strip():
            raise ValueError("valid run, sequence, and source surface are required")
        payload = {
            "run_id": run_id,
            "sequence": sequence,
            "config_fingerprint": config_fingerprint,
            "source_surface": source_surface,
        }
        source_identity = _hash_json(payload)
        return self._begin_intent(
            kind=IntentKind.PAPER_CYCLE,
            source_identity=source_identity,
            payload=payload,
            run_id=run_id,
            sequence=sequence,
        )

    def begin_attempt_intent(
        self,
        *,
        attempt_id: str,
        attempt_generation: int,
        request_payload: Mapping[str, object],
    ) -> AuthorityFence:
        _digest(attempt_id, "attempt_id")
        if isinstance(attempt_generation, bool) or attempt_generation < 1:
            raise ValueError("attempt_generation must be positive")
        source_identity = _hash_json(
            {
                "attempt_id": attempt_id,
                "attempt_generation": attempt_generation,
                "request": dict(request_payload),
            }
        )
        return self._begin_intent(
            kind=IntentKind.PAPER_ATTEMPT,
            source_identity=source_identity,
            payload=dict(request_payload),
            attempt_id=attempt_id,
            attempt_generation=attempt_generation,
        )

    def _begin_intent(
        self,
        *,
        kind: IntentKind,
        source_identity: str,
        payload: Mapping[str, object],
        run_id: str | None = None,
        sequence: int | None = None,
        attempt_id: str | None = None,
        attempt_generation: int | None = None,
        provider_evidence_hash: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> AuthorityFence:
        db = connection or self.db
        now = self._snapshot()
        payload_json = _canonical_json(payload)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
        intent_id = _hash_json(
            {
                "schema": PR02_SCHEMA_VERSION,
                "kind": kind.value,
                "source_identity": source_identity,
                "release_digest": self.release_digest,
                "policy_bundle_hash": self.policy_bundle_hash,
            }
        )
        existing = db.execute(
            "SELECT * FROM pr02_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        if existing is not None:
            expected = (
                payload_hash,
                self.release_digest,
                self.policy_bundle_hash,
                kind.value,
            )
            actual = (
                str(existing["payload_hash"]),
                str(existing["release_digest"]),
                str(existing["policy_bundle_hash"]),
                str(existing["intent_kind"]),
            )
            if actual != expected:
                raise UnifiedAuthorityError("PR02_INTENT_IMMUTABILITY_CONFLICT")
            return _fence_from_row(existing, replayed=True)
        db.execute(
            "INSERT INTO pr02_intents("
            "intent_id,intent_kind,source_identity,run_id,sequence,attempt_id,"
            "attempt_generation,provider_evidence_hash,release_digest,"
            "policy_bundle_hash,payload_json,payload_hash,status,owner_id,"
            "fencing_token,boot_id,process_generation,issued_utc_ns,"
            "expires_utc_ns,issued_monotonic_ns,expires_monotonic_ns,terminal_id,"
            "created_utc_ns,updated_utc_ns) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
            "?,?,?,?,?,NULL,?,?)",
            (
                intent_id,
                kind.value,
                source_identity,
                run_id,
                sequence,
                attempt_id,
                attempt_generation,
                provider_evidence_hash,
                self.release_digest,
                self.policy_bundle_hash,
                payload_json,
                payload_hash,
                IntentStatus.RECORDED.value,
                self.owner_id,
                1,
                now.boot_id,
                now.process_generation,
                now.utc_ns,
                now.utc_ns + self.lease_ttl_ns,
                now.monotonic_ns,
                now.monotonic_ns + self.lease_ttl_ns,
                now.utc_ns,
                now.utc_ns,
            ),
        )
        row = db.execute(
            "SELECT * FROM pr02_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        assert row is not None
        return _fence_from_row(row, replayed=False)

    def bind_provider_evidence(
        self,
        fence: AuthorityFence,
        *,
        provider_evidence_hash: str,
    ) -> AuthorityFence:
        _digest(provider_evidence_hash, "provider_evidence_hash")
        now = self._snapshot()
        with self.db:
            row = self._verify_fence(self.db, fence, now)
            current = row["provider_evidence_hash"]
            if current is not None and str(current) != provider_evidence_hash:
                raise UnifiedAuthorityError("PR02_PROVIDER_EVIDENCE_CONFLICT")
            self.db.execute(
                "UPDATE pr02_intents SET provider_evidence_hash=?,status=?,"
                "updated_utc_ns=? WHERE intent_id=?",
                (
                    provider_evidence_hash,
                    IntentStatus.EVIDENCE_BOUND.value,
                    now.utc_ns,
                    fence.intent_id,
                ),
            )
        return fence

    def commit_cycle_terminal(
        self,
        fence: AuthorityFence,
        *,
        outcome: str,
        reason_code: str,
        report_hash: str,
        report_payload: Mapping[str, object],
        provider_evidence_hash: str,
        ready_for_next_cycle: bool,
        source_surface: str,
        sender_imported: bool = False,
        submission_allowed: bool = False,
        live_enabled: bool = False,
    ) -> TerminalCommit:
        if sender_imported or submission_allowed or live_enabled:
            outcome = "INDETERMINATE"
            reason_code = "PR02_UNSAFE_EXECUTION_SURFACE_REJECTED"
            ready_for_next_cycle = False
        _digest(report_hash, "report_hash")
        _digest(provider_evidence_hash, "provider_evidence_hash")
        payload = dict(report_payload)
        payload.update(
            {
                "outcome": outcome,
                "reason_code": reason_code,
                "ready_for_next_cycle": ready_for_next_cycle,
                "provider_evidence_hash": provider_evidence_hash,
            }
        )
        now = self._snapshot()
        with self.db:
            row = self._verify_fence(self.db, fence, now)
            if str(row["intent_kind"]) != IntentKind.PAPER_CYCLE.value:
                raise UnifiedAuthorityError("PR02_WRONG_INTENT_KIND")
            bound = row["provider_evidence_hash"]
            if bound is not None and str(bound) != provider_evidence_hash:
                raise UnifiedAuthorityError("PR02_PROVIDER_EVIDENCE_CONFLICT")
            commit = self._insert_terminal_and_outbox(
                self.db,
                row=row,
                outcome=outcome,
                reason_code=reason_code,
                report_hash=report_hash,
                payload=payload,
                now=now,
                lifecycle_event_id=None,
                reservation_id=None,
                reservation_state=ReservationTerminalState.NOT_APPLICABLE,
                topic="paper.service.cycle_recorded",
            )
            self._write_a3_projection(
                self.db,
                row=row,
                outcome=outcome,
                reason_code=reason_code,
                report_hash=report_hash,
                payload=payload,
                provider_evidence_hash=provider_evidence_hash,
                ready_for_next_cycle=ready_for_next_cycle,
                source_surface=source_surface,
                sender_imported=sender_imported,
                submission_allowed=submission_allowed,
                live_enabled=live_enabled,
                now=now,
            )
            return commit

    def commit_attempt_terminal(
        self,
        fence: AuthorityFence,
        *,
        target_state: ExecutionState,
        reservation_terminal_state: ReservationTerminalState,
        outcome: str,
        reason_code: str,
        report_hash: str,
        report_payload: Mapping[str, object],
    ) -> TerminalCommit:
        _digest(report_hash, "report_hash")
        now = self._snapshot()
        with self.db:
            row = self._verify_fence(self.db, fence, now)
            if str(row["intent_kind"]) != IntentKind.PAPER_ATTEMPT.value:
                raise UnifiedAuthorityError("PR02_WRONG_INTENT_KIND")
            attempt_id = str(row["attempt_id"] or "")
            generation = int(row["attempt_generation"] or 0)
            attempt = self.db.execute(
                "SELECT * FROM durable_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if attempt is None or int(attempt["generation"]) != generation:
                raise UnifiedAuthorityError("PR02_ATTEMPT_IDENTITY_MISMATCH")
            existing_terminal = self.db.execute(
                "SELECT * FROM pr02_terminal_records WHERE intent_id=?",
                (row["intent_id"],),
            ).fetchone()
            if existing_terminal is not None:
                return self._insert_terminal_and_outbox(
                    self.db,
                    row=row,
                    outcome=outcome,
                    reason_code=reason_code,
                    report_hash=report_hash,
                    payload=dict(report_payload),
                    now=now,
                    lifecycle_event_id=existing_terminal["lifecycle_event_id"],
                    reservation_id=existing_terminal["reservation_id"],
                    reservation_state=ReservationTerminalState(
                        str(existing_terminal["reservation_terminal_state"])
                    ),
                    topic="paper.attempt.terminal",
                )
            current = ExecutionState(str(attempt["state"]))
            self.lifecycle.machine.transition(current, target_state)
            revision = int(attempt["revision"])
            lifecycle_event_id = self.lifecycle._event(
                attempt_id=attempt_id,
                sequence=revision + 1,
                idempotency_key=f"pr02-terminal:{fence.intent_id}",
                event_type="pr02_terminal_committed",
                from_state=current,
                to_state=target_state,
                reason=reason_code,
                payload={
                    "report_hash": report_hash,
                    "outcome": outcome,
                    "release_digest": self.release_digest,
                    "policy_bundle_hash": self.policy_bundle_hash,
                },
                topic=None,
                now=now.utc_ns,
            )
            updated = self.db.execute(
                "UPDATE durable_attempts SET state=?,revision=?,terminal_at_ns=?,"
                "updated_at_ns=? WHERE attempt_id=? AND revision=?",
                (
                    target_state.value,
                    revision + 1,
                    now.utc_ns,
                    now.utc_ns,
                    attempt_id,
                    revision,
                ),
            )
            if updated.rowcount != 1:
                raise UnifiedAuthorityError("PR02_ATTEMPT_REVISION_CONFLICT")
            reservation_id = attempt["reservation_id"]
            if reservation_id is not None:
                self._terminalize_reservation(
                    self.db,
                    attempt_id=attempt_id,
                    reservation_id=str(reservation_id),
                    state=reservation_terminal_state,
                    reason_code=reason_code,
                    now_utc_ns=now.utc_ns,
                )
            return self._insert_terminal_and_outbox(
                self.db,
                row=row,
                outcome=outcome,
                reason_code=reason_code,
                report_hash=report_hash,
                payload=dict(report_payload),
                now=now,
                lifecycle_event_id=lifecycle_event_id,
                reservation_id=(
                    None if reservation_id is None else str(reservation_id)
                ),
                reservation_state=reservation_terminal_state,
                topic="paper.attempt.terminal",
            )

    def _terminalize_reservation(
        self,
        db: sqlite3.Connection,
        *,
        attempt_id: str,
        reservation_id: str,
        state: ReservationTerminalState,
        reason_code: str,
        now_utc_ns: int,
    ) -> None:
        if state is ReservationTerminalState.NOT_APPLICABLE:
            raise UnifiedAuthorityError("PR02_RESERVATION_STATE_REQUIRED")
        current = db.execute(
            "SELECT state FROM durable_reservations WHERE reservation_id=? "
            "AND attempt_id=?",
            (reservation_id, attempt_id),
        ).fetchone()
        if current is None or str(current["state"]) != "active":
            raise UnifiedAuthorityError("PR02_RESERVATION_NOT_ACTIVE")
        if state is ReservationTerminalState.FROZEN:
            return
        db.execute(
            "UPDATE durable_reservations SET state=?,release_reason=?,updated_at_ns=? "
            "WHERE reservation_id=? AND attempt_id=? AND state='active'",
            (state.value, reason_code, now_utc_ns, reservation_id, attempt_id),
        )
        db.execute(
            "UPDATE durable_attempts SET reservation_state=?,updated_at_ns=? "
            "WHERE attempt_id=?",
            (state.value, now_utc_ns, attempt_id),
        )

    def _insert_terminal_and_outbox(
        self,
        db: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        outcome: str,
        reason_code: str,
        report_hash: str,
        payload: Mapping[str, object],
        now: TimeSnapshot,
        lifecycle_event_id: str | None,
        reservation_id: str | None,
        reservation_state: ReservationTerminalState,
        topic: str,
    ) -> TerminalCommit:
        payload_json = _canonical_json(payload)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
        terminal_id = _hash_json(
            {
                "intent_id": row["intent_id"],
                "outcome": outcome,
                "report_hash": report_hash,
                "release_digest": self.release_digest,
                "policy_bundle_hash": self.policy_bundle_hash,
            }
        )
        event_id = _hash_json({"terminal_id": terminal_id, "topic": topic})
        existing = db.execute(
            "SELECT * FROM pr02_terminal_records WHERE intent_id=?",
            (row["intent_id"],),
        ).fetchone()
        if existing is not None:
            expected = (terminal_id, outcome, report_hash, payload_hash)
            actual = (
                str(existing["terminal_id"]),
                str(existing["outcome"]),
                str(existing["report_hash"]),
                str(existing["payload_hash"]),
            )
            if actual != expected:
                raise UnifiedAuthorityError("PR02_TERMINAL_IMMUTABILITY_CONFLICT")
            return TerminalCommit(
                terminal_id,
                str(row["intent_id"]),
                outcome,
                report_hash,
                event_id,
                existing["lifecycle_event_id"],
                True,
            )
        db.execute(
            "INSERT INTO pr02_terminal_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                terminal_id,
                row["intent_id"],
                row["attempt_id"],
                row["attempt_generation"],
                outcome,
                reason_code,
                report_hash,
                lifecycle_event_id,
                reservation_id,
                reservation_state.value,
                self.release_digest,
                self.policy_bundle_hash,
                payload_json,
                payload_hash,
                now.utc_ns,
            ),
        )
        outbox_payload = _canonical_json(
            {
                "terminal_id": terminal_id,
                "intent_id": row["intent_id"],
                "outcome": outcome,
                "reason_code": reason_code,
                "report_hash": report_hash,
                "payload_hash": payload_hash,
                "release_digest": self.release_digest,
                "policy_bundle_hash": self.policy_bundle_hash,
            }
        )
        outbox_hash = hashlib.sha256(outbox_payload.encode()).hexdigest()
        db.execute(
            "INSERT INTO pr02_outbox_event VALUES(?,?,?,?,?,?)",
            (
                event_id,
                row["intent_id"],
                topic,
                outbox_payload,
                outbox_hash,
                now.utc_ns,
            ),
        )
        db.execute(
            "INSERT INTO pr02_outbox_delivery(event_id,status) VALUES(?,?)",
            (event_id, "pending"),
        )
        terminal_status = (
            IntentStatus.INDETERMINATE.value
            if outcome == "INDETERMINATE"
            else IntentStatus.TERMINAL.value
        )
        db.execute(
            "UPDATE pr02_intents SET status=?,terminal_id=?,updated_utc_ns=? "
            "WHERE intent_id=?",
            (terminal_status, terminal_id, now.utc_ns, row["intent_id"]),
        )
        return TerminalCommit(
            terminal_id,
            str(row["intent_id"]),
            outcome,
            report_hash,
            event_id,
            lifecycle_event_id,
            False,
        )

    def _write_a3_projection(
        self,
        db: sqlite3.Connection,
        *,
        row: sqlite3.Row,
        outcome: str,
        reason_code: str,
        report_hash: str,
        payload: Mapping[str, object],
        provider_evidence_hash: str,
        ready_for_next_cycle: bool,
        source_surface: str,
        sender_imported: bool,
        submission_allowed: bool,
        live_enabled: bool,
        now: TimeSnapshot,
    ) -> None:
        report_json = _canonical_json(payload)
        db.execute(
            "INSERT OR IGNORE INTO a3_paper_service_cycles VALUES"
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row["source_identity"],
                row["run_id"],
                row["sequence"],
                PR02_SCHEMA_VERSION,
                outcome,
                reason_code,
                int(ready_for_next_cycle),
                provider_evidence_hash,
                report_hash,
                source_surface,
                row["owner_id"],
                row["fencing_token"],
                row["expires_utc_ns"],
                row["issued_utc_ns"],
                now.utc_ns,
                int(sender_imported),
                int(submission_allowed),
                int(live_enabled),
                report_json,
            ),
        )
        db.execute(
            "INSERT OR IGNORE INTO a3_paper_service_outbox("
            "cycle_id,topic,payload_json,owner_id,fencing_token,created_at_ns) "
            "VALUES(?,?,?,?,?,?)",
            (
                row["source_identity"],
                "paper.service.cycle_recorded",
                report_json,
                row["owner_id"],
                row["fencing_token"],
                now.utc_ns,
            ),
        )

    def _verify_fence(
        self,
        db: sqlite3.Connection,
        fence: AuthorityFence,
        now: TimeSnapshot,
    ) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM pr02_intents WHERE intent_id=?", (fence.intent_id,)
        ).fetchone()
        if row is None:
            raise UnifiedAuthorityError("PR02_INTENT_NOT_FOUND")
        valid = (
            str(row["owner_id"]) == fence.owner_id
            and int(row["fencing_token"]) == fence.fencing_token
            and str(row["boot_id"]) == fence.boot_id == now.boot_id
            and int(row["process_generation"])
            == fence.process_generation
            == now.process_generation
            and str(row["release_digest"])
            == fence.release_digest
            == self.release_digest
            and str(row["policy_bundle_hash"])
            == fence.policy_bundle_hash
            == self.policy_bundle_hash
            and now.utc_ns < int(row["expires_utc_ns"])
            and now.monotonic_ns < int(row["expires_monotonic_ns"])
        )
        if not valid:
            raise UnifiedAuthorityError("PR02_OWNER_FENCE_LEASE_OR_POLICY_MISMATCH")
        return row

    def append_dead_letter(
        self,
        fence: AuthorityFence,
        *,
        reason_code: str,
        attempt_count: int,
        evidence_hash: str | None = None,
    ) -> str:
        if attempt_count < 1:
            raise ValueError("attempt_count must be positive")
        if evidence_hash is not None:
            _digest(evidence_hash, "evidence_hash")
        now = self._snapshot()
        with self.db:
            self._verify_fence(self.db, fence, now)
            dead_letter_id = _hash_json(
                {
                    "intent_id": fence.intent_id,
                    "reason_code": reason_code,
                    "attempt_count": attempt_count,
                    "evidence_hash": evidence_hash,
                    "observed_utc_ns": now.utc_ns,
                }
            )
            self.db.execute(
                "INSERT INTO pr02_dead_letter_history VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    dead_letter_id,
                    fence.intent_id,
                    reason_code,
                    evidence_hash,
                    attempt_count,
                    fence.owner_id,
                    fence.fencing_token,
                    fence.boot_id,
                    fence.process_generation,
                    now.utc_ns,
                ),
            )
            self.db.execute(
                "UPDATE pr02_intents SET status=?,updated_utc_ns=? WHERE intent_id=?",
                (IntentStatus.DEAD_LETTER.value, now.utc_ns, fence.intent_id),
            )
            return dead_letter_id

    def recovery_summary(self) -> tuple[dict[str, object], ...]:
        now = self._snapshot()
        rows = self.db.execute(
            "SELECT intent_id,intent_kind,status,owner_id,fencing_token,boot_id,"
            "process_generation,expires_utc_ns,expires_monotonic_ns,terminal_id "
            "FROM pr02_intents ORDER BY created_utc_ns,intent_id"
        ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            same_domain = (
                str(row["boot_id"]) == now.boot_id
                and int(row["process_generation"]) == now.process_generation
            )
            live = same_domain and (
                now.utc_ns < int(row["expires_utc_ns"])
                and now.monotonic_ns < int(row["expires_monotonic_ns"])
            )
            if row["terminal_id"] is not None:
                action = "terminal_exactly_once"
            elif live:
                action = "resume_owned_intent"
            else:
                action = "safe_indeterminacy_reconcile"
            result.append({**dict(row), "recovery_action": action})
        return tuple(result)


class UnifiedA3AdmissionSink:
    """B3 sink that can commit only inside the PR-02 authority connection."""

    def __init__(
        self,
        *,
        time_authority: TimeAuthority,
        owner_id: str = "b3-pr02-admission",
        lease_ttl_ns: int = 30_000_000_000,
    ) -> None:
        self.time_authority = time_authority
        self.owner_id = owner_id
        self.lease_ttl_ns = lease_ttl_ns

    def commit(
        self,
        connection: sqlite3.Connection,
        evidence: VerifiedProviderEventLike,
    ) -> str:
        UnifiedLifecycleAuthority.assert_connection_is_authority(connection)
        snapshot = self.time_authority.snapshot()
        if snapshot.time_source_status is TimeSourceStatus.ANOMALOUS:
            raise UnifiedAuthorityError("PR02_TRUSTED_TIME_ANOMALOUS")
        for name in (
            "event_identity",
            "provider_evidence_hash",
            "release_digest",
            "policy_bundle_hash",
            "evidence_hash",
        ):
            _digest(str(getattr(evidence, name)), name)
        row = connection.execute(
            "SELECT product_id FROM database_identity_pr195 WHERE singleton=1"
        ).fetchone()
        assert row is not None
        payload = {
            "event_identity": evidence.event_identity,
            "provider_evidence_hash": evidence.provider_evidence_hash,
            "evidence_hash": evidence.evidence_hash,
        }
        payload_json = _canonical_json(payload)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
        intent_id = _hash_json(
            {
                "schema": PR02_SCHEMA_VERSION,
                "kind": IntentKind.PROVIDER_HANDOFF.value,
                "source_identity": evidence.event_identity,
                "release_digest": evidence.release_digest,
                "policy_bundle_hash": evidence.policy_bundle_hash,
            }
        )
        existing = connection.execute(
            "SELECT payload_hash FROM pr02_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        if existing is not None:
            if str(existing["payload_hash"]) != payload_hash:
                raise UnifiedAuthorityError("PR02_PROVIDER_HANDOFF_CONFLICT")
            return intent_id
        connection.execute(
            "INSERT INTO pr02_intents("
            "intent_id,intent_kind,source_identity,run_id,sequence,attempt_id,"
            "attempt_generation,provider_evidence_hash,release_digest,"
            "policy_bundle_hash,payload_json,payload_hash,status,owner_id,"
            "fencing_token,boot_id,process_generation,issued_utc_ns,expires_utc_ns,"
            "issued_monotonic_ns,expires_monotonic_ns,terminal_id,created_utc_ns,"
            "updated_utc_ns) VALUES(?,?,?,NULL,NULL,NULL,NULL,?,?,?,?,?,?,?,?,?,?,?,?,"
            "?,?,NULL,?,?)",
            (
                intent_id,
                IntentKind.PROVIDER_HANDOFF.value,
                evidence.event_identity,
                evidence.provider_evidence_hash,
                evidence.release_digest,
                evidence.policy_bundle_hash,
                payload_json,
                payload_hash,
                IntentStatus.EVIDENCE_BOUND.value,
                self.owner_id,
                1,
                snapshot.boot_id,
                snapshot.process_generation,
                snapshot.utc_ns,
                snapshot.utc_ns + self.lease_ttl_ns,
                snapshot.monotonic_ns,
                snapshot.monotonic_ns + self.lease_ttl_ns,
                snapshot.utc_ns,
                snapshot.utc_ns,
            ),
        )
        return intent_id


def _fence_from_row(row: sqlite3.Row, *, replayed: bool) -> AuthorityFence:
    return AuthorityFence(
        intent_id=str(row["intent_id"]),
        owner_id=str(row["owner_id"]),
        fencing_token=int(row["fencing_token"]),
        boot_id=str(row["boot_id"]),
        process_generation=int(row["process_generation"]),
        release_digest=str(row["release_digest"]),
        policy_bundle_hash=str(row["policy_bundle_hash"]),
        expires_utc_ns=int(row["expires_utc_ns"]),
        expires_monotonic_ns=int(row["expires_monotonic_ns"]),
        replayed=replayed,
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _digest(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be lowercase sha256")


__all__ = [
    "AuthorityFence",
    "IntentKind",
    "IntentStatus",
    "PR02_APPLICATION_SCHEMA_VERSION",
    "PR02_DATABASE_EPOCH",
    "PR02_PRODUCT_ID",
    "PR02_SCHEMA_VERSION",
    "ReservationTerminalState",
    "TerminalCommit",
    "UnifiedA3AdmissionSink",
    "UnifiedAuthorityError",
    "UnifiedLifecycleAuthority",
]
