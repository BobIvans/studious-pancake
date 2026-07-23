from __future__ import annotations

import math
import pytest

from src.mpr10_lifecycle_queue_observability import (
    MPR10EvidenceError,
    MPR10_SCHEMA_VERSION,
    evaluate_mpr10_lifecycle_gate,
    live_capability_allowed,
    sender_capability_allowed,
    signer_capability_allowed,
)


def _digest(seed: str) -> str:
    # Deterministic non-placeholder 64-char lowercase test digest.
    return (seed.encode().hex() * 8)[:64].ljust(64, "1")


def complete_evidence() -> dict[str, object]:
    return {
        "schema_version": MPR10_SCHEMA_VERSION,
        "artifact_hashes": {
            "queue_lifecycle_model_hash": _digest("queue"),
            "lifecycle_authority_contract_hash": _digest("authority"),
            "shutdown_policy_hash": _digest("shutdown"),
            "tracker_retention_policy_hash": _digest("tracker"),
            "observability_window_policy_hash": _digest("observability"),
            "numeric_config_policy_hash": _digest("numeric"),
            "stress_suite_hash": _digest("stress"),
        },
        "runtime_capabilities": {
            "live": False,
            "signer": False,
            "sender": False,
        },
        "queue_lifecycle": {
            "single_lifecycle_authority": True,
            "expiry_records_terminal_outcome": True,
            "expiry_releases_pending_identity": True,
            "public_expire_lock_protected": True,
            "consumer_expiry_claims_or_terminalizes": True,
            "sink_result_matches_lifecycle_state": True,
            "readmission_policy_explicit": True,
            "concurrent_stress_preserves_heap_ids_lifecycle": True,
            "crash_replay_preserves_terminal_expiry": True,
        },
        "shutdown": {
            "declared_grace_ms": 30_000,
            "admission_stops_before_drain": True,
            "no_unbounded_second_drain": True,
            "hung_handler_finishes_within_grace": True,
            "remaining_work_marked_resumable_or_aborted": True,
            "cancellation_safe_terminalization": True,
            "structured_concurrency_used": True,
        },
        "bounded_state": {
            "terminal_tracker_bounded": True,
            "terminal_tracker_max_entries": 100_000,
            "terminal_tracker_retention_ms": 86_400_000,
            "durable_dedupe_handoff": True,
            "eviction_metrics_exported": True,
            "multi_day_memory_bound_verified": True,
            "observability_query_windowed": True,
            "metrics_query_row_limit": 50_000,
            "metrics_query_deadline_ms": 5_000,
            "streaming_quantiles_or_sql_histograms": True,
            "truncation_metadata_exported": True,
        },
        "numeric_timing": {
            "max_delay_seconds": 60.0,
            "rejected_values": [
                "nan",
                "positive_infinity",
                "negative_infinity",
                "excessive_delay",
                "negative_delay",
            ],
            "all_duration_inputs_finite": True,
            "upper_bounds_enforced": True,
            "config_errors_typed_before_start": True,
        },
    }


def reason_codes(report):
    return set(report.reason_codes)


def test_complete_evidence_is_ready_and_sender_free():
    report = evaluate_mpr10_lifecycle_gate(complete_evidence())
    assert report.ready is True
    assert report.reason_codes == ()
    assert report.live_capability_allowed is False
    assert report.signer_capability_allowed is False
    assert report.sender_capability_allowed is False
    assert live_capability_allowed() is False
    assert signer_capability_allowed() is False
    assert sender_capability_allowed() is False


def test_expired_opportunity_cannot_leave_pending():
    evidence = complete_evidence()
    evidence["queue_lifecycle"]["expiry_releases_pending_identity"] = False
    report = evaluate_mpr10_lifecycle_gate(evidence)
    assert report.ready is False
    assert "EXPIRY_LEAVES_PENDING" in reason_codes(report)


