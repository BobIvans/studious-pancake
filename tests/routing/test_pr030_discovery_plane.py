from __future__ import annotations

import asyncio
from datetime import timedelta
import json
from pathlib import Path
from typing import Any

import pytest

from src.routing.clients import (
    JupiterRouterAdapter,
    OdosAdapter,
    OkxDexAdapter,
    OpenOceanAdapter,
)
from src.routing.models import (
    MinimumOutputState,
    ProviderCapability,
    ProviderFailureReason,
    ProviderRole,
    QuoteRequest,
)
from src.routing.registry import (
    DiscoveryPlane,
    ProviderRegistry,
    RouteDiscoveryService,
)
from src.routing.transport import redact_headers, sanitize_url


SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
WALLET = "11111111111111111111111111111111"
FIXTURES = json.loads(
    (
        Path(__file__).parents[1]
        / "fixtures"
        / "routing"
        / "pr030_provider_responses.json"
    ).read_text()
)


class RecordedTransport:
    def __init__(
        self,
        responses: dict[str, tuple[int, dict[str, str], Any]],
    ) -> None:
        self.responses = responses
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
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "json_body": json_body,
            }
        )
        return self.responses[url]


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
async def test_four_providers_share_one_candidate_schema() -> None:
    transport = RecordedTransport(
        {
            JupiterRouterAdapter.endpoint: (200, {}, FIXTURES["jupiter"]),
            OkxDexAdapter.endpoint: (200, {}, FIXTURES["okx"]),
            OpenOceanAdapter.endpoint: (200, {}, FIXTURES["openocean"]),
            OdosAdapter.endpoint: (200, {}, FIXTURES["odos"]),
        }
    )
    registry = ProviderRegistry(
        (
            JupiterRouterAdapter(api_key="jup-secret", transport=transport),
            OkxDexAdapter(
                api_key="okx-key",
                passphrase="okx-pass",
                secret="okx-secret",
                transport=transport,
            ),
            OpenOceanAdapter(api_key="oo-secret", transport=transport),
            OdosAdapter(transport=transport),
        )
    )

    batch = await DiscoveryPlane(registry).discover(request())

    assert not batch.failures
    assert {quote.provider for quote in batch.quotes} == {
        "jupiter_router",
        "okx_dex",
        "openocean",
        "odos",
    }
    assert all(quote.input_amount == 1_000_000 for quote in batch.quotes)
    assert all(quote.input_decimals == 9 for quote in batch.quotes)
    assert all(quote.output_decimals == 6 for quote in batch.quotes)
    assert all(quote.provenance is not None for quote in batch.quotes)
    assert all(quote.correlation_labels for quote in batch.quotes)

    classification = RouteDiscoveryService(registry).classify(batch.quotes)
    assert tuple(
        quote.provider for quote in classification.executable_candidates
    ) == ("jupiter_router",)
    assert next(
        quote
        for quote in batch.quotes
        if quote.provider == "openocean"
    ).minimum_output_state is MinimumOutputState.UNPROVEN


@pytest.mark.asyncio
async def test_provider_failure_isolated_and_unknown_schema_fails_closed() -> None:
    broken = dict(FIXTURES["jupiter"])
    broken.pop("swapInstruction")
    transport = RecordedTransport(
        {
            JupiterRouterAdapter.endpoint: (200, {}, broken),
            OdosAdapter.endpoint: (200, {}, FIXTURES["odos"]),
        }
    )
    registry = ProviderRegistry(
        (
            JupiterRouterAdapter(api_key="jup-secret", transport=transport),
            OdosAdapter(transport=transport),
        )
    )

    batch = await DiscoveryPlane(registry).discover(request())

    assert tuple(quote.provider for quote in batch.quotes) == ("odos",)
    assert len(batch.failures) == 1
    assert batch.failures[0].provider == "jupiter_router"
    assert batch.failures[0].reason is ProviderFailureReason.INVALID_SCHEMA


