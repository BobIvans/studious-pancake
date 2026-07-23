from __future__ import annotations

from dataclasses import replace
import json

import pytest

from src.mpr05_installed_paper_shadow_qualification import (
    MPR05Decision,
    MPR05EvidenceError,
    MIN_SOAK_HOURS,
    REQUIRED_FAULT_INJECTIONS,
    SLOEnvelope,
    complete_sender_free_evidence,
    evaluate_mpr05_qualification,
    report_json,
)


def test_mpr05_complete_sender_free_evidence_is_ready() -> None:
    evidence = complete_sender_free_evidence()

    report = evaluate_mpr05_qualification(evidence)

    assert report.ready
    assert report.decision is MPR05Decision.READY_SENDER_FREE
    assert report.reason_codes == ()
    assert report.soak_hours == MIN_SOAK_HOURS
    assert report.live_execution_allowed is False
    assert report.signer_or_sender_reachable is False


def test_mpr05_rejects_parallel_runner_even_when_metrics_are_green() -> None:
    evidence = replace(complete_sender_free_evidence(), parallel_runner_used=True)

    report = evaluate_mpr05_qualification(evidence)

    assert not report.ready
    assert "INSTALLED_PRODUCTION_COMPOSITION:parallel_runner_used" in report.reason_codes


def test_mpr05_requires_72h_installed_soak() -> None:
    evidence = replace(
        complete_sender_free_evidence(),
        soak_ended_ns=(MIN_SOAK_HOURS - 1) * 3_600_000_000_000,
    )

    report = evaluate_mpr05_qualification(evidence)

    assert not report.ready
    assert "CONTINUOUS_72H_SOAK:soak_duration_below_72h" in report.reason_codes


def test_mpr05_every_admitted_candidate_must_terminalize_within_slo() -> None:
    base = complete_sender_free_evidence()
    evidence = replace(
        base,
        metrics=replace(
            base.metrics,
            durable_terminal_candidates=base.metrics.admitted_candidates - 1,
            terminal_within_slo_candidates=base.metrics.admitted_candidates - 2,
        ),
    )

    report = evaluate_mpr05_qualification(evidence)

    assert not report.ready
    assert (
        "DURABLE_TERMINAL_OUTCOME_WITHIN_SLO:not_every_candidate_terminal"
        in report.reason_codes
    )
    assert (
        "DURABLE_TERMINAL_OUTCOME_WITHIN_SLO:not_every_candidate_within_slo"
        in report.reason_codes
    )


def test_mpr05_management_listener_cannot_mask_dead_or_stale_worker() -> None:
    base = complete_sender_free_evidence()
    evidence = replace(
        base,
        workload_workers_alive=False,
        management_listener_alive=True,
        metrics=replace(base.metrics, stale_worker_count=1),
    )

    report = evaluate_mpr05_qualification(evidence)

    assert not report.ready
    assert "DURABLE_TERMINAL_OUTCOME_WITHIN_SLO:workload_workers_dead" in report.reason_codes
    assert "DURABLE_TERMINAL_OUTCOME_WITHIN_SLO:stale_workers_present" in report.reason_codes
    assert (
        "DURABLE_TERMINAL_OUTCOME_WITHIN_SLO:management_alive_but_workload_unready"
        in report.reason_codes
    )


def test_mpr05_blocks_balance_loss_evidence_loss_and_leaked_claims() -> None:
    base = complete_sender_free_evidence()
    evidence = replace(
        base,
        metrics=replace(
            base.metrics,
            unexplained_balance_loss_count=1,
            evidence_loss_count=1,
            leaked_reservation_count=1,
            leaked_outbox_claim_count=1,
        ),
    )

    report = evaluate_mpr05_qualification(evidence)

    assert not report.ready
    assert "ZERO_LOSS_AND_NO_LEAKED_CLAIMS:unexplained_balance_loss_count" in report.reason_codes
    assert "ZERO_LOSS_AND_NO_LEAKED_CLAIMS:evidence_loss_count" in report.reason_codes
    assert "ZERO_LOSS_AND_NO_LEAKED_CLAIMS:leaked_reservation_count" in report.reason_codes
    assert "ZERO_LOSS_AND_NO_LEAKED_CLAIMS:leaked_outbox_claim_count" in report.reason_codes


