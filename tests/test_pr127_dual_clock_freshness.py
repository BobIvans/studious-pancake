from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.freshness import (
    PR127ClockSkewDiagnostic,
    PR127ClockSkewStatus,
    PR127ClockSnapshot,
    PR127CycleDeadlinePlan,
    PR127DeadlineReason,
    PR127FreshnessReason,
    PR127MonotonicLease,
    PR127ProviderNativeExpiry,
    PR127QuoteFreshnessPolicy,
    PR127QuoteProvenance,
    evaluate_pr127_quote_freshness,
)

ROUTE_HASH = "a" * 64
BASE_UTC = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)


def _clock(
    monotonic_ns: int,
    *,
    seconds: int = 0,
    slot: int | None = 100,
    block_height: int | None = 1_000,
) -> PR127ClockSnapshot:
    return PR127ClockSnapshot(
        monotonic_ns=monotonic_ns,
        utc_wall=BASE_UTC + timedelta(seconds=seconds),
        context_slot=slot,
        block_height=block_height,
    )


def _policy(**overrides) -> PR127QuoteFreshnessPolicy:
    data = {
        "provider": "jupiter",
        "conservative_local_max_age_ns": 100,
        "max_context_slot_delta": 3,
        "max_block_height_delta": 5,
        "source": "test-policy",
        "reason": "bounded quote freshness",
    }
    data.update(overrides)
    return PR127QuoteFreshnessPolicy(**data)


def _provenance(**overrides) -> PR127QuoteProvenance:
    data = {
        "provider": "jupiter",
        "quote_id": "quote-001",
        "route_hash": ROUTE_HASH,
        "requested_at": _clock(1_000, seconds=1),
        "received_at": _clock(1_100, seconds=2),
        "provider_timestamp_utc": BASE_UTC + timedelta(seconds=2),
    }
    data.update(overrides)
    return PR127QuoteProvenance(**data)


def test_pr127_wall_clock_jump_cannot_extend_local_quote_validity() -> None:
    decision = evaluate_pr127_quote_freshness(
        provenance=_provenance(),
        policy=_policy(conservative_local_max_age_ns=100),
        now=PR127ClockSnapshot(
            monotonic_ns=1_250,
            utc_wall=BASE_UTC - timedelta(hours=2),
            context_slot=101,
            block_height=1_001,
        ),
    )

    assert decision.fresh is False
    assert decision.reason is PR127FreshnessReason.LOCAL_MAX_AGE_EXPIRED
    assert decision.effective_expires_at_monotonic_ns == 1_200


def test_pr127_wall_clock_jump_cannot_change_freshness_result() -> None:
    provenance = _provenance()
    policy = _policy(conservative_local_max_age_ns=100)
    huge_forward_wall = PR127ClockSnapshot(
        monotonic_ns=1_150,
        utc_wall=BASE_UTC + timedelta(days=365),
        context_slot=101,
        block_height=1_001,
    )
    normal_wall = PR127ClockSnapshot(
        monotonic_ns=1_150,
        utc_wall=BASE_UTC + timedelta(seconds=3),
        context_slot=101,
        block_height=1_001,
    )

    assert (
        evaluate_pr127_quote_freshness(
            provenance=provenance,
            policy=policy,
            now=huge_forward_wall,
        ).to_json()
        == evaluate_pr127_quote_freshness(
            provenance=provenance,
            policy=policy,
            now=normal_wall,
        ).to_json()
    )


def test_pr127_provider_native_expiry_overrides_long_local_max_age() -> None:
    provenance = _provenance(
        provider_native_expiry=PR127ProviderNativeExpiry(
            expires_at_monotonic_ns=1_160,
            provider_expires_at_utc=BASE_UTC + timedelta(seconds=4),
        )
    )

    decision = evaluate_pr127_quote_freshness(
        provenance=provenance,
        policy=_policy(conservative_local_max_age_ns=1_000),
        now=_clock(1_161, seconds=-60, slot=101, block_height=1_001),
    )

    assert decision.fresh is False
    assert decision.reason is PR127FreshnessReason.PROVIDER_NATIVE_EXPIRED
    assert decision.effective_expires_at_monotonic_ns == 1_160


def test_pr127_expires_at_none_never_means_unbounded_freshness() -> None:
    decision = evaluate_pr127_quote_freshness(
        provenance=_provenance(),
        policy=_policy(conservative_local_max_age_ns=None),
        now=_clock(1_101, seconds=3),
    )

    assert decision.fresh is False
    assert decision.reason is PR127FreshnessReason.MISSING_PROVIDER_OR_LOCAL_EXPIRY


