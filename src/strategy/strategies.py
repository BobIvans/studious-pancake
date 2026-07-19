"""Registered detection strategies and disabled shells."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable

from .domain import Opportunity
from .interfaces import StrategyContext, StrategyMode


@dataclass
class BaseDetectionStrategy:
    name: str
    mode: StrategyMode = StrategyMode.SHADOW
    disabled_reason: str | None = None
    poll_interval_seconds: float = 1.0
    _running: bool = field(default=False, init=False)
    _context: StrategyContext | None = field(default=None, init=False)

    async def start(self, context: StrategyContext) -> None:
        self._context = context
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def detect_once(self) -> Iterable[Opportunity]:
        return ()

    async def opportunities(self) -> AsyncIterator[Opportunity]:
        while self._running:
            for opportunity in await self.detect_once():
                yield opportunity
            await asyncio.sleep(self.poll_interval_seconds)


class LSTDepegStrategy(BaseDetectionStrategy):
    def __init__(self, *, mode: StrategyMode = StrategyMode.SHADOW) -> None:
        super().__init__("lst_depeg", mode)


class LSTUnstakeStrategy(BaseDetectionStrategy):
    def __init__(self, *, mode: StrategyMode = StrategyMode.SHADOW) -> None:
        super().__init__("lst_unstake", mode)


class CircularArbitrageStrategy(BaseDetectionStrategy):
    def __init__(self, *, mode: StrategyMode = StrategyMode.SHADOW) -> None:
        super().__init__("circular_arbitrage", mode)


class DisabledShellStrategy(BaseDetectionStrategy):
    async def start(self, context: StrategyContext) -> None:
        return None


class KaminoLiquidationStrategy(DisabledShellStrategy):
    def __init__(self) -> None:
        super().__init__("kamino_liquidation", StrategyMode.DISABLED, "execution intentionally out of scope for PR-002")


class PumpMigrationStrategy(DisabledShellStrategy):
    def __init__(self) -> None:
        super().__init__("pump_fun_migration", StrategyMode.DISABLED, "Pump.fun V2 implementation is a non-goal")


class OrderbookAmmStrategy(DisabledShellStrategy):
    def __init__(self) -> None:
        super().__init__("orderbook_amm_arbitrage", StrategyMode.DISABLED, "Phoenix/OpenBook implementation is a non-goal")
