"""PR-194 deterministic fair scheduling for proof-critical workloads.

The scheduler separates discovery, finalization and settlement resource pools,
reserves bounded queue capacity for required/critical work, applies weighted fair
finish tags across strategy/provider lanes, and adds deterministic aging and
explicit deadline feasibility checks. It never executes provider or trading work;
it only owns admission and dispatch order.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Mapping


PR194_SCHEDULER_SCHEMA = "pr194.proof-critical-scheduler.v1"


class WorkloadClass(StrEnum):
    OPTIONAL_DISCOVERY = "optional_discovery"
    REQUIRED_DISCOVERY = "required_discovery"
    REFINEMENT = "refinement"
    FINALIZATION = "finalization"
    SETTLEMENT_STATUS = "settlement_status"
    EMERGENCY_RECONCILIATION = "emergency_reconciliation"

    @property
    def is_critical(self) -> bool:
        return self in {
            WorkloadClass.FINALIZATION,
            WorkloadClass.SETTLEMENT_STATUS,
            WorkloadClass.EMERGENCY_RECONCILIATION,
        }

    @property
    def is_required(self) -> bool:
        return self is not WorkloadClass.OPTIONAL_DISCOVERY


class ResourcePool(StrEnum):
    DISCOVERY = "discovery"
    FINALIZATION = "finalization"
    SETTLEMENT = "settlement"


class AdmissionDecision(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    CAPACITY = "capacity"
    STRATEGY_CAP = "strategy_cap"
    EXPIRED = "expired"
    DEADLINE_INFEASIBLE = "deadline_infeasible"


@dataclass(frozen=True, slots=True)
class WorkItem:
    work_id: str
    workload_class: WorkloadClass
    strategy_id: str
    provider_id: str
    enqueued_at: float
    deadline_at: float
    estimated_duration_seconds: float
    cost_units: int = 1
    base_priority: float = 0.0
    required: bool = False

    def __post_init__(self) -> None:
        if not self.work_id.strip():
            raise ValueError("work_id is required")
        if not self.strategy_id.strip() or not self.provider_id.strip():
            raise ValueError("strategy_id and provider_id are required")
        if not math.isfinite(self.enqueued_at) or not math.isfinite(self.deadline_at):
            raise ValueError("work timestamps must be finite")
        if self.deadline_at <= self.enqueued_at:
            raise ValueError("deadline_at must be after enqueued_at")
        if (
            not math.isfinite(self.estimated_duration_seconds)
            or self.estimated_duration_seconds < 0
        ):
            raise ValueError("estimated_duration_seconds must be finite and non-negative")
        if isinstance(self.cost_units, bool) or self.cost_units <= 0:
            raise ValueError("cost_units must be positive")
        if not math.isfinite(self.base_priority):
            raise ValueError("base_priority must be finite")

    @property
    def effective_required(self) -> bool:
        return self.required or self.workload_class.is_required

    @property
    def resource_pool(self) -> ResourcePool:
        if self.workload_class is WorkloadClass.FINALIZATION:
            return ResourcePool.FINALIZATION
        if self.workload_class in {
            WorkloadClass.SETTLEMENT_STATUS,
            WorkloadClass.EMERGENCY_RECONCILIATION,
        }:
            return ResourcePool.SETTLEMENT
        return ResourcePool.DISCOVERY


@dataclass(frozen=True, slots=True)
class WorkAdmission:
    decision: AdmissionDecision
    work_id: str
    detail: str

    @property
    def accepted(self) -> bool:
        return self.decision is AdmissionDecision.ACCEPTED


@dataclass(frozen=True, slots=True)
class WorkLease:
    work_id: str
    workload_class: WorkloadClass
    strategy_id: str
    provider_id: str
    resource_pool: ResourcePool
    dispatched_at: float
    deadline_at: float
    wait_seconds: float
    scheduler_generation: int


@dataclass(frozen=True)
class FairWorkloadPolicy:
    max_pending: int = 128
    critical_reserve: int = 16
    required_reserve: int = 16
    per_strategy_cap: int = 16
    aging_boost_per_second: float = 0.25
    required_boost: float = 50.0
    class_weights: Mapping[WorkloadClass, float] = field(
        default_factory=lambda: {
            WorkloadClass.OPTIONAL_DISCOVERY: 1.0,
            WorkloadClass.REQUIRED_DISCOVERY: 2.0,
            WorkloadClass.REFINEMENT: 1.5,
            WorkloadClass.FINALIZATION: 8.0,
            WorkloadClass.SETTLEMENT_STATUS: 10.0,
            WorkloadClass.EMERGENCY_RECONCILIATION: 12.0,
        }
    )
    max_inflight_by_pool: Mapping[ResourcePool, int] = field(
        default_factory=lambda: {
            ResourcePool.DISCOVERY: 8,
            ResourcePool.FINALIZATION: 2,
            ResourcePool.SETTLEMENT: 2,
        }
    )

    def validate(self) -> None:
        if self.max_pending <= 0:
            raise ValueError("max_pending must be positive")
        if self.critical_reserve < 0 or self.required_reserve < 0:
            raise ValueError("queue reserves must be non-negative")
        if self.critical_reserve + self.required_reserve >= self.max_pending:
            raise ValueError("queue reserves must leave optional capacity")
        if self.per_strategy_cap <= 0:
            raise ValueError("per_strategy_cap must be positive")
        if self.aging_boost_per_second < 0 or self.required_boost < 0:
            raise ValueError("aging and required boosts must be non-negative")
        for workload_class in WorkloadClass:
            weight = self.class_weights.get(workload_class)
            if weight is None or not math.isfinite(weight) or weight <= 0:
                raise ValueError(f"missing positive weight for {workload_class.value}")
        for pool in ResourcePool:
            capacity = self.max_inflight_by_pool.get(pool)
            if capacity is None or capacity <= 0:
                raise ValueError(f"missing positive inflight capacity for {pool.value}")


@dataclass(slots=True)
class FairWorkloadMetrics:
    submitted: int = 0
    accepted: int = 0
    dispatched: int = 0
    completed: int = 0
    cancelled_pending: int = 0
    cancelled_inflight: int = 0
    waiter_cancellations: int = 0
    expired: int = 0
    deadline_infeasible: int = 0
    capacity_rejections: int = 0
    strategy_cap_rejections: int = 0
    critical_path_denials: int = 0
    wait_seconds_by_class: dict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )
    dispatched_by_strategy: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )


@dataclass(slots=True)
class _QueuedWork:
    item: WorkItem
    sequence: int
    start_tag: float
    finish_tag: float


class BoundedFairWorkloadScheduler:
    """Deterministic bounded weighted-fair scheduler with isolated pools."""

    def __init__(
        self,
        policy: FairWorkloadPolicy | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        generation: int = 1,
    ) -> None:
        self.policy = policy or FairWorkloadPolicy()
        self.policy.validate()
        if generation <= 0:
            raise ValueError("generation must be positive")
        self.clock = clock
        self.generation = generation
        self.metrics = FairWorkloadMetrics()
        self._pending: list[_QueuedWork] = []
        self._pending_by_id: dict[str, _QueuedWork] = {}
        self._pending_by_strategy: dict[str, int] = defaultdict(int)
        self._inflight: dict[str, WorkLease] = {}
        self._inflight_by_pool: dict[ResourcePool, int] = defaultdict(int)
        self._lane_finish: dict[tuple[str, str, str], float] = defaultdict(float)
        self._virtual_time = 0.0
        self._sequence = 0

    def qsize(self) -> int:
        return len(self._pending)

    def inflight(self, pool: ResourcePool | None = None) -> int:
        if pool is None:
            return len(self._inflight)
        return self._inflight_by_pool[pool]

    def _admission_limit(self, item: WorkItem) -> int:
        if item.workload_class.is_critical:
            return self.policy.max_pending
        if item.effective_required:
            return self.policy.max_pending - self.policy.critical_reserve
        return (
            self.policy.max_pending
            - self.policy.critical_reserve
            - self.policy.required_reserve
        )

    def _is_feasible(self, item: WorkItem, now: float) -> bool:
        return now + item.estimated_duration_seconds <= item.deadline_at

    def submit(self, item: WorkItem, *, now: float | None = None) -> WorkAdmission:
        """Admit work without allowing optional traffic to consume reserves."""

        current = self.clock() if now is None else now
        self.metrics.submitted += 1
        if item.work_id in self._pending_by_id or item.work_id in self._inflight:
            return WorkAdmission(AdmissionDecision.DUPLICATE, item.work_id, "duplicate")
        if current >= item.deadline_at:
            self.metrics.expired += 1
            return WorkAdmission(AdmissionDecision.EXPIRED, item.work_id, "expired")
        if not self._is_feasible(item, current):
            self.metrics.deadline_infeasible += 1
            return WorkAdmission(
                AdmissionDecision.DEADLINE_INFEASIBLE,
                item.work_id,
                "cannot finish before deadline",
            )
        if self.qsize() >= self._admission_limit(item):
            self.metrics.capacity_rejections += 1
            if item.workload_class.is_critical:
                self.metrics.critical_path_denials += 1
            return WorkAdmission(
                AdmissionDecision.CAPACITY,
                item.work_id,
                "purpose-specific pending capacity exhausted",
            )
        strategy_pending = self._pending_by_strategy[item.strategy_id]
        strategy_limit = self.policy.per_strategy_cap
        if item.effective_required:
            strategy_limit += self.policy.required_reserve
        if strategy_pending >= strategy_limit:
            self.metrics.strategy_cap_rejections += 1
            return WorkAdmission(
                AdmissionDecision.STRATEGY_CAP,
                item.work_id,
                "per-strategy pending cap exhausted",
            )

        lane = (
            item.workload_class.value,
            item.strategy_id,
            item.provider_id,
        )
        weight = self.policy.class_weights[item.workload_class]
        start_tag = max(self._virtual_time, self._lane_finish[lane])
        finish_tag = start_tag + (item.cost_units / weight)
        self._lane_finish[lane] = finish_tag
        queued = _QueuedWork(
            item=item,
            sequence=self._sequence,
            start_tag=start_tag,
            finish_tag=finish_tag,
        )
        self._sequence += 1
        self._pending.append(queued)
        self._pending_by_id[item.work_id] = queued
        self._pending_by_strategy[item.strategy_id] += 1
        self.metrics.accepted += 1
        return WorkAdmission(AdmissionDecision.ACCEPTED, item.work_id, "accepted")

    def _remove_pending(self, queued: _QueuedWork) -> None:
        self._pending.remove(queued)
        self._pending_by_id.pop(queued.item.work_id, None)
        remaining = self._pending_by_strategy[queued.item.strategy_id] - 1
        if remaining <= 0:
            self._pending_by_strategy.pop(queued.item.strategy_id, None)
        else:
            self._pending_by_strategy[queued.item.strategy_id] = remaining

    def _purge_unserviceable(self, now: float) -> None:
        for queued in tuple(self._pending):
            item = queued.item
            if now >= item.deadline_at:
                self._remove_pending(queued)
                self.metrics.expired += 1
            elif not self._is_feasible(item, now):
                self._remove_pending(queued)
                self.metrics.deadline_infeasible += 1

    def _dispatch_key(self, queued: _QueuedWork, now: float) -> tuple[float, float, int]:
        item = queued.item
        wait = max(0.0, now - item.enqueued_at)
        aging = self.policy.aging_boost_per_second * wait
        required = self.policy.required_boost if item.effective_required else 0.0
        remaining = max(1e-9, item.deadline_at - now)
        deadline_pressure = min(25.0, 1.0 / remaining)
        effective_finish = (
            queued.finish_tag
            - item.base_priority
            - aging
            - required
            - deadline_pressure
        )
        return (effective_finish, item.deadline_at, queued.sequence)

    def dispatch(
        self,
        pool: ResourcePool,
        *,
        now: float | None = None,
    ) -> WorkLease | None:
        """Dispatch one feasible item for a dedicated resource pool."""

        current = self.clock() if now is None else now
        self._purge_unserviceable(current)
        if self._inflight_by_pool[pool] >= self.policy.max_inflight_by_pool[pool]:
            return None
        candidates = [
            queued for queued in self._pending if queued.item.resource_pool is pool
        ]
        if not candidates:
            return None
        queued = min(candidates, key=lambda candidate: self._dispatch_key(candidate, current))
        self._remove_pending(queued)
        item = queued.item
        wait = max(0.0, current - item.enqueued_at)
        lease = WorkLease(
            work_id=item.work_id,
            workload_class=item.workload_class,
            strategy_id=item.strategy_id,
            provider_id=item.provider_id,
            resource_pool=pool,
            dispatched_at=current,
            deadline_at=item.deadline_at,
            wait_seconds=wait,
            scheduler_generation=self.generation,
        )
        self._inflight[item.work_id] = lease
        self._inflight_by_pool[pool] += 1
        self._virtual_time = max(self._virtual_time, queued.start_tag)
        self.metrics.dispatched += 1
        self.metrics.wait_seconds_by_class[item.workload_class.value].append(wait)
        self.metrics.dispatched_by_strategy[item.strategy_id] += 1
        return lease

    def complete(self, work_id: str) -> bool:
        lease = self._inflight.pop(work_id, None)
        if lease is None:
            return False
        self._inflight_by_pool[lease.resource_pool] -= 1
        self.metrics.completed += 1
        return True

    def cancel(self, work_id: str) -> bool:
        queued = self._pending_by_id.get(work_id)
        if queued is not None:
            self._remove_pending(queued)
            self.metrics.cancelled_pending += 1
            return True
        lease = self._inflight.pop(work_id, None)
        if lease is not None:
            self._inflight_by_pool[lease.resource_pool] -= 1
            self.metrics.cancelled_inflight += 1
            return True
        return False

    def pending_ids(self, pool: ResourcePool | None = None) -> tuple[str, ...]:
        queued = self._pending
        if pool is not None:
            queued = [item for item in queued if item.item.resource_pool is pool]
        return tuple(item.item.work_id for item in sorted(queued, key=lambda x: x.sequence))

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1)
        return ordered[index]

    def snapshot(self) -> dict[str, object]:
        wait = {
            workload_class: {
                "p50": self._percentile(values, 0.50),
                "p95": self._percentile(values, 0.95),
                "p99": self._percentile(values, 0.99),
                "max": max(values, default=0.0),
            }
            for workload_class, values in self.metrics.wait_seconds_by_class.items()
        }
        total_dispatched = max(1, self.metrics.dispatched)
        fairness_share = {
            strategy: count / total_dispatched
            for strategy, count in sorted(self.metrics.dispatched_by_strategy.items())
        }
        return {
            "schema_version": PR194_SCHEDULER_SCHEMA,
            "generation": self.generation,
            "pending": self.qsize(),
            "inflight": len(self._inflight),
            "submitted": self.metrics.submitted,
            "accepted": self.metrics.accepted,
            "dispatched": self.metrics.dispatched,
            "completed": self.metrics.completed,
            "expired": self.metrics.expired,
            "deadline_infeasible": self.metrics.deadline_infeasible,
            "capacity_rejections": self.metrics.capacity_rejections,
            "strategy_cap_rejections": self.metrics.strategy_cap_rejections,
            "critical_path_denials": self.metrics.critical_path_denials,
            "wait_seconds": wait,
            "fairness_share": fairness_share,
            "inflight_by_pool": {
                pool.value: self._inflight_by_pool[pool] for pool in ResourcePool
            },
        }


class AsyncFairWorkloadBroker:
    """Cancellation-safe async waiter facade over the deterministic scheduler."""

    def __init__(self, scheduler: BoundedFairWorkloadScheduler) -> None:
        self.scheduler = scheduler
        self._condition = asyncio.Condition()

    async def submit(self, item: WorkItem) -> WorkAdmission:
        async with self._condition:
            admission = self.scheduler.submit(item)
            if admission.accepted:
                self._condition.notify_all()
            return admission

    async def acquire(
        self,
        pool: ResourcePool,
        *,
        timeout: float | None = None,
    ) -> WorkLease:
        async with self._condition:
            try:
                if timeout is None:
                    while True:
                        lease = self.scheduler.dispatch(pool)
                        if lease is not None:
                            return lease
                        await self._condition.wait()
                async with asyncio.timeout(timeout):
                    while True:
                        lease = self.scheduler.dispatch(pool)
                        if lease is not None:
                            return lease
                        await self._condition.wait()
            except asyncio.CancelledError:
                self.scheduler.metrics.waiter_cancellations += 1
                raise

    async def complete(self, work_id: str) -> bool:
        async with self._condition:
            completed = self.scheduler.complete(work_id)
            if completed:
                self._condition.notify_all()
            return completed

    async def cancel(self, work_id: str) -> bool:
        async with self._condition:
            cancelled = self.scheduler.cancel(work_id)
            if cancelled:
                self._condition.notify_all()
            return cancelled
