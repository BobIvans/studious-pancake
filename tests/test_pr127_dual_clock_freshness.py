from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.freshness.dual_clock import (
    PR127ClockError,
    PR127ClockReading,
    PR127ClockSkewIssue,
    PR127Cooldown,
    PR127CycleBudget,
    PR127ExpiryMode,
    PR127FreshnessReason,
    PR127Lease,
    PR127QuoteFreshnessEvidence,
    PR127ReplayClock,
    PR127SlotPolicy,
    diagnose_pr127_clock_skew,
    evaluate_pr127_quote_freshness,
)

NS = 1_000_000_000
START_UTC = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


def _reading(
    monotonic_ns: int,
    *,
    utc_offset_seconds: int = 0,
    slot: int = 100,
    block_height: int = 5_000,
) -> PR127ClockReading:
    return PR127ClockReading(
        monotonic_ns=monotonic_ns,
        utc_datetime=START_UTC + timedelta(seconds=utc_offset_seconds),
        context_slot=slot,
        block_height=block_height,
        source="test-clock",
    )


def test_pr127_wall_clock_backward_jump_cannot_extend_quote_validity() -> None:
    received = _reading(10 * NS, utc_offset_seconds=10)
    evidence = PR127QuoteFreshnessEvidence.local_max_age(
        provider="jupiter",
        candidate_id="candidate-a",
        requested_at_monotonic_ns=9 * NS,
        received_at=received,
        max_age_ns=2 * NS,
        source_reason="provider has no native expiry; bounded locally",
    )

    jumped_back = _reading(13 * NS, utc_offset_seconds=-3)
    decision = evaluate_pr127_quote_freshness(evidence, evaluated_at=jumped_back)

    assert decision.allowed is False
    assert decision.reason is PR127FreshnessReason.QUOTE_EXPIRED
    assert evidence.to_json()["expiry_mode"] == PR127ExpiryMode.LOCAL_MAX_AGE.value


def test_pr127_wall_clock_forward_jump_cannot_skip_cooldown_or_expire_lease() -> None:
    start = _reading(100, utc_offset_seconds=0)
    future_wall_same_monotonic_window = _reading(
        200,
        utc_offset_seconds=86_400,
    )
    cooldown = PR127Cooldown.start(start, key="provider:jupiter", duration_ns=1_000)
    lease = PR127Lease.acquire(
        start,
        resource_key="candidate-a",
        owner_id="worker-1",
        ttl_ns=1_000,
    )

    assert cooldown.ready_at(future_wall_same_monotonic_window) is False
    assert lease.active_at(future_wall_same_monotonic_window) is True


def test_pr127_provider_native_and_local_expiry_are_explicitly_bounded() -> None:
    received = _reading(1_000, slot=120)
    provider_native = PR127QuoteFreshnessEvidence.provider_native_expiry_after(
        provider="okx",
        candidate_id="candidate-b",
        requested_at_monotonic_ns=900,
        received_at=received,
        expires_after_ns=250,
        source_reason="provider returned quote TTL",
        provider_timestamp_utc=received.utc_datetime,
        provider_expires_at_utc=received.utc_datetime + timedelta(milliseconds=1),
    )
    local = PR127QuoteFreshnessEvidence.local_max_age(
        provider="openocean",
        candidate_id="candidate-c",
        requested_at_monotonic_ns=900,
        received_at=received,
        max_age_ns=150,
        source_reason="documented conservative adapter max age",
    )

    assert provider_native.expiry_mode is PR127ExpiryMode.PROVIDER_NATIVE
    assert provider_native.expires_at_monotonic_ns == 1_250
    assert local.expiry_mode is PR127ExpiryMode.LOCAL_MAX_AGE
    assert local.expires_at_monotonic_ns == 1_150

    with pytest.raises(PR127ClockError, match="positive integer"):
        PR127QuoteFreshnessEvidence.local_max_age(
            provider="bad-provider",
            candidate_id="candidate-d",
            requested_at_monotonic_ns=900,
            received_at=received,
            max_age_ns=0,
            source_reason="unbounded freshness must fail closed",
        )


