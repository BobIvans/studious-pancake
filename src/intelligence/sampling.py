"""Deterministic bounded baseline/negative sampling; pins take precedence."""

from collections import defaultdict
from .common import digest


def select_periodic_baseline(
    rows: list[dict], *, interval_ms: int = 300_000
) -> list[str]:
    if interval_ms < 1:
        raise ValueError("positive sample period required")
    selected: dict[tuple, str] = {}
    for row in sorted(rows, key=lambda r: (r["available_at_ms"], r["event_id"])):
        key = (
            row["source_id"],
            row.get("instrument_id", row.get("cursor_partition")),
            row["available_at_ms"] // interval_ms,
        )
        selected.setdefault(key, row["event_id"])
    return sorted(selected.values())


def reservoir_sample_failures(
    rows: list[dict], *, per_class: int = 8, seed: str = "v2"
) -> list[str]:
    if per_class < 2:
        raise ValueError("first/last require at least two samples")
    classes = defaultdict(list)
    for row in rows:
        if row.get("reason_code"):
            classes[row["reason_code"]].append(row)
    selected: set[str] = set()
    for items in classes.values():
        items.sort(key=lambda r: (r["available_at_ms"], r["event_id"]))
        selected.update((items[0]["event_id"], items[-1]["event_id"]))
        interior = sorted(items[1:-1], key=lambda r: digest([seed, r["event_id"]]))
        selected.update(r["event_id"] for r in interior[: per_class - 2])
    return sorted(selected)


def pin_significant_delta(rows: list[dict], *, threshold_atoms: int) -> list[str]:
    if threshold_atoms < 0:
        raise ValueError("negative delta threshold")
    previous: dict[tuple, int] = {}
    pinned: list[str] = []
    for row in sorted(rows, key=lambda r: (r["available_at_ms"], r["event_id"])):
        key = (row["source_id"], row["instrument_id"])
        value = row.get("value_atoms")
        if type(value) is not int:
            continue
        if key not in previous or abs(value - previous[key]) >= threshold_atoms:
            pinned.append(row["event_id"])
        previous[key] = value
    return sorted(pinned)


def pin_candidate_window(
    rows: list[dict], *, start_ms: int, end_ms: int, source_ids: list[str] | None = None
) -> list[str]:
    if not 0 <= start_ms <= end_ms:
        raise ValueError("invalid candidate window")
    return sorted(
        r["event_id"]
        for r in rows
        if start_ms <= r["available_at_ms"] <= end_ms
        and (source_ids is None or r["source_id"] in source_ids)
    )
