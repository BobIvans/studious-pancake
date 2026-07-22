#!/usr/bin/env python3
"""Manage Helius webhooks through the pinned production management contract."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
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
)
from src.ingest.webhook_config import WebhookConfig

load_dotenv()


class WebhookManager:
    """Manage only explicitly supplied or configured Helius webhook IDs."""

    def __init__(self, management_id: str | None = None) -> None:
        api_key = os.getenv("HELIUS_API_KEY", "").strip()
        self.client = HeliusWebhookClient(api_key)
        self.management_id = management_id or WebhookConfig.PRIMARY_MANAGEMENT_ID

    def _ensure_managed_id(self, webhook_id: str) -> str:
        normalized = webhook_id.strip()
        if not normalized:
            raise HeliusWebhookContractError("webhook ID is required")
        configured = set(WebhookConfig.MANAGEMENT_IDS)
        if configured and normalized not in configured:
            raise HeliusWebhookContractError(
                f"Webhook ID is not configured for management: {normalized}"
            )
        return normalized

    def get_webhooks(self) -> list[dict[str, Any]]:
        webhooks = self.client.list_webhooks()
        print(f"Found {len(webhooks)} webhooks")
        return webhooks

    def get_webhook_by_id(
        self, webhook_id: str, *, silent: bool = False
    ) -> dict[str, Any]:
        normalized = self._ensure_managed_id(webhook_id)
        webhook = self.client.get_webhook(normalized)
        if not silent:
            print(f"Retrieved webhook: {normalized}")
        return webhook

    def update_webhook(
        self, webhook_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        normalized = self._ensure_managed_id(webhook_id)
        result = self.client.update_webhook(normalized, updates)
        print(f"Updated webhook: {normalized}")
        return result

    def add_addresses_to_webhook(
        self, webhook_id: str, addresses: Iterable[str]
    ) -> dict[str, Any]:
        normalized = self._ensure_managed_id(webhook_id)
        current = self.client.get_webhook(normalized)
        clean_addresses = [
            address.strip() for address in addresses if address and address.strip()
        ]
        if not clean_addresses:
            raise HeliusWebhookContractError("No addresses supplied")

        current_addresses = list(
            dict.fromkeys(current.get("accountAddresses") or [])
        )
        new_addresses = [
            address
            for address in clean_addresses
            if address not in current_addresses
        ]
        if not new_addresses:
            print(
                f"All {len(clean_addresses)} address(es) already exist on "
                f"webhook {normalized}"
            )
            return current
        return self.update_webhook(
            normalized,
            {"accountAddresses": current_addresses + new_addresses},
        )

    def delete_webhook(self, webhook_id: str) -> bool:
        normalized = self._ensure_managed_id(webhook_id)
        self.client.delete_webhook(normalized)
        print(f"Deleted webhook: {normalized}")
        return True

    def create_webhook(self, config: dict[str, Any]) -> dict[str, Any]:
        result = self.client.create_webhook(config)
        print(f"Created webhook: {extract_webhook_id(result)}")
        return result

    def verify_webhooks(self) -> list[str]:
        print("Verifying webhook configuration...")
        active_webhooks: list[str] = []
        expected_addresses = set(
            WebhookConfig.LST_ADDRESSES
            + WebhookConfig.PARCL_ADDRESSES
            + WebhookConfig.PYTH_ADDRESSES
            + WebhookConfig.ORCA_POOL_ADDRESSES
        )
        for webhook_id in WebhookConfig.WEBHOOK_IDS:
            webhook = self.get_webhook_by_id(webhook_id)
            active_webhooks.append(webhook_id)
            actual_addresses = set(webhook.get("accountAddresses", []))
            missing = sorted(expected_addresses - actual_addresses)
            if missing:
                print(f"Webhook {webhook_id}: missing {len(missing)} addresses")
            else:
                print(f"Webhook {webhook_id}: expected address set is present")
        print(
            f"Verified {len(active_webhooks)}/{len(WebhookConfig.WEBHOOK_IDS)} "
            "webhooks"
        )
        return active_webhooks

    def export_webhook_status(self, output: Path) -> dict[str, Any]:
        status: dict[str, Any] = {
            "management_id": self.management_id,
            "webhook_ids": WebhookConfig.WEBHOOK_IDS,
            "webhook_event_types": WebhookConfig.WEBHOOK_EVENT_TYPES,
            "webhook_details": [],
        }
        details = status["webhook_details"]
        assert isinstance(details, list)
        for webhook_id in WebhookConfig.WEBHOOK_IDS:
            webhook = self.get_webhook_by_id(webhook_id, silent=True)
            details.append(
                {
                    "id": webhook_id,
                    "url": webhook.get("webhookURL"),
                    "type": webhook.get("webhookType"),
                    "events": WebhookConfig.WEBHOOK_EVENT_TYPES.get(
                        webhook_id, []
                    ),
                    "addresses": webhook.get("accountAddresses", []),
                    "status": "active",
                }
            )
        output.write_text(
            json.dumps(status, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"Webhook status exported to {output}")
        return status


def _split_addresses(value: str) -> list[str]:
    return [
        item.strip()
        for item in value.replace(",", " ").split()
        if item.strip()
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage configured Helius webhooks"
    )
    parser.add_argument("--management-id")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List Helius webhooks")
    subparsers.add_parser("verify", help="Verify configured webhooks")

    export_parser = subparsers.add_parser(
        "export", help="Export configured webhook status"
    )
    export_parser.add_argument(
        "--output", type=Path, default=Path("webhook_status.json")
    )

    add_parser = subparsers.add_parser(
        "add-addresses", help="Add account addresses to a webhook"
    )
    add_parser.add_argument("--webhook-id", required=True)
    add_parser.add_argument("--addresses", required=True)

    delete_parser = subparsers.add_parser("delete", help="Delete a webhook")
    delete_parser.add_argument("--webhook-id", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        manager = WebhookManager(args.management_id)
        if args.command == "list":
            manager.get_webhooks()
        elif args.command == "verify":
            manager.verify_webhooks()
        elif args.command == "export":
            manager.export_webhook_status(args.output)
        elif args.command == "add-addresses":
            manager.add_addresses_to_webhook(
                args.webhook_id, _split_addresses(args.addresses)
            )
        elif args.command == "delete":
            manager.delete_webhook(args.webhook_id)
        else:
            raise HeliusWebhookContractError(
                f"unsupported command: {args.command}"
            )
        return 0
    except (HeliusWebhookContractError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
