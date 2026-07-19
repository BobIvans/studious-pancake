"""In-process opportunity lifecycle dedupe tracker."""
from __future__ import annotations

import asyncio
from enum import Enum


class TrackerState(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    TERMINAL = "terminal"


class InMemoryOpportunityTracker:
    def __init__(self) -> None:
        self._states: dict[str, TrackerState] = {}
        self._lock = asyncio.Lock()

    async def mark_pending(self, opportunity_id: str) -> bool:
        async with self._lock:
            if opportunity_id in self._states:
                return False
            self._states[opportunity_id] = TrackerState.PENDING
            return True

    async def claim(self, opportunity_id: str) -> bool:
        async with self._lock:
            state = self._states.get(opportunity_id)
            if state is None:
                self._states[opportunity_id] = TrackerState.IN_FLIGHT
                return True
            if state is TrackerState.PENDING:
                self._states[opportunity_id] = TrackerState.IN_FLIGHT
                return True
            return False

    async def release_pending(self, opportunity_id: str) -> None:
        async with self._lock:
            if self._states.get(opportunity_id) is TrackerState.PENDING:
                self._states.pop(opportunity_id, None)

    async def terminal(self, opportunity_id: str) -> None:
        async with self._lock:
            self._states[opportunity_id] = TrackerState.TERMINAL
