from __future__ import annotations

from src.paper_qualification_pr04 import (
    MIN_SOAK_SECONDS,
    REQUIRED_RELEASE_ARTIFACTS,
    evaluate_paper_qualification,
)

_HASH = "a" * 64


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "new-mega-pr-04.paper-qualification.v1",
        "sender_free_release": True,
        "live_enabled": False,
        "offline_build": True,
        "no_network_release_install": True,
        "actions_pinned_to_full_sha": True,
        "images_pinned_by_digest": True,
        "clean_wheel_tests_passed": True,
        "container_sandbox_enforced": True,
        "python_optimized_tests_passed": True,
        "data_lineage_quarantined": True,
        "solders_in_test_toolchain": True,
        "release_artifacts": [
            {
                "id": artifact_id,
                "sha256": _HASH,
                "evidence_kind": "real-provider-paper"
                if artifact_id == "paper_soak_report"
                else "materialized-release",
                "required_before_paper_ready": True,
            }
            for artifact_id in REQUIRED_RELEASE_ARTIFACTS
        ],
    }


def _soak() -> dict[str, object]:
    return {
        "schema_version": "new-mega-pr-04.shadow-soak-report.v1",
        "duration_seconds": MIN_SOAK_SECONDS,
        "evidence_kind": "real-provider-paper",
        "live_enabled": False,
        "sender_free": True,
        "provider_evidence_present": True,
        "data_lineage_quarantined": True,
        "unresolved_p0_incidents": 0,
        "duplicate_or_replayed_cycles": 0,
        "unique_cycle_count": 3,
        "unique_cycle_ids": ["cycle-1", "cycle-2", "cycle-3"],
        "gross_pnl_paper": 0,
        "net_pnl_paper": 0,
        "fee_rent_repayment_impact": 0,
    }


def test_new_mega_pr04_accepts_real_72h_sender_free_paper_evidence() -> None:
    report = evaluate_paper_qualification(_manifest(), _soak())

    assert report.accepted is True
    assert report.paper_ready is True
    assert report.live_ready is False
    assert report.blockers == ()
    assert report.evidence_digest is not None


def test_new_mega_pr04_rejects_synthetic_or_placeholder_release_artifacts() -> None:
    manifest = _manifest()
    artifacts = manifest["release_artifacts"]
    assert isinstance(artifacts, list)
    artifacts[0]["evidence_kind"] = "placeholder"

    report = evaluate_paper_qualification(manifest, _soak())

    assert report.accepted is False
    assert any(blocker.startswith("ARTIFACT_SYNTHETIC_OR_PLACEHOLDER") for blocker in report.blockers)
    assert report.paper_ready is False
    assert report.live_ready is False


def test_new_mega_pr04_rejects_short_or_recorded_soak() -> None:
    soak = _soak()
    soak["duration_seconds"] = MIN_SOAK_SECONDS - 1
    soak["evidence_kind"] = "recorded"

    report = evaluate_paper_qualification(_manifest(), soak)

    assert report.accepted is False
    assert "SOAK_DURATION_LT_72H" in report.blockers
    assert "SOAK_NOT_REAL_PROVIDER_PAPER" in report.blockers


def test_new_mega_pr04_rejects_duplicate_or_replayed_cycles() -> None:
    soak = _soak()
    soak["duplicate_or_replayed_cycles"] = 1
    soak["unique_cycle_ids"] = ["cycle-1", "cycle-1"]

    report = evaluate_paper_qualification(_manifest(), soak)

    assert report.accepted is False
    assert "REPLAYED_CYCLES_PRESENT" in report.blockers
    assert "DUPLICATE_CYCLE_IDS" in report.blockers


def test_new_mega_pr04_live_must_remain_disabled() -> None:
    manifest = _manifest()
    manifest["live_enabled"] = True
    soak = _soak()
    soak["live_enabled"] = True

    report = evaluate_paper_qualification(manifest, soak)

    assert report.accepted is False
    assert "LIVE_MUST_REMAIN_DISABLED" in report.blockers
    assert "SOAK_LIVE_MUST_BE_FALSE" in report.blockers
    assert report.live_ready is False
