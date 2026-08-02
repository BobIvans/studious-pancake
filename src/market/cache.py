"""Bounded immutable generation-aware derived-state cache for MPR-042."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import time
from typing import Any, Awaitable, Callable, Mapping

from .observations import ObservationError


@dataclass(frozen=True, slots=True)
class DerivedCacheKey:
    namespace: str
    logical_key: str
    generation_identity: str
    provenance_hash: str
    provider: str = "unknown"

    def __post_init__(self) -> None:
        for name, value in (
            ("namespace", self.namespace),
            ("logical_key", self.logical_key),
            ("generation_identity", self.generation_identity),
            ("provenance_hash", self.provenance_hash),
            ("provider", self.provider),
        ):
            if not isinstance(value, str) or not value:
                raise ObservationError(f"cache key {name} is required")

    @property
    def identity(self) -> str:
        encoded = json.dumps(
            {
                "generation": self.generation_identity,
                "key": self.logical_key,
                "namespace": self.namespace,
                "provenance": self.provenance_hash,
                "provider": self.provider,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class DerivedCacheEntry:
    key: DerivedCacheKey
    payload: bytes
    content_hash: str
    expires_at: float
    negative: bool

    @property
    def byte_size(self) -> int:
        return len(self.payload)


class GenerationBoundCache:
    """LRU cache with immutable payloads and cancellation-safe single-flight."""

    def __init__(
        self,
        *,
        max_entries: int = 256,
        max_bytes: int = 4 * 1024 * 1024,
        max_entries_per_provider: int = 64,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_entries <= 0 or max_bytes <= 0 or max_entries_per_provider <= 0:
            raise ObservationError("cache bounds must be positive")
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.max_entries_per_provider = max_entries_per_provider
        self._clock = clock
        self._entries: OrderedDict[str, DerivedCacheEntry] = OrderedDict()
        self._bytes = 0
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _encode(value: Any) -> bytes:
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        except (TypeError, ValueError) as exc:
            raise ObservationError("cache values must be deterministic JSON") from exc

    @staticmethod
    def _decode(payload: bytes) -> Any:
        return json.loads(payload.decode())

    def put_json(
        self,
        key: DerivedCacheKey,
        value: Any,
        *,
        ttl_seconds: float,
        negative: bool = False,
    ) -> str:
        if ttl_seconds <= 0:
            raise ObservationError("cache ttl_seconds must be positive")
        payload = self._encode(value)
        if len(payload) > self.max_bytes:
            raise ObservationError("cache entry exceeds total byte budget")
        identity = key.identity
        content_hash = hashlib.sha256(payload).hexdigest()
        entry = DerivedCacheEntry(
            key=key,
            payload=payload,
            content_hash=content_hash,
            expires_at=self._clock() + ttl_seconds,
            negative=negative,
        )
        previous = self._entries.pop(identity, None)
        if previous is not None:
            self._bytes -= previous.byte_size
        self._entries[identity] = entry
        self._bytes += entry.byte_size
        self._evict()
        return content_hash

    def get_json(self, key: DerivedCacheKey) -> Any | None:
        identity = key.identity
        entry = self._entries.get(identity)
        if entry is None:
            return None
        if self._clock() >= entry.expires_at:
            self._delete(identity)
            return None
        if entry.key.generation_identity != key.generation_identity:
            self._delete(identity)
            return None
        if entry.key.provenance_hash != key.provenance_hash:
            self._delete(identity)
            return None
        if hashlib.sha256(entry.payload).hexdigest() != entry.content_hash:
            self._delete(identity)
            raise ObservationError("cache content hash mismatch")
        self._entries.move_to_end(identity)
        return self._decode(entry.payload)

    def is_negative(self, key: DerivedCacheKey) -> bool:
        entry = self._entries.get(key.identity)
        return bool(entry and self._clock() < entry.expires_at and entry.negative)

    async def get_or_compute(
        self,
        key: DerivedCacheKey,
        factory: Callable[[], Awaitable[Any]],
        *,
        ttl_seconds: float,
        negative_ttl_seconds: float = 1.0,
    ) -> Any:
        cached = self.get_json(key)
        if cached is not None or self.is_negative(key):
            return cached
        identity = key.identity
        async with self._lock:
            cached = self.get_json(key)
            if cached is not None or self.is_negative(key):
                return cached
            task = self._inflight.get(identity)
            if task is None:
                task = asyncio.create_task(factory())
                self._inflight[identity] = task
        try:
            result = await asyncio.shield(task)
        finally:
            async with self._lock:
                if self._inflight.get(identity) is task and task.done():
                    self._inflight.pop(identity, None)
        if result is None:
            self.put_json(
                key,
                None,
                ttl_seconds=negative_ttl_seconds,
                negative=True,
            )
            return None
        self.put_json(key, result, ttl_seconds=ttl_seconds)
        return result

    def invalidate_generation(self, generation_identity: str) -> tuple[str, ...]:
        removed = tuple(
            identity
            for identity, entry in self._entries.items()
            if entry.key.generation_identity == generation_identity
        )
        for identity in removed:
            self._delete(identity)
        return removed

    def invalidate_provider(self, provider: str) -> tuple[str, ...]:
        removed = tuple(
            identity
            for identity, entry in self._entries.items()
            if entry.key.provider == provider
        )
        for identity in removed:
            self._delete(identity)
        return removed

    def invalidate_provenance(self, provenance_hash: str) -> tuple[str, ...]:
        removed = tuple(
            identity
            for identity, entry in self._entries.items()
            if entry.key.provenance_hash == provenance_hash
        )
        for identity in removed:
            self._delete(identity)
        return removed

    def snapshot_manifest(self) -> Mapping[str, Any]:
        return {
            "schema_version": "mpr042.cache-manifest.v1",
            "entries": len(self._entries),
            "bytes": self._bytes,
            "content_hashes": tuple(
                entry.content_hash for entry in self._entries.values()
            ),
        }

    def _delete(self, identity: str) -> None:
        entry = self._entries.pop(identity, None)
        if entry is not None:
            self._bytes -= entry.byte_size

    def _evict(self) -> None:
        while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
            identity, entry = self._entries.popitem(last=False)
            self._bytes -= entry.byte_size
        while True:
            counts: dict[str, int] = {}
            offender: str | None = None
            for entry in self._entries.values():
                provider = entry.key.provider
                counts[provider] = counts.get(provider, 0) + 1
                if counts[provider] > self.max_entries_per_provider:
                    offender = provider
                    break
            if offender is None:
                break
            for identity, entry in self._entries.items():
                if entry.key.provider == offender:
                    self._delete(identity)
                    break
