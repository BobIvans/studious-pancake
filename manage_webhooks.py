"""Helius Webhook Management Script.

Manage LST arbitrage webhooks programmatically using stored IDs.
"""

import json
import requests
import os
from dotenv import load_dotenv
from src.ingest.webhook_config import WebhookConfig

# Load environment variables
load_dotenv()

class WebhookManager:
    """Manage Helius webhooks for LST arbitrage monitoring."""

    def __init__(self):
        self.api_key = os.getenv("HELIUS_API_KEY")
        if not self.api_key:
            raise ValueError("HELIUS_API_KEY not found in environment")

        self.base_url = "https://api.helius.xyz/v0"
        self.management_id = WebhookConfig.PRIMARY_MANAGEMENT_ID

    def get_webhooks(self):
        """Get all webhooks for the management ID."""
        url = f"{self.base_url}/webhooks?api-key={self.api_key}"
        response = requests.get(url)

        if response.status_code == 200:
            webhooks = response.json()
            print(f"✅ Found {len(webhooks)} webhooks")
            return webhooks
        else:
            print(f"❌ Error getting webhooks: {response.status_code}")
            print(response.text)
            return []

    def get_webhook_by_id(self, webhook_id: str):
        """Get specific webhook details."""
        url = f"{self.base_url}/webhooks/{webhook_id}?api-key={self.api_key}"
        response = requests.get(url)

        if response.status_code == 200:
            webhook = response.json()
            print(f"✅ Retrieved webhook: {webhook_id}")
            return webhook
        else:
            print(f"❌ Error getting webhook {webhook_id}: {response.status_code}")
            print(response.text)
            return None

    def update_webhook(self, webhook_id: str, updates: dict):
        """Update a webhook configuration."""
        url = f"{self.base_url}/webhooks/{webhook_id}?api-key={self.api_key}"
        response = requests.put(url, json=updates)

        if response.status_code == 200:
            result = response.json()
            print(f"✅ Updated webhook: {webhook_id}")
            return result
        else:
            print(f"❌ Error updating webhook {webhook_id}: {response.status_code}")
            print(response.text)
            return None

    def delete_webhook(self, webhook_id: str):
        """Delete a webhook."""
        url = f"{self.base_url}/webhooks/{webhook_id}?api-key={self.api_key}"
        response = requests.delete(url)

        if response.status_code == 200:
            print(f"✅ Deleted webhook: {webhook_id}")
            return True
        else:
            print(f"❌ Error deleting webhook {webhook_id}: {response.status_code}")
            print(response.text)
            return False

    def create_webhook(self, config: dict):
        """Create a new webhook."""
        url = f"{self.base_url}/webhooks?api-key={self.api_key}"
        response = requests.post(url, json=config)

        if response.status_code == 200:
            result = response.json()
            webhook_id = result.get("webhookId")
            print(f"✅ Created webhook: {webhook_id}")
            return result
        else:
            print(f"❌ Error creating webhook: {response.status_code}")
            print(response.text)
            return None

    def verify_webhooks(self):
        """Verify that all configured webhooks exist and are active."""
        print("🔍 Verifying webhook configuration...")

        active_webhooks = []
        for webhook_id in WebhookConfig.WEBHOOK_IDS:
            webhook = self.get_webhook_by_id(webhook_id)
            if webhook:
                active_webhooks.append(webhook_id)
                # Check if addresses match
                addresses = webhook.get("accountAddresses", [])
                expected_addresses = set(WebhookConfig.LST_ADDRESSES)
                actual_addresses = set(addresses)

                if expected_addresses == actual_addresses:
                    print(f"✅ Webhook {webhook_id}: Addresses match")
                else:
                    print(f"⚠️ Webhook {webhook_id}: Address mismatch")
                    print(f"  Expected: {sorted(expected_addresses)}")
                    print(f"  Actual: {sorted(actual_addresses)}")
            else:
                print(f"❌ Webhook {webhook_id}: Not found")

        print(f"✅ Verified {len(active_webhooks)}/{len(WebhookConfig.WEBHOOK_IDS)} webhooks")
        return active_webhooks

    def export_webhook_status(self):
        """Export current webhook status to JSON."""
        status = {
            "timestamp": requests.get("http://worldtimeapi.org/api/timezone/Europe/Moscow").json().get("datetime", ""),
            "management_id": self.management_id,
            "webhook_ids": WebhookConfig.WEBHOOK_IDS,
            "lst_addresses": WebhookConfig.LST_ADDRESSES,
            "webhook_details": []
        }

        for webhook_id in WebhookConfig.WEBHOOK_IDS:
            webhook = self.get_webhook_by_id(webhook_id)
            if webhook:
                status["webhook_details"].append({
                    "id": webhook_id,
                    "url": webhook.get("webhookURL"),
                    "type": webhook.get("webhookType"),
                    "addresses": webhook.get("accountAddresses", []),
                    "status": "active"
                })
            else:
                status["webhook_details"].append({
                    "id": webhook_id,
                    "status": "inactive"
                })

        with open("webhook_status.json", "w") as f:
            json.dump(status, f, indent=2)

        print("📁 Webhook status exported to webhook_status.json")
        return status

def main():
    """Main function for webhook management."""
    print("🚀 Helius Webhook Manager")
    print("=" * 50)

    try:
        manager = WebhookManager()

        print(f"📊 Management ID: {manager.management_id}")
        print(f"🎯 LST Addresses: {len(WebhookConfig.LST_ADDRESSES)}")
        print(f"🔗 Active Webhooks: {len(WebhookConfig.WEBHOOK_IDS)}")
        print()

        # Show webhook info
        info = WebhookConfig.get_webhook_info()
        print("📋 Configuration:")
        for key, value in info.items():
            if isinstance(value, list):
                print(f"  {key}: {len(value)} items")
            else:
                print(f"  {key}: {value}")
        print()

        # Verify webhooks
        manager.verify_webhooks()
        print()

        # Export status
        manager.export_webhook_status()
        print()

        print("✅ Webhook management complete!")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()