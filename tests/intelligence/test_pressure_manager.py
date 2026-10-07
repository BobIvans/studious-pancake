import hashlib

import pytest

from src.agg02.contracts import Agg02Error, RawEventEnvelope
from src.agg02.storage import DurableRawJournal
from src.intelligence.pressure_manager import (
    pressure_plan,
    run_pressure_cycle,
    select_reclaim_candidates,
)


def event(i: int, payload: bytes) -> RawEventEnvelope:
    return RawEventEnvelope(
        event_id=f"event-{i}",
        source_id="provider",
        chain_id="chain",
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        received_at_ms=i * 1000,
        available_at_ms=i * 1000 + 1,
        decoder_version="v1",
        cursor_source="provider",
        cursor_partition="pairs",
        cursor_offset=i,
        reconnect_epoch=0,
        slot=i,
        commitment="confirmed",
    )


def record(i: int) -> dict:
    return {
        "event_id": f"event-{i}",
        "available_at_ms": i * 1000 + 1,
        "referenced": False,
        "active_experiment": False,
        "reference_inventory_complete": True,
        "representation_verified": True,
        "provenance_verified": True,
        "minimum_samples_retained": True,
        # These are intentionally not asserted before the manager creates
        # and independently verifies the exact compaction.
        "compaction_verified": False,
        "replay_verified": False,
    }


def measured(used: int, budget: int) -> dict:
    return {
        "measured_files_bytes": used,
        "intelligence_budget_bytes": budget,
        "total_disk_bytes": budget * 10,
        "free_disk_bytes": budget * 5,
        "reserve_bytes": budget,
        "spare_bytes": 1_000_000_000,
        "storage_pressure_state": "NORMAL",
    }


def test_pressure_thresholds_and_hysteresis_targets():
    assert pressure_plan(79, 100)["level"] == "NORMAL"
    compact = pressure_plan(80, 100)
    assert compact["level"] == "COMPACT"
    assert compact["requested_reclaim_bytes"] == 5
    prune = pressure_plan(90, 100)
    assert prune["level"] == "PRUNE"
    assert prune["requested_reclaim_bytes"] == 10
    critical = pressure_plan(95, 100)
    assert critical["level"] == "CRITICAL"
    assert critical["requested_reclaim_bytes"] == 10
    assert critical["admission_pause_required"]
    assert not critical["automatic_oldest_fraction_deletion"]


def test_pressure_selection_is_oldest_eligible_not_oldest_fraction(tmp_path):
    path = tmp_path / "raw.db"
    with DurableRawJournal(path) as journal:
        for i in range(1, 5):
            payload = bytes([i]) * 100
            journal.append(event(i, payload), payload)
        journal.pin_retention(["event-1"], evidence_id="important")
        selection = select_reclaim_candidates(
            journal,
            [record(i) for i in range(1, 5)],
            now_ms=200_000_000,
            minimum_age_ms=86_400_000,
            requested_reclaim_bytes=150,
        )
        assert selection["event_ids"] == ["event-2", "event-3"]
        assert selection["logical_reclaim_bytes"] == 200
        assert "event-1" not in selection["event_ids"]


def test_dry_run_never_mutates_payloads(monkeypatch, tmp_path):
    root = tmp_path / "state"
    root.mkdir()
    path = root / "raw.db"
    with DurableRawJournal(path) as journal:
        journal.append(event(1, b"x" * 100), b"x" * 100)
    monkeypatch.setattr(
        "src.intelligence.pressure_manager.read_disk_budget",
        lambda *_args, **_kwargs: measured(95_000, 100_000),
    )
    result = run_pressure_cycle(
        state_root=root,
        journal_path=path,
        records=[record(1)],
        references=[],
        reference_inventory_complete=True,
        output_dir=tmp_path / "pressure",
        execute=False,
        now_ms=200_000_000,
    )
    assert result["status"] == "DRY_RUN"
    with DurableRawJournal(path) as journal:
        inventory = journal.retention_storage_inventory()
        assert inventory[0]["inline_payload_bytes"] == 100
        assert not inventory[0]["archived"]


def test_execute_offloads_only_proven_events_and_keeps_exact_replay(
    monkeypatch, tmp_path
):
    root = tmp_path / "state"
    root.mkdir()
    path = root / "raw.db"
    payloads = {}
    with DurableRawJournal(path) as journal:
        for i in range(1, 5):
            payload = bytes([i]) * 6_000
            payloads[f"event-{i}"] = payload
            journal.append(event(i, payload), payload)
        journal.pin_retention(["event-1"], evidence_id="canonical-episode")

    monkeypatch.setattr(
        "src.intelligence.pressure_manager.read_disk_budget",
        lambda *_args, **_kwargs: measured(95_000, 100_000),
    )
    result = run_pressure_cycle(
        state_root=root,
        journal_path=path,
        records=[record(i) for i in range(1, 5)],
        references=[{"evidence_id": "canonical-episode", "raw_event_ids": ["event-1"]}],
        reference_inventory_complete=True,
        output_dir=tmp_path / "pressure",
        execute=True,
        now_ms=200_000_000,
    )
    assert result["status"] == "COMPLETED_WITH_ADMISSION_PAUSE"
    assert result["archived_events"] == 2
    assert result["selection"]["event_ids"] == ["event-2", "event-3"]
    # Logical page reuse cannot clear an unchanged physical CRITICAL verdict.
    assert result["admission_pause_required"]
    assert not result["physical_reclaim_guaranteed"]

    with DurableRawJournal(path) as journal:
        inventory = {
            row["event_id"]: row for row in journal.retention_storage_inventory()
        }
        assert inventory["event-1"]["pinned"]
        assert not inventory["event-1"]["archived"]
        assert inventory["event-2"]["archived"]
        assert inventory["event-3"]["archived"]
        assert not inventory["event-4"]["archived"]
        for event_id, payload in payloads.items():
            assert journal.payload(event_id) == payload


