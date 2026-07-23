"""PR-194 bounded fair scheduling and proof-critical worker isolation."""

from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import AsyncIterator, Callable, Mapping


class WorkloadClass(StrEnum):
    OPTIONAL_DISCOVERY = "optional_discovery"
    REQUIRED_DISCOVERY = "required_discovery"
    REFINEMENT = "refinement"
    FINALIZATION = "finalization"
    SETTLEMENT_STATUS = "settlement_status"
    EMERGENCY_RECONCILIATION = "emergency_reconciliation"


class WorkPool(StrEnum):
    DISCOVERY = "discovery"
    FINALIZATION = "finalization"
    SETTLEMENT = "settlement"


_POOL_BY_CLASS: Mapping[WorkloadClass, WorkPool] = {
    WorkloadClass.OPTIONAL_DISCOVERY: WorkPool.DISCOVERY,
    WorkloadClass.REQUIRED_DISCOVERY: WorkPool.DISCOVERY,
    WorkloadClass.REFINEMENT: WorkPool.DISCOVERY,
    WorkloadClass.FINALIZATION: WorkPool.FINALIZATION,
    WorkloadClass.SETTLEMENT_STATUS: WorkPool.SETTLEMENT,
    WorkloadClass.EMERGENCY_RECONCILIATION: WorkPool.SETTLEMENT,
}
_CLASS_RANK: Mapping[WorkloadClass, int] = {
    WorkloadClass.EMERGENCY_RECONCILIATION: 0,
    WorkloadClass.SETTLEMENT_STATUS: 1,
    WorkloadClass.FINALIZATION: 2,
    WorkloadClass.REQUIRED_DISCOVERY: 3,
    WorkloadClass.REFINEMENT: 4,
    WorkloadClass.OPTIONAL_DISCOVERY: 5,
}
_REQUIRED_CLASSES = frozenset(
    {
        WorkloadClass.REQUIRED_DISCOVERY,
        WorkloadClass.FINALIZATION,
        WorkloadClass.SETTLEMENT_STATUS,
        WorkloadClass.EMERGENCY_RECONCILIATION,
    }
)


class WorkloadDeadlineExceeded(RuntimeError):
    """Work could not enter its isolated pool before the deadline."""


@dataclass(frozen=True, slots=True)
class ScheduledWork:
    work_id: str
    strategy_id: str
    provider_id: str
    workload_class: WorkloadClass
    enqueued_at: float
    deadline_at: float
    estimated_cost_seconds: float
    base_priority: float = 0.0
    required: bool = False

    def __post_init__(self) -> None:
        if not self.work_id or not self.strategy_id or not self.provider_id:
            raise ValueError("work, strategy and provider IDs are required")
        values = (
            self.enqueued_at,
            self.deadline_at,
            self.estimated_cost_seconds,
            self.base_priority,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("work timing, cost and priority must be finite")
        if self.deadline_at <= self.enqueued_at:
            raise ValueError("deadline_at must be after enqueued_at")
        if self.estimated_cost_seconds < 0:
            raise ValueError("estimated_cost_seconds must be non-negative")

    @property
    def pool(self) -> WorkPool:
        return _POOL_BY_CLASS[self.workload_class]

    @property
    def is_required(self) -> bool:
        return self.required or self.workload_class in _REQUIRED_CLASSES


@dataclass(frozen=True, slots=True)
class ProofCriticalSchedulerConfig:
    max_queue_size: int = 256
    max_per_strategy: int = 64
    max_per_provider: int = 128
    required_reserve: int = 32
    aging_per_second: float = 1.0
    urgency_window_seconds: float = 2.0
    starvation_slo_seconds: float = 1.0
    strategy_weights: Mapping[str, int] = field(default_factory=dict)
    pool_capacities: Mapping[WorkPool, int] = field(
        default_factory=lambda: {
            WorkPool.DISCOVERY: 4,
            WorkPool.FINALIZATION: 2,
            WorkPool.SETTLEMENT: 2,
        }
    )

    def __post_init__(self) -> None:
        if self.max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive")
        if self.max_per_strategy <= 0 or self.max_per_provider <= 0:
            raise ValueError("strategy/provider caps must be positive")
        if self.required_reserve < 0 or self.required_reserve >= self.max_queue_size:
            raise ValueError("required_reserve must be smaller than max_queue_size")
        if self.aging_per_second < 0 or self.urgency_window_seconds <= 0:
            raise ValueError("aging and urgency settings are invalid")
        if self.starvation_slo_seconds <= 0:
            raise ValueError("starvation_slo_seconds must be positive")
        if any(not key or value <= 0 for key, value in self.strategy_weights.items()):
            raise ValueError("strategy weights require IDs and positive values")
        if any(self.pool_capacities.get(pool, 0) <= 0 for pool in WorkPool):
            raise ValueError("every proof-critical pool needs positive capacity")


@dataclass(slots=True)
class ProofCriticalSchedulerMetrics:
    accepted: int = 0
    duplicates: int = 0
    rejected_full: int = 0
    rejected_strategy_cap: int = 0
    rejected_provider_cap: int = 0
    rejected_impossible: int = 0
    expired: int = 0
    evicted: int = 0
    critical_path_denials: int = 0
    deadline_misses: int = 0
    cancelled_pool_waiters: int = 0
    dispatched_by_strategy: defaultdict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    evicted_by_strategy: defaultdict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    wait_samples_by_class: defaultdict[str, list[float]] = field(
        default_factory=lambda: defaultdict(list)
    )
    max_starvation_seconds_by_class: defaultdict[str, float] = field(
        default_factory=lambda: defaultdict(float)
    )
    pool_active: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))

    def snapshot(self) -> dict[str, object]:
        waits = {
            key: {
                "p50": _percentile(values, 0.50),
                "p95": _percentile(values, 0.95),
                "p99": _percentile(values, 0.99),
            }
            for key, values in sorted(self.wait_samples_by_class.items())
        }
        total = sum(self.dispatched_by_strategy.values())
        fairness = {
            key: count / total if total else 0.0
            for key, count in sorted(self.dispatched_by_strategy.items())
        }
        return {
            "accepted": self.accepted,
            "duplicates": self.duplicates,
            "rejected_full": self.rejected_full,
            "rejected_strategy_cap": self.rejected_strategy_cap,
            "rejected_provider_cap": self.rejected_provider_cap,
            "rejected_impossible": self.rejected_impossible,
            "expired": self.expired,
            "evicted": self.evicted,
            "critical_path_denials": self.critical_path_denials,
            "deadline_misses": self.deadline_misses,
            "cancelled_pool_waiters": self.cancelled_pool_waiters,
            "dispatch_by_strategy": dict(self.dispatched_by_strategy),
            "evictions_by_strategy": dict(self.evicted_by_strategy),
            "wait_seconds": waits,
            "max_starvation_seconds": dict(self.max_starvation_seconds_by_class),
            "fairness_share": fairness,
            "pool_active": dict(self.pool_active),
        }


