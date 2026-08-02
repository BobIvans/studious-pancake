"""Typed Helius webhook desired-state adapter.

The adapter owns remote management only.  It does not change webhook delivery,
ingress verification, event parsing, quote semantics, or execution behavior.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .engine import ProviderConflict
from .models import PlanOperation, RemoteInventory, RemoteResource, canonical_sha256


class HeliusManagementError(RuntimeError):
    """A redacted Helius management operation failed."""


_ALLOWED_FIELDS = frozenset(
    {
        "webhookURL",
        "webhookType",
        "transactionTypes",
        "accountAddresses",
        "txnStatus",
        "accountFilters",
        "authHeader",
    }
)


def _normalized_specification(raw: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in sorted(_ALLOWED_FIELDS):
        if key not in raw:
            continue
        value = raw[key]
        if key in {"transactionTypes", "accountAddresses"}:
            if not isinstance(value, list):
                raise HeliusManagementError(f"Helius {key} must be a list")
            normalized[key] = sorted(dict.fromkeys(map(str, value)))
        elif key == "accountFilters":
            normalized[key] = value
        else:
            normalized[key] = value
    return normalized


class HeliusWebhookProvider:
    provider_name = "helius"
    resource_kind = "webhook"

    def __init__(
        self,
        *,
        api_key: str,
        bindings: Mapping[str, str] | None = None,
        base_url: str = "https://api.helius.xyz/v0",
        timeout_seconds: float = 15.0,
        client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Helius API key is required")
        self._api_key = api_key.strip()
        self._bindings = dict(bindings or {})
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        if client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - installed dependency
                raise HeliusManagementError("httpx dependency unavailable") from exc
            client = httpx.Client(timeout=timeout_seconds)
        self._client = client

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        try:
            response = self._client.request(
                method,
                f"{self._base_url}{path}",
                params={"api-key": self._api_key},
                json=(dict(payload) if payload is not None else None),
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            if response.status_code == 204:
                return None
            return response.json()
        except Exception as exc:
            # Never include response bodies, URLs containing query credentials, or
            # raw provider exceptions in durable/user-facing evidence.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            suffix = f" status={status}" if status is not None else ""
            raise HeliusManagementError(
                f"Helius management request failed:{suffix or ' transport'}"
            ) from None

    def _remote(self, raw: Mapping[str, Any]) -> RemoteResource:
        provider_id = str(raw.get("webhookId") or "").strip()
        if not provider_id:
            raise HeliusManagementError("Helius webhook response lacks webhookId")
        return RemoteResource(
            provider=self.provider_name,
            kind=self.resource_kind,
            provider_resource_id=provider_id,
            specification=_normalized_specification(raw),
            local_key=self._bindings.get(provider_id),
        )

    def discover(self) -> RemoteInventory:
        raw = self._request("GET", "/webhooks")
        page_count = 1
        complete = True
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, Mapping):
            values = raw.get("items") or raw.get("webhooks")
            if not isinstance(values, list):
                raise HeliusManagementError("Helius inventory shape is unsupported")
            items = values
            # A cursor without a supported paging contract makes the inventory
            # explicitly incomplete and blocks destructive apply.
            complete = not bool(raw.get("nextCursor") or raw.get("nextPageToken"))
        else:
            raise HeliusManagementError("Helius inventory is not a list/object")
        resources = tuple(
            self._remote(item) for item in items if isinstance(item, Mapping)
        )
        generation = canonical_sha256([item.to_dict() for item in resources])
        return RemoteInventory(
            resources=resources,
            complete=complete,
            page_count=page_count,
            provider_generation=generation,
        )

    def create(
        self, operation: PlanOperation, *, idempotency_key: str
    ) -> RemoteResource:
        payload = _normalized_specification(operation.desired_specification or {})
        raw = self._request("POST", "/webhooks", payload=payload)
        if not isinstance(raw, Mapping):
            raise HeliusManagementError("Helius create response is invalid")
        remote = self._remote(raw)
        self._bindings[remote.provider_resource_id] = operation.resource_key
        return RemoteResource(
            provider=remote.provider,
            kind=remote.kind,
            provider_resource_id=remote.provider_resource_id,
            specification=remote.specification,
            local_key=operation.resource_key,
        )

    def update(
        self, operation: PlanOperation, *, idempotency_key: str
    ) -> RemoteResource:
        if operation.provider_resource_id is None:
            raise ProviderConflict("Helius update requires provider_resource_id")
        current = self.discover()
        remote = next(
            (
                item
                for item in current.resources
                if item.provider_resource_id == operation.provider_resource_id
            ),
            None,
        )
        if (
            remote is None
            or remote.fingerprint != operation.expected_remote_fingerprint
        ):
            raise ProviderConflict("Helius webhook changed before update")
        payload = _normalized_specification(operation.desired_specification or {})
        raw = self._request(
            "PUT", f"/webhooks/{operation.provider_resource_id}", payload=payload
        )
        if not isinstance(raw, Mapping):
            raw = {**payload, "webhookId": operation.provider_resource_id}
        updated = self._remote(raw)
        self._bindings[updated.provider_resource_id] = operation.resource_key
        return RemoteResource(
            provider=updated.provider,
            kind=updated.kind,
            provider_resource_id=updated.provider_resource_id,
            specification=updated.specification,
            local_key=operation.resource_key,
        )

    def delete(self, operation: PlanOperation, *, idempotency_key: str) -> None:
        if operation.provider_resource_id is None:
            raise ProviderConflict("Helius delete requires provider_resource_id")
        current = self.discover()
        remote = next(
            (
                item
                for item in current.resources
                if item.provider_resource_id == operation.provider_resource_id
            ),
            None,
        )
        if remote is None:
            return
        if remote.fingerprint != operation.expected_remote_fingerprint:
            raise ProviderConflict("Helius webhook changed before delete")
        self._request("DELETE", f"/webhooks/{operation.provider_resource_id}")
        self._bindings.pop(operation.provider_resource_id, None)
