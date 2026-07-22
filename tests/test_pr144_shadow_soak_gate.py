from __future__ import annotations

from src.shadow_soak_pr144 import (
    REQUIRED_SHADOW_STREAMS,
    ShadowSoakEvidence,
    ShadowSoakPolicy,
    ShadowSoakWindow,
    SoakDecision,
    SoakReason,
    evaluate_shadow_soak,
    release_gate_payload,
)


def _hash(label: str) -> str:
    return (label.encode("utf-8").hex() * 8)[:64]


def _window(hours: int = 72) -> ShadowSoakWindow:
    return ShadowSoakWindow(1_000, 1_000 + hours * 3_600_000)


def _evidence(**overrides: object) -> ShadowSoakEvidence:
    values: dict[str, object] = {
        "run_id": "shadow-soak-001",
        "window": _window(),
        "streams": REQUIRED_SHADOW_STREAMS,
        "evidence_hash": _hash("shadow-soak-001"),
        "reviewed_by_human": True,
        "total_events": 500,
        "reconciled_terminal_events": 500,
    }
    values.update(overrides)
    return ShadowSoakEvidence(**values)  # type: ignore[arg-type]


def _has_reason(report, reason: SoakReason) -> bool:
    return any(failure.reason is reason for failure in report.failures)


def test_pr144_review_ready_after_72h_with_required_streams() -> None:
    report = evaluate_shadow_soak(_evidence())

    assert report.decision is SoakDecision.REVIEW_READY
    assert report.review_ready is True
    assert report.live_canary_allowed is False
    assert report.failures == ()


def test_pr144_short_soak_is_blocked() -> None:
    report = evaluate_shadow_soak(_evidence(window=_window(71)))

    assert report.review_ready is False
    assert _has_reason(report, SoakReason.TOO_SHORT)


def test_pr144_missing_cpi_stream_is_blocked() -> None:
    streams = tuple(
        stream for stream in REQUIRED_SHADOW_STREAMS if stream != "cpi_call_graph"
    )

    report = evaluate_shadow_soak(_evidence(streams=streams))

    assert report.review_ready is False
    assert any(
        failure.reason is SoakReason.MISSING_STREAM
        and failure.stream == "cpi_call_graph"
        for failure in report.failures
    )


def test_pr144_unreconciled_terminal_event_is_blocked() -> None:
    report = evaluate_shadow_soak(_evidence(reconciled_terminal_events=499))

    assert report.review_ready is False
    assert _has_reason(report, SoakReason.UNRECONCILED_TERMINAL)


def test_pr144_sender_or_submission_side_effect_is_blocked() -> None:
    report = evaluate_shadow_soak(
        _evidence(sender_invocations=1, submission_attempts=1)
    )

    assert report.review_ready is False
    assert _has_reason(report, SoakReason.SENDER_TOUCHED)
    assert _has_reason(report, SoakReason.SUBMISSION_ATTEMPTED)


def test_pr144_transaction_signature_is_never_shadow_soak_evidence() -> None:
    report = evaluate_shadow_soak(_evidence(observed_transaction_signatures=1))

    assert report.review_ready is False
    assert _has_reason(report, SoakReason.SIGNATURE_OBSERVED)


def test_pr144_live_enabled_flag_blocks_soak() -> None:
    report = evaluate_shadow_soak(_evidence(live_enabled=True))

    assert report.review_ready is False
    assert _has_reason(report, SoakReason.LIVE_ENABLED)


def test_pr144_placeholder_hash_is_blocked() -> None:
    report = evaluate_shadow_soak(_evidence(evidence_hash="0" * 64))

    assert report.review_ready is False
    assert _has_reason(report, SoakReason.PLACEHOLDER_HASH)


def test_pr144_gap_or_duplicate_identity_blocks_soak() -> None:
    report = evaluate_shadow_soak(
        _evidence(gap_count=1, duplicate_identity_count=1)
    )

    assert report.review_ready is False
    assert _has_reason(report, SoakReason.GAP_DETECTED)
    assert _has_reason(report, SoakReason.DUPLICATE_IDENTITY)


def test_pr144_error_budget_is_enforced() -> None:
    report = evaluate_shadow_soak(
        _evidence(total_events=100, reconciled_terminal_events=100, error_count=2),
        ShadowSoakPolicy(max_error_rate_bps=100),
    )

    assert report.review_ready is False
    assert _has_reason(report, SoakReason.ERROR_BUDGET_EXCEEDED)


def test_pr144_release_payload_never_allows_live_canary() -> None:
    report = evaluate_shadow_soak(_evidence())
    payload = release_gate_payload(report)

    assert payload["shadow_soak_review_ready"] is True
    assert payload["live_canary_allowed"] is False
    assert payload["decision"] == "review_ready"


def test_pr144_report_hash_is_deterministic_with_stream_order() -> None:
    first = evaluate_shadow_soak(_evidence())
    second = evaluate_shadow_soak(
        _evidence(streams=tuple(reversed(REQUIRED_SHADOW_STREAMS)))
    )

    assert first.report_hash == second.report_hash
