from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.shadow_soak.campaign_evidence import (
    CampaignEvidence,
    CampaignPolicy,
    CoverageInterval,
    EvidenceClass,
    IntervalKind,
    OutcomeRecord,
    evaluate_campaign_evidence,
    evaluate_real_shadow_soak_residual,
)
from src.shadow_soak.evidence import (
    MINIMUM_SOAK_SECONDS,
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
    SoakPrerequisiteEvidence,
)

START = datetime(2026, 9, 9, 0, 0, tzinfo=UTC)
GIT_SHA = "1234567890abcdef1234567890abcdef12345678"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _interval(
    segment: str,
    start: float,
    end: float,
    *,
    evidence_class: EvidenceClass = EvidenceClass.REAL_SHADOW_READ_ONLY,
    kind: IntervalKind = IntervalKind.ELIGIBLE,
) -> CoverageInterval:
    return CoverageInterval(
        segment_id=segment,
        started_at=START + timedelta(seconds=start),
        ended_at=START + timedelta(seconds=end),
        evidence_class=evidence_class,
        kind=kind,
        source_cursor=f"cursor-{segment}",
    )


def _outcome(
    outcome_id: str,
    semantic_sha256: str = SHA_A,
    *,
    observation: str | None = None,
    cycle: str | None = None,
    attempt: str | None = None,
    terminal: bool = True,
) -> OutcomeRecord:
    return OutcomeRecord(
        outcome_id=outcome_id,
        semantic_sha256=semantic_sha256,
        source_observation_id=observation or f"obs-{outcome_id}",
        logical_cycle_id=cycle or f"cycle-{outcome_id}",
        provider_attempt_id=attempt or f"attempt-{outcome_id}",
        terminal=terminal,
    )


def _evidence(**overrides: object) -> CampaignEvidence:
    data: dict[str, object] = {
        "campaign_id": "campaign-2607",
        "source_commit": GIT_SHA,
        "installed_artifact_sha256": SHA_B,
        "policy_sha256": SHA_C,
        "evidence_class": EvidenceClass.REAL_SHADOW_READ_ONLY,
        "intervals": (_interval("a", 0, 10),),
        "outcomes": (_outcome("o1"),),
        "claimed_eligible_seconds": 10,
        "claimed_unique_terminal_outcomes": 1,
    }
    data.update(overrides)
    return CampaignEvidence(**data)


def _artifact(kind: SoakArtifactKind, seed: str) -> SoakArtifactReference:
    return SoakArtifactReference(
        path=f"artifacts/mpr2607/{kind.value}.jsonl",
        sha256=seed * 64,
        kind=kind,
        event_count=10,
    )


def _metrics() -> ShadowSoakMetrics:
    return ShadowSoakMetrics(
        candidates_seen=2,
        candidates_simulated=2,
        candidates_rejected=0,
        paper_outcomes_written=2,
        outcomes_reconciled=2,
        reconciliation_mismatches=0,
        message_hash_mismatches=0,
        repayment_mismatches=0,
        ambiguous_outcomes=0,
        quota_exhaustions=0,
        provider_5xx_errors=0,
        rpc_errors=0,
        stale_data_rejections=0,
        stale_data_accepted=0,
        p50_latency_ms=10,
        p95_latency_ms=20,
        max_latency_ms=30,
        net_pnl_lamports=1,
    )


def _prereq(name: str) -> SoakPrerequisiteEvidence:
    return SoakPrerequisiteEvidence(
        name=name,
        evidence_sha256="7" * 64,
        passed=True,
        human_reviewed=True,
        source_commit="8" * 40,
        reviewer="reviewer",
    )


def _package() -> RealShadowSoakPackage:
    end = START + timedelta(seconds=MINIMUM_SOAK_SECONDS + 3600)
    reviewed = end + timedelta(minutes=5)
    soak = ShadowSoakEvidence(
        run_id="campaign-2607",
        code_commit=GIT_SHA,
        started_at=START,
        ended_at=end,
        environment=SoakEnvironment.MAINNET_READ_ONLY,
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
            corpus_events=2,
            replayed_events=2,
            deterministic_passed_events=2,
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
        reviewed_at=reviewed,
        signed_by="release-key",
        signature_reference="signatures/mpr2607.sig",
    )
    return RealShadowSoakPackage(
        soak=soak,
        soak_evaluation=evaluate_shadow_soak(soak),
        prerequisites=(
            _prereq("pr076.production-paper-shadow-runner"),
            _prereq("pr077.data-lifecycle-observability"),
            _prereq("pr078.security-sbom-chaos-evidence"),
        ),
        immutable_bundle=ImmutableSoakBundle(
            uri="artifacts/mpr2607/bundle.tar.zst",
            sha256="9" * 64,
            signed=True,
            signature_sha256="d" * 64,
            size_bytes=4096,
        ),
        assembled_at=reviewed + timedelta(minutes=1),
        assembled_by="operator",
        no_sender_observed=True,
        live_submissions_observed=0,
        replay_verified_after_collection=True,
        minimum_sample_threshold=1,
    )


