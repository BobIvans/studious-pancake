"""PR-200 deadline-aware, bounded single-writer persistence boundary.

The worker owns all blocking durable I/O on one dedicated thread. Async callers
submit explicitly classified operations and never execute SQLite calls on the
main event-loop thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
import itertools
import queue
import threading
import time
from typing import Generic, TypeVar, cast

T = TypeVar("T")


class PersistenceWorkClass(IntEnum):
    """Lower values are serviced first and receive reserved capacity."""

    FINANCIAL_LEDGER = 0
    LIFECYCLE = 10
    WEBHOOK_DURABLE_ENQUEUE = 20
    ALERT_OUTBOX = 30
    OBSERVABILITY_EXPORT = 40
    MAINTENANCE = 50

    @property
    def proof_critical(self) -> bool:
        return self <= PersistenceWorkClass.LIFECYCLE


class PersistenceState(StrEnum):
    """What is known about one durable operation."""

    NOT_SUBMITTED = "not_submitted"
    NOT_COMMITTED = "not_committed"
    COMMITTED = "committed"
    UNKNOWN = "unknown_await_reconciliation"


@dataclass(frozen=True, slots=True)
class PersistenceCommit(Generic[T]):
    """Explicit result returned by an operation running on the writer thread."""

    committed: bool
    value: T


@dataclass(frozen=True, slots=True)
class PersistenceResult(Generic[T]):
    operation_id: str
    state: PersistenceState
    value: T | None = None
    reason: str | None = None

    @property
    def terminal(self) -> bool:
        return self.state is not PersistenceState.UNKNOWN


@dataclass(frozen=True, slots=True)
class PersistenceOperation(Generic[T]):
    operation_id: str
    work_class: PersistenceWorkClass
    deadline_ns: int
    estimated_bytes: int
    run: Callable[[int], PersistenceCommit[T]]

    def __post_init__(self) -> None:
        if not self.operation_id.strip():
            raise ValueError("operation_id is required")
        if self.deadline_ns <= 0:
            raise ValueError("deadline_ns must be positive")
        if self.estimated_bytes < 0:
            raise ValueError("estimated_bytes cannot be negative")


@dataclass(frozen=True, slots=True)
class AsyncPersistenceWriterConfig:
    max_queue_items: int = 256
    max_queue_bytes: int = 16 * 1024 * 1024
    reserved_critical_items: int = 16
    reserved_critical_bytes: int = 1024 * 1024
    result_cache_items: int = 4096
    thread_name: str = "pr200-persistence-writer"

    def __post_init__(self) -> None:
        if self.max_queue_items <= 0 or self.max_queue_bytes <= 0:
            raise ValueError("queue limits must be positive")
        if not 0 <= self.reserved_critical_items < self.max_queue_items:
            raise ValueError("reserved_critical_items must be below max_queue_items")
        if not 0 <= self.reserved_critical_bytes < self.max_queue_bytes:
            raise ValueError("reserved_critical_bytes must be below max_queue_bytes")
        if self.result_cache_items <= 0:
            raise ValueError("result_cache_items must be positive")
        if not self.thread_name.strip():
            raise ValueError("thread_name is required")


@dataclass(frozen=True, slots=True)
class PersistenceHealth:
    writer_alive: bool
    accepting: bool
    queue_depth: int
    queue_bytes: int
    oldest_queue_age_ms: int
    in_flight_operation_id: str | None
    completed: int
    committed: int
    not_committed: int
    not_submitted: int
    unknown_waits: int
    failed_exceptions: int
    queue_rejections: int
    last_operation_latency_ms: int
    max_operation_latency_ms: int
    shutdown_clean: bool


@dataclass(order=True, slots=True)
class _QueueItem(Generic[T]):
    priority: int
    sequence: int
    enqueued_ns: int = field(compare=False)
    estimated_bytes: int = field(compare=False)
    operation: PersistenceOperation[T] | None = field(compare=False)
    promise: Future[PersistenceResult[T]] | None = field(compare=False)


class AsyncPersistenceWriter:
    """Bounded priority queue backed by one owned blocking-I/O thread."""

    def __init__(
        self,
        config: AsyncPersistenceWriterConfig = AsyncPersistenceWriterConfig(),
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self.config = config
        self._monotonic_ns = monotonic_ns
        self._queue: queue.PriorityQueue[_QueueItem[object]] = queue.PriorityQueue()
        self._lock = threading.RLock()
        self._sequence = itertools.count()
        self._thread: threading.Thread | None = None
        self._accepting = True
        self._closing = False
        self._cancel_optional_on_close = True
        self._shutdown_clean = False
        self._queued_items = 0
        self._queued_bytes = 0
        self._queued_at: dict[str, int] = {}
        self._in_flight_operation_id: str | None = None
        self._pending: dict[str, Future[PersistenceResult[object]]] = {}
        self._results: dict[str, PersistenceResult[object]] = {}
        self._result_order: list[str] = []
        self._completed = 0
        self._committed = 0
        self._not_committed = 0
        self._not_submitted = 0
        self._unknown_waits = 0
        self._failed_exceptions = 0
        self._queue_rejections = 0
        self._last_operation_latency_ms = 0
        self._max_operation_latency_ms = 0

    def start(self) -> None:
        """Start the owner thread; no durable I/O occurs on the caller thread."""

        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run,
                name=self.config.thread_name,
                daemon=True,
            )
            self._thread.start()

    async def submit(self, operation: PersistenceOperation[T]) -> PersistenceResult[T]:
        self.start()
        immediate, promise = self._admit(operation)
        if immediate is not None:
            return immediate
        assert promise is not None

        remaining = (operation.deadline_ns - self._monotonic_ns()) / 1_000_000_000
        if remaining <= 0:
            return cast(PersistenceResult[T], self._unknown(operation.operation_id))

        wrapped = asyncio.wrap_future(promise)
        try:
            return await asyncio.wait_for(asyncio.shield(wrapped), timeout=remaining)
        except TimeoutError:
            return cast(PersistenceResult[T], self._unknown(operation.operation_id))
        except asyncio.CancelledError:
            # The writer may already be committing. Preserve the operation and force
            # the caller to reconcile by operation_id rather than retrying blindly.
            self._unknown(operation.operation_id)
            raise

    def lookup(self, operation_id: str) -> PersistenceResult[object]:
        """Return the durable result, or UNKNOWN while the operation is in flight."""

        with self._lock:
            result = self._results.get(operation_id)
            if result is not None:
                return result
            if operation_id in self._pending:
                return PersistenceResult(
                    operation_id=operation_id,
                    state=PersistenceState.UNKNOWN,
                    reason="operation_in_flight",
                )
        return PersistenceResult(
            operation_id=operation_id,
            state=PersistenceState.NOT_SUBMITTED,
            reason="operation_not_known",
        )

    def health(self) -> PersistenceHealth:
        now_ns = self._monotonic_ns()
        with self._lock:
            oldest_ns = min(self._queued_at.values(), default=now_ns)
            thread = self._thread
            return PersistenceHealth(
                writer_alive=bool(thread and thread.is_alive()),
                accepting=self._accepting,
                queue_depth=self._queued_items,
                queue_bytes=self._queued_bytes,
                oldest_queue_age_ms=(
                    max(0, (now_ns - oldest_ns) // 1_000_000)
                    if self._queued_items
                    else 0
                ),
                in_flight_operation_id=self._in_flight_operation_id,
                completed=self._completed,
                committed=self._committed,
                not_committed=self._not_committed,
                not_submitted=self._not_submitted,
                unknown_waits=self._unknown_waits,
                failed_exceptions=self._failed_exceptions,
                queue_rejections=self._queue_rejections,
                last_operation_latency_ms=self._last_operation_latency_ms,
                max_operation_latency_ms=self._max_operation_latency_ms,
                shutdown_clean=self._shutdown_clean,
            )

    async def close(
        self,
        *,
        cancel_optional: bool = True,
        join_timeout_seconds: float = 5.0,
    ) -> PersistenceHealth:
        """Stop admission, preserve critical work and finish writer shutdown."""

        if join_timeout_seconds <= 0:
            raise ValueError("join_timeout_seconds must be positive")
        with self._lock:
            self._accepting = False
            self._closing = True
            self._cancel_optional_on_close = cancel_optional
            thread = self._thread
            if thread is None:
                self._shutdown_clean = True
                return self.health()
            self._queue.put(
                _QueueItem(
                    priority=1_000_000,
                    sequence=next(self._sequence),
                    enqueued_ns=self._monotonic_ns(),
                    estimated_bytes=0,
                    operation=None,
                    promise=None,
                )
            )
        await asyncio.to_thread(thread.join, join_timeout_seconds)
        with self._lock:
            self._shutdown_clean = not thread.is_alive()
        return self.health()

    def _admit(
        self, operation: PersistenceOperation[T]
    ) -> tuple[PersistenceResult[T] | None, Future[PersistenceResult[T]] | None]:
        now_ns = self._monotonic_ns()
        with self._lock:
            existing_result = self._results.get(operation.operation_id)
            if existing_result is not None:
                if (
                    existing_result.state is PersistenceState.NOT_SUBMITTED
                    and now_ns < operation.deadline_ns
                ):
                    # Admission failure is known-safe to retry. Remove the cached
                    # result and make a fresh bounded admission decision.
                    self._results.pop(operation.operation_id, None)
                    try:
                        self._result_order.remove(operation.operation_id)
                    except ValueError:
                        pass
                else:
                    return cast(PersistenceResult[T], existing_result), None
            existing_promise = self._pending.get(operation.operation_id)
            if existing_promise is not None:
                return None, cast(Future[PersistenceResult[T]], existing_promise)
            if not self._accepting:
                result = self._not_submitted_result(
                    operation.operation_id, "writer_closed"
                )
                return cast(PersistenceResult[T], result), None
            if now_ns >= operation.deadline_ns:
                result = self._not_submitted_result(
                    operation.operation_id,
                    "deadline_expired_before_admission",
                )
                return cast(PersistenceResult[T], result), None
            if not self._has_capacity(
                operation.work_class, operation.estimated_bytes
            ):
                self._queue_rejections += 1
                result = self._not_submitted_result(
                    operation.operation_id, "queue_full"
                )
                return cast(PersistenceResult[T], result), None

            promise: Future[PersistenceResult[T]] = Future()
            self._pending[operation.operation_id] = cast(
                Future[PersistenceResult[object]], promise
            )
            self._queued_items += 1
            self._queued_bytes += operation.estimated_bytes
            self._queued_at[operation.operation_id] = now_ns
            self._queue.put(
                cast(
                    _QueueItem[object],
                    _QueueItem(
                        priority=int(operation.work_class),
                        sequence=next(self._sequence),
                        enqueued_ns=now_ns,
                        estimated_bytes=operation.estimated_bytes,
                        operation=operation,
                        promise=promise,
                    ),
                )
            )
            return None, promise

    def _has_capacity(
        self, work_class: PersistenceWorkClass, estimated_bytes: int
    ) -> bool:
        item_limit = self.config.max_queue_items
        byte_limit = self.config.max_queue_bytes
        if not work_class.proof_critical:
            item_limit -= self.config.reserved_critical_items
            byte_limit -= self.config.reserved_critical_bytes
        return (
            self._queued_items + 1 <= item_limit
            and self._queued_bytes + estimated_bytes <= byte_limit
        )

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item.operation is None:
                self._queue.task_done()
                break
            operation = item.operation
            promise = item.promise
            assert promise is not None
            with self._lock:
                self._queued_items -= 1
                self._queued_bytes -= item.estimated_bytes
                self._queued_at.pop(operation.operation_id, None)
                self._in_flight_operation_id = operation.operation_id
                cancel_for_shutdown = (
                    self._closing
                    and self._cancel_optional_on_close
                    and not operation.work_class.proof_critical
                )
            started_ns = self._monotonic_ns()
            result: PersistenceResult[object]
            if cancel_for_shutdown:
                result = PersistenceResult(
                    operation_id=operation.operation_id,
                    state=PersistenceState.NOT_SUBMITTED,
                    reason="optional_work_cancelled_during_shutdown",
                )
            elif started_ns >= operation.deadline_ns:
                result = PersistenceResult(
                    operation_id=operation.operation_id,
                    state=PersistenceState.NOT_SUBMITTED,
                    reason="deadline_expired_before_execution",
                )
            else:
                try:
                    commit = operation.run(operation.deadline_ns)
                    result = PersistenceResult(
                        operation_id=operation.operation_id,
                        state=(
                            PersistenceState.COMMITTED
                            if commit.committed
                            else PersistenceState.NOT_COMMITTED
                        ),
                        value=commit.value,
                    )
                except Exception as exc:  # preserve unknown commit semantics
                    with self._lock:
                        self._failed_exceptions += 1
                    result = PersistenceResult(
                        operation_id=operation.operation_id,
                        state=PersistenceState.UNKNOWN,
                        reason=f"writer_exception:{type(exc).__name__}",
                    )
            finished_ns = self._monotonic_ns()
            latency_ms = max(0, (finished_ns - started_ns) // 1_000_000)
            self._complete(operation.operation_id, result, latency_ms)
            if not promise.done():
                promise.set_result(result)
            self._queue.task_done()

        with self._lock:
            self._in_flight_operation_id = None

    def _complete(
        self,
        operation_id: str,
        result: PersistenceResult[object],
        latency_ms: int,
    ) -> None:
        with self._lock:
            self._pending.pop(operation_id, None)
            self._results[operation_id] = result
            self._result_order.append(operation_id)
            self._completed += 1
            if result.state is PersistenceState.COMMITTED:
                self._committed += 1
            elif result.state is PersistenceState.NOT_COMMITTED:
                self._not_committed += 1
            elif result.state is PersistenceState.NOT_SUBMITTED:
                self._not_submitted += 1
            self._last_operation_latency_ms = latency_ms
            self._max_operation_latency_ms = max(
                self._max_operation_latency_ms, latency_ms
            )
            self._in_flight_operation_id = None
            while len(self._result_order) > self.config.result_cache_items:
                evicted = self._result_order.pop(0)
                self._results.pop(evicted, None)

    def _not_submitted_result(
        self, operation_id: str, reason: str
    ) -> PersistenceResult[object]:
        result: PersistenceResult[object] = PersistenceResult(
            operation_id=operation_id,
            state=PersistenceState.NOT_SUBMITTED,
            reason=reason,
        )
        self._results[operation_id] = result
        self._result_order.append(operation_id)
        self._completed += 1
        self._not_submitted += 1
        while len(self._result_order) > self.config.result_cache_items:
            evicted = self._result_order.pop(0)
            self._results.pop(evicted, None)
        return result

    def _unknown(self, operation_id: str) -> PersistenceResult[object]:
        with self._lock:
            final = self._results.get(operation_id)
            if final is not None:
                return final
            self._unknown_waits += 1
        return PersistenceResult(
            operation_id=operation_id,
            state=PersistenceState.UNKNOWN,
            reason="caller_deadline_elapsed_await_reconciliation",
        )


__all__ = [
    "AsyncPersistenceWriter",
    "AsyncPersistenceWriterConfig",
    "PersistenceCommit",
    "PersistenceHealth",
    "PersistenceOperation",
    "PersistenceResult",
    "PersistenceState",
    "PersistenceWorkClass",
]
