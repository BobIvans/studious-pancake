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

from .common import canonical, digest, load_json, save_json, seal, verify_seal
from .evidence_refs import find_raw_references
from .parquet_compaction import publish_partition
from .prune import prune_verified_payloads
from .retention_policy import retention_dry_run, retention_eligibility
from .storage_budget import read_disk_budget

PPM = 1_000_000
COMPACT_THRESHOLD_PPM = 800_000
PRUNE_THRESHOLD_PPM = 900_000
CRITICAL_THRESHOLD_PPM = 950_000
DEFAULT_PARTITION_PAYLOAD_BYTES = 128 * 1024 * 1024
COMPACTION_HEADROOM_BYTES = 16 * 1024 * 1024

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


def _planning_eligible(
    record: Mapping[str, object], *, now_ms: int, minimum_age_ms: int
) -> bool:
    # Compaction and replay are created by this cycle. All other gates must
    # already be proven before the event can even be selected for offload.
    probe = dict(record)
    probe["compaction_verified"] = True
    probe["replay_verified"] = True
    return (
        retention_eligibility(probe, now_ms=now_ms, minimum_age_ms=minimum_age_ms)[
            "eligible"
        ]
        is True
    )


def select_reclaim_candidates(
    journal: DurableRawJournal,
    records: Iterable[Mapping[str, object]],
    *,
    now_ms: int,
    minimum_age_ms: int,
    requested_reclaim_bytes: int,
    max_events: int = 20_000,
    max_payload_bytes: int = DEFAULT_PARTITION_PAYLOAD_BYTES,
    references: list[dict] | None = None,
) -> dict:
    if requested_reclaim_bytes < 0 or max_events < 1 or max_payload_bytes < 1:
        raise ValueError("invalid reclaim budget")
    storage = {row["event_id"]: row for row in journal.retention_storage_inventory()}
    candidates = []
    seen: set[str] = set()
    referenced = find_raw_references(references or [])
    for source in records:
        record = dict(source)
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or event_id not in storage:
            continue
        if event_id in seen:
            raise ValueError("duplicate retention event")
        seen.add(event_id)
        facts = storage[event_id]
        inline_bytes = facts["inline_payload_bytes"]
        available = facts["available_at_ms"]
        if (
            facts["archived"]
            or facts["pinned"]
            or facts["gap_before"]
            or event_id in referenced
            or not isinstance(inline_bytes, int)
            or inline_bytes <= 0
            or type(available) is not int
            or record.get("available_at_ms") != available
        ):
            continue
        if not _planning_eligible(record, now_ms=now_ms, minimum_age_ms=minimum_age_ms):
            continue
        candidates.append(
            (
                available,
                event_id,
                inline_bytes,
                record,
            )
        )
    candidates.sort(key=lambda item: (item[0], item[1]))
    selected: list[dict] = []
    selected_bytes = 0
    for _, event_id, inline_bytes, record in candidates:
        if len(selected) >= max_events:
            break
        if inline_bytes > max_payload_bytes:
            continue
        if selected and selected_bytes + inline_bytes > max_payload_bytes:
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


