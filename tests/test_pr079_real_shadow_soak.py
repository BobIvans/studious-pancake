from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from src.shadow_soak.evidence import (
    ReplayEvidence,
    ShadowSoakEvidence,
    ShadowSoakMetrics,
    SoakArtifactKind,
    SoakArtifactReference,
    SoakEnvironment,
    evaluate_shadow_soak,
)
from src.shadow_soak.real_soak import (
    ImmutableSoakBundle,
    RealShadowSoakPackage,
    RealShadowSoakState,
    SoakPrerequisiteEvidence,
    evaluate_real_shadow_soak,
)

START = datetime(2026, 7, 1, tzinfo=timezone.utc)
END = START + timedelta(hours=73)
REVIEWED = END + timedelta(hours=1)
ASSEMBLED = REVIEWED + timedelta(minutes=5)


def _artifact(kind: SoakArtifactKind, seed: str) -> SoakArtifactReference:
    return SoakArtifactReference(
        path=f"artifacts/pr079/{kind.value}.jsonl",
        sha256=seed * 64,
        kind=kind,
        event_count=10,
    )


def _metrics() -> ShadowSoakMetrics:
    return ShadowSoakMetrics(
        candidates_seen=12,
        candidates_simulated=8,
        candidates_rejected=4,
        paper_outcomes_written=5,
        outcomes_reconciled=5,
        reconciliation_mismatches=0,
        message_hash_mismatches=0,
        repayment_mismatches=0,
        ambiguous_outcomes=0,
        quota_exhaustions=0,
        provider_5xx_errors=0,
        rpc_errors=0,
        stale_data_rejections=2,
        stale_data_accepted=0,
        p50_latency_ms=80,
        p95_latency_ms=120,
        max_latency_ms=200,
        net_pnl_lamports=10,
    )


def _soak(environment: SoakEnvironment = SoakEnvironment.MAINNET_READ_ONLY):
    evidence = ShadowSoakEvidence(
        run_id="pr079-real-soak",
        code_commit="1" * 40,
        started_at=START,
        ended_at=END,
        environment=environment,
        vertical_stages=(
            "discovery",
            "capital",
            "planner",
            "compiler",
            "simulation",
            "reconciliation",
            "lifecycle",
        ),
        metrics=_metrics(),
        replay=ReplayEvidence(
            corpus_events=12,
            replayed_events=12,
            deterministic_passed_events=12,
            deterministic_failed_events=0,
            corpus_sha256="2" * 64,
        ),
        artifacts=(
            _artifact(SoakArtifactKind.RAW_EVENTS, "3"),
            _artifact(SoakArtifactKind.REPLAY_CORPUS, "4"),
            _artifact(SoakArtifactKind.METRICS_REPORT, "5"),
            _artifact(SoakArtifactKind.OPERATOR_REVIEW, "6"),
        ),
        operator="operator",
        human_reviewed=True,
        reviewer="reviewer",
        reviewed_at=REVIEWED,
        signed_by="release-key",
        signature_reference="signatures/pr079.sig",
    )
    return evidence, evaluate_shadow_soak(evidence)


def _prereq(name: str) -> SoakPrerequisiteEvidence:
    return SoakPrerequisiteEvidence(
        name=name,
        evidence_sha256="7" * 64,
        passed=True,
        human_reviewed=True,
        source_commit="8" * 40,
        reviewer="reviewer",
    )


def _package(**overrides) -> RealShadowSoakPackage:
    soak, evaluation = _soak()
    values = {
        "soak": soak,
        "soak_evaluation": evaluation,
        "prerequisites": (
            _prereq("pr076.production-paper-shadow-runner"),
            _prereq("pr077.data-lifecycle-observability"),
            _prereq("pr078.security-sbom-chaos-evidence"),
        ),
        "immutable_bundle": ImmutableSoakBundle(
            uri="artifacts/pr079/immutable-bundle.tar.zst",
            sha256="9" * 64,
            signed=True,
            signature_sha256="a" * 64,
            size_bytes=4096,
        ),
        "assembled_at": ASSEMBLED,
        "assembled_by": "operator",
        "no_sender_observed": True,
        "live_submissions_observed": 0,
        "replay_verified_after_collection": True,
        "minimum_sample_threshold": 10,
    }
    values.update(overrides)
    return RealShadowSoakPackage(**values)


def test_pr079_accepts_real_reviewed_soak_without_live_enablement() -> None:
    result = evaluate_real_shadow_soak(_package())

    assert result.state is RealShadowSoakState.READY_FOR_RELEASE_EVIDENCE
    assert result.release_evidence_ready is True
    assert result.live_allowed is False
    assert result.blockers == ()
    assert result.candidates_seen == 12
    assert result.replay_pass_rate_bps == 10_000


def test_pr079_rejects_recorded_fixture_soak() -> None:
    soak, evaluation = _soak(SoakEnvironment.RECORDED)
    result = evaluate_real_shadow_soak(_package(soak=soak, soak_evaluation=evaluation))

    assert result.state is RealShadowSoakState.BLOCKED
    assert "RECORDED_FIXTURE_NOT_REAL_SOAK" in result.blockers
    assert result.live_allowed is False


def test_pr079_rejects_missing_upstream_prerequisite() -> None:
    result = evaluate_real_shadow_soak(
        _package(
            prerequisites=(
                _prereq("pr076.production-paper-shadow-runner"),
                _prereq("pr077.data-lifecycle-observability"),
            )
        )
    )

    assert result.state is RealShadowSoakState.BLOCKED
    assert "PREREQUISITE_MISSING:pr078.security-sbom-chaos-evidence" in result.blockers


def test_pr079_rejects_sender_or_live_submission_observation() -> None:
    result = evaluate_real_shadow_soak(
        _package(no_sender_observed=False, live_submissions_observed=1)
    )

    assert "SENDER_WAS_OBSERVED_DURING_SOAK" in result.blockers
    assert "LIVE_SUBMISSIONS_OBSERVED" in result.blockers
    assert result.live_allowed is False


def test_pr079_rejects_stale_soak_evaluation_attachment() -> None:
    soak, evaluation = _soak()
    stale_metrics = replace(soak.metrics, candidates_seen=20)
    changed_soak = replace(soak, metrics=stale_metrics)
    result = evaluate_real_shadow_soak(
        _package(soak=changed_soak, soak_evaluation=evaluation)
    )

    assert "SOAK_EVALUATION_HASH_MISMATCH" in result.blockers
    assert "STALE_SOAK_EVALUATION_ATTACHED" in result.blockers
