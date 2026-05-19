#!/usr/bin/env python3
"""
Helius Webhook Setup Script

Creates a webhook for Sanctum LST arbitrage monitoring.
"""

import json
import requests
import os
from dotenv import load_dotenv
from src.ingest.webhook_config import WebhookConfig

# Load environment variables
load_dotenv()

def check_existing_webhooks(api_key: str):
    """Check for existing LST arbitrage webhooks."""
    url = f"https://api.helius.xyz/v0/webhooks?api-key={api_key}"

    try:
        response = requests.get(url)
        if response.status_code == 200:
            webhooks = response.json()
            existing_lst_webhooks = []

            for webhook in webhooks:
                addresses = set(webhook.get("accountAddresses", []))
                lst_addresses = set(WebhookConfig.LST_ADDRESSES)

                if lst_addresses.issubset(addresses):
                    existing_lst_webhooks.append({
                        "id": webhook.get("webhookId"),
                        "url": webhook.get("webhookURL"),
                        "addresses": len(addresses)
                    })

            return existing_lst_webhooks
        else:
            print(f"⚠️ Could not check existing webhooks: {response.status_code}")
            return []

    except Exception as e:
        print(f"⚠️ Error checking existing webhooks: {e}")
        return []

def create_helius_webhook():
    """Create Helius webhook for LST arbitrage monitoring."""

    # Helius API endpoint
    api_key = os.getenv("HELIUS_API_KEY")
    if not api_key:
        print("❌ HELIUS_API_KEY not found in .env file")
        return

    # Check for existing webhooks
    print("🔍 Checking for existing LST webhooks...")
    existing_webhooks = check_existing_webhooks(api_key)

    if existing_webhooks:
        print(f"✅ Found {len(existing_webhooks)} existing LST webhooks:")
        for webhook in existing_webhooks:
            print(f"  🆔 {webhook['id']} -> {webhook['url']} ({webhook['addresses']} addresses)")

        # Check if we have all configured webhooks
        existing_ids = {w['id'] for w in existing_webhooks}
        configured_ids = set(WebhookConfig.WEBHOOK_IDS)

        if existing_ids == configured_ids:
            print("✅ All configured webhooks are active!")
            return WebhookConfig.WEBHOOK_IDS[0]  # Return first ID
        else:
            print("⚠️ Webhook configuration mismatch. Some webhooks may need recreation.")

    url = f"https://api.helius.xyz/v0/webhooks?api-key={api_key}"

    # Use configuration from WebhookConfig
    webhook_data = WebhookConfig.get_webhook_config()

    print("🚀 Creating Helius webhook...")
    print(f"📡 URL: {webhook_data['webhookURL']}")
    print(f"🎯 Monitoring {len(webhook_data['accountAddresses'])} LST addresses")
    print(f"📊 Transaction types: {', '.join(webhook_data['transactionTypes'])}")

    try:
        response = requests.post(url, json=webhook_data, headers={
            "Content-Type": "application/json"
        })

        if response.status_code == 200:
            result = response.json()
            webhook_id = result.get("webhookId")

            print("✅ Webhook created successfully!")
            print(f"🆔 Webhook ID: {webhook_id}")

            # Save webhook ID to existing IDs file
            current_ids = []
            if os.path.exists("helius_webhook_ids.txt"):
                with open("helius_webhook_ids.txt", "r") as f:
                    current_ids = [line.strip() for line in f if line.strip()]

            if webhook_id not in current_ids:
                current_ids.append(webhook_id)
                with open("helius_webhook_ids.txt", "w") as f:
                    f.write("\n".join(current_ids))

            # Save full configuration
            with open("helius_webhook_config.json", "w") as f:
                json.dump(webhook_data, f, indent=2)

            print("📁 IDs saved to helius_webhook_ids.txt")
            print("📁 Configuration saved to helius_webhook_config.json")

            return webhook_id

        else:
            print(f"❌ Error creating webhook: {response.status_code}")
            print(response.text)
            return None

    except Exception as e:
        print(f"❌ Error: {e}")
        return None

if __name__ == "__main__":
    print("🎯 Helius LST Arbitrage Webhook Setup")
    print("=" * 50)
    print(f"📊 Monitoring {len(WebhookConfig.LST_ADDRESSES)} addresses:")
    for addr in WebhookConfig.LST_ADDRESSES:
        name = {
            "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": "JitoSOL",
            "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": "mSOL",
            "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1": "bSOL",
            "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm": "INF",
            "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq": "Sanctum Router"
        }.get(addr, addr[:8])
        print(f"  • {name}: {addr}")
    print()
    print(f"🔗 Expected webhook IDs: {len(WebhookConfig.WEBHOOK_IDS)}")
    for i, wid in enumerate(WebhookConfig.WEBHOOK_IDS, 1):
        print(f"  {i}. {wid}")
    print()

    webhook_id = create_helius_webhook()
    if webhook_id:
        print("\n🎉 Setup complete!")
        print("✅ Your webhooks are ready to receive LST arbitrage signals.")
        print(f"🆔 Primary webhook ID: {webhook_id}")
        print(f"🎛️ Management IDs: {', '.join(WebhookConfig.MANAGEMENT_IDS)}")
        print("\n💡 Use 'python manage_webhooks.py' to check webhook status.")
    else:
        print("\n❌ Setup failed. Please check your configuration.")
        print("💡 Make sure HELIUS_API_KEY is set in your .env file.")