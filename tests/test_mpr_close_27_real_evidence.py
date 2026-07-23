from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.release_gate.mpr27_real_evidence import (
    REQUIRED_FAULT_CASES,
    REQUIRED_RELEASE_ARTIFACTS,
    REQUIRED_SECRET_DRILLS,
    REQUIRED_SLO_METRICS,
    build_release_evidence_report,
    verify_report,
    write_report_atomic,
)


def _write(path: Path, value: bytes | dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        path.write_bytes(value)
    else:
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _valid_artifacts(root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for artifact_id in sorted(REQUIRED_RELEASE_ARTIFACTS):
        path = root / f"{artifact_id}.bin"
        _write(path, f"materialized {artifact_id} evidence".encode("utf-8"))
        mapping[artifact_id] = path.name

    _write(
        root / "shadow_campaign_report_digest.json",
        {
            "campaign_days": 3,
            "keypair_loaded": False,
            "provider_data_lineage": "provider",
            "sender_enabled": False,
            "synthetic": False,
        },
    )
    mapping["shadow_campaign_report_digest"] = "shadow_campaign_report_digest.json"

    _write(
        root / "fault_injection_report_digest.json",
        {"cases": [{"id": case, "passed": True} for case in REQUIRED_FAULT_CASES]},
    )
    mapping["fault_injection_report_digest"] = "fault_injection_report_digest.json"

    _write(
        root / "backup_restore_report_digest.json",
        {
            "duplicate_decisions_after_restore": 0,
            "event_chain_verified": True,
            "restored_into_clean_runtime": True,
        },
    )
    mapping["backup_restore_report_digest"] = "backup_restore_report_digest.json"

    _write(
        root / "slo_baseline_report_digest.json",
        {"metrics": {metric: 1 for metric in REQUIRED_SLO_METRICS}},
    )
    mapping["slo_baseline_report_digest"] = "slo_baseline_report_digest.json"

    _write(
        root / "secret_incident_drill_report_digest.json",
        {
            "cases": [{"id": case, "passed": True} for case in REQUIRED_SECRET_DRILLS],
            "raw_secret_logged": False,
        },
    )
    mapping["secret_incident_drill_report_digest"] = (
        "secret_incident_drill_report_digest.json"
    )
    return mapping


def test_complete_materialized_evidence_is_review_ready(tmp_path: Path) -> None:
    artifact_paths = _valid_artifacts(tmp_path)

    report = build_release_evidence_report(
        root=tmp_path,
        artifact_paths=artifact_paths,
        generated_at_unix_ns=123,
    )

    assert report.accepted is True
    assert report.live_trading_enabled is False
    assert report.promotion_state == "review_ready_release_evidence"
    assert report.missing_artifacts == ()
    assert {artifact.id for artifact in report.artifacts} >= REQUIRED_RELEASE_ARTIFACTS


def test_missing_required_artifacts_keep_promotion_blocked(tmp_path: Path) -> None:
    report = build_release_evidence_report(
        root=tmp_path,
        artifact_paths={},
        generated_at_unix_ns=123,
    )

    assert report.accepted is False
    assert report.promotion_state == "blocked_pending_evidence"
    assert set(report.missing_artifacts) == REQUIRED_RELEASE_ARTIFACTS
    assert "MISSING_RUNTIME_WHEEL_DIGEST" in report.blockers


def test_placeholder_artifact_is_rejected(tmp_path: Path) -> None:
    artifact_paths = _valid_artifacts(tmp_path)
    _write(tmp_path / "runtime_wheel_digest.bin", b"placeholder fake evidence")

    report = build_release_evidence_report(
        root=tmp_path,
        artifact_paths=artifact_paths,
        generated_at_unix_ns=123,
    )

    assert report.accepted is False
    assert (
        "runtime_wheel_digest:PLACEHOLDER_EVIDENCE_REJECTED" in report.blockers
    )


def test_one_day_or_synthetic_shadow_campaign_is_rejected(tmp_path: Path) -> None:
    artifact_paths = _valid_artifacts(tmp_path)
    _write(
        tmp_path / "shadow_campaign_report_digest.json",
        {
            "campaign_days": 1,
            "keypair_loaded": False,
            "provider_data_lineage": "recorded",
            "sender_enabled": False,
            "synthetic": True,
        },
    )

    report = build_release_evidence_report(
        root=tmp_path,
        artifact_paths=artifact_paths,
        generated_at_unix_ns=123,
    )

    assert report.accepted is False
    assert "shadow_campaign_report_digest:SHADOW_CAMPAIGN_SYNTHETIC" in report.blockers
    assert "shadow_campaign_report_digest:SHADOW_CAMPAIGN_TOO_SHORT" in report.blockers
    assert (
        "shadow_campaign_report_digest:SHADOW_CAMPAIGN_NOT_PROVIDER_LINEAGE"
        in report.blockers
    )


def test_backup_restore_must_prove_no_duplicate_decisions(tmp_path: Path) -> None:
    artifact_paths = _valid_artifacts(tmp_path)
    _write(
        tmp_path / "backup_restore_report_digest.json",
        {
            "duplicate_decisions_after_restore": 1,
            "event_chain_verified": True,
            "restored_into_clean_runtime": True,
        },
    )

    report = build_release_evidence_report(
        root=tmp_path,
        artifact_paths=artifact_paths,
        generated_at_unix_ns=123,
    )

    assert report.accepted is False
    assert (
        "backup_restore_report_digest:BACKUP_RESTORE_DUPLICATE_DECISIONS"
        in report.blockers
    )


def test_report_write_and_verify_recomputes_materialized_hashes(tmp_path: Path) -> None:
    artifact_paths = _valid_artifacts(tmp_path)
    report = build_release_evidence_report(
        root=tmp_path,
        artifact_paths=artifact_paths,
        generated_at_unix_ns=123,
    )
    output = write_report_atomic(tmp_path / "report.json", report)

    verified = verify_report(root=tmp_path, report_path=output)

    assert verified.accepted is True

    _write(tmp_path / "runtime_image_digest.bin", b"changed materialized evidence")
    changed = verify_report(root=tmp_path, report_path=output)
    assert changed.accepted is False
    assert "REPORT_DIGEST_DRIFT" in changed.blockers


def test_artifact_paths_must_stay_inside_release_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-mpr27.txt"
    _write(outside, b"not approved")

    report = build_release_evidence_report(
        root=tmp_path,
        artifact_paths={"runtime_wheel_digest": "../outside-mpr27.txt"},
        generated_at_unix_ns=123,
    )

    assert report.accepted is False
    assert "ARTIFACT_INVALID_PATH_runtime_wheel_digest" in report.blockers
