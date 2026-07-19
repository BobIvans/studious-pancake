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
    def __init__(self, *, mode: StrategyMode = StrategyMode.DISABLED) -> None:
        reason = "detector_not_implemented" if mode is StrategyMode.DISABLED else None
        super().__init__("lst_depeg", mode, reason)


class LSTUnstakeStrategy(BaseDetectionStrategy):
    def __init__(self, *, mode: StrategyMode = StrategyMode.DISABLED) -> None:
        reason = "detector_not_implemented" if mode is StrategyMode.DISABLED else None
        super().__init__("lst_unstake", mode, reason)


class CircularArbitrageStrategy(BaseDetectionStrategy):
    def __init__(self, *, mode: StrategyMode = StrategyMode.DISABLED) -> None:
        reason = "detector_not_implemented" if mode is StrategyMode.DISABLED else None
        super().__init__("circular_arbitrage", mode, reason)


class DisabledShellStrategy(BaseDetectionStrategy):
    async def start(self, context: StrategyContext) -> None:
        return None


class KaminoLiquidationStrategy(DisabledShellStrategy):
    def __init__(self) -> None:
        super().__init__("kamino_liquidation", StrategyMode.DISABLED, "legacy Kamino liquidation execution quarantined; PR-020 shadow planner lives in src.liquidation.strategy and has no sender access")


class PumpMigrationStrategy(DisabledShellStrategy):
    def __init__(self, *, adapter_configured: bool = False) -> None:
        if adapter_configured:
            super().__init__("pump_fun_migration", StrategyMode.SHADOW, None)
        else:
            super().__init__("pump_fun_migration", StrategyMode.DISABLED, "PUMP_ADAPTER_NOT_CONFIGURED_SHADOW_ONLY")

    async def detect_once(self) -> Iterable[Opportunity]:
        # PR-021: only normalized shadow candidates from the verified Pump adapter
        # may be yielded here. Heuristic graduation/backrun ArbitrageSignal values
        # are intentionally not adapted into strategy opportunities.
        return ()


class OrderbookAmmStrategy(DisabledShellStrategy):
    def __init__(self) -> None:
        super().__init__("orderbook_amm_arbitrage", StrategyMode.DISABLED, "canonical Phoenix Legacy/OpenBook V2 orderbook path is shadow-only; detector wiring awaits verified market subscriptions")
