from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .events import EventEnvelope
from .redaction import REDACTION_VERSION

MIGRATION_VERSION = 17
SCHEMA_NAME = "pr132.observability-store.v1"

TERMINAL_EVENT_TYPES = frozenset(
    {
        "attempt_terminal",
        "balance_reconciled",
        "reconciliation_completed",
    }
)

REQUIRED_TABLE_COLUMNS: dict[str, frozenset[str]] = {
    "schema_migrations": frozenset(
        {"version", "applied_at", "schema_name", "schema_checksum"}
    ),
    "event_log": frozenset(
        {
            "event_id",
            "aggregate_id",
            "sequence_no",
            "idempotency_key",
            "occurred_at_utc_ns",
            "monotonic_ns",
            "event_type",
            "schema_version",
            "reason_code",
            "outcome",
            "stage",
            "severity",
            "environment",
            "logical_opportunity_id",
            "plan_hash",
            "attempt_generation",
            "attempt_id",
            "message_hash",
            "tx_signature",
            "jito_bundle_id",
            "provider_id",
            "venue_id",
            "payload_json",
            "payload_digest",
            "config_checksum",
            "redaction_version",
            "redaction_hits",
            "producer_code_version",
            "contract_fixture_version",
            "created_at",
        }
    ),
    "attempt_projection": frozenset(
        {
            "attempt_id",
            "aggregate_id",
            "last_sequence_no",
            "terminal",
            "outcome",
            "reason_code",
            "updated_at",
        }
    ),
    "opportunity_projection": frozenset(
        {
            "logical_opportunity_id",
            "aggregate_id",
            "last_sequence_no",
            "terminal",
            "updated_at",
        }
    ),
    "evidence_blob": frozenset(
        {"digest", "classification", "size_bytes", "payload_json", "created_at"}
    ),
    "outbox": frozenset(
        {"id", "event_id", "work_type", "status", "created_at", "completed_at"}
    ),
    "export_manifest": frozenset(
        {
            "manifest_id",
            "partition_path",
            "checksum",
            "event_count",
            "first_event_id",
            "last_event_id",
            "schema_version",
            "redaction_version",
            "created_at",
        }
    ),
    "retention_ledger": frozenset(
        {
            "id",
            "target_digest",
            "target_type",
            "action",
            "dry_run",
            "eligible_after_ns",
            "manifest_id",
            "created_at",
        }
    ),
}


class ObservabilityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SchemaDoctorResult:
    ok: bool
    missing_tables: tuple[str, ...]
    missing_columns: dict[str, tuple[str, ...]]
    schema_checksum: str

    def summary(self) -> str:
        parts: list[str] = []
        if self.missing_tables:
            parts.append("missing_tables=" + ",".join(self.missing_tables))
        for table, columns in self.missing_columns.items():
            parts.append(f"{table}.missing_columns=" + ",".join(columns))
        return "; ".join(parts) if parts else "ok"


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    return getattr(value, "value", str(value))


