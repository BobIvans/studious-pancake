import asyncio

import pytest

from src.proof_critical_scheduler_pr194 import (
    IsolatedConcurrencyPools,
    ProofCriticalSchedulerConfig,
    ProofCriticalWorkloadScheduler,
    ScheduledWork,
    WorkPool,
    WorkloadClass,
)
from src.providers.jupiter.quota import JupiterQuotaManager, JupiterQuotaPurpose
from src.providers.jupiter.scheduler import (
    JupiterAttemptContext,
    JupiterAttemptSchedulerConfig,
    JupiterAttemptStopReason,
    JupiterRouteAttemptScheduler,
    JupiterSafetyEnvelope,
)


def _envelope() -> JupiterSafetyEnvelope:
    return JupiterSafetyEnvelope(
        max_slippage_bps=50,
        max_price_impact_bps=100,
        min_net_profit_base_units=1,
    )


def _work(
    work_id: str,
    *,
    strategy: str,
    workload_class: WorkloadClass,
    now: float = 0.0,
    deadline: float = 10.0,
    priority: float = 0.0,
    required: bool = False,
) -> ScheduledWork:
    return ScheduledWork(
        work_id=work_id,
        strategy_id=strategy,
        provider_id="jupiter",
        workload_class=workload_class,
        enqueued_at=now,
        deadline_at=deadline,
        estimated_cost_seconds=0.1,
        base_priority=priority,
        required=required,
    )


@pytest.mark.asyncio
async def test_discovery_capacity_does_not_block_finalization_profile() -> None:
    now = [0.0]
    quota = JupiterQuotaManager(
        limit=10,
        window_seconds=60,
        finalization_reserve=2,
        clock=lambda: now[0],
    )
    for _ in range(8):
        token = await quota.reserve(JupiterQuotaPurpose.DISCOVERY)
        await quota.mark_used(token)

    scheduler = JupiterRouteAttemptScheduler(
        JupiterAttemptSchedulerConfig(
            account_budget_steps=(64, 56, 50),
            reserve_finalization_profiles=1,
            max_attempts=4,
        ),
        _envelope(),
        quota,
    )
    plan = scheduler.plan(
        JupiterAttemptContext(
            trace_id="pr194-finalization-reserve",
            request_fingerprint="SOL/USDC/1000",
            now=0.0,
            deadline_at=1.0,
        )
    )

    assert plan.stop_reason is JupiterAttemptStopReason.READY
    assert [attempt.profile.request_purpose for attempt in plan.attempts] == [
        JupiterQuotaPurpose.FINALIZATION
    ]
    assert set(plan.quota_skipped_profiles) == {
        "discovery-max-accounts-64",
        "refinement-max-accounts-56",
        "refinement-max-accounts-50",
    }


def test_max_attempts_cannot_remove_reserved_finalization_profiles() -> None:
    scheduler = JupiterRouteAttemptScheduler(
        JupiterAttemptSchedulerConfig(
            account_budget_steps=(64, 56, 50),
            reserve_finalization_profiles=2,
            max_attempts=3,
        ),
        _envelope(),
    )
    profiles = scheduler.profiles()
    assert len(profiles) == 3
    assert [profile.request_purpose for profile in profiles[-2:]] == [
        JupiterQuotaPurpose.FINALIZATION,
        JupiterQuotaPurpose.FINALIZATION,
    ]

    with pytest.raises(ValueError, match="cannot truncate"):
        JupiterRouteAttemptScheduler(
            JupiterAttemptSchedulerConfig(
                reserve_finalization_profiles=2,
                max_attempts=1,
            ),
            _envelope(),
        )


@pytest.mark.asyncio
async def test_required_reserve_survives_optional_strategy_flood() -> None:
    scheduler = ProofCriticalWorkloadScheduler(
        ProofCriticalSchedulerConfig(
            max_queue_size=4,
            required_reserve=1,
            max_per_strategy=4,
            max_per_provider=4,
        ),
        clock=lambda: 0.0,
    )

    assert await scheduler.put(
        _work(
            "a-1",
            strategy="noisy",
            workload_class=WorkloadClass.OPTIONAL_DISCOVERY,
            priority=3,
        )
    )
    assert await scheduler.put(
        _work(
            "a-2",
            strategy="noisy",
            workload_class=WorkloadClass.OPTIONAL_DISCOVERY,
            priority=2,
        )
    )
    assert await scheduler.put(
        _work(
            "a-3",
            strategy="noisy",
            workload_class=WorkloadClass.OPTIONAL_DISCOVERY,
            priority=1,
        )
    )
    assert not await scheduler.put(
        _work(
            "a-4",
            strategy="noisy",
            workload_class=WorkloadClass.OPTIONAL_DISCOVERY,
            priority=0,
        )
    )
    assert await scheduler.put(
        _work(
            "required",
            strategy="low-volume",
            workload_class=WorkloadClass.REQUIRED_DISCOVERY,
        )
    )

    selected = await scheduler.get(WorkPool.DISCOVERY)
    assert selected.work_id == "required"


