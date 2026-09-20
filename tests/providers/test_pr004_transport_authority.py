from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from src.routing.transport import (
    HttpxJsonTransport,
    SanitizedTransportError,
    TransportPolicy,
)


def _transport(handler, **policy_overrides):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
    )
    policy = TransportPolicy(**policy_overrides)
    return (
        HttpxJsonTransport(
            policy=policy,
            allowed_hosts=frozenset({"provider.example"}),
            client=client,
        ),
        client,
    )


def test_network_transport_requires_an_explicit_host_allowlist() -> None:
    with pytest.raises(ValueError, match="allowed_hosts"):
        HttpxJsonTransport()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b'{"answer":1,"answer":2}', "invalid JSON"),
        (b'{"answer":NaN}', "invalid JSON"),
        (b'{"answer":Infinity}', "invalid JSON"),
    ],
)
def test_strict_json_rejects_duplicate_keys_and_non_finite_numbers(
    body: bytes, message: str
) -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=body,
                request=request,
            )

        transport, client = _transport(handler)
        try:
            with pytest.raises(SanitizedTransportError, match=message):
                await transport.request("GET", "https://provider.example/read")
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_content_type_and_declared_body_size_are_fail_closed() -> None:
    async def scenario() -> None:
        responses = iter(
            (
                ("text/html", {}, b"<html>secret</html>"),
                ("application/json", {"content-length": "999"}, b"{}"),
            )
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            content_type, headers, body = next(responses)
            return httpx.Response(
                200,
                headers={"content-type": content_type, **headers},
                content=body,
                request=request,
            )

        transport, client = _transport(handler, max_response_bytes=32)
        try:
            with pytest.raises(SanitizedTransportError, match="content type"):
                await transport.request("GET", "https://provider.example/read")
            with pytest.raises(SanitizedTransportError, match="too large"):
                await transport.request("GET", "https://provider.example/read")
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_retry_after_supports_delta_and_http_date() -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    parse = HttpxJsonTransport._retry_after_seconds
    assert parse({"retry-after": "3"}, 10, now=now) == 3
    assert parse({"retry-after": "Fri, 31 Jul 2026 12:00:05 GMT"}, 10, now=now) == 5


def test_one_total_deadline_bounds_retries_and_backoff() -> None:
    async def scenario() -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                503,
                headers={"content-type": "application/json"},
                json={"untrusted": "failure"},
                request=request,
            )

        transport, client = _transport(
            handler,
            max_attempts=20,
            total_timeout_seconds=0.03,
            backoff_base_seconds=0.02,
        )
        try:
            with pytest.raises(SanitizedTransportError, match="timed out"):
                await transport.request("GET", "https://provider.example/read")
            assert calls < 20
        finally:
            await client.aclose()

    asyncio.run(scenario())
