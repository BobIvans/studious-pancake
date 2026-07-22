from __future__ import annotations

import hashlib
from pathlib import Path

from .archive import ArchiveCoordinator, ArchiveError
from .archive_segments import canonical_json, event_ids_from_jsonl, segment_identity
from .archive_types import PR198_EXPORT_TOOL_VERSION
from .store import ObservabilityStore


def verify_archive(
    store: ObservabilityStore,
    out_dir: str | Path,
    *,
    require_remote_ack: bool = False,
) -> dict[str, object]:
    out = Path(out_dir).resolve()
    coordinator = ArchiveCoordinator(store)
    divergences: list[dict[str, object]] = []
    total_events = 0
    manifests = coordinator.authoritative_manifests()

    for manifest in manifests:
        segment_id = str(manifest["segment_id"])
        path = Path(str(manifest["partition_path"]))
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError:
            divergences.append(
                {"code": "ARCHIVE_SEGMENT_MISSING", "segment_id": segment_id}
            )
            continue
        if not resolved.is_relative_to(out):
            divergences.append(
                {"code": "ARCHIVE_PATH_ESCAPE", "segment_id": segment_id}
            )
            continue
        data = resolved.read_bytes()
        if hashlib.sha256(data).hexdigest() != str(manifest["checksum"]):
            divergences.append(
                {"code": "ARCHIVE_CHECKSUM_MISMATCH", "segment_id": segment_id}
            )
            continue
        try:
            event_ids = event_ids_from_jsonl(data)
        except ArchiveError as exc:
            divergences.append(
                {
                    "code": "ARCHIVE_JSONL_INVALID",
                    "segment_id": segment_id,
                    "detail": str(exc),
                }
            )
            continue
        linked_ids = coordinator.linked_event_ids(segment_id)
        if event_ids != linked_ids:
            divergences.append(
                {"code": "ARCHIVE_EVENT_LINK_MISMATCH", "segment_id": segment_id}
            )
        expected_id = hashlib.sha256(
            canonical_json(segment_identity(manifest, linked_ids)).encode("utf-8")
        ).hexdigest()
        if expected_id != segment_id:
            divergences.append(
                {"code": "ARCHIVE_MANIFEST_IDENTITY_MISMATCH", "segment_id": segment_id}
            )
        if len(event_ids) != int(manifest["event_count"]):
            divergences.append(
                {"code": "ARCHIVE_EVENT_COUNT_MISMATCH", "segment_id": segment_id}
            )
        if require_remote_ack and str(manifest["remote_status"]) != "acked":
            divergences.append(
                {"code": "ARCHIVE_REMOTE_ACK_MISSING", "segment_id": segment_id}
            )
        total_events += len(event_ids)

    activated_at = float(
        store.db.execute(
            "SELECT value FROM archive_meta WHERE key='activated_at'"
        ).fetchone()["value"]
    )
    uncovered = store.db.execute(
        """
        SELECT COUNT(*) AS count FROM outbox
        WHERE work_type='export' AND status='done' AND completed_at>=?
          AND NOT EXISTS(
              SELECT 1 FROM archive_segment_event AS link
              WHERE link.outbox_id=outbox.id
          )
        """,
        (activated_at,),
    ).fetchone()
    if int(uncovered["count"]):
        divergences.append(
            {
                "code": "ARCHIVE_OUTBOX_COVERAGE_GAP",
                "count": int(uncovered["count"]),
            }
        )
    legacy_unlinked = store.db.execute(
        """
        SELECT COUNT(*) AS count FROM outbox
        WHERE work_type='export' AND status='done'
          AND (completed_at<? OR completed_at IS NULL)
          AND NOT EXISTS(
              SELECT 1 FROM archive_segment_event AS link
              WHERE link.outbox_id=outbox.id
          )
        """,
        (activated_at,),
    ).fetchone()
    return {
        "ok": not divergences,
        "manifest_count": len(manifests),
        "event_count": total_events,
        "divergences": divergences,
        "remote_ack_pending": len(coordinator.manifests_needing_remote_ack()),
        "legacy_unlinked_outbox_count": int(legacy_unlinked["count"]),
        "legacy_compatibility_artifact_authoritative": False,
        "tool_version": PR198_EXPORT_TOOL_VERSION,
    }
