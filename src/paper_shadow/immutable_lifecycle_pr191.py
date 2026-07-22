"""PR-191 append-only lifecycle and split outbox authority.

This module performs an explicit compatibility cutover for the PR-150 lifecycle
store.  The legacy schema remains readable, while all new writes use immutable
transition/outbox-event rows and consumer-owned delivery rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any

_legacy = importlib.import_module("src.paper_shadow.structured_runtime")
_ORIGINAL_STORE = _legacy.SQLitePaperLifecycleStore

PR191_LIFECYCLE_SCHEMA = "pr191.immutable-lifecycle-outbox.v1"


class LifecycleImmutabilityConflict(RuntimeError):
    """A replay reused an immutable identity with different semantic content."""


class OutboxDeliveryState(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    FAILED_RETRYABLE = "failed-retryable"
    DEAD_LETTER = "dead-letter"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class TransitionCommitResult:
    transition_id: str
    outbox_id: str
    payload_hash: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class OutboxLease:
    outbox_id: str
    owner: str
    fencing_token: int
    lease_expires_at_unix_ms: int
    attempt_count: int


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _transition_payload(transition: Any) -> dict[str, Any]:
    return {
        "schema_version": transition.schema_version,
        "transition_id": transition.transition_id,
        "attempt_id": transition.attempt_id,
        "run_id": transition.run_id,
        "cycle": transition.cycle,
        "state": transition.state.value,
        "terminal_reason": transition.terminal_reason,
        "candidates_seen": transition.candidates_seen,
        "events_written": transition.events_written,
        "ready_for_next_cycle": bool(transition.ready_for_next_cycle),
        "dependency_reasons": list(transition.dependency_reasons),
        "details": dict(transition.details),
        "created_at_unix_ms": transition.created_at_unix_ms,
    }


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": row["schema_version"],
        "transition_id": row["transition_id"],
        "attempt_id": row["attempt_id"],
        "run_id": row["run_id"],
        "cycle": row["cycle"],
        "state": row["state"],
        "terminal_reason": row["terminal_reason"],
        "candidates_seen": row["candidates_seen"],
        "events_written": row["events_written"],
        "ready_for_next_cycle": bool(row["ready_for_next_cycle"]),
        "dependency_reasons": json.loads(row["dependency_reasons_json"]),
        "details": json.loads(row["details_json"]),
        "created_at_unix_ms": row["created_at_unix_ms"],
    }


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


class ImmutableSQLitePaperLifecycleStore(_ORIGINAL_STORE):
    """Append-only PR-191 replacement for the public PR-150 store."""

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def migrate(self) -> None:
        super().migrate()
        with self._connect() as conn:
            transition_columns = _column_names(conn, "paper_lifecycle_transition")
            if "payload_hash" not in transition_columns:
                conn.execute(
                    "ALTER TABLE paper_lifecycle_transition ADD COLUMN payload_hash TEXT"
                )

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_lifecycle_outbox_event (
                    outbox_id TEXT PRIMARY KEY,
                    transition_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    cycle INTEGER NOT NULL CHECK(cycle > 0),
                    kind TEXT NOT NULL,
                    payload_hash TEXT NOT NULL CHECK(length(payload_hash) = 64),
                    created_at_unix_ms INTEGER NOT NULL,
                    schema_version TEXT NOT NULL,
                    FOREIGN KEY(transition_id)
                        REFERENCES paper_lifecycle_transition(transition_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS paper_lifecycle_outbox_delivery (
                    outbox_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL CHECK(state IN (
                        'pending','leased','sent','acknowledged',
                        'failed-retryable','dead-letter','superseded'
                    )),
                    owner TEXT,
                    fencing_token INTEGER NOT NULL DEFAULT 0 CHECK(fencing_token >= 0),
                    lease_expires_at_unix_ms INTEGER,
                    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
                    next_retry_at_unix_ms INTEGER,
                    last_error_code TEXT,
                    acknowledged_at_unix_ms INTEGER,
                    updated_at_unix_ms INTEGER NOT NULL,
                    FOREIGN KEY(outbox_id)
                        REFERENCES paper_lifecycle_outbox_event(outbox_id)
                        ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS paper_lifecycle_outbox_attempt (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    outbox_id TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    result_state TEXT NOT NULL,
                    error_code TEXT,
                    created_at_unix_ms INTEGER NOT NULL,
                    FOREIGN KEY(outbox_id)
                        REFERENCES paper_lifecycle_outbox_event(outbox_id)
                        ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_pr191_delivery_state_retry
                ON paper_lifecycle_outbox_delivery(state, next_retry_at_unix_ms);
                """
            )
            self._backfill_transition_hashes(conn)
            self._backfill_outbox_split(conn)

    def _backfill_transition_hashes(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT * FROM paper_lifecycle_transition WHERE payload_hash IS NULL"
        ).fetchall()
        for row in rows:
            payload_hash = _sha256_text(_canonical_json(_row_payload(row)))
            conn.execute(
                "UPDATE paper_lifecycle_transition SET payload_hash=? "
                "WHERE transition_id=? AND payload_hash IS NULL",
                (payload_hash, row["transition_id"]),
            )

    def _backfill_outbox_split(self, conn: sqlite3.Connection) -> None:
        legacy_rows = conn.execute(
            """
            SELECT o.*, t.payload_hash, t.schema_version
            FROM paper_lifecycle_outbox AS o
            JOIN paper_lifecycle_transition AS t
              ON t.transition_id = o.transition_id
            """
        ).fetchall()
        now_ms = int(time.time() * 1000)
        for row in legacy_rows:
            conn.execute(
                """
                INSERT INTO paper_lifecycle_outbox_event(
                    outbox_id,transition_id,run_id,cycle,kind,payload_hash,
                    created_at_unix_ms,schema_version
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(outbox_id) DO NOTHING
                """,
                (
                    row["outbox_id"],
                    row["transition_id"],
                    row["run_id"],
                    row["cycle"],
                    row["kind"],
                    row["payload_hash"],
                    row["created_at_unix_ms"],
                    row["schema_version"],
                ),
            )
            state = (
                OutboxDeliveryState.ACKNOWLEDGED.value
                if bool(row["delivered"])
                else OutboxDeliveryState.PENDING.value
            )
            conn.execute(
                """
                INSERT INTO paper_lifecycle_outbox_delivery(
                    outbox_id,state,updated_at_unix_ms,acknowledged_at_unix_ms
                ) VALUES(?,?,?,?)
                ON CONFLICT(outbox_id) DO NOTHING
                """,
                (
                    row["outbox_id"],
                    state,
                    now_ms,
                    now_ms if bool(row["delivered"]) else None,
                ),
            )

    def record_transition(self, transition: Any) -> TransitionCommitResult:
        self.migrate()
        payload = _transition_payload(transition)
        payload_json = _canonical_json(payload)
        payload_hash = _sha256_text(payload_json)
        dependency_reasons_json = _canonical_json(
            list(transition.dependency_reasons)
        )
        details_json = _canonical_json(dict(transition.details))
        now_ms = int(time.time() * 1000)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT * FROM paper_lifecycle_transition
                WHERE transition_id=? OR (run_id=? AND cycle=?)
                LIMIT 1
                """,
                (transition.transition_id, transition.run_id, transition.cycle),
            ).fetchone()
            if existing is not None:
                existing_hash = existing["payload_hash"] or _sha256_text(
                    _canonical_json(_row_payload(existing))
                )
                if (
                    existing["transition_id"] != transition.transition_id
                    or existing_hash != payload_hash
                ):
                    raise LifecycleImmutabilityConflict(
                        "PR191_IMMUTABILITY_CONFLICT"
                    )
                self._assert_outbox_event_matches(
                    conn,
                    transition.outbox_id,
                    transition.transition_id,
                    payload_hash,
                )
                return TransitionCommitResult(
                    transition.transition_id,
                    transition.outbox_id,
                    payload_hash,
                    True,
                )

            conn.execute(
                """
                INSERT INTO paper_lifecycle_transition(
                    transition_id,attempt_id,run_id,cycle,state,terminal_reason,
                    candidates_seen,events_written,ready_for_next_cycle,
                    dependency_reasons_json,details_json,created_at_unix_ms,
                    schema_version,payload_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    transition.transition_id,
                    transition.attempt_id,
                    transition.run_id,
                    transition.cycle,
                    transition.state.value,
                    transition.terminal_reason,
                    transition.candidates_seen,
                    transition.events_written,
                    int(transition.ready_for_next_cycle),
                    dependency_reasons_json,
                    details_json,
                    transition.created_at_unix_ms,
                    transition.schema_version,
                    payload_hash,
                ),
            )
            conn.execute(
                """
                INSERT INTO paper_lifecycle_outbox_event(
                    outbox_id,transition_id,run_id,cycle,kind,payload_hash,
                    created_at_unix_ms,schema_version
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    transition.outbox_id,
                    transition.transition_id,
                    transition.run_id,
                    transition.cycle,
                    _legacy.PR150_OUTBOX_KIND,
                    payload_hash,
                    transition.created_at_unix_ms,
                    PR191_LIFECYCLE_SCHEMA,
                ),
            )
            conn.execute(
                """
                INSERT INTO paper_lifecycle_outbox_delivery(
                    outbox_id,state,updated_at_unix_ms
                ) VALUES(?,?,?)
                """,
                (
                    transition.outbox_id,
                    OutboxDeliveryState.PENDING.value,
                    now_ms,
                ),
            )
            # Compatibility projection only. Producer replay never updates it.
            conn.execute(
                """
                INSERT INTO paper_lifecycle_outbox(
                    outbox_id,transition_id,run_id,cycle,kind,delivered,
                    created_at_unix_ms
                ) VALUES(?,?,?,?,?,0,?)
                ON CONFLICT(outbox_id) DO NOTHING
                """,
                (
                    transition.outbox_id,
                    transition.transition_id,
                    transition.run_id,
                    transition.cycle,
                    _legacy.PR150_OUTBOX_KIND,
                    transition.created_at_unix_ms,
                ),
            )
            return TransitionCommitResult(
                transition.transition_id,
                transition.outbox_id,
                payload_hash,
                False,
            )

    @staticmethod
    def _assert_outbox_event_matches(
        conn: sqlite3.Connection,
        outbox_id: str,
        transition_id: str,
        payload_hash: str,
    ) -> None:
        event = conn.execute(
            "SELECT transition_id,payload_hash FROM paper_lifecycle_outbox_event "
            "WHERE outbox_id=?",
            (outbox_id,),
        ).fetchone()
        if event is None:
            raise LifecycleImmutabilityConflict("PR191_OUTBOX_EVENT_MISSING")
        if (
            event["transition_id"] != transition_id
            or event["payload_hash"] != payload_hash
        ):
            raise LifecycleImmutabilityConflict("PR191_OUTBOX_IMMUTABILITY_CONFLICT")

    def mark_delivered(
        self,
        outbox_id: str,
        *,
        acknowledged_at_unix_ms: int | None = None,
    ) -> bool:
        self.migrate()
        now_ms = acknowledged_at_unix_ms or int(time.time() * 1000)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute(
                """
                UPDATE paper_lifecycle_outbox_delivery
                SET state='acknowledged', owner=NULL, lease_expires_at_unix_ms=NULL,
                    acknowledged_at_unix_ms=COALESCE(acknowledged_at_unix_ms, ?),
                    updated_at_unix_ms=?
                WHERE outbox_id=? AND state!='acknowledged'
                """,
                (now_ms, now_ms, outbox_id),
            ).rowcount
            conn.execute(
                "UPDATE paper_lifecycle_outbox SET delivered=1 WHERE outbox_id=?",
                (outbox_id,),
            )
            return bool(changed)

    def lease_pending(
        self,
        *,
        owner: str,
        now_unix_ms: int,
        lease_duration_ms: int,
        limit: int = 1,
    ) -> tuple[OutboxLease, ...]:
        if not owner.strip() or lease_duration_ms <= 0 or limit <= 0:
            raise ValueError("owner, positive lease duration and limit are required")
        self.migrate()
        leases: list[OutboxLease] = []
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT outbox_id,fencing_token,attempt_count
                FROM paper_lifecycle_outbox_delivery
                WHERE (
                    state IN ('pending','failed-retryable')
                    AND COALESCE(next_retry_at_unix_ms,0) <= ?
                ) OR (
                    state='leased' AND lease_expires_at_unix_ms <= ?
                )
                ORDER BY updated_at_unix_ms,outbox_id
                LIMIT ?
                """,
                (now_unix_ms, now_unix_ms, limit),
            ).fetchall()
            for row in rows:
                fencing = int(row["fencing_token"]) + 1
                attempts = int(row["attempt_count"]) + 1
                expires = now_unix_ms + lease_duration_ms
                conn.execute(
                    """
                    UPDATE paper_lifecycle_outbox_delivery
                    SET state='leased',owner=?,fencing_token=?,
                        lease_expires_at_unix_ms=?,attempt_count=?,
                        updated_at_unix_ms=?
                    WHERE outbox_id=?
                    """,
                    (
                        owner,
                        fencing,
                        expires,
                        attempts,
                        now_unix_ms,
                        row["outbox_id"],
                    ),
                )
                leases.append(
                    OutboxLease(
                        row["outbox_id"], owner, fencing, expires, attempts
                    )
                )
        return tuple(leases)

    def record_delivery_attempt(
        self,
        lease: OutboxLease,
        *,
        result_state: OutboxDeliveryState,
        error_code: str | None = None,
        next_retry_at_unix_ms: int | None = None,
        now_unix_ms: int | None = None,
    ) -> None:
        if result_state in {OutboxDeliveryState.PENDING, OutboxDeliveryState.LEASED}:
            raise ValueError("delivery attempt requires a terminal attempt state")
        now_ms = now_unix_ms or int(time.time() * 1000)
        self.migrate()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                """
                SELECT owner,fencing_token,state
                FROM paper_lifecycle_outbox_delivery WHERE outbox_id=?
                """,
                (lease.outbox_id,),
            ).fetchone()
            if (
                current is None
                or current["owner"] != lease.owner
                or int(current["fencing_token"]) != lease.fencing_token
                or current["state"] != OutboxDeliveryState.LEASED.value
            ):
                raise LifecycleImmutabilityConflict("PR191_STALE_DELIVERY_LEASE")
            conn.execute(
                """
                INSERT INTO paper_lifecycle_outbox_attempt(
                    outbox_id,owner,fencing_token,result_state,error_code,
                    created_at_unix_ms
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    lease.outbox_id,
                    lease.owner,
                    lease.fencing_token,
                    result_state.value,
                    error_code,
                    now_ms,
                ),
            )
            conn.execute(
                """
                UPDATE paper_lifecycle_outbox_delivery
                SET state=?,owner=NULL,lease_expires_at_unix_ms=NULL,
                    next_retry_at_unix_ms=?,last_error_code=?,
                    acknowledged_at_unix_ms=CASE
                        WHEN ?='acknowledged'
                        THEN COALESCE(acknowledged_at_unix_ms,?)
                        ELSE acknowledged_at_unix_ms
                    END,
                    updated_at_unix_ms=?
                WHERE outbox_id=?
                """,
                (
                    result_state.value,
                    next_retry_at_unix_ms,
                    error_code,
                    result_state.value,
                    now_ms,
                    now_ms,
                    lease.outbox_id,
                ),
            )
            if result_state is OutboxDeliveryState.ACKNOWLEDGED:
                conn.execute(
                    "UPDATE paper_lifecycle_outbox SET delivered=1 WHERE outbox_id=?",
                    (lease.outbox_id,),
                )

    def read_outbox(self) -> tuple[dict[str, Any], ...]:
        if not Path(self.path).exists():
            return ()
        self.migrate()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.outbox_id,e.transition_id,e.run_id,e.cycle,e.kind,
                       e.payload_hash,e.created_at_unix_ms,e.schema_version,
                       d.state,d.owner,d.fencing_token,d.lease_expires_at_unix_ms,
                       d.attempt_count,d.next_retry_at_unix_ms,d.last_error_code,
                       d.acknowledged_at_unix_ms
                FROM paper_lifecycle_outbox_event AS e
                JOIN paper_lifecycle_outbox_delivery AS d USING(outbox_id)
                ORDER BY e.cycle,e.outbox_id
                """
            ).fetchall()
        return tuple(
            {
                "outbox_id": row["outbox_id"],
                "transition_id": row["transition_id"],
                "run_id": row["run_id"],
                "cycle": row["cycle"],
                "kind": row["kind"],
                "delivered": row["state"]
                == OutboxDeliveryState.ACKNOWLEDGED.value,
                "delivery_state": row["state"],
                "owner": row["owner"],
                "fencing_token": row["fencing_token"],
                "lease_expires_at_unix_ms": row["lease_expires_at_unix_ms"],
                "attempt_count": row["attempt_count"],
                "next_retry_at_unix_ms": row["next_retry_at_unix_ms"],
                "last_error_code": row["last_error_code"],
                "acknowledged_at_unix_ms": row["acknowledged_at_unix_ms"],
                "payload_hash": row["payload_hash"],
                "created_at_unix_ms": row["created_at_unix_ms"],
                "schema_version": row["schema_version"],
            }
            for row in rows
        )


def install_pr191_lifecycle_cutover() -> None:
    """Replace the public PR-150 store symbol without creating a second DB."""
    if _legacy.SQLitePaperLifecycleStore is not ImmutableSQLitePaperLifecycleStore:
        _legacy.LegacySQLitePaperLifecycleStore = _ORIGINAL_STORE
        _legacy.SQLitePaperLifecycleStore = ImmutableSQLitePaperLifecycleStore


install_pr191_lifecycle_cutover()


__all__ = [
    "ImmutableSQLitePaperLifecycleStore",
    "LifecycleImmutabilityConflict",
    "OutboxDeliveryState",
    "OutboxLease",
    "PR191_LIFECYCLE_SCHEMA",
    "TransitionCommitResult",
    "install_pr191_lifecycle_cutover",
]
