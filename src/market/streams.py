"""Durable cursors, reconnect epochs and atomic observation publication."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Iterable, Mapping

from .observations import (
    CompletenessPolicy,
    CompletenessState,
    MarketObservationV2,
    ObservationBatch,
    ObservationError,
    ObservationWatermark,
    SourceCursor,
)


@dataclass(frozen=True, slots=True)
class FanoutMatrix:
    """Closed-world source requirements for every detector/strategy consumer."""

    requirements: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        if not self.requirements:
            raise ObservationError("fanout matrix cannot be empty")
        for strategy, sources in self.requirements.items():
            if not strategy or not sources:
                raise ObservationError("fanout strategy and sources are required")
            if len(sources) != len(set(sources)):
                raise ObservationError("fanout source requirements must be unique")

    def required_sources(self, strategy: str) -> tuple[str, ...]:
        try:
            return self.requirements[strategy]
        except KeyError as exc:
            raise ObservationError(f"unregistered fanout strategy: {strategy}") from exc


class DurableCursorStore:
    """Small atomic JSON cursor store suitable for replay/restart qualification."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, SourceCursor]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "mpr042.source-cursors.v1":
            raise ObservationError("unsupported source cursor snapshot")
        cursors: dict[str, SourceCursor] = {}
        for item in payload.get("cursors", ()):
            cursor = SourceCursor(
                source=str(item["source"]),
                partition=str(item["partition"]),
                offset=item["offset"],
                slot=item["slot"],
                reconnect_epoch=item["reconnect_epoch"],
            )
            cursors[cursor.key] = cursor
        return cursors

    def save(self, cursors: Mapping[str, SourceCursor]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "mpr042.source-cursors.v1",
            "cursors": [
                {
                    "source": cursor.source,
                    "partition": cursor.partition,
                    "offset": cursor.offset,
                    "slot": cursor.slot,
                    "reconnect_epoch": cursor.reconnect_epoch,
                }
                for cursor in sorted(cursors.values(), key=lambda item: item.key)
            ],
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)


class WatermarkedObservationBuffer:
    """Stage source events and atomically publish one coherent batch.

    A reconnect opens a new epoch and blocks publication until every required
    source has explicitly completed backfill in that epoch.  Duplicate and
    reordered offsets are rejected before they can affect detector-visible state.
    """

    def __init__(
        self,
        *,
        fanout: FanoutMatrix,
        cursor_store: DurableCursorStore | None = None,
    ) -> None:
        self.fanout = fanout
        self.cursor_store = cursor_store
        self._cursors = cursor_store.load() if cursor_store is not None else {}
        self._epoch = max(
            (cursor.reconnect_epoch for cursor in self._cursors.values()), default=0
        )
        self._observations: dict[str, MarketObservationV2] = {}
        # Persisted cursors prove resume position, not source completeness.
        # A restarted process must explicitly finish backfill before publish.
        self._backfill_complete: set[str] = set()

    @property
    def reconnect_epoch(self) -> int:
        return self._epoch

    def begin_reconnect(self) -> int:
        self._epoch += 1
        self._backfill_complete.clear()
        self._observations.clear()
        return self._epoch

    def ingest(self, observation: MarketObservationV2) -> bool:
        cursor = observation.cursor
        if cursor is None:
            raise ObservationError("stream observation requires a source cursor")
        if cursor.reconnect_epoch != self._epoch:
            raise ObservationError(
                "stream observation belongs to a stale reconnect epoch"
            )
        previous = self._cursors.get(cursor.key)
        if previous is not None and previous.reconnect_epoch == cursor.reconnect_epoch:
            if cursor.offset == previous.offset:
                return False
            if cursor.offset < previous.offset:
                raise ObservationError("source cursor offset moved backwards")
            if cursor.slot < previous.slot:
                raise ObservationError("source cursor slot moved backwards")
        self._cursors[cursor.key] = cursor
        if observation.supersedes_id is not None:
            self._observations.pop(observation.supersedes_id, None)
        self._observations[observation.observation_id] = observation
        if self.cursor_store is not None:
            self.cursor_store.save(self._cursors)
        return True

    def mark_backfill_complete(self, source: str) -> None:
        if not source:
            raise ObservationError("backfill source is required")
        if source not in {cursor.source for cursor in self._cursors.values()}:
            raise ObservationError("cannot complete backfill without a source cursor")
        self._backfill_complete.add(source)

    def publish(
        self,
        strategy: str,
        *,
        max_slot_skew: int = 0,
        minimum_observations: int = 1,
    ) -> ObservationBatch:
        required = self.fanout.required_sources(strategy)
        relevant_cursors = tuple(
            cursor
            for cursor in self._cursors.values()
            if cursor.source in required and cursor.reconnect_epoch == self._epoch
        )
        missing_backfill = sorted(set(required) - self._backfill_complete)
        missing_cursors = sorted(
            set(required) - {cursor.source for cursor in relevant_cursors}
        )
        reasons = tuple(
            [f"backfill_pending:{source}" for source in missing_backfill]
            + [f"missing_cursor:{source}" for source in missing_cursors]
        )
        if relevant_cursors:
            minimum_slot = min(cursor.slot for cursor in relevant_cursors)
            maximum_slot = max(cursor.slot for cursor in relevant_cursors)
            watermark = ObservationWatermark(
                cursors=relevant_cursors,
                minimum_slot=minimum_slot,
                maximum_slot=maximum_slot,
                reconnect_epoch=self._epoch,
            )
        else:
            placeholders = tuple(
                SourceCursor(source, "missing", 0, 0, self._epoch)
                for source in required
            )
            watermark = ObservationWatermark(
                cursors=placeholders,
                minimum_slot=0,
                maximum_slot=0,
                reconnect_epoch=self._epoch,
            )
        policy = CompletenessPolicy(
            policy_id=f"mpr042:{strategy}",
            required_sources=required,
            max_slot_skew=max_slot_skew,
            minimum_observations=minimum_observations,
        )
        observations = tuple(
            item
            for item in self._observations.values()
            if item.cursor is not None and item.cursor.source in required
        )
        requested_state = CompletenessState.BLOCKED if reasons else None
        return ObservationBatch(
            observations,
            watermark=watermark,
            policy=policy,
            completeness=requested_state,
            degraded_reasons=reasons,
        )

    def invalidate_generation(self, generation_identity: str) -> tuple[str, ...]:
        invalidated = tuple(
            observation_id
            for observation_id, observation in self._observations.items()
            if observation.generation.identity == generation_identity
        )
        for observation_id in invalidated:
            self._observations.pop(observation_id, None)
        return invalidated

    def cursors(self) -> tuple[SourceCursor, ...]:
        return tuple(sorted(self._cursors.values(), key=lambda item: item.key))


