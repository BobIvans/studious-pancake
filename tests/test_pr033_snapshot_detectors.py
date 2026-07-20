from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from src.application import build_application
from src.market.snapshots import MarketQuoteSnapshot, RecordedSnapshotSource, SnapshotSet
from src.strategy.consumer import (
    CapitalAwareShadowOpportunityHandler,
    ConfiguredCapitalPrecheck,
)
from src.strategy.detectors import CircularArbitrageDetector, DetectorPair
from src.strategy.interfaces import StrategyMode
from src.strategy.results import OpportunityResultStatus

pytestmark = pytest.mark.unit

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _quote(
    *,
    input_mint: str,
    output_mint: str,
    in_amount: int,
    out_amount: int,
    observed_at: float,
    slot: int = 100,
) -> MarketQuoteSnapshot:
    return MarketQuoteSnapshot(
        provider="recorded-jupiter",
        input_mint=input_mint,
        output_mint=output_mint,
        in_amount=in_amount,
        out_amount=out_amount,
        slot=slot,
        observed_at=observed_at,
        source="recorded-fixture",
    )


def _pair(**overrides) -> DetectorPair:
    payload = {
        "pair_id": "sol-usdc-loop",
        "base_mint": SOL,
        "intermediate_mint": USDC,
        "probe_amount_base_units": 1_000_000_000,
        "min_gross_profit_base_units": 500_000,
        "max_snapshot_age_seconds": 5.0,
        "ttl_seconds": 2.0,
        "cooldown_seconds": 0.0,
        "max_slot_skew": 0,
    }
    payload.update(overrides)
    return DetectorPair(**payload)


def test_recorded_snapshots_create_expected_two_leg_candidate() -> None:
    now = time.time()
    snapshots = SnapshotSet(
        (
            _quote(
                input_mint=SOL,
                output_mint=USDC,
                in_amount=1_000_000_000,
                out_amount=110_000_000,
                observed_at=now,
            ),
            _quote(
                input_mint=USDC,
                output_mint=SOL,
                in_amount=110_000_000,
                out_amount=1_002_000_000,
                observed_at=now,
            ),
        )
    )
    detector = CircularArbitrageDetector((_pair(),))

    (opportunity,) = detector.detect(snapshots, now=now)

    assert opportunity.strategy_name == "circular_arbitrage"
    assert opportunity.opportunity_type == "two_leg_circular_snapshot"
    assert opportunity.metadata["gross_profit_base_units"] == 2_000_000
    assert opportunity.metadata["route"][0]["provider"] == "recorded-jupiter"


def test_stale_or_cross_slot_snapshots_fail_closed() -> None:
    now = time.time()
    pair = _pair(max_snapshot_age_seconds=1.0, max_slot_skew=0)
    stale = SnapshotSet(
        (
            _quote(
                input_mint=SOL,
                output_mint=USDC,
                in_amount=1_000_000_000,
                out_amount=110_000_000,
                observed_at=now - 10,
            ),
            _quote(
                input_mint=USDC,
                output_mint=SOL,
                in_amount=110_000_000,
                out_amount=1_002_000_000,
                observed_at=now,
            ),
        )
    )
    cross_slot = SnapshotSet(
        (
            _quote(
                input_mint=SOL,
                output_mint=USDC,
                in_amount=1_000_000_000,
                out_amount=110_000_000,
                observed_at=now,
                slot=100,
            ),
            _quote(
                input_mint=USDC,
                output_mint=SOL,
                in_amount=110_000_000,
                out_amount=1_002_000_000,
                observed_at=now,
                slot=101,
            ),
        )
    )
    detector = CircularArbitrageDetector((pair,))

    assert detector.detect(stale, now=now) == ()
    assert detector.last_rejections[pair.pair_id].reason_code == "missing_route_leg"
    assert detector.detect(cross_slot, now=now) == ()
    assert detector.last_rejections[pair.pair_id].reason_code == (
        "cross_slot_or_stale_snapshot"
    )


@pytest.mark.asyncio
async def test_configured_capital_precheck_returns_no_trade_for_weak_edge() -> None:
    now = time.time()
    detector = CircularArbitrageDetector(
        (_pair(min_gross_profit_base_units=1, cooldown_seconds=0.0),)
    )
    snapshots = SnapshotSet(
        (
            _quote(
                input_mint=SOL,
                output_mint=USDC,
                in_amount=1_000_000_000,
                out_amount=110_000_000,
                observed_at=now,
            ),
            _quote(
                input_mint=USDC,
                output_mint=SOL,
                in_amount=110_000_000,
                out_amount=1_000_001_000,
                observed_at=now,
            ),
        )
    )
    (opportunity,) = detector.detect(snapshots, now=now)
    config = SimpleNamespace(
        monetary=SimpleNamespace(
            minimum_net_profit_lamports=100_000,
            contingency_lamports=500_000,
        )
    )
    handler = CapitalAwareShadowOpportunityHandler(ConfiguredCapitalPrecheck(config))

    result = await handler.handle(opportunity, mode=StrategyMode.SHADOW)

    assert result.status is OpportunityResultStatus.REJECTED
    assert result.reason_code == "no_trade_insufficient_prechecked_edge"


@dataclass
class _Config:
    pairs: tuple[DetectorPair, ...]
    opportunity_queue_size: int = 16
    shutdown_drain_timeout_seconds: float = 0.01

    @property
    def strategy_modes(self):
        return {
            "lst_depeg": "disabled",
            "lst_unstake": "disabled",
            "circular_arbitrage": "shadow",
        }

    @property
    def detectors(self):
        return SimpleNamespace(
            circular_arbitrage=SimpleNamespace(
                pairs=self.pairs,
                poll_interval_ms=10,
            )
        )

    @property
    def monetary(self):
        return SimpleNamespace(
            minimum_net_profit_lamports=100_000,
            contingency_lamports=100_000,
        )


@pytest.mark.asyncio
async def test_application_wires_snapshot_detector_to_shadow_handler() -> None:
    now = time.time()
    source = RecordedSnapshotSource(
        (
            _quote(
                input_mint=SOL,
                output_mint=USDC,
                in_amount=1_000_000_000,
                out_amount=110_000_000,
                observed_at=now,
            ),
            _quote(
                input_mint=USDC,
                output_mint=SOL,
                in_amount=110_000_000,
                out_amount=1_002_000_000,
                observed_at=now,
            ),
        )
    )
    app = build_application(
        _Config((_pair(cooldown_seconds=60.0),)),
        market_state=source,
    )

    await app.run()
    for _ in range(20):
        if app.context.result_sink.results:
            break
        await asyncio.sleep(0.02)
    await app.stop()

    assert app.executable_strategies()[0].name == "circular_arbitrage"
    assert app.context.result_sink.results
    result = app.context.result_sink.results[0]
    assert result.status is OpportunityResultStatus.SHADOW_NOT_EXECUTED
