"""Bounded, lifecycle-aware opportunity queue with atomic expiry and leases."""
from __future__ import annotations

import asyncio
import heapq
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import StrEnum

from src.runtime.trusted_time import SystemTrustedTime, TrustedTime
from .domain import Opportunity
from .interfaces import OpportunityRanker
from .tracker import InMemoryOpportunityTracker, TrackerState


class QueueState(StrEnum):
    OPEN = "OPEN"
    QUIESCING = "QUIESCING"
    DRAINING = "DRAINING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class QueueAdmissionError(RuntimeError):
    def __init__(self, state: QueueState) -> None:
        self.state = state
        super().__init__(f"queue admission rejected: {state.value}")


class QueueClosed(RuntimeError): pass


@dataclass(frozen=True, slots=True)
class InFlightLease:
    item_id: str
    consumer_id: str
    generation: int
    acquired_monotonic_ns: int
    deadline_monotonic_ns: int
    retry_limit: int
    terminal_outcome: str | None = None


@dataclass(slots=True)
class StrategyQueueMetrics:
    detected: int = 0; enqueued: int = 0; duplicates: int = 0
    expired: int = 0; dropped: int = 0
    last_event: str | None = None; last_error: str | None = None


class OpportunityQueue:
    def __init__(self, maxsize: int, ranker: OpportunityRanker,
                 tracker: InMemoryOpportunityTracker | None = None, *,
                 clock: TrustedTime | None = None, lease_ns: int = 30_000_000_000) -> None:
        if isinstance(maxsize, bool) or not isinstance(maxsize, int) or maxsize <= 0:
            raise ValueError("opportunity queue maxsize must be positive")
        if isinstance(lease_ns, bool) or not isinstance(lease_ns, int) or lease_ns <= 0:
            raise ValueError("lease_ns must be a positive integer")
        self.maxsize, self.ranker, self.tracker = maxsize, ranker, tracker
        self.clock, self.lease_ns = clock or SystemTrustedTime(), lease_ns
        self._heap: list[tuple[float, float, int, str, Opportunity]] = []
        self._ids: set[str] = set(); self._leases: dict[str, InFlightLease] = {}
        self._retry_generations: dict[str, int] = {}; self._seq = 0
        self._cv = asyncio.Condition(); self.state = QueueState.OPEN
        self.metrics: defaultdict[str, StrategyQueueMetrics] = defaultdict(StrategyQueueMetrics)
        self.expiry_events: deque[tuple[str, str]] = deque(maxlen=maxsize)

    def qsize(self) -> int: return len(self._heap)
    @property
    def leases(self) -> tuple[InFlightLease, ...]: return tuple(self._leases.values())

    async def put(self, opportunity: Opportunity) -> bool:
        priority = await self.ranker.priority(opportunity)
        if isinstance(priority, bool) or not isinstance(priority, (int, float)) or not math.isfinite(priority):
            raise ValueError("opportunity priority must be finite")
        async with self._cv:
            if self.state is not QueueState.OPEN: raise QueueAdmissionError(self.state)
            await self._expire_locked()
            m = self.metrics[opportunity.strategy_name]; m.detected += 1; m.last_event = "detected"
            if opportunity.opportunity_id in self._ids or opportunity.opportunity_id in self._leases:
                m.duplicates += 1; m.last_event = "duplicate"; return False
            if self.tracker is not None and not await self.tracker.mark_pending(opportunity.opportunity_id):
                m.duplicates += 1; m.last_event = "duplicate_lifecycle"; return False
            item = (-float(priority), opportunity.expires_at, self._seq, opportunity.opportunity_id, opportunity); self._seq += 1
            if len(self._heap) >= self.maxsize:
                worst = max(self._heap, key=lambda x: (x[0], -x[2]))
                if item >= worst:
                    if self.tracker: await self.tracker.release_pending(opportunity.opportunity_id)
                    m.dropped += 1; m.last_event = "dropped"; return False
                self._heap.remove(worst); heapq.heapify(self._heap); self._ids.discard(worst[3])
                if self.tracker: await self.tracker.release_pending(worst[3])
                self.metrics[worst[4].strategy_name].dropped += 1
            heapq.heappush(self._heap, item); self._ids.add(opportunity.opportunity_id)
            m.enqueued += 1; m.last_event = "enqueued"; self._cv.notify_all(); return True

    async def get(self, *, consumer_id: str = "canonical-consumer") -> Opportunity:
        if not consumer_id.strip(): raise ValueError("consumer_id is required")
        async with self._cv:
            while True:
                await self._expire_locked()
                if self._heap:
                    _, _, _, oid, opp = heapq.heappop(self._heap); self._ids.discard(oid)
                    generation = self._retry_generations.pop(oid, 0) + 1
                    if self.tracker is not None and not await self.tracker.claim(oid, generation):
                        # The lifecycle authority must agree before ownership is handed off.
                        self.state = QueueState.FAILED
                        self._cv.notify_all()
                        raise RuntimeError("queue item could not be atomically claimed")
                    acquired = self.clock.snapshot().monotonic_ns
                    self._leases[oid] = InFlightLease(oid, consumer_id, generation, acquired, acquired + self.lease_ns, 2)
                    return opp
                if self.state in {QueueState.DRAINING, QueueState.CLOSED, QueueState.FAILED}: raise QueueClosed(self.state.value)
                await self._cv.wait()

    async def acknowledge(self, item_id: str, outcome: str) -> None:
        async with self._cv:
            lease = self._leases.pop(item_id, None)
            if lease is None: raise ValueError("item has no active lease")
            if self.tracker: await self.tracker.terminal(item_id)
            self._retry_generations.pop(item_id, None)
            self._cv.notify_all()

    async def recover(self, item: Opportunity, *, quarantine: bool = False) -> None:
        async with self._cv:
            lease = self._leases.pop(item.opportunity_id, None)
            if lease is None: raise ValueError("item has no active lease")
            if quarantine or lease.generation >= lease.retry_limit:
                if self.tracker: await self.tracker.terminal(item.opportunity_id, TrackerState.QUARANTINED)
            elif item.expires_at <= self.clock.snapshot().utc.timestamp():
                if self.tracker: await self.tracker.terminal(item.opportunity_id, TrackerState.EXPIRED)
            else:
                self._retry_generations[item.opportunity_id] = lease.generation
                heapq.heappush(self._heap, (0.0, item.expires_at, self._seq, item.opportunity_id, item)); self._seq += 1; self._ids.add(item.opportunity_id)
            self._cv.notify_all()

    async def expire(self) -> int:
        async with self._cv: return await self._expire_locked()

    async def _expire_locked(self) -> int:
        now = self.clock.snapshot().utc.timestamp(); keep = []; count = 0
        for item in self._heap:
            if item[1] <= now:
                count += 1; oid, opp = item[3], item[4]; self._ids.discard(oid)
                if self.tracker: await self.tracker.terminal(oid, TrackerState.EXPIRED)
                m = self.metrics[opp.strategy_name]; m.expired += 1; m.last_event = "expired"
                self.expiry_events.append((oid, "expired"))
            else: keep.append(item)
        if count: self._heap = keep; heapq.heapify(self._heap); self._cv.notify_all()
        return count

    async def quiesce(self) -> None:
        async with self._cv:
            if self.state is QueueState.OPEN: self.state = QueueState.QUIESCING
            self._cv.notify_all()

    async def close(self, *, deadline_monotonic_ns: int) -> tuple[str, ...]:
        async with self._cv:
            if self.state is QueueState.OPEN: self.state = QueueState.QUIESCING
            self.state = QueueState.DRAINING; self._cv.notify_all()
            while self._leases and self.clock.snapshot().monotonic_ns < deadline_monotonic_ns:
                remaining = (deadline_monotonic_ns - self.clock.snapshot().monotonic_ns) / 1_000_000_000
                try: await asyncio.wait_for(self._cv.wait(), max(0, remaining))
                except TimeoutError: break
            unresolved = tuple(sorted((*self._ids, *self._leases)))
            for _, _, _, oid, _ in self._heap:
                if self.tracker: await self.tracker.terminal(oid, TrackerState.QUARANTINED)
            self._heap.clear(); self._ids.clear()
            self._retry_generations.clear()
            self.state = QueueState.CLOSED if not self._leases else QueueState.FAILED
            self._cv.notify_all(); return unresolved