@dataclass(frozen=True, slots=True)
class RawStreamEvent:
    """Append-only local replay evidence, including native sequence and fork identity."""

    source: str
    partition: str
    generation: int
    cursor: int
    available_at_ns: int
    observed_at_ns: int
    market_id: str
    revision: str
    payload_json: str
    block_hash: str
    parent_hash: str
    kind: str = "snapshot"
    supersedes_hash: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "source",
            "partition",
            "market_id",
            "revision",
            "block_hash",
            "parent_hash",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ObservationError(f"{field} required")
        for field in ("generation", "cursor", "available_at_ns", "observed_at_ns"):
            if type(getattr(self, field)) is not int or getattr(self, field) < 0:
                raise ObservationError(f"{field} requires nonnegative integer")
        if self.available_at_ns < self.observed_at_ns:
            raise ObservationError("availability precedes observation")
        if self.kind not in {"snapshot", "delta", "retraction"}:
            raise ObservationError("unsupported raw event kind")
        if self.kind == "retraction" and not self.supersedes_hash:
            raise ObservationError("retraction needs evidence target")
        if (
            not isinstance(self.payload_json, str)
            or len(self.payload_json.encode("utf-8")) > 1_000_000
        ):
            raise ObservationError("raw event payload bound exceeded")
        body = json.loads(self.payload_json)
        canonical = json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        object.__setattr__(self, "payload_json", canonical)

    @property
    def identity(self) -> str:
        from dataclasses import asdict
        import hashlib

        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class RecoverableStreamJournal:
    """One local raw-state writer; no financial ledger or provider connection.

    Event, cursor and reconstructible head commit together. Sequence gaps and
    fork changes require a snapshot. Reopening derives state from committed raw
    evidence rather than treating a saved cursor as a saved order book.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        max_events: int = 100_000,
        max_payload_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (max_events, max_payload_bytes)
        ):
            raise ObservationError("positive integer journal budgets required")
        self.max_events = max_events
        self.max_payload_bytes = max_payload_bytes
        import sqlite3

        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS raw_stream_events (identity TEXT PRIMARY KEY, source TEXT NOT NULL, partition TEXT NOT NULL, generation INTEGER NOT NULL, cursor INTEGER NOT NULL, available_ns INTEGER NOT NULL, payload TEXT NOT NULL, UNIQUE(source,partition,generation,cursor))"
        )

    def close(self) -> None:
        self.db.close()

    def events(self, *, available_at_ns: int) -> tuple[RawStreamEvent, ...]:
        rows = self.db.execute(
            "SELECT payload FROM raw_stream_events WHERE available_ns<=? ORDER BY available_ns,source,partition,generation,cursor,identity",
            (available_at_ns,),
        ).fetchall()
        return tuple(RawStreamEvent(**json.loads(row[0])) for row in rows)

    def append(self, event: RawStreamEvent) -> bool:
        from dataclasses import asdict

        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute(
                "SELECT identity FROM raw_stream_events WHERE source=? AND partition=? AND generation=? AND cursor=?",
                (event.source, event.partition, event.generation, event.cursor),
            ).fetchone()
            if prior:
                if prior[0] != event.identity:
                    raise ObservationError("same cursor has different payload")
                self.db.execute("COMMIT")
                return False
            count, stored_bytes = self.db.execute(
                "SELECT COUNT(*),COALESCE(SUM(LENGTH(CAST(payload AS BLOB))),0) FROM raw_stream_events"
            ).fetchone()
            serialized = json.dumps(asdict(event), sort_keys=True)
            if (
                count >= self.max_events
                or stored_bytes + len(serialized.encode("utf-8"))
                > self.max_payload_bytes
            ):
                raise ObservationError("raw journal storage budget exhausted")
            row = self.db.execute(
                "SELECT payload FROM raw_stream_events WHERE source=? AND partition=? ORDER BY generation DESC,cursor DESC LIMIT 1",
                (event.source, event.partition),
            ).fetchone()
            if row:
                previous = RawStreamEvent(**json.loads(row[0]))
                if event.generation < previous.generation or (
                    event.generation == previous.generation
                    and event.cursor <= previous.cursor
                ):
                    raise ObservationError("raw stream cursor regressed")
                if event.available_at_ns < previous.available_at_ns:
                    raise ObservationError("availability regressed")
                continuous = (
                    event.generation == previous.generation
                    and event.cursor == previous.cursor + 1
                )
                same_fork = (
                    event.block_hash == previous.block_hash
                    or event.parent_hash == previous.block_hash
                )
                if event.kind == "delta" and (not continuous or not same_fork):
                    raise ObservationError("gap or fork requires snapshot repair")
            elif event.kind != "snapshot":
                raise ObservationError("first event requires snapshot")
            if (
                event.kind == "retraction"
                and self.db.execute(
                    "SELECT 1 FROM raw_stream_events WHERE identity=?",
                    (event.supersedes_hash,),
                ).fetchone()
                is None
            ):
                raise ObservationError("unknown retraction target")
            self.db.execute(
                "INSERT INTO raw_stream_events VALUES(?,?,?,?,?,?,?)",
                (
                    event.identity,
                    event.source,
                    event.partition,
                    event.generation,
                    event.cursor,
                    event.available_at_ns,
                    json.dumps(asdict(event), sort_keys=True),
                ),
            )
            self.db.execute("COMMIT")
            return True
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def reconstruct(
        self, *, source: str, partition: str, available_at_ns: int
    ) -> Mapping[str, object]:
        events = tuple(
            e
            for e in self.events(available_at_ns=available_at_ns)
            if e.source == source and e.partition == partition
        )
        retracted = {e.supersedes_hash for e in events if e.kind == "retraction"}
        state: dict[str, object] = {}
        valid = False
        previous: RawStreamEvent | None = None
        for event in events:
            if event.kind == "retraction":
                continue
            if event.identity in retracted:
                valid = False
                continue
            if event.kind == "snapshot":
                body = json.loads(event.payload_json)
                if not isinstance(body, dict):
                    raise ObservationError("snapshot state must be a mapping")
                state = body
                valid = True
            else:
                if (
                    not valid
                    or previous is None
                    or event.generation != previous.generation
                    or event.cursor != previous.cursor + 1
                ):
                    valid = False
                    continue
                patch = json.loads(event.payload_json)
                if not isinstance(patch, dict):
                    raise ObservationError("delta state must be a mapping")
                for key, value in patch.items():
                    if value is None:
                        state.pop(key, None)
                    else:
                        state[key] = value
            previous = event
        if not valid:
            raise ObservationError("state requires repaired snapshot")
        return state
