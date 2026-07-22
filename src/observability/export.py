from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
import hashlib
import os
from pathlib import Path
from typing import Any, Protocol
import uuid

from .archive import ArchiveCoordinator, ArchiveError, RemoteArchiveAck
from .archive_segments import (
    date_partition,
    fsync_dir,
    recover_orphan_segments,
    remove_stale_temp_files,
    secure_directory,
    write_immutable_segment,
)
from .archive_types import PR198_EXPORT_TOOL_VERSION
from .archive_verify import verify_archive
from .store import ObservabilityStore

EXPORT_TOOL_VERSION = "observability-export.v1"
PR132_EXPORT_TOOL_VERSION = "observability-export.v2"


class ArchiveUploader(Protocol):
    def upload(
        self,
        *,
        segment_path: Path,
        manifest: Mapping[str, object],
    ) -> RemoteArchiveAck: ...


def export_jsonl(
    store: ObservabilityStore,
    out_dir: str | Path,
    *,
    exporter_id: str | None = None,
    lease_seconds: float = 30.0,
    claim_limit: int = 10_000,
    archive_uploader: ArchiveUploader | None = None,
    require_remote_ack: bool = False,
) -> dict[str, object]:
    """Export pending envelopes as fenced immutable JSONL segments."""

    if require_remote_ack and archive_uploader is None:
        raise ArchiveError("ARCHIVE_REMOTE_UPLOADER_REQUIRED")
    out = Path(out_dir)
    secure_directory(out)
    coordinator = ArchiveCoordinator(store)
    coordinator.expire_claims()
    remove_stale_temp_files(coordinator, out)
    effective_id = exporter_id or f"exporter-{uuid.uuid4().hex}"
    recovered = recover_orphan_segments(
        coordinator,
        out,
        exporter_id=effective_id,
        lease_seconds=lease_seconds,
        remote_required=require_remote_ack,
    )
    _retry_remote_archives(coordinator, archive_uploader)

    claim = coordinator.claim_pending(
        exporter_id=effective_id,
        lease_seconds=lease_seconds,
        limit=claim_limit,
    )
    if claim is None:
        return _noop_result(store, out, coordinator, recovered)
    rows = coordinator.rows_for_claim(claim)
    if not rows:
        raise ArchiveError("ARCHIVE_CLAIM_WITHOUT_ROWS")

    partitions: dict[tuple[object, ...], list[Any]] = defaultdict(list)
    for row in rows:
        key = (
            date_partition(int(row["occurred_at_utc_ns"])),
            str(row["event_type"]),
            str(row["database_epoch"]),
            str(row["release_id"]),
            str(row["policy_bundle_hash"]),
            int(row["schema_version"]),
            str(row["redaction_version"]),
        )
        partitions[key].append(row)

    manifests: list[dict[str, object]] = []
    for partition_rows in partitions.values():
        ordered = sorted(
            partition_rows,
            key=lambda row: (
                int(row["occurred_at_utc_ns"]),
                str(row["event_id"]),
                int(row["outbox_id"]),
            ),
        )
        manifest = write_immutable_segment(
            out,
            claim=claim,
            rows=ordered,
            remote_required=require_remote_ack,
        )
        coordinator.commit_segment(claim=claim, manifest=manifest, rows=ordered)
        manifests.append(manifest)
        _upload_manifest(coordinator, archive_uploader, manifest)

    legacy = _write_legacy_compat_jsonl(store, out)
    result = _legacy_result(legacy, event_count=len(rows))
    result.update(
        {
            "manifest_count": len(manifests),
            "manifests": manifests,
            "recovered_manifest_count": len(recovered),
            "recovered_manifests": recovered,
            "legacy_path": legacy["path"],
            "legacy_authoritative": False,
            "pr132_export_tool_version": PR132_EXPORT_TOOL_VERSION,
            "pr198_export_tool_version": PR198_EXPORT_TOOL_VERSION,
            "remote_ack_required": require_remote_ack,
            "remote_ack_pending": len(coordinator.manifests_needing_remote_ack()),
        }
    )
    return result


