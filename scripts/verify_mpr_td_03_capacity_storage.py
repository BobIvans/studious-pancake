#!/usr/bin/env python3
"""Run a real offline SQLite capacity and recovery smoke qualification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.persistence import connect_operational  # noqa: E402


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def build_evidence() -> dict[str, object]:
    errors: list[str] = []
    profiles = json.loads(
        (ROOT / "config/capacity_profiles.json").read_text(encoding="utf-8")
    )
    profile = profiles["profiles"]["ci_smoke"]
    rows = int(profile["rows"])
    payload = "x" * int(profile["payload_bytes"])
    with tempfile.TemporaryDirectory(prefix="mpr-td-03-") as directory:
        base = Path(directory)
        db_path = base / "runtime.sqlite3"
        backup_path = base / "backup.sqlite3"
        connection = connect_operational(db_path)
        connection.execute(
            "CREATE TABLE events("
            "event_id TEXT PRIMARY KEY, "
            "created_ns INTEGER NOT NULL, "
            "payload TEXT NOT NULL)"
        )
        connection.execute("CREATE INDEX idx_events_created_ns ON events(created_ns)")
        started = time.perf_counter()
        with connection:
            connection.executemany(
                "INSERT INTO events(event_id, created_ns, payload) VALUES(?, ?, ?)",
                ((f"event-{index}", index, payload) for index in range(rows)),
            )
        insert_seconds = max(time.perf_counter() - started, 1e-9)
        throughput = rows / insert_seconds
        query_ms: list[float] = []
        for index in range(min(rows, 200)):
            qstart = time.perf_counter()
            result = connection.execute(
                "SELECT payload FROM events WHERE event_id = ?", (f"event-{index}",)
            ).fetchone()
            query_ms.append((time.perf_counter() - qstart) * 1_000)
            if result != (payload,):
                errors.append("indexed lookup returned incorrect payload")
                break
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT payload FROM events WHERE event_id = ?",
            ("event-1",),
        ).fetchall()
        plan_text = " ".join(str(row) for row in plan).upper()
        indexed_plan = "SEARCH" in plan_text and "SCAN EVENTS" not in plan_text
        if not indexed_plan:
            errors.append(f"indexed query plan regressed: {plan!r}")
        backup_started = time.perf_counter()
        backup = connect_operational(backup_path)
        connection.backup(backup)
        backup.commit()
        backup_seconds = time.perf_counter() - backup_started
        integrity = backup.execute("PRAGMA integrity_check").fetchone()[0]
        restored_count = backup.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        backup.close()
        connection.close()
        if integrity != "ok":
            errors.append(f"backup integrity failed: {integrity}")
        if restored_count != rows:
            errors.append("backup row count mismatch")
        db_bytes = db_path.stat().st_size
        wal_path = Path(f"{db_path}-wal")
        wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0
        p95 = _percentile(query_ms, 0.95)
        if throughput < float(profile["minimum_insert_rows_per_second"]):
            errors.append(f"insert throughput below CI floor: {throughput:.2f}")
        if p95 > float(profile["maximum_indexed_query_p95_ms"]):
            errors.append(f"indexed query p95 exceeded CI ceiling: {p95:.3f}ms")
        if backup_seconds > float(profile["maximum_backup_seconds"]):
            errors.append(f"backup exceeded CI ceiling: {backup_seconds:.3f}s")
        if db_bytes > int(profile["maximum_database_bytes"]):
            errors.append(f"qualification database exceeded budget: {db_bytes}")
    return {
        "schema_version": "mpr-td-03.capacity-storage-evidence.v1",
        "accepted": not errors,
        "qualification_scope": profile["qualification_scope"],
        "rows": rows,
        "insert_rows_per_second": round(throughput, 3),
        "indexed_query_p50_ms": round(statistics.median(query_ms), 6),
        "indexed_query_p95_ms": round(p95, 6),
        "indexed_plan": indexed_plan,
        "database_bytes": db_bytes,
        "wal_bytes": wal_bytes,
        "backup_seconds": round(backup_seconds, 6),
        "backup_integrity": integrity,
        "restored_rows": restored_count,
        "production_capacity_qualified": False,
        "sender_free": True,
        "production_ready": False,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    evidence = build_evidence()
    print(
        json.dumps(evidence, indent=2, sort_keys=True)
        if args.as_json
        else ("PASS" if evidence["accepted"] else "FAIL")
    )
    return 0 if evidence["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