def _run_pressure_cycle_locked(
    *,
    state_root: str | Path,
    journal_path: str | Path,
    records: list[dict],
    references: list[dict],
    reference_inventory_complete: bool,
    output_dir: str | Path,
    minimum_age_ms: int = 86_400_000,
    max_events: int = 20_000,
    max_payload_bytes: int = DEFAULT_PARTITION_PAYLOAD_BYTES,
    execute: bool = False,
    now_ms: int | None = None,
    cycle_key: str,
    request_sha: str,
) -> dict:
    state_root = Path(state_root)
    journal_path = Path(journal_path)
    output_dir = Path(output_dir)
    now = int(time.time() * 1000) if now_ms is None else now_ms
    if now < 0:
        raise ValueError("invalid pressure clock")
    if not journal_path.is_file():
        raise ValueError("pressure journal missing")
    measurement = read_disk_budget(state_root)
    used = _managed_used(measurement, state_root, journal_path, output_dir)
    plan = pressure_plan(used, int(measurement["intelligence_budget_bytes"]))
    base = {
        "plan": plan,
        "measurement": measurement,
        "execute_requested": execute,
        "physical_reclaim_guaranteed": False,
        "sqlite_vacuum_performed": False,
        "cycle_key": cycle_key,
        "request_sha256": request_sha,
    }
    prepared_path = output_dir / f"pressure-{cycle_key}.prepare.json"
    prepared = load_json(prepared_path) if prepared_path.exists() else None
    if prepared is not None:
        verify_seal(prepared)
        if prepared["request_sha256"] != request_sha:
            raise ValueError("pressure batch identity rebound")
        now, base, plan = prepared["now_ms"], prepared["base"], prepared["base"]["plan"]
    if prepared is None and (
        plan["level"] == "NORMAL" or plan["requested_reclaim_bytes"] == 0
    ):
        return seal({**base, "status": "NO_ACTION_REQUIRED"})
    if reference_inventory_complete is not True:
        return seal(
            {
                **base,
                "status": (
                    "ADMISSION_PAUSE_REQUIRED"
                    if plan["level"] == "CRITICAL"
                    else "REFERENCE_INVENTORY_INCOMPLETE"
                ),
                "reason": "REFERENCE_INVENTORY_INCOMPLETE",
                "admission_pause_required": plan["level"] == "CRITICAL",
            }
        )
    with DurableRawJournal(journal_path) as journal:
        selection = select_reclaim_candidates(
            journal,
            records,
            now_ms=now,
            minimum_age_ms=minimum_age_ms,
            requested_reclaim_bytes=int(plan["requested_reclaim_bytes"]),
            max_events=max_events,
            max_payload_bytes=max_payload_bytes,
            references=references,
        )
        if prepared is not None:
            selection = prepared["selection"]
        planned = {**base, "selection": selection}
        if not selection["event_ids"]:
            return seal(
                {
                    **planned,
                    "status": (
                        "ADMISSION_PAUSE_REQUIRED"
                        if plan["level"] == "CRITICAL"
                        else "NO_SAFE_RECLAIM_CANDIDATES"
                    ),
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
        if reference_inventory_complete is not True:
            return seal(
                {
                    **planned,
                    "status": "ADMISSION_PAUSE_REQUIRED",
                    "reason": "REFERENCE_INVENTORY_INCOMPLETE",
                    "admission_pause_required": True,
                }
            )
        owner_inventory = {
            r["event_id"]: r for r in journal.retention_storage_inventory()
        }
        envelope_bytes = sum(
            _integer(owner_inventory[event_id]["envelope_bytes"])
            for event_id in selection["event_ids"]
        )
        preflight_bytes = (
            int(selection["logical_reclaim_bytes"]) * 3
            + envelope_bytes * 4
            + len(canonical(selection["records"])) * 4
            + COMPACTION_HEADROOM_BYTES
        )
        headroom = read_disk_budget(state_root)
        if preflight_bytes > int(headroom["spare_bytes"]):
            return seal(
                {
                    **planned,
                    "status": (
                        "ADMISSION_PAUSE_REQUIRED"
                        if plan["level"] == "CRITICAL"
                        else "COMPACTION_HEADROOM_BLOCKED"
                    ),
                    "reason": "INSUFFICIENT_SAFE_COMPACTION_HEADROOM",
                    "compaction_preflight_bytes": preflight_bytes,
                    "admission_pause_required": plan["level"] == "CRITICAL",
                }
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        if prepared is None:
            save_json(
                prepared_path,
                seal(
                    {
                        "request_sha256": request_sha,
                        "now_ms": now,
                        "base": base,
                        "selection": selection,
                    }
                ),
            )
        parquet = output_dir / f"pressure-{cycle_key}.parquet"
        compaction = publish_partition(
            journal,
            parquet,
            event_ids=set(selection["event_ids"]),
            max_rows=max_events,
            max_payload_bytes=max_payload_bytes,
        )
        proven = []
        for record in selection["records"]:
            item = dict(record)
            item["compaction_verified"] = True
            item["replay_verified"] = True
            proven.append(item)
        retention = retention_dry_run(proven, now_ms=now, minimum_age_ms=minimum_age_ms)
        if {d["event_id"] for d in retention["decisions"] if d["eligible"]} != set(
            selection["event_ids"]
        ):
            raise ValueError("pressure retention proof changed after compaction")
        retention_path = output_dir / f"pressure-{cycle_key}.retention.json"
        save_json(retention_path, retention)
        tombstone_path = output_dir / f"pressure-{cycle_key}.tombstone.json"
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
            _integer(row["inline_payload_bytes"]) for row in after_inventory.values()
        )
        shortfall = max(
            0,
            int(plan["requested_reclaim_bytes"])
            - int(selection["logical_reclaim_bytes"]),
        )
        after_measurement = read_disk_budget(state_root)
        after_used = _managed_used(
            after_measurement, state_root, journal_path, output_dir
        )
        after_plan = pressure_plan(
            after_used, int(after_measurement["intelligence_budget_bytes"])
        )
        pause = after_plan["level"] == "CRITICAL" or (
            plan["level"] == "CRITICAL" and shortfall > 0
        )
        return seal(
            {
                **planned,
                "status": (
                    "COMPLETED_WITH_ADMISSION_PAUSE"
                    if pause
                    else ("COMPLETED_PARTIAL" if shortfall else "COMPLETED")
                ),
                "compaction": compaction,
                "retention_receipt_sha256": retention["receipt_sha256"],
                "prune_receipt_sha256": result["receipt_sha256"],
                "archived_events": result["archived_events"],
                "logical_reclaim_bytes": selection["logical_reclaim_bytes"],
                "reclaim_shortfall_bytes": shortfall,
                "remaining_inline_payload_bytes": remaining_inline,
                "admission_pause_required": pause,
                "after_plan": after_plan,
                "physical_reclaim_guaranteed": False,
                "physical_reclaim_note": (
                    "Inline SQLite payload pages are reusable after offload; the database file "
                    "does not necessarily shrink until a separately qualified maintenance operation."
                ),
            }
        )


def _integer(value: object) -> int:
    if not isinstance(value, int):
        raise ValueError("invalid owner byte accounting")
    return value


def _managed_used(measurement: dict, root: Path, journal: Path, output: Path) -> int:
    used = int(measurement["measured_files_bytes"])
    extra: set[Path] = set()
    if not journal.resolve().is_relative_to(root.resolve()):
        extra.update(
            p.resolve()
            for p in (journal, Path(str(journal) + "-wal"), Path(str(journal) + "-shm"))
            if p.exists()
        )
    if output.exists() and not output.resolve().is_relative_to(root.resolve()):
        extra.update(
            p.resolve()
            for p in output.rglob("*")
            if p.is_file()
            and not p.is_symlink()
            and not p.resolve().is_relative_to(root.resolve())
        )
    used += sum(p.stat().st_size for p in extra)
    return used


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
    max_payload_bytes: int = DEFAULT_PARTITION_PAYLOAD_BYTES,
    execute: bool = False,
    now_ms: int | None = None,
    batch_id: str | None = None,
) -> dict:
    """One cross-process cycle, outside append; stable batch receipts survive restart."""
    root, journal, output = Path(state_root), Path(journal_path), Path(output_dir)
    if not root.is_dir() or not journal.is_file():
        raise ValueError("existing pressure state root and journal required")
    if (
        minimum_age_ms < 1
        or max_events < 1
        or max_payload_bytes < 1
        or (now_ms is not None and now_ms < 0)
    ):
        raise ValueError("invalid pressure limits/clock")
    if batch_id is not None and not batch_id:
        raise ValueError("nonempty pressure batch identity required")
    request_sha = digest(
        {
            "root": str(root.resolve()),
            "journal": str(journal.resolve()),
            "output": str(output.resolve()),
            "records": records,
            "references": references,
            "complete": reference_inventory_complete,
            "age": minimum_age_ms,
            "events": max_events,
            "bytes": max_payload_bytes,
            "execute": execute,
        }
    )
    key = (
        digest({"batch_id": batch_id})
        if batch_id is not None
        else digest(
            {
                "request": request_sha,
                "now": now_ms if now_ms is not None else time.time_ns(),
            }
        )
    )
    receipt_path = output / f"pressure-{key}.receipt.json"
    measurement = read_disk_budget(root)
    plan = pressure_plan(
        _managed_used(measurement, root, journal, output),
        int(measurement["intelligence_budget_bytes"]),
    )
    recovery = (
        output / f"pressure-{key}.prepare.json"
    ).exists() or receipt_path.exists()
    if plan["level"] == "NORMAL" and not recovery:
        return seal(
            {
                "plan": plan,
                "measurement": measurement,
                "status": "NO_ACTION_REQUIRED",
                "admission_pause_required": False,
                "execute_requested": execute,
                "physical_reclaim_guaranteed": False,
                "sqlite_vacuum_performed": False,
            }
        )
    # Lock the existing inode: NORMAL never creates even a lock file. No thread
    # is hidden in the journal and SQLite append transactions remain independent.
    import fcntl

    with journal.open("rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("STORAGE_PRESSURE_CYCLE_ALREADY_RUNNING") from exc
        if receipt_path.exists():
            receipt = load_json(receipt_path)
            verify_seal(receipt)
            if receipt["request_sha256"] != request_sha:
                raise ValueError("pressure batch identity rebound")
            if "compaction" in receipt:
                from src.agg02.storage import DatasetManifest
                from .parquet_compaction import verify_partition

                verify_partition(DatasetManifest(**receipt["compaction"]["dataset"]))
            return receipt
        ancestor = output
        while not ancestor.exists():
            ancestor = ancestor.parent
        if ancestor.stat().st_dev != root.stat().st_dev:
            raise ValueError("pressure output must share the measured filesystem")
        result = _run_pressure_cycle_locked(
            state_root=root,
            journal_path=journal,
            records=records,
            references=references,
            reference_inventory_complete=reference_inventory_complete,
            output_dir=output,
            minimum_age_ms=minimum_age_ms,
            max_events=max_events,
            max_payload_bytes=max_payload_bytes,
            execute=execute,
            now_ms=now_ms,
            cycle_key=key,
            request_sha=request_sha,
        )
        if execute and result["status"] != "NO_ACTION_REQUIRED":
            save_json(receipt_path, result)
        return result


__all__ = [
    "COMPACT_THRESHOLD_PPM",
    "PRUNE_THRESHOLD_PPM",
    "CRITICAL_THRESHOLD_PPM",
    "DEFAULT_PARTITION_PAYLOAD_BYTES",
    "pressure_plan",
    "select_reclaim_candidates",
    "run_pressure_cycle",
]
