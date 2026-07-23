"""Single durable SQLite authority for canonical paper terminal truth."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from typing import Mapping

from .model import PaperCycleReport, PersistenceError


class CanonicalPaperStore:
    _MIGRATION_ID = "mega-pr-01-0001"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        try:
            self.connection = sqlite3.connect(
                self.path, timeout=5.0, isolation_level=None, check_same_thread=False
            )
            self.connection.row_factory = sqlite3.Row
            for statement in (
                "PRAGMA journal_mode=WAL", "PRAGMA synchronous=FULL",
                "PRAGMA foreign_keys=ON", "PRAGMA trusted_schema=OFF",
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
            migration_id TEXT PRIMARY KEY, checksum TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_cycles (
            cycle_id TEXT PRIMARY KEY, source_digest TEXT NOT NULL,
            config_digest TEXT NOT NULL, status TEXT NOT NULL,
            reason_code TEXT NOT NULL, report_json TEXT NOT NULL,
            report_hash TEXT NOT NULL, started_utc_ns INTEGER NOT NULL,
            completed_utc_ns INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS paper_candidate_decisions (
            cycle_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
            candidate_digest TEXT NOT NULL, outcome TEXT NOT NULL,
            reason_code TEXT NOT NULL, net_profit_lamports INTEGER NOT NULL,
            PRIMARY KEY (cycle_id, candidate_id),
            FOREIGN KEY (cycle_id) REFERENCES paper_cycles(cycle_id) ON DELETE RESTRICT
        );
        """
        checksum = hashlib.sha256(schema.encode()).hexdigest()
        with self._lock:
            self.connection.executescript(schema)
            row = self.connection.execute(
                "SELECT checksum FROM paper_migrations WHERE migration_id=?",
                (self._MIGRATION_ID,),
            ).fetchone()
            if row is None:
                self.connection.execute(
                    "INSERT INTO paper_migrations VALUES (?,?)", (self._MIGRATION_ID, checksum)
                )
            elif row["checksum"] != checksum:
                raise PersistenceError("canonical paper migration checksum mismatch")

    def load(self, cycle_id: str) -> PaperCycleReport | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT report_json FROM paper_cycles WHERE cycle_id=?", (cycle_id,)
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
                    "SELECT source_digest,config_digest,report_json FROM paper_cycles WHERE cycle_id=?",
                    (report.cycle_id,),
                ).fetchone()
                if existing is not None:
                    if existing["source_digest"] != report.source_digest or existing["config_digest"] != report.config_digest:
                        raise PersistenceError("cycle idempotency collision")
                    self.connection.execute("ROLLBACK")
                    return PaperCycleReport.from_dict(json.loads(existing["report_json"]))
                self.connection.execute(
                    "INSERT INTO paper_cycles VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        report.cycle_id, report.source_digest, report.config_digest,
                        report.outcome.value, report.reason_code, encoded, report.report_hash,
                        report.started_utc_ns, report.completed_utc_ns,
                    ),
                )
                for decision in report.decisions:
                    self.connection.execute(
                        "INSERT INTO paper_candidate_decisions VALUES (?,?,?,?,?,?)",
                        (
                            report.cycle_id, decision.candidate_id, decision.candidate_digest,
                            decision.outcome.value, decision.reason_code,
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
