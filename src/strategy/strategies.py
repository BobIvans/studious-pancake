"""Registered detection strategies and disabled shells."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable

from src.market.snapshots import coerce_snapshot_set

from .detectors import CircularArbitrageDetector, DetectorPair
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
    """Shadow-safe two-leg circular detector backed by real/recorded snapshots."""

    def __init__(
        self,
        *,
        mode: StrategyMode = StrategyMode.DISABLED,
        pairs: Iterable[DetectorPair] | None = None,
    ) -> None:
        reason = "detector_not_enabled" if mode is StrategyMode.DISABLED else None
        super().__init__("circular_arbitrage", mode, reason)
        self._configured_pairs = tuple(pairs or ())
        self.detector = CircularArbitrageDetector(self._configured_pairs)

    async def start(self, context: StrategyContext) -> None:
        await super().start(context)
        detector_config = _circular_detector_config(context.config)
        if not self._configured_pairs:
            self.detector = CircularArbitrageDetector(_pairs_from_config(detector_config))
        poll_interval_ms = getattr(detector_config, "poll_interval_ms", None)
        if poll_interval_ms is not None:
            self.poll_interval_seconds = int(poll_interval_ms) / 1000

    async def detect_once(self) -> Iterable[Opportunity]:
        if self._context is None:
            return ()
        if not self.detector.pairs:
            return ()
        snapshots = await coerce_snapshot_set(self._context.market_state)
        return self.detector.detect(snapshots)


class DisabledShellStrategy(BaseDetectionStrategy):
    async def start(self, context: StrategyContext) -> None:
        return None


class KaminoLiquidationStrategy(DisabledShellStrategy):
    def __init__(self) -> None:
        super().__init__(
            "kamino_liquidation",
            StrategyMode.DISABLED,
            "legacy Kamino liquidation execution quarantined; PR-020 shadow "
            "planner lives in src.liquidation.strategy and has no sender access",
        )


class PumpMigrationStrategy(DisabledShellStrategy):
    def __init__(self, *, adapter_configured: bool = False) -> None:
        if adapter_configured:
            super().__init__("pump_fun_migration", StrategyMode.SHADOW, None)
        else:
            super().__init__(
                "pump_fun_migration",
                StrategyMode.DISABLED,
                "PUMP_ADAPTER_NOT_CONFIGURED_SHADOW_ONLY",
            )

    async def detect_once(self) -> Iterable[Opportunity]:
        # PR-021: only normalized shadow candidates from the verified Pump adapter
        # may be yielded here. Heuristic graduation/backrun ArbitrageSignal values
        # are intentionally not adapted into strategy opportunities.
        return ()


class OrderbookAmmStrategy(DisabledShellStrategy):
    def __init__(self) -> None:
        super().__init__(
            "orderbook_amm_arbitrage",
            StrategyMode.DISABLED,
            "canonical Phoenix Legacy/OpenBook V2 orderbook path is shadow-only; "
            "detector wiring awaits verified market subscriptions",
        )


def _circular_detector_config(config: object | None) -> object | None:
    detectors = getattr(config, "detectors", None)
    return getattr(detectors, "circular_arbitrage", None)


def _pairs_from_config(detector_config: object | None) -> tuple[DetectorPair, ...]:
    if detector_config is None:
        return ()
    pairs = getattr(detector_config, "pairs", ())
    result: list[DetectorPair] = []
    for pair in pairs:
        if isinstance(pair, DetectorPair):
            result.append(pair)
            continue
        result.append(
            DetectorPair(
                pair_id=str(pair.pair_id),
                base_mint=str(pair.base_mint),
                intermediate_mint=str(pair.intermediate_mint),
                probe_amount_base_units=int(pair.probe_amount_base_units),
                min_gross_profit_base_units=int(pair.min_gross_profit_base_units),
                max_snapshot_age_seconds=pair.max_snapshot_age_ms / 1000,
                ttl_seconds=pair.ttl_ms / 1000,
                cooldown_seconds=pair.cooldown_ms / 1000,
                max_slot_skew=int(pair.max_slot_skew),
            )
        )
    return tuple(result)
