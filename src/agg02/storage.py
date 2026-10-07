"""Durable raw journal and optional analytical Parquet projection for AGG-02."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterable, Iterator, Mapping

from .contracts import Agg02Error, RawEventEnvelope, canonical_hash, canonical_json


@dataclass(frozen=True, slots=True)
class JournalReceipt:
    event_id: str
    inserted: bool
    cursor_key: str
    cursor_offset: int
    receipt_hash: str


@dataclass(frozen=True, slots=True)
class JournalCursor:
    source: str
    partition: str
    offset: int
    slot: int | None
    reconnect_epoch: int


@dataclass(frozen=True, slots=True)
class GapRecord:
    source: str
    partition: str
    reconnect_epoch: int
    from_offset: int
    to_offset: int | None
    reason: str
    closed: bool


class DurableRawJournal:
    """SQLite raw-bytes journal whose cursor advances in the same transaction."""

    def __init__(
        self, path: str | Path, *, max_journal_bytes: int | None = None
    ) -> None:
        if max_journal_bytes is not None and (
            type(max_journal_bytes) is not int or max_journal_bytes < 1
        ):
            raise Agg02Error("AGG02_JOURNAL_BUDGET_INVALID")
        self.max_journal_bytes = max_journal_bytes
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.execute("PRAGMA trusted_schema=OFF")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS raw_events ("
            "event_id TEXT PRIMARY KEY, source TEXT NOT NULL, "
            "partition_name TEXT NOT NULL, cursor_offset INTEGER NOT NULL, "
            "reconnect_epoch INTEGER NOT NULL, slot INTEGER, "
            "payload_sha256 TEXT NOT NULL, envelope_json TEXT NOT NULL, "
            "payload BLOB NOT NULL)"
        )
        self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS raw_events_cursor_idx ON raw_events("
            "source, partition_name, reconnect_epoch, cursor_offset)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS raw_cursors ("
            "source TEXT NOT NULL, partition_name TEXT NOT NULL, "
            "cursor_offset INTEGER NOT NULL, slot INTEGER, "
            "reconnect_epoch INTEGER NOT NULL, "
            "PRIMARY KEY(source, partition_name))"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS raw_gaps ("
            "source TEXT NOT NULL, partition_name TEXT NOT NULL, "
            "reconnect_epoch INTEGER NOT NULL, from_offset INTEGER NOT NULL, "
            "to_offset INTEGER, reason TEXT NOT NULL, closed INTEGER NOT NULL, "
            "PRIMARY KEY(source, partition_name, reconnect_epoch, from_offset))"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS raw_retention_pins ("
            "event_id TEXT NOT NULL, evidence_id TEXT NOT NULL, "
            "PRIMARY KEY(event_id,evidence_id))"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS raw_payload_archives ("
            "event_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL, "
            "original_bytes INTEGER NOT NULL, receipt_hash TEXT NOT NULL)"
        )

    def append(self, envelope: RawEventEnvelope, payload: bytes) -> JournalReceipt:
        if hashlib.sha256(payload).hexdigest() != envelope.payload_sha256:
            raise Agg02Error("AGG02_RAW_PAYLOAD_HASH_MISMATCH")
        envelope_json = canonical_json(
            {
                "event_id": envelope.event_id,
                "identity": envelope.identity,
                "source_id": envelope.source_id,
                "chain_id": envelope.chain_id,
                "received_at_ms": envelope.received_at_ms,
                "available_at_ms": envelope.available_at_ms,
                "decoder_version": envelope.decoder_version,
                "cursor_source": envelope.cursor_source,
                "cursor_partition": envelope.cursor_partition,
                "cursor_offset": envelope.cursor_offset,
                "reconnect_epoch": envelope.reconnect_epoch,
                "slot": envelope.slot,
                "commitment": envelope.commitment,
                "source_event_time_ms": envelope.source_event_time_ms,
                "source_sequence": envelope.source_sequence,
                "uncertainty_ms": envelope.uncertainty_ms,
                "gap_before": envelope.gap_before,
                "payload_sha256": envelope.payload_sha256,
            }
        )
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            existing = self._db.execute(
                "SELECT payload_sha256,envelope_json "
                "FROM raw_events WHERE event_id=?",
                (envelope.event_id,),
            ).fetchone()
            if existing is not None:
                if existing != (envelope.payload_sha256, envelope_json):
                    raise Agg02Error("AGG02_EVENT_ID_REBOUND")
                return self._receipt(envelope, inserted=False)
            if self.max_journal_bytes is not None:
                used = sum(
                    p.stat().st_size
                    for p in (self.path, Path(str(self.path) + "-wal"))
                    if p.exists()
                )
                # Reserve SQLite page/index/WAL expansion before admitting a new event.
                if (
                    used + len(payload) * 3 + len(envelope_json.encode()) * 3 + 65_536
                    > self.max_journal_bytes
                ):
                    raise Agg02Error("AGG02_STORAGE_PRESSURE_ADMISSION_BLOCKED")
            cursor = self._db.execute(
                "SELECT cursor_offset,reconnect_epoch FROM raw_cursors "
                "WHERE source=? AND partition_name=?",
                (envelope.cursor_source, envelope.cursor_partition),
            ).fetchone()
            if cursor is not None:
                previous_offset, previous_epoch = int(cursor[0]), int(cursor[1])
                if envelope.reconnect_epoch < previous_epoch:
                    raise Agg02Error("AGG02_STALE_RECONNECT_EPOCH")
                if envelope.reconnect_epoch == previous_epoch:
                    if envelope.cursor_offset <= previous_offset:
                        raise Agg02Error("AGG02_CURSOR_MOVED_BACKWARDS")
                    if (
                        envelope.cursor_offset > previous_offset + 1
                        and not envelope.gap_before
                    ):
                        raise Agg02Error("AGG02_UNDECLARED_CURSOR_GAP")
            self._db.execute(
                "INSERT INTO raw_events("
                "event_id,source,partition_name,cursor_offset,reconnect_epoch,"
                "slot,payload_sha256,envelope_json,payload"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    envelope.event_id,
                    envelope.cursor_source,
                    envelope.cursor_partition,
                    envelope.cursor_offset,
                    envelope.reconnect_epoch,
                    envelope.slot,
                    envelope.payload_sha256,
                    envelope_json,
                    payload,
                ),
            )
            self._db.execute(
                "INSERT INTO raw_cursors("
                "source,partition_name,cursor_offset,slot,reconnect_epoch"
                ") VALUES (?,?,?,?,?) "
                "ON CONFLICT(source,partition_name) DO UPDATE SET "
                "cursor_offset=excluded.cursor_offset,"
                "slot=excluded.slot,reconnect_epoch=excluded.reconnect_epoch",
                (
                    envelope.cursor_source,
                    envelope.cursor_partition,
                    envelope.cursor_offset,
                    envelope.slot,
                    envelope.reconnect_epoch,
                ),
            )
        return self._receipt(envelope, inserted=True)

    def _receipt(self, envelope: RawEventEnvelope, *, inserted: bool) -> JournalReceipt:
        digest = canonical_hash(
            {
                "event_id": envelope.event_id,
                "identity": envelope.identity,
                "cursor_key": envelope.cursor_key,
                "cursor_offset": envelope.cursor_offset,
                "inserted": inserted,
            }
        )
        return JournalReceipt(
            envelope.event_id,
            inserted,
            envelope.cursor_key,
            envelope.cursor_offset,
            digest,
        )

    def cursor(self, source: str, partition: str) -> JournalCursor | None:
        row = self._db.execute(
            "SELECT cursor_offset,slot,reconnect_epoch FROM raw_cursors "
            "WHERE source=? AND partition_name=?",
            (source, partition),
        ).fetchone()
        if row is None:
            return None
        return JournalCursor(source, partition, int(row[0]), row[1], int(row[2]))

    def payload(self, event_id: str) -> bytes | None:
        row = self._db.execute(
            "SELECT payload FROM raw_events WHERE event_id=?", (event_id,)
        ).fetchone()
        if row is None:
            return None
        archived = self._db.execute(
            "SELECT manifest_json FROM raw_payload_archives WHERE event_id=?",
            (event_id,),
        ).fetchone()
        if archived is None:
            return bytes(row[0])
        manifest = DatasetManifest(**json.loads(archived[0]))
        for event in DatasetReplayReader.read(manifest):
            if event["event_id"] == event_id:
                value = event["payload"]
                if not isinstance(value, bytes):
                    raise Agg02Error("AGG02_ARCHIVED_PAYLOAD_TYPE_INVALID")
                payload = value
                if hashlib.sha256(payload).hexdigest() != event["payload_sha256"]:
                    raise Agg02Error("AGG02_ARCHIVED_PAYLOAD_HASH_MISMATCH")
                return payload
        raise Agg02Error("AGG02_ARCHIVED_EVENT_MISSING")

    def retention_rows(self) -> tuple[dict[str, object], ...]:
        """Read-only projection of the authoritative journal, including exact bytes."""
        return tuple(self.iter_retention_rows())

    def iter_retention_rows(
        self,
        *,
        max_available_at_ms: int | None = None,
        event_ids: set[str] | None = None,
    ) -> Iterator[dict[str, object]]:
        rows = self._db.execute(
            "SELECT event_id,envelope_json FROM raw_events "
            "ORDER BY reconnect_epoch,source,partition_name,cursor_offset,event_id"
        )
        for event_id, envelope in rows:
            parsed = json.loads(envelope)
            if event_ids is not None and event_id not in event_ids:
                continue
            if (
                max_available_at_ms is not None
                and parsed["available_at_ms"] > max_available_at_ms
            ):
                continue
            yield {
                **parsed,
                "envelope_json": envelope,
                "payload": self.payload(event_id),
            }

    def pin_retention(self, event_ids: Iterable[str], *, evidence_id: str) -> None:
        """Explicit evidence pin, serialized with raw archival in this owner."""
        if not evidence_id:
            raise Agg02Error("AGG02_RETENTION_EVIDENCE_ID_REQUIRED")
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            for event_id in event_ids:
                if self.payload(event_id) is None:
                    raise Agg02Error("AGG02_RETENTION_EVENT_MISSING")
                self._db.execute(
                    "INSERT OR IGNORE INTO raw_retention_pins VALUES (?,?)",
                    (event_id, evidence_id),
                )

    def retention_pins(self) -> dict[str, tuple[str, ...]]:
        result: dict[str, list[str]] = {}
        for event_id, evidence_id in self._db.execute(
            "SELECT event_id,evidence_id FROM raw_retention_pins ORDER BY event_id,evidence_id"
        ):
            result.setdefault(event_id, []).append(evidence_id)
        return {key: tuple(value) for key, value in result.items()}

    def retention_storage_inventory(self) -> tuple[dict[str, object], ...]:
        """Bounded metadata-only storage view for retention/pressure planning.

        This view never rehydrates archived Parquet payloads.  It reports only
        the current inline SQLite payload bytes and owner-side pin/archive state.
        """
        rows = self._db.execute(
            "SELECT e.event_id,LENGTH(e.payload),"
            "EXISTS(SELECT 1 FROM raw_payload_archives a WHERE a.event_id=e.event_id),"
            "EXISTS(SELECT 1 FROM raw_retention_pins p WHERE p.event_id=e.event_id),"
            "e.envelope_json "
            "FROM raw_events e "
            "ORDER BY e.reconnect_epoch,e.source,e.partition_name,e.cursor_offset,e.event_id"
        ).fetchall()
        return tuple(
            {
                "event_id": str(event_id),
                "inline_payload_bytes": int(inline_bytes or 0),
                "archived": bool(archived),
                "pinned": bool(pinned),
                "available_at_ms": json.loads(envelope_json)["available_at_ms"],
                "gap_before": json.loads(envelope_json)["gap_before"],
                "envelope_bytes": len(envelope_json.encode("utf-8")),
            }
            for event_id, inline_bytes, archived, pinned, envelope_json in rows
        )

    def archive_verified_payloads(
        self,
        manifest: DatasetManifest,
        *,
        event_ids: tuple[str, ...],
        now_ms: int,
        minimum_age_ms: int,
        receipt_hash: str,
    ) -> int:
        """Reversible offload only: keep envelopes/cursors and exact Parquet replay.

        The intelligence policy gate must supply its receipt before calling this.
        Pins and payload identities are checked again under the owner write lock.
        No row, cursor, gap, or archived payload is deleted by this operation.
        """
        if (
            type(now_ms) is not int
            or type(minimum_age_ms) is not int
            or minimum_age_ms < 1
        ):
            raise Agg02Error("AGG02_RETENTION_CLOCK_INVALID")
        replay = {str(r["event_id"]): r for r in DatasetReplayReader.read(manifest)}
        if len(replay) != manifest.row_count or len(set(event_ids)) != len(event_ids):
            raise Agg02Error("AGG02_ARCHIVE_DUPLICATE_EVENT")
        serialized = canonical_json(asdict(manifest))
        count = 0
        with self._db:
            self._db.execute("BEGIN IMMEDIATE")
            for event_id in event_ids:
                if self._db.execute(
                    "SELECT 1 FROM raw_retention_pins WHERE event_id=?", (event_id,)
                ).fetchone():
                    raise Agg02Error("AGG02_RETENTION_EVENT_PINNED")
                row = self._db.execute(
                    "SELECT envelope_json,payload,payload_sha256 FROM raw_events WHERE event_id=?",
                    (event_id,),
                ).fetchone()
                archived = replay.get(event_id)
                if row is None or archived is None:
                    raise Agg02Error("AGG02_RETENTION_EVENT_MISSING")
                previous_archive = self._db.execute(
                    "SELECT manifest_json,receipt_hash FROM raw_payload_archives WHERE event_id=?",
                    (event_id,),
                ).fetchone()
                if previous_archive:
                    if previous_archive != (serialized, receipt_hash):
                        raise Agg02Error("AGG02_ARCHIVE_LINEAGE_MISMATCH")
                    continue
                envelope = json.loads(row[0])
                archived_payload = archived["payload"]
                if not isinstance(archived_payload, bytes):
                    raise Agg02Error("AGG02_ARCHIVED_PAYLOAD_TYPE_INVALID")
                if now_ms - envelope["available_at_ms"] < minimum_age_ms:
                    raise Agg02Error("AGG02_RETENTION_EVENT_TOO_YOUNG")
                if (
                    archived["envelope_json"] != row[0]
                    or archived_payload != bytes(row[1])
                    or hashlib.sha256(archived_payload).hexdigest() != row[2]
                ):
                    raise Agg02Error("AGG02_ARCHIVE_LINEAGE_MISMATCH")
                if envelope["gap_before"]:
                    raise Agg02Error("AGG02_RETENTION_GAP_PIN_REQUIRED")
                self._db.execute(
                    "INSERT INTO raw_payload_archives VALUES (?,?,?,?)",
                    (event_id, serialized, len(row[1]), receipt_hash),
                )
                self._db.execute(
                    "UPDATE raw_events SET payload=? WHERE event_id=?", (b"", event_id)
                )
                count += 1
        return count

    def replay_event_ids(self) -> tuple[str, ...]:
        rows = self._db.execute(
            "SELECT event_id FROM raw_events "
            "ORDER BY reconnect_epoch,source,partition_name,cursor_offset,event_id"
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def record_gap(
        self,
        *,
        source: str,
        partition: str,
        reconnect_epoch: int,
        from_offset: int,
        to_offset: int | None,
        reason: str,
    ) -> GapRecord:
        if not source or not partition or not reason:
            raise Agg02Error("AGG02_INVALID_GAP_RECORD")
        with self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO raw_gaps("
                "source,partition_name,reconnect_epoch,from_offset,to_offset,"
                "reason,closed) VALUES (?,?,?,?,?,?,0)",
                (source, partition, reconnect_epoch, from_offset, to_offset, reason),
            )
        return GapRecord(
            source,
            partition,
            reconnect_epoch,
            from_offset,
            to_offset,
            reason,
            False,
        )

    def close_gap(
        self,
        *,
        source: str,
        partition: str,
        reconnect_epoch: int,
        from_offset: int,
    ) -> None:
        with self._db:
            changed = self._db.execute(
                "UPDATE raw_gaps SET closed=1 "
                "WHERE source=? AND partition_name=? AND reconnect_epoch=? "
                "AND from_offset=? AND closed=0",
                (source, partition, reconnect_epoch, from_offset),
            ).rowcount
        if changed != 1:
            raise Agg02Error("AGG02_GAP_NOT_OPEN")

    def open_gaps(self) -> tuple[GapRecord, ...]:
        rows = self._db.execute(
            "SELECT source,partition_name,reconnect_epoch,from_offset,to_offset,"
            "reason,closed FROM raw_gaps WHERE closed=0 "
            "ORDER BY source,partition_name,reconnect_epoch,from_offset"
        ).fetchall()
        return tuple(
            GapRecord(
                str(row[0]),
                str(row[1]),
                int(row[2]),
                int(row[3]),
                None if row[4] is None else int(row[4]),
                str(row[5]),
                bool(row[6]),
            )
            for row in rows
        )

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "DurableRawJournal":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    dataset_id: str
    schema_version: str
    path: str
    row_count: int
    sha256: str
    min_available_at_ms: int | None
    max_available_at_ms: int | None


class AnalyticalDatasetPublisher:
    """Optional Parquet projection; never an authoritative financial ledger."""

    def publish(
        self,
        *,
        dataset_id: str,
        schema_version: str,
        rows: Iterable[Mapping[str, object]],
        destination: str | Path,
        compression: str = "snappy",
    ) -> DatasetManifest:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise Agg02Error("AGG02_ANALYTICS_EXTRA_REQUIRED") from exc
        normalized = [dict(row) for row in rows]
        if not normalized:
            raise Agg02Error("AGG02_EMPTY_DATASET_PARTITION")
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        table = pa.Table.from_pylist(normalized)
        pq.write_table(table, temporary, compression=compression)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        os.replace(temporary, path)
        available_values: list[int] = []
        for row in normalized:
            available_at = row.get("available_at_ms")
            if isinstance(available_at, int) and not isinstance(available_at, bool):
                available_values.append(available_at)
        return DatasetManifest(
            dataset_id=dataset_id,
            schema_version=schema_version,
            path=str(path),
            row_count=len(normalized),
            sha256=digest,
            min_available_at_ms=min(available_values) if available_values else None,
            max_available_at_ms=max(available_values) if available_values else None,
        )

    @staticmethod
    def verify(manifest: DatasetManifest) -> None:
        path = Path(manifest.path)
        if not path.is_file():
            raise Agg02Error("AGG02_DATASET_MISSING")
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest.sha256:
            raise Agg02Error("AGG02_DATASET_CHECKSUM_MISMATCH")


class DatasetReplayReader:
    """Checksum/schema-bound analytical replay with optional as-known cutoff."""

    @staticmethod
    def read(
        manifest: DatasetManifest,
        *,
        expected_schema_version: str | None = None,
        max_available_at_ms: int | None = None,
    ) -> tuple[dict[str, object], ...]:
        AnalyticalDatasetPublisher.verify(manifest)
        if (
            expected_schema_version is not None
            and manifest.schema_version != expected_schema_version
        ):
            raise Agg02Error("AGG02_REPLAY_SCHEMA_MISMATCH")
        if max_available_at_ms is not None and (
            type(max_available_at_ms) is not int or max_available_at_ms < 0
        ):
            raise Agg02Error("AGG02_REPLAY_CUTOFF_INVALID")
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise Agg02Error("AGG02_ANALYTICS_EXTRA_REQUIRED") from exc

        rows = tuple(dict(row) for row in pq.read_table(manifest.path).to_pylist())
        if len(rows) != manifest.row_count:
            raise Agg02Error("AGG02_REPLAY_ROW_COUNT_MISMATCH")
        available_values = [
            value
            for row in rows
            if (
                isinstance((value := row.get("available_at_ms")), int)
                and not isinstance(value, bool)
            )
        ]
        if available_values and (
            min(available_values) != manifest.min_available_at_ms
            or max(available_values) != manifest.max_available_at_ms
        ):
            raise Agg02Error("AGG02_REPLAY_AVAILABILITY_RANGE_MISMATCH")
        if max_available_at_ms is None:
            return rows

        selected: list[dict[str, object]] = []
        for row in rows:
            available_at = row.get("available_at_ms")
            if not isinstance(available_at, int) or isinstance(available_at, bool):
                raise Agg02Error("AGG02_REPLAY_AVAILABLE_AT_REQUIRED")
            if available_at <= max_available_at_ms:
                selected.append(row)
        return tuple(selected)
