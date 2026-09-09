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
)

START = datetime(2026, 9, 9, 0, 0, tzinfo=UTC)
GIT_SHA = "1234567890abcdef1234567890abcdef12345678"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _interval(
    segment: str,
    start: int,
    end: int,
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
        intervals=(
            _interval("a", 0, 10),
            _interval("b", 20, 30),
        ),
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
        intervals=(
            _interval("a", 0, 10),
            _interval("b", 12, 20),
        ),
        claimed_eligible_seconds=18,
    )

    result = evaluate_campaign_evidence(evidence, CampaignPolicy(18, 2))

    assert result.eligible_seconds == 18
    assert result.longest_continuous_seconds == 20
    assert result.gap_seconds == 2
    assert result.qualified is True


def test_synthetic_and_recorded_intervals_receive_no_real_duration_credit() -> None:
    evidence = _evidence(
        evidence_class=EvidenceClass.RECORDED_REPLAY,
        intervals=(
            _interval(
                "synthetic",
                0,
                100,
                evidence_class=EvidenceClass.SYNTHETIC_OFFLINE,
            ),
            _interval(
                "recorded",
                100,
                200,
                evidence_class=EvidenceClass.RECORDED_REPLAY,
            ),
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
        outcomes=(
            _outcome("same", SHA_A),
            _outcome("same", SHA_A),
        ),
        claimed_unique_terminal_outcomes=1,
    )

    result = evaluate_campaign_evidence(evidence, CampaignPolicy(10, 0))

    assert result.unique_terminal_outcomes == 1
    assert result.duplicate_terminal_deliveries == 1
    assert "DUPLICATE_TERMINAL_DELIVERIES:1" in result.warnings
    assert result.qualified is True


def test_same_outcome_id_with_changed_semantics_is_conflict() -> None:
    evidence = _evidence(
        outcomes=(
            _outcome("same", SHA_A),
            _outcome("same", SHA_B),
        ),
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
        evidence,
        CampaignPolicy(10, 0, minimum_terminal_samples=2),
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
