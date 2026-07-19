"""Bounded priority opportunity queue with expiry and metrics."""
from __future__ import annotations

import asyncio, heapq, time
from collections import defaultdict
from dataclasses import dataclass, field

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
    def __init__(self, maxsize: int, ranker: OpportunityRanker) -> None:
        self.maxsize = maxsize
        self.ranker = ranker
        self._heap: list[tuple[float, float, str, Opportunity]] = []
        self._ids: set[str] = set()
        self._cv = asyncio.Condition()
        self.metrics: defaultdict[str, StrategyQueueMetrics] = defaultdict(StrategyQueueMetrics)

    def qsize(self) -> int:
        return len(self._heap)

    async def put(self, opportunity: Opportunity) -> bool:
        async with self._cv:
            self._expire_locked()
            m = self.metrics[opportunity.strategy_name]
            m.detected += 1; m.last_event = "detected"
            if opportunity.opportunity_id in self._ids:
                m.duplicates += 1; m.last_event = "duplicate"
                return False
            while len(self._heap) >= self.maxsize:
                worst = max(self._heap, key=lambda x: x[0])
                self._heap.remove(worst); heapq.heapify(self._heap)
                self._ids.discard(worst[2])
                self.metrics[worst[3].strategy_name].dropped += 1
            priority = await self.ranker.priority(opportunity)
            heapq.heappush(self._heap, (-priority, opportunity.expires_at, opportunity.opportunity_id, opportunity))
            self._ids.add(opportunity.opportunity_id)
            m.enqueued += 1; m.last_event = "enqueued"
            self._cv.notify()
            return True

    async def get(self) -> Opportunity:
        async with self._cv:
            while True:
                self._expire_locked()
                if self._heap:
                    _, _, oid, opp = heapq.heappop(self._heap)
                    self._ids.discard(oid)
                    return opp
                await self._cv.wait()

    def expire(self) -> int:
        before = self.qsize()
        self._expire_locked()
        return before - self.qsize()

    def _expire_locked(self) -> None:
        now = time.time()
        keep = []
        for item in self._heap:
            _, expires_at, oid, opp = item
            if expires_at <= now:
                self._ids.discard(oid)
                self.metrics[opp.strategy_name].expired += 1
                self.metrics[opp.strategy_name].last_event = "expired"
            else:
                keep.append(item)
        if len(keep) != len(self._heap):
            self._heap = keep; heapq.heapify(self._heap)
