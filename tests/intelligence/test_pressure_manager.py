import hashlib

from src.agg02.contracts import RawEventEnvelope
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
        "spare_bytes": budget * 4,
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
    assert result["status"] == "COMPLETED"
    assert result["archived_events"] == 2
    assert result["selection"]["event_ids"] == ["event-2", "event-3"]
    assert not result["admission_pause_required"]
    assert not result["physical_reclaim_guaranteed"]

    with DurableRawJournal(path) as journal:
        inventory = {row["event_id"]: row for row in journal.retention_storage_inventory()}
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
