from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.providers.jupiter.quota import JupiterQuotaManager
from src.routing.clients import JupiterRouterAdapter
from src.routing.models import ProviderFailureReason, QuoteRequest
from src.routing.registry import DiscoveryPlane, ProviderRegistry

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WALLET = "11111111111111111111111111111111"
FIXTURE = json.loads(
    (
        Path(__file__).parents[1]
        / "fixtures"
        / "routing"
        / "pr030_provider_responses.json"
    ).read_text(encoding="utf-8")
)["jupiter"]


class RecordedTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        self.calls.append({"method": method, "url": url})
        return 200, {}, FIXTURE


def request() -> QuoteRequest:
    return QuoteRequest(
        input_mint=SOL,
        output_mint=USDC,
        amount_base_units=1_000_000,
        user_wallet=WALLET,
        slippage_bps=50,
        input_decimals=9,
        output_decimals=6,
    )


@pytest.mark.asyncio
async def test_jupiter_discovery_uses_shared_pr031_quota() -> None:
    transport = RecordedTransport()
    quota = JupiterQuotaManager(limit=2, finalization_reserve=1)
    adapter = JupiterRouterAdapter(
        api_key="jup-secret",
        transport=transport,
        jupiter_quota=quota,
    )
    plane = DiscoveryPlane(ProviderRegistry((adapter,)))

    first = await plane.discover(request())
    second = await plane.discover(request())

    assert len(first.quotes) == 1
    assert not first.failures
    assert not second.quotes
    assert second.failures[0].reason is ProviderFailureReason.RATE_LIMITED
    assert quota.metrics.used == 1
    assert len(transport.calls) == 1
