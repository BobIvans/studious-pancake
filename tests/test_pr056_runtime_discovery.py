from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

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
    build_runtime_discovery,
)
from src.strategy.detectors import DetectorPair

pytestmark = pytest.mark.unit

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
JITOSOL = "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"
WALLET = "11111111111111111111111111111111"


def _runtime_pair(
    *,
    pair_id: str = "sol-usdc-loop",
    intermediate_mint: str = USDC,
    required: bool = True,
) -> RuntimeDiscoveryPair:
    return RuntimeDiscoveryPair(
        pair=DetectorPair(
            pair_id=pair_id,
            base_mint=SOL,
            intermediate_mint=intermediate_mint,
            probe_amount_base_units=100_000_000,
            min_gross_profit_base_units=100_000,
            max_snapshot_age_seconds=5.0,
            ttl_seconds=2.0,
            cooldown_seconds=0.0,
            max_slot_skew=2,
        ),
        base_decimals=9,
        intermediate_decimals=6 if intermediate_mint == USDC else 9,
        required=required,
    )


def _universe(*pairs: RuntimeDiscoveryPair, max_candidates: int = 64):
    return RuntimeDiscoveryUniverse(
        schema_version="pr056.discovery-universe.v1",
        pairs=tuple(pairs) or (_runtime_pair(),),
        cycle_timeout_seconds=1.0,
        provider_timeout_seconds=0.5,
        max_concurrent_pairs=1,
        max_candidates=max_candidates,
    )


def _quote(
    request: QuoteRequest,
    *,
    output: int,
    slot: int = 100,
    provider: str = "jupiter_router",
    suffix: str = "a",
) -> NormalizedQuote:
    now = datetime.now(timezone.utc)
    capabilities = replace(
        JupiterRouterAdapter.capabilities,
        provider_id=provider,
    )
    labels = (f"aggregator:{provider}", "underlying:raydium")
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
            endpoint="https://provider.invalid/quote",
            schema_version_pin="fixture-v1",
            response_hash=f"hash-{suffix}",
            context_slot=slot,
            provider_timestamp=now,
            correlation_labels=labels,
        ),
    )


class RecordedPlane:
    def __init__(self, *, duplicate_first: bool = False, missing_slot: bool = False):
        self.calls: list[QuoteRequest] = []
        self.duplicate_first = duplicate_first
        self.missing_slot = missing_slot
        self.active = 0
        self.peak_active = 0

    async def discover(self, request: QuoteRequest) -> DiscoveryBatch:
        self.calls.append(request)
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        try:
            first_leg = request.input_mint == SOL
            output = 110_000_000 if first_leg else 101_000_000
            quote = _quote(
                request,
                output=output,
                slot=100,
                suffix=f"{len(self.calls)}-{request.output_mint[:4]}",
            )
            if self.missing_slot:
                quote = replace(quote, context_slot=None)
            quotes = (quote, quote) if self.duplicate_first and first_leg else (quote,)
            return DiscoveryBatch(request.fingerprint, quotes)
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_cycle_creates_provenance_rich_candidate_and_deduplicates() -> None:
    plane = RecordedPlane(duplicate_first=True)
    quota = JupiterQuotaManager()
    coordinator = RuntimeDiscoveryCoordinator(
        plane=plane,
        universe=_universe(_runtime_pair()),
        user_wallet=WALLET,
        commitment="confirmed",
        jupiter_quota=quota,
    )

    report = await coordinator.run_cycle()

    assert report.evidence.cycle_succeeded is True
    assert report.evidence.requests_attempted == 2
    assert report.evidence.duplicate_snapshots_dropped == 1
    assert len(report.opportunities) == 1
    route = report.opportunities[0].metadata["route"]
    assert route[0]["commitment"] == "confirmed"
    assert route[0]["request_fingerprint"] == plane.calls[0].fingerprint
    assert "underlying:raydium" in route[0]["correlation_labels"]
    assert any(label.startswith("cycle:") for label in route[0]["correlation_labels"])
    assert coordinator.jupiter_quota is quota


@pytest.mark.asyncio
async def test_required_route_without_slot_provenance_blocks_cycle() -> None:
    plane = RecordedPlane(missing_slot=True)
    coordinator = RuntimeDiscoveryCoordinator(
        plane=plane,
        universe=_universe(_runtime_pair()),
        user_wallet=WALLET,
        commitment="confirmed",
    )

    report = await coordinator.run_cycle()

    assert report.opportunities == ()
    assert report.evidence.cycle_succeeded is False
    assert report.evidence.terminal_reason == "blocked_required_discovery_incomplete"
    assert report.evidence.completed_required_pairs == ()


@pytest.mark.asyncio
async def test_missing_wallet_blocks_before_any_provider_call() -> None:
    plane = RecordedPlane()
    coordinator = RuntimeDiscoveryCoordinator(
        plane=plane,
        universe=_universe(_runtime_pair()),
        user_wallet=None,
        commitment="confirmed",
    )

    report = await coordinator.run_cycle()

    assert report.evidence.cycle_succeeded is False
    assert report.evidence.terminal_reason == "blocked_missing_wallet_public_key"
    assert plane.calls == []


@pytest.mark.asyncio
async def test_candidate_queue_is_bounded_and_pair_work_is_backpressured() -> None:
    plane = RecordedPlane()
    coordinator = RuntimeDiscoveryCoordinator(
        plane=plane,
        universe=_universe(
            _runtime_pair(),
            _runtime_pair(
                pair_id="sol-jitosol-loop",
                intermediate_mint=JITOSOL,
                required=False,
            ),
            max_candidates=1,
        ),
        user_wallet=WALLET,
        commitment="confirmed",
    )

    report = await coordinator.run_cycle()

    assert report.evidence.cycle_succeeded is True
    assert len(report.opportunities) == 1
    assert report.evidence.candidates_dropped_backpressure == 1
    assert plane.peak_active <= 1


def test_builder_reuses_one_account_wide_jupiter_quota_manager() -> None:
    config = SimpleNamespace(
        providers=SimpleNamespace(
            jupiter=SimpleNamespace(
                enabled=True,
                api_key_reference=SimpleNamespace(
                    resolve_from_environment=lambda _env: "secret"
                ),
            )
        ),
        wallet=SimpleNamespace(public_key=WALLET),
        cluster=SimpleNamespace(commitment=SimpleNamespace(value="confirmed")),
    )
    coordinator = build_runtime_discovery(
        config,
        environ={},
        universe=_universe(_runtime_pair()),
        contract_registry=SimpleNamespace(provider=lambda _name: ()),
    )

    jupiter = next(
        adapter
        for adapter in coordinator.plane.registry.adapters
        if adapter.provider_id == "jupiter_router"
    )
    assert jupiter.quota is coordinator.jupiter_quota