@pytest.mark.asyncio
async def test_missing_credentials_disable_only_affected_providers() -> None:
    transport = RecordedTransport(
        {OdosAdapter.endpoint: (200, {}, FIXTURES["odos"])}
    )
    registry = ProviderRegistry.from_env({}, transport=transport)

    report = {row["provider"]: row for row in registry.startup_report()}
    assert report["jupiter_router"]["state"] == "ready"
    assert report["okx_dex"]["state"] == "disabled_missing_credentials"
    assert report["openocean"]["state"] == "disabled_missing_credentials"
    assert report["odos"]["state"] == "discovery_only"

    batch = await DiscoveryPlane(registry).discover(request())
    assert tuple(quote.provider for quote in batch.quotes) == ("odos",)
    assert {failure.provider for failure in batch.failures} == {"jupiter_router"}
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_cancellation_is_not_converted_to_provider_failure() -> None:
    class BlockingTransport:
        async def request(self, *_: Any, **__: Any):
            await asyncio.Event().wait()

    plane = DiscoveryPlane(
        ProviderRegistry((OdosAdapter(transport=BlockingTransport()),)),
        provider_timeout_seconds=60,
    )
    task = asyncio.create_task(plane.discover(request()))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_capability_taxonomy_keeps_non_jupiter_out_of_planner() -> None:
    assert (
        JupiterRouterAdapter.capabilities.discovery_capability
        is ProviderCapability.COMPOSABLE_INSTRUCTIONS
    )
    assert (
        OkxDexAdapter.capabilities.discovery_capability
        is ProviderCapability.COMPOSABLE_INSTRUCTIONS
    )
    assert OkxDexAdapter.capabilities.role is ProviderRole.DISCOVERY_ONLY
    assert (
        OpenOceanAdapter(api_key="x").capabilities.discovery_capability
        is ProviderCapability.QUOTE_ONLY
    )
    assert (
        OdosAdapter.capabilities.discovery_capability
        is ProviderCapability.IMMUTABLE_TRANSACTION
    )


def test_secrets_and_query_values_are_redacted_from_diagnostics() -> None:
    assert sanitize_url(
        "https://api.example.test/path?apiKey=secret&amount=10"
    ) == "https://api.example.test/path"
    redacted = redact_headers(
        {
            "x-api-key": "secret",
            "OK-ACCESS-SIGN": "signature",
            "content-type": "application/json",
        }
    )
    assert redacted["x-api-key"] == "<redacted>"
    assert redacted["OK-ACCESS-SIGN"] == "<redacted>"
    assert redacted["content-type"] == "application/json"


def test_stale_quote_is_discovery_visible_but_not_executable() -> None:
    adapter = JupiterRouterAdapter()
    quote = adapter.normalize_build(request(), FIXTURES["jupiter"])
    service = RouteDiscoveryService(ProviderRegistry((adapter,)))
    result = service.classify(
        (quote,),
        now=quote.expires_at + timedelta(seconds=1),
    )
    assert result.discovery_candidates == (quote,)
    assert result.executable_candidates == ()


def test_external_contract_registry_is_authoritative() -> None:
    class Value:
        def __init__(self, value: str):
            self.value = value

    class Contract:
        def __init__(
            self,
            contract_id: str,
            status: str,
            capabilities: tuple[str, ...],
        ) -> None:
            self.id = contract_id
            self.status = Value(status)
            self.capabilities = tuple(Value(item) for item in capabilities)
            self.source_ref = "recorded-test-pin"

    class Registry:
        contracts = {
            "jupiter": Contract(
                "jupiter.swap-v2-build",
                "active",
                ("quote", "composable-instructions"),
            ),
            "okx": Contract("okx.solana", "discovery-only", ("quote",)),
            "openocean": Contract(
                "openocean.solana", "discovery-only", ("quote",)
            ),
            "odos": Contract(
                "odos.solana",
                "discovery-only",
                ("quote", "immutable-transaction"),
            ),
        }

        def provider(self, name: str):
            return (self.contracts[name],)

    registry = ProviderRegistry.from_env(
        {
            "JUPITER_API_KEY": "j",
            "OKX_API_KEY": "o",
            "OKX_PASSPHRASE": "p",
            "OKX_SECRET_KEY": "s",
            "OPENOCEAN_API_KEY": "oo",
        },
        contract_registry=Registry(),
    )
    roles = {
        adapter.provider_id: adapter.capabilities.role
        for adapter in registry.adapters
    }
    assert roles == {
        "jupiter_router": ProviderRole.EXECUTABLE,
        "okx_dex": ProviderRole.DISCOVERY_ONLY,
        "openocean": ProviderRole.DISCOVERY_ONLY,
        "odos": ProviderRole.DISCOVERY_ONLY,
    }