def test_mpr05_requires_all_fault_injection_scenarios() -> None:
    evidence = replace(
        complete_sender_free_evidence(),
        fault_injections=tuple(REQUIRED_FAULT_INJECTIONS[:-1]),
    )

    report = evaluate_mpr05_qualification(evidence)

    assert not report.ready
    assert "FAULT_INJECTION_COVERAGE:missing_fault_forced_restart" in report.reason_codes


def test_mpr05_requires_deterministic_replay_hash_and_no_mismatch() -> None:
    base = complete_sender_free_evidence()
    evidence = replace(
        base,
        metrics=replace(base.metrics, replay_case_count=9, replay_mismatch_count=1),
    )

    report = evaluate_mpr05_qualification(evidence)

    assert not report.ready
    assert "DETERMINISTIC_CAPTURE_REPLAY:too_few_replay_cases" in report.reason_codes
    assert "DETERMINISTIC_CAPTURE_REPLAY:replay_mismatch" in report.reason_codes


def test_mpr05_signed_immutable_artifact_is_release_blocking() -> None:
    evidence = replace(
        complete_sender_free_evidence(),
        artifact_immutable=False,
        offline_reverification_passed=False,
        signature_verified=False,
    )

    report = evaluate_mpr05_qualification(evidence)

    assert not report.ready
    assert (
        "SIGNED_IMMUTABLE_OFFLINE_REVERIFIABLE_SOAK_ARTIFACT:artifact_not_immutable"
        in report.reason_codes
    )
    assert (
        "SIGNED_IMMUTABLE_OFFLINE_REVERIFIABLE_SOAK_ARTIFACT:offline_reverification_failed"
        in report.reason_codes
    )
    assert (
        "SIGNED_IMMUTABLE_OFFLINE_REVERIFIABLE_SOAK_ARTIFACT:signature_not_verified"
        in report.reason_codes
    )


def test_mpr05_live_signer_or_sender_surface_is_forbidden() -> None:
    evidence = replace(
        complete_sender_free_evidence(),
        live_execution_allowed=True,
        signer_or_sender_reachable=True,
    )

    report = evaluate_mpr05_qualification(evidence)

    assert not report.ready
    assert "NO_LIVE_SIGNER_OR_SENDER_SURFACE:live_execution_allowed" in report.reason_codes
    assert "NO_LIVE_SIGNER_OR_SENDER_SURFACE:signer_or_sender_reachable" in report.reason_codes


def test_mpr05_slo_thresholds_are_enforced() -> None:
    base = complete_sender_free_evidence()
    evidence = replace(
        base,
        metrics=replace(
            base.metrics,
            max_queue_age_ms=101,
            max_event_loop_lag_ms=11,
            max_worker_heartbeat_age_ms=101,
            max_shutdown_drain_ms=1001,
        ),
    )

    report = evaluate_mpr05_qualification(
        evidence,
        slo=SLOEnvelope(
            max_queue_age_ms=100,
            max_event_loop_lag_ms=10,
            max_worker_heartbeat_age_ms=100,
            max_shutdown_drain_ms=1000,
        ),
    )

    assert "DURABLE_TERMINAL_OUTCOME_WITHIN_SLO:queue_age_slo_exceeded" in report.reason_codes
    assert "DURABLE_TERMINAL_OUTCOME_WITHIN_SLO:event_loop_lag_slo_exceeded" in report.reason_codes
    assert "DURABLE_TERMINAL_OUTCOME_WITHIN_SLO:worker_heartbeat_slo_exceeded" in report.reason_codes
    assert "DURABLE_TERMINAL_OUTCOME_WITHIN_SLO:shutdown_drain_slo_exceeded" in report.reason_codes


def test_mpr05_evidence_validation_is_strict() -> None:
    with pytest.raises(MPR05EvidenceError, match="sha256"):
        replace(complete_sender_free_evidence(), wheel_sha256="not-a-hash")

    base = complete_sender_free_evidence()
    with pytest.raises(MPR05EvidenceError, match="dependencies"):
        replace(base, dependencies=base.dependencies[:-1])

    with pytest.raises(MPR05EvidenceError, match="unique"):
        replace(base, fault_injections=("provider_outage", "provider_outage"))


def test_mpr05_report_json_is_stable_and_sender_free() -> None:
    payload = json.loads(report_json(complete_sender_free_evidence()))

    assert payload["schema_version"] == "mpr05.installed-paper-shadow-qualification.v1"
    assert payload["decision"] == "ready_sender_free"
    assert payload["ready"] is True
    assert payload["live_execution_allowed"] is False
    assert payload["signer_or_sender_reachable"] is False
    assert len(payload["evidence_hash"]) == 64
