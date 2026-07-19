"""Application lifecycle for the arbitrage bot."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.strategy import OpportunityQueue, StrategyRegistry, StrategyRuntime
from src.strategy.interfaces import StrategyContext, StrategyMode
from src.strategy.ranker import ArbitrageScorerRanker
from src.strategy.strategies import (
    CircularArbitrageStrategy, KaminoLiquidationStrategy, LSTDepegStrategy,
    LSTUnstakeStrategy, OrderbookAmmStrategy, PumpMigrationStrategy,
)


@dataclass(slots=True)
class ApplicationContext:
    config: Any
    registry: StrategyRegistry
    opportunity_queue: OpportunityQueue
    strategy_runtime: StrategyRuntime


class ArbitrageApplication:
    def __init__(self, context: ApplicationContext) -> None:
        self.context = context

    async def run(self) -> None:
        await self.context.strategy_runtime.start()

    async def stop(self) -> None:
        await self.context.strategy_runtime.stop()


def _mode(config: Any, name: str, default: StrategyMode = StrategyMode.SHADOW) -> StrategyMode:
    value = getattr(config, "strategy_modes", {}).get(name, default.value) if config is not None else default.value
    return StrategyMode(value)


def build_application(config: Any = None) -> ArbitrageApplication:
    registry = StrategyRegistry()
    registry.register(LSTDepegStrategy(mode=_mode(config, "lst_depeg")))
    registry.register(LSTUnstakeStrategy(mode=_mode(config, "lst_unstake")))
    registry.register(CircularArbitrageStrategy(mode=_mode(config, "circular_arbitrage")))
    registry.register(KaminoLiquidationStrategy())
    registry.register(PumpMigrationStrategy())
    registry.register(OrderbookAmmStrategy())
    queue = OpportunityQueue(maxsize=getattr(config, "opportunity_queue_size", 1024), ranker=ArbitrageScorerRanker())
    runtime = StrategyRuntime(registry, queue, StrategyContext(config=config))
    return ArbitrageApplication(ApplicationContext(config, registry, queue, runtime))
