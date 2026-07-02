"""Test Helius Webhook Handler."""

import asyncio
import json
import hmac
import hashlib
import os
import glob
from aiohttp import web
import pytest

from src.ingest.helius_webhook_handler import HeliusWebhookHandler
from src.ingest.data_aggregator import DataAggregator


def test_hmac_signature_computation():
    """Test HMAC-SHA256 signature computation logic."""
    secret = "test_webhook_secret_12345"
    body = json.dumps({"test": "data"}).encode('utf-8')
    
    expected_sig = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    
    assert len(expected_sig) == 64, "Signature should be 64 hex chars"
    assert isinstance(expected_sig, str), "Signature should be string"
    
    wrong_sig = "a" * 64
    assert not hmac.compare_digest(expected_sig, wrong_sig), "Different signatures should not match"
    
    same_sig = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected_sig, same_sig), "Same computation should match"


def test_rate_limiter_structure():
    """Test rate limiter data structure initialization."""
    da = DataAggregator("test_rate.db")
    handler = HeliusWebhookHandler(da, 9999)
    
    assert hasattr(handler, 'ip_limits'), "Handler should have ip_limits attribute"
    assert handler.MAX_REQ_PER_SEC == 5, "MAX_REQ_PER_SEC should be 5"


async def test_webhook_handler_basic():
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
        pass

    handler = HeliusWebhookHandler(data_aggregator, 8081, mock_callback)

    for event in sample_webhook_data["events"]:
        await handler._process_event(event, sample_webhook_data["webhookId"])

    print("✅ Webhook handler test completed")

    export_file = await data_aggregator.export_for_analysis(days=1)
    print(f"📊 Test data exported to {export_file}")

    import glob
    for jsonl_file in glob.glob("bot_analysis_*.jsonl"):
        try:
            os.remove(jsonl_file)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(test_webhook_handler_basic())
    finally:
        for temp_file in ["test_bot_history.db", "test_bot_history.db-shm", "test_bot_history.db-wal"]:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass