from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import setup_helius_webhook
from src.external_contracts.helius_webhooks import (
    HELIUS_WEBHOOKS_BASE_URL,
    MAX_MANAGEMENT_RESPONSE_BYTES,
    HeliusWebhookClient,
    HeliusWebhookContractError,
    extract_webhook_id,
    sanitize_webhook_payload,
    validate_public_https_webhook_url,
)
from src.ingest.webhook_config import WebhookConfig


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        if isinstance(payload, bytes):
            self.content = payload
        else:
            self.content = json.dumps(payload).encode("utf-8")


class _Session:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


def _payload() -> dict[str, Any]:
    return {
        "webhookURL": "https://hooks.example.com/helius",
        "webhookType": "enhanced",
        "transactionTypes": ["SWAP"],
        "accountAddresses": ["11111111111111111111111111111111"],
        "authHeader": "Bearer deterministic-test-value",
        "webhookIds": ["internal-only"],
        "managementIds": ["internal-only"],
    }


def test_pr151_uses_current_helius_host_and_canonical_id() -> None:
    assert HELIUS_WEBHOOKS_BASE_URL == "https://api-mainnet.helius-rpc.com/v0"
    assert extract_webhook_id({"webhookID": "abc"}) == "abc"
    with pytest.raises(HeliusWebhookContractError, match="webhookID"):
        extract_webhook_id({"webhookId": "legacy"})


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/helius",
        "https://localhost/webhook",
        "https://127.0.0.1/webhook",
        "https://10.0.0.5/webhook",
        "https://user:secret@hooks.example.com/webhook",
    ],
)
def test_pr151_delivery_url_must_be_public_https(url: str) -> None:
    with pytest.raises(HeliusWebhookContractError):
        validate_public_https_webhook_url(url)


def test_pr151_payload_strips_internal_fields_and_requires_auth() -> None:
    sanitized = sanitize_webhook_payload(_payload(), require_auth_header=True)
    assert sanitized["webhookURL"] == "https://hooks.example.com/helius"
    assert "webhookIds" not in sanitized
    assert "managementIds" not in sanitized

    without_auth = _payload()
    without_auth.pop("authHeader")
    with pytest.raises(HeliusWebhookContractError, match="authHeader"):
        sanitize_webhook_payload(without_auth, require_auth_header=True)


def test_pr151_api_key_is_not_interpolated_into_url() -> None:
    session = _Session([_Response(201, {"webhookID": "created"})])
    client = HeliusWebhookClient(
        "secret-api-key",
        session=session,  # type: ignore[arg-type]
        timeout_seconds=7.5,
    )

    result = client.create_webhook(_payload())

    assert extract_webhook_id(result) == "created"
    call = session.calls[0]
    assert call["url"] == f"{HELIUS_WEBHOOKS_BASE_URL}/webhooks"
    assert "secret-api-key" not in call["url"]
    assert call["params"] == {"api-key": "secret-api-key"}
    assert call["timeout"] == 7.5


def test_pr151_update_sends_only_supported_management_fields() -> None:
    current = _payload() | {"webhookID": "existing", "createdAt": "ignored"}
    updated = _payload() | {"webhookID": "existing"}
    session = _Session([_Response(200, current), _Response(200, updated)])
    client = HeliusWebhookClient("key", session=session)  # type: ignore[arg-type]

    client.update_webhook("existing", {"transactionTypes": ["TRANSFER"]})

    body = session.calls[1]["json"]
    assert body["transactionTypes"] == ["TRANSFER"]
    assert "webhookID" not in body
    assert "createdAt" not in body


def test_pr151_management_response_is_bounded() -> None:
    session = _Session([_Response(200, b"x" * (MAX_MANAGEMENT_RESPONSE_BYTES + 1))])
    client = HeliusWebhookClient("key", session=session)  # type: ignore[arg-type]

    with pytest.raises(HeliusWebhookContractError, match="size limit"):
        client.list_webhooks()


def test_pr151_written_config_redacts_auth_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids_path = tmp_path / "ids.txt"
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(setup_helius_webhook, "WEBHOOK_IDS_FILE", ids_path)
    monkeypatch.setattr(setup_helius_webhook, "WEBHOOK_CONFIG_FILE", config_path)

    setup_helius_webhook._record_webhook("id-1", _payload())

    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored["authHeader"] == "<redacted>"
    assert ids_path.read_text(encoding="utf-8") == "id-1\n"


def test_pr151_webhook_config_has_no_localhost_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WEBHOOK_URL", raising=False)
    monkeypatch.delenv("HELIUS_WEBHOOK_AUTH_HEADER", raising=False)

    payload = WebhookConfig.get_webhook_config()

    assert payload["webhookURL"] == ""
    assert payload["authHeader"] is None
    with pytest.raises(HeliusWebhookContractError):
        sanitize_webhook_payload(payload, require_auth_header=True)
