"""Fair, deadline-aware provider work admission with leased capacity."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
import time
from typing import Awaitable, Callable, Generic, TypeVar

from .authority import ProviderSpendAuthority
from .dependency import DependencyController
from .models import (
    AdmissionCode,
    AdmissionRequest,
    ProviderAdmissionError,
    ProviderLease,
)


T = TypeVar("T")


@dataclass(slots=True)
class _QueuedWork:
    request: AdmissionRequest
    future: asyncio.Future[ProviderLease]
    sequence: int


class DeadlineAdmissionScheduler:
    """Admit provider work by urgency, priority and least-served fairness key."""

    def __init__(
        self,
        authority: ProviderSpendAuthority,
        dependencies: DependencyController,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_queue_size: int = 4096,
        urgency_window_seconds: float = 0.250,
        poll_interval_seconds: float = 0.050,
    ) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be positive")
        if urgency_window_seconds < 0:
            raise ValueError("urgency_window_seconds must be non-negative")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self.authority = authority
        self.dependencies = dependencies
        self.clock = clock
        self.max_queue_size = max_queue_size
        self.urgency_window_seconds = float(urgency_window_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._condition = asyncio.Condition()
        self._pending: list[_QueuedWork] = []
        self._served: dict[str, int] = defaultdict(int)
        self._sequence = 0
        self._granted = 0
        self._expired = 0
        self._denied = 0

    def _sort_key(self, item: _QueuedWork, now: float) -> tuple[object, ...]:
        remaining = item.request.deadline_at - now
        urgent = 0 if remaining <= self.urgency_window_seconds else 1
        return (
            urgent,
            item.request.priority,
            self._served[item.request.fairness_key],
            item.request.deadline_at,
            item.sequence,
        )

    async def _dispatch_locked(self) -> None:
        now = self.clock()
        for item in tuple(self._pending):
            if item.future.done():
                self._pending.remove(item)
                continue
            if item.request.deadline_at > now:
                continue
            self._pending.remove(item)
            self._expired += 1
            item.future.set_exception(
                ProviderAdmissionError(
                    item.request.provider_id,
                    AdmissionCode.DEADLINE_EXPIRED,
                    "work expired while waiting for provider admission",
                    retryable=False,
                )
            )

        for item in sorted(
            tuple(self._pending), key=lambda queued: self._sort_key(queued, now)
        ):
            if item.future.done() or item not in self._pending:
                continue
            try:
                manifest = self.authority.entitlement(item.request.provider_id)
                await self.dependencies.assert_admissible(
                    item.request.provider_id,
                    manifest.generation,
                    item.request.operation,
                )
                lease = await self.authority.reserve(item.request)
            except ProviderAdmissionError as exc:
                if exc.retryable and (
                    exc.retry_at is None
                    or exc.retry_at < item.request.deadline_at
                ):
                    continue
                self._pending.remove(item)
                self._denied += 1
                item.future.set_exception(exc)
                continue
            self._pending.remove(item)
            self._served[item.request.fairness_key] += 1
            self._granted += 1
            item.future.set_result(lease)

    async def acquire(self, request: AdmissionRequest) -> ProviderLease:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ProviderLease] = loop.create_future()
        async with self._condition:
            if request.deadline_at <= self.clock():
                raise ProviderAdmissionError(
                    request.provider_id,
                    AdmissionCode.DEADLINE_EXPIRED,
                    "work deadline elapsed before queue admission",
                    retryable=False,
                )
            if len(self._pending) >= self.max_queue_size:
                raise ProviderAdmissionError(
                    request.provider_id,
                    AdmissionCode.QUEUE_FULL,
                    "provider admission queue is full",
                    retryable=True,
                )
            self._sequence += 1
            queued = _QueuedWork(
                request=request,
                future=future,
                sequence=self._sequence,
            )
            self._pending.append(queued)
            self._condition.notify_all()
            try:
                while not future.done():
                    await self._dispatch_locked()
                    if future.done():
                        break
                    remaining = request.deadline_at - self.clock()
                    if remaining <= 0:
                        await self._dispatch_locked()
                        break
                    timeout = min(self.poll_interval_seconds, remaining)
                    try:
                        await asyncio.wait_for(self._condition.wait(), timeout)
                    except asyncio.TimeoutError:
                        pass
                return future.result()
            except asyncio.CancelledError:
                if queued in self._pending:
                    self._pending.remove(queued)
                if future.done() and not future.cancelled():
                    lease = future.result()
                    await self.authority.release(lease)
                elif not future.done():
                    future.cancel()
                self._condition.notify_all()
                raise

    async def execute(
        self,
        request: AdmissionRequest,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        lease = await self.acquire(request)
        issued = False
        try:
            await self.authority.mark_issued(lease)
            issued = True
            return await operation()
        finally:
            if issued:
                await self.authority.complete(lease)
            else:
                await self.authority.release(lease)
            async with self._condition:
                await self._dispatch_locked()
                self._condition.notify_all()

    async def snapshot(self) -> dict[str, object]:
        async with self._condition:
            return {
                "queued": len(self._pending),
                "granted": self._granted,
                "expired": self._expired,
                "denied": self._denied,
                "served_by_fairness_key": dict(sorted(self._served.items())),
                "pending_work_ids": tuple(
                    item.request.work_id
                    for item in sorted(
                        self._pending,
                        key=lambda queued: (
                            queued.request.deadline_at,
                            queued.sequence,
                        ),
                    )
                ),
            }


__all__ = ["DeadlineAdmissionScheduler"]
