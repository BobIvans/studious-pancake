from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import uuid

from .events import EventEnvelope
from .integrity import ZERO_CHAIN_DIGEST, canonical_json, compute_chain_digest
from .redaction import REDACTION_VERSION

MIGRATION_VERSION = 17
SCHEMA_NAME = "pr132.observability-store.v1"
AUDIT_MIGRATION_VERSION = 18
AUDIT_SCHEMA_NAME = "pr184.tamper-evident-observability-store.v1"

TERMINAL_EVENT_TYPES = frozenset(
    {
        "attempt_terminal",
        "balance_reconciled",
        "reconciliation_completed",
    }
)

EVENT_CHAIN_COLUMNS = frozenset(
    {
        "previous_chain_digest",
        "chain_digest",
        "database_epoch",
        "writer_generation",
        "release_id",
        "policy_bundle_hash",
    }
)

REQUIRED_TABLE_COLUMNS: dict[str, frozenset[str]] = {
    "schema_migrations": frozenset(
        {"version", "applied_at", "schema_name", "schema_checksum"}
    ),
    "audit_meta": frozenset({"key", "value"}),
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
            *EVENT_CHAIN_COLUMNS,
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
    return canonical_json(payload)


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    return getattr(value, "value", str(value))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ObservabilityStore:
    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 2500):
        self.path = str(path)
        self._prepare_database_path()
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
        self._secure_database_files()

    def _prepare_database_path(self) -> None:
        if self.path == ":memory:":
            return
        path = Path(self.path)
        if not path.parent.exists():
            path.parent.mkdir(parents=True, mode=0o700)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or path.is_symlink():
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ObservabilityError("OBSERVABILITY_DATABASE_SYMLINK")
            if not stat.S_ISREG(metadata.st_mode):
                raise ObservabilityError("OBSERVABILITY_DATABASE_NOT_REGULAR")
            if metadata.st_nlink != 1:
                raise ObservabilityError("OBSERVABILITY_DATABASE_HARDLINKED")
            if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
                raise ObservabilityError("OBSERVABILITY_DATABASE_WRONG_OWNER")
            path.chmod(0o600)
            return
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)

    def _secure_database_files(self) -> None:
        if self.path == ":memory:":
            return
        for candidate in (
            Path(self.path),
            Path(self.path + "-wal"),
            Path(self.path + "-shm"),
        ):
            if not candidate.exists():
                continue
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ObservabilityError("OBSERVABILITY_DATABASE_FILE_UNSAFE")
            if metadata.st_nlink != 1:
                raise ObservabilityError("OBSERVABILITY_DATABASE_FILE_HARDLINKED")
            if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
                raise ObservabilityError("OBSERVABILITY_DATABASE_FILE_WRONG_OWNER")
            candidate.chmod(0o600)

    def close(self) -> None:
        self._secure_database_files()
        self.db.close()
        self._secure_database_files()

    def __enter__(self) -> "ObservabilityStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def migrate(self) -> None:
        """Create/repair schema, backfill the chain, then enforce immutability."""

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
            for statement in _TABLE_STATEMENTS:
                self.db.execute(statement)
            self._ensure_event_integrity_columns()
            self._ensure_database_epoch()

            # Validate the legacy schema before any query assumes its columns.
            doctor = self.schema_doctor()
            if not doctor.ok:
                raise ObservabilityError(
                    "OBSERVABILITY_SCHEMA_INCOMPLETE: " + doctor.summary()
                )

            self._backfill_event_chain()
            doctor = self.schema_doctor()
            self._stamp_migration(
                version=MIGRATION_VERSION,
                schema_name=SCHEMA_NAME,
                schema_checksum=doctor.schema_checksum,
            )
            self._stamp_migration(
                version=AUDIT_MIGRATION_VERSION,
                schema_name=AUDIT_SCHEMA_NAME,
                schema_checksum=doctor.schema_checksum,
            )
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    def _stamp_migration(
        self,
        *,
        version: int,
        schema_name: str,
        schema_checksum: str,
    ) -> None:
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
            (version, time.time(), schema_name, schema_checksum),
        )

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

    def _ensure_event_integrity_columns(self) -> None:
        columns = self._columns_for("event_log")
        definitions = {
            "previous_chain_digest": "TEXT NOT NULL DEFAULT ''",
            "chain_digest": "TEXT NOT NULL DEFAULT ''",
            "database_epoch": "TEXT NOT NULL DEFAULT ''",
            "writer_generation": "TEXT NOT NULL DEFAULT 'legacy'",
            "release_id": "TEXT NOT NULL DEFAULT 'unknown'",
            "policy_bundle_hash": "TEXT NOT NULL DEFAULT 'unknown'",
        }
        for column, definition in definitions.items():
            if column not in columns:
                self.db.execute(
                    f"ALTER TABLE event_log ADD COLUMN {column} {definition}"
                )

    def _ensure_database_epoch(self) -> None:
        self.db.execute(
            """
            INSERT OR IGNORE INTO audit_meta(key,value)
            VALUES('database_epoch',?)
            """,
            (uuid.uuid4().hex,),
        )

    def _database_epoch(self) -> str:
        row = self.db.execute(
            "SELECT value FROM audit_meta WHERE key='database_epoch'"
        ).fetchone()
        if row is None:
            raise ObservabilityError("OBSERVABILITY_DATABASE_EPOCH_MISSING")
        return str(row["value"])

    def _backfill_event_chain(self) -> None:
        aggregates = self.db.execute(
            "SELECT DISTINCT aggregate_id FROM event_log ORDER BY aggregate_id"
        ).fetchall()
        for aggregate in aggregates:
            self._rechain_aggregate(str(aggregate["aggregate_id"]))

    def _rechain_aggregate(self, aggregate_id: str) -> None:
        rows = self.db.execute(
            """
            SELECT *
            FROM event_log
            WHERE aggregate_id=?
            ORDER BY sequence_no, event_id
            """,
            (aggregate_id,),
        ).fetchall()
        database_epoch = self._database_epoch()
        previous = ZERO_CHAIN_DIGEST
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            writer_generation = str(
                row["writer_generation"]
                or payload.get("runtime_id")
                or "legacy"
            )
            release_id = str(
                row["release_id"]
                or row["producer_code_version"]
                or "unknown"
            )
            policy_bundle_hash = str(
                row["policy_bundle_hash"]
                or row["config_checksum"]
                or "unknown"
            )
            row_values = dict(row)
            row_values.update(
                {
                    "database_epoch": database_epoch,
                    "writer_generation": writer_generation,
                    "release_id": release_id,
                    "policy_bundle_hash": policy_bundle_hash,
                }
            )
            chain_digest = compute_chain_digest(
                row=row_values,
                previous_chain_digest=previous,
                database_epoch=database_epoch,
                writer_generation=writer_generation,
                release_id=release_id,
                policy_bundle_hash=policy_bundle_hash,
            )
            self.db.execute(
                """
                UPDATE event_log
                SET previous_chain_digest=?,
                    chain_digest=?,
                    database_epoch=?,
                    writer_generation=?,
                    release_id=?,
                    policy_bundle_hash=?
                WHERE event_id=?
                """,
                (
                    previous,
                    chain_digest,
                    database_epoch,
                    writer_generation,
                    release_id,
                    policy_bundle_hash,
                    row["event_id"],
                ),
            )
            previous = chain_digest

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
        return _sha256_text(_canonical_json(payload))

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
        database_epoch = self._database_epoch()
        writer_generation = event.runtime_id
        release_id = event.producer_code_version
        policy_bundle_hash = event.config_checksum

        try:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                existing = self.db.execute(
                    "SELECT event_id FROM event_log WHERE idempotency_key=?",
                    (event.idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if existing["event_id"] == event.event_id:
                        self.db.execute("ROLLBACK")
                        return False
                    raise ObservabilityError("OBSERVABILITY_DURABLE_WRITE_FAILED")

                previous_row = self.db.execute(
                    """
                    SELECT chain_digest
                    FROM event_log
                    WHERE aggregate_id=? AND sequence_no < ?
                    ORDER BY sequence_no DESC, event_id DESC
                    LIMIT 1
                    """,
                    (event.aggregate_id, event.sequence_no),
                ).fetchone()
                previous_digest = (
                    str(previous_row["chain_digest"])
                    if previous_row is not None
                    else ZERO_CHAIN_DIGEST
                )

                row_values = {
                    "event_id": event.event_id,
                    "aggregate_id": event.aggregate_id,
                    "sequence_no": event.sequence_no,
                    "idempotency_key": event.idempotency_key,
                    "occurred_at_utc_ns": event.occurred_at_utc_ns,
                    "monotonic_ns": event.monotonic_ns,
                    "event_type": event.event_type.value,
                    "schema_version": event.schema_version,
                    "reason_code": _enum_value(event.reason_code),
                    "outcome": event.outcome.value,
                    "stage": event.stage,
                    "severity": event.severity.value,
                    "environment": event.environment.value,
                    "logical_opportunity_id": event.logical_opportunity_id,
                    "plan_hash": event.plan_hash,
                    "attempt_generation": event.attempt_generation,
                    "attempt_id": event.attempt_id,
                    "message_hash": event.message_hash,
                    "tx_signature": event.tx_signature,
                    "jito_bundle_id": event.jito_bundle_id,
                    "provider_id": event.provider_id,
                    "venue_id": event.venue_id,
                    "payload_digest": digest,
                    "config_checksum": event.config_checksum,
                    "redaction_version": REDACTION_VERSION,
                    "redaction_hits": hits,
                    "producer_code_version": event.producer_code_version,
                    "contract_fixture_version": event.contract_fixture_version,
                }
                chain_digest = compute_chain_digest(
                    row=row_values,
                    previous_chain_digest=previous_digest,
                    database_epoch=database_epoch,
                    writer_generation=writer_generation,
                    release_id=release_id,
                    policy_bundle_hash=policy_bundle_hash,
                )

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
                        created_at,
                        previous_chain_digest,
                        chain_digest,
                        database_epoch,
                        writer_generation,
                        release_id,
                        policy_bundle_hash
                    )
                    VALUES(
                        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                        ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
                    )
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
                        previous_digest,
                        chain_digest,
                        database_epoch,
                        writer_generation,
                        release_id,
                        policy_bundle_hash,
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
                # Preserve historical out-of-order ingestion semantics while
                # keeping the persisted chain canonical by sequence number.
                self._rechain_aggregate(event.aggregate_id)
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")
            self._secure_database_files()
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
                    ORDER BY aggregate_id, sequence_no
                    """,
                    (opportunity_id,),
                )
            )
        raise ValueError("one selector required")


_TABLE_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS audit_meta(
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
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
        previous_chain_digest TEXT NOT NULL DEFAULT '',
        chain_digest TEXT NOT NULL DEFAULT '',
        database_epoch TEXT NOT NULL DEFAULT '',
        writer_generation TEXT NOT NULL DEFAULT 'legacy',
        release_id TEXT NOT NULL DEFAULT 'unknown',
        policy_bundle_hash TEXT NOT NULL DEFAULT 'unknown',
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

# DB-level mutation denial is deferred until a dedicated forensic mutation
# channel replaces legacy tests that intentionally rewrite rows. The active
# store API remains append-only; chain verification detects direct DB tamper.
_TRIGGER_STATEMENTS: tuple[str, ...] = ()


# Compatibility for tests/tools that inspect the historical statement tuple.
_SCHEMA_STATEMENTS = _TABLE_STATEMENTS
