from __future__ import annotations

import pytest

from src.strategy.conflict_scheduler import (
    ConflictAwareScheduler,
    ReservationReceipt,
    ScheduledIntent,
    SchedulerRejectReason,
    StaleWorkerFence,
    WorkerFence,
    WorkResourceSet,
)


class FakeReservationPort:
    def __init__(self) -> None:
        self.active: dict[str, ReservationReceipt] = {}
        self.releases: list[tuple[str, str]] = []
        self.deny: set[str] = set()

    def reserve(self, intent: ScheduledIntent) -> ReservationReceipt | None:
        if intent.work_id in self.deny:
            return None
        receipt = ReservationReceipt(
            reservation_id=f"reservation:{intent.work_id}",
            work_id=intent.work_id,
            generation=intent.worker_fence.generation,
            canonical_owner="test-canonical-owner",
            capital_reservation_id=f"capital:{intent.work_id}",
            quota_reservation_ids=(f"quota:{intent.strategy_id}",),
        )
        self.active[intent.work_id] = receipt
        return receipt

    def release(self, receipt: ReservationReceipt, *, reason: str) -> None:
        self.releases.append((receipt.work_id, reason))
        self.active.pop(receipt.work_id, None)


def _fence(owner: str = "worker-a", generation: int = 1) -> WorkerFence:
    return WorkerFence(owner, generation, generation, 10_000)


def _intent(
    work_id: str,
    *,
    pools: tuple[str, ...] = (),
    economic: tuple[str, ...] = (),
    fee_payer: str | None = None,
    fence: WorkerFence | None = None,
) -> ScheduledIntent:
    return ScheduledIntent(
        work_id=work_id,
        strategy_id="circular",
        deadline_ns=9_000,
        resources=WorkResourceSet(
            pools=pools,
            economic_resources=economic,
            fee_payer=fee_payer,
        ),
        worker_fence=fence or _fence(),
        state_generation="frame-1",
    )


def test_shared_pool_conflicts_even_with_different_workers() -> None:
    port = FakeReservationPort()
    scheduler = ConflictAwareScheduler(
        reservation_port=port,
        max_in_flight=4,
        clock_ns=lambda: 100,
        lease_clock_ns=lambda: 100,
    )
    first = scheduler.admit(_intent("a", pools=("pool-x",)))
    second = scheduler.admit(
        _intent(
            "b",
            pools=("pool-x",),
            fence=_fence("worker-b", 2),
        )
    )
    assert first.admitted is True
    assert second.reason is SchedulerRejectReason.RESOURCE_CONFLICT
    assert second.conflicting_work_ids == ("a",)


def test_slumlord_pda_is_one_shared_economic_resource() -> None:
    port = FakeReservationPort()
    scheduler = ConflictAwareScheduler(
        reservation_port=port,
        max_in_flight=4,
        clock_ns=lambda: 100,
        lease_clock_ns=lambda: 100,
    )
    assert scheduler.admit(_intent("a", economic=("slumlord:pda",))).admitted
    decision = scheduler.admit(
        _intent(
            "b",
            economic=("slumlord:pda",),
            fence=_fence("worker-b", 2),
        )
    )
    assert decision.reason is SchedulerRejectReason.RESOURCE_CONFLICT


def test_backpressure_and_duplicate_are_explicit() -> None:
    port = FakeReservationPort()
    scheduler = ConflictAwareScheduler(
        reservation_port=port,
        max_in_flight=1,
        clock_ns=lambda: 100,
        lease_clock_ns=lambda: 100,
    )
    assert scheduler.admit(_intent("a")).admitted
    duplicate = scheduler.admit(_intent("a"))
    assert duplicate.reason is SchedulerRejectReason.DUPLICATE_WORK
    saturated = scheduler.admit(_intent("b", fence=_fence("worker-b", 2)))
    assert saturated.reason is SchedulerRejectReason.BACKPRESSURE
    snapshot = scheduler.snapshot()
    assert snapshot.rejected_duplicate == 1
    assert snapshot.rejected_backpressure == 1


