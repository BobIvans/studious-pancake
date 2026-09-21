"""PR-158 / NF-381..384: content-addressed evidence storage and compaction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .common import artifact, fail_closed, canonical_hash, require_non_negative_int, require_sha256, require_text


def content_address_partition(
    dataset_id: str,
    rows: Sequence[Mapping[str, object]],
):
    did = require_text(dataset_id, "dataset_id")
    normalized = tuple(dict(row) for row in rows)
    content_hash = canonical_hash(normalized)
    return artifact(
        child="PR-158",
        nf="NF-381",
        action="content_address_partition",
        subject_id=did,
        payload={"row_count": len(normalized), "partition_sha256": content_hash},
    )


def deduplicate_raw_events(
    dataset_id: str,
    events: Sequence[Mapping[str, object]],
):
    did = require_text(dataset_id, "dataset_id")
    unique: dict[str, Mapping[str, object]] = {}
    for event in events:
        event_id = require_text(event.get("event_id"), "event_id")
        previous = unique.get(event_id)
        if previous is not None and canonical_hash(dict(previous)) != canonical_hash(dict(event)):
            return fail_closed(
                child="PR-158",
                nf="NF-382",
                action="deduplicate_raw_events",
                subject_id=did,
                reason="IDENTITY_MISMATCH",
                payload={"conflicting_event_id": event_id},
            )
        unique[event_id] = dict(event)
    return artifact(
        child="PR-158",
        nf="NF-382",
        action="deduplicate_raw_events",
        subject_id=did,
        payload={
            "input_count": len(events),
            "unique_count": len(unique),
            "event_ids": tuple(sorted(unique)),
        },
    )


def compact_evidence_segments(
    dataset_id: str,
    segment_hashes: Sequence[str],
):
    did = require_text(dataset_id, "dataset_id")
    segments = tuple(
        sorted(require_sha256(value, "segment_hash") for value in segment_hashes)
    )
    if not segments:
        return fail_closed(
            child="PR-158",
            nf="NF-383",
            action="compact_evidence_segments",
            subject_id=did,
            reason="INSUFFICIENT_EVIDENCE",
        )
    compacted = canonical_hash({"segments": segments})
    return artifact(
        child="PR-158",
        nf="NF-383",
        action="compact_evidence_segments",
        subject_id=did,
        payload={"segments": segments, "compacted_sha256": compacted},
    )


def verify_compaction_equivalence(
    dataset_id: str,
    source_row_count: int,
    compacted_row_count: int,
    source_logical_sha256: str,
    compacted_logical_sha256: str,
):
    did = require_text(dataset_id, "dataset_id")
    source_count = require_non_negative_int(source_row_count, "source_row_count")
    compact_count = require_non_negative_int(compacted_row_count, "compacted_row_count")
    source_hash = require_sha256(source_logical_sha256, "source_logical_sha256")
    compact_hash = require_sha256(compacted_logical_sha256, "compacted_logical_sha256")
    equivalent = source_count == compact_count and source_hash == compact_hash
    payload = {
        "source_row_count": source_count,
        "compacted_row_count": compact_count,
        "source_logical_sha256": source_hash,
        "compacted_logical_sha256": compact_hash,
    }
    if not equivalent:
        return fail_closed(
            child="PR-158",
            nf="NF-384",
            action="verify_compaction_equivalence",
            subject_id=did,
            reason="INCONSISTENT_STATE",
            payload=payload,
        )
    return artifact(
        child="PR-158",
        nf="NF-384",
        action="verify_compaction_equivalence",
        subject_id=did,
        payload=payload,
    )
