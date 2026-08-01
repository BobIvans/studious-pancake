"""Async strategy runtime and task supervision."""
from __future__ import annotations

import asyncio, logging
from collections import deque

from .interfaces import StrategyContext, StrategyMode
from .queue import OpportunityQueue
from .registry import StrategyRegistry

logger = logging.getLogger(__name__)


class TaskSupervisor:
    def __init__(self, *, exception_capacity: int = 128, on_failure=None) -> None:
        self.tasks: set[asyncio.Task] = set()
        self.exceptions: deque[BaseException] = deque(maxlen=exception_capacity)
        self.terminal: deque[tuple[str, str]] = deque(maxlen=exception_capacity)
        self._on_failure = on_failure

    def create(self, coro, *, name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self.tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task) -> None:
        self.tasks.discard(task)
        if task.cancelled():
            self.terminal.append((task.get_name(), "cancelled"))
            return
        exc = task.exception()
        if exc is not None:
            self.exceptions.append(exc)
            self.terminal.append((task.get_name(), "failed"))
            logger.exception("supervised_task_failed", exc_info=exc, extra={"task": task.get_name()})
            if self._on_failure is not None:
                self._on_failure(task, exc)

    async def shutdown(self) -> None:
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class StrategyRuntime:
    def __init__(self, registry: StrategyRegistry, queue: OpportunityQueue, context: StrategyContext | None = None) -> None:
        self.registry = registry
        self.queue = queue
        self.context = context or StrategyContext()
        self.supervisor = TaskSupervisor(on_failure=self._critical_task_failed)
        self._started = False
        self._stopping = False
        self.ready = False
        self.states: dict[str, str] = {}
        self.reasons: dict[str, str | None] = {}

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("strategy runtime already started")
        self._started = True
        self._stopping = False
        for strategy in self.registry.all():
            if strategy.mode is StrategyMode.DISABLED:
                self.queue.metrics[strategy.name].last_event = f"disabled: {strategy.disabled_reason or 'no reason'}"
                self.states[strategy.name] = "disabled"
                self.reasons[strategy.name] = strategy.disabled_reason or "strategy_disabled"
                continue
            logger.info("strategy_start", extra={"strategy": strategy.name, "mode": strategy.mode.value})
            try:
                await strategy.start(self.context)
            except Exception as exc:
                self.queue.metrics[strategy.name].last_error = str(exc)
                self.states[strategy.name] = "start_failed"
                self.reasons[strategy.name] = str(exc)
                logger.exception("strategy_start_failed", extra={"strategy": strategy.name})
                continue
            self.states[strategy.name] = "running"
            self.reasons[strategy.name] = None
            self.supervisor.create(self._consume(strategy), name=f"strategy:{strategy.name}")
        self.ready = any(state == "running" for state in self.states.values())

    def _critical_task_failed(self, task: asyncio.Task, exc: BaseException) -> None:
        self.ready = False
        name = task.get_name().removeprefix("strategy:")
        self.states[name] = "failed"
        self.reasons[name] = f"{type(exc).__name__}: {exc}"
        if not self._stopping:
            for dependent in tuple(self.supervisor.tasks):
                dependent.cancel()

    async def _consume(self, strategy) -> None:
        try:
            async for opportunity in strategy.opportunities():
                await self.queue.put(opportunity)
                logger.info("opportunity_detected", extra={"strategy": strategy.name, "queue_size": self.queue.qsize()})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.queue.metrics[strategy.name].last_error = str(exc)
            logger.exception("strategy_error", extra={"strategy": strategy.name})
            self.states[strategy.name] = "failed"
            self.reasons[strategy.name] = f"{type(exc).__name__}: {exc}"
            raise

    async def stop(self) -> None:
        self._stopping = True
        self.ready = False
        await self.supervisor.shutdown()
        failures = []
        for strategy in self.registry.all():
            try:
                await strategy.stop()
                if self.states.get(strategy.name) == "running":
                    self.states[strategy.name] = "stopped"
                logger.info("strategy_stop", extra={"strategy": strategy.name})
            except Exception as exc:
                self.states[strategy.name] = "stop_failed"
                self.reasons[strategy.name] = f"{type(exc).__name__}: {exc}"
                failures.append(exc)
        self._started = False
        if failures:
            raise ExceptionGroup("strategy stop failed", failures)
