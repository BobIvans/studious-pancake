"""Async strategy runtime and task supervision."""
from __future__ import annotations

import asyncio, logging
from contextlib import suppress

from .interfaces import StrategyContext, StrategyMode
from .queue import OpportunityQueue
from .registry import StrategyRegistry

logger = logging.getLogger(__name__)


class TaskSupervisor:
    def __init__(self) -> None:
        self.tasks: set[asyncio.Task] = set()
        self.exceptions: list[BaseException] = []

    def create(self, coro, *, name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self.tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task) -> None:
        self.tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            self.exceptions.append(exc)
            logger.exception("supervised_task_failed", exc_info=exc, extra={"task": task.get_name()})

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
        self.supervisor = TaskSupervisor()
        self._started = False

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("strategy runtime already started")
        self._started = True
        for strategy in self.registry.all():
            if strategy.mode is StrategyMode.DISABLED:
                self.queue.metrics[strategy.name].last_event = f"disabled: {strategy.disabled_reason or 'no reason'}"
                continue
            logger.info("strategy_start", extra={"strategy": strategy.name, "mode": strategy.mode.value})
            try:
                await strategy.start(self.context)
            except Exception as exc:
                self.queue.metrics[strategy.name].last_error = str(exc)
                logger.exception("strategy_start_failed", extra={"strategy": strategy.name})
                continue
            self.supervisor.create(self._consume(strategy), name=f"strategy:{strategy.name}")

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

    async def stop(self) -> None:
        await self.supervisor.shutdown()
        for strategy in self.registry.all():
            with suppress(Exception):
                await strategy.stop()
                logger.info("strategy_stop", extra={"strategy": strategy.name})
        self._started = False
