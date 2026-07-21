from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.market.snapshots import MarketQuoteSnapshot, SnapshotSet
from src.providers.jupiter.quota import JupiterQuotaManager
from src.routing.clients import JupiterRouterAdapter
from src.routing.models import (
    DiscoveryBatch,
    MinimumOutputState,
    NormalizedQuote,
    QuoteProvenance,
    QuoteRequest,
    SwapMode,
)
from src.runtime_discovery import (
    RuntimeDiscoveryCoordinator,
    RuntimeDiscoveryPair,
    RuntimeDiscoveryUniverse,
)
from src.strategy.detectors import CircularArbitrageDetector, DetectorPair

pytestmark = pytest.mark.unit

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WALLET = "11111111111111111111111111111111"


def _pair() -> DetectorPair:
    return DetectorPair(
        pair_id="sol-usdc-loop",
        base_mint=SOL,
        intermediate_mint=USDC,
        probe_amount_base_units=100,
        min_gross_profit_base_units=1,
        max_snapshot_age_seconds=10.0,
        ttl_seconds=2.0,
        cooldown_seconds=0.0,
        max_slot_skew=0,
    )


def _runtime_pair() -> RuntimeDiscoveryPair:
    return RuntimeDiscoveryPair(
        pair=_pair(),
        base_decimals=9,
        intermediate_decimals=6,
        required=True,
    )


def _snapshot(
    *,
    input_mint: str,
    output_mint: str,
    in_amount: int,
    out_amount: int,
    provider: str = "jupiter_router",
    quote_id: str,
    request_fingerprint: str,
    response_hash: str,
    slot: int = 100,
) -> MarketQuoteSnapshot:
    return MarketQuoteSnapshot(
        provider=provider,
        input_mint=input_mint,
        output_mint=output_mint,
        in_amount=in_amount,
        out_amount=out_amount,
        slot=slot,
        observed_at=1_700_000_000.0,
        expires_at=1_700_000_010.0,
        commitment="confirmed",
        quote_id=quote_id,
        request_fingerprint=request_fingerprint,
        response_hash=response_hash,
    )


def _normalized_quote(
    request: QuoteRequest,
    *,
    output: int,
    suffix: str,
    slot: int = 100,
) -> NormalizedQuote:
    now = datetime.now(timezone.utc)
    provider = "jupiter_router"
    capabilities = replace(
        JupiterRouterAdapter.capabilities,
        provider_id=provider,
    )
    labels = (f"amount:{request.amount_base_units}",)
    return NormalizedQuote(
        provider=provider,
        request_fingerprint=request.fingerprint,
        raw_response_hash=f"hash-{suffix}",
        external_id=f"quote-{suffix}",
        input_mint=request.input_mint,
        output_mint=request.output_mint,
        input_amount=request.amount_base_units,
        expected_output=output,
        minimum_output=max(1, output - 1),
        minimum_output_state=MinimumOutputState.PROVEN,
        swap_mode=SwapMode.EXACT_IN,
        slippage_bps=request.slippage_bps,
        route_provenance=("Raydium",),
        dex_sources=("Raydium",),
        price_impact_pct="0.01",
        provider_fee=None,
        platform_fee=None,
        context_slot=slot,
        received_at=now,
        expires_at=now + timedelta(seconds=30),
        artifact_kind=capabilities.artifact_kind,
        capabilities=capabilities,
        diagnostic_trace_id=f"trace-{suffix}",
        input_decimals=request.input_decimals,
        output_decimals=request.output_decimals,
        provider_timestamp=now,
        correlation_labels=labels,
        provenance=QuoteProvenance(
            provider=provider,
            endpoint="https://provider.invalid/build",
            schema_version_pin="fixture-v1",
            response_hash=f"hash-{suffix}",
            context_slot=slot,
            provider_timestamp=now,
            correlation_labels=labels,
        ),
    )


