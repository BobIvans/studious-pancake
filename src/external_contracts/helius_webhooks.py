"""Strict Helius webhook management contract.

This module owns only the management-plane HTTP contract. It never receives
webhook deliveries and it never enables trading. Callers must supply an API key
and a publicly reachable HTTPS delivery URL.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import ipaddress
import json
from typing import Any
from urllib.parse import urlparse

import requests

HELIUS_WEBHOOKS_BASE_URL = "https://api-mainnet.helius-rpc.com/v0"
HELIUS_REQUEST_TIMEOUT_SECONDS = 15.0
MAX_MANAGEMENT_RESPONSE_BYTES = 2_000_000

_CREATE_UPDATE_FIELDS = frozenset(
    {
        "accountAddresses",
        "accountFilters",
        "authHeader",
        "encoding",
        "transactionTypes",
        "txnStatus",
        "webhookType",
        "webhookURL",
    }
)
_REQUIRED_CREATE_FIELDS = frozenset(
    {"accountAddresses", "transactionTypes", "webhookType", "webhookURL"}
)


class HeliusWebhookContractError(ValueError):
    """Raised when local or remote Helius management evidence is invalid."""


def extract_webhook_id(payload: Mapping[str, Any]) -> str:
    """Extract the canonical Helius management response identifier."""

    webhook_id = payload.get("webhookID")
    if not isinstance(webhook_id, str) or not webhook_id.strip():
        raise HeliusWebhookContractError(
            "Helius response is missing canonical webhookID"
        )
    return webhook_id.strip()


def validate_public_https_webhook_url(value: str) -> str:
    """Require an absolute public HTTPS delivery URL without embedded secrets."""

    candidate = value.strip()
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HeliusWebhookContractError(
            "webhookURL must be an absolute public HTTPS URL"
        )
    if parsed.username or parsed.password or parsed.fragment:
        raise HeliusWebhookContractError(
            "webhookURL must not contain credentials or a fragment"
        )

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(
        ".local"
    ):
        raise HeliusWebhookContractError("webhookURL must not target localhost")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise HeliusWebhookContractError(
            "webhookURL must resolve through a public address"
        )
    return candidate


def sanitize_webhook_payload(
    payload: Mapping[str, Any],
    *,
    require_auth_header: bool,
) -> dict[str, Any]:
    """Return only Helius-supported management fields and validate invariants."""

    sanitized = {
        key: payload[key]
        for key in _CREATE_UPDATE_FIELDS
        if key in payload and payload[key] is not None
    }
    missing = sorted(_REQUIRED_CREATE_FIELDS.difference(sanitized))
    if missing:
        raise HeliusWebhookContractError(
            f"Helius webhook payload is missing required fields: {missing}"
        )

    sanitized["webhookURL"] = validate_public_https_webhook_url(
        str(sanitized["webhookURL"])
    )
    _require_nonempty_string_sequence(
        sanitized["accountAddresses"], "accountAddresses"
    )
    _require_nonempty_string_sequence(
        sanitized["transactionTypes"], "transactionTypes"
    )

    webhook_type = sanitized["webhookType"]
    if not isinstance(webhook_type, str) or not webhook_type.strip():
        raise HeliusWebhookContractError("webhookType must be a non-empty string")

    auth_header = sanitized.get("authHeader")
    if require_auth_header and (
        not isinstance(auth_header, str) or not auth_header.strip()
    ):
        raise HeliusWebhookContractError(
            "authHeader is required for production webhook authenticity"
        )
    if isinstance(auth_header, str):
        sanitized["authHeader"] = auth_header.strip()
    return sanitized


def _require_nonempty_string_sequence(value: Any, label: str) -> None:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise HeliusWebhookContractError(f"{label} must be a sequence of strings")
    if not value or any(not isinstance(item, str) or not item.strip() for item in value):
        raise HeliusWebhookContractError(
            f"{label} must contain non-empty strings"
        )


class HeliusWebhookClient:
    """Small synchronous client for the current Helius webhook management API."""

    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = HELIUS_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if not api_key.strip():
            raise HeliusWebhookContractError("HELIUS_API_KEY is required")
        if timeout_seconds <= 0:
            raise HeliusWebhookContractError("timeout_seconds must be positive")
        self._api_key = api_key.strip()
        self._session = session or requests.Session()
        self._timeout_seconds = timeout_seconds

    def list_webhooks(self) -> list[dict[str, Any]]:
        payload = self._request_json("GET", "/webhooks", expected_statuses={200})
        if not isinstance(payload, list) or any(
            not isinstance(item, dict) for item in payload
        ):
            raise HeliusWebhookContractError(
                "Helius list response must be an array of objects"
            )
        return payload

    def get_webhook(self, webhook_id: str) -> dict[str, Any]:
        normalized_id = _require_webhook_id(webhook_id)
        payload = self._request_json(
            "GET", f"/webhooks/{normalized_id}", expected_statuses={200}
        )
        if not isinstance(payload, dict):
            raise HeliusWebhookContractError(
                "Helius get response must be a JSON object"
            )
        return payload

    def create_webhook(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = sanitize_webhook_payload(payload, require_auth_header=True)
        response = self._request_json(
            "POST", "/webhooks", expected_statuses={200, 201}, json_body=body
        )
        if not isinstance(response, dict):
            raise HeliusWebhookContractError(
                "Helius create response must be a JSON object"
            )
        extract_webhook_id(response)
        return response

    def update_webhook(
        self, webhook_id: str, updates: Mapping[str, Any]
    ) -> dict[str, Any]:
        normalized_id = _require_webhook_id(webhook_id)
        current = self.get_webhook(normalized_id)
        merged = dict(current)
        merged.update(updates)
        body = sanitize_webhook_payload(merged, require_auth_header=True)
        response = self._request_json(
            "PUT",
            f"/webhooks/{normalized_id}",
            expected_statuses={200},
            json_body=body,
        )
        if not isinstance(response, dict):
            raise HeliusWebhookContractError(
                "Helius update response must be a JSON object"
            )
        return response

    def delete_webhook(self, webhook_id: str) -> None:
        normalized_id = _require_webhook_id(webhook_id)
        self._request_json(
            "DELETE",
            f"/webhooks/{normalized_id}",
            expected_statuses={200, 204},
            allow_empty=True,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        expected_statuses: set[int],
        json_body: Mapping[str, Any] | None = None,
        allow_empty: bool = False,
    ) -> Any:
        response = self._session.request(
            method,
            f"{HELIUS_WEBHOOKS_BASE_URL}{path}",
            params={"api-key": self._api_key},
            json=dict(json_body) if json_body is not None else None,
            headers={"Accept": "application/json"},
            timeout=self._timeout_seconds,
        )
        if response.status_code not in expected_statuses:
            raise HeliusWebhookContractError(
                f"Helius management request failed with HTTP {response.status_code}"
            )
        content = response.content
        if not content:
            if allow_empty:
                return None
            raise HeliusWebhookContractError("Helius response body is empty")
        if len(content) > MAX_MANAGEMENT_RESPONSE_BYTES:
            raise HeliusWebhookContractError("Helius response exceeds size limit")
        try:
            return json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HeliusWebhookContractError(
                "Helius response is not valid UTF-8 JSON"
            ) from exc


def _require_webhook_id(value: str) -> str:
    normalized = value.strip()
    if not normalized or any(character.isspace() for character in normalized):
        raise HeliusWebhookContractError("webhook ID must be non-empty")
    return normalized


__all__ = [
    "HELIUS_REQUEST_TIMEOUT_SECONDS",
    "HELIUS_WEBHOOKS_BASE_URL",
    "HeliusWebhookClient",
    "HeliusWebhookContractError",
    "extract_webhook_id",
    "sanitize_webhook_payload",
    "validate_public_https_webhook_url",
]