def test_overlapping_parallel_segments_use_union_not_sum() -> None:
    evidence = _evidence(
        intervals=(
            _interval("a", 0, 10),
            _interval("b", 5, 15),
        ),
        claimed_eligible_seconds=15,
    )
    result = evaluate_campaign_evidence(evidence, CampaignPolicy(15, 0))
    assert result.eligible_seconds == 15
    assert result.calendar_span_seconds == 15
    assert result.longest_continuous_seconds == 15
    assert result.qualified is True


def test_calendar_span_does_not_fill_unobserved_gap() -> None:
    evidence = _evidence(
        intervals=(_interval("a", 0, 10), _interval("b", 20, 30)),
        claimed_eligible_seconds=20,
    )
    result = evaluate_campaign_evidence(evidence, CampaignPolicy(20, 0))
    assert result.eligible_seconds == 20
    assert result.calendar_span_seconds == 30
    assert result.gap_seconds == 10
    assert result.longest_continuous_seconds == 10
    assert "CONTINUOUS_WINDOW_BELOW_POLICY" in result.blockers


def test_permitted_gap_can_join_continuous_window_without_inflating_coverage() -> None:
    evidence = _evidence(
        intervals=(_interval("a", 0, 10), _interval("b", 12, 20)),
        claimed_eligible_seconds=18,
    )
    result = evaluate_campaign_evidence(evidence, CampaignPolicy(18, 2))
    assert result.eligible_seconds == 18
    assert result.longest_continuous_seconds == 20
    assert result.gap_seconds == 2
    assert result.qualified is True


def test_fractional_gap_is_compared_without_truncation() -> None:
    evidence = _evidence(
        intervals=(_interval("a", 0, 10), _interval("b", 12.9, 20.9)),
        claimed_eligible_seconds=18,
    )
    result = evaluate_campaign_evidence(evidence, CampaignPolicy(18, 2))
    assert result.eligible_seconds == 18
    assert result.longest_continuous_seconds == 10
    assert "CONTINUOUS_WINDOW_BELOW_POLICY" in result.blockers


def test_synthetic_and_recorded_intervals_receive_no_real_duration_credit() -> None:
    evidence = _evidence(
        evidence_class=EvidenceClass.RECORDED_REPLAY,
        intervals=(
            _interval("synthetic", 0, 100, evidence_class=EvidenceClass.SYNTHETIC_OFFLINE),
            _interval("recorded", 100, 200, evidence_class=EvidenceClass.RECORDED_REPLAY),
        ),
        claimed_eligible_seconds=200,
    )
    result = evaluate_campaign_evidence(evidence, CampaignPolicy(1, 0))
    assert result.eligible_seconds == 0
    assert "REAL_SHADOW_LINEAGE_REQUIRED" in result.blockers
    assert "CLAIMED_DURATION_MISMATCH" in result.blockers


def test_replay_execution_count_never_adds_real_duration() -> None:
    evidence = _evidence(replay_executions=100)
    result = evaluate_campaign_evidence(evidence, CampaignPolicy(10, 0))
    assert result.eligible_seconds == 10
    assert result.qualified is True
    assert "REPLAY_EXECUTIONS_EXCLUDED_FROM_REAL_DURATION:100" in result.warnings


def test_duplicate_terminal_delivery_is_counted_once() -> None:
    evidence = _evidence(
        outcomes=(_outcome("same", SHA_A), _outcome("same", SHA_A)),
        claimed_unique_terminal_outcomes=1,
    )
    result = evaluate_campaign_evidence(evidence, CampaignPolicy(10, 0))
    assert result.unique_terminal_outcomes == 1
    assert result.duplicate_terminal_deliveries == 1
    assert "DUPLICATE_TERMINAL_DELIVERIES:1" in result.warnings
    assert result.qualified is True


def test_new_outcome_id_cannot_duplicate_same_terminal_lineage() -> None:
    evidence = _evidence(
        outcomes=(
            _outcome("delivery-1", SHA_A, observation="obs", cycle="cycle", attempt="attempt"),
            _outcome("delivery-2", SHA_A, observation="obs", cycle="cycle", attempt="attempt"),
        ),
        claimed_unique_terminal_outcomes=1,
    )
    result = evaluate_campaign_evidence(
        evidence, CampaignPolicy(10, 0, minimum_terminal_samples=2)
    )
    assert result.unique_terminal_outcomes == 1
    assert result.duplicate_terminal_deliveries == 1
    assert "TERMINAL_SAMPLES_BELOW_POLICY" in result.blockers


