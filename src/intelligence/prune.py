"""Conservative reversible payload offload with durable pre-mutation receipts."""

from pathlib import Path
from src.agg02.storage import DatasetManifest, DurableRawJournal
from .common import digest, save_json, seal, verify_seal
from .evidence_refs import deletion_impact
from .parquet_compaction import verify_partition
from .retention_policy import retention_dry_run


def prune_dry_run(
    records: list[dict], *, now_ms: int, minimum_age_ms=86_400_000
) -> dict:
    return retention_dry_run(records, now_ms=now_ms, minimum_age_ms=minimum_age_ms)


def write_tombstone_receipt(path: str | Path, receipt: dict) -> None:
    verify_seal(receipt)
    target = Path(path)
    if target.exists():
        raise ValueError("tombstone receipt already exists")
    save_json(target, receipt)


def prune_verified_payloads(
    journal: DurableRawJournal,
    *,
    compaction: dict,
    retention: dict,
    references: list[dict],
    records: list[dict],
    receipt_path: str | Path,
    inventory_complete: bool = False,
) -> dict:
    verify_seal(compaction)
    verify_seal(retention)
    rebuilt = retention_dry_run(
        records, now_ms=retention["now_ms"], minimum_age_ms=retention["minimum_age_ms"]
    )
    if rebuilt != retention:
        raise ValueError("retention record/receipt mismatch")
    event_ids = tuple(d["event_id"] for d in retention["decisions"] if d["eligible"])
    impact = deletion_impact(
        list(event_ids), references, inventory_complete=inventory_complete
    )
    if not impact["eligible"]:
        raise ValueError("references/pins unknown or present")
    manifest = DatasetManifest(**compaction["dataset"])
    proof = verify_partition(manifest)
    if proof != compaction["proof"] or not set(event_ids) <= set(proof["event_ids"]):
        raise ValueError("compaction proof mismatch")
    if set(event_ids) & journal.retention_pins().keys():
        raise ValueError("journal evidence pin blocks pruning")
    tombstone = seal(
        {
            "schema": "studious.tombstone.v2",
            "event_ids": list(event_ids),
            "compaction": compaction,
            "retention_sha256": retention["receipt_sha256"],
            "impact": impact,
            "rollback": "AGG02_EXACT_PARQUET_REPLAY",
            "status": "PREPARED",
            "model_authority": False,
        }
    )
    write_tombstone_receipt(receipt_path, tombstone)
    archived = journal.archive_verified_payloads(
        manifest,
        event_ids=event_ids,
        now_ms=retention["now_ms"],
        minimum_age_ms=retention["minimum_age_ms"],
        receipt_hash=tombstone["receipt_sha256"],
    )
    result = seal(
        {
            **{k: v for k, v in tombstone.items() if k != "receipt_sha256"},
            "status": "COMMITTED",
            "archived_events": archived,
        }
    )
    save_json(Path(receipt_path).with_suffix(".committed.json"), result)
    return result
