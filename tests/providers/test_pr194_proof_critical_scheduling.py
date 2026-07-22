from __future__ import annotations

import asyncio

import pytest

from src.providers.jupiter.quota import JupiterQuotaManager, JupiterQuotaPurpose
from src.providers.jupiter.scheduler import (
    JupiterAttemptContext,
    JupiterAttemptRole,
    JupiterAttemptSchedulerConfig,
    JupiterAttemptStopReason,
    JupiterRouteAttemptScheduler,
    JupiterSafetyEnvelope,
)
from src.scheduling.proof_critical import (
    AdmissionDecision,
    AsyncFairWorkloadBroker,
    BoundedFairWorkloadScheduler,
    FairWorkloadPolicy,
    ResourcePool,
    WorkItem,
    WorkloadClass,
)


def _envelope() -> JupiterSafetyEnvelope:
    return JupiterSafetyEnvelope(
        max_slippage_bps=50,
        max_price_impact_bps=100,
        min_net_profit_base_units=1,
    )


def _context() -> JupiterAttemptContext:
    return JupiterAttemptContext(
        trace_id="pr194",
        request_fingerprint="SOL/USDC/1000",
        now=1.0,
        deadline_at=5.0,
        estimated_edge_bps=20,
        min_edge_bps=10,
    )


@pytest.mark.asyncio
async def test_discovery_capacity_does_not_block_finalization_plan() -> None:
    now = [0.0]
    quota = JupiterQuotaManager(
        limit=10,
        window_seconds=60,
        finalization_reserve=2,
        clock=lambda: now[0],
    )
    for index in range(8):
        token = await quota.reserve(
            JupiterQuotaPurpose.DISCOVERY,
            request_fingerprint=f"discovery-{index}",
        )
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
    plan = scheduler.plan(_context())

    assert plan.stop_reason is JupiterAttemptStopReason.READY
    assert [attempt.profile.role for attempt in plan.attempts] == [
        JupiterAttemptRole.FINALIZATION
    ]
    assert all(
        skipped.purpose
        in {JupiterQuotaPurpose.DISCOVERY, JupiterQuotaPurpose.REFINEMENT}
        for skipped in plan.skipped_profiles
    )
    assert quota.can_reserve(JupiterQuotaPurpose.FINALIZATION) is True
    assert quota.can_reserve(JupiterQuotaPurpose.DISCOVERY) is False


def test_finalization_profile_is_inside_max_attempts_and_invalid_config_fails() -> None:
    scheduler = JupiterRouteAttemptScheduler(
        JupiterAttemptSchedulerConfig(
            account_budget_steps=(64, 60, 56, 52, 50),
            reserve_finalization_profiles=2,
            max_attempts=3,
        ),
        _envelope(),
    )
    profiles = scheduler.profiles()
    assert len(profiles) == 3
    assert [profile.role for profile in profiles[-2:]] == [
        JupiterAttemptRole.FINALIZATION,
        JupiterAttemptRole.FINALIZATION,
    ]

    with pytest.raises(ValueError, match="at least one finalization"):
        JupiterRouteAttemptScheduler(
            JupiterAttemptSchedulerConfig(
                reserve_finalization_profiles=0,
                max_attempts=3,
            ),
            _envelope(),
        )
    with pytest.raises(ValueError, match="cannot exceed max_attempts"):
        JupiterRouteAttemptScheduler(
            JupiterAttemptSchedulerConfig(
                reserve_finalization_profiles=4,
                max_attempts=3,
            ),
            _envelope(),
        )


def _work(
    work_id: str,
    workload_class: WorkloadClass,
    strategy: str,
    *,
    now: float = 0.0,
    deadline: float = 100.0,
    duration: float = 1.0,
    required: bool = False,
    priority: float = 0.0,
) -> WorkItem:
    return WorkItem(
        work_id=work_id,
        workload_class=workload_class,
        strategy_id=strategy,
        provider_id="jupiter",
        enqueued_at=now,
        deadline_at=deadline,
        estimated_duration_seconds=duration,
        required=required,
        base_priority=priority,
    )


def _policy() -> FairWorkloadPolicy:
    return FairWorkloadPolicy(
        max_pending=12,
        critical_reserve=3,
        required_reserve=2,
        per_strategy_cap=3,
        max_inflight_by_pool={
            ResourcePool.DISCOVERY: 1,
            ResourcePool.FINALIZATION: 1,
            ResourcePool.SETTLEMENT: 1,
        },
    )


