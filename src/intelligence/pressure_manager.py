"""Automatic, fail-closed storage-pressure orchestration.

The manager never deletes evidence by age/fraction alone. It prepares exact
Parquet replay, then offloads only deterministic retention-eligible inline raw
payloads. Critical pressure pauses admission when safe reclaim is insufficient.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping
import time

from src.agg02.storage import DurableRawJournal

from .common import digest, save_json, seal
from .parquet_compaction import publish_partition
from .prune import prune_verified_payloads
from .retention_policy import retention_dry_run, retention_eligibility
from .storage_budget import read_disk_budget

PPM = 1_000_000
COMPACT_THRESHOLD_PPM = 800_000
PRUNE_THRESHOLD_PPM = 900_000
CRITICAL_THRESHOLD_PPM = 950_000

# Hysteresis targets: reclaim enough to get materially below the threshold,
# never a fixed fraction of the oldest corpus.
TARGET_PPM = {
    "COMPACT": 750_000,
    "PRUNE": 800_000,
    "CRITICAL": 850_000,
}


def pressure_plan(used_bytes: int, budget_bytes: int) -> dict:
    if used_bytes < 0 or budget_bytes < 0:
        raise ValueError("negative storage")
    if budget_bytes == 0:
        level = "CRITICAL" if used_bytes else "NORMAL"
        ratio_ppm = PPM if used_bytes else 0
    else:
        ratio_ppm = min(PPM * 10, used_bytes * PPM // budget_bytes)
        if ratio_ppm < COMPACT_THRESHOLD_PPM:
            level = "NORMAL"
        elif ratio_ppm < PRUNE_THRESHOLD_PPM:
            level = "COMPACT"
        elif ratio_ppm < CRITICAL_THRESHOLD_PPM:
            level = "PRUNE"
        else:
            level = "CRITICAL"
    target_ppm = TARGET_PPM.get(level)
    target_bytes = (
        budget_bytes * target_ppm // PPM if target_ppm is not None else used_bytes
    )
    reclaim = max(0, used_bytes - target_bytes)
    return {
        "schema": "studious.storage-pressure-plan.v1",
        "level": level,
        "used_bytes": used_bytes,
        "budget_bytes": budget_bytes,
        "usage_ratio_ppm": ratio_ppm,
        "target_ratio_ppm": target_ppm,
        "target_bytes": target_bytes,
        "requested_reclaim_bytes": reclaim,
        "automatic_oldest_fraction_deletion": False,
        "admission_pause_required": level == "CRITICAL",
        "model_authority": False,
    }


def _planning_eligible(record: Mapping[str, object], *, now_ms: int, minimum_age_ms: int) -> bool:
    # Compaction and replay are created by this cycle. All other gates must
    # already be proven before the event can even be selected for offload.
    probe = dict(record)
    probe["compaction_verified"] = True
    probe["replay_verified"] = True
    return retention_eligibility(
        probe, now_ms=now_ms, minimum_age_ms=minimum_age_ms
    )["eligible"] is True


def select_reclaim_candidates(
    journal: DurableRawJournal,
    records: Iterable[Mapping[str, object]],
    *,
    now_ms: int,
    minimum_age_ms: int,
    requested_reclaim_bytes: int,
    max_events: int = 20_000,
) -> dict:
    if requested_reclaim_bytes < 0 or max_events < 1:
        raise ValueError("invalid reclaim budget")
    storage = {row["event_id"]: row for row in journal.retention_storage_inventory()}
    candidates = []
    for source in records:
        record = dict(source)
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or event_id not in storage:
            continue
        facts = storage[event_id]
        if facts["archived"] or facts["pinned"] or facts["inline_payload_bytes"] <= 0:
            continue
        if not _planning_eligible(
            record, now_ms=now_ms, minimum_age_ms=minimum_age_ms
        ):
            continue
        candidates.append(
            (
                int(record.get("available_at_ms", 0)),
                event_id,
                int(facts["inline_payload_bytes"]),
                record,
            )
        )
    candidates.sort(key=lambda item: (item[0], item[1]))
    selected: list[dict] = []
    selected_bytes = 0
    for _, event_id, inline_bytes, record in candidates:
        if len(selected) >= max_events:
            break
        selected.append(record)
        selected_bytes += inline_bytes
        if requested_reclaim_bytes and selected_bytes >= requested_reclaim_bytes:
            break
    return {
        "event_ids": [r["event_id"] for r in selected],
        "records": selected,
        "logical_reclaim_bytes": selected_bytes,
        "requested_reclaim_bytes": requested_reclaim_bytes,
        "candidate_count": len(candidates),
        "selected_count": len(selected),
    }


def run_pressure_cycle(
    *,
    state_root: str | Path,
    journal_path: str | Path,
    records: list[dict],
    references: list[dict],
    reference_inventory_complete: bool,
    output_dir: str | Path,
    minimum_age_ms: int = 86_400_000,
    max_events: int = 20_000,
    execute: bool = False,
    now_ms: int | None = None,
) -> dict:
    state_root = Path(state_root)
    journal_path = Path(journal_path)
    output_dir = Path(output_dir)
    now = int(time.time() * 1000) if now_ms is None else now_ms
    if now < 0:
        raise ValueError("invalid pressure clock")
    measurement = read_disk_budget(state_root, journal=journal_path)
    used = int(measurement["measured_files_bytes"])
    # If the AGG-02 journal is outside the managed state root, count its physical
    # SQLite/WAL footprint once. This is disk-pressure accounting, not raw-data semantics.
    try:
        journal_inside = journal_path.resolve().is_relative_to(state_root.resolve())
    except FileNotFoundError:
        journal_inside = False
    if not journal_inside:
        used += sum(
            path.stat().st_size
            for path in (
                journal_path,
                Path(str(journal_path) + "-wal"),
                Path(str(journal_path) + "-shm"),
            )
            if path.exists()
        )
    plan = pressure_plan(used, int(measurement["intelligence_budget_bytes"]))
    base = {
        "plan": plan,
        "measurement": measurement,
        "execute_requested": execute,
        "physical_reclaim_guaranteed": False,
        "sqlite_vacuum_performed": False,
    }
    if plan["level"] == "NORMAL" or plan["requested_reclaim_bytes"] == 0:
        return seal({**base, "status": "NO_ACTION_REQUIRED"})
    if not journal_path.is_file():
        return seal({**base, "status": "BLOCKED", "reason": "JOURNAL_MISSING"})
    with DurableRawJournal(journal_path) as journal:
        selection = select_reclaim_candidates(
            journal,
            records,
            now_ms=now,
            minimum_age_ms=minimum_age_ms,
            requested_reclaim_bytes=int(plan["requested_reclaim_bytes"]),
            max_events=max_events,
        )
        planned = {**base, "selection": selection}
        if not selection["event_ids"]:
            return seal(
                {
                    **planned,
                    "status": "ADMISSION_PAUSE_REQUIRED" if plan["level"] == "CRITICAL" else "NO_SAFE_RECLAIM_CANDIDATES",
                    "reason": "NO_VERIFIED_EXPIRABLE_PAYLOADS",
                    "admission_pause_required": plan["level"] == "CRITICAL",
                }
            )
        if not execute:
            return seal(
                {
                    **planned,
                    "status": "DRY_RUN",
                    "admission_pause_required": plan["level"] == "CRITICAL",
                }
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        batch_id = digest(
            {
                "now_ms": now,
                "level": plan["level"],
                "event_ids": selection["event_ids"],
            }
        )[:20]
        parquet = output_dir / f"pressure-{now}-{batch_id}.parquet"
        compaction = publish_partition(
            journal,
            parquet,
            event_ids=set(selection["event_ids"]),
            max_rows=max_events,
        )
        proven = []
        for record in selection["records"]:
            item = dict(record)
            item["compaction_verified"] = True
            item["replay_verified"] = True
            proven.append(item)
        retention = retention_dry_run(
            proven, now_ms=now, minimum_age_ms=minimum_age_ms
        )
        if {d["event_id"] for d in retention["decisions"] if d["eligible"]} != set(
            selection["event_ids"]
        ):
            raise ValueError("pressure retention proof changed after compaction")
        retention_path = output_dir / f"pressure-{now}-{batch_id}.retention.json"
        save_json(retention_path, retention)
        tombstone_path = output_dir / f"pressure-{now}-{batch_id}.tombstone.json"
        result = prune_verified_payloads(
            journal,
            compaction=compaction,
            retention=retention,
            references=references,
            records=proven,
            receipt_path=tombstone_path,
            inventory_complete=reference_inventory_complete,
        )
        after_inventory = {
            row["event_id"]: row for row in journal.retention_storage_inventory()
        }
        remaining_inline = sum(
            int(row["inline_payload_bytes"]) for row in after_inventory.values()
        )
        shortfall = max(
            0,
            int(plan["requested_reclaim_bytes"])
            - int(selection["logical_reclaim_bytes"]),
        )
        pause = plan["level"] == "CRITICAL" and shortfall > 0
        return seal(
            {
                **planned,
                "status": "COMPLETED_WITH_ADMISSION_PAUSE" if pause else "COMPLETED",
                "compaction": compaction,
                "retention_receipt_sha256": retention["receipt_sha256"],
                "prune_receipt_sha256": result["receipt_sha256"],
                "archived_events": result["archived_events"],
                "logical_reclaim_bytes": selection["logical_reclaim_bytes"],
                "reclaim_shortfall_bytes": shortfall,
                "remaining_inline_payload_bytes": remaining_inline,
                "admission_pause_required": pause,
                "physical_reclaim_guaranteed": False,
                "physical_reclaim_note": (
                    "Inline SQLite payload pages are reusable after offload; the database file "
                    "does not necessarily shrink until a separately qualified maintenance operation."
                ),
            }
        )


__all__ = [
    "COMPACT_THRESHOLD_PPM",
    "PRUNE_THRESHOLD_PPM",
    "CRITICAL_THRESHOLD_PPM",
    "pressure_plan",
    "select_reclaim_candidates",
    "run_pressure_cycle",
]
