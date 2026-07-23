from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from src.pr198_sender_free_qualification_v3 import (
    EvidenceRef,
    MIN_SOAK_HOURS,
    PR198V3BoundaryError,
    PR198V3QualificationEvidence,
    PR198V3SLOEvidence,
    PR198V3SLOLimits,
    REQUIRED_CHAOS_SCENARIOS,
    evaluate_pr198_v3_qualification,
    pr198_v3_status_payload,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def ref(label: str) -> EvidenceRef:
    return EvidenceRef(
        label=label,
        sha256=digest(f"{label}-artifact"),
        relative_path=f"artifacts/pr198/{label}.json",
    )


def good_slo() -> PR198V3SLOEvidence:
    return PR198V3SLOEvidence(
        max_event_loop_lag_ms=50,
        p99_opportunity_age_ms=500,
        max_queue_age_ms=1_000,
        max_shutdown_ms=5_000,
        memory_growth_mb=16,
        fd_growth=2,
        reconciliation_p99_ms=700,
    )


def good_evidence(**overrides: object) -> PR198V3QualificationEvidence:
    run_started_ns = 1_000_000_000
    run_ended_ns = run_started_ns + int((MIN_SOAK_HOURS + 1) * 3_600_000_000_000)
    data: dict[str, object] = {
        "release_id": "release-pr198-v3",
        "source_commit_sha256": digest("source-commit"),
        "wheel_sha256": digest("wheel"),
        "image_sha256": digest("image"),
        "config_sha256": digest("config"),
        "policy_bundle_sha256": digest("policy"),
        "run_started_ns": run_started_ns,
        "run_ended_ns": run_ended_ns,
        "cycles_completed": 2_000,
        "safe_idle_cycles": 12,
        "real_provider_cycles": 500,
        "installed_wheel_exercised": True,
        "container_image_exercised": True,
        "single_sender_free_service": True,
        "uses_pr195_lifecycle": True,
        "uses_pr196_provider_contracts": True,
        "uses_pr197_economic_proof": True,
        "durable_input_before_ack": True,
        "durable_terminal_outcome": True,
        "bounded_queue_policy": True,
        "deterministic_drop_policy": True,
        "deterministic_replay_cases": 25,
        "replay_mismatches": 0,
        "acknowledged_event_loss_count": 0,
        "pending_without_terminal_count": 0,
        "unknown_outcome_count": 0,
        "restart_replay_verified": True,
        "sigterm_drain_verified": True,
        "chaos_scenarios_passed": REQUIRED_CHAOS_SCENARIOS,
        "provider_outage_cycles": 5,
        "db_lock_cycles": 3,
        "clock_jump_cycles": 2,
        "sender_imports_detected": 0,
        "live_capability_enabled": False,
        "signer_capability_enabled": False,
        "shadow_artifact": ref("shadow"),
        "replay_artifact": ref("replay"),
        "chaos_artifact": ref("chaos"),
        "slo": good_slo(),
    }
    data.update(overrides)
    return PR198V3QualificationEvidence(**data)


def test_pr198_v3_happy_path_is_sender_free_and_deterministic() -> None:
    report = evaluate_pr198_v3_qualification(good_evidence())

    assert report.passed is True
    assert report.blockers == ()
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_import_allowed is False
    assert report.report_hash == report.report_hash
    assert all(report.requirement_results.values())


def test_pr198_v3_rejects_safe_idle_or_one_cycle_masquerading_as_readiness() -> None:
    report = evaluate_pr198_v3_qualification(
        good_evidence(
            cycles_completed=1,
            safe_idle_cycles=1,
            real_provider_cycles=0,
        )
    )

    assert report.passed is False
    assert any("continuous_not_safe_idle" in blocker for blocker in report.blockers)


def test_pr198_v3_requires_installed_artifact_and_dependency_chain() -> None:
    report = evaluate_pr198_v3_qualification(
        good_evidence(
            installed_wheel_exercised=False,
            uses_pr196_provider_contracts=False,
        )
    )

    assert report.passed is False
    assert report.requirement_results["installed_artifact_cutover"] is False
    assert report.requirement_results["pr195_196_197_dependency_chain"] is False


def test_pr198_v3_requires_durable_inputs_and_zero_unknown_outcomes() -> None:
    report = evaluate_pr198_v3_qualification(
        good_evidence(
            durable_input_before_ack=False,
            acknowledged_event_loss_count=1,
            unknown_outcome_count=1,
        )
    )

    assert report.passed is False
    assert report.requirement_results["durable_input_and_terminal_outcome"] is False


def test_pr198_v3_requires_exact_replay_without_mismatches() -> None:
    report = evaluate_pr198_v3_qualification(
        good_evidence(deterministic_replay_cases=9, replay_mismatches=1)
    )

    assert report.passed is False
    assert report.requirement_results["deterministic_replay"] is False


def test_pr198_v3_requires_full_chaos_matrix() -> None:
    report = evaluate_pr198_v3_qualification(
        good_evidence(
            chaos_scenarios_passed=("queue_pressure", "provider_outage"),
            clock_jump_cycles=0,
        )
    )

    assert report.passed is False
    assert report.requirement_results["chaos_qualification"] is False


def test_pr198_v3_rejects_slo_breach() -> None:
    bad_slo = replace(good_slo(), max_shutdown_ms=120_000)
    report = evaluate_pr198_v3_qualification(
        good_evidence(slo=bad_slo),
        limits=PR198V3SLOLimits(max_shutdown_ms=30_000),
    )

    assert report.passed is False
    assert report.requirement_results["slo_envelope"] is False


def test_pr198_v3_rejects_sender_live_or_signer_surface() -> None:
    report = evaluate_pr198_v3_qualification(
        good_evidence(
            sender_imports_detected=1,
            live_capability_enabled=True,
            signer_capability_enabled=True,
        )
    )

    assert report.passed is False
    assert report.requirement_results["no_sender_or_live_surface"] is False


def test_pr198_v3_artifact_paths_are_normalized_relative_paths() -> None:
    with pytest.raises(PR198V3BoundaryError):
        EvidenceRef(label="shadow", sha256=digest("shadow"), relative_path="../shadow.json")


def test_pr198_v3_status_payload_is_fail_closed() -> None:
    payload = pr198_v3_status_payload()

    assert payload["roadmap_pr"] == "PR-198"
    assert payload["v3_scope"] == "continuous_sender_free_paper_shadow_replay_chaos"
    assert payload["live_execution_allowed"] is False
    assert payload["signer_allowed"] is False
    assert payload["sender_import_allowed"] is False
    assert set(REQUIRED_CHAOS_SCENARIOS).issubset(payload["required_chaos_scenarios"])
