from __future__ import annotations

import asyncio

import pytest

from src.ingest.pyth_auth import PythHermesAuthError, pyth_bearer_headers
from src.ingest.pyth_core_price_feeder import PythCorePriceFeeder
from src.ingest.pyth_oracle_client import PythHermesClient
from src.market.source_catalog import SourceAccess, load_market_source_catalog


def test_pyth_bearer_header_uses_explicit_key_without_logging_or_query_auth() -> None:
    assert pyth_bearer_headers(api_key="secret-value") == {
        "Authorization": "Bearer secret-value"
    }


def test_pyth_reference_resolves_env_secret() -> None:
    assert pyth_bearer_headers(
        api_key_reference="env:PYTH_TEST_KEY",
        environ={"PYTH_TEST_KEY": "secret-value"},
    ) == {"Authorization": "Bearer secret-value"}


def test_pyth_clients_fail_closed_before_network_without_api_key_reference(monkeypatch) -> None:
    monkeypatch.delenv("FLASHLOAN_PYTH_API_KEY_REFERENCE", raising=False)

    async def run() -> None:
        with pytest.raises(PythHermesAuthError):
            await PythHermesClient().start()
        with pytest.raises(PythHermesAuthError):
            await PythCorePriceFeeder().start()

    asyncio.run(run())


def test_market_catalog_records_current_provider_truth() -> None:
    catalog = load_market_source_catalog()
    pyth = catalog.require("pyth-hermes")
    marginfi = catalog.require("marginfi")
    odos = catalog.require("odos")

    assert catalog.checked_at == "2026-10-06"
    assert pyth.access is SourceAccess.FREE_TIER_KEY
    assert "Bearer" in pyth.limitation
    assert any("typescript-sdk/getting-started" in u for u in marginfi.evidence_urls)
    assert "2.8.0" in marginfi.limitation
    assert "shut down permanently" in odos.limitation
