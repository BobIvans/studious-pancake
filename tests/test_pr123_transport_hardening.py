from __future__ import annotations

from datetime import UTC, datetime
import gzip
import json
import random

import pytest

from src.transport_hardening_pr123 import (
    PR123RetryPolicy,
    PR123TransportError,
    PR123TransportLimits,
    PR123TransportPolicy,
    guarded_json_response,
    is_private_or_loopback_host,
    parse_retry_after,
    redacted_transport_fingerprint,
    retry_delay_seconds,
    should_retry_status,
    validate_outbound_url,
    validate_proxy_environment,
    validate_redirect,
)

_POLICY = PR123TransportPolicy(allowed_hosts=("api.jup.ag", "rpc.helius.xyz"))


def test_pr123_accepts_small_streamed_json_and_hashes_body() -> None:
    result = guarded_json_response(
        headers={"Content-Type": "application/json; charset=utf-8"},
        chunks=[b'{"jsonrpc":"2.0",', b'"result":[1,2,3]}'],
        limits=PR123TransportLimits(max_decompressed_bytes=128),
        policy=_POLICY,
    )

    assert result.payload == {"jsonrpc": "2.0", "result": [1, 2, 3]}
    assert result.compressed_bytes == result.decompressed_bytes
    assert len(result.compressed_sha256) == 64
    assert len(result.decompressed_sha256) == 64


def test_pr123_rejects_unbounded_identity_response() -> None:
    with pytest.raises(PR123TransportError, match="PR123_DECOMPRESSED_BODY_TOO_LARGE"):
        guarded_json_response(
            headers={"Content-Type": "application/json"},
            chunks=[b'{"payload":"', b"x" * 200, b'"}'],
            limits=PR123TransportLimits(
                max_compressed_bytes=512,
                max_decompressed_bytes=64,
            ),
            policy=_POLICY,
        )


def test_pr123_rejects_gzip_decompression_bomb() -> None:
    compressed = gzip.compress(b'{"payload":"' + (b"x" * 300) + b'"}')

    with pytest.raises(PR123TransportError, match="PR123_DECOMPRESSED_BODY_TOO_LARGE"):
        guarded_json_response(
            headers={
                "Content-Type": "application/json",
                "Content-Encoding": "gzip",
            },
            chunks=[compressed[:12], compressed[12:]],
            limits=PR123TransportLimits(
                max_compressed_bytes=1024,
                max_decompressed_bytes=128,
            ),
            policy=_POLICY,
        )


def test_pr123_rejects_deep_json_and_wide_containers() -> None:
    headers = {"Content-Type": "application/json"}
    limits = PR123TransportLimits(
        max_json_depth=2,
        max_array_length=3,
        max_object_fields=3,
        max_string_length=8,
    )

    for payload, error in (
        ({"a": {"b": {"c": 1}}}, "PR123_JSON_DEPTH_EXCEEDED"),
        ([1, 2, 3, 4], "PR123_JSON_ARRAY_TOO_LONG"),
        ({"a": 1, "b": 2, "c": 3, "d": 4}, "PR123_JSON_OBJECT_TOO_WIDE"),
        ({"a": "123456789"}, "PR123_JSON_STRING_TOO_LONG"),
    ):
        with pytest.raises(PR123TransportError, match=error):
            guarded_json_response(
                headers=headers,
                chunks=[json.dumps(payload).encode()],
                limits=limits,
                policy=_POLICY,
            )


def test_pr123_rejects_content_type_encoding_and_proxy_env() -> None:
    with pytest.raises(PR123TransportError, match="PR123_CONTENT_TYPE_DENIED"):
        guarded_json_response(
            headers={"Content-Type": "text/html"},
            chunks=[b"{}"],
            limits=PR123TransportLimits(),
            policy=_POLICY,
        )

    with pytest.raises(PR123TransportError, match="PR123_CONTENT_ENCODING_DENIED"):
        guarded_json_response(
            headers={
                "Content-Type": "application/json",
                "Content-Encoding": "br",
            },
            chunks=[b"{}"],
            limits=PR123TransportLimits(),
            policy=_POLICY,
        )

    with pytest.raises(PR123TransportError, match="PR123_PROXY_ENV_DENIED"):
        validate_proxy_environment(
            policy=_POLICY,
            environ={"HTTPS_PROXY": "http://127.0.0.1:8080"},
        )


