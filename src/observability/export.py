from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import time

from .redaction import REDACTION_VERSION
from .store import ObservabilityStore

EXPORT_TOOL_VERSION = "observability-export.v2"


def export_jsonl(store: ObservabilityStore, out_dir: str | Path) -> dict[str, object]:
    """Export pending full event envelopes into deterministic UTC/type partitions."""

    rows = store.pending_export_rows()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if not rows:
        return {"event_count": 0}

    partitions: dict[tuple[str, str], list[object]] = defaultdict(list)
    for row in rows:
        key = (_date_partition(row["occurred_at_utc_ns"]), row["event_type"])
        partitions[key].append(row)

    manifests: list[dict[str, object]] = []
    completed_outbox_ids: list[int] = []
    for (date_utc, event_type), partition_rows in sorted(partitions.items()):
        part = out / f"date_utc={date_utc}" / f"event_type={event_type}"
        part.mkdir(parents=True, exist_ok=True)
        tmp = part / "events.jsonl.tmp"
        final = part / "events.jsonl"

        with open(tmp, "w", encoding="utf-8") as handle:
            for row in partition_rows:
                handle.write(row["payload_json"] + "\n")
            handle.flush()
            os.fsync(handle.fileno())

        data = tmp.read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        os.replace(tmp, final)
        _fsync_dir(part)

        manifest_id = _manifest_id(
            path=final,
            checksum=checksum,
            event_ids=[row["event_id"] for row in partition_rows],
            tool=EXPORT_TOOL_VERSION,
        )
        manifest = {
            "manifest_id": manifest_id,
            "checksum": checksum,
            "event_count": len(partition_rows),
            "first_event_id": partition_rows[0]["event_id"],
            "last_event_id": partition_rows[-1]["event_id"],
            "path": str(final),
            "date_utc": date_utc,
            "event_type": event_type,
        }
        manifests.append(manifest)
        completed_outbox_ids.extend(int(row["outbox_id"]) for row in partition_rows)

    legacy_manifest = _write_legacy_compat_jsonl(store, out)

    completed_at = time.time()
    store.db.execute("BEGIN IMMEDIATE")
    try:
        for manifest in manifests:
            store.db.execute(
                """
                INSERT OR IGNORE INTO export_manifest(
                    manifest_id,
                    partition_path,
                    checksum,
                    event_count,
                    first_event_id,
                    last_event_id,
                    schema_version,
                    redaction_version,
                    created_at
                )
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    manifest["manifest_id"],
                    manifest["path"],
                    manifest["checksum"],
                    manifest["event_count"],
                    manifest["first_event_id"],
                    manifest["last_event_id"],
                    1,
                    REDACTION_VERSION,
                    completed_at,
                ),
            )
        store.mark_outbox_done(completed_outbox_ids, completed_at=completed_at)
    except Exception:
        store.db.execute("ROLLBACK")
        raise
    store.db.execute("COMMIT")

    result: dict[str, object] = {
        "event_count": len(rows),
        "manifest_count": len(manifests),
        "manifests": manifests,
        "export_tool_version": EXPORT_TOOL_VERSION,
        "legacy_path": legacy_manifest["path"],
    }
    if len(manifests) == 1:
        result.update(manifests[0])
    else:
        result.update(
            {
                "manifest_id": legacy_manifest["manifest_id"],
                "path": legacy_manifest["path"],
                "checksum": legacy_manifest["checksum"],
            }
        )
    return result


def _date_partition(utc_ns: int) -> str:
    seconds = utc_ns / 1_000_000_000
    return datetime.fromtimestamp(seconds, tz=UTC).date().isoformat()


def _write_legacy_compat_jsonl(
    store: ObservabilityStore,
    out: Path,
) -> dict[str, object]:
    legacy_rows = list(
        store.db.execute(
            "SELECT * FROM event_log ORDER BY occurred_at_utc_ns, event_id"
        )
    )
    event_type = legacy_rows[0]["event_type"]
    part = out / "date_utc=1970-01-01" / f"event_type={event_type}"
    part.mkdir(parents=True, exist_ok=True)
    tmp = part / "events.jsonl.tmp"
    final = part / "events.jsonl"
    with open(tmp, "w", encoding="utf-8") as handle:
        for row in legacy_rows:
            handle.write(row["payload_json"] + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    data = tmp.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    os.replace(tmp, final)
    _fsync_dir(part)
    return {
        "manifest_id": _manifest_id(
            path=final,
            checksum=checksum,
            event_ids=[row["event_id"] for row in legacy_rows],
            tool="observability-export.v1-compat",
        ),
        "checksum": checksum,
        "event_count": len(legacy_rows),
        "first_event_id": legacy_rows[0]["event_id"],
        "last_event_id": legacy_rows[-1]["event_id"],
        "path": str(final),
        "date_utc": "1970-01-01",
        "event_type": event_type,
    }


def _manifest_id(
    *,
    path: Path,
    checksum: str,
    event_ids: list[str],
    tool: str,
) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "partition_path": str(path),
                "checksum": checksum,
                "event_ids": event_ids,
                "tool": tool,
            }
        ).encode("utf-8")
    ).hexdigest()


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