def test_pr127_requires_provider_native_expiry_when_policy_demands_it() -> None:
    decision = evaluate_pr127_quote_freshness(
        provenance=_provenance(),
        policy=_policy(
            conservative_local_max_age_ns=100,
            require_provider_native_expiry=True,
        ),
        now=_clock(1_120, seconds=3),
    )

    assert decision.fresh is False
    assert decision.reason is PR127FreshnessReason.MISSING_PROVIDER_OR_LOCAL_EXPIRY


def test_pr127_provenance_preserves_dual_clock_and_chain_context() -> None:
    provenance = _provenance(
        provider_native_expiry=PR127ProviderNativeExpiry(
            expires_at_monotonic_ns=1_200,
            provider_expires_at_utc=BASE_UTC + timedelta(seconds=5),
        )
    )

    payload = provenance.to_json()

    assert payload["requested_at"]["monotonic_ns"] == "1000"
    assert payload["received_at"]["utc_wall"] == "2026-07-21T12:00:02Z"
    assert payload["received_at"]["context_slot"] == 100
    assert payload["received_at"]["block_height"] == 1000
    assert payload["provider_timestamp_utc"] == "2026-07-21T12:00:02Z"
    assert payload["provider_native_expiry"]["expires_at_monotonic_ns"] == "1200"
    assert len(provenance.provenance_hash()) == 64


def test_pr127_cross_slot_and_block_height_policies_fail_closed() -> None:
    by_slot = evaluate_pr127_quote_freshness(
        provenance=_provenance(received_at=_clock(1_100, seconds=2, slot=100)),
        policy=_policy(max_context_slot_delta=2),
        now=_clock(1_120, seconds=3, slot=103),
    )
    by_height = evaluate_pr127_quote_freshness(
        provenance=_provenance(received_at=_clock(1_100, seconds=2, block_height=10)),
        policy=_policy(max_block_height_delta=4),
        now=_clock(1_120, seconds=3, block_height=15),
    )

    assert by_slot.reason is PR127FreshnessReason.CONTEXT_SLOT_TOO_OLD
    assert by_slot.context_slot_delta == 3
    assert by_height.reason is PR127FreshnessReason.BLOCK_HEIGHT_TOO_OLD
    assert by_height.block_height_delta == 5


def test_pr127_cycle_deadline_accounts_for_required_stage_budgets() -> None:
    plan = PR127CycleDeadlinePlan(
        cycle_id="cycle-001",
        started_at=_clock(10_000),
        first_leg_budget_ns=100,
        exact_second_leg_budget_ns=200,
        final_build_budget_ns=300,
        compile_simulation_budget_ns=400,
        slack_budget_ns=50,
    )

    assert plan.total_budget_ns == 1_050
    assert plan.deadline_monotonic_ns == 11_050
    assert plan.evaluate(_clock(11_050, seconds=100)) is (
        PR127DeadlineReason.WITHIN_DEADLINE
    )
    assert plan.evaluate(_clock(11_051, seconds=-100)) is (
        PR127DeadlineReason.DEADLINE_EXPIRED
    )
    assert plan.remaining_ns(_clock(10_050, seconds=999)) == 1_000


def test_pr127_monotonic_lease_ignores_wall_clock_jumps() -> None:
    lease = PR127MonotonicLease(
        key="cooldown:jupiter",
        acquired_at=_clock(5_000),
        ttl_ns=500,
    )

    assert lease.active(
        PR127ClockSnapshot(
            monotonic_ns=5_400,
            utc_wall=BASE_UTC + timedelta(days=30),
        )
    )
    assert not lease.active(
        PR127ClockSnapshot(
            monotonic_ns=5_501,
            utc_wall=BASE_UTC - timedelta(days=30),
        )
    )


def test_pr127_clock_skew_diagnostic_is_advisory_only() -> None:
    diagnostic = PR127ClockSkewDiagnostic(
        observed_utc=BASE_UTC + timedelta(seconds=31),
        reference_utc=BASE_UTC,
        max_allowed_skew_seconds=30,
    )
    decision = evaluate_pr127_quote_freshness(
        provenance=_provenance(),
        policy=_policy(),
        now=_clock(1_150, seconds=31),
    )

    assert diagnostic.status is PR127ClockSkewStatus.SKEWED
    assert decision.fresh is True


def test_pr127_replay_determinism_uses_explicit_clock_inputs() -> None:
    provenance = _provenance()
    policy = _policy()
    now = _clock(1_150, seconds=999)

    first = evaluate_pr127_quote_freshness(
        provenance=provenance,
        policy=policy,
        now=now,
    )
    second = evaluate_pr127_quote_freshness(
        provenance=provenance,
        policy=policy,
        now=now,
    )

    assert first.to_json() == second.to_json()


def test_pr127_rejects_non_utc_wall_clock() -> None:
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        PR127ClockSnapshot(
            monotonic_ns=1,
            utc_wall=datetime(2026, 7, 21, 12, 0),
        )