@dataclass(slots=True)
class _QueuedWork:
    work: ScheduledWork
    sequence: int


class ProofCriticalWorkloadScheduler:
    """Bounded weighted-fair queue with reserved service for required work."""

    def __init__(
        self,
        config: ProofCriticalSchedulerConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        metrics: ProofCriticalSchedulerMetrics | None = None,
    ) -> None:
        self.config = config or ProofCriticalSchedulerConfig()
        self.clock = clock
        self.metrics = metrics or ProofCriticalSchedulerMetrics()
        self._items: list[_QueuedWork] = []
        self._ids: set[str] = set()
        self._strategy_counts: defaultdict[str, int] = defaultdict(int)
        self._provider_counts: defaultdict[str, int] = defaultdict(int)
        self._dispatch_cost: defaultdict[str, float] = defaultdict(float)
        self._sequence = 0
        self._condition = asyncio.Condition()

    def qsize(self) -> int:
        return len(self._items)

    async def put(self, work: ScheduledWork) -> bool:
        async with self._condition:
            now = self.clock()
            self._expire_locked(now)
            if work.work_id in self._ids:
                self.metrics.duplicates += 1
                return False
            if work.deadline_at - now < work.estimated_cost_seconds:
                self.metrics.rejected_impossible += 1
                if work.is_required:
                    self.metrics.critical_path_denials += 1
                return False
            if self._strategy_counts[work.strategy_id] >= self.config.max_per_strategy:
                self.metrics.rejected_strategy_cap += 1
                return False
            if self._provider_counts[work.provider_id] >= self.config.max_per_provider:
                self.metrics.rejected_provider_cap += 1
                return False
            optional_limit = self.config.max_queue_size - self.config.required_reserve
            optional_count = sum(not item.work.is_required for item in self._items)
            if not work.is_required and optional_count >= optional_limit:
                self.metrics.rejected_full += 1
                return False
            if len(self._items) >= self.config.max_queue_size:
                if not work.is_required or not self._evict_optional_locked(now):
                    self.metrics.rejected_full += 1
                    if work.is_required:
                        self.metrics.critical_path_denials += 1
                    return False
            self._sequence += 1
            self._items.append(_QueuedWork(work, self._sequence))
            self._ids.add(work.work_id)
            self._strategy_counts[work.strategy_id] += 1
            self._provider_counts[work.provider_id] += 1
            self.metrics.accepted += 1
            self._condition.notify()
            return True

    async def get(self, pool: WorkPool | None = None) -> ScheduledWork:
        async with self._condition:
            while True:
                now = self.clock()
                self._expire_locked(now)
                candidates = [
                    item
                    for item in self._items
                    if pool is None or item.work.pool is pool
                ]
                if candidates:
                    selected = min(candidates, key=lambda item: self._key(item, now))
                    self._remove_locked(selected)
                    work = selected.work
                    wait = max(0.0, now - work.enqueued_at)
                    workload_class = work.workload_class.value
                    self.metrics.wait_samples_by_class[workload_class].append(wait)
                    previous_starvation = self.metrics.max_starvation_seconds_by_class[
                        workload_class
                    ]
                    self.metrics.max_starvation_seconds_by_class[workload_class] = max(
                        previous_starvation, wait
                    )
                    self.metrics.dispatched_by_strategy[work.strategy_id] += 1
                    self._dispatch_cost[work.strategy_id] += max(
                        work.estimated_cost_seconds, 0.001
                    )
                    return work
                await self._condition.wait()

    def _key(self, item: _QueuedWork, now: float) -> tuple[object, ...]:
        work = item.work
        weight = self.config.strategy_weights.get(work.strategy_id, 1)
        weighted_service = self._dispatch_cost[work.strategy_id] / weight
        age = max(0.0, now - work.enqueued_at)
        remaining = max(0.0, work.deadline_at - now)
        urgency = max(0.0, self.config.urgency_window_seconds - remaining)
        dynamic_priority = (
            work.base_priority
            + age * self.config.aging_per_second
            + urgency * self.config.aging_per_second
        )
        starved = age >= self.config.starvation_slo_seconds
        return (
            _CLASS_RANK[work.workload_class],
            not starved,
            weighted_service,
            work.strategy_id,
            -dynamic_priority,
            work.deadline_at,
            item.sequence,
        )

    def _evict_optional_locked(self, now: float) -> bool:
        optional = [item for item in self._items if not item.work.is_required]
        if not optional:
            return False
        victim = max(optional, key=lambda item: self._key(item, now))
        self._remove_locked(victim)
        self.metrics.evicted += 1
        self.metrics.evicted_by_strategy[victim.work.strategy_id] += 1
        return True

    def _expire_locked(self, now: float) -> None:
        expired = [
            item
            for item in self._items
            if item.work.deadline_at <= now
            or item.work.deadline_at - now < item.work.estimated_cost_seconds
        ]
        for item in expired:
            self._remove_locked(item)
            self.metrics.expired += 1
            if item.work.is_required:
                self.metrics.deadline_misses += 1

    def _remove_locked(self, item: _QueuedWork) -> None:
        self._items.remove(item)
        work = item.work
        self._ids.discard(work.work_id)
        self._strategy_counts[work.strategy_id] -= 1
        self._provider_counts[work.provider_id] -= 1


