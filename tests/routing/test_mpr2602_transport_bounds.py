import asyncio
import httpx
import pytest
from src.routing.transport import (
    HttpxJsonTransport,
    SanitizedTransportError,
    TransportPolicy,
)


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


def make(stream, status=200, **policy):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                status, headers={"content-type": "application/json"}, stream=stream
            )
        ),
        trust_env=False,
    )
    return (
        HttpxJsonTransport(
            client=client,
            allowed_hosts=frozenset({"example.com"}),
            policy=TransportPolicy(**policy),
        ),
        client,
    )


@pytest.mark.asyncio
async def test_stream_stops_before_reading_entire_oversized_body():
    stream = Chunks([b" " * 32] * 100)
    transport, client = make(stream, max_response_bytes=64)
    async with client:
        with pytest.raises(SanitizedTransportError):
            await transport.request("GET", "https://example.com/data")
    assert stream.reads <= 3
    assert stream.closed


@pytest.mark.asyncio
async def test_json_depth_rejected_before_recursive_parser():
    stream = Chunks([b"[" * 2000 + b"0" + b"]" * 2000])
    transport, client = make(stream)
    async with client:
        with pytest.raises(SanitizedTransportError):
            await transport.request("GET", "https://example.com/data")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 429, 503])
async def test_gzip_bomb_bounded_and_closed(status):
    import gzip

    stream = Chunks([gzip.compress(b"x" * 1_000_000)])
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                status,
                headers={
                    "content-type": "application/json",
                    "content-encoding": "gzip",
                },
                stream=stream,
            )
        ),
        trust_env=False,
    )
    transport = HttpxJsonTransport(
        client=client,
        allowed_hosts=frozenset({"example.com"}),
        policy=TransportPolicy(max_response_bytes=64),
    )
    async with client:
        with pytest.raises(SanitizedTransportError, match="too large") as caught:
            await transport.request("GET", "https://example.com/data")
    assert caught.value.status_code == status
    assert stream.closed


@pytest.mark.asyncio
async def test_guard_rechecks_after_429_and_can_revoke():
    calls = []
    guards = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(429, json={}, headers={"retry-after": "0"})

    async def guard(request, attempt):
        guards.append((request.method, bytes(request.content), attempt))
        if attempt == 2:
            raise SanitizedTransportError("revoked")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        transport = HttpxJsonTransport(
            client=client, allowed_hosts=frozenset({"example.com"}), attempt_guard=guard
        )
        with pytest.raises(SanitizedTransportError, match="revoked"):
            await transport.request(
                "POST", "https://example.com/data", json_body={"x": 1}
            )
    assert len(calls) == 1
    assert [x[2] for x in guards] == [1, 2]


@pytest.mark.asyncio
async def test_cancel_read_closes_response():
    entered = asyncio.Event()

    class Hanging(Chunks):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b"{}"

    stream = Hanging([])
    transport, client = make(stream)
    async with client:
        task = asyncio.create_task(transport.request("GET", "https://example.com/data"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [b'{"x":1e999}', b'{"x":"\xff"}', b'{"x":1,"x":2}', b'{"' + b"x" * 100 + b'":1}'],
)
async def test_strict_decoding_does_not_expose_body(body):
    stream = Chunks([body])
    transport, client = make(stream, max_string_length=32)
    async with client:
        with pytest.raises(SanitizedTransportError) as caught:
            await transport.request("GET", "https://example.com/data")
    assert body.decode("utf8", errors="ignore") not in str(caught.value)
    assert stream.closed


@pytest.mark.asyncio
async def test_redirect_is_never_followed():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://127.0.0.1/secret"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        transport = HttpxJsonTransport(
            client=client, allowed_hosts=frozenset({"example.com"})
        )
        with pytest.raises(SanitizedTransportError, match="redirect"):
            await transport.request("GET", "https://example.com/data")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_three_attempts_each_guarded():
    issued, calls = [], []

    async def guard(request, attempt):
        issued.append(attempt)

    async def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) < 3 else 200, json={"ok": True})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        transport = HttpxJsonTransport(
            client=client,
            allowed_hosts=frozenset({"example.com"}),
            attempt_guard=guard,
            policy=TransportPolicy(max_attempts=3, backoff_base_seconds=0),
        )
        assert (await transport.request("GET", "https://example.com/data"))[2] == {
            "ok": True
        }
    assert issued == [1, 2, 3]
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_first_guard_denial_has_zero_effects():
    calls = []

    async def guard(request, attempt):
        raise SanitizedTransportError("disabled")

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        transport = HttpxJsonTransport(
            client=client, allowed_hosts=frozenset({"example.com"}), attempt_guard=guard
        )
        with pytest.raises(SanitizedTransportError, match="disabled"):
            await transport.request("GET", "https://example.com/data")
    assert calls == []


@pytest.mark.asyncio
async def test_valid_gzip_stream_and_trailing_member_rejection():
    import gzip

    for trailing in (False, True):
        encoded = gzip.compress(b'{"ok":true}')
        if trailing:
            encoded += gzip.compress(b"{}")
        stream = Chunks([encoded[:5], encoded[5:]])
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    headers={
                        "content-type": "application/json",
                        "content-encoding": "gzip",
                    },
                    stream=stream,
                )
            ),
            trust_env=False,
        ) as client:
            transport = HttpxJsonTransport(
                client=client, allowed_hosts=frozenset({"example.com"})
            )
            if trailing:
                with pytest.raises(SanitizedTransportError, match="compressed"):
                    await transport.request("GET", "https://example.com/data")
            else:
                assert (await transport.request("GET", "https://example.com/data"))[
                    2
                ] == {"ok": True}
        assert stream.closed