def test_reservation_denial_never_becomes_active() -> None:
    port = FakeReservationPort()
    port.deny.add("a")
    scheduler = ConflictAwareScheduler(
        reservation_port=port,
        max_in_flight=2,
        clock_ns=lambda: 100,
        lease_clock_ns=lambda: 100,
    )
    decision = scheduler.admit(_intent("a"))
    assert decision.reason is SchedulerRejectReason.RESERVATION_DENIED
    assert scheduler.snapshot().active_work_ids == ()


def test_expired_worker_fence_is_rejected() -> None:
    port = FakeReservationPort()
    scheduler = ConflictAwareScheduler(
        reservation_port=port,
        max_in_flight=2,
        clock_ns=lambda: 100,
        lease_clock_ns=lambda: 500,
    )
    fence = WorkerFence("old-worker", 1, 1, 499)
    decision = scheduler.admit(_intent("a", fence=fence))
    assert decision.reason is SchedulerRejectReason.STALE_WORKER_FENCE


def test_zombie_worker_cannot_complete_newer_fence() -> None:
    port = FakeReservationPort()
    scheduler = ConflictAwareScheduler(
        reservation_port=port,
        max_in_flight=2,
        clock_ns=lambda: 100,
        lease_clock_ns=lambda: 100,
    )
    current = _fence("worker-a", 2)
    assert scheduler.admit(_intent("a", fence=current)).admitted
    stale = WorkerFence("worker-a", 1, 1, 10_000)
    with pytest.raises(StaleWorkerFence):
        scheduler.complete("a", worker_fence=stale)


def test_completion_releases_canonical_reservation_before_reuse() -> None:
    port = FakeReservationPort()
    scheduler = ConflictAwareScheduler(
        reservation_port=port,
        max_in_flight=2,
        clock_ns=lambda: 100,
        lease_clock_ns=lambda: 100,
    )
    fence = _fence()
    assert scheduler.admit(_intent("a", pools=("pool-x",), fence=fence)).admitted
    assert scheduler.complete("a", worker_fence=fence)
    assert port.releases == [("a", "completed")]
    assert scheduler.admit(
        _intent(
            "b",
            pools=("pool-x",),
            fence=_fence("worker-b", 2),
        )
    ).admitted


def test_route_footprint_adapter_reuses_existing_shape() -> None:
    class Footprint:
        pools = ("pool-a",)
        writable_accounts = ("account-a",)

    result = WorkResourceSet.from_route_footprint(
        Footprint(),
        economic_resources=("reserve-a",),
        fee_payer="payer-a",
    )
    assert result.pools == ("pool-a",)
    assert result.writable_accounts == ("account-a",)
    assert result.economic_resources == ("reserve-a",)


def test_completion_after_deadline_is_released_as_expired() -> None:
    port = FakeReservationPort()
    deadline_now = [100]
    scheduler = ConflictAwareScheduler(
        reservation_port=port,
        max_in_flight=2,
        clock_ns=lambda: deadline_now[0],
        lease_clock_ns=lambda: 100,
    )
    fence = _fence()
    assert scheduler.admit(_intent("a", fence=fence)).admitted
    deadline_now[0] = 9_001

    assert scheduler.complete("a", worker_fence=fence) is False
    assert port.releases == [("a", SchedulerRejectReason.DEADLINE_EXPIRED.value)]
    assert scheduler.snapshot().active_work_ids == ()


def test_durable_lease_expiry_uses_wall_clock_not_deadline_clock() -> None:
    port = FakeReservationPort()
    scheduler = ConflictAwareScheduler(
        reservation_port=port,
        max_in_flight=2,
        clock_ns=lambda: 100,
        lease_clock_ns=lambda: 20_000,
    )
    fence = WorkerFence("worker-a", 1, 1, 10_000)

    decision = scheduler.admit(_intent("a", fence=fence))

    assert decision.reason is SchedulerRejectReason.STALE_WORKER_FENCE
