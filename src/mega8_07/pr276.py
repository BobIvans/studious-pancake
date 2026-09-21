"""PR-276 / STREAM-02: event-time joins and revisioned state."""
from __future__ import annotations

from typing import Mapping, Sequence

from .core import Mega807Error, require_nonnegative, stable_hash


EventRow = tuple[int, int, str, Mapping[str, int | str]]


def join_event_time_streams(
    left: Sequence[EventRow],
    right: Sequence[EventRow],
    *,
    max_event_gap: int,
) -> tuple[tuple[EventRow, EventRow], ...]:
    require_nonnegative(max_event_gap, "max_event_gap")
    joined: list[tuple[EventRow, EventRow]] = []
    for lrow in left:
        if lrow[1] < lrow[0]:
            raise Mega807Error("IMPOSSIBLE_AVAILABILITY_ORDER")
        for rrow in right:
            if rrow[1] < rrow[0]:
                raise Mega807Error("IMPOSSIBLE_AVAILABILITY_ORDER")
            if abs(lrow[0] - rrow[0]) <= max_event_gap:
                joined.append((lrow, rrow))
    return tuple(sorted(joined, key=lambda pair: (pair[0][0], pair[1][0])))


def manage_watermark_lateness(
    rows: Sequence[EventRow], *, watermark: int, max_lateness: int
) -> tuple[EventRow, ...]:
    require_nonnegative(watermark, "watermark")
    require_nonnegative(max_lateness, "max_lateness")
    floor = max(0, watermark - max_lateness)
    return tuple(row for row in rows if row[0] >= floor)


def materialize_stream_state(
    rows: Sequence[EventRow], *, revision: str
) -> dict[str, object]:
    payload = [
        {
            "event_time": row[0],
            "available_at": row[1],
            "source": row[2],
            "payload": dict(sorted(row[3].items())),
        }
        for row in rows
    ]
    return {
        "revision": revision,
        "rows": tuple(payload),
        "sha256": stable_hash("mega8-07-stream-state", payload),
    }


def replay_stream_join(
    first: Sequence[tuple[EventRow, EventRow]],
    second: Sequence[tuple[EventRow, EventRow]],
) -> str:
    if tuple(first) != tuple(second):
        raise Mega807Error("STREAM_REPLAY_MISMATCH")
    return stable_hash("mega8-07-stream-replay", list(first))
