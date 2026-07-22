from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.external_contracts.helius_webhooks import (
    HELIUS_WEBHOOKS_BASE_URL,
    HeliusWebhookClient,
    HeliusWebhookContractError,
    extract_webhook_id,
    sanitize_webhook_payload,
    validate_public_https_webhook_url,
)
from src.external_contracts.production_compatibility import (
    SCHEMA_VERSION,
    ProductionCompatibilityError,
    evaluate_production_compatibility,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/production_debt_pr149.json"


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


def test_pr149_helius_contract_uses_current_host_and_canonical_id() -> None:
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
def test_pr149_helius_delivery_url_must_be_public_https(url: str) -> None:
    with pytest.raises(HeliusWebhookContractError):
        validate_public_https_webhook_url(url)


def test_pr149_helius_payload_strips_internal_fields_and_requires_auth() -> None:
    sanitized = sanitize_webhook_payload(_payload(), require_auth_header=True)
    assert sanitized["webhookURL"] == "https://hooks.example.com/helius"
    assert "webhookIds" not in sanitized
    assert "managementIds" not in sanitized

    without_auth = _payload()
    without_auth.pop("authHeader")
    with pytest.raises(HeliusWebhookContractError, match="authHeader"):
        sanitize_webhook_payload(without_auth, require_auth_header=True)


def test_pr149_helius_client_keeps_api_key_out_of_url_and_bounds_timeout() -> None:
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


def test_pr149_helius_update_sends_only_supported_management_fields() -> None:
    current = _payload() | {"webhookID": "existing", "createdAt": "ignored"}
    updated = _payload() | {"webhookID": "existing"}
    session = _Session([_Response(200, current), _Response(200, updated)])
    client = HeliusWebhookClient("key", session=session)  # type: ignore[arg-type]

    client.update_webhook("existing", {"transactionTypes": ["TRANSFER"]})

    body = session.calls[1]["json"]
    assert body["transactionTypes"] == ["TRANSFER"]
    assert "webhookID" not in body
    assert "createdAt" not in body


def test_pr149_repository_contract_gate_is_fail_closed_but_not_live() -> None:
    report = evaluate_production_compatibility(ROOT, MANIFEST)

    assert report.schema_version == SCHEMA_VERSION
    assert report.ready is True
    assert report.live_trading_allowed is False
    assert report.debt_item_count == 36
    assert report.epic_count == 4
    assert not report.blockers
    assert {item.finding_id for item in report.warnings} == {
        "JITO-LEGACY-CLIENT-REQUIRES-REPLACEMENT"
    }
    assert len(report.report_sha256) == 64


def test_pr149_manifest_rejects_duplicate_debt_ids(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["epics"][1]["items"][0]["id"] = "A01"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProductionCompatibilityError, match="duplicate"):
        evaluate_production_compatibility(ROOT, manifest)


def test_pr149_source_drift_becomes_a_blocker(tmp_path: Path) -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["source_contract_rules"] = [
        {
            "id": "STALE-HELIUS",
            "path": "manage.py",
            "severity": "blocker",
            "required_substrings": ["api-mainnet.helius-rpc.com"],
            "forbidden_substrings": ["api.helius.xyz"],
        }
    ]
    (tmp_path / "manage.py").write_text(
        "https://api.helius.xyz/v0", encoding="utf-8"
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_production_compatibility(tmp_path, manifest)

    assert report.ready is False
    assert report.blockers[0].finding_id == "STALE-HELIUS"
