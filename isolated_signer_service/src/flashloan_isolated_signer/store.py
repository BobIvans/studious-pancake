"""Durable exactly-once intent ledger for roadmap PR-08."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from .models import (
    BoundaryFailure,
    IntentRecord,
    IntentState,
    PR08BoundaryError,
    PRODUCT_ID,
    SCHEMA_VERSION,
    SubmissionPermit,
    TransportKind,
    identifier,
    sha256,
)


class DurableSubmissionIntentStore:
    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 250) -> None:
        if not 0 <= busy_timeout_ms <= 5_000:
            raise ValueError("busy_timeout_ms must be between 0 and 5000")
        self.path = str(path)
        self.busy_timeout_ms = busy_timeout_ms
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS pr08_meta(
                      singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                      product_id TEXT NOT NULL,
                      schema_version TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS pr08_intent(
                      intent_id TEXT PRIMARY KEY,
                      idempotency_key TEXT NOT NULL UNIQUE,
                      permit_hash TEXT NOT NULL,
                      message_sha256 TEXT NOT NULL,
                      attempt_id TEXT NOT NULL,
                      generation INTEGER NOT NULL,
                      transport TEXT NOT NULL,
                      state TEXT NOT NULL,
                      request_hash TEXT NOT NULL,
                      receipt_hash TEXT,
                      created_at_ns INTEGER NOT NULL,
                      updated_at_ns INTEGER NOT NULL
                    );
                    """
                )
                connection.execute(
                    """INSERT INTO pr08_meta VALUES(1, ?, ?)
                    ON CONFLICT(singleton) DO NOTHING""",
                    (PRODUCT_ID, SCHEMA_VERSION),
                )
                row = connection.execute(
                    "SELECT product_id, schema_version FROM pr08_meta"
                ).fetchone()
                if row is None or tuple(row) != (PRODUCT_ID, SCHEMA_VERSION):
                    raise PR08BoundaryError(
                        BoundaryFailure.STORE_ERROR, "database identity mismatch"
                    )
        except PR08BoundaryError:
            raise
        except sqlite3.Error as exc:
            raise PR08BoundaryError(
                BoundaryFailure.STORE_ERROR, "database initialization failed"
            ) from exc

    def prepare(
        self, permit: SubmissionPermit, *, request_hash: str, now_ns: int
    ) -> IntentRecord:
        sha256(request_hash, "request_hash")
        intent_id = f"intent_{permit.idempotency_key}"
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM pr08_intent WHERE idempotency_key=?",
                    (permit.idempotency_key,),
                ).fetchone()
                if row is not None:
                    record = self._record(row)
                    connection.execute("COMMIT")
                    if (
                        record.permit_hash == permit.permit_hash
                        and record.request_hash == request_hash
                    ):
                        return record
                    raise PR08BoundaryError(
                        BoundaryFailure.REPLAY_CONFLICT,
                        "idempotency identity conflicts with durable intent",
                    )
                connection.execute(
                    """INSERT INTO pr08_intent VALUES(
                    ?,?,?,?,?,?,?,?,?,NULL,?,?)""",
                    (
                        intent_id,
                        permit.idempotency_key,
                        permit.permit_hash,
                        permit.message_sha256,
                        permit.attempt_id,
                        permit.generation,
                        permit.transport.value,
                        IntentState.PREPARED.value,
                        request_hash,
                        now_ns,
                        now_ns,
                    ),
                )
                connection.execute("COMMIT")
                return IntentRecord(
                    intent_id,
                    permit.idempotency_key,
                    permit.permit_hash,
                    permit.message_sha256,
                    permit.attempt_id,
                    permit.generation,
                    permit.transport,
                    IntentState.PREPARED,
                    request_hash,
                    None,
                    now_ns,
                    now_ns,
                )
        except PR08BoundaryError:
            raise
        except sqlite3.Error as exc:
            raise PR08BoundaryError(
                BoundaryFailure.STORE_ERROR, "failed to persist intent"
            ) from exc

    def transition(
        self,
        intent_id: str,
        *,
        expected: IntentState,
        target: IntentState,
        now_ns: int,
        receipt_hash: str | None = None,
    ) -> IntentRecord:
        identifier(intent_id, "intent_id")
        if receipt_hash is not None:
            sha256(receipt_hash, "receipt_hash")
        allowed = {
            (IntentState.PREPARED, IntentState.DISPATCHED),
            (IntentState.PREPARED, IntentState.REVOKED),
            (IntentState.DISPATCHED, IntentState.ACKNOWLEDGED),
            (IntentState.DISPATCHED, IntentState.INDETERMINATE),
        }
        if (expected, target) not in allowed:
            raise PR08BoundaryError(
                BoundaryFailure.INTENT_STATE, "unsupported intent transition"
            )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                changed = connection.execute(
                    """UPDATE pr08_intent SET state=?, receipt_hash=?, updated_at_ns=?
                    WHERE intent_id=? AND state=?""",
                    (target.value, receipt_hash, now_ns, intent_id, expected.value),
                ).rowcount
                if changed != 1:
                    connection.execute("ROLLBACK")
                    raise PR08BoundaryError(
                        BoundaryFailure.INTENT_STATE,
                        "intent compare-and-swap failed",
                    )
                row = connection.execute(
                    "SELECT * FROM pr08_intent WHERE intent_id=?", (intent_id,)
                ).fetchone()
                connection.execute("COMMIT")
                if row is None:
                    raise PR08BoundaryError(
                        BoundaryFailure.STORE_ERROR, "updated intent is missing"
                    )
                return self._record(row)
        except PR08BoundaryError:
            raise
        except sqlite3.Error as exc:
            raise PR08BoundaryError(
                BoundaryFailure.STORE_ERROR, "failed to transition intent"
            ) from exc

    @staticmethod
    def _record(row: sqlite3.Row) -> IntentRecord:
        return IntentRecord(
            intent_id=row["intent_id"],
            idempotency_key=row["idempotency_key"],
            permit_hash=row["permit_hash"],
            message_sha256=row["message_sha256"],
            attempt_id=row["attempt_id"],
            generation=row["generation"],
            transport=TransportKind(row["transport"]),
            state=IntentState(row["state"]),
            request_hash=row["request_hash"],
            receipt_hash=row["receipt_hash"],
            created_at_ns=row["created_at_ns"],
            updated_at_ns=row["updated_at_ns"],
        )
