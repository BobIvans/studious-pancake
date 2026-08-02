from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one patch target, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "src/market/observations.py",
    "class RecordedSnapshotSource:\n"
    "    def __init__(self, quotes: Iterable[MarketObservationV2] = ()) -> None:\n"
    "        self._batch = SnapshotSet(quotes)\n",
    "class RecordedSnapshotSource:\n"
    "    def __init__(self, quotes: Iterable[MarketObservationV2] = ()) -> None:\n"
    "        self._batch: ObservationBatch = SnapshotSet(quotes)\n",
)

replace_once(
    "src/market/cache.py",
    "        self._inflight: dict[str, asyncio.Task[Any]] = {}\n",
    "        self._inflight: dict[str, asyncio.Future[Any]] = {}\n",
)
replace_once(
    "src/market/cache.py",
    "                task = asyncio.create_task(factory())\n",
    "                task = asyncio.ensure_future(factory())\n",
)

replace_once(
    "src/market/streams.py",
    "        self._backfill_complete: set[str] = {\n"
    "            cursor.source for cursor in self._cursors.values()\n"
    "        }\n",
    "        # Persisted cursors prove resume position, not source completeness.\n"
    "        # A restarted process must explicitly finish backfill before publish.\n"
    "        self._backfill_complete: set[str] = set()\n",
)

replace_once(
    "src/runtime_discovery_coordinator.py",
    "            max_slot_skew=max(0, maximum_slot - minimum_slot),\n",
    "            max_slot_skew=max(\n"
    "                item.pair.max_slot_skew\n"
    "                for item in self.universe.pairs\n"
    "                if item.required\n"
    "            ),\n",
)

path = Path("tests/test_mpr042_market_truth.py")
text = path.read_text(encoding="utf-8")
marker = "\ndef test_duplicate_is_dropped_and_reordered_cursor_fails_closed() -> None:\n"
test = '''\n\ndef test_restart_requires_explicit_backfill_even_with_durable_cursors(\n    tmp_path: Path,\n) -> None:\n    store = DurableCursorStore(tmp_path / "cursors.json")\n    fanout = FanoutMatrix({"circular": ("jupiter", "okx")})\n    original = WatermarkedObservationBuffer(fanout=fanout, cursor_store=store)\n    original.ingest(_observation(source="jupiter"))\n    original.ingest(_observation(source="okx"))\n    original.mark_backfill_complete("jupiter")\n    original.mark_backfill_complete("okx")\n    assert original.publish("circular", minimum_observations=2).admissible\n\n    restarted = WatermarkedObservationBuffer(fanout=fanout, cursor_store=store)\n    blocked = restarted.publish("circular", minimum_observations=2)\n\n    assert blocked.completeness is CompletenessState.BLOCKED\n    assert "backfill_pending:jupiter" in blocked.degraded_reasons\n    assert "backfill_pending:okx" in blocked.degraded_reasons\n'''
if text.count(marker) != 1:
    raise SystemExit("test marker not found exactly once")
path.write_text(text.replace(marker, test + marker, 1), encoding="utf-8")
