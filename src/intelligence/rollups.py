"""Availability-time rollups with full cursor/hash coverage proofs."""

from collections import defaultdict
from .common import digest, seal, verify_seal


def _build(rows: list[dict], width_ms: int) -> dict:
    if len({r["event_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate rollup event")
    groups = defaultdict(list)
    for row in rows:
        if type(row.get("available_at_ms")) is not int or row["available_at_ms"] < 0:
            raise ValueError("availability time required")
        groups[
            (
                row["source_id"],
                row["cursor_partition"],
                row["available_at_ms"] // width_ms,
            )
        ].append(row)
    buckets = []
    for (source, partition, bucket), events in sorted(groups.items()):
        refs = [
            {
                k: r[k]
                for k in (
                    "event_id",
                    "payload_sha256",
                    "cursor_offset",
                    "reconnect_epoch",
                    "gap_before",
                    "available_at_ms",
                )
            }
            for r in sorted(events, key=lambda r: r["event_id"])
        ]
        buckets.append(
            {
                "source_id": source,
                "partition": partition,
                "start_ms": bucket * width_ms,
                "end_ms": (bucket + 1) * width_ms,
                "count": len(events),
                "unique_payloads": len({r["payload_sha256"] for r in events}),
                "gap_count": sum(r["gap_before"] for r in events),
                "source_refs": refs,
            }
        )
    return seal(
        {
            "schema": "studious.rollup.v2",
            "width_ms": width_ms,
            "input_sha256": digest(
                [
                    {k: v for k, v in r.items() if k != "payload"}
                    for r in sorted(rows, key=lambda r: r["event_id"])
                ]
            ),
            "buckets": buckets,
        }
    )


def build_1m_rollup(rows):
    return _build(rows, 60_000)


def build_5m_rollup(rows):
    return _build(rows, 300_000)


def build_1h_rollup(rows):
    return _build(rows, 3_600_000)


def verify_rollup_coverage(rollup: dict, rows: list[dict]) -> dict:
    verify_seal(rollup)
    expected = _build(rows, rollup["width_ms"])
    if expected != rollup:
        raise ValueError("rollup coverage mismatch")
    return {
        "covered_events": len(rows),
        "verified": True,
        "rollup_sha256": rollup["receipt_sha256"],
    }