class IsolatedConcurrencyPools:
    """Independent concurrency pools for discovery, finalization and settlement."""

    def __init__(
        self,
        config: ProofCriticalSchedulerConfig | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        metrics: ProofCriticalSchedulerMetrics | None = None,
    ) -> None:
        self.config = config or ProofCriticalSchedulerConfig()
        self.clock = clock
        self.metrics = metrics or ProofCriticalSchedulerMetrics()
        self._semaphores = {
            pool: asyncio.Semaphore(self.config.pool_capacities[pool])
            for pool in WorkPool
        }

    @asynccontextmanager
    async def lease(
        self,
        work_or_pool: ScheduledWork | WorkPool,
        *,
        deadline_at: float | None = None,
    ) -> AsyncIterator[None]:
        if isinstance(work_or_pool, ScheduledWork):
            pool = work_or_pool.pool
            deadline = work_or_pool.deadline_at
            work_id = work_or_pool.work_id
            required = work_or_pool.is_required
        else:
            pool = WorkPool(work_or_pool)
            if deadline_at is None:
                raise ValueError("deadline_at is required when leasing by pool")
            deadline = deadline_at
            work_id = pool.value
            required = pool is not WorkPool.DISCOVERY
        semaphore = self._semaphores[pool]
        remaining = deadline - self.clock()
        if remaining <= 0:
            self.metrics.deadline_misses += 1
            raise WorkloadDeadlineExceeded(work_id)
        acquired = False
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=remaining)
            acquired = True
            self.metrics.pool_active[pool.value] += 1
            yield
        except asyncio.TimeoutError as exc:
            self.metrics.deadline_misses += 1
            if required:
                self.metrics.critical_path_denials += 1
            raise WorkloadDeadlineExceeded(work_id) from exc
        except asyncio.CancelledError:
            if not acquired:
                self.metrics.cancelled_pool_waiters += 1
            raise
        finally:
            if acquired:
                self.metrics.pool_active[pool.value] -= 1
                semaphore.release()


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1))
    return ordered[index]
