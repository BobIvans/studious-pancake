from __future__ import annotations

import hashlib
from pathlib import Path
import ssl

import httpx
import pytest

from src.routing.transport import (
    HttpxJsonTransport,
    SanitizedTransportError,
    TransportPolicy,
    build_tls_context,
    sanitize_url,
)

pytestmark = pytest.mark.unit


def test_pr185_sanitizer_removes_userinfo_query_and_fragment() -> None:
    safe = sanitize_url(
        "https://alice:supersecret@example.com/path?api_key=hidden#fragment"
    )

    assert safe == "https://example.com/path"
    assert "alice" not in safe
    assert "supersecret" not in safe
    assert "api_key" not in safe


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "message"),
    (
        ("https://alice:secret@example.com/path", "credentials"),
        ("https://example.com/path#fragment", "fragments"),
        ("https://example.com/path?api_key=secret", "query"),
        ("https://example.com.:443/path", "canonical"),
        ("https://example.com:8443/path", "port"),
        ("https://127.0.0.1/path", "private"),
    ),
)
async def test_pr185_rejects_unsafe_endpoint_identity(
    url: str,
    message: str,
) -> None:
    transport = HttpxJsonTransport(allowed_hosts=frozenset({"example.com"}))
    try:
        with pytest.raises(SanitizedTransportError, match=message):
            transport._validate_url(url)
    finally:
        await transport.aclose()


@pytest.mark.asyncio
async def test_pr185_default_httpx_client_ignores_ambient_environment() -> None:
    transport = HttpxJsonTransport(allowed_hosts=frozenset({"example.com"}))
    try:
        assert transport._client._trust_env is False
        assert transport._client.follow_redirects is False
    finally:
        await transport.aclose()


def test_pr185_tls_context_is_explicit_and_evidenced() -> None:
    policy = TransportPolicy()
    context, evidence = build_tls_context(policy)
    ca_bytes = Path(evidence.ca_bundle_path).read_bytes()

    assert context.check_hostname is True
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert evidence.ca_bundle_sha256 == hashlib.sha256(ca_bytes).hexdigest()
    assert evidence.verify_mode == "CERT_REQUIRED"


def test_pr185_ca_bundle_drift_fails_closed() -> None:
    policy = TransportPolicy(expected_ca_bundle_sha256="0" * 64)

    with pytest.raises(ValueError, match="digest"):
        build_tls_context(policy)


@pytest.mark.asyncio
async def test_pr185_request_uses_safe_allowlisted_transport() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "example.com"
        assert request.url.params["limit"] == "1"
        return httpx.Response(200, json={"ok": True}, request=request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
        follow_redirects=False,
    )
    transport = HttpxJsonTransport(
        allowed_hosts=frozenset({"example.com"}),
        client=client,
    )
    try:
        status, _, payload = await transport.request(
            "GET",
            "https://example.com/v1/data",
            params={"limit": "1"},
        )
    finally:
        await client.aclose()

    assert status == 200
    assert payload == {"ok": True}


def test_pr185_policy_rejects_tls_downgrade() -> None:
    with pytest.raises(ValueError, match="TLS 1.2"):
        TransportPolicy(minimum_tls_version=ssl.TLSVersion.TLSv1_1)