@pytest.mark.asyncio
async def test_weighted_fair_dispatch_serves_low_volume_strategy() -> None:
    scheduler = ProofCriticalWorkloadScheduler(
        ProofCriticalSchedulerConfig(
            max_queue_size=8,
            required_reserve=1,
            strategy_weights={"noisy": 1, "low-volume": 1},
        ),
        clock=lambda: 0.0,
    )
    for index in range(4):
        assert await scheduler.put(
            _work(
                f"noisy-{index}",
                strategy="noisy",
                workload_class=WorkloadClass.OPTIONAL_DISCOVERY,
                priority=100 - index,
            )
        )
    assert await scheduler.put(
        _work(
            "low-volume-1",
            strategy="low-volume",
            workload_class=WorkloadClass.OPTIONAL_DISCOVERY,
            priority=1,
        )
    )

    first = await scheduler.get(WorkPool.DISCOVERY)
    second = await scheduler.get(WorkPool.DISCOVERY)
    assert first.strategy_id == "low-volume"
    assert second.strategy_id == "noisy"


@pytest.mark.asyncio
async def test_impossible_work_is_rejected_before_consuming_capacity() -> None:
    scheduler = ProofCriticalWorkloadScheduler(clock=lambda: 9.95)
    accepted = await scheduler.put(
        _work(
            "expired",
            strategy="required",
            workload_class=WorkloadClass.FINALIZATION,
            now=0.0,
            deadline=10.0,
            required=True,
        )
    )
    assert not accepted
    assert scheduler.qsize() == 0
    assert scheduler.metrics.rejected_impossible == 1


@pytest.mark.asyncio
async def test_finalization_pool_isolated_from_discovery_exhaustion() -> None:
    clock = lambda: asyncio.get_running_loop().time()
    config = ProofCriticalSchedulerConfig(
        pool_capacities={
            WorkPool.DISCOVERY: 1,
            WorkPool.FINALIZATION: 1,
            WorkPool.SETTLEMENT: 1,
        }
    )
    pools = IsolatedConcurrencyPools(config, clock=clock)
    deadline = clock() + 1.0

    async with pools.lease(WorkPool.DISCOVERY, deadline_at=deadline):
        async with pools.lease(WorkPool.FINALIZATION, deadline_at=deadline):
            assert pools.metrics.pool_active[WorkPool.DISCOVERY.value] == 1
            assert pools.metrics.pool_active[WorkPool.FINALIZATION.value] == 1


@pytest.mark.asyncio
async def test_cancelled_pool_waiter_does_not_leak_capacity() -> None:
    clock = lambda: asyncio.get_running_loop().time()
    config = ProofCriticalSchedulerConfig(
        pool_capacities={
            WorkPool.DISCOVERY: 1,
            WorkPool.FINALIZATION: 1,
            WorkPool.SETTLEMENT: 1,
        }
    )
    pools = IsolatedConcurrencyPools(config, clock=clock)
    deadline = clock() + 5.0

    async with pools.lease(WorkPool.DISCOVERY, deadline_at=deadline):
        entered = asyncio.Event()

        async def waiter() -> None:
            entered.set()
            async with pools.lease(WorkPool.DISCOVERY, deadline_at=deadline):
                raise AssertionError("cancelled waiter acquired unexpectedly")

        task = asyncio.create_task(waiter())
        await entered.wait()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async with pools.lease(WorkPool.DISCOVERY, deadline_at=clock() + 1.0):
        assert pools.metrics.pool_active[WorkPool.DISCOVERY.value] == 1
    assert pools.metrics.cancelled_pool_waiters == 1


def test_metrics_expose_wait_starvation_and_fairness_surfaces() -> None:
    metrics = ProofCriticalWorkloadScheduler().metrics
    metrics.wait_samples_by_class[WorkloadClass.FINALIZATION.value].extend(
        [0.1, 0.2, 0.3]
    )
    metrics.max_starvation_seconds_by_class[WorkloadClass.FINALIZATION.value] = 0.3
    metrics.dispatched_by_strategy["a"] = 3
    metrics.dispatched_by_strategy["b"] = 1
    snapshot = metrics.snapshot()
    assert snapshot["wait_seconds"][WorkloadClass.FINALIZATION.value]["p95"] == 0.3
    assert snapshot["max_starvation_seconds"][WorkloadClass.FINALIZATION.value] == 0.3
    assert snapshot["fairness_share"] == {"a": 0.75, "b": 0.25}
