"""Test Helius Webhook Handler."""

import asyncio
import json
from src.ingest.helius_webhook_handler import HeliusWebhookHandler
from src.ingest.data_aggregator import DataAggregator

async def test_webhook_handler():
    """Test webhook handler with sample data."""
    # Sample webhook data
    sample_webhook_data = {
        "webhookId": "test-webhook-123",
        "events": [
            {
                "type": "SWAP",
                "slot": 123456789,
                "timestamp": 1640995200,
                "tokenTransfers": [
                    {
                        "mint": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # JitoSOL
                        "tokenAmount": 1000000000,  # 1 JitoSOL
                        "fromUserAccount": "user123...",
                        "toUserAccount": "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq"  # Sanctum Router
                    }
                ],
                "accountData": [
                    {
                        "account": {"address": "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq"},
                        "nativeBalanceChange": 1000000
                    }
                ]
            }
        ]
    }

    # Initialize components
    data_aggregator = DataAggregator("test_bot_history.db")

    async def mock_callback(opportunity, webhook_id):
        print(f"Mock callback triggered for opportunity: {opportunity['description']}")

    handler = HeliusWebhookHandler(data_aggregator, 8081, mock_callback)

    # Simulate webhook processing
    for event in sample_webhook_data["events"]:
        await handler._process_event(event, sample_webhook_data["webhookId"])

    print("✅ Webhook handler test completed")

    # Export test data
    export_file = await data_aggregator.export_for_analysis(days=1)
    print(f"📊 Test data exported to {export_file}")

if __name__ == "__main__":
    asyncio.run(test_webhook_handler())