class MultiFirstLegPlane:
    def __init__(self) -> None:
        self.calls: list[QuoteRequest] = []

    async def discover(self, request: QuoteRequest) -> DiscoveryBatch:
        self.calls.append(request)
        if request.input_mint == SOL:
            return DiscoveryBatch(
                request.fingerprint,
                (
                    _normalized_quote(request, output=110, suffix="first-110"),
                    _normalized_quote(request, output=120, suffix="first-120"),
                ),
            )
        return DiscoveryBatch(
            request.fingerprint,
            (
                _normalized_quote(
                    request,
                    output=request.amount_base_units + 1,
                    suffix=f"second-{request.amount_base_units}",
                ),
            ),
        )


def test_detector_rejects_second_leg_quote_obtained_for_wrong_amount() -> None:
    detector = CircularArbitrageDetector((_pair(),))
    first = _snapshot(
        input_mint=SOL,
        output_mint=USDC,
        in_amount=100,
        out_amount=120,
        quote_id="first",
        request_fingerprint="first-100",
        response_hash="first-hash",
    )
    wrong_second = _snapshot(
        input_mint=USDC,
        output_mint=SOL,
        in_amount=130,
        out_amount=150,
        quote_id="second-wrong",
        request_fingerprint="second-130",
        response_hash="second-hash",
    )

    opportunities = detector.detect(
        SnapshotSet((first, wrong_second)),
        now=1_700_000_001.0,
    )

    assert opportunities == ()
    rejection = detector.last_rejections["sol-usdc-loop"]
    assert rejection.reason_code == "second_leg_amount_mismatch"
    assert rejection.details["second_leg_amount_mismatches"] == 1


def test_detector_uses_exact_second_leg_amount_and_integer_profit() -> None:
    detector = CircularArbitrageDetector((_pair(),))
    first = _snapshot(
        input_mint=SOL,
        output_mint=USDC,
        in_amount=100,
        out_amount=120,
        quote_id="first",
        request_fingerprint="first-100",
        response_hash="first-hash",
    )
    exact_second = _snapshot(
        input_mint=USDC,
        output_mint=SOL,
        in_amount=120,
        out_amount=105,
        quote_id="second-exact",
        request_fingerprint="second-120",
        response_hash="second-hash",
    )

    opportunities = detector.detect(
        SnapshotSet((first, exact_second)),
        now=1_700_000_001.0,
    )

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.expected_gross_profit == 5
    assert isinstance(opportunity.expected_gross_profit, int)
    assert opportunity.metadata["amount_coupled_quotes"] is True
    assert opportunity.metadata["route"][0]["in_amount"] == 100
    assert opportunity.metadata["route"][0]["out_amount"] == 120
    assert opportunity.metadata["route"][1]["in_amount"] == 120
    assert opportunity.metadata["route"][1]["out_amount"] == 105
    assert len(opportunity.metadata["route_identity"]) == 64


@pytest.mark.asyncio
async def test_coordinator_requests_second_leg_for_each_exact_first_output() -> None:
    plane = MultiFirstLegPlane()
    coordinator = RuntimeDiscoveryCoordinator(
        plane=plane,
        universe=RuntimeDiscoveryUniverse(
            schema_version="pr056.discovery-universe.v1",
            pairs=(_runtime_pair(),),
            cycle_timeout_seconds=1.0,
            provider_timeout_seconds=0.5,
            max_concurrent_pairs=1,
        ),
        user_wallet=WALLET,
        commitment="confirmed",
        jupiter_quota=JupiterQuotaManager(),
    )

    report = await coordinator.run_cycle()

    assert report.evidence.cycle_succeeded is True
    assert report.evidence.requests_attempted == 3
    second_amounts = [request.amount_base_units for request in plane.calls[1:]]
    assert second_amounts == [110, 120]
    assert len(report.opportunities) == 1
    route = report.opportunities[0].metadata["route"]
    assert (
        route[1]["in_amount"]
        == report.opportunities[0].metadata["intermediate_amount_base_units"]
    )
    assert route[1]["request_fingerprint"] in {
        plane.calls[1].fingerprint,
        plane.calls[2].fingerprint,
    }
