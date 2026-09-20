"""Durable raw journal and optional analytical Parquet projection for AGG-02."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sqlite3
from typing import Iterable, Mapping

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

    def __init__(self, path: str | Path) -> None:
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
        return None if row is None else bytes(row[0])

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
        pq.write_table(table, temporary)
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
