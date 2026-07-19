"""Supported application composition root for the arbitrage bot.

PR-023 intentionally keeps this runtime inspection/shadow-safe. Legacy execution
modules are not imported here and live mode remains fail-closed.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from src.capabilities import CapabilityMatrix
from src.strategy import OpportunityQueue, StrategyRegistry, StrategyRuntime
from src.strategy.consumer import (
    InMemoryOpportunityTracker,
    OpportunityConsumer,
    OpportunityHandler,
    ShadowOnlyOpportunityHandler,
)
from src.strategy.interfaces import StrategyContext, StrategyMode
from src.strategy.ranker import ArbitrageScorerRanker
from src.strategy.results import InMemoryOpportunityResultSink, OpportunityResultSink
from src.strategy.strategies import (
    CircularArbitrageStrategy,
    KaminoLiquidationStrategy,
    LSTDepegStrategy,
    LSTUnstakeStrategy,
    OrderbookAmmStrategy,
    PumpMigrationStrategy,
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
    capability: str = "disabled"
    quarantined: bool = False
    active_in_supported_entrypoint: bool = False


@dataclass(slots=True)
class ApplicationContext:
    config: Any
    capabilities: CapabilityMatrix
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
        for strategy in self.context.registry.all():
            declared = self.context.capabilities.strategy(strategy.name)
            state = self.context.strategy_runtime.states.get(
                strategy.name,
                "disabled" if strategy.mode is StrategyMode.DISABLED else "registered",
            )
            reason = self.context.strategy_runtime.reasons.get(
                strategy.name, strategy.disabled_reason or declared.reason
            )
            entries.append(
                StrategyManifestEntry(
                    name=strategy.name,
                    configured_mode=strategy.mode.value,
                    effective_mode=strategy.mode.value,
                    state=state,
                    reason=reason,
                    capability=declared.capability.value,
                    quarantined=declared.quarantined,
                    active_in_supported_entrypoint=declared.active_in_supported_entrypoint,
                )
            )
        return entries

    def capability_errors(self) -> tuple[str, ...]:
        path_errors = self.context.capabilities.validate_paths()
        registry_errors = self.context.capabilities.validate_strategy_registry(
            self.context.registry.all()
        )
        return path_errors + registry_errors

    def executable_strategies(self) -> tuple[StrategyManifestEntry, ...]:
        """Return strategies that the capability contract permits to do real work.

        A merely registered shadow shell is not executable. It must be explicitly
        declared shadow-ready/live-ready and enabled in a matching mode.
        """
        executable = []
        for entry in self.manifest():
            if entry.effective_mode == StrategyMode.SHADOW.value and entry.capability in {
                "shadow-ready",
                "live-ready",
            }:
                executable.append(entry)
            elif (
                entry.effective_mode == StrategyMode.LIVE.value
                and entry.capability == "live-ready"
            ):
                executable.append(entry)
        return tuple(executable)

    def validate(self) -> None:
        if self.context.handler is None:
            raise ConfigurationError("opportunity handler is required")
        for strategy in self.context.registry.all():
            if strategy.mode is StrategyMode.LIVE:
                raise ConfigurationError(
                    "live mode is disabled until the canonical execution stack is implemented: "
                    f"{strategy.name}"
                )
            if strategy.mode is StrategyMode.DISABLED and not strategy.disabled_reason:
                raise ConfigurationError(
                    f"disabled strategy requires reason: {strategy.name}"
                )
        errors = self.capability_errors()
        if errors:
            raise ConfigurationError("; ".join(errors))

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
            await asyncio.wait_for(
                self._drain_queue(),
                timeout=self.context.shutdown_drain_timeout_seconds,
            )
        except asyncio.TimeoutError:
            while self.context.opportunity_queue.qsize():
                opportunity = await self.context.opportunity_queue.get()
                await self.context.consumer.process_one(opportunity)
        await self.context.consumer.stop()
        self._started = False

    async def _drain_queue(self) -> None:
        while self.context.opportunity_queue.qsize():
            opportunity = await self.context.opportunity_queue.get()
            await self.context.consumer.process_one(opportunity)


def _mode(
    config: Any, name: str, default: StrategyMode = StrategyMode.DISABLED
) -> StrategyMode:
    value = (
        getattr(config, "strategy_modes", {}).get(name, default.value)
        if config is not None
        else default.value
    )
    try:
        return StrategyMode(value)
    except ValueError as exc:
        raise ConfigurationError(f"invalid strategy mode for {name}: {value!r}") from exc


def build_application(
    config: Any = None, capabilities: CapabilityMatrix | None = None
) -> ArbitrageApplication:
    capability_matrix = capabilities or CapabilityMatrix.load_default()
    registry = StrategyRegistry()
    registry.register(LSTDepegStrategy(mode=_mode(config, "lst_depeg")))
    registry.register(LSTUnstakeStrategy(mode=_mode(config, "lst_unstake")))
    registry.register(
        CircularArbitrageStrategy(mode=_mode(config, "circular_arbitrage"))
    )

    # Advanced venues are deliberately constructed disabled. Environment flags
    # are not consulted here; promotion requires a reviewed capability-contract change.
    registry.register(KaminoLiquidationStrategy())
    registry.register(PumpMigrationStrategy(adapter_configured=False))
    registry.register(OrderbookAmmStrategy())

    tracker = InMemoryOpportunityTracker()
    queue = OpportunityQueue(
        maxsize=getattr(config, "opportunity_queue_size", 1024),
        ranker=ArbitrageScorerRanker(),
        tracker=tracker,
    )
    runtime = StrategyRuntime(registry, queue, StrategyContext(config=config))
    sink = InMemoryOpportunityResultSink()
    handler = ShadowOnlyOpportunityHandler()
    consumer = OpportunityConsumer(queue, registry, tracker, handler, sink)
    timeout = getattr(config, "shutdown_drain_timeout_seconds", 0.25)
    context = ApplicationContext(
        config=config,
        capabilities=capability_matrix,
        registry=registry,
        opportunity_queue=queue,
        strategy_runtime=runtime,
        consumer=consumer,
        handler=handler,
        result_sink=sink,
        tracker=tracker,
        shutdown_drain_timeout_seconds=timeout,
    )
    return ArbitrageApplication(context)
