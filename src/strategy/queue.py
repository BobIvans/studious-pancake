"""Bounded priority opportunity queue with expiry and metrics."""
from __future__ import annotations

import asyncio
import heapq
import math
import time
from collections import defaultdict
from dataclasses import dataclass

from .tracker import InMemoryOpportunityTracker
from .domain import Opportunity
from .interfaces import OpportunityRanker


@dataclass(slots=True)
class StrategyQueueMetrics:
    detected: int = 0
    enqueued: int = 0
    duplicates: int = 0
    expired: int = 0
    dropped: int = 0
    last_event: str | None = None
    last_error: str | None = None


class OpportunityQueue:
    def __init__(self, maxsize: int, ranker: OpportunityRanker, tracker: InMemoryOpportunityTracker | None = None) -> None:
        if maxsize <= 0:
            raise ValueError("opportunity queue maxsize must be positive")
        self.maxsize = maxsize
        self.ranker = ranker
        self.tracker = tracker
        self._heap: list[tuple[float, float, int, str, Opportunity]] = []
        self._ids: set[str] = set()
        self._seq = 0
        self._cv = asyncio.Condition()
        self.metrics: defaultdict[str, StrategyQueueMetrics] = defaultdict(StrategyQueueMetrics)

    def qsize(self) -> int:
        return len(self._heap)

    async def put(self, opportunity: Opportunity) -> bool:
        priority = await self.ranker.priority(opportunity)
        if not math.isfinite(priority):
            raise ValueError("opportunity priority must be finite")
        async with self._cv:
            self._expire_locked()
            m = self.metrics[opportunity.strategy_name]
            m.detected += 1; m.last_event = "detected"
            if opportunity.opportunity_id in self._ids:
                m.duplicates += 1; m.last_event = "duplicate"
                return False
            if self.tracker is not None and not await self.tracker.mark_pending(opportunity.opportunity_id):
                m.duplicates += 1; m.last_event = "duplicate_lifecycle"
                return False
            item = (-priority, opportunity.expires_at, self._seq, opportunity.opportunity_id, opportunity)
            self._seq += 1
            if len(self._heap) >= self.maxsize:
                worst = max(self._heap, key=lambda x: (x[0], -x[2]))
                if item >= worst:
                    if self.tracker is not None:
                        await self.tracker.release_pending(opportunity.opportunity_id)
                    m.dropped += 1; m.last_event = "dropped"
                    return False
                self._heap.remove(worst); heapq.heapify(self._heap)
                self._ids.discard(worst[3])
                if self.tracker is not None:
                    await self.tracker.release_pending(worst[3])
                self.metrics[worst[4].strategy_name].dropped += 1
                self.metrics[worst[4].strategy_name].last_event = "dropped"
            heapq.heappush(self._heap, item)
            self._ids.add(opportunity.opportunity_id)
            m.enqueued += 1; m.last_event = "enqueued"
            self._cv.notify()
            return True

    async def get(self) -> Opportunity:
        async with self._cv:
            while True:
                self._expire_locked()
                if self._heap:
                    _, _, _, oid, opp = heapq.heappop(self._heap)
                    self._ids.discard(oid)
                    return opp
                await self._cv.wait()

    def expire(self) -> int:
        before = self.qsize(); self._expire_locked(); return before - self.qsize()

    def _expire_locked(self) -> None:
        now = time.time(); keep = []
        for item in self._heap:
            if len(item) == 4:  # compatibility for older direct white-box tests
                _, expires_at, oid, opp = item
            else:
                _, expires_at, _, oid, opp = item
            if expires_at <= now:
                self._ids.discard(oid)
                self.metrics[opp.strategy_name].expired += 1
                self.metrics[opp.strategy_name].last_event = "expired"
            else:
                keep.append(item)
        if len(keep) != len(self._heap):
            self._heap = keep; heapq.heapify(self._heap)
