"""PR-123 hardened outbound HTTP/RPC transport primitives.

This module treats provider and RPC responses as hostile input. It does not
perform live network I/O; it defines the fail-closed policy checks and bounded
parsers that outbound clients must use before trusting response bodies,
redirects, retry headers, or proxy configuration.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import hashlib
import ipaddress
import json
import os
import random
import re
from typing import Iterable, Mapping
from urllib.parse import urljoin, urlsplit
import zlib

PR123_SCHEMA_VERSION = "pr123.hardened-transport.v1"
_JSON_CONTENT_TYPES = frozenset(
    {
        "application/json",
        "application/json-rpc",
        "application/problem+json",
    }
)
_DEFAULT_ALLOWED_ENCODINGS = frozenset({"identity", "gzip"})
_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_CREDENTIAL_HEADER_RE = re.compile(
    r"(authorization|proxy-authorization|cookie|x-api-key|api-key|token)",
    re.IGNORECASE,
)


class PR123TransportError(ValueError):
    """Raised when a transport boundary is violated."""


@dataclass(frozen=True, slots=True)
class PR123TransportLimits:
    """Bounded parser limits for hostile HTTP/RPC responses."""

    max_compressed_bytes: int = 1_048_576
    max_decompressed_bytes: int = 2_097_152
    max_json_depth: int = 32
    max_array_length: int = 5_000
    max_object_fields: int = 512
    max_string_length: int = 16_384
    max_redirects: int = 0

    def validate(self) -> None:
        values = asdict(self)
        for name, value in values.items():
            if not isinstance(value, int) or value < 0:
                raise PR123TransportError(f"PR123_LIMIT_INVALID:{name}")


@dataclass(frozen=True, slots=True)
class PR123RetryPolicy:
    """Retry policy with total deadline and deterministic capped backoff."""

    total_deadline_seconds: float = 8.0
    base_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0
    jitter_fraction: float = 0.2
    retry_statuses: tuple[int, ...] = (408, 425, 429, 500, 502, 503, 504)
    fatal_statuses: tuple[int, ...] = (400, 401, 403, 404, 409, 422)

    def validate(self) -> None:
        if self.total_deadline_seconds <= 0:
            raise PR123TransportError("PR123_RETRY_DEADLINE_INVALID")
        if self.base_backoff_seconds <= 0 or self.max_backoff_seconds <= 0:
            raise PR123TransportError("PR123_RETRY_BACKOFF_INVALID")
        if not 0 <= self.jitter_fraction <= 1:
            raise PR123TransportError("PR123_RETRY_JITTER_INVALID")


@dataclass(frozen=True, slots=True)
class PR123TransportPolicy:
    """Fail-closed outbound policy for public provider/RPC endpoints."""

    allowed_hosts: tuple[str, ...]
    expected_content_types: tuple[str, ...] = tuple(sorted(_JSON_CONTENT_TYPES))
    expected_encodings: tuple[str, ...] = tuple(sorted(_DEFAULT_ALLOWED_ENCODINGS))
    allow_redirects: bool = False
    allow_private_networks: bool = False
    allow_proxy_env: bool = False
    tls_verify: bool = True

    def validate(self) -> None:
        if not self.allowed_hosts:
            raise PR123TransportError("PR123_ALLOWED_HOSTS_EMPTY")
        if not self.tls_verify:
            raise PR123TransportError("PR123_TLS_VERIFY_DISABLED")
        for host in self.allowed_hosts:
            _validate_hostname(host, "allowed_hosts")


@dataclass(frozen=True, slots=True)
class PR123GuardedJson:
    """Parsed response plus redacted integrity evidence."""

    payload: object
    compressed_sha256: str
    decompressed_sha256: str
    compressed_bytes: int
    decompressed_bytes: int
    content_type: str
    content_encoding: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def guarded_json_response(
    *,
    headers: Mapping[str, str],
    chunks: Iterable[bytes],
    limits: PR123TransportLimits,
    policy: PR123TransportPolicy,
) -> PR123GuardedJson:
    """Read and parse JSON from bounded chunks after transport validation."""

    body, compressed_hash, compressed_bytes, encoding = read_bounded_body(
        headers=headers,
        chunks=chunks,
        limits=limits,
        policy=policy,
    )
    try:
        payload = json.loads(body.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise PR123TransportError("PR123_BODY_UTF8_INVALID") from exc
    except json.JSONDecodeError as exc:
        raise PR123TransportError(f"PR123_JSON_INVALID:{exc.msg}") from exc

    validate_json_shape(payload, limits)
    return PR123GuardedJson(
        payload=payload,
        compressed_sha256=compressed_hash,
        decompressed_sha256=sha256_hex(body),
        compressed_bytes=compressed_bytes,
        decompressed_bytes=len(body),
        content_type=normalize_content_type(headers.get("Content-Type", "")),
        content_encoding=encoding,
    )


def read_bounded_body(
    *,
    headers: Mapping[str, str],
    chunks: Iterable[bytes],
    limits: PR123TransportLimits,
    policy: PR123TransportPolicy,
) -> tuple[bytes, str, int, str]:
    """Stream chunks through compressed and decompressed byte limits."""

    limits.validate()
    policy.validate()
    content_type = normalize_content_type(headers.get("Content-Type", ""))
    if content_type not in set(policy.expected_content_types):
        raise PR123TransportError(f"PR123_CONTENT_TYPE_DENIED:{content_type}")

    encoding = normalize_content_encoding(headers.get("Content-Encoding", ""))
    if encoding not in set(policy.expected_encodings):
        raise PR123TransportError(f"PR123_CONTENT_ENCODING_DENIED:{encoding}")

    compressed_seen = 0
    compressed_hash = hashlib.sha256()
    if encoding == "identity":
        output_parts: list[bytes] = []
        output_seen = 0
        for chunk in chunks:
            _require_bytes(chunk)
            compressed_seen += len(chunk)
            if compressed_seen > limits.max_compressed_bytes:
                raise PR123TransportError("PR123_COMPRESSED_BODY_TOO_LARGE")
            compressed_hash.update(chunk)
            output_seen += len(chunk)
            if output_seen > limits.max_decompressed_bytes:
                raise PR123TransportError("PR123_DECOMPRESSED_BODY_TOO_LARGE")
            output_parts.append(chunk)
        return (
            b"".join(output_parts),
            compressed_hash.hexdigest(),
            compressed_seen,
            encoding,
        )

    if encoding == "gzip":
        body = _decompress_gzip_bounded(chunks, limits, compressed_hash)
        return body, compressed_hash.hexdigest(), _last_seen.byte_count, encoding

    raise PR123TransportError(f"PR123_CONTENT_ENCODING_UNSUPPORTED:{encoding}")


@dataclass(slots=True)
class _ByteCounter:
    byte_count: int = 0


_last_seen = _ByteCounter()


def _decompress_gzip_bounded(
    chunks: Iterable[bytes],
    limits: PR123TransportLimits,
    compressed_hash: "hashlib._Hash",
) -> bytes:
    output_parts: list[bytes] = []
    output_seen = 0
    compressed_seen = 0
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)

    for chunk in chunks:
        _require_bytes(chunk)
        compressed_seen += len(chunk)
        if compressed_seen > limits.max_compressed_bytes:
            raise PR123TransportError("PR123_COMPRESSED_BODY_TOO_LARGE")
        compressed_hash.update(chunk)
        remaining = limits.max_decompressed_bytes - output_seen
        data = inflater.decompress(chunk, remaining + 1)
        output_seen += len(data)
        if output_seen > limits.max_decompressed_bytes:
            raise PR123TransportError("PR123_DECOMPRESSED_BODY_TOO_LARGE")
        output_parts.append(data)

    tail = inflater.flush()
    output_seen += len(tail)
    if output_seen > limits.max_decompressed_bytes:
        raise PR123TransportError("PR123_DECOMPRESSED_BODY_TOO_LARGE")
    output_parts.append(tail)
    _last_seen.byte_count = compressed_seen
    return b"".join(output_parts)


def validate_json_shape(value: object, limits: PR123TransportLimits) -> None:
    """Validate JSON depth, collection widths, and string sizes."""

    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > limits.max_json_depth:
            raise PR123TransportError("PR123_JSON_DEPTH_EXCEEDED")
        if isinstance(current, str):
            if len(current) > limits.max_string_length:
                raise PR123TransportError("PR123_JSON_STRING_TOO_LONG")
        elif isinstance(current, list):
            if len(current) > limits.max_array_length:
                raise PR123TransportError("PR123_JSON_ARRAY_TOO_LONG")
            stack.extend((item, depth + 1) for item in current)
        elif isinstance(current, dict):
            if len(current) > limits.max_object_fields:
                raise PR123TransportError("PR123_JSON_OBJECT_TOO_WIDE")
            for key, item in current.items():
                if not isinstance(key, str):
                    raise PR123TransportError("PR123_JSON_OBJECT_KEY_INVALID")
                if len(key) > limits.max_string_length:
                    raise PR123TransportError("PR123_JSON_KEY_TOO_LONG")
                stack.append((item, depth + 1))


def validate_outbound_url(url: str, policy: PR123TransportPolicy) -> str:
    """Validate scheme, host, allowlist and private-network policy."""

    policy.validate()
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise PR123TransportError("PR123_URL_SCHEME_DENIED")
    if parsed.username or parsed.password:
        raise PR123TransportError("PR123_URL_CREDENTIALS_DENIED")
    host = parsed.hostname or ""
    _validate_hostname(host, "url_host")
    if host not in set(policy.allowed_hosts):
        raise PR123TransportError(f"PR123_HOST_NOT_ALLOWLISTED:{host}")
    if not policy.allow_private_networks and is_private_or_loopback_host(host):
        raise PR123TransportError(f"PR123_PRIVATE_HOST_DENIED:{host}")
    return host


def validate_redirect(
    *,
    source_url: str,
    location: str,
    policy: PR123TransportPolicy,
    request_headers: Mapping[str, str] | None = None,
) -> str:
    """Validate one redirect target, denying redirects by default."""

    if not policy.allow_redirects:
        raise PR123TransportError("PR123_REDIRECT_DENIED")
    source = urlsplit(source_url)
    target_url = urljoin(source_url, location)
    target = urlsplit(target_url)
    if target.username or target.password:
        raise PR123TransportError("PR123_REDIRECT_CREDENTIAL_URL_DENIED")
    source_host = source.hostname or ""
    target_host = target.hostname or ""
    headers = request_headers or {}
    if source_host != target_host and has_credential_headers(headers):
        raise PR123TransportError("PR123_CREDENTIAL_REDIRECT_BLOCKED")
    validate_outbound_url(target_url, policy)
    return target_url


def validate_proxy_environment(
    *,
    policy: PR123TransportPolicy,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Reject ambient proxy inheritance unless explicitly configured."""

    values = environ if environ is not None else os.environ
    present = tuple(name for name in _PROXY_ENV_KEYS if values.get(name))
    if present and not policy.allow_proxy_env:
        joined = ",".join(sorted(present))
        raise PR123TransportError(f"PR123_PROXY_ENV_DENIED:{joined}")
    return present


