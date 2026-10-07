import hashlib
from pathlib import Path

import pytest

from src.agg02.contracts import RawEventEnvelope, Agg02Error
from src.agg02.storage import DurableRawJournal
from src.intelligence.parquet_compaction import publish_partition, verify_partition
from src.intelligence.prune import prune_verified_payloads
from src.intelligence.retention_policy import retention_dry_run
from src.intelligence.rollups import build_1m_rollup, verify_rollup_coverage
from src.intelligence.sampling import (
    reservoir_sample_failures,
    select_periodic_baseline,
)
from src.intelligence.storage_budget import (
    compute_dynamic_budget,
    forecast_days_until_budget,
)


def event(i, payload):
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


def eligibility(rows):
    return [
        {
            **{k: v for k, v in r.items() if k != "payload"},
            "referenced": False,
            "active_experiment": False,
            **{
                k: True
                for k in (
                    "reference_inventory_complete",
                    "representation_verified",
                    "provenance_verified",
                    "compaction_verified",
                    "replay_verified",
                    "minimum_samples_retained",
                )
            },
        }
        for r in rows
    ]


def test_real_owner_zstd_replay_prune_receipts_and_pins(tmp_path):
    with DurableRawJournal(tmp_path / "raw.db") as journal:
        for i in range(1, 5):
            payload = bytes([i]) * 1000
            journal.append(event(i, payload), payload)
        rows = journal.retention_rows()
        rollup = build_1m_rollup(list(rows))
        assert verify_rollup_coverage(rollup, list(rows))["covered_events"] == 4
        compaction = publish_partition(journal, tmp_path / "raw.parquet")
        records = eligibility(rows)
        retention = retention_dry_run(records, now_ms=200_000_000)
        with pytest.raises(ValueError, match="unknown"):
            prune_verified_payloads(
                journal,
                compaction=compaction,
                retention=retention,
                references=[],
                records=records,
                receipt_path=tmp_path / "unknown.json",
            )
        journal.pin_retention(["event-1"], evidence_id="episode-1")
        with pytest.raises(ValueError, match="pin"):
            prune_verified_payloads(
                journal,
                compaction=compaction,
                retention=retention,
                references=[],
                records=records,
                inventory_complete=True,
                receipt_path=tmp_path / "pinned.json",
            )
        records[0]["candidate_window"] = True
        retention = retention_dry_run(records, now_ms=200_000_000)
        result = prune_verified_payloads(
            journal,
            compaction=compaction,
            retention=retention,
            references=[{"evidence_id": "episode-1", "raw_event_ids": ["event-1"]}],
            records=records,
            inventory_complete=True,
            receipt_path=tmp_path / "tombstone.json",
        )
        assert result["archived_events"] == 3
        assert journal.replay_event_ids() == tuple(f"event-{i}" for i in range(1, 5))
        for i in range(1, 5):
            assert journal.payload(f"event-{i}") == bytes([i]) * 1000
        assert journal.cursor("provider", "pairs").offset == 4
        assert not journal.append(
            event(2, bytes([2]) * 1000), bytes([2]) * 1000
        ).inserted
        assert (tmp_path / "tombstone.committed.json").exists()
    with DurableRawJournal(tmp_path / "raw.db") as reopened:
        assert reopened.payload("event-3") == bytes([3]) * 1000
    (tmp_path / "raw.parquet").write_bytes(b"corruption")
    with DurableRawJournal(tmp_path / "raw.db") as reopened:
        with pytest.raises(Agg02Error, match="CHECKSUM"):
            reopened.payload("event-3")


@pytest.mark.parametrize(
    "flag",
    [
        "active_experiment",
        "referenced",
        "candidate_window",
        "baseline_sample",
        "gap_before",
        "correction",
        "retraction",
        "replay_mismatch",
        "unique_anomaly",
    ],
)
def test_protected_retention_classes_never_expire(flag):
    record = eligibility([{"event_id": "x", "available_at_ms": 0}])[0]
    record[flag] = True
    assert not retention_dry_run([record], now_ms=200_000_000)["decisions"][0][
        "eligible"
    ]


def test_missing_proofs_and_young_events_fail_closed():
    assert not retention_dry_run(
        [{"event_id": "x", "available_at_ms": 0}], now_ms=200_000_000
    )["decisions"][0]["eligible"]
    assert not retention_dry_run(
        eligibility([{"event_id": "x", "available_at_ms": 0}]), now_ms=100
    )["decisions"][0]["eligible"]


def test_bounded_deterministic_failure_and_baseline_samples():
    rows = [
        {
            "event_id": str(i),
            "available_at_ms": i * 1000,
            "source_id": "p",
            "instrument_id": "pair",
            "reason_code": "REPEAT",
        }
        for i in range(100)
    ]
    sampled = reservoir_sample_failures(rows, per_class=5)
    assert len(sampled) == 5 and "0" in sampled and "99" in sampled
    assert sampled == reservoir_sample_failures(list(reversed(rows)), per_class=5)
    assert select_periodic_baseline(rows) == ["0"]
    assert (
        compute_dynamic_budget(100_000_000_000, 20_000_000_000)[
            "storage_pressure_state"
        ]
        == "STORAGE_PRESSURE"
    )
    assert (
        forecast_days_until_budget(1, 100, None, None)["projected_bytes_per_day"]
        is None
    )
    assert (
        forecast_days_until_budget(0, 86400, 1, 1)["projected_days_until_budget"] == 1
    )