def test_pr127_preserves_quote_provenance_fields() -> None:
    received = _reading(2_000, utc_offset_seconds=2, slot=777, block_height=9_999)
    provider_time = received.utc_datetime - timedelta(milliseconds=100)
    evidence = PR127QuoteFreshnessEvidence.local_max_age(
        provider="jupiter",
        candidate_id="candidate-provenance",
        requested_at_monotonic_ns=1_500,
        received_at=received,
        max_age_ns=500,
        source_reason="adapter policy",
        provider_timestamp_utc=provider_time,
    )
    payload = evidence.to_json()

    assert payload["requested_at_monotonic_ns"] == "1500"
    assert payload["received_at"]["monotonic_ns"] == "2000"
    assert payload["provider_timestamp_utc"] == "2026-07-21T12:00:01.900000Z"
    assert payload["context_slot"] == 777
    assert payload["block_height"] == 9_999


def test_pr127_cycle_deadline_sums_all_finalization_budgets() -> None:
    start = _reading(1_000)
    budget = PR127CycleBudget(
        first_legs_ns=10,
        exact_second_legs_ns=20,
        final_build_ns=30,
        compile_simulation_ns=40,
        retry_overhead_ns=5,
    )
    deadline = budget.deadline_from(start)

    assert budget.total_budget_ns == 105
    assert deadline.expires_at_monotonic_ns == 1_105
    assert deadline.expired_at(_reading(1_104)) is False
    assert deadline.expired_at(_reading(1_105)) is True


def test_pr127_cross_slot_policy_is_provider_candidate_specific() -> None:
    received = _reading(10_000, slot=100, block_height=1_000)
    evidence = PR127QuoteFreshnessEvidence.local_max_age(
        provider="jupiter",
        candidate_id="candidate-slot",
        requested_at_monotonic_ns=9_000,
        received_at=received,
        max_age_ns=10_000,
        source_reason="bounded local ttl",
    )
    policy = PR127SlotPolicy(
        provider="jupiter",
        candidate_id="candidate-slot",
        allow_cross_slot=True,
        max_slot_drift=2,
        max_block_height_drift=10,
    )

    accepted = evaluate_pr127_quote_freshness(
        evidence,
        evaluated_at=_reading(11_000, slot=102, block_height=1_009),
        policy=policy,
    )
    rejected = evaluate_pr127_quote_freshness(
        evidence,
        evaluated_at=_reading(11_000, slot=103, block_height=1_009),
        policy=policy,
    )

    assert accepted.allowed is True
    assert rejected.allowed is False
    assert rejected.reason is PR127FreshnessReason.SLOT_DRIFT_EXCEEDED


def test_pr127_same_slot_policy_rejects_cross_slot_candidates() -> None:
    received = _reading(10_000, slot=200)
    evidence = PR127QuoteFreshnessEvidence.local_max_age(
        provider="odos",
        candidate_id="candidate-same-slot",
        requested_at_monotonic_ns=9_000,
        received_at=received,
        max_age_ns=10_000,
        source_reason="bounded local ttl",
    )
    policy = PR127SlotPolicy(
        provider="odos",
        candidate_id="candidate-same-slot",
        allow_cross_slot=False,
    )

    decision = evaluate_pr127_quote_freshness(
        evidence,
        evaluated_at=_reading(11_000, slot=201),
        policy=policy,
    )

    assert decision.allowed is False
    assert decision.reason is PR127FreshnessReason.CROSS_SLOT_NOT_ALLOWED


def test_pr127_replay_clock_deterministically_replays_wall_clock_jumps() -> None:
    replay = PR127ReplayClock(
        (
            _reading(1_000, utc_offset_seconds=10),
            _reading(1_500, utc_offset_seconds=-10),
        )
    )
    first = replay.now()
    second = replay.now()
    deadline = PR127CycleBudget(
        first_legs_ns=100,
        exact_second_legs_ns=100,
        final_build_ns=100,
        compile_simulation_ns=100,
    ).deadline_from(first)

    assert deadline.remaining_ns_at(second) == 0
    assert deadline.expired_at(second) is True
    with pytest.raises(PR127ClockError, match="exhausted"):
        replay.now()


def test_pr127_ntp_skew_diagnostic_detects_backward_wall_clock() -> None:
    previous = _reading(1_000, utc_offset_seconds=10)
    current = _reading(2_000, utc_offset_seconds=9)

    issues = diagnose_pr127_clock_skew(
        previous,
        current,
        max_wall_monotonic_skew_ns=10,
    )

    assert PR127ClockSkewIssue.WALL_CLOCK_MOVED_BACKWARD in issues
    assert PR127ClockSkewIssue.WALL_MONOTONIC_SKEW_EXCEEDED in issues