def test_pr123_url_redirect_and_private_network_policy_are_fail_closed() -> None:
    validate_outbound_url("https://api.jup.ag/swap/v1/quote", _POLICY)

    with pytest.raises(PR123TransportError, match="PR123_URL_SCHEME_DENIED"):
        validate_outbound_url("http://api.jup.ag/swap/v1/quote", _POLICY)

    with pytest.raises(PR123TransportError, match="PR123_HOST_NOT_ALLOWLISTED"):
        validate_outbound_url("https://evil.example/quote", _POLICY)

    with pytest.raises(PR123TransportError, match="PR123_REDIRECT_DENIED"):
        validate_redirect(
            source_url="https://api.jup.ag/quote",
            location="https://rpc.helius.xyz/",
            policy=_POLICY,
        )

    redirect_policy = PR123TransportPolicy(
        allowed_hosts=("api.jup.ag", "rpc.helius.xyz"),
        allow_redirects=True,
    )
    assert (
        validate_redirect(
            source_url="https://api.jup.ag/quote",
            location="https://api.jup.ag/next",
            policy=redirect_policy,
            request_headers={"Authorization": "Bearer secret"},
        )
        == "https://api.jup.ag/next"
    )

    with pytest.raises(PR123TransportError, match="PR123_CREDENTIAL_REDIRECT_BLOCKED"):
        validate_redirect(
            source_url="https://api.jup.ag/quote",
            location="https://rpc.helius.xyz/",
            policy=redirect_policy,
            request_headers={"Authorization": "Bearer secret"},
        )

    with pytest.raises(
        PR123TransportError, match="PR123_REDIRECT_CREDENTIAL_URL_DENIED"
    ):
        validate_redirect(
            source_url="https://api.jup.ag/quote",
            location="https://user:pass@api.jup.ag/next",
            policy=redirect_policy,
        )

    private_policy = PR123TransportPolicy(
        allowed_hosts=("127.0.0.1",),
        allow_redirects=True,
    )
    assert is_private_or_loopback_host("127.0.0.1") is True
    with pytest.raises(PR123TransportError, match="PR123_PRIVATE_HOST_DENIED"):
        validate_outbound_url("https://127.0.0.1/rpc", private_policy)


def test_pr123_retry_after_and_redacted_hash_evidence() -> None:
    now = datetime(2026, 7, 21, 20, 0, tzinfo=UTC)
    assert parse_retry_after("3", now=now) == 3.0
    assert parse_retry_after("Tue, 21 Jul 2026 20:00:05 GMT", now=now) == 5.0

    retry_policy = PR123RetryPolicy(
        total_deadline_seconds=10.0,
        base_backoff_seconds=1.0,
        max_backoff_seconds=4.0,
        jitter_fraction=0.0,
    )
    assert should_retry_status(429, retry_policy) is True
    assert should_retry_status(401, retry_policy) is False
    assert (
        retry_delay_seconds(
            attempt=2,
            policy=retry_policy,
            retry_after="5",
            now=now,
            rng=random.Random(1),
        )
        == 5.0
    )

    evidence = redacted_transport_fingerprint(
        method="post",
        url="https://api.jup.ag/quote",
        request_headers={"Authorization": "Bearer real", "Accept": "application/json"},
        response_headers={"X-Request-Id": "abc"},
        body=b'{"ok":true}',
    )
    assert set(evidence) == {
        "schema_version",
        "fingerprint_sha256",
        "body_sha256",
    }
    assert len(evidence["fingerprint_sha256"]) == 64
    assert len(evidence["body_sha256"]) == 64
