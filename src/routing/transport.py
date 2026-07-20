"""Shared asynchronous JSON transport for the PR-030 discovery plane."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit, urlunsplit

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


def sanitize_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def redact_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    return {
        key: ("<redacted>" if key.lower() in _SECRET_HEADER_NAMES else value)
        for key, value in (headers or {}).items()
    }


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
        self.allowed_hosts = allowed_hosts
        self._owns_client = client is None
        timeout = httpx.Timeout(
            connect=self.policy.connect_timeout_seconds,
            read=self.policy.read_timeout_seconds,
            write=self.policy.write_timeout_seconds,
            pool=self.policy.pool_timeout_seconds,
        )
        self._client = client or httpx.AsyncClient(timeout=timeout)

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
        if (
            self.allowed_hosts is not None
            and parsed.hostname not in self.allowed_hosts
        ):
            raise SanitizedTransportError(
                f"provider host is not allowlisted: {parsed.hostname}"
            )

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
