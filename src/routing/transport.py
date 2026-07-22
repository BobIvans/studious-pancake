"""Shared asynchronous JSON transport for the discovery plane.

PR-185 hardens the active HTTPX boundary: endpoint URLs are canonicalized,
credentials in URLs are forbidden, redirects and ambient environment trust are
disabled, and TLS verification is constructed explicitly.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import ipaddress
import json
from pathlib import Path
import ssl
from typing import Any, Mapping, Protocol
from urllib.parse import SplitResult, urlsplit, urlunsplit

import certifi
import httpx

_SECRET_HEADER_NAMES = frozenset(
    {
        "authorization",
        "x-api-key",
        "ok-access-key",
        "ok-access-passphrase",
        "ok-access-sign",
        "cookie",
        "set-cookie",
    }
)


class Transport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, str], Any]: ...


@dataclass(frozen=True)
class TransportPolicy:
    connect_timeout_seconds: float = 2.0
    read_timeout_seconds: float = 5.0
    write_timeout_seconds: float = 5.0
    pool_timeout_seconds: float = 2.0
    total_timeout_seconds: float = 7.0
    max_attempts: int = 2
    backoff_base_seconds: float = 0.1
    max_retry_after_seconds: float = 2.0
    allowed_ports: tuple[int, ...] = (443,)
    allow_url_query: bool = False
    allow_private_ip_literals: bool = False
    minimum_tls_version: ssl.TLSVersion = ssl.TLSVersion.TLSv1_2
    ca_bundle_path: str | None = None
    expected_ca_bundle_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        for field_name in (
            "connect_timeout_seconds",
            "read_timeout_seconds",
            "write_timeout_seconds",
            "pool_timeout_seconds",
            "total_timeout_seconds",
        ):
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if not self.allowed_ports or any(
            isinstance(port, bool) or not 1 <= port <= 65_535
            for port in self.allowed_ports
        ):
            raise ValueError("allowed_ports must contain valid TCP ports")
        if self.minimum_tls_version < ssl.TLSVersion.TLSv1_2:
            raise ValueError("minimum_tls_version must be TLS 1.2 or newer")
        if self.expected_ca_bundle_sha256 is not None:
            digest = self.expected_ca_bundle_sha256
            if len(digest) != 64 or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise ValueError("expected_ca_bundle_sha256 must be lowercase sha256")


@dataclass(frozen=True)
class TlsTrustEvidence:
    ca_bundle_path: str
    ca_bundle_sha256: str
    minimum_tls_version: str
    check_hostname: bool
    verify_mode: str


class SanitizedTransportError(RuntimeError):
    """Transport failure that never embeds query parameters or credentials."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def _safe_netloc(parsed: SplitResult) -> str:
    host = parsed.hostname or ""
    display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    try:
        port = parsed.port
    except ValueError:
        port = None
    return f"{display_host}:{port}" if port is not None else display_host


def sanitize_url(url: str) -> str:
    """Return a credential-free URL suitable for logs and errors."""

    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, _safe_netloc(parsed), parsed.path, "", ""))


def redact_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    return {
        key: ("<redacted>" if key.lower() in _SECRET_HEADER_NAMES else value)
        for key, value in (headers or {}).items()
    }


def _canonical_hostname(host: str) -> str:
    if not host or host != host.lower() or host.endswith("."):
        raise SanitizedTransportError("provider host is not canonical")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise SanitizedTransportError("provider host IDNA encoding is invalid") from exc
    if ascii_host != host:
        raise SanitizedTransportError("provider host must use canonical ASCII IDNA")
    return host


