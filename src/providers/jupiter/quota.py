"""Account-wide Jupiter quota accounting.

This module intentionally has no HTTP client dependency. It provides the
process-local fallback quota boundary that every Jupiter caller can share inside
one runtime process. MEGA-PR-01 V6 adds ``DurableJupiterQuotaManager`` in
``src.providers.jupiter.durable_quota`` for API-account-wide cross-process and
restart-safe enforcement.

Runtime code must still honour 429/Retry-After and telemetry must tune the
configured budget.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Deque, Iterable, Mapping
from uuid import uuid4


class JupiterQuotaPurpose(str, Enum):
    """Quota buckets used by the PR-031 scheduler."""

    DISCOVERY = "discovery"
    REFINEMENT = "refinement"
    FINALIZATION = "finalization"

    @classmethod
    def normalize(cls, value: "JupiterQuotaPurpose | str") -> "JupiterQuotaPurpose":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value))
        except ValueError:
            # Unknown callers are treated as discovery so they cannot consume the
            # reserved finalization budget by accident.
            return cls.DISCOVERY


@dataclass(frozen=True)
class QuotaReservation:
    """A reserved Jupiter request slot.

    ``issued`` is tracked by the manager's event log rather than mutating this
    object, so the token stays hashable and safe to pass through async code.
    """

    reservation_id: str
    purpose: JupiterQuotaPurpose
    reserved_at: float
    request_fingerprint: str = ""


@dataclass
class JupiterQuotaMetrics:
    reserved: int = 0
    used: int = 0
    released: int = 0
    denied: int = 0
    rate_limited_429s: int = 0
    finalization_reserve_starvation: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_queue_seconds: float = 0.0
    circuit_state: str = "ready"
    retry_after_until: float | None = None
    last_denial_reason: str | None = None

    def snapshot(self, *, now: float | None = None) -> dict[str, int | float | str | None]:
        retry_for: float | None = None
        if now is not None and self.retry_after_until is not None:
            retry_for = max(0.0, self.retry_after_until - now)
        return {
            "reserved": self.reserved,
            "used": self.used,
            "released": self.released,
            "denied": self.denied,
            "rate_limited_429s": self.rate_limited_429s,
            "finalization_reserve_starvation": self.finalization_reserve_starvation,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "total_queue_seconds": self.total_queue_seconds,
            "circuit_state": self.circuit_state,
            "retry_after_for_seconds": retry_for,
            "last_denial_reason": self.last_denial_reason,
        }


@dataclass
class _QuotaEvent:
    token: QuotaReservation
    issued: bool = False


@dataclass
class CachedQuotaDecision:
    """Tiny deterministic cache for identical quote/build requests."""

    value: object
    expires_at: float
    provenance: Mapping[str, str] = field(default_factory=dict)


class JupiterQuotaError(RuntimeError):
    """Raised when the account-wide budget is exhausted or cooling down."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class JupiterQuotaManager:
    """Sliding-window Jupiter quota manager shared by one active process."""

    def __init__(
        self,
        limit: int = 60,
        window_seconds: float = 60.0,
        finalization_reserve: int = 4,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if finalization_reserve < 0 or finalization_reserve >= limit:
            raise ValueError("finalization_reserve must be >= 0 and smaller than limit")
        self.limit = int(limit)
        self.window = float(window_seconds)
        self.finalization_reserve = int(finalization_reserve)
        self.clock = clock
        self._events: Deque[_QuotaEvent] = deque()
        self._lock = asyncio.Lock()
        self._cache: dict[str, CachedQuotaDecision] = {}
        self.metrics = JupiterQuotaMetrics()

    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0].token.reserved_at >= self.window:
            self._events.popleft()
        expired = [key for key, item in self._cache.items() if item.expires_at <= now]
        for key in expired:
            self._cache.pop(key, None)
        if self.metrics.retry_after_until is not None and self.metrics.retry_after_until <= now:
            self.metrics.retry_after_until = None
            if self.metrics.circuit_state == "rate_limited":
                self.metrics.circuit_state = "ready"

    def _capacity_for(self, purpose: JupiterQuotaPurpose) -> int:
        if purpose is JupiterQuotaPurpose.FINALIZATION:
            return self.limit
        return max(0, self.limit - self.finalization_reserve)

    def _deny(self, reason: str) -> None:
        self.metrics.denied += 1
        self.metrics.last_denial_reason = reason
        self.metrics.circuit_state = "rate_limited"

    async def reserve(
        self,
        purpose: JupiterQuotaPurpose | str = JupiterQuotaPurpose.DISCOVERY,
        *,
        request_fingerprint: str = "",
    ) -> QuotaReservation:
        """Reserve one quota slot before issuing a Jupiter request.

        Non-finalization callers cannot consume the protected finalization
        reserve.  Finalization can use the whole configured window because it is
        the proof-critical quote/build path that follows capital and route
        prechecks.
        """

        normalized = JupiterQuotaPurpose.normalize(purpose)
        start = self.clock()
        async with self._lock:
            now = self.clock()
            self._prune(now)
            if self.metrics.retry_after_until is not None and now < self.metrics.retry_after_until:
                self._deny("retry-after-active")
                raise JupiterQuotaError("retry-after-active")

            cap = self._capacity_for(normalized)
            if len(self._events) >= cap:
                if normalized is not JupiterQuotaPurpose.FINALIZATION:
                    self.metrics.finalization_reserve_starvation += 1
                self._deny("account-wide-quota-exhausted")
                raise JupiterQuotaError("account-wide-quota-exhausted")

            token = QuotaReservation(
                reservation_id=uuid4().hex,
                purpose=normalized,
                reserved_at=now,
                request_fingerprint=request_fingerprint,
            )
            self._events.append(_QuotaEvent(token=token))
            self.metrics.reserved += 1
            self.metrics.total_queue_seconds += max(0.0, now - start)
            self.metrics.circuit_state = "ready"
            return token

    async def mark_used(self, token: QuotaReservation) -> None:
        async with self._lock:
            for event in self._events:
                if event.token == token:
                    event.issued = True
                    self.metrics.used += 1
                    return

    async def release_unissued(self, token: QuotaReservation) -> None:
        async with self._lock:
            for event in tuple(self._events):
                if event.token == token and not event.issued:
                    self._events.remove(event)
                    self.metrics.released += 1
                    return

    def record_429(self, retry_after: float | None = None) -> None:
        """Compatibility wrapper for existing router code."""

        self.record_http_429(retry_after)

    def record_http_429(self, retry_after: float | None = None) -> None:
        now = self.clock()
        self.metrics.rate_limited_429s += 1
        self.metrics.circuit_state = "rate_limited"
        if retry_after is not None:
            self.metrics.retry_after_until = max(
                self.metrics.retry_after_until or now,
                now + max(0.0, retry_after),
            )

    def snapshot(self) -> dict[str, int | float | str | None]:
        now = self.clock()
        self._prune(now)
        return self.metrics.snapshot(now=now) | {
            "limit": self.limit,
            "window_seconds": self.window,
            "finalization_reserve": self.finalization_reserve,
            "window_occupancy": len(self._events),
            "cache_size": len(self._cache),
        }

    def cache_get(self, key: str) -> object | None:
        now = self.clock()
        self._prune(now)
        item = self._cache.get(key)
        if item is None:
            self.metrics.cache_misses += 1
            return None
        self.metrics.cache_hits += 1
        return item.value

    def cache_put(
        self,
        key: str,
        value: object,
        *,
        ttl_seconds: float,
        provenance: Mapping[str, str] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            return
        self._cache[key] = CachedQuotaDecision(
            value=value,
            expires_at=self.clock() + ttl_seconds,
            provenance=provenance or {},
        )

    def active_purposes(self) -> tuple[JupiterQuotaPurpose, ...]:
        now = self.clock()
        self._prune(now)
        return tuple(event.token.purpose for event in self._events)


def _cache_identity_part(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not (value == value and value not in (float("inf"), float("-inf"))):
            raise ValueError("cache identity does not allow non-finite floats")
        return value
    if isinstance(value, tuple):
        return [_cache_identity_part(item) for item in value]
    if isinstance(value, list):
        return [_cache_identity_part(item) for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in sorted(value.items(), key=lambda entry: str(entry[0])):
            if not isinstance(key, (str, int, bool)):
                raise TypeError("cache identity mapping keys must be JSON-compatible scalars")
            normalized[str(key)] = _cache_identity_part(item)
        return normalized
    raise TypeError(f"cache identity does not support value type: {type(value).__name__}")


def cache_key(parts: Iterable[object]) -> str:
    """Collision-resistant cache key for semantic quote/build request identity.

    The old delimiter-joined key made ``("a|b", "c")`` collide with
    ``("a", "b|c")``. MEGA-PR-01 V6 requires canonical encoding before quota
    spend, so the supported key is now the SHA-256 digest of a strict JSON
    envelope with type-preserving values and deterministic ordering.
    """

    payload = {
        "schema_version": "mega-pr-01.jupiter-cache-key.v2",
        "parts": [_cache_identity_part(part) for part in parts],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return "jupiter-cache:v2:" + hashlib.sha256(encoded).hexdigest()
