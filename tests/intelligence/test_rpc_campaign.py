"""Provider-independent read scopes and bounded public-RPC 429 behavior."""

import asyncio
import time

import httpx
import pytest

from src.market.native_cpmm_capture import (
    configured_rpc_url,
    public_read_entitlements,
    RPC_PROVIDER,
)
from src.routing.transport import (
    HttpxJsonTransport,
    TransportPolicy,
    SanitizedTransportError,
)


def test_rpc_endpoint_is_environment_selected_and_read_scope_only(monkeypatch):
    monkeypatch.setenv("SOLANA_RPC_HTTP", "https://replacement-rpc.example")
    endpoint = configured_rpc_url()
    assert endpoint == "https://replacement-rpc.example"
    manifest = public_read_entitlements(expires_at_epoch_seconds=2_000_000_000)[
        RPC_PROVIDER
    ]
    assert manifest.allowed_endpoints == (endpoint,)
    assert "sendTransaction" not in manifest.allowed_rpc_methods
    assert manifest.credential_ref == "anonymous-public-read"
    with pytest.raises(ValueError, match="credentials"):
        configured_rpc_url({"SOLANA_RPC_HTTP": "https://user:secret@example.com"})


def test_campaign_missing_public_address_does_not_read_private_key_or_start(tmp_path):
    from src.intelligence.campaign import run_paper_campaign

    class PublicOnly(dict):
        def get(self, key, *args):
            assert key in {"FLASHLOAN_WALLET_PUBLIC_KEY", "SOLANA_RPC_HTTP"}
            return super().get(key, *args)

    receipt = run_paper_campaign(
        tmp_path / "campaign",
        environment=PublicOnly(SOLANA_RPC_HTTP="https://api.mainnet.solana.com"),
    )
    assert receipt["status"] == "BLOCKED"
    assert not receipt["process_started"]
    assert receipt["missing"] == ["FLASHLOAN_WALLET_PUBLIC_KEY"]


def test_long_retry_after_never_shortened_or_immediately_retried():
    async def scenario():
        calls = []

        async def handler(request):
            calls.append(request)
            return httpx.Response(
                429, text="Too many requests", headers={"Retry-After": "60"}
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            trust_env=False,
            follow_redirects=False,
        ) as client:
            transport = HttpxJsonTransport(
                client=client,
                allowed_hosts=frozenset({"rpc.example"}),
                policy=TransportPolicy(max_attempts=3, max_retry_after_seconds=0.1),
            )
            started = time.monotonic()
            for _ in range(2):
                with pytest.raises(SanitizedTransportError, match="cooldown") as caught:
                    await transport.request(
                        "POST", "https://rpc.example", json_body={"method": "getSlot"}
                    )
                assert caught.value.status_code == 429 and caught.value.retryable
            assert len(calls) == 1
            assert time.monotonic() - started < 1

    asyncio.run(scenario())


def test_short_retry_after_retries_read_and_terminal_429_is_typed():
    async def scenario():
        calls = 0

        async def handler(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(429, headers={"Retry-After": "0.001"})
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": "ok", "id": 1})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            trust_env=False,
            follow_redirects=False,
        ) as client:
            transport = HttpxJsonTransport(
                client=client,
                allowed_hosts=frozenset({"rpc.example"}),
                policy=TransportPolicy(backoff_base_seconds=0.001),
            )
            status, _, result = await transport.request(
                "POST", "https://rpc.example", json_body={"method": "getHealth"}
            )
            assert status == 200 and result["result"] == "ok" and calls == 2

    asyncio.run(scenario())
