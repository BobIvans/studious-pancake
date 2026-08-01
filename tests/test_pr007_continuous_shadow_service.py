from __future__ import annotations
import sqlite3, time
from src.paper_shadow.faults import ALERTS, FAULTS, run_campaign
from src.paper_shadow.service import (
    DataLineage,
    Probe,
    READINESS_PROBES,
    RuntimeMode,
    SoakLedger,
    compute_readiness,
    fixture_bindings,
    verify_soak,
)


def healthy_probes():
    now = time.time_ns()
    return {name: Probe(True, 1, now) for name in READINESS_PROBES}


def test_liveness_is_not_readiness_and_every_probe_is_required():
    assert compute_readiness(RuntimeMode.SAFE_IDLE, healthy_probes())["live"]
    assert not compute_readiness(RuntimeMode.SAFE_IDLE, healthy_probes())["ready"]
    probes = healthy_probes()
    probes.pop("reconciliation")
    report = compute_readiness(RuntimeMode.SHADOW, probes)
    assert not report["ready"] and "missing:reconciliation" in report["blockers"]
    probes = healthy_probes()
    probes["tasks"] = Probe(False, 1, time.time_ns(), "dead_worker")
    assert not compute_readiness(RuntimeMode.PAPER, probes)["ready"]


def test_unique_cycles_are_release_bound_and_fixture_soak_cannot_promote(tmp_path):
    ledger = SoakLedger(tmp_path)
    first = ledger.append(
        lineage=DataLineage.SYNTHETIC_FIXTURE, bindings=fixture_bindings(0)
    )
    second = ledger.append(
        lineage=DataLineage.SYNTHETIC_FIXTURE, bindings=fixture_bindings(1)
    )
    ledger.close()
    assert first["cycle_id"] != second["cycle_id"]
    report = verify_soak(tmp_path, minimum_hours=0)
    assert not report["verified"]
    assert "non_promotion_lineage" in report["blockers"]
    assert report["signer_available"] is False
    assert report["submission_available"] is False


def test_independent_verifier_detects_hash_chain_tampering(tmp_path):
    ledger = SoakLedger(tmp_path)
    ledger.append(
        lineage=DataLineage.CREDENTIALED_PROVIDER_SNAPSHOT, bindings=fixture_bindings(0)
    )
    ledger.close()
    db = sqlite3.connect(tmp_path / "cycles.sqlite3")
    db.execute("UPDATE cycles SET data_hash='bad'")
    db.commit()
    db.close()
    assert any(
        x.startswith("integrity:")
        for x in verify_soak(tmp_path, minimum_hours=0)["blockers"]
    )


def test_fault_campaign_is_complete_release_bound_and_blocks_readiness():
    release = "a" * 64
    results = run_campaign(release)
    assert {x.fault for x in results} == set(FAULTS)
    assert all(x.readiness_blocked and x.release_digest == release for x in results)
    assert {x.alert for x in results if x.alert} == set(ALERTS.values())


def test_no_unrestricted_live_signer_or_submission_state():
    assert {m.value for m in RuntimeMode} == {
        "safe-idle",
        "paper",
        "shadow",
        "live-gate/canary-blocked",
    }
    report = compute_readiness(RuntimeMode.SHADOW, healthy_probes())
    assert (
        report["ready"]
        and not report["signer_available"]
        and not report["submission_available"]
    )
