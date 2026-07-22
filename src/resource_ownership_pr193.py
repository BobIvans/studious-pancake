"""PR-193 explicit resource ownership and deterministic shutdown primitives."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

PR193_RESOURCE_SCHEMA = "pr193.resource-ownership.v1"


class ResourceOwnership(StrEnum):
    OWNED = "owned"
    BORROWED = "borrowed"
    SHARED = "shared"


class ResourceState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class ResourceOwnershipError(RuntimeError):
    """Raised when a resource graph has ambiguous ownership."""


class ResourceCloseError(RuntimeError):
    """Raised after all resources were attempted but one or more closes failed."""

    def __init__(self, failures: tuple[tuple[str, str], ...]) -> None:
        self.failures = failures
        summary = ", ".join(f"{resource_id}:{error_type}" for resource_id, error_type in failures)
        super().__init__(f"resource shutdown failed: {summary}")


@runtime_checkable
class SyncCloseable(Protocol):
    def close(self) -> None:
        ...


@runtime_checkable
class AsyncCloseable(Protocol):
    async def aclose(self) -> None:
        ...


@dataclass(slots=True)
class ResourceRegistration:
    resource_id: str
    kind: str
    ownership: ResourceOwnership
    resource: Any
    opened_generation: int
    closed_generation: int | None = None

    @property
    def state(self) -> ResourceState:
        return ResourceState.CLOSED if self.closed_generation is not None else ResourceState.OPEN

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PR193_RESOURCE_SCHEMA,
            "resource_id": self.resource_id,
            "kind": self.kind,
            "ownership": self.ownership.value,
            "opened_generation": self.opened_generation,
            "closed_generation": self.closed_generation,
            "state": self.state.value,
        }


class ResourceGraph:
    """One composition-owned graph closed exactly once in reverse open order."""

    def __init__(self, *, generation: int = 1) -> None:
        if generation <= 0:
            raise ValueError("generation must be positive")
        self.generation = generation
        self._registrations: list[ResourceRegistration] = []
        self._resource_ids: set[str] = set()
        self._owned_object_ids: set[int] = set()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def register(
        self,
        resource: Any,
        *,
        resource_id: str,
        kind: str,
        ownership: ResourceOwnership = ResourceOwnership.OWNED,
    ) -> Any:
        if self._closed:
            raise ResourceOwnershipError("cannot register resource after graph close")
        normalized_id = resource_id.strip()
        normalized_kind = kind.strip()
        if not normalized_id or not normalized_kind:
            raise ResourceOwnershipError("resource_id and kind are required")
        if normalized_id in self._resource_ids:
            raise ResourceOwnershipError(f"duplicate resource_id: {normalized_id}")
        object_id = id(resource)
        if ownership is ResourceOwnership.OWNED and object_id in self._owned_object_ids:
            raise ResourceOwnershipError("one resource object cannot have two owners")
        if ownership is ResourceOwnership.OWNED:
            self._owned_object_ids.add(object_id)
        self._resource_ids.add(normalized_id)
        self._registrations.append(
            ResourceRegistration(
                resource_id=normalized_id,
                kind=normalized_kind,
                ownership=ownership,
                resource=resource,
                opened_generation=self.generation,
            )
        )
        return resource

    def health(self) -> tuple[dict[str, Any], ...]:
        return tuple(item.to_dict() for item in self._registrations)

    def close(self) -> None:
        """Close synchronous owned resources in reverse order."""
        if self._closed:
            return
        failures: list[tuple[str, str]] = []
        try:
            for registration in reversed(self._registrations):
                if registration.ownership is not ResourceOwnership.OWNED:
                    registration.closed_generation = self.generation
                    continue
                try:
                    close = getattr(registration.resource, "close", None)
                    if close is None or not callable(close):
                        raise ResourceOwnershipError(
                            "owned resource has no synchronous close contract"
                        )
                    result = close()
                    if inspect.isawaitable(result):
                        raise ResourceOwnershipError(
                            "synchronous close returned an awaitable; use aclose"
                        )
                except Exception as exc:
                    failures.append((registration.resource_id, type(exc).__name__))
                finally:
                    registration.closed_generation = self.generation
        finally:
            self._closed = True
        if failures:
            raise ResourceCloseError(tuple(failures))

    async def aclose(self) -> None:
        """Close mixed sync/async owned resources in reverse order."""
        if self._closed:
            return
        failures: list[tuple[str, str]] = []
        try:
            for registration in reversed(self._registrations):
                if registration.ownership is not ResourceOwnership.OWNED:
                    registration.closed_generation = self.generation
                    continue
                try:
                    async_close = getattr(registration.resource, "aclose", None)
                    if callable(async_close):
                        await async_close()
                    else:
                        close = getattr(registration.resource, "close", None)
                        if close is None or not callable(close):
                            raise ResourceOwnershipError(
                                "owned resource has no close/aclose contract"
                            )
                        result = close()
                        if inspect.isawaitable(result):
                            await result
                except Exception as exc:
                    failures.append((registration.resource_id, type(exc).__name__))
                finally:
                    registration.closed_generation = self.generation
        finally:
            self._closed = True
        if failures:
            raise ResourceCloseError(tuple(failures))

    def __enter__(self) -> ResourceGraph:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    async def __aenter__(self) -> ResourceGraph:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.aclose()
