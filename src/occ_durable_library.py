"""Durable, namespace-scoped OCC context source storage.

This is a content/provenance owner only.  It does not schedule jobs, execute
commands, access the network, sign transactions, or grant live authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Collection, Mapping

SCHEMA = "occ.durable-library.v1"
MAX_CONTENT_BYTES = 4 * 1024 * 1024
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class OCCDurableError(ValueError):
    """Raised when an OCC source or access contract is invalid."""


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _identifier(field: str, value: object) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise OCCDurableError(f"{field.upper()}_INVALID")
    return value


def _sha256(field: str, value: object) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise OCCDurableError(f"{field.upper()}_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class SourceVersion:
    namespace: str
    source_id: str
    version_sha256: str
    content_sha256: str
    byte_length: int
    first_seen_event_seq: int
    head_event_seq: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OCCDurableLibrary:
    """SQLite source/version registry with append-only sync history."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS source_versions (
                    namespace TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    version_sha256 TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    content_text TEXT NOT NULL,
                    byte_length INTEGER NOT NULL CHECK(byte_length >= 0),
                    first_seen_event_seq INTEGER NOT NULL CHECK(first_seen_event_seq >= 1),
                    PRIMARY KEY(namespace, source_id, version_sha256)
                );
                CREATE TABLE IF NOT EXISTS source_sync_events (
                    namespace TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    event_seq INTEGER NOT NULL CHECK(event_seq >= 1),
                    version_sha256 TEXT NOT NULL,
                    previous_version_sha256 TEXT,
                    outcome TEXT NOT NULL CHECK(outcome IN ('CREATED', 'UPDATED')),
                    PRIMARY KEY(namespace, source_id, event_seq),
                    FOREIGN KEY(namespace, source_id, version_sha256)
                        REFERENCES source_versions(namespace, source_id, version_sha256)
                        ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS source_heads (
                    namespace TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    version_sha256 TEXT NOT NULL,
                    event_seq INTEGER NOT NULL CHECK(event_seq >= 1),
                    PRIMARY KEY(namespace, source_id),
                    FOREIGN KEY(namespace, source_id, version_sha256)
                        REFERENCES source_versions(namespace, source_id, version_sha256)
                        ON DELETE RESTRICT
                );
                """)

    @staticmethod
    def _authorize(namespace: object, allowed_namespaces: Collection[str]) -> str:
        resolved = _identifier("namespace", namespace)
        if resolved not in frozenset(allowed_namespaces):
            raise OCCDurableError("SOURCE_NAMESPACE_DENIED")
        return resolved

    def sync(
        self,
        *,
        namespace: str,
        source_id: str,
        content: str,
        allowed_namespaces: Collection[str],
    ) -> Mapping[str, Any]:
        namespace = self._authorize(namespace, allowed_namespaces)
        source_id = _identifier("source_id", source_id)
        if not isinstance(content, str):
            raise OCCDurableError("SOURCE_CONTENT_INVALID")
        raw = content.encode("utf-8")
        if len(raw) > MAX_CONTENT_BYTES:
            raise OCCDurableError("SOURCE_CONTENT_TOO_LARGE")
        content_sha256 = hashlib.sha256(raw).hexdigest()
        version_sha256 = digest(
            {
                "schema_version": SCHEMA,
                "namespace": namespace,
                "source_id": source_id,
                "content_sha256": content_sha256,
            }
        )

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            head = connection.execute(
                """
                SELECT version_sha256, event_seq
                FROM source_heads
                WHERE namespace=? AND source_id=?
                """,
                (namespace, source_id),
            ).fetchone()
            if head is not None and head["version_sha256"] == version_sha256:
                connection.commit()
                return {
                    "schema_version": SCHEMA,
                    "namespace": namespace,
                    "source_id": source_id,
                    "version_sha256": version_sha256,
                    "content_sha256": content_sha256,
                    "event_seq": int(head["event_seq"]),
                    "duplicate": True,
                    "history_appended": False,
                }

            event_seq = 1 if head is None else int(head["event_seq"]) + 1
            connection.execute(
                """
                INSERT OR IGNORE INTO source_versions(
                    namespace, source_id, version_sha256, content_sha256,
                    content_text, byte_length, first_seen_event_seq
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    namespace,
                    source_id,
                    version_sha256,
                    content_sha256,
                    content,
                    len(raw),
                    event_seq,
                ),
            )
            connection.execute(
                """
                INSERT INTO source_sync_events(
                    namespace, source_id, event_seq, version_sha256,
                    previous_version_sha256, outcome
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    namespace,
                    source_id,
                    event_seq,
                    version_sha256,
                    None if head is None else str(head["version_sha256"]),
                    "CREATED" if head is None else "UPDATED",
                ),
            )
            connection.execute(
                """
                INSERT INTO source_heads(namespace, source_id, version_sha256, event_seq)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, source_id) DO UPDATE SET
                    version_sha256=excluded.version_sha256,
                    event_seq=excluded.event_seq
                """,
                (namespace, source_id, version_sha256, event_seq),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        return {
            "schema_version": SCHEMA,
            "namespace": namespace,
            "source_id": source_id,
            "version_sha256": version_sha256,
            "content_sha256": content_sha256,
            "event_seq": event_seq,
            "duplicate": False,
            "history_appended": True,
        }

    def get_version(
        self,
        *,
        namespace: str,
        source_id: str,
        version_sha256: str,
        allowed_namespaces: Collection[str],
    ) -> SourceVersion:
        namespace = self._authorize(namespace, allowed_namespaces)
        source_id = _identifier("source_id", source_id)
        version_sha256 = _sha256("version_sha256", version_sha256)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT v.namespace, v.source_id, v.version_sha256,
                       v.content_sha256, v.byte_length, v.first_seen_event_seq,
                       h.event_seq AS head_event_seq
                FROM source_versions AS v
                LEFT JOIN source_heads AS h
                  ON h.namespace=v.namespace AND h.source_id=v.source_id
                 AND h.version_sha256=v.version_sha256
                WHERE v.namespace=? AND v.source_id=? AND v.version_sha256=?
                """,
                (namespace, source_id, version_sha256),
            ).fetchone()
        if row is None:
            raise OCCDurableError("SOURCE_VERSION_NOT_FOUND")
        return SourceVersion(
            namespace=str(row["namespace"]),
            source_id=str(row["source_id"]),
            version_sha256=str(row["version_sha256"]),
            content_sha256=str(row["content_sha256"]),
            byte_length=int(row["byte_length"]),
            first_seen_event_seq=int(row["first_seen_event_seq"]),
            head_event_seq=(
                None if row["head_event_seq"] is None else int(row["head_event_seq"])
            ),
        )

    def latest(
        self,
        *,
        namespace: str,
        source_id: str,
        allowed_namespaces: Collection[str],
    ) -> SourceVersion:
        namespace = self._authorize(namespace, allowed_namespaces)
        source_id = _identifier("source_id", source_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT version_sha256
                FROM source_heads
                WHERE namespace=? AND source_id=?
                """,
                (namespace, source_id),
            ).fetchone()
        if row is None:
            raise OCCDurableError("SOURCE_NOT_FOUND")
        return self.get_version(
            namespace=namespace,
            source_id=source_id,
            version_sha256=str(row["version_sha256"]),
            allowed_namespaces=allowed_namespaces,
        )

    def verify_current_version(
        self,
        *,
        namespace: str,
        source_id: str,
        version_sha256: str,
        allowed_namespaces: Collection[str],
    ) -> SourceVersion:
        version_sha256 = _sha256("version_sha256", version_sha256)
        current = self.latest(
            namespace=namespace,
            source_id=source_id,
            allowed_namespaces=allowed_namespaces,
        )
        if current.version_sha256 != version_sha256:
            raise OCCDurableError("STALE_CONTEXT_VERSION")
        return current

    def history(
        self,
        *,
        namespace: str,
        source_id: str,
        allowed_namespaces: Collection[str],
    ) -> tuple[Mapping[str, Any], ...]:
        namespace = self._authorize(namespace, allowed_namespaces)
        source_id = _identifier("source_id", source_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_seq, version_sha256, previous_version_sha256, outcome
                FROM source_sync_events
                WHERE namespace=? AND source_id=?
                ORDER BY event_seq
                """,
                (namespace, source_id),
            ).fetchall()
        return tuple(
            {
                "event_seq": int(row["event_seq"]),
                "version_sha256": str(row["version_sha256"]),
                "previous_version_sha256": (
                    None
                    if row["previous_version_sha256"] is None
                    else str(row["previous_version_sha256"])
                ),
                "outcome": str(row["outcome"]),
            }
            for row in rows
        )
