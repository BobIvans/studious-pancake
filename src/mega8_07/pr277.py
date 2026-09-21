"""PR-277 / ARCHIVE-02: immutable cold-archive manifests and restore drills."""
from __future__ import annotations

from typing import Mapping, Sequence

from .core import Mega807Error, require_nonnegative, require_sha256, stable_hash


def archive_cold_partition(
    *, partition_id: str, object_hashes: Sequence[str], storage_cost_units: int,
    max_cost_units: int,
) -> dict[str, object]:
    cost = require_nonnegative(storage_cost_units, "storage_cost_units")
    limit = require_nonnegative(max_cost_units, "max_cost_units")
    if cost > limit:
        raise Mega807Error("ARCHIVE_COST_BUDGET_EXCEEDED")
    hashes = tuple(sorted(require_sha256(value, "object_hash") for value in object_hashes))
    manifest = {
        "partition_id": partition_id,
        "object_hashes": hashes,
        "storage_cost_units": cost,
    }
    return {**manifest, "manifest_sha256": stable_hash("mega8-07-archive", manifest)}


def verify_archive_manifest(
    manifest: Mapping[str, object], objects: Mapping[str, bytes]
) -> bool:
    expected = tuple(manifest.get("object_hashes", ()))
    if set(expected) != set(objects):
        raise Mega807Error("ARCHIVE_OBJECT_SET_MISMATCH")
    for digest, payload in objects.items():
        actual = stable_hash("mega8-07-archive-object", payload.hex())
        if actual != digest:
            raise Mega807Error("ARCHIVE_OBJECT_HASH_MISMATCH")
    return True


def restore_archived_dataset(
    manifest: Mapping[str, object], objects: Mapping[str, bytes]
) -> tuple[bytes, ...]:
    verify_archive_manifest(manifest, objects)
    return tuple(objects[digest] for digest in manifest["object_hashes"])


def test_archive_disaster_recovery(
    manifest: Mapping[str, object],
    primary: Mapping[str, bytes],
    restored: Mapping[str, bytes],
) -> str:
    verify_archive_manifest(manifest, primary)
    verify_archive_manifest(manifest, restored)
    if dict(primary) != dict(restored):
        raise Mega807Error("ARCHIVE_RESTORE_MISMATCH")
    return stable_hash("mega8-07-archive-dr", manifest)