def test_noisy_optional_strategy_cannot_consume_required_or_critical_reserve() -> None:
    scheduler = BoundedFairWorkloadScheduler(_policy(), clock=lambda: 0.0)

    decisions = [
        scheduler.submit(
            _work(f"noise-{index}", WorkloadClass.OPTIONAL_DISCOVERY, "noisy")
        )
        for index in range(8)
    ]
    assert sum(decision.accepted for decision in decisions) == 3
    assert any(
        decision.decision is AdmissionDecision.STRATEGY_CAP for decision in decisions
    )

    required = scheduler.submit(
        _work(
            "required",
            WorkloadClass.REQUIRED_DISCOVERY,
            "quiet-required",
            required=True,
        )
    )
    finalization = scheduler.submit(
        _work("finalize", WorkloadClass.FINALIZATION, "proof-owner")
    )
    settlement = scheduler.submit(
        _work("settle", WorkloadClass.SETTLEMENT_STATUS, "proof-owner")
    )
    assert required.accepted
    assert finalization.accepted
    assert settlement.accepted

    discovery_lease = scheduler.dispatch(ResourcePool.DISCOVERY, now=5.0)
    assert discovery_lease is not None
    assert discovery_lease.work_id == "required"

    # Dedicated pools remain dispatchable while discovery's only worker is busy.
    final_lease = scheduler.dispatch(ResourcePool.FINALIZATION, now=5.0)
    settlement_lease = scheduler.dispatch(ResourcePool.SETTLEMENT, now=5.0)
    assert final_lease is not None and final_lease.work_id == "finalize"
    assert settlement_lease is not None and settlement_lease.work_id == "settle"


def test_deadline_feasibility_cancellation_and_metrics_are_fail_closed() -> None:
    now = [10.0]
    scheduler = BoundedFairWorkloadScheduler(_policy(), clock=lambda: now[0])

    expired = scheduler.submit(
        _work(
            "expired",
            WorkloadClass.FINALIZATION,
            "proof",
            now=0.0,
            deadline=5.0,
        )
    )
    impossible = scheduler.submit(
        _work(
            "impossible",
            WorkloadClass.FINALIZATION,
            "proof",
            now=10.0,
            deadline=11.0,
            duration=2.0,
        )
    )
    assert expired.decision is AdmissionDecision.EXPIRED
    assert impossible.decision is AdmissionDecision.DEADLINE_INFEASIBLE

    assert scheduler.submit(
        _work(
            "cancel-pending",
            WorkloadClass.FINALIZATION,
            "proof",
            now=10.0,
            deadline=20.0,
        )
    ).accepted
    assert scheduler.cancel("cancel-pending") is True
    assert scheduler.pending_ids(ResourcePool.FINALIZATION) == ()

    assert scheduler.submit(
        _work(
            "cancel-inflight",
            WorkloadClass.FINALIZATION,
            "proof",
            now=10.0,
            deadline=20.0,
        )
    ).accepted
    lease = scheduler.dispatch(ResourcePool.FINALIZATION, now=10.0)
    assert lease is not None
    assert scheduler.inflight(ResourcePool.FINALIZATION) == 1
    assert scheduler.cancel("cancel-inflight") is True
    assert scheduler.inflight(ResourcePool.FINALIZATION) == 0

    metrics = scheduler.snapshot()
    assert metrics["expired"] == 1
    assert metrics["deadline_infeasible"] == 1
    inflight_by_pool = metrics["inflight_by_pool"]
    assert isinstance(inflight_by_pool, dict)
    assert inflight_by_pool["finalization"] == 0


def test_recorded_workload_order_is_deterministic_and_fair() -> None:
    def run() -> list[str]:
        scheduler = BoundedFairWorkloadScheduler(_policy(), clock=lambda: 0.0)
        for index in range(3):
            assert scheduler.submit(
                _work(
                    f"a-{index}",
                    WorkloadClass.OPTIONAL_DISCOVERY,
                    "strategy-a",
                    priority=100.0,
                )
            ).accepted
            assert scheduler.submit(
                _work(
                    f"b-{index}",
                    WorkloadClass.OPTIONAL_DISCOVERY,
                    "strategy-b",
                )
            ).accepted
        order: list[str] = []
        for step in range(6):
            lease = scheduler.dispatch(ResourcePool.DISCOVERY, now=float(step + 1))
            assert lease is not None
            order.append(lease.work_id)
            assert scheduler.complete(lease.work_id)
        shares = scheduler.snapshot()["fairness_share"]
        assert isinstance(shares, dict)
        assert shares["strategy-a"] == pytest.approx(0.5)
        assert shares["strategy-b"] == pytest.approx(0.5)
        return order

    assert run() == run()


@pytest.mark.asyncio
async def test_cancelled_async_waiter_does_not_leak_pool_or_work() -> None:
    scheduler = BoundedFairWorkloadScheduler(_policy())
    broker = AsyncFairWorkloadBroker(scheduler)
    waiter = asyncio.create_task(broker.acquire(ResourcePool.SETTLEMENT))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert scheduler.inflight(ResourcePool.SETTLEMENT) == 0
    assert scheduler.qsize() == 0
    assert scheduler.metrics.waiter_cancellations == 1
