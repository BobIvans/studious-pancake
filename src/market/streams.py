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
