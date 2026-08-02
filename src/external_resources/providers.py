"""Provider-neutral in-memory implementation used by tests and dry-run tooling."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from typing import Iterable

from .engine import ProviderConflict
from .models import PlanOperation, RemoteInventory, RemoteResource


class InMemoryProvider:
    def __init__(
        self,
        resources: Iterable[RemoteResource] = (),
        *,
        complete: bool = True,
    ) -> None:
        self._resources = {item.provider_resource_id: item for item in resources}
        self.complete = complete
        self._idempotency: dict[str, str | None] = {}

    def discover(self) -> RemoteInventory:
        return RemoteInventory(
            resources=tuple(
                self._resources[key] for key in sorted(self._resources)
            ),
            complete=self.complete,
            page_count=1,
            provider_generation=hashlib.sha256(
                "|".join(
                    sorted(item.fingerprint for item in self._resources.values())
                ).encode()
            ).hexdigest(),
        )

    def create(
        self, operation: PlanOperation, *, idempotency_key: str
    ) -> RemoteResource:
        prior = self._idempotency.get(idempotency_key)
        if prior is not None:
            return self._resources[prior]
        provider_id = f"mem-{idempotency_key[:16]}"
        resource = RemoteResource(
            provider=operation.provider,
            kind=operation.resource_kind,
            provider_resource_id=provider_id,
            specification=dict(operation.desired_specification or {}),
            local_key=operation.resource_key,
        )
        self._resources[provider_id] = resource
        self._idempotency[idempotency_key] = provider_id
        return resource

    def update(
        self, operation: PlanOperation, *, idempotency_key: str
    ) -> RemoteResource:
        if operation.provider_resource_id is None:
            raise ProviderConflict("update requires provider_resource_id")
        prior = self._idempotency.get(idempotency_key)
        if prior is not None:
            return self._resources[prior]
        current = self._resources.get(operation.provider_resource_id)
        if current is None:
            raise ProviderConflict("update target missing")
        updated = replace(
            current,
            specification=dict(operation.desired_specification or {}),
            local_key=operation.resource_key,
        )
        self._resources[current.provider_resource_id] = updated
        self._idempotency[idempotency_key] = current.provider_resource_id
        return updated

    def delete(self, operation: PlanOperation, *, idempotency_key: str) -> None:
        if idempotency_key in self._idempotency:
            return
        if operation.provider_resource_id is not None:
            self._resources.pop(operation.provider_resource_id, None)
        self._idempotency[idempotency_key] = None
