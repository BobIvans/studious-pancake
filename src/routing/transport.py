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
    max_response_bytes: int = 1_048_576
    max_json_depth: int = 32
    max_json_nodes: int = 50_000
    require_json_content_type: bool = True

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
        for field_name in (
            "max_response_bytes",
            "max_json_depth",
            "max_json_nodes",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if not isinstance(self.require_json_content_type, bool):
            raise ValueError("require_json_content_type must be boolean")


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


def _content_length(headers: Mapping[str, str]) -> int | None:
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed


def _is_json_content_type(raw_content_type: str | None) -> bool:
    if raw_content_type is None:
        return False
    media_type = raw_content_type.split(";", 1)[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


def _json_node_metrics(payload: Any) -> tuple[int, int]:
    nodes = 0
    max_depth = 0
    stack: list[tuple[Any, int]] = [(payload, 1)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        max_depth = max(max_depth, depth)
        if isinstance(item, dict):
            stack.extend((value, depth + 1) for value in item.values())
        elif isinstance(item, list):
            stack.extend((value, depth + 1) for value in item)
    return nodes, max_depth


def _bounded_json_payload(
    response: httpx.Response,
    *,
    method: str,
    safe_target: str,
    response_headers: Mapping[str, str],
    policy: TransportPolicy,
) -> Any:
    content_length = _content_length(response_headers)
    if content_length is not None and content_length > policy.max_response_bytes:
        raise SanitizedTransportError(
            f"{method.upper()} {safe_target} exceeded response byte limit",
            status_code=response.status_code,
            retryable=False,
        )

    if policy.require_json_content_type and not _is_json_content_type(
        response_headers.get("content-type")
    ):
        raise SanitizedTransportError(
            f"{method.upper()} {safe_target} returned non-JSON content type",
            status_code=response.status_code,
            retryable=False,
        )

    body = response.content
    if len(body) > policy.max_response_bytes:
        raise SanitizedTransportError(
            f"{method.upper()} {safe_target} exceeded response byte limit",
            status_code=response.status_code,
            retryable=False,
        )

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SanitizedTransportError(
            f"{method.upper()} {safe_target} returned non-JSON data",
            status_code=response.status_code,
            retryable=False,
        ) from exc

    nodes, depth = _json_node_metrics(payload)
    if depth > policy.max_json_depth:
        raise SanitizedTransportError(
            f"{method.upper()} {safe_target} returned over-nested JSON",
            status_code=response.status_code,
            retryable=False,
        )
    if nodes > policy.max_json_nodes:
        raise SanitizedTransportError(
            f"{method.upper()} {safe_target} returned oversized JSON",
            status_code=response.status_code,
            retryable=False,
        )
    return payload


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

            payload = _bounded_json_payload(
                response,
                method=method,
                safe_target=safe_target,
                response_headers=response_headers,
                policy=self.policy,
            )
            return response.status_code, response_headers, payload

        raise AssertionError("transport retry loop exited unexpectedly")
