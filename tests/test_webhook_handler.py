"""Test Helius Webhook Handler."""

import asyncio
import json
import hmac
import hashlib
import os
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from src.ingest.helius_webhook_handler import HeliusWebhookHandler
from src.ingest.data_aggregator import DataAggregator


class TestWebhookHandler(AioHTTPTestCase):
    """Test webhook handler with HMAC signature verification."""

    async def get_application(self):
        """Create test application."""
        self.data_aggregator = DataAggregator("test_bot_history.db")
        self.handler = HeliusWebhookHandler(self.data_aggregator, 8081)
        return self.handler.app

    def setUp(self):
        """Set up test environment."""
        os.environ["HELIUS_WEBHOOK_SECRET"] = "test_webhook_secret_12345"

    def tearDown(self):
        """Clean up test environment."""
        if "HELIUS_WEBHOOK_SECRET" in os.environ:
            del os.environ["HELIUS_WEBHOOK_SECRET"]

    def _compute_signature(self, body: bytes) -> str:
        """Compute HMAC-SHA256 signature for test body."""
        secret = os.environ.get("HELIUS_WEBHOOK_SECRET", "").encode('utf-8')
        return hmac.new(secret, body, hashlib.sha256).hexdigest()

    @unittest_run_loop
    async def test_hmac_signature_valid(self):
        """Test webhook accepts valid HMAC signature."""
        test_body = json.dumps({"webhookId": "test-123", "events": [{"type": "SWAP"}]}).encode('utf-8')
        signature = self._compute_signature(test_body)
        
        request = web.Request(
            self.app,
            method="POST",
            path="/webhook",
            headers={"X-Helius-Signature": signature}
        )
        request._read_bytes = test_body
        
        response = await self.handler.handle_webhook(request)
        self.assertEqual(response.status, 200)

    @unittest_run_loop
    async def test_hmac_signature_missing(self):
        """Test webhook rejects missing signature."""
        test_body = json.dumps({"webhookId": "test-123", "events": [{"type": "SWAP"}]}).encode('utf-8')
        
        request = web.Request(
            self.app,
            method="POST",
            path="/webhook",
            headers={}
        )
        request._read_bytes = test_body
        
        response = await self.handler.handle_webhook(request)
        self.assertEqual(response.status, 401)

    @unittest_run_loop
    async def test_hmac_signature_invalid(self):
        """Test webhook rejects invalid signature."""
        test_body = json.dumps({"webhookId": "test-123", "events": [{"type": "SWAP"}]}).encode('utf-8')
        
        request = web.Request(
            self.app,
            method="POST",
            path="/webhook",
            headers={"X-Helius-Signature": "invalid_signature_12345"}
        )
        request._read_bytes = test_body
        
        response = await self.handler.handle_webhook(request)
        self.assertEqual(response.status, 401)


async def test_webhook_handler():
    """Test webhook handler with sample data."""
    sample_webhook_data = {
        "webhookId": "test-webhook-123",
        "events": [
            {
                "type": "SWAP",
                "slot": 123456789,
                "timestamp": 1640995200,
                "tokenTransfers": [
                    {
                        "mint": "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
                        "tokenAmount": 1000000000,
                        "fromUserAccount": "user123...",
                        "toUserAccount": "stkitrT1Uoy18Dk1fTrgPw8W6MVzoCfYoAFT4MLsmhq"
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

    data_aggregator = DataAggregator("test_bot_history.db")

    async def mock_callback(opportunity, webhook_id):
        print(f"Mock callback triggered for opportunity: {opportunity['description']}")

    handler = HeliusWebhookHandler(data_aggregator, 8081, mock_callback)

    for event in sample_webhook_data["events"]:
        await handler._process_event(event, sample_webhook_data["webhookId"])

    print("✅ Webhook handler test completed")

    export_file = await data_aggregator.export_for_analysis(days=1)
    print(f"📊 Test data exported to {export_file}")

if __name__ == "__main__":
    asyncio.run(test_webhook_handler())