def test_expiry_must_be_lock_protected():
    evidence = complete_evidence()
    evidence["queue_lifecycle"]["public_expire_lock_protected"] = False
    report = evaluate_mpr10_lifecycle_gate(evidence)
    assert "EXPIRE_NOT_LOCK_PROTECTED" in reason_codes(report)


def test_consumer_expiry_must_match_lifecycle_terminal_state():
    evidence = complete_evidence()
    evidence["queue_lifecycle"]["consumer_expiry_claims_or_terminalizes"] = False
    evidence["queue_lifecycle"]["sink_result_matches_lifecycle_state"] = False
    report = evaluate_mpr10_lifecycle_gate(evidence)
    assert "CONSUMER_EXPIRY_NOT_LIFECYCLE_BOUND" in reason_codes(report)
    assert "SINK_LIFECYCLE_MISMATCH" in reason_codes(report)


def test_shutdown_rejects_unbounded_second_drain():
    evidence = complete_evidence()
    evidence["shutdown"]["no_unbounded_second_drain"] = False
    report = evaluate_mpr10_lifecycle_gate(evidence)
    assert "UNBOUNDED_SECOND_DRAIN" in reason_codes(report)


def test_hung_handler_must_finish_within_grace():
    evidence = complete_evidence()
    evidence["shutdown"]["hung_handler_finishes_within_grace"] = False
    report = evaluate_mpr10_lifecycle_gate(evidence)
    assert "HUNG_HANDLER_BLOCKS_SHUTDOWN" in reason_codes(report)


def test_terminal_tracker_must_be_bounded():
    evidence = complete_evidence()
    evidence["bounded_state"]["terminal_tracker_bounded"] = False
    evidence["bounded_state"]["terminal_tracker_max_entries"] = 0
    report = evaluate_mpr10_lifecycle_gate(evidence)
    assert "TERMINAL_TRACKER_UNBOUNDED" in reason_codes(report)
    assert "TERMINAL_TRACKER_CAP_INVALID" in reason_codes(report)


def test_observability_cannot_sort_full_history():
    evidence = complete_evidence()
    evidence["bounded_state"]["observability_query_windowed"] = False
    evidence["bounded_state"]["streaming_quantiles_or_sql_histograms"] = False
    report = evaluate_mpr10_lifecycle_gate(evidence)
    assert "OBSERVABILITY_QUERY_UNBOUNDED" in reason_codes(report)
    assert "OBSERVABILITY_SORTS_FULL_HISTORY" in reason_codes(report)


def test_numeric_timing_requires_nan_inf_rejection_coverage():
    evidence = complete_evidence()
    evidence["numeric_timing"]["rejected_values"] = ["nan"]
    report = evaluate_mpr10_lifecycle_gate(evidence)
    assert "NUMERIC_REJECTION_COVERAGE_MISSING" in reason_codes(report)


def test_numeric_max_delay_must_be_finite():
    evidence = complete_evidence()
    evidence["numeric_timing"]["max_delay_seconds"] = math.nan
    report = evaluate_mpr10_lifecycle_gate(evidence)
    assert "NUMERIC_MAX_DELAY_INVALID" in reason_codes(report)


def test_runtime_capabilities_cannot_be_enabled():
    evidence = complete_evidence()
    evidence["runtime_capabilities"]["live"] = True
    evidence["runtime_capabilities"]["signer"] = True
    evidence["runtime_capabilities"]["sender"] = True
    report = evaluate_mpr10_lifecycle_gate(evidence)
    assert {
        "LIVE_CAPABILITY_NOT_ALLOWED",
        "SIGNER_CAPABILITY_NOT_ALLOWED",
        "SENDER_CAPABILITY_NOT_ALLOWED",
    }.issubset(reason_codes(report))


def test_placeholder_digest_is_rejected():
    evidence = complete_evidence()
    evidence["artifact_hashes"]["queue_lifecycle_model_hash"] = "0" * 64
    with pytest.raises(MPR10EvidenceError):
        evaluate_mpr10_lifecycle_gate(evidence)