def test_critical_shortfall_requires_admission_pause(monkeypatch, tmp_path):
    root = tmp_path / "state"
    root.mkdir()
    path = root / "raw.db"
    with DurableRawJournal(path) as journal:
        journal.append(event(1, b"x" * 100), b"x" * 100)
        journal.pin_retention(["event-1"], evidence_id="must-keep")
    monkeypatch.setattr(
        "src.intelligence.pressure_manager.read_disk_budget",
        lambda *_args, **_kwargs: measured(99_000, 100_000),
    )
    result = run_pressure_cycle(
        state_root=root,
        journal_path=path,
        records=[record(1)],
        references=[{"evidence_id": "must-keep", "raw_event_ids": ["event-1"]}],
        reference_inventory_complete=True,
        output_dir=tmp_path / "pressure",
        execute=True,
        now_ms=200_000_000,
    )
    assert result["status"] == "ADMISSION_PAUSE_REQUIRED"
    assert result["admission_pause_required"]
    assert result["reason"] == "NO_VERIFIED_EXPIRABLE_PAYLOADS"


def setup_cycle(monkeypatch, tmp_path, *, used=95_000):
    root = tmp_path / "state"
    root.mkdir()
    journal = root / "raw.db"
    with DurableRawJournal(journal) as owner:
        owner.append(event(1, b"x" * 12_000), b"x" * 12_000)
    monkeypatch.setattr(
        "src.intelligence.pressure_manager.read_disk_budget",
        lambda *_a, **_k: measured(used, 100_000),
    )
    return dict(
        state_root=root,
        journal_path=journal,
        records=[record(1)],
        references=[],
        reference_inventory_complete=True,
        output_dir=tmp_path / "pressure",
        now_ms=200_000_000,
        execute=True,
        batch_id="batch-one",
    )


def test_normal_has_no_filesystem_mutation_or_journal_open(monkeypatch, tmp_path):
    args = setup_cycle(monkeypatch, tmp_path, used=79_000)
    before = {
        p.name: p.read_bytes() for p in args["state_root"].iterdir() if p.is_file()
    }
    monkeypatch.setattr(
        "src.intelligence.pressure_manager.DurableRawJournal",
        lambda *_a: pytest.fail("NORMAL opened a writable journal"),
    )
    assert run_pressure_cycle(**args)["status"] == "NO_ACTION_REQUIRED"
    assert not args["output_dir"].exists()
    assert before == {
        p.name: p.read_bytes() for p in args["state_root"].iterdir() if p.is_file()
    }


def test_complete_inventory_and_safe_compaction_headroom_are_required(
    monkeypatch, tmp_path
):
    args = setup_cycle(monkeypatch, tmp_path)
    args["reference_inventory_complete"] = False
    result = run_pressure_cycle(**args)
    assert result["reason"] == "REFERENCE_INVENTORY_INCOMPLETE"
    assert "selection" not in result
    args["batch_id"] = "no-headroom"
    args["reference_inventory_complete"] = True
    monkeypatch.setattr(
        "src.intelligence.pressure_manager.read_disk_budget",
        lambda *_a, **_k: {**measured(95_000, 100_000), "spare_bytes": 1},
    )
    result = run_pressure_cycle(**args)
    assert result["reason"] == "INSUFFICIENT_SAFE_COMPACTION_HEADROOM"
    assert not list(args["output_dir"].glob("*.parquet"))


def test_pressure_batch_retry_is_identical_and_rejects_rebound(monkeypatch, tmp_path):
    args = setup_cycle(monkeypatch, tmp_path)
    first = run_pressure_cycle(**args)
    args["now_ms"] += 1000
    assert run_pressure_cycle(**args) == first
    assert len(list(args["output_dir"].glob("*.parquet"))) == 1
    args["references"] = [{"evidence_id": "new", "raw_event_ids": ["event-1"]}]
    with pytest.raises(ValueError, match="identity rebound"):
        run_pressure_cycle(**args)


