"""Helius Webhook Management Script.

Manage LST arbitrage webhooks programmatically using stored IDs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Iterable, List, Optional

import requests
from dotenv import load_dotenv

from src.ingest.webhook_config import WebhookConfig

load_dotenv()


class WebhookManager:
    """Manage Helius webhooks for LST arbitrage monitoring."""

    def __init__(self, management_id: Optional[str] = None):
        self.api_key = os.getenv("HELIUS_API_KEY")
        if not self.api_key:
            raise ValueError("HELIUS_API_KEY not found in environment")

        self.base_url = "https://api.helius.xyz/v0"
        self.management_id = management_id or WebhookConfig.PRIMARY_MANAGEMENT_ID

    def _ensure_managed_id(self, webhook_id: str) -> None:
        if webhook_id not in WebhookConfig.MANAGEMENT_IDS:
            raise ValueError(f"Webhook ID is not configured for management: {webhook_id}")

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}?api-key={self.api_key}"
        response = requests.request(method, url, timeout=30, **kwargs)
        return response

    def get_webhooks(self):
        """Get all webhooks for the management ID."""
        response = self._request("GET", "/webhooks")

        if response.status_code == 200:
            webhooks = response.json()
            print(f"Found {len(webhooks)} webhooks")
            return webhooks

        print(f"Error getting webhooks: {response.status_code}")
        print(response.text)
        return []

    def get_webhook_by_id(self, webhook_id: str, silent: bool = False):
        """Get specific webhook details."""
        response = self._request("GET", f"/webhooks/{webhook_id}")

        if response.status_code == 200:
            webhook = response.json()
            if not silent:
                print(f"Retrieved webhook: {webhook_id}")
            return webhook

        if not silent:
            print(f"Error getting webhook {webhook_id}: {response.status_code}")
            print(response.text)
        return None

    def update_webhook(self, webhook_id: str, updates: dict):
        """Merge updates into an existing webhook and PUT it to Helius."""
        self._ensure_managed_id(webhook_id)
        current = self.get_webhook_by_id(webhook_id, silent=True)
        if not current:
            return None

        merged = dict(current)
        merged.update(updates)

        response = self._request("PUT", f"/webhooks/{webhook_id}", json=merged)

        if response.status_code == 200:
            result = response.json()
            print(f"Updated webhook: {webhook_id}")
            return result

        print(f"Error updating webhook {webhook_id}: {response.status_code}")
        print(response.text)
        return None

    def add_addresses_to_webhook(self, webhook_id: str, addresses: Iterable[str]):
        """Add new account addresses to a configured webhook ID."""
        self._ensure_managed_id(webhook_id)
        current = self.get_webhook_by_id(webhook_id, silent=True)
        if not current:
            return None

        clean_addresses = [address.strip() for address in addresses if address and address.strip()]
        if not clean_addresses:
            print("No addresses supplied")
            return None

        current_addresses = list(dict.fromkeys(current.get("accountAddresses") or []))
        new_addresses = [address for address in clean_addresses if address not in current_addresses]
        if not new_addresses:
            print(f"All {len(clean_addresses)} address(es) already exist on webhook {webhook_id}")
            return current

        updates = {"accountAddresses": current_addresses + new_addresses}
        return self.update_webhook(webhook_id, updates)

    def delete_webhook(self, webhook_id: str):
        """Delete a webhook."""
        self._ensure_managed_id(webhook_id)
        response = self._request("DELETE", f"/webhooks/{webhook_id}")

        if response.status_code == 200:
            print(f"Deleted webhook: {webhook_id}")
            return True

        print(f"Error deleting webhook {webhook_id}: {response.status_code}")
        print(response.text)
        return False

    def create_webhook(self, config: dict):
        """Create a new webhook."""
        response = self._request("POST", "/webhooks", json=config)

        if response.status_code == 200:
            result = response.json()
            webhook_id = result.get("webhookId")
            print(f"Created webhook: {webhook_id}")
            return result

        print(f"Error creating webhook: {response.status_code}")
        print(response.text)
        return None

    def verify_webhooks(self):
        """Verify that all configured webhooks exist and are active."""
        print("Verifying webhook configuration...")

        active_webhooks = []
        for webhook_id in WebhookConfig.WEBHOOK_IDS:
            webhook = self.get_webhook_by_id(webhook_id)
            if webhook:
                active_webhooks.append(webhook_id)
                addresses = webhook.get("accountAddresses", [])
                expected_addresses = set(WebhookConfig.LST_ADDRESSES + WebhookConfig.XSTOCK_ADDRESSES + WebhookConfig.PARCL_ADDRESSES + WebhookConfig.PYTH_ADDRESSES + WebhookConfig.ORCA_POOL_ADDRESSES)
                actual_addresses = set(addresses)

                if expected_addresses <= actual_addresses:
                    print(f"Webhook {webhook_id}: address set contains expected monitored addresses")
                else:
                    missing = sorted(expected_addresses - actual_addresses)
                    print(f"Webhook {webhook_id}: address mismatch")
                    print(f"  Missing: {missing[:10]}{'...' if len(missing) > 10 else ''}")
            else:
                print(f"Webhook {webhook_id}: Not found")

        print(f"Verified {len(active_webhooks)}/{len(WebhookConfig.WEBHOOK_IDS)} webhooks")
        return active_webhooks

    def export_webhook_status(self):
        """Export current webhook status to JSON."""
        status = {
            "management_id": self.management_id,
            "webhook_ids": WebhookConfig.WEBHOOK_IDS,
            "webhook_event_types": WebhookConfig.WEBHOOK_EVENT_TYPES,
            "webhook_details": []
        }

        for webhook_id in WebhookConfig.WEBHOOK_IDS:
            webhook = self.get_webhook_by_id(webhook_id, silent=True)
            if webhook:
                status["webhook_details"].append({
                    "id": webhook_id,
                    "url": webhook.get("webhookURL"),
                    "type": webhook.get("webhookType"),
                    "events": WebhookConfig.WEBHOOK_EVENT_TYPES.get(webhook_id, []),
                    "addresses": webhook.get("accountAddresses", []),
                    "status": "active"
                })
            else:
                status["webhook_details"].append({
                    "id": webhook_id,
                    "events": WebhookConfig.WEBHOOK_EVENT_TYPES.get(webhook_id, []),
                    "status": "inactive"
                })

        with open("webhook_status.json", "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2)

        print("Webhook status exported to webhook_status.json")
        return status


def _split_addresses(value: str) -> List[str]:
    return [item.strip() for item in value.replace(",", " ").split() if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage configured Helius webhooks")
    parser.add_argument("--management-id", choices=WebhookConfig.MANAGEMENT_IDS, default=WebhookConfig.PRIMARY_MANAGEMENT_ID)

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List Helius webhooks")

    verify_parser = subparsers.add_parser("verify", help="Verify configured webhooks")
    verify_parser.set_defaults(func=lambda args, manager: manager.verify_webhooks())

    export_parser = subparsers.add_parser("export", help="Export configured webhook status")
    export_parser.set_defaults(func=lambda args, manager: manager.export_webhook_status())

    add_parser = subparsers.add_parser("add-addresses", help="Add account addresses to a configured webhook ID")
    add_parser.add_argument("--webhook-id", required=True, choices=WebhookConfig.MANAGEMENT_IDS)
    add_parser.add_argument("--addresses", required=True, help="Space/comma separated Solana account addresses")
    add_parser.set_defaults(func=lambda args, manager: manager.add_addresses_to_webhook(args.webhook_id, _split_addresses(args.addresses)))

    delete_parser = subparsers.add_parser("delete", help="Delete a configured webhook ID")
    delete_parser.add_argument("--webhook-id", required=True, choices=WebhookConfig.MANAGEMENT_IDS)
    delete_parser.set_defaults(func=lambda args, manager: manager.delete_webhook(args.webhook_id))

    return parser


def main() -> int:
    """Main function for webhook management."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        manager = WebhookManager(args.management_id)

        print("Helius Webhook Manager")
        print("=" * 50)
        print(f"Management ID: {manager.management_id}")
        print(f"LST Addresses: {len(WebhookConfig.LST_ADDRESSES)}")
        print(f"Active Webhooks: {len(WebhookConfig.WEBHOOK_IDS)}")
        print("Configured webhook event types:")
        for webhook_id, events in WebhookConfig.WEBHOOK_EVENT_TYPES.items():
            print(f"  {webhook_id}: {', '.join(events)}")
        print()

        if args.command == "list":
            manager.get_webhooks()
        else:
            args.func(args, manager)

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
