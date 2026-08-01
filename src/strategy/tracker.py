"""Bounded opportunity lifecycle and replay-window authority."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from src.runtime.trusted_time import SystemTrustedTime, TrustedTime


class TrackerState(str, Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    TERMINAL = "terminal"
    EXPIRED = "expired"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True)
class TrackerRecord:
    state: TrackerState
    touched_ns: int
    generation: int = 0


class InMemoryOpportunityTracker:
    def __init__(
        self,
        *,
        capacity: int = 10_000,
        replay_ttl_ns: int = 3_600_000_000_000,
        clock: TrustedTime | None = None,
    ) -> None:
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("tracker capacity must be a positive integer")
        if (
            isinstance(replay_ttl_ns, bool)
            or not isinstance(replay_ttl_ns, int)
            or replay_ttl_ns < 1
        ):
            raise ValueError("replay_ttl_ns must be a positive integer")
        self.capacity, self.replay_ttl_ns = capacity, replay_ttl_ns
        self.clock = clock or SystemTrustedTime()
        self._states: OrderedDict[str, TrackerRecord] = OrderedDict()
        self._lock = asyncio.Lock()

    async def mark_pending(self, opportunity_id: str) -> bool:
        async with self._lock:
            now = self.clock.snapshot().monotonic_ns
            self._compact_locked(now)
            if opportunity_id in self._states:
                return False
            if len(self._states) >= self.capacity:
                # Never evict owned work to admit new work.
                terminal = next(
                    (
                        k
                        for k, v in self._states.items()
                        if v.state not in {TrackerState.PENDING, TrackerState.IN_FLIGHT}
                    ),
                    None,
                )
                if terminal is None:
                    return False
                self._states.pop(terminal)
            self._states[opportunity_id] = TrackerRecord(TrackerState.PENDING, now)
            return True

    async def claim(self, opportunity_id: str, generation: int = 0) -> bool:
        async with self._lock:
            now = self.clock.snapshot().monotonic_ns
            self._compact_locked(now)
            state = self._states.get(opportunity_id)
            if state is not None and state.state is not TrackerState.PENDING:
                return False
            self._states[opportunity_id] = TrackerRecord(
                TrackerState.IN_FLIGHT, now, generation
            )
            self._states.move_to_end(opportunity_id)
            return True

    async def release_pending(self, opportunity_id: str) -> None:
        async with self._lock:
            if (
                record := self._states.get(opportunity_id)
            ) and record.state is TrackerState.PENDING:
                self._states.pop(opportunity_id)

    async def recover_pending(self, opportunity_id: str, generation: int) -> bool:
        """Return one specifically fenced in-flight identity to pending."""
        async with self._lock:
            now = self.clock.snapshot().monotonic_ns
            record = self._states.get(opportunity_id)
            if (
                record is None
                or record.state is not TrackerState.IN_FLIGHT
                or record.generation != generation
            ):
                return False
            self._states[opportunity_id] = TrackerRecord(
                TrackerState.PENDING, now, generation
            )
            self._states.move_to_end(opportunity_id)
            return True

    async def terminal(
        self, opportunity_id: str, state: TrackerState = TrackerState.TERMINAL
    ) -> None:
        if state in {TrackerState.PENDING, TrackerState.IN_FLIGHT}:
            raise ValueError("terminal state required")
        async with self._lock:
            now = self.clock.snapshot().monotonic_ns
            generation = self._states.get(
                opportunity_id, TrackerRecord(state, now)
            ).generation
            self._states[opportunity_id] = TrackerRecord(state, now, generation)
            self._states.move_to_end(opportunity_id)
            self._compact_locked(now)

    async def state(self, opportunity_id: str) -> TrackerState | None:
        async with self._lock:
            record = self._states.get(opportunity_id)
            return None if record is None else record.state

    def _compact_locked(self, now: int) -> None:
        expired = [
            key
            for key, record in self._states.items()
            if record.state not in {TrackerState.PENDING, TrackerState.IN_FLIGHT}
            and now - record.touched_ns >= self.replay_ttl_ns
        ]
        for key in expired:
            self._states.pop(key, None)
        while len(self._states) > self.capacity:
            terminal_key = next(
                (
                    k
                    for k, v in self._states.items()
                    if v.state not in {TrackerState.PENDING, TrackerState.IN_FLIGHT}
                ),
                None,
            )
            if terminal_key is None:
                break
            self._states.pop(terminal_key)
