"""Application lifecycle for the arbitrage bot."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from src.strategy import OpportunityQueue, StrategyRegistry, StrategyRuntime
from src.strategy.consumer import InMemoryOpportunityTracker, OpportunityConsumer, OpportunityHandler, ShadowOnlyOpportunityHandler
from src.strategy.interfaces import StrategyContext, StrategyMode
from src.strategy.ranker import ArbitrageScorerRanker
from src.strategy.results import InMemoryOpportunityResultSink, OpportunityResultSink
from src.strategy.strategies import (
    CircularArbitrageStrategy, KaminoLiquidationStrategy, LSTDepegStrategy,
    LSTUnstakeStrategy, OrderbookAmmStrategy, PumpMigrationStrategy,
)


class ConfigurationError(ValueError):
    """Fail-closed runtime configuration error."""


@dataclass(frozen=True, slots=True)
class StrategyManifestEntry:
    name: str
    configured_mode: str
    effective_mode: str
    state: str
    reason: str | None = None


@dataclass(slots=True)
class ApplicationContext:
    config: Any
    registry: StrategyRegistry
    opportunity_queue: OpportunityQueue
    strategy_runtime: StrategyRuntime
    consumer: OpportunityConsumer
    handler: OpportunityHandler
    result_sink: OpportunityResultSink
    tracker: InMemoryOpportunityTracker
    shutdown_drain_timeout_seconds: float = 0.25


class ArbitrageApplication:
    def __init__(self, context: ApplicationContext) -> None:
        self.context = context
        self._started = False

    def manifest(self) -> list[StrategyManifestEntry]:
        entries = []
        for s in self.context.registry.all():
            state = self.context.strategy_runtime.states.get(
                s.name, "disabled" if s.mode is StrategyMode.DISABLED else "registered"
            )
            reason = self.context.strategy_runtime.reasons.get(s.name, s.disabled_reason)
            entries.append(StrategyManifestEntry(s.name, s.mode.value, s.mode.value, state, reason))
        return entries

    def validate(self) -> None:
        if self.context.handler is None:
            raise ConfigurationError("opportunity handler is required")
        for strategy in self.context.registry.all():
            if strategy.mode is StrategyMode.LIVE:
                raise ConfigurationError(f"live mode is disabled until execution stack is implemented: {strategy.name}")
            if strategy.mode is StrategyMode.DISABLED and not strategy.disabled_reason:
                raise ConfigurationError(f"disabled strategy requires reason: {strategy.name}")

    async def run(self) -> None:
        if self._started:
            raise RuntimeError("application already started")
        self.validate()
        self.context.consumer.start()
        try:
            await self.context.strategy_runtime.start()
        except Exception:
            await self.context.consumer.stop()
            raise
        self._started = True

    async def stop(self) -> None:
        await self.context.strategy_runtime.stop()
        try:
            await asyncio.wait_for(self._drain_queue(), timeout=self.context.shutdown_drain_timeout_seconds)
        except asyncio.TimeoutError:
            while self.context.opportunity_queue.qsize():
                opp = await self.context.opportunity_queue.get()
                await self.context.consumer.process_one(opp)
        await self.context.consumer.stop()
        self._started = False

    async def _drain_queue(self) -> None:
        while self.context.opportunity_queue.qsize():
            opp = await self.context.opportunity_queue.get()
            await self.context.consumer.process_one(opp)


def _mode(config: Any, name: str, default: StrategyMode = StrategyMode.DISABLED) -> StrategyMode:
    value = getattr(config, "strategy_modes", {}).get(name, default.value) if config is not None else default.value
    try:
        return StrategyMode(value)
    except ValueError as exc:
        raise ConfigurationError(f"invalid strategy mode for {name}: {value!r}") from exc


def build_application(config: Any = None) -> ArbitrageApplication:
    registry = StrategyRegistry()
    registry.register(LSTDepegStrategy(mode=_mode(config, "lst_depeg")))
    registry.register(LSTUnstakeStrategy(mode=_mode(config, "lst_unstake")))
    registry.register(CircularArbitrageStrategy(mode=_mode(config, "circular_arbitrage")))
    registry.register(KaminoLiquidationStrategy())
    registry.register(PumpMigrationStrategy())
    registry.register(OrderbookAmmStrategy())
    tracker = InMemoryOpportunityTracker()
    queue = OpportunityQueue(maxsize=getattr(config, "opportunity_queue_size", 1024),
                             ranker=ArbitrageScorerRanker(), tracker=tracker)
    runtime = StrategyRuntime(registry, queue, StrategyContext(config=config))
    sink = InMemoryOpportunityResultSink()
    handler = ShadowOnlyOpportunityHandler()
    consumer = OpportunityConsumer(queue, registry, tracker, handler, sink)
    timeout = getattr(config, "shutdown_drain_timeout_seconds", 0.25)
    return ArbitrageApplication(ApplicationContext(config, registry, queue, runtime, consumer, handler, sink, tracker, timeout))
