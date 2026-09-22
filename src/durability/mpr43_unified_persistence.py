"""MPR-43 unified persistence, migration and recovery foundation.

This module is intentionally standard-library-only and side-effect-free at import
time. It does not submit transactions, call RPC/Jito, read private keys, or
enable live execution. It provides one reviewed SQLite authority shape for
migration checksums, schema fingerprinting, writer fencing, append-only audit
events, durable inbox/outbox rows, integer-only economic ledger entries, and
backup/restore verification.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any

SCHEMA_VERSION = "mpr43.unified-persistence.v1"
CANONICAL_AUTHORITY_NAME = "mpr43-unified-persistence-authority"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


class Mpr43PersistenceError(ValueError):
    """Raised when persistence authority invariants fail closed."""


class Mpr43State(StrEnum):
    QUEUED = "queued"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(
            _canonical_json(
                {
                    "schema_version": SCHEMA_VERSION,
                    "version": self.version,
                    "name": self.name,
                    "sql": self.sql,
                }
            ).encode("utf-8")
        ).hexdigest()

    def validate(self) -> None:
        _positive_int(self.version, "migration.version")
        _safe_id(self.name, "migration.name")
        if not self.sql.strip():
            raise Mpr43PersistenceError("MIGRATION_SQL_EMPTY")


@dataclass(frozen=True, slots=True)
class GenerationFence:
    generation_id: str
    lease_token: str

    def __post_init__(self) -> None:
        _safe_id(self.generation_id, "generation_id")
        _safe_id(self.lease_token, "lease_token")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    generation_id: str
    event_type: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        _safe_id(self.event_id, "event_id")
        _safe_id(self.generation_id, "generation_id")
        _safe_id(self.event_type, "event_type")
        _json_bytes(self.payload)


@dataclass(frozen=True, slots=True)
class InboxEvent:
    event_id: str
    provider: str
    payload: Mapping[str, Any]
    received_at_ns: int

    def __post_init__(self) -> None:
        _safe_id(self.event_id, "inbox.event_id")
        _safe_id(self.provider, "inbox.provider")
        _non_negative_int(self.received_at_ns, "inbox.received_at_ns")
        _json_bytes(self.payload)


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    outbox_id: str
    event_type: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        _safe_id(self.outbox_id, "outbox.outbox_id")
        _safe_id(self.event_type, "outbox.event_type")
        _json_bytes(self.payload)


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    entry_id: str
    attempt_id: str
    asset_id: str
    delta_base_units: int
    reason: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        _safe_id(self.entry_id, "ledger.entry_id")
        _safe_id(self.attempt_id, "ledger.attempt_id")
        _safe_id(self.asset_id, "ledger.asset_id")
        _strict_int(self.delta_base_units, "ledger.delta_base_units")
        _safe_id(self.reason, "ledger.reason")
        _sha256(self.evidence_sha256, "ledger.evidence_sha256")


@dataclass(frozen=True, slots=True)
class BackupManifest:
    schema_version: str
    authority_name: str
    source_schema_fingerprint: str
    backup_schema_fingerprint: str
    backup_sha256: str
    source_path: str
    backup_path: str
    created_at_ns: int
    integrity_check: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RestoreReport:
    schema_version: str
    backup_path: str
    schema_fingerprint: str
    integrity_check: str
    active_writer_count: int
    accepted: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DirectConnectFinding:
    path: str
    line: int
    snippet: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        1,
        "authority_metadata",
        """
        CREATE TABLE IF NOT EXISTS mpr43_migration (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at_ns INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mpr43_runtime_generation (
            generation_id TEXT PRIMARY KEY,
            lease_token TEXT NOT NULL,
            started_at_ns INTEGER NOT NULL,
            ended_at_ns INTEGER,
            active INTEGER NOT NULL CHECK (active IN (0, 1))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_mpr43_one_active_generation
            ON mpr43_runtime_generation(active)
            WHERE active = 1;
        """,
    ),
    Migration(
        2,
        "append_only_audit",
        """
        CREATE TABLE IF NOT EXISTS mpr43_audit_event (
            event_id TEXT PRIMARY KEY,
            generation_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            created_at_ns INTEGER NOT NULL,
            FOREIGN KEY (generation_id)
                REFERENCES mpr43_runtime_generation(generation_id)
        );
        """,
    ),
    Migration(
        3,
        "durable_inbox_outbox",
        """
        CREATE TABLE IF NOT EXISTS mpr43_inbox_event (
            event_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            received_at_ns INTEGER NOT NULL,
            state TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS mpr43_outbox_event (
            outbox_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            created_at_ns INTEGER NOT NULL,
            state TEXT NOT NULL,
            dispatch_attempts INTEGER NOT NULL DEFAULT 0
        );
        """,
    ),
    Migration(
        4,
        "integer_economic_ledger",
        """
        CREATE TABLE IF NOT EXISTS mpr43_economic_ledger (
            entry_id TEXT PRIMARY KEY,
            attempt_id TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            delta_base_units INTEGER NOT NULL,
            reason TEXT NOT NULL,
            evidence_sha256 TEXT NOT NULL,
            created_at_ns INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mpr43_ledger_attempt
            ON mpr43_economic_ledger(attempt_id);
        """,
    ),
    Migration(
        5,
        "backup_manifest",
        """
        CREATE TABLE IF NOT EXISTS mpr43_backup_manifest (
            backup_id TEXT PRIMARY KEY,
            source_schema_fingerprint TEXT NOT NULL,
            backup_sha256 TEXT NOT NULL,
            backup_path TEXT NOT NULL,
            created_at_ns INTEGER NOT NULL,
            integrity_check TEXT NOT NULL
        );
        """,
    ),
)


class UnifiedPersistenceAuthority:
    """One canonical SQLite authority for MPR-43 qualification slices."""

    def __init__(
        self,
        path: str | Path,
        *,
        monotonic_ns=time.monotonic_ns,
        wall_time_ns=time.time_ns,
    ) -> None:
        self.path = Path(path)
        self._monotonic_ns = monotonic_ns
        self._wall_time_ns = wall_time_ns

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS mpr43_migration ("
                "version INTEGER PRIMARY KEY,"
                "name TEXT NOT NULL,"
                "checksum TEXT NOT NULL,"
                "applied_at_ns INTEGER NOT NULL"
                ")"
            )
            for migration in MIGRATIONS:
                migration.validate()
                existing = con.execute(
                    "SELECT name, checksum FROM mpr43_migration WHERE version = ?",
                    (migration.version,),
                ).fetchone()
                if existing is not None:
                    name, checksum = str(existing[0]), str(existing[1])
                    if name != migration.name or checksum != migration.checksum:
                        raise Mpr43PersistenceError(
                            f"MIGRATION_CHECKSUM_MISMATCH:{migration.version}"
                        )
                    continue
                con.executescript(migration.sql)
                con.execute(
                    "INSERT INTO mpr43_migration(version, name, checksum, applied_at_ns)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        migration.version,
                        migration.name,
                        migration.checksum,
                        self._wall_time_ns(),
                    ),
                )
        self.verify_pragmas()

    def verify_pragmas(self) -> None:
        with self._connect() as con:
            foreign_keys = int(con.execute("PRAGMA foreign_keys").fetchone()[0])
            if foreign_keys != 1:
                raise Mpr43PersistenceError("FOREIGN_KEYS_DISABLED")
            journal_mode = str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            if journal_mode not in {"wal", "memory"}:
                raise Mpr43PersistenceError(f"UNSUPPORTED_JOURNAL_MODE:{journal_mode}")

    def start_generation(self, fence: GenerationFence) -> None:
        self.initialize()
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            active = con.execute(
                "SELECT generation_id FROM mpr43_runtime_generation WHERE active = 1"
            ).fetchone()
            if active is not None and str(active[0]) != fence.generation_id:
                raise Mpr43PersistenceError(
                    f"ACTIVE_GENERATION_EXISTS:{str(active[0])}"
                )
            con.execute(
                "INSERT INTO mpr43_runtime_generation"
                "(generation_id, lease_token, started_at_ns, active)"
                " VALUES (?, ?, ?, 1)"
                " ON CONFLICT(generation_id) DO UPDATE SET"
                " lease_token=excluded.lease_token,"
                " started_at_ns=excluded.started_at_ns,"
                " ended_at_ns=NULL,"
                " active=1",
                (fence.generation_id, fence.lease_token, self._wall_time_ns()),
            )

    def close_generation(self, fence: GenerationFence) -> None:
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            self._assert_writer(con, fence)
            con.execute(
                "UPDATE mpr43_runtime_generation"
                " SET active = 0, ended_at_ns = ?"
                " WHERE generation_id = ? AND lease_token = ? AND active = 1",
                (self._wall_time_ns(), fence.generation_id, fence.lease_token),
            )
            if con.total_changes < 1:
                raise Mpr43PersistenceError("GENERATION_CLOSE_FAILED")

    def append_audit_event(self, fence: GenerationFence, event: AuditEvent) -> None:
        if event.generation_id != fence.generation_id:
            raise Mpr43PersistenceError("AUDIT_GENERATION_MISMATCH")
        payload_json = _canonical_json(event.payload)
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            self._assert_writer(con, fence)
            con.execute(
                "INSERT INTO mpr43_audit_event"
                "(event_id, generation_id, event_type, payload_json, payload_sha256,"
                " created_at_ns)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    event.event_id,
                    event.generation_id,
                    event.event_type,
                    payload_json,
                    hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                    self._wall_time_ns(),
                ),
            )

    def record_inbox_outbox_atomic(
        self,
        fence: GenerationFence,
        *,
        inbox: InboxEvent,
        outbox: OutboxEvent,
        audit_event_id: str,
    ) -> None:
        inbox_json = _canonical_json(inbox.payload)
        outbox_json = _canonical_json(outbox.payload)
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            self._assert_writer(con, fence)
            con.execute(
                "INSERT INTO mpr43_inbox_event"
                "(event_id, provider, payload_json, payload_sha256, received_at_ns,"
                " state)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    inbox.event_id,
                    inbox.provider,
                    inbox_json,
                    hashlib.sha256(inbox_json.encode("utf-8")).hexdigest(),
                    inbox.received_at_ns,
                    Mpr43State.QUEUED.value,
                ),
            )
            con.execute(
                "INSERT INTO mpr43_outbox_event"
                "(outbox_id, event_type, payload_json, payload_sha256, created_at_ns,"
                " state)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    outbox.outbox_id,
                    outbox.event_type,
                    outbox_json,
                    hashlib.sha256(outbox_json.encode("utf-8")).hexdigest(),
                    self._wall_time_ns(),
                    Mpr43State.PENDING.value,
                ),
            )
            audit_payload = {
                "inbox_event_id": inbox.event_id,
                "outbox_id": outbox.outbox_id,
                "provider": inbox.provider,
            }
            audit_json = _canonical_json(audit_payload)
            con.execute(
                "INSERT INTO mpr43_audit_event"
                "(event_id, generation_id, event_type, payload_json, payload_sha256,"
                " created_at_ns)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    audit_event_id,
                    fence.generation_id,
                    "inbox-outbox-atomic",
                    audit_json,
                    hashlib.sha256(audit_json.encode("utf-8")).hexdigest(),
                    self._wall_time_ns(),
                ),
            )

    def append_ledger_entry(self, fence: GenerationFence, entry: LedgerEntry) -> None:
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            self._assert_writer(con, fence)
            con.execute(
                "INSERT INTO mpr43_economic_ledger"
                "(entry_id, attempt_id, asset_id, delta_base_units, reason,"
                " evidence_sha256, created_at_ns)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry.entry_id,
                    entry.attempt_id,
                    entry.asset_id,
                    entry.delta_base_units,
                    entry.reason,
                    entry.evidence_sha256,
                    self._wall_time_ns(),
                ),
            )

    def schema_fingerprint(self) -> str:
        self.initialize()
        with self._connect() as con:
            rows = con.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master"
                " WHERE sql IS NOT NULL"
                " AND name NOT LIKE 'sqlite_%'"
                " ORDER BY type, name, tbl_name, sql"
            ).fetchall()
            migrations = con.execute(
                "SELECT version, name, checksum FROM mpr43_migration"
                " ORDER BY version"
            ).fetchall()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "sqlite_master": [
                {
                    "type": str(row[0]),
                    "name": str(row[1]),
                    "tbl_name": str(row[2]),
                    "sql": " ".join(str(row[3]).split()),
                }
                for row in rows
            ],
            "migrations": [
                {"version": int(row[0]), "name": str(row[1]), "checksum": str(row[2])}
                for row in migrations
            ],
        }
        return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()

    def create_backup(self, destination: str | Path) -> BackupManifest:
        self.initialize()
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        source_fingerprint = self.schema_fingerprint()
        with self._connect() as source, sqlite3.connect(str(destination_path)) as target:
            source.backup(target)
        backup_sha = _file_sha256(destination_path)
        report = validate_restore(
            destination_path,
            expected_schema_fingerprint=source_fingerprint,
        )
        if not report.accepted:
            raise Mpr43PersistenceError(
                "BACKUP_RESTORE_VALIDATION_FAILED:" + ",".join(report.blockers)
            )
        manifest = BackupManifest(
            schema_version=SCHEMA_VERSION,
            authority_name=CANONICAL_AUTHORITY_NAME,
            source_schema_fingerprint=source_fingerprint,
            backup_schema_fingerprint=report.schema_fingerprint,
            backup_sha256=backup_sha,
            source_path=str(self.path),
            backup_path=str(destination_path),
            created_at_ns=self._wall_time_ns(),
            integrity_check=report.integrity_check,
        )
        backup_id = hashlib.sha256(
            _canonical_json(manifest.to_dict()).encode("utf-8")
        ).hexdigest()
        with self._connect() as con:
            con.execute(
                "INSERT INTO mpr43_backup_manifest"
                "(backup_id, source_schema_fingerprint, backup_sha256, backup_path,"
                " created_at_ns, integrity_check)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    backup_id,
                    manifest.source_schema_fingerprint,
                    manifest.backup_sha256,
                    manifest.backup_path,
                    manifest.created_at_ns,
                    manifest.integrity_check,
                ),
            )
        return manifest

    def close_all_active_generations_for_backup(self) -> None:
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute(
                "UPDATE mpr43_runtime_generation"
                " SET active = 0, ended_at_ns = COALESCE(ended_at_ns, ?)"
                " WHERE active = 1",
                (self._wall_time_ns(),),
            )

    def count_rows(self, table: str) -> int:
        _safe_id(table, "table")
        with self._connect() as con:
            return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None)
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _assert_writer(self, con: sqlite3.Connection, fence: GenerationFence) -> None:
        row = con.execute(
            "SELECT 1 FROM mpr43_runtime_generation"
            " WHERE generation_id = ? AND lease_token = ? AND active = 1",
            (fence.generation_id, fence.lease_token),
        ).fetchone()
        if row is None:
            raise Mpr43PersistenceError("STALE_OR_INACTIVE_WRITER")


def validate_restore(
    backup_path: str | Path,
    *,
    expected_schema_fingerprint: str | None = None,
) -> RestoreReport:
    path = Path(backup_path)
    blockers: list[str] = []
    if not path.exists() or not path.is_file():
        blockers.append("BACKUP_FILE_MISSING")
        return RestoreReport(
            schema_version=SCHEMA_VERSION,
            backup_path=str(path),
            schema_fingerprint="",
            integrity_check="missing",
            active_writer_count=0,
            accepted=False,
            blockers=tuple(blockers),
        )

    authority = UnifiedPersistenceAuthority(path)
    try:
        fingerprint = authority.schema_fingerprint()
        with authority._connect() as con:
            integrity = str(con.execute("PRAGMA integrity_check").fetchone()[0])
            active_writer_count = int(
                con.execute(
                    "SELECT COUNT(*) FROM mpr43_runtime_generation WHERE active = 1"
                ).fetchone()[0]
            )
    except sqlite3.DatabaseError as exc:
        blockers.append(f"BACKUP_SQLITE_ERROR:{type(exc).__name__}")
        return RestoreReport(
            schema_version=SCHEMA_VERSION,
            backup_path=str(path),
            schema_fingerprint="",
            integrity_check="sqlite-error",
            active_writer_count=0,
            accepted=False,
            blockers=tuple(blockers),
        )
    if integrity.lower() != "ok":
        blockers.append("BACKUP_INTEGRITY_CHECK_FAILED")
    if expected_schema_fingerprint is not None and fingerprint != expected_schema_fingerprint:
        blockers.append("BACKUP_SCHEMA_FINGERPRINT_MISMATCH")
    if active_writer_count:
        blockers.append("RESTORE_HAS_ACTIVE_WRITER_GENERATION")
    return RestoreReport(
        schema_version=SCHEMA_VERSION,
        backup_path=str(path),
        schema_fingerprint=fingerprint,
        integrity_check=integrity,
        active_writer_count=active_writer_count,
        accepted=not blockers,
        blockers=tuple(blockers),
    )


def scan_unapproved_sqlite_connects(
    root: str | Path,
    *,
    allowed_paths: Iterable[str] = (),
) -> tuple[DirectConnectFinding, ...]:
    root_path = Path(root)
    allowed = {Path(item).as_posix() for item in allowed_paths}
    findings: list[DirectConnectFinding] = []
    for path in sorted(root_path.rglob("*.py")):
        relative = path.relative_to(root_path).as_posix()
        if relative in allowed:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if (
                "sqlite3.connect(" in stripped
                or "aiosqlite.connect(" in stripped
                or "from sqlite3 import connect" in stripped
            ):
                findings.append(
                    DirectConnectFinding(
                        path=relative,
                        line=line_number,
                        snippet=stripped[:240],
                    )
                )
    return tuple(findings)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return _canonical_json(dict(value)).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Mpr43PersistenceError("JSON_PAYLOAD_NOT_CANONICAL") from exc


def _safe_id(value: str, field: str) -> str:
    value = str(value)
    if not _SAFE_ID_RE.fullmatch(value):
        raise Mpr43PersistenceError(f"{field} must be a bounded safe identifier")
    return value


def _sha256(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise Mpr43PersistenceError(f"{field} must be a non-placeholder sha256")
    return lowered


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise Mpr43PersistenceError(f"{field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Mpr43PersistenceError(f"{field} must be a non-negative integer")
    return value


def _strict_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Mpr43PersistenceError(f"{field} must be an integer base-unit value")
    return value


__all__ = [
    "CANONICAL_AUTHORITY_NAME",
    "MIGRATIONS",
    "SCHEMA_VERSION",
    "AuditEvent",
    "BackupManifest",
    "DirectConnectFinding",
    "GenerationFence",
    "InboxEvent",
    "LedgerEntry",
    "Migration",
    "Mpr43PersistenceError",
    "Mpr43State",
    "OutboxEvent",
    "RestoreReport",
    "UnifiedPersistenceAuthority",
    "scan_unapproved_sqlite_connects",
    "validate_restore",
]
