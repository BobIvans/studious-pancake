"""Verified exact AGG-02 projection, never a competing market store."""

from dataclasses import asdict
from pathlib import Path
from src.agg02.storage import (
    AnalyticalDatasetPublisher,
    DatasetManifest,
    DatasetReplayReader,
    DurableRawJournal,
)
from .common import digest, save_json, seal, verify_seal


def publish_partition(journal: DurableRawJournal, destination: str | Path) -> dict:
    rows = journal.retention_rows()
    manifest = AnalyticalDatasetPublisher().publish(
        dataset_id=digest([r["event_id"] for r in rows]),
        schema_version="studious.raw-archive.v2",
        rows=rows,
        destination=destination,
        compression="zstd",
    )
    proof = verify_partition(manifest, rows=rows)
    receipt = build_compaction_manifest(manifest, proof)
    save_json(Path(destination).with_suffix(".manifest.json"), receipt)
    return receipt


def verify_partition(manifest: DatasetManifest, *, rows=None) -> dict:
    replay = DatasetReplayReader.read(
        manifest, expected_schema_version="studious.raw-archive.v2"
    )
    if len({r["event_id"] for r in replay}) != len(replay):
        raise ValueError("duplicate replay event")
    import hashlib

    for row in replay:
        if hashlib.sha256(bytes(row["payload"])).hexdigest() != row["payload_sha256"]:
            raise ValueError("raw replay payload checksum mismatch")
    if rows is not None and tuple(dict(r) for r in rows) != replay:
        raise ValueError("compaction exact roundtrip failed")
    return {
        "verified": True,
        "event_ids": [r["event_id"] for r in replay],
        "row_count": len(replay),
        "replay_contract": "EXACT_BYTES_AND_ENVELOPE",
    }


def build_compaction_manifest(manifest: DatasetManifest, proof: dict) -> dict:
    return seal(
        {
            "schema": "studious.compaction.v2",
            "dataset": asdict(manifest),
            "proof": proof,
            "physical_prune_default": "DRY_RUN",
        }
    )


def compact_unreferenced_raw(
    journal: DurableRawJournal, destination: str | Path
) -> dict:
    # Publication preserves all events including pins; pruning is a separate gated step.
    return publish_partition(journal, destination)
