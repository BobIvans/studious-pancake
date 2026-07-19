#!/usr/bin/env python3
"""Test script for Pre-Trade Guard functionality."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from solders.pubkey import Pubkey
from src.ingest.pre_trade_guard import TokenSecurityChecker, LiquidityValidator, PreTradeGuard
import pytest
pytestmark = pytest.mark.unit


class TestPreTradeGuard(unittest.TestCase):

    def setUp(self):
        self.loop = asyncio.get_event_loop()

    @patch('aiohttp.ClientSession.post')
    def test_token_security_whitelist(self, mock_post):
        """Проверка, что токены из белого списка (например, SOL) проходят проверку мгновенно."""

        checker = TokenSecurityChecker(session=None, rpc_url="http://dummy")

        is_safe, reason = self.loop.run_until_complete(
            checker.check_token_security("So11111111111111111111111111111111111111112")
        )
        self.assertTrue(is_safe)
        self.assertEqual(reason, "Whitelisted safe token")

    @patch('aiohttp.ClientSession.post')
    def test_token_security_honeypot_detection(self, mock_post):
        """Проверка детектора ханипотов по структуре Token-2022."""
        checker = TokenSecurityChecker(session=MagicMock(), rpc_url="http://dummy")

        mock_response = AsyncMock()
        mock_response.status = 200
        fake_binary = b"\x00" * 166 + b"\x0d\x00\x04\x00" + b"\x00" * 10
        import base64
        fake_b64 = base64.b64encode(fake_binary).decode('ascii')

        mock_response.json = AsyncMock(return_value={
            "result": {
                "value": {
                    "owner": "TokenzQdBNbLqP5VEhfqASPWnGD1x1gUghStfV2hLwx",
                    "data": [fake_b64, "base64"]
                }
            }
        })
        mock_post.return_value.__aenter__.return_value = mock_response

        is_safe, reason = self.loop.run_until_complete(
            checker.check_token_security("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", rpc_url="http://dummy")
        )
        self.assertFalse(is_safe)
        self.assertIn("PermanentDelegate", reason)


if __name__ == "__main__":
    unittest.main()
