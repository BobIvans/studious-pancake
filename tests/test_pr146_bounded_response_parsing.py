from __future__ import annotations

import json
from typing import Any

import pytest

from src.routing.transport import (
    HttpxJsonTransport,
    SanitizedTransportError,
    TransportPolicy,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any = None,
        *,
        headers: dict[str, str] | None = None,
        raw: bytes | None = None,
    ) -> None:
        self.status_code = status_code
        body = raw if raw is not None else json.dumps(payload).encode()
        self.content = body
        self.headers = headers or {
            "content-type": "application/json",
            "content-length": str(len(body)),
        }


class FakeClient:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def request(self, *args: object, **kwargs: object) -> FakeResponse:
        self.calls += 1
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_pr146_accepts_small_bounded_json_payload() -> None:
    client = FakeClient(FakeResponse(200, {"ok": True}))
    transport = HttpxJsonTransport(
        client=client,
        allowed_hosts=frozenset({"quote-api.jup.ag"}),
    )

    status, headers, payload = await transport.request(
        "GET",
        "https://quote-api.jup.ag/swap/v1/quote?secret=hidden",
    )

    assert status == 200
    assert headers["content-type"] == "application/json"
    assert payload == {"ok": True}


@pytest.mark.asyncio
async def test_pr146_content_length_above_limit_fails_before_parsing() -> None:
    client = FakeClient(
        FakeResponse(
            200,
            {"ignored": True},
            headers={
                "content-type": "application/json",
                "content-length": "1000",
            },
        )
    )
    transport = HttpxJsonTransport(
        client=client,
        policy=TransportPolicy(max_response_bytes=10),
    )

    with pytest.raises(SanitizedTransportError) as exc:
        await transport.request(
            "GET",
            "https://quote-api.jup.ag/swap/v1/quote?api_key=secret",
        )

    assert "exceeded response byte limit" in str(exc.value)
    assert "api_key" not in str(exc.value)
    assert exc.value.status_code == 200
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_pr146_actual_body_above_limit_fails_without_content_length() -> None:
    client = FakeClient(
        FakeResponse(
            200,
            headers={"content-type": "application/json"},
            raw=b'{"payload":"' + (b"x" * 50) + b'"}',
        )
    )
    transport = HttpxJsonTransport(
        client=client,
        policy=TransportPolicy(max_response_bytes=20),
    )

    with pytest.raises(SanitizedTransportError) as exc:
        await transport.request("POST", "https://example.com/rpc")

    assert "exceeded response byte limit" in str(exc.value)


@pytest.mark.asyncio
async def test_pr146_non_json_content_type_is_rejected() -> None:
    client = FakeClient(
        FakeResponse(
            200,
            raw=b"<html>not json</html>",
            headers={
                "content-type": "text/html; charset=utf-8",
                "content-length": "21",
            },
        )
    )
    transport = HttpxJsonTransport(client=client)

    with pytest.raises(SanitizedTransportError) as exc:
        await transport.request("GET", "https://example.com/api")

    assert "non-JSON content type" in str(exc.value)


@pytest.mark.asyncio
async def test_pr146_json_suffix_content_type_is_accepted() -> None:
    client = FakeClient(
        FakeResponse(
            400,
            {"error": "bad-request"},
            headers={
                "content-type": "application/problem+json",
                "content-length": "24",
            },
        )
    )
    transport = HttpxJsonTransport(client=client)

    status, _, payload = await transport.request("GET", "https://example.com/api")

    assert status == 400
    assert payload == {"error": "bad-request"}


@pytest.mark.asyncio
async def test_pr146_over_nested_json_is_rejected() -> None:
    payload: dict[str, Any] = {"value": "leaf"}
    for _ in range(5):
        payload = {"nested": payload}
    client = FakeClient(FakeResponse(200, payload))
    transport = HttpxJsonTransport(
        client=client,
        policy=TransportPolicy(max_json_depth=4),
    )

    with pytest.raises(SanitizedTransportError) as exc:
        await transport.request("GET", "https://example.com/api")

    assert "over-nested JSON" in str(exc.value)


@pytest.mark.asyncio
async def test_pr146_over_wide_json_is_rejected() -> None:
    client = FakeClient(FakeResponse(200, {"items": list(range(20))}))
    transport = HttpxJsonTransport(
        client=client,
        policy=TransportPolicy(max_json_nodes=10),
    )

    with pytest.raises(SanitizedTransportError) as exc:
        await transport.request("GET", "https://example.com/api")

    assert "oversized JSON" in str(exc.value)


@pytest.mark.asyncio
async def test_pr146_retry_response_is_not_schema_parsed_before_retry() -> None:
    retry = FakeResponse(
        429,
        raw=b"<html>retry</html>",
        headers={
            "content-type": "text/html",
            "content-length": "18",
            "retry-after": "0",
        },
    )
    success = FakeResponse(200, {"ok": True})
    client = FakeClient(retry, success)
    transport = HttpxJsonTransport(
        client=client,
        policy=TransportPolicy(max_attempts=2, backoff_base_seconds=0.0),
    )

    status, _, payload = await transport.request("GET", "https://example.com/api")

    assert status == 200
    assert payload == {"ok": True}
    assert client.calls == 2


def test_pr146_policy_bounds_must_be_positive_integers() -> None:
    with pytest.raises(ValueError):
        TransportPolicy(max_response_bytes=0)
    with pytest.raises(ValueError):
        TransportPolicy(max_json_depth=False)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        TransportPolicy(max_json_nodes=0)
