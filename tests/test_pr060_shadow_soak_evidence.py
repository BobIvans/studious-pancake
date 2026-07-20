from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.release_gate.models import EvidenceKind, PinKind
from src.shadow_soak import (
    MINIMUM_SOAK_SECONDS,
    ReplayEvidence,
    ShadowSoakError,
    ShadowSoakEvidence,
    ShadowSoakMetrics,
    SoakArtifactKind,
    SoakArtifactReference,
    SoakEnvironment,
    evaluate_shadow_soak,
    sha256_payload,
    to_pr047_shadow_soak_reference,
)


def _sha(label: str) -> str:
    return sha256_payload({"label": label})


def _metrics(**overrides: int) -> ShadowSoakMetrics:
    values = {
        "candidates_seen": 24,
        "candidates_simulated": 18,
        "candidates_rejected": 6,
        "paper_outcomes_written": 18,
        "outcomes_reconciled": 18,
        "reconciliation_mismatches": 0,
        "message_hash_mismatches": 0,
        "repayment_mismatches": 0,
        "ambiguous_outcomes": 0,
        "quota_exhaustions": 0,
        "provider_5xx_errors": 0,
        "rpc_errors": 0,
        "stale_data_rejections": 3,
        "stale_data_accepted": 0,
        "p50_latency_ms": 42,
        "p95_latency_ms": 120,
        "max_latency_ms": 180,
        "net_pnl_lamports": 250_000,
    }
    values.update(overrides)
    return ShadowSoakMetrics(**values)


def _replay(**overrides: int | str) -> ReplayEvidence:
    values: dict[str, int | str] = {
        "corpus_events": 128,
        "replayed_events": 128,
        "deterministic_passed_events": 128,
        "deterministic_failed_events": 0,
        "corpus_sha256": _sha("corpus"),
    }
    values.update(overrides)
    return ReplayEvidence(**values)  # type: ignore[arg-type]


def _artifacts() -> tuple[SoakArtifactReference, ...]:
    return (
        SoakArtifactReference(
            path="artifacts/pr060/raw-events.jsonl",
            sha256=_sha("raw-events"),
            kind=SoakArtifactKind.RAW_EVENTS,
            event_count=128,
        ),
        SoakArtifactReference(
            path="artifacts/pr060/replay-corpus.jsonl",
            sha256=_sha("replay-corpus"),
            kind=SoakArtifactKind.REPLAY_CORPUS,
            event_count=128,
        ),
        SoakArtifactReference(
            path="artifacts/pr060/metrics.json",
            sha256=_sha("metrics"),
            kind=SoakArtifactKind.METRICS_REPORT,
        ),
        SoakArtifactReference(
            path="artifacts/pr060/operator-review.md",
            sha256=_sha("operator-review"),
            kind=SoakArtifactKind.OPERATOR_REVIEW,
        ),
    )


def _evidence(**overrides: object) -> ShadowSoakEvidence:
    start = datetime(2026, 7, 21, 0, 0, tzinfo=timezone.utc)
    values = {
        "run_id": "shadow-soak-20260721-a",
        "code_commit": "a" * 40,
        "started_at": start,
        "ended_at": start + timedelta(seconds=MINIMUM_SOAK_SECONDS),
        "environment": SoakEnvironment.SHADOW,
        "vertical_stages": (
            "discovery",
            "capital",
            "planner",
            "compiler",
            "simulation",
            "reconciliation",
            "lifecycle",
        ),
        "metrics": _metrics(),
        "replay": _replay(),
        "artifacts": _artifacts(),
        "operator": "ops-shadow",
        "human_reviewed": True,
        "reviewer": "risk-owner",
        "reviewed_at": start
        + timedelta(seconds=MINIMUM_SOAK_SECONDS, minutes=5),
        "signed_by": "release-manager",
        "signature_reference": "artifacts/pr060/evidence.sig",
        "notes": "synthetic unit-test evidence object; not a real soak run",
    }
    values.update(overrides)
    return ShadowSoakEvidence(**values)  # type: ignore[arg-type]


def test_72_hour_reviewed_signed_soak_promotes_evidence_only() -> None:
    evidence = _evidence()

    result = evaluate_shadow_soak(evidence)

    assert result.promotion_ready is True
    assert result.state == "shadow-soak-passed"
    assert result.duration_seconds == MINIMUM_SOAK_SECONDS
    assert result.blockers == ()
    assert result.metrics_summary["replay_pass_rate_bps"] == 10_000
    assert evidence.evidence_sha256 == evidence.evidence_sha256


