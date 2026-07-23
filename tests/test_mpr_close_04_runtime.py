from __future__ import annotations

import json
from pathlib import Path

from src.mpr_close_04_runtime import (
    materialize_evidence,
    open_persistence,
    publish_backup,
    readiness_state,
    reconcile_economics,
    run_shadow_soak_fixture,
    validate_backup,
    validate_shadow_soak,
)


def test_persistence_factory_creates_schema(tmp_path: Path):
    identity = open_persistence(tmp_path / "db.sqlite3")

    assert identity.approved_factory_only is True
    assert len(identity.schema_fingerprint) == 64


def test_economics_uses_conservative_finalized_net():
    report = reconcile_economics(
        input_lamports=1000,
        expected_output_lamports=1120,
        finalized_payer_delta_lamports=90,
        finalized_token_delta_lamports=40,
        reservation_lamports=10,
        flashloan_borrow_lamports=1000,
        flashloan_repay_lamports=1001,
        simulation_success=True,
        finalized_available=True,
        finalized_slot=10,
        finalized_root=10,
    )

    assert report.economic_result == "net_positive"
    assert report.conservative_net_lamports > 0


def test_economics_fails_closed_without_finality():
    report = reconcile_economics(
        input_lamports=1000,
        expected_output_lamports=2000,
        finalized_payer_delta_lamports=1000,
        finalized_token_delta_lamports=1000,
        reservation_lamports=0,
        flashloan_borrow_lamports=1000,
        flashloan_repay_lamports=1001,
        simulation_success=True,
        finalized_available=False,
        finalized_slot=None,
        finalized_root=None,
    )

    assert report.economic_result == "fail_closed"
    assert report.fail_closed_reason == "finalized_deltas_unavailable"


def test_backup_protocol_and_fault_matrix(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "state.json").write_text('{"ok":true}\n', encoding="utf-8")

    publish_backup(source, tmp_path / "backup", "generation-1")
    validation = validate_backup(tmp_path / "backup", "generation-1")

    assert validation["accepted"] is True
    assert "atomic_rename" in validation["publication_steps"]
    assert "rollback_generation" in validation["fault_matrix"]


def test_readiness_keeps_live_off():
    report = readiness_state(paper_ready=True)

    assert report["state"] == "paper_ready"
    assert report["live_available"] is False
    assert report["signer_available"] is False
    assert report["sender_available"] is False


def test_shadow_soak_fixture_lineage(tmp_path: Path):
    report = run_shadow_soak_fixture(tmp_path, 30)
    validation = validate_shadow_soak(report, require_real=True)

    assert validation["accepted"] is True
    assert set(validation["lineage_counts"]) == {"synthetic", "recorded", "credentialed", "finalized"}
    assert validation["synthetic_counted_as_real_release_evidence"] is False


def test_materialized_evidence_keeps_live_disabled(tmp_path: Path):
    payload = materialize_evidence(tmp_path / "evidence")
    evidence = json.loads(Path(payload["evidence_path"]).read_text(encoding="utf-8"))

    assert payload["live_available"] is False
    assert evidence["live_available"] is False
    assert evidence["signer_loaded"] is False
    assert evidence["sender_loaded"] is False