def test_same_lineage_with_changed_semantics_is_conflict() -> None:
    evidence = _evidence(
        outcomes=(
            _outcome("delivery-1", SHA_A, observation="obs", cycle="cycle", attempt="attempt"),
            _outcome("delivery-2", SHA_B, observation="obs", cycle="cycle", attempt="attempt"),
        ),
        claimed_unique_terminal_outcomes=1,
    )
    result = evaluate_campaign_evidence(evidence, CampaignPolicy(10, 0))
    assert any(reason.startswith("OUTCOME_LINEAGE_SEMANTIC_CONFLICT:") for reason in result.blockers)


def test_same_outcome_id_with_changed_semantics_is_conflict() -> None:
    evidence = _evidence(
        outcomes=(_outcome("same", SHA_A), _outcome("same", SHA_B)),
        claimed_unique_terminal_outcomes=1,
    )
    result = evaluate_campaign_evidence(evidence, CampaignPolicy(10, 0))
    assert "OUTCOME_ID_SEMANTIC_CONFLICT:same" in result.blockers
    assert result.qualified is False


def test_equal_market_payload_can_still_be_distinct_real_observations() -> None:
    evidence = _evidence(
        outcomes=(
            _outcome("o1", SHA_A, observation="poll-1"),
            _outcome("o2", SHA_A, observation="poll-2"),
        ),
        claimed_unique_terminal_outcomes=2,
    )
    result = evaluate_campaign_evidence(
        evidence, CampaignPolicy(10, 0, minimum_terminal_samples=2)
    )
    assert result.unique_terminal_outcomes == 2
    assert result.qualified is True


def test_summary_only_duration_or_count_forgery_is_rejected() -> None:
    evidence = _evidence(
        claimed_eligible_seconds=72 * 60 * 60,
        claimed_unique_terminal_outcomes=99,
    )
    result = evaluate_campaign_evidence(evidence, CampaignPolicy(10, 0))
    assert result.eligible_seconds == 10
    assert result.unique_terminal_outcomes == 1
    assert "CLAIMED_DURATION_MISMATCH" in result.blockers
    assert "CLAIMED_TERMINAL_COUNT_MISMATCH" in result.blockers


def test_blocked_fault_and_downtime_intervals_do_not_receive_eligible_credit() -> None:
    evidence = _evidence(
        intervals=(
            _interval("ok", 0, 10),
            _interval("fault", 10, 20, kind=IntervalKind.FAULT),
            _interval("down", 20, 30, kind=IntervalKind.DOWNTIME),
            _interval("blocked", 30, 40, kind=IntervalKind.BLOCKED),
        ),
        claimed_eligible_seconds=10,
    )
    result = evaluate_campaign_evidence(evidence, CampaignPolicy(10, 0))
    assert result.eligible_seconds == 10
    assert result.calendar_span_seconds == 40
    assert result.gap_seconds == 30
    assert result.qualified is True


def test_composed_qualification_enforces_pr079_72h_floor_on_recomputed_coverage() -> None:
    package = _package()
    evidence = _evidence(
        campaign_id=package.soak.run_id,
        source_commit=package.soak.code_commit,
        intervals=(_interval("short", 0, 10),),
        claimed_eligible_seconds=10,
    )
    result = evaluate_real_shadow_soak_residual(
        package,
        evidence,
        CampaignPolicy(10, 0),
    )
    assert result.existing_readiness.release_evidence_ready is True
    assert result.residual.eligible_seconds == 10
    assert "MPR2607:ELIGIBLE_DURATION_BELOW_POLICY" in result.blockers
    assert "MPR2607:CONTINUOUS_WINDOW_BELOW_POLICY" in result.blockers
    assert result.qualified is False


def test_composed_qualification_rejects_real_intervals_outside_soak_window() -> None:
    package = _package()
    duration = MINIMUM_SOAK_SECONDS
    outside = CoverageInterval(
        segment_id="outside",
        started_at=package.soak.ended_at + timedelta(seconds=1),
        ended_at=package.soak.ended_at + timedelta(seconds=duration + 1),
        evidence_class=EvidenceClass.REAL_SHADOW_READ_ONLY,
        kind=IntervalKind.ELIGIBLE,
        source_cursor="cursor-outside",
    )
    evidence = _evidence(
        campaign_id=package.soak.run_id,
        source_commit=package.soak.code_commit,
        intervals=(outside,),
        claimed_eligible_seconds=duration,
    )
    result = evaluate_real_shadow_soak_residual(
        package,
        evidence,
        CampaignPolicy(duration, 0),
    )
    assert "MPR2607:INTERVAL_OUTSIDE_SOAK_WINDOW:outside" in result.blockers
    assert result.qualified is False