def test_short_run_fails_closed_even_with_clean_metrics() -> None:
    start = datetime(2026, 7, 21, 0, 0, tzinfo=timezone.utc)
    evidence = _evidence(
        started_at=start,
        ended_at=start + timedelta(hours=24),
        reviewed_at=start + timedelta(hours=24, minutes=5),
    )

    result = evaluate_shadow_soak(evidence)

    assert result.promotion_ready is False
    assert "SHADOW_SOAK_DURATION_BELOW_THRESHOLD" in result.blockers


def test_replay_failures_and_empty_corpus_block_promotion() -> None:
    failed_replay = _evidence(
        replay=_replay(
            deterministic_passed_events=127,
            deterministic_failed_events=1,
        )
    )
    empty_replay = _evidence(
        replay=_replay(
            corpus_events=0,
            replayed_events=0,
            deterministic_passed_events=0,
        )
    )

    failed_result = evaluate_shadow_soak(failed_replay)
    empty_result = evaluate_shadow_soak(empty_replay)

    assert failed_result.promotion_ready is False
    assert "DETERMINISTIC_REPLAY_FAILURES_PRESENT" in failed_result.blockers
    assert "DETERMINISTIC_REPLAY_PASS_RATE_TOO_LOW" in failed_result.blockers
    assert empty_result.promotion_ready is False
    assert "REPLAY_CORPUS_EMPTY" in empty_result.blockers


def test_reconciliation_message_and_repayment_mismatches_block() -> None:
    evidence = _evidence(
        metrics=_metrics(
            reconciliation_mismatches=1,
            message_hash_mismatches=1,
            repayment_mismatches=1,
            ambiguous_outcomes=1,
        )
    )

    result = evaluate_shadow_soak(evidence)

    assert result.promotion_ready is False
    assert "RECONCILIATION_MISMATCHES_PRESENT" in result.blockers
    assert "MESSAGE_HASH_MISMATCHES_PRESENT" in result.blockers
    assert "REPAYMENT_MISMATCHES_PRESENT" in result.blockers
    assert "AMBIGUOUS_OUTCOMES_PRESENT" in result.blockers


def test_human_review_and_signed_bundle_are_required() -> None:
    evidence = _evidence(
        human_reviewed=False,
        reviewer="",
        signed_by="",
        signature_reference="",
    )

    result = evaluate_shadow_soak(evidence)

    assert result.promotion_ready is False
    assert "HUMAN_REVIEW_MISSING" in result.blockers
    assert "REVIEWER_MISSING" in result.blockers
    assert "SIGNED_EVIDENCE_MISSING" in result.blockers
    assert "SIGNATURE_REFERENCE_MISSING" in result.blockers


def test_missing_required_vertical_stage_blocks() -> None:
    evidence = _evidence(
        vertical_stages=(
            "discovery",
            "capital",
            "planner",
            "compiler",
            "simulation",
            "lifecycle",
        )
    )

    result = evaluate_shadow_soak(evidence)

    assert result.promotion_ready is False
    assert "REQUIRED_STAGE_MISSING:reconciliation" in result.blockers


def test_evidence_validation_rejects_clock_and_count_corruption() -> None:
    start = datetime(2026, 7, 21, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ShadowSoakError, match="ended_at must be after"):
        _evidence(started_at=start, ended_at=start)

    with pytest.raises(ShadowSoakError, match="reconciled outcomes cannot exceed"):
        replace(_metrics(), outcomes_reconciled=19)

    with pytest.raises(ShadowSoakError, match="artifact.path"):
        SoakArtifactReference(
            path="../leak.json",
            sha256=_sha("bad"),
            kind=SoakArtifactKind.RAW_EVENTS,
        )


def test_pr060_can_emit_pr047_pr039_evidence_reference() -> None:
    evidence = _evidence()
    result = evaluate_shadow_soak(evidence)

    reference = to_pr047_shadow_soak_reference(
        evidence,
        result,
        pin_path="artifacts/pr060/shadow-soak-evidence.json",
        pin_sha256=evidence.evidence_sha256,
    )

    assert reference.kind is EvidenceKind.PR039_SHADOW_SOAK
    assert reference.pin.kind is PinKind.EVIDENCE
    assert reference.schema_version == "pr060.shadow-soak-evidence.v1"
    assert reference.passed is True
    assert reference.human_reviewed is True