def parse_retry_after(value: str, *, now: datetime | None = None) -> float:
    """Parse numeric and HTTP-date Retry-After values."""

    text = value.strip()
    if not text:
        raise PR123TransportError("PR123_RETRY_AFTER_EMPTY")
    if text.isdecimal():
        return float(max(0, int(text)))

    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError) as exc:
        raise PR123TransportError("PR123_RETRY_AFTER_INVALID") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, (parsed - reference).total_seconds())


def retry_delay_seconds(
    *,
    attempt: int,
    policy: PR123RetryPolicy,
    retry_after: str | None = None,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> float:
    """Return bounded exponential backoff with optional Retry-After floor."""

    policy.validate()
    if attempt < 0:
        raise PR123TransportError("PR123_RETRY_ATTEMPT_INVALID")
    exponential = min(
        policy.max_backoff_seconds,
        policy.base_backoff_seconds * (2**attempt),
    )
    random_source = rng if rng is not None else random.Random(0)
    jitter_span = exponential * policy.jitter_fraction
    jitter = random_source.uniform(-jitter_span, jitter_span)
    delay = max(0.0, exponential + jitter)
    if retry_after is not None:
        delay = max(delay, parse_retry_after(retry_after, now=now))
    return min(delay, policy.total_deadline_seconds)


def should_retry_status(status_code: int, policy: PR123RetryPolicy) -> bool:
    """Classify retryable versus fatal status codes."""

    policy.validate()
    if status_code in policy.fatal_statuses:
        return False
    return status_code in policy.retry_statuses


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return headers with credential-bearing fields removed."""

    redacted: dict[str, str] = {}
    for name, value in sorted(headers.items(), key=lambda item: item[0].lower()):
        if _CREDENTIAL_HEADER_RE.search(name):
            redacted[name] = "<redacted>"
        else:
            redacted[name] = value
    return redacted


def has_credential_headers(headers: Mapping[str, str]) -> bool:
    return any(_CREDENTIAL_HEADER_RE.search(name) for name in headers)


def redacted_transport_fingerprint(
    *,
    method: str,
    url: str,
    request_headers: Mapping[str, str],
    response_headers: Mapping[str, str],
    body: bytes,
) -> dict[str, str]:
    """Return request/response hash evidence without exposing credentials."""

    evidence = {
        "method": method.upper(),
        "url_host": urlsplit(url).hostname or "",
        "request_headers": redact_headers(request_headers),
        "response_headers": redact_headers(response_headers),
        "body_sha256": sha256_hex(body),
    }
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": PR123_SCHEMA_VERSION,
        "fingerprint_sha256": sha256_hex(encoded),
        "body_sha256": evidence["body_sha256"],
    }


def normalize_content_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def normalize_content_encoding(value: str) -> str:
    text = value.strip().lower()
    return "identity" if not text else text


def is_private_or_loopback_host(host: str) -> bool:
    lowered = host.strip().lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"}:
        return True
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_hostname(host: str, field: str) -> None:
    if not host or "/" in host or "\\" in host or "@" in host:
        raise PR123TransportError(f"PR123_HOST_INVALID:{field}")
    if len(host) > 253:
        raise PR123TransportError(f"PR123_HOST_TOO_LONG:{field}")


def _require_bytes(value: object) -> None:
    if not isinstance(value, bytes):
        raise PR123TransportError("PR123_RESPONSE_CHUNK_NOT_BYTES")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run PR-123 hardened transport offline self-check."
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    policy = PR123TransportPolicy(allowed_hosts=("api.jup.ag",))
    limits = PR123TransportLimits(max_decompressed_bytes=4096)
    result = guarded_json_response(
        headers={"Content-Type": "application/json"},
        chunks=[b'{"ok":true,"schema":"pr123"}'],
        limits=limits,
        policy=policy,
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("PR-123 hardened transport self-check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PR123GuardedJson",
    "PR123RetryPolicy",
    "PR123_SCHEMA_VERSION",
    "PR123TransportError",
    "PR123TransportLimits",
    "PR123TransportPolicy",
    "guarded_json_response",
    "has_credential_headers",
    "is_private_or_loopback_host",
    "main",
    "normalize_content_encoding",
    "normalize_content_type",
    "parse_retry_after",
    "read_bounded_body",
    "redact_headers",
    "redacted_transport_fingerprint",
    "retry_delay_seconds",
    "sha256_hex",
    "should_retry_status",
    "validate_json_shape",
    "validate_outbound_url",
    "validate_proxy_environment",
    "validate_redirect",
]
