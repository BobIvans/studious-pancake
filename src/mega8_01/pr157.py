"""PR-157 / NF-377..380: reproducible dataset migrations and backfills."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .common import artifact, fail_closed, canonical_hash, require_sha256, require_text, sorted_unique


def plan_schema_migration(
    dataset_id: str,
    from_revision: str,
    to_revision: str,
    ordered_steps: Sequence[str],
):
    did = require_text(dataset_id, "dataset_id")
    old = require_text(from_revision, "from_revision")
    new = require_text(to_revision, "to_revision")
    steps = tuple(require_text(step, "migration_step") for step in ordered_steps)
    if old == new and steps:
        return fail_closed(
            child="PR-157",
            nf="NF-377",
            action="plan_schema_migration",
            subject_id=did,
            reason="INCONSISTENT_STATE",
            payload={"from_revision": old, "to_revision": new, "steps": steps},
        )
    return artifact(
        child="PR-157",
        nf="NF-377",
        action="plan_schema_migration",
        subject_id=did,
        payload={"from_revision": old, "to_revision": new, "steps": steps},
    )


def execute_idempotent_backfill(
    dataset_id: str,
    source_partition_sha256: str,
    target_revision: str,
    transform_identity: str,
):
    did = require_text(dataset_id, "dataset_id")
    source_hash = require_sha256(source_partition_sha256, "source_partition_sha256")
    revision = require_text(target_revision, "target_revision")
    transform = require_text(transform_identity, "transform_identity")
    receipt = canonical_hash(
        {
            "dataset_id": did,
            "source_partition_sha256": source_hash,
            "target_revision": revision,
            "transform_identity": transform,
        }
    )
    return artifact(
        child="PR-157",
        nf="NF-378",
        action="execute_idempotent_backfill",
        subject_id=did,
        payload={"backfill_receipt_sha256": receipt, "target_revision": revision},
    )


def record_dataset_revision(
    dataset_id: str,
    revision: str,
    partition_hashes: Sequence[str],
    metadata: Mapping[str, object],
):
    did = require_text(dataset_id, "dataset_id")
    rev = require_text(revision, "revision")
    partitions = tuple(
        sorted(require_sha256(value, "partition_hash") for value in partition_hashes)
    )
    if not partitions:
        return fail_closed(
            child="PR-157",
            nf="NF-379",
            action="record_dataset_revision",
            subject_id=did,
            reason="INSUFFICIENT_EVIDENCE",
        )
    return artifact(
        child="PR-157",
        nf="NF-379",
        action="record_dataset_revision",
        subject_id=did,
        payload={
            "revision": rev,
            "partition_hashes": partitions,
            "metadata_sha256": canonical_hash(dict(metadata)),
        },
    )


def validate_cross_revision_replay(
    dataset_id: str,
    source_result_sha256: str,
    migrated_result_sha256: str,
    allowed_differences: Sequence[str] = (),
):
    did = require_text(dataset_id, "dataset_id")
    source = require_sha256(source_result_sha256, "source_result_sha256")
    migrated = require_sha256(migrated_result_sha256, "migrated_result_sha256")
    allowed = sorted_unique(allowed_differences)
    if source != migrated and not allowed:
        return fail_closed(
            child="PR-157",
            nf="NF-380",
            action="validate_cross_revision_replay",
            subject_id=did,
            reason="INCONSISTENT_STATE",
            payload={"source": source, "migrated": migrated},
        )
    return artifact(
        child="PR-157",
        nf="NF-380",
        action="validate_cross_revision_replay",
        subject_id=did,
        payload={"source": source, "migrated": migrated, "allowed_differences": allowed},
    )