def _retry_remote_archives(
    coordinator: ArchiveCoordinator,
    uploader: ArchiveUploader | None,
) -> None:
    if uploader is None:
        return
    for manifest in coordinator.manifests_needing_remote_ack():
        _upload_manifest(coordinator, uploader, manifest)


def _upload_manifest(
    coordinator: ArchiveCoordinator,
    uploader: ArchiveUploader | None,
    manifest: Mapping[str, object],
) -> None:
    if uploader is None:
        return
    segment_id = str(manifest["segment_id"])
    path_value = manifest.get("path") or manifest.get("partition_path")
    if not path_value:
        raise ArchiveError("ARCHIVE_SEGMENT_PATH_MISSING")
    try:
        ack = uploader.upload(
            segment_path=Path(str(path_value)),
            manifest=manifest,
        )
        coordinator.record_remote_ack(segment_id=segment_id, ack=ack)
    except Exception as exc:
        coordinator.record_remote_failure(
            segment_id=segment_id,
            reason=type(exc).__name__,
        )
        if bool(manifest.get("remote_required", False)):
            raise ArchiveError("ARCHIVE_REMOTE_ACK_FAILED") from exc


def _noop_result(
    store: ObservabilityStore,
    out: Path,
    coordinator: ArchiveCoordinator,
    recovered: list[dict[str, object]],
) -> dict[str, object]:
    rows = _legacy_event_rows(store)
    common = {
        "event_count": 0,
        "manifest_count": 0,
        "manifests": [],
        "recovered_manifest_count": len(recovered),
        "recovered_manifests": recovered,
        "remote_ack_pending": len(coordinator.manifests_needing_remote_ack()),
        "legacy_authoritative": False,
        "pr198_export_tool_version": PR198_EXPORT_TOOL_VERSION,
    }
    if not rows:
        return common
    legacy = _write_legacy_compat_jsonl(store, out, legacy_rows=rows)
    result = _legacy_result(legacy, event_count=0)
    result.update(common)
    result.update(
        {
            "legacy_path": legacy["path"],
            "pr132_export_tool_version": PR132_EXPORT_TOOL_VERSION,
        }
    )
    return result


def _legacy_result(
    legacy: Mapping[str, object],
    *,
    event_count: int,
) -> dict[str, object]:
    return {
        "manifest_id": legacy["manifest_id"],
        "checksum": legacy["checksum"],
        "event_count": event_count,
        "path": legacy["path"],
        "export_tool_version": EXPORT_TOOL_VERSION,
        "authoritative": False,
    }


def _legacy_event_rows(store: ObservabilityStore) -> list[Any]:
    return list(
        store.db.execute(
            "SELECT * FROM event_log ORDER BY occurred_at_utc_ns, event_id"
        )
    )


def _write_legacy_compat_jsonl(
    store: ObservabilityStore,
    out: Path,
    *,
    legacy_rows: list[Any] | None = None,
) -> dict[str, object]:
    rows = legacy_rows if legacy_rows is not None else _legacy_event_rows(store)
    event_type = str(rows[0]["event_type"])
    part = out / "date_utc=1970-01-01" / f"event_type={event_type}"
    secure_directory(part)
    tmp = part / f"events.jsonl.{uuid.uuid4().hex}.tmp"
    final = part / "events.jsonl"
    with open(tmp, "w", encoding="utf-8") as handle:
        os.chmod(tmp, 0o600)
        for row in rows:
            handle.write(str(row["payload_json"]) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    data = tmp.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    os.replace(tmp, final)
    fsync_dir(part)
    return {
        "manifest_id": hashlib.sha256((str(final) + checksum).encode()).hexdigest(),
        "checksum": checksum,
        "event_count": len(rows),
        "first_event_id": rows[0]["event_id"],
        "last_event_id": rows[-1]["event_id"],
        "path": str(final),
        "date_utc": "1970-01-01",
        "event_type": event_type,
        "authoritative": False,
        "artifact_role": "legacy_compatibility_only",
    }


__all__ = [
    "ArchiveUploader",
    "EXPORT_TOOL_VERSION",
    "PR132_EXPORT_TOOL_VERSION",
    "PR198_EXPORT_TOOL_VERSION",
    "export_jsonl",
    "verify_archive",
]
