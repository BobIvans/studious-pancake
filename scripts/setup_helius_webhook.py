#!/usr/bin/env python3
"""Create or discover a production-compatible Helius webhook."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv

from src.external_contracts.helius_webhooks import (
    HeliusWebhookClient,
    HeliusWebhookContractError,
    extract_webhook_id,
    sanitize_webhook_payload,
)
from src.ingest.webhook_config import WebhookConfig

load_dotenv()

WEBHOOK_IDS_FILE = Path("helius_webhook_ids.txt")
WEBHOOK_CONFIG_FILE = Path("helius_webhook_config.json")


def check_existing_webhooks(
    client: HeliusWebhookClient,
) -> list[dict[str, Any]]:
    """Return existing webhooks that cover all configured LST addresses."""

    expected = set(WebhookConfig.LST_ADDRESSES)
    matches: list[dict[str, Any]] = []
    for webhook in client.list_webhooks():
        addresses = set(webhook.get("accountAddresses", []))
        if expected.issubset(addresses):
            matches.append(
                {
                    "id": extract_webhook_id(webhook),
                    "url": webhook.get("webhookURL"),
                    "addresses": len(addresses),
                }
            )
    return matches


def create_helius_webhook() -> str:
    """Create a Helius webhook or return an exact existing match."""

    api_key = os.getenv("HELIUS_API_KEY", "").strip()
    client = HeliusWebhookClient(api_key)
    payload = sanitize_webhook_payload(
        WebhookConfig.get_webhook_config(), require_auth_header=True
    )

    existing = check_existing_webhooks(client)
    for webhook in existing:
        if webhook["url"] == payload["webhookURL"]:
            webhook_id = str(webhook["id"])
            print(f"Using existing webhook: {webhook_id}")
            return webhook_id

    result = client.create_webhook(payload)
    webhook_id = extract_webhook_id(result)
    _record_webhook(webhook_id, payload)
    print(f"Created webhook: {webhook_id}")
    return webhook_id


def _record_webhook(webhook_id: str, payload: dict[str, Any]) -> None:
    current_ids: list[str] = []
    if WEBHOOK_IDS_FILE.is_file():
        current_ids = [
            line.strip()
            for line in WEBHOOK_IDS_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    if webhook_id not in current_ids:
        current_ids.append(webhook_id)
    WEBHOOK_IDS_FILE.write_text(
        "\n".join(current_ids) + "\n", encoding="utf-8"
    )

    redacted = dict(payload)
    if "authHeader" in redacted:
        redacted["authHeader"] = "<redacted>"
    WEBHOOK_CONFIG_FILE.write_text(
        json.dumps(redacted, indent=2, sort_keys=True), encoding="utf-8"
    )


def main() -> int:
    try:
        webhook_id = create_helius_webhook()
    except (HeliusWebhookContractError, OSError) as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Primary webhook ID: {webhook_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
