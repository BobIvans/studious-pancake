"""Single durable SQLite authority for canonical paper terminal truth."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from typing import Mapping

from .model import PaperCycleReport, PersistenceError, is_sha256


class CanonicalPaperStore:
    _MIGRATION_ID = "mega-pr-01-0002-unique-cycle-identity"
    _EXPECTED_COLUMNS = {
        "paper_migrations": {
            "migration_id": ("TEXT", True, True),
            "checksum": ("TEXT", True, False),
        },
        "paper_cycle_sequences": {
            "input_identity": ("TEXT", True, True),
            "last_sequence": ("INTEGER", True, False),
        },
        "paper_cycles": {
            "cycle_id": ("TEXT", True, True),
            "source_digest": ("TEXT", True, False),
            "config_digest": ("TEXT", True, False),
            "status": ("TEXT", True, False),
            "reason_code": ("TEXT", True, False),
            "report_json": ("TEXT", True, False),
            "report_hash": ("TEXT", True, False),
            "started_utc_ns": ("INTEGER", True, False),
            "completed_utc_ns": ("INTEGER", True, False),
        },
        "paper_candidate_decisions": {
            "cycle_id": ("TEXT", True, True),
            "candidate_id": ("TEXT", True, True),
            "candidate_digest": ("TEXT", True, False),
            "outcome": ("TEXT", True, False),
            "reason_code": ("TEXT", True, False),
            "net_profit_lamports": ("INTEGER", True, False),
        },
    }

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        try:
            self.connection = sqlite3.connect(
                self.path,
                timeout=5.0,
                isolation_level=None,
                check_same_thread=False,
            )
            self.connection.row_factory = sqlite3.Row
            for statement in (
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=FULL",
                "PRAGMA foreign_keys=ON",
                "PRAGMA trusted_schema=OFF",
                "PRAGMA busy_timeout=5000",
            ):
                self.connection.execute(statement)
            self._migrate()
        except sqlite3.Error as exc:
            raise PersistenceError("failed to initialize canonical paper store") from exc

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "CanonicalPaperStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _migrate(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS paper_migrations (
            migration_id TEXT PRIMARY KEY,
            checksum TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_cycle_sequences (
            input_identity TEXT PRIMARY KEY,
            last_sequence INTEGER NOT NULL CHECK(last_sequence >= 0)
        );
        CREATE TABLE IF NOT EXISTS paper_cycles (
            cycle_id TEXT PRIMARY KEY,
            source_digest TEXT NOT NULL,
            config_digest TEXT NOT NULL,
            status TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            report_json TEXT NOT NULL,
            report_hash TEXT NOT NULL,
            started_utc_ns INTEGER NOT NULL,
            completed_utc_ns INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_candidate_decisions (
            cycle_id TEXT NOT NULL,
            candidate_id TEXT NOT NULL,
            candidate_digest TEXT NOT NULL,
            outcome TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            net_profit_lamports INTEGER NOT NULL,
            PRIMARY KEY (cycle_id, candidate_id),
            FOREIGN KEY (cycle_id) REFERENCES paper_cycles(cycle_id) ON DELETE RESTRICT
        );
        """
        checksum = hashlib.sha256(schema.encode()).hexdigest()
        with self._lock:
            self._validate_existing_schema_before_create()
            self.connection.executescript(schema)
            self._validate_current_schema()
            row = self.connection.execute(
                "SELECT checksum FROM paper_migrations WHERE migration_id=?",
                (self._MIGRATION_ID,),
            ).fetchone()
            if row is None:
                self.connection.execute(
                    "INSERT INTO paper_migrations VALUES (?,?)",
                    (self._MIGRATION_ID, checksum),
                )
            elif row["checksum"] != checksum:
                raise PersistenceError("canonical paper migration checksum mismatch")

    def _validate_existing_schema_before_create(self) -> None:
        existing = {
            row["name"]
            for row in self.connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name LIKE 'paper_%'
                """
            )
        }
        for table_name in sorted(existing & set(self._EXPECTED_COLUMNS)):
            self._assert_table_contract(table_name)

    def _validate_current_schema(self) -> None:
        for table_name in sorted(self._EXPECTED_COLUMNS):
            self._assert_table_contract(table_name)
        fk_errors = list(self.connection.execute("PRAGMA foreign_key_check"))
        if fk_errors:
            raise PersistenceError("canonical paper foreign key check failed")
        integrity = self.connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise PersistenceError("canonical paper integrity check failed")

    def _assert_table_contract(self, table_name: str) -> None:
        expected = self._EXPECTED_COLUMNS[table_name]
        rows = list(self.connection.execute(f"PRAGMA table_info({table_name})"))
        if not rows:
            raise PersistenceError(f"canonical paper missing table {table_name}")
        observed = {str(row["name"]): row for row in rows}
        missing = sorted(set(expected) - set(observed))
        if missing:
            raise PersistenceError(
                f"canonical paper schema mismatch {table_name} missing={','.join(missing)}"
            )
        pk_columns = {
            name
            for name, row in observed.items()
            if int(row["pk"]) > 0 and name in expected
        }
        expected_pk = {name for name, spec in expected.items() if spec[2]}
        if pk_columns != expected_pk:
            raise PersistenceError(f"canonical paper schema mismatch {table_name} pk")
        for name, (declared_type, not_null, _pk) in expected.items():
            row = observed[name]
            if str(row["type"]).upper() != declared_type:
                raise PersistenceError(
                    f"canonical paper schema mismatch {table_name}.{name} type"
                )
            if bool(row["notnull"]) is not not_null and not row["pk"]:
                raise PersistenceError(
                    f"canonical paper schema mismatch {table_name}.{name} nullability"
                )

    def allocate_run_sequence(self, input_identity: str) -> int:
        if not is_sha256(input_identity):
            raise PersistenceError("input_identity must be a lowercase sha256")
        with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                row = self.connection.execute(
                    """
                    SELECT last_sequence FROM paper_cycle_sequences
                    WHERE input_identity=?
                    """,
                    (input_identity,),
                ).fetchone()
                if row is None:
                    sequence = 1
                    self.connection.execute(
                        """
                        INSERT INTO paper_cycle_sequences
                            (input_identity, last_sequence)
                        VALUES (?, ?)
                        """,
                        (input_identity, sequence),
                    )
                else:
                    previous = int(row["last_sequence"])
                    sequence = previous + 1
                    cursor = self.connection.execute(
                        """
                        UPDATE paper_cycle_sequences
                        SET last_sequence=?
                        WHERE input_identity=? AND last_sequence=?
                        """,
                        (sequence, input_identity, previous),
                    )
                    if cursor.rowcount != 1:
                        raise PersistenceError("canonical paper sequence CAS failed")
                self.connection.execute("COMMIT")
                return sequence
            except Exception:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise

    def load(self, cycle_id: str) -> PaperCycleReport | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT report_json FROM paper_cycles WHERE cycle_id=?",
                (cycle_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row["report_json"])
        except json.JSONDecodeError as exc:
            raise PersistenceError("stored report JSON is corrupt") from exc
        if not isinstance(payload, Mapping):
            raise PersistenceError("stored report has invalid shape")
        return PaperCycleReport.from_dict(payload)

    def commit(self, report: PaperCycleReport) -> PaperCycleReport:
        encoded = json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._lock:
            try:
                self.connection.execute("BEGIN IMMEDIATE")
                existing = self.connection.execute(
                    """
                    SELECT source_digest,config_digest,report_json
                    FROM paper_cycles
                    WHERE cycle_id=?
                    """,
                    (report.cycle_id,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["source_digest"] != report.source_digest
                        or existing["config_digest"] != report.config_digest
                    ):
                        raise PersistenceError("cycle idempotency collision")
                    self.connection.execute("ROLLBACK")
                    return PaperCycleReport.from_dict(json.loads(existing["report_json"]))
                self.connection.execute(
                    "INSERT INTO paper_cycles VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        report.cycle_id,
                        report.source_digest,
                        report.config_digest,
                        report.outcome.value,
                        report.reason_code,
                        encoded,
                        report.report_hash,
                        report.started_utc_ns,
                        report.completed_utc_ns,
                    ),
                )
                for decision in report.decisions:
                    self.connection.execute(
                        "INSERT INTO paper_candidate_decisions VALUES (?,?,?,?,?,?)",
                        (
                            report.cycle_id,
                            decision.candidate_id,
                            decision.candidate_digest,
                            decision.outcome.value,
                            decision.reason_code,
                            decision.net_profit_lamports,
                        ),
                    )
                self.connection.execute("COMMIT")
            except Exception:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise
        loaded = self.load(report.cycle_id)
        if loaded is None:
            raise PersistenceError("terminal report missing after commit")
        return loaded