class ObservabilityStore:
    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 2500):
        self.path = str(path)
        self.db = sqlite3.connect(
            self.path,
            isolation_level=None,
            timeout=busy_timeout_ms / 1000,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        self.db.execute("PRAGMA foreign_keys=ON")
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.migrate()

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "ObservabilityStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def migrate(self) -> None:
        """Create/repair the current schema and only stamp it after verification."""

        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations(
                    version INTEGER PRIMARY KEY,
                    applied_at REAL NOT NULL,
                    schema_name TEXT NOT NULL DEFAULT 'legacy',
                    schema_checksum TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._ensure_schema_migration_metadata_columns()
            for statement in _SCHEMA_STATEMENTS:
                self.db.execute(statement)

            doctor = self.schema_doctor()
            if not doctor.ok:
                raise ObservabilityError(
                    "OBSERVABILITY_SCHEMA_INCOMPLETE: " + doctor.summary()
                )
            self.db.execute(
                """
                INSERT INTO schema_migrations(
                    version,
                    applied_at,
                    schema_name,
                    schema_checksum
                )
                VALUES(?,?,?,?)
                ON CONFLICT(version) DO UPDATE SET
                    applied_at=excluded.applied_at,
                    schema_name=excluded.schema_name,
                    schema_checksum=excluded.schema_checksum
                """,
                (
                    MIGRATION_VERSION,
                    time.time(),
                    SCHEMA_NAME,
                    doctor.schema_checksum,
                ),
            )
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def _ensure_schema_migration_metadata_columns(self) -> None:
        columns = self._columns_for("schema_migrations")
        if "schema_name" not in columns:
            self.db.execute(
                "ALTER TABLE schema_migrations "
                "ADD COLUMN schema_name TEXT NOT NULL DEFAULT 'legacy'"
            )
        if "schema_checksum" not in columns:
            self.db.execute(
                "ALTER TABLE schema_migrations "
                "ADD COLUMN schema_checksum TEXT NOT NULL DEFAULT ''"
            )

    def schema_doctor(self) -> SchemaDoctorResult:
        tables = self._existing_tables()
        missing_tables = tuple(
            sorted(table for table in REQUIRED_TABLE_COLUMNS if table not in tables)
        )
        missing_columns: dict[str, tuple[str, ...]] = {}
        for table, required_columns in sorted(REQUIRED_TABLE_COLUMNS.items()):
            if table in missing_tables:
                continue
            existing_columns = self._columns_for(table)
            missing = tuple(sorted(required_columns - existing_columns))
            if missing:
                missing_columns[table] = missing
        return SchemaDoctorResult(
            ok=not missing_tables and not missing_columns,
            missing_tables=missing_tables,
            missing_columns=missing_columns,
            schema_checksum=self.schema_checksum(),
        )

    def assert_schema_current(self) -> None:
        doctor = self.schema_doctor()
        if not doctor.ok:
            raise ObservabilityError(
                "OBSERVABILITY_SCHEMA_INCOMPLETE: " + doctor.summary()
            )

    def schema_checksum(self) -> str:
        rows = self.db.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE type IN ('table', 'index', 'trigger')
              AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
        payload = [
            {
                "type": row["type"],
                "name": row["name"],
                "sql": " ".join((row["sql"] or "").split()),
            }
            for row in rows
        ]
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def _existing_tables(self) -> set[str]:
        rows = self.db.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
        return {row["name"] for row in rows}

    def _columns_for(self, table: str) -> set[str]:
        return {row["name"] for row in self.db.execute(f"PRAGMA table_info({table})")}

    def append(self, event: EventEnvelope) -> bool:
        self.assert_schema_current()
        payload, hits = event.redacted_payload()
        digest = event.payload_digest()
        now = time.time()

        try:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                cur = self.db.execute(
                    """
                    INSERT OR IGNORE INTO event_log(
                        event_id,
                        aggregate_id,
                        sequence_no,
                        idempotency_key,
                        occurred_at_utc_ns,
                        monotonic_ns,
                        event_type,
                        schema_version,
                        reason_code,
                        outcome,
                        stage,
                        severity,
                        environment,
                        logical_opportunity_id,
                        plan_hash,
                        attempt_generation,
                        attempt_id,
                        message_hash,
                        tx_signature,
                        jito_bundle_id,
                        provider_id,
                        venue_id,
                        payload_json,
                        payload_digest,
                        config_checksum,
                        redaction_version,
                        redaction_hits,
                        producer_code_version,
                        contract_fixture_version,
                        created_at
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event.event_id,
                        event.aggregate_id,
                        event.sequence_no,
                        event.idempotency_key,
                        event.occurred_at_utc_ns,
                        event.monotonic_ns,
                        event.event_type.value,
                        event.schema_version,
                        _enum_value(event.reason_code),
                        event.outcome.value,
                        event.stage,
                        event.severity.value,
                        event.environment.value,
                        event.logical_opportunity_id,
                        event.plan_hash,
                        event.attempt_generation,
                        event.attempt_id,
                        event.message_hash,
                        event.tx_signature,
                        event.jito_bundle_id,
                        event.provider_id,
                        event.venue_id,
                        _canonical_json(payload),
                        digest,
                        event.config_checksum,
                        REDACTION_VERSION,
                        hits,
                        event.producer_code_version,
                        event.contract_fixture_version,
                        now,
                    ),
                )
                if cur.rowcount == 0:
                    existing = self.db.execute(
                        "SELECT event_id FROM event_log WHERE idempotency_key=?",
                        (event.idempotency_key,),
                    ).fetchone()
                    if existing and existing["event_id"] == event.event_id:
                        self.db.execute("ROLLBACK")
                        return False
                    raise ObservabilityError("OBSERVABILITY_DURABLE_WRITE_FAILED")

                self.db.execute(
                    """
                    INSERT OR IGNORE INTO outbox(event_id,work_type,status,created_at)
                    VALUES(?,?,?,?)
                    """,
                    (event.event_id, "export", "pending", now),
                )
                terminal = 1 if event.event_type.value in TERMINAL_EVENT_TYPES else 0
                if event.attempt_id:
                    self._upsert_attempt_projection(event, terminal=terminal, now=now)
                self._upsert_opportunity_projection(event, terminal=terminal, now=now)
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")
            return True
        except sqlite3.Error as exc:
            raise ObservabilityError("OBSERVABILITY_DURABLE_WRITE_FAILED") from exc

    def _upsert_attempt_projection(
        self,
        event: EventEnvelope,
        *,
        terminal: int,
        now: float,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO attempt_projection(
                attempt_id,
                aggregate_id,
                last_sequence_no,
                terminal,
                outcome,
                reason_code,
                updated_at
            )
            VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(attempt_id) DO UPDATE SET
                aggregate_id=excluded.aggregate_id,
                last_sequence_no=excluded.last_sequence_no,
                terminal=CASE
                    WHEN attempt_projection.terminal=1 THEN 1
                    ELSE excluded.terminal
                END,
                outcome=CASE
                    WHEN attempt_projection.terminal=1
                         AND excluded.terminal=0
                    THEN attempt_projection.outcome
                    ELSE excluded.outcome
                END,
                reason_code=CASE
                    WHEN attempt_projection.terminal=1
                         AND excluded.terminal=0
                    THEN attempt_projection.reason_code
                    ELSE excluded.reason_code
                END,
                updated_at=excluded.updated_at
            WHERE excluded.last_sequence_no > attempt_projection.last_sequence_no
            """,
            (
                event.attempt_id,
                event.aggregate_id,
                event.sequence_no,
                terminal,
                event.outcome.value,
                _enum_value(event.reason_code),
                now,
            ),
        )

    def _upsert_opportunity_projection(
        self,
        event: EventEnvelope,
        *,
        terminal: int,
        now: float,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO opportunity_projection(
                logical_opportunity_id,
                aggregate_id,
                last_sequence_no,
                terminal,
                updated_at
            )
            VALUES(?,?,?,?,?)
            ON CONFLICT(logical_opportunity_id) DO UPDATE SET
                aggregate_id=excluded.aggregate_id,
                last_sequence_no=excluded.last_sequence_no,
                terminal=CASE
                    WHEN opportunity_projection.terminal=1 THEN 1
                    ELSE excluded.terminal
                END,
                updated_at=excluded.updated_at
            WHERE excluded.last_sequence_no > opportunity_projection.last_sequence_no
            """,
            (
                event.logical_opportunity_id,
                event.aggregate_id,
                event.sequence_no,
                terminal,
                now,
            ),
        )

    def pending_export_rows(self) -> list[sqlite3.Row]:
        self.assert_schema_current()
        return list(
            self.db.execute(
                """
                SELECT event_log.*, outbox.id AS outbox_id
                FROM event_log
                JOIN outbox ON outbox.event_id=event_log.event_id
                WHERE outbox.status='pending' AND outbox.work_type='export'
                ORDER BY
                    event_log.occurred_at_utc_ns,
                    event_log.event_type,
                    event_log.event_id
                """
            )
        )

    def mark_outbox_done(self, outbox_ids: list[int], *, completed_at: float) -> None:
        if not outbox_ids:
            return
        placeholders = ",".join("?" for _ in outbox_ids)
        self.db.execute(
            f"""
            UPDATE outbox
            SET status='done', completed_at=?
            WHERE id IN ({placeholders})
            """,
            (completed_at, *outbox_ids),
        )

    def events_for(
        self,
        *,
        aggregate_id: str | None = None,
        opportunity_id: str | None = None,
        attempt_id: str | None = None,
    ) -> list[sqlite3.Row]:
        if aggregate_id:
            return list(
                self.db.execute(
                    "SELECT * FROM event_log WHERE aggregate_id=? ORDER BY sequence_no",
                    (aggregate_id,),
                )
            )
        if attempt_id:
            return list(
                self.db.execute(
                    "SELECT * FROM event_log WHERE attempt_id=? ORDER BY sequence_no",
                    (attempt_id,),
                )
            )
        if opportunity_id:
            return list(
                self.db.execute(
                    """
                    SELECT *
                    FROM event_log
                    WHERE logical_opportunity_id=?
                    ORDER BY sequence_no
                    """,
                    (opportunity_id,),
                )
            )
        raise ValueError("one selector required")


_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS event_log(
        event_id TEXT PRIMARY KEY,
        aggregate_id TEXT NOT NULL,
        sequence_no INTEGER NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE,
        occurred_at_utc_ns INTEGER NOT NULL,
        monotonic_ns INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        schema_version INTEGER NOT NULL,
        reason_code TEXT,
        outcome TEXT NOT NULL,
        stage TEXT NOT NULL,
        severity TEXT NOT NULL,
        environment TEXT NOT NULL,
        logical_opportunity_id TEXT NOT NULL,
        plan_hash TEXT NOT NULL,
        attempt_generation INTEGER NOT NULL,
        attempt_id TEXT,
        message_hash TEXT,
        tx_signature TEXT,
        jito_bundle_id TEXT,
        provider_id TEXT,
        venue_id TEXT,
        payload_json TEXT NOT NULL,
        payload_digest TEXT NOT NULL,
        config_checksum TEXT NOT NULL,
        redaction_version TEXT NOT NULL,
        redaction_hits INTEGER NOT NULL,
        producer_code_version TEXT,
        contract_fixture_version TEXT,
        created_at REAL NOT NULL,
        UNIQUE(aggregate_id, sequence_no)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attempt_projection(
        attempt_id TEXT PRIMARY KEY,
        aggregate_id TEXT NOT NULL,
        last_sequence_no INTEGER NOT NULL,
        terminal INTEGER NOT NULL,
        outcome TEXT,
        reason_code TEXT,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS opportunity_projection(
        logical_opportunity_id TEXT PRIMARY KEY,
        aggregate_id TEXT NOT NULL,
        last_sequence_no INTEGER NOT NULL,
        terminal INTEGER NOT NULL,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence_blob(
        digest TEXT PRIMARY KEY,
        classification TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS outbox(
        id INTEGER PRIMARY KEY,
        event_id TEXT NOT NULL UNIQUE,
        work_type TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at REAL NOT NULL,
        completed_at REAL,
        FOREIGN KEY(event_id) REFERENCES event_log(event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS export_manifest(
        manifest_id TEXT PRIMARY KEY,
        partition_path TEXT NOT NULL UNIQUE,
        checksum TEXT NOT NULL,
        event_count INTEGER NOT NULL,
        first_event_id TEXT,
        last_event_id TEXT,
        schema_version INTEGER NOT NULL,
        redaction_version TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS retention_ledger(
        id INTEGER PRIMARY KEY,
        target_digest TEXT NOT NULL,
        target_type TEXT NOT NULL,
        action TEXT NOT NULL,
        dry_run INTEGER NOT NULL,
        eligible_after_ns INTEGER NOT NULL,
        manifest_id TEXT,
        created_at REAL NOT NULL
    )
    """,
)