@pytest.mark.parametrize("crash_point", [".committed.json", ".receipt.json"])
def test_restart_recovers_after_offload_without_duplicate_archive(
    monkeypatch, tmp_path, crash_point
):
    import src.intelligence.prune as prune
    import src.intelligence.pressure_manager as manager

    args = setup_cycle(monkeypatch, tmp_path)
    target = prune if crash_point == ".committed.json" else manager
    save = target.save_json

    def interrupted(path, value):
        if str(path).endswith(crash_point):
            raise OSError("simulated crash after durable offload")
        return save(path, value)

    monkeypatch.setattr(target, "save_json", interrupted)
    with pytest.raises(OSError, match="simulated crash"):
        run_pressure_cycle(**args)
    monkeypatch.setattr(target, "save_json", save)
    resumed = run_pressure_cycle(**args)
    assert resumed["archived_events"] == 1
    assert len(list(args["output_dir"].glob("*.parquet"))) == 1
    with DurableRawJournal(args["journal_path"]) as owner:
        assert owner.payload("event-1") == b"x" * 12_000
    assert run_pressure_cycle(**args) == resumed


def test_cross_process_lock_blocks_a_second_pressure_cycle(monkeypatch, tmp_path):
    import fcntl

    args = setup_cycle(monkeypatch, tmp_path)
    with args["journal_path"].open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="ALREADY_RUNNING"):
            run_pressure_cycle(**args)
    assert not args["output_dir"].exists()


def test_references_and_owner_age_are_checked_before_selection(tmp_path):
    path = tmp_path / "raw.db"
    with DurableRawJournal(path) as journal:
        for i in range(1, 4):
            journal.append(event(i, b"x"), b"x")
        forged = record(2)
        forged["available_at_ms"] = 0
        selection = select_reclaim_candidates(
            journal,
            [record(1), forged, record(3)],
            now_ms=200_000_000,
            minimum_age_ms=86_400_000,
            requested_reclaim_bytes=10,
            references=[{"evidence_id": "pin", "raw_event_ids": ["event-1"]}],
        )
        assert selection["event_ids"] == ["event-3"]
        with pytest.raises(ValueError, match="duplicate"):
            select_reclaim_candidates(
                journal,
                [record(3), record(3)],
                now_ms=200_000_000,
                minimum_age_ms=86_400_000,
                requested_reclaim_bytes=10,
            )


def test_cli_pressure_dry_run_execute_and_stable_retry(monkeypatch, tmp_path, capsys):
    import json
    from src.intelligence.cli import main
    from src.intelligence.common import save_json

    args = setup_cycle(monkeypatch, tmp_path)
    records = tmp_path / "records.json"
    refs = tmp_path / "refs.json"
    save_json(records, {"records": args["records"]})
    save_json(refs, {"records": [], "inventory_complete": True})
    argv = [
        "--state-root",
        str(args["state_root"]),
        "storage",
        "pressure",
        "--journal",
        str(args["journal_path"]),
        "--records",
        str(records),
        "--references",
        str(refs),
        "--out",
        str(args["output_dir"]),
        "--batch-id",
        "cli-batch",
    ]
    assert main(argv) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "DRY_RUN"
    assert main(argv + ["--execute"]) == 3
    first = json.loads(capsys.readouterr().out)
    assert first["archived_events"] == 1
    assert main(argv + ["--execute"]) == 3
    assert json.loads(capsys.readouterr().out) == first


def test_real_boundary_pauses_canonical_supervisor_and_persists_receipts(
    monkeypatch, tmp_path
):
    import asyncio
    from src.intelligence.pressure_boundary import StoragePressureBoundary
    from src.paper_shadow.repeated_service_pr04 import RepeatedInstalledPaperService
    from tests.test_pr04_repeated_installed_paper_service import _Runner, _report

    args = setup_cycle(monkeypatch, tmp_path)
    runner = _Runner([_report(1)])
    runner.storage_pressure_boundary = StoragePressureBoundary(
        state_root=args["state_root"],
        journal_path=args["journal_path"],
        output_dir=args["output_dir"],
        inventory=lambda: {
            "records": args["records"],
            "references": [],
            "inventory_complete": True,
        },
    )
    summary = asyncio.run(RepeatedInstalledPaperService(runner).run(asyncio.Event()))
    assert runner.calls == 0
    assert summary.stop_reason.value == "storage_pressure"
    assert summary.storage_pressure_receipts[0]["cycle"]["archived_events"] == 1
    assert len(list(args["output_dir"].glob("blocker-*.json"))) == 1
    with DurableRawJournal(args["journal_path"]) as owner:
        assert owner.payload("event-1") == b"x" * 12000


def test_cached_receipt_rechecks_corrupt_archive(monkeypatch, tmp_path):
    args = setup_cycle(monkeypatch, tmp_path)
    result = run_pressure_cycle(**args)
    from pathlib import Path

    Path(result["compaction"]["dataset"]["path"]).write_bytes(b"corrupt")
    with pytest.raises(Agg02Error, match="CHECKSUM_MISMATCH"):
        run_pressure_cycle(**args)


def test_prune_that_becomes_physically_critical_also_pauses(monkeypatch, tmp_path):
    args = setup_cycle(monkeypatch, tmp_path, used=90_000)
    result = run_pressure_cycle(**args)
    assert result["plan"]["level"] == "PRUNE"
    assert result["after_plan"]["level"] == "CRITICAL"
    assert result["admission_pause_required"]
