import pytest

from src.providers.jupiter.quota import (
    JupiterQuotaError,
    JupiterQuotaManager,
    JupiterQuotaPurpose,
    cache_key,
)
from src.providers.jupiter.scheduler import (
    JupiterAttemptContext,
    JupiterAttemptSchedulerConfig,
    JupiterAttemptStopReason,
    JupiterRouteAttemptScheduler,
    JupiterSafetyEnvelope,
)


def envelope() -> JupiterSafetyEnvelope:
    return JupiterSafetyEnvelope(
        max_slippage_bps=50,
        max_price_impact_bps=100,
        min_net_profit_base_units=1,
    )


@pytest.mark.asyncio
async def test_account_wide_quota_preserves_finalization_reserve_and_recovers():
    now = [0.0]
    quota = JupiterQuotaManager(
        limit=5,
        window_seconds=10,
        finalization_reserve=1,
        clock=lambda: now[0],
    )

    for _ in range(4):
        token = await quota.reserve(JupiterQuotaPurpose.DISCOVERY)
        await quota.mark_used(token)

    with pytest.raises(JupiterQuotaError) as denied:
        await quota.reserve(JupiterQuotaPurpose.REFINEMENT)
    assert denied.value.reason == "account-wide-quota-exhausted"
    assert quota.metrics.finalization_reserve_starvation == 1

    final_token = await quota.reserve(JupiterQuotaPurpose.FINALIZATION)
    await quota.mark_used(final_token)

    now[0] = 11.0
    await quota.reserve(JupiterQuotaPurpose.DISCOVERY)
    snapshot = quota.snapshot()
    assert snapshot["window_occupancy"] == 1
    assert snapshot["circuit_state"] == "ready"


@pytest.mark.asyncio
async def test_retry_after_circuit_blocks_then_reopens():
    now = [100.0]
    quota = JupiterQuotaManager(
        limit=10,
        window_seconds=60,
        finalization_reserve=2,
        clock=lambda: now[0],
    )

    quota.record_http_429(3.0)
    with pytest.raises(JupiterQuotaError) as denied:
        await quota.reserve(JupiterQuotaPurpose.FINALIZATION)
    assert denied.value.reason == "retry-after-active"

    now[0] = 104.0
    token = await quota.reserve(JupiterQuotaPurpose.FINALIZATION)
    assert token.purpose is JupiterQuotaPurpose.FINALIZATION
    assert quota.snapshot()["circuit_state"] == "ready"


def test_cache_key_and_cache_ttl_are_deterministic_and_redaction_safe():
    now = [0.0]
    quota = JupiterQuotaManager(clock=lambda: now[0])
    key = cache_key(("SOL", "USDC", 1_000_000, "profile-64"))
    quota.cache_put(key, {"quote": "redacted"}, ttl_seconds=1.0)
    assert quota.cache_get(key) == {"quote": "redacted"}
    now[0] = 2.0
    assert quota.cache_get(key) is None


def test_scheduler_is_finite_and_does_not_relax_safety_envelope():
    scheduler = JupiterRouteAttemptScheduler(
        JupiterAttemptSchedulerConfig(
            account_budget_steps=(64, 56, 50, 48),
            reserve_finalization_profiles=1,
            max_attempts=4,
        ),
        envelope(),
    )

    plan = scheduler.plan(
        JupiterAttemptContext(
            trace_id="trace-031",
            request_fingerprint="SOL/USDC/1000000",
            now=10.0,
            deadline_at=11.0,
            quote_created_at=9.5,
            estimated_edge_bps=25,
            min_edge_bps=10,
        )
    )

    assert plan.stop_reason is JupiterAttemptStopReason.READY
    assert len(plan.attempts) == 4
    assert [attempt.max_accounts for attempt in plan.attempts] == [64, 56, 50, 50]
    assert plan.attempts[-1].profile.request_purpose is JupiterQuotaPurpose.FINALIZATION
    assert all(attempt.envelope == envelope() for attempt in plan.attempts)
    assert all(attempt.max_accounts >= 50 for attempt in plan.attempts)


def test_scheduler_stop_conditions_fail_closed_before_requesting_quota():
    scheduler = JupiterRouteAttemptScheduler(
        JupiterAttemptSchedulerConfig(account_budget_steps=(64, 56)),
        envelope(),
    )

    expired = scheduler.plan(
        JupiterAttemptContext(
            trace_id="expired",
            request_fingerprint="same",
            now=10.0,
            deadline_at=10.0,
        )
    )
    assert expired.attempts == ()
    assert expired.stop_reason is JupiterAttemptStopReason.DEADLINE_EXCEEDED

    stale = scheduler.plan(
        JupiterAttemptContext(
            trace_id="stale",
            request_fingerprint="same",
            now=10.0,
            deadline_at=12.0,
            quote_created_at=0.0,
        )
    )
    assert stale.attempts == ()
    assert stale.stop_reason is JupiterAttemptStopReason.STALE_QUOTE

    weak_edge = scheduler.plan(
        JupiterAttemptContext(
            trace_id="weak",
            request_fingerprint="same",
            now=10.0,
            deadline_at=12.0,
            estimated_edge_bps=4,
            min_edge_bps=5,
        )
    )
    assert weak_edge.attempts == ()
    assert weak_edge.stop_reason is JupiterAttemptStopReason.EDGE_BELOW_THRESHOLD


def test_routing_adapter_uses_shared_jupiter_quota_not_private_fixed_limiter():
    from src.routing.adapters import JupiterRouterAdapter

    quota = JupiterQuotaManager(limit=7, window_seconds=30, finalization_reserve=2)
    adapter = JupiterRouterAdapter(jupiter_quota=quota)
    assert adapter.quota is quota
    assert not hasattr(adapter, "limiter")