def _reject_private_ip_literal(host: str, *, allowed: bool) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    unsafe = (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
    if unsafe and not allowed:
        raise SanitizedTransportError("private or special endpoint address is denied")


def build_tls_context(
    policy: TransportPolicy,
) -> tuple[ssl.SSLContext, TlsTrustEvidence]:
    """Build explicit verified TLS context and record trust-store identity."""

    ca_bundle_path = policy.ca_bundle_path or certifi.where()
    ca_path = Path(ca_bundle_path).resolve()
    if not ca_path.is_file():
        raise ValueError("CA bundle must be a regular file")
    ca_digest = hashlib.sha256(ca_path.read_bytes()).hexdigest()
    if (
        policy.expected_ca_bundle_sha256 is not None
        and ca_digest != policy.expected_ca_bundle_sha256
    ):
        raise ValueError("CA bundle digest does not match reviewed policy")

    context = ssl.create_default_context(cafile=str(ca_path))
    context.minimum_version = policy.minimum_tls_version
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    evidence = TlsTrustEvidence(
        ca_bundle_path=str(ca_path),
        ca_bundle_sha256=ca_digest,
        minimum_tls_version=context.minimum_version.name,
        check_hostname=context.check_hostname,
        verify_mode=ssl.VerifyMode(context.verify_mode).name,
    )
    return context, evidence


class HttpxJsonTransport:
    """Bounded, cancellation-safe JSON transport shared by all providers."""

    def __init__(
        self,
        *,
        policy: TransportPolicy | None = None,
        allowed_hosts: frozenset[str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.policy = policy or TransportPolicy()
        self.allowed_hosts = (
            None
            if allowed_hosts is None
            else frozenset(_canonical_hostname(host) for host in allowed_hosts)
        )
        self._owns_client = client is None
        timeout = httpx.Timeout(
            connect=self.policy.connect_timeout_seconds,
            read=self.policy.read_timeout_seconds,
            write=self.policy.write_timeout_seconds,
            pool=self.policy.pool_timeout_seconds,
        )
        tls_context, tls_evidence = build_tls_context(self.policy)
        self.tls_evidence = tls_evidence
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            verify=tls_context,
            trust_env=False,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "HttpxJsonTransport":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    def _validate_url(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise SanitizedTransportError(
                "provider transport requires an absolute HTTPS endpoint"
            )
        if parsed.username is not None or parsed.password is not None:
            raise SanitizedTransportError("provider URL credentials are forbidden")
        if parsed.fragment:
            raise SanitizedTransportError("provider URL fragments are forbidden")
        if parsed.query and not self.policy.allow_url_query:
            raise SanitizedTransportError(
                "provider URL query is forbidden; use request params"
            )
        host = _canonical_hostname(parsed.hostname)
        try:
            port = parsed.port or 443
        except ValueError as exc:
            raise SanitizedTransportError("provider URL port is invalid") from exc
        if port not in self.policy.allowed_ports:
            raise SanitizedTransportError("provider URL port is not approved")
        _reject_private_ip_literal(
            host,
            allowed=self.policy.allow_private_ip_literals,
        )
        if self.allowed_hosts is not None and host not in self.allowed_hosts:
            raise SanitizedTransportError(f"provider host is not allowlisted: {host}")

    @staticmethod
    def _retry_after_seconds(
        headers: Mapping[str, str], maximum: float
    ) -> float | None:
        raw = headers.get("retry-after")
        if raw is None:
            return None
        try:
            return min(max(float(raw), 0.0), maximum)
        except ValueError:
            return None

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, str], Any]:
        self._validate_url(url)
        safe_target = sanitize_url(url)
        retry_statuses = {429, 500, 502, 503, 504}

        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                response = await asyncio.wait_for(
                    self._client.request(
                        method,
                        url,
                        headers=headers,
                        params=params,
                        json=json_body,
                    ),
                    timeout=self.policy.total_timeout_seconds,
                )
            except asyncio.CancelledError:
                raise
            except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
                if attempt == self.policy.max_attempts:
                    raise SanitizedTransportError(
                        f"{method.upper()} {safe_target} timed out",
                        retryable=True,
                    ) from exc
                await asyncio.sleep(
                    self.policy.backoff_base_seconds * (2 ** (attempt - 1))
                )
                continue
            except httpx.TransportError as exc:
                if attempt == self.policy.max_attempts:
                    raise SanitizedTransportError(
                        f"{method.upper()} {safe_target} transport failed",
                        retryable=True,
                    ) from exc
                await asyncio.sleep(
                    self.policy.backoff_base_seconds * (2 ** (attempt - 1))
                )
                continue

            response_headers = {
                key.lower(): value for key, value in response.headers.items()
            }
            if (
                response.status_code in retry_statuses
                and attempt < self.policy.max_attempts
            ):
                delay = self._retry_after_seconds(
                    response_headers,
                    self.policy.max_retry_after_seconds,
                )
                if delay is None:
                    delay = self.policy.backoff_base_seconds * (
                        2 ** (attempt - 1)
                    )
                await asyncio.sleep(delay)
                continue

            try:
                payload = response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise SanitizedTransportError(
                    f"{method.upper()} {safe_target} returned non-JSON data",
                    status_code=response.status_code,
                    retryable=False,
                ) from exc
            return response.status_code, response_headers, payload

        raise AssertionError("transport retry loop exited unexpectedly")


__all__ = [
    "HttpxJsonTransport",
    "SanitizedTransportError",
    "TlsTrustEvidence",
    "Transport",
    "TransportPolicy",
    "build_tls_context",
    "redact_headers",
    "sanitize_url",
]
