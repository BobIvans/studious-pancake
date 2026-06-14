#!/usr/bin/env python3
"""
Unit Tests for Jito Sniper Components

Tests the WebSocket-based pool creation sniping system with Jito bundles.
"""

import asyncio
import unittest
import sys
import os
from unittest.mock import Mock, patch, AsyncMock

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ingest.jito_sniper import (
    JitoTipManager,
    WssPoolCreationListener,
    JitoBundleSender,
    TransactionTipBuilder,
    PoolCreationEvent
)


class TestJitoTipManager(unittest.TestCase):
    """Test Jito tip management functionality."""

    def setUp(self):
        self.tip_manager = JitoTipManager(percentile=75.0, min_tip_lamports=10000)

    def test_initial_state(self):
        """Test initial state without data."""
        tip = self.tip_manager.get_optimal_tip()
        self.assertEqual(tip, 10000)  # Should return minimum

    def test_optimal_tip_calculation(self):
        """Test tip calculation with sample data."""
        import time
        # Simulate tip data
        self.tip_manager.current_tips = [10000, 20000, 30000, 40000, 50000]  # Sorted
        self.tip_manager.last_update = time.time()  # Use time.time() instead of asyncio loop
        self.tip_manager.current_percentiles = {"75th": 40000}
        self.tip_manager.ema_75th = 40000

        # 75th percentile should be near the higher end
        tip = self.tip_manager.get_optimal_tip()
        self.assertGreaterEqual(tip, 30000)  # At least 75th percentile
        self.assertEqual(tip, 44000)  # 40000 * tip_multiplier (1.1)

    def test_minimum_tip_enforcement(self):
        """Test that minimum tip is always enforced."""
        import time
        self.tip_manager.current_tips = [1000, 2000, 3000]  # All below minimum
        self.tip_manager.last_update = time.time()

        tip = self.tip_manager.get_optimal_tip()
        self.assertEqual(tip, 10000)  # Should enforce minimum

    def test_stale_data_handling(self):
        """Test handling of stale tip data."""
        self.tip_manager.current_tips = [50000]
        self.tip_manager.last_update = 0  # Very old

        tip = self.tip_manager.get_optimal_tip()
        self.assertEqual(tip, 10000)  # Should return minimum for stale data

    def test_random_tip_account(self):
        """Test random tip account selection."""
        account = self.tip_manager.get_random_tip_account()
        self.assertIn(account, self.tip_manager.DEFAULT_TIP_ACCOUNTS)


class TestWssPoolCreationListener(unittest.TestCase):
    """Test WebSocket pool creation listener."""

    def setUp(self):
        self.listener = WssPoolCreationListener()
        self.listener.event_callback = AsyncMock()

    def test_target_programs(self):
        """Test that target programs are configured."""
        self.assertIn("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8", self.listener.TARGET_PROGRAMS)

    def test_pool_creation_parsing(self):
        """Test parsing of pool creation logs."""
        # Set up a subscription so program_id can be determined
        self.listener.subscriptions["675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"] = 1

        # Mock logs that should trigger pool creation detection
        logs = [
            "Program 675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8 invoke [1]",
            "Initialize AMM pool with tokens...",
            "Pool created successfully"
        ]

        result = self.listener._parse_pool_creation_logs(logs, "test_signature", 12345)

        # Should detect pool creation
        self.assertIsNotNone(result)
        self.assertIsInstance(result, PoolCreationEvent)
        self.assertEqual(result.program_id, "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
        self.assertEqual(result.signature, "test_signature")
        self.assertEqual(result.slot, 12345)

    def test_non_pool_logs(self):
        """Test that non-pool logs are ignored."""
        logs = [
            "Transfer 1 SOL",
            "System program success"
        ]

        result = self.listener._parse_pool_creation_logs(logs, "test_signature", 12345)
        self.assertIsNone(result)


class TestJitoBundleSender(unittest.TestCase):
    """Test Jito bundle sending functionality."""

    def setUp(self):
        self.sender = JitoBundleSender()

    def test_endpoint_configuration(self):
        """Test that Jito endpoints are configured."""
        self.assertEqual(len(self.sender.JITO_ENDPOINTS), 1)  # Single NY endpoint
        self.assertTrue(all("jito.wtf" in endpoint for endpoint in self.sender.JITO_ENDPOINTS))

    @patch('aiohttp.ClientSession.post')
    async def test_successful_bundle_send(self, mock_post):
        """Test successful bundle sending."""
        # Mock successful response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"result": "bundle_123"})
        mock_post.return_value.__aenter__.return_value = mock_response

        # Create mock transaction
        mock_tx = Mock()
        mock_tx.to_bytes.return_value.hex.return_value = "deadbeef"

        async with self.sender:
            result = await self.sender.send_bundle(mock_tx)

        self.assertTrue(result["success"])
        self.assertEqual(result["success_count"], 4)  # All endpoints should succeed
        self.assertEqual(result["first_bundle_id"], "bundle_123")

    @patch('aiohttp.ClientSession.post')
    async def test_tip_failure_handling(self, mock_post):
        """Test handling of tip payment failures."""
        # Mock response with tip error
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.json = AsyncMock(return_value={"error": "Insufficient tip"})
        mock_post.return_value.__aenter__.return_value = mock_response

        mock_tx = Mock()
        mock_tx.to_bytes.return_value.hex.return_value = "deadbeef"

        async with self.sender:
            result = await self.sender.send_bundle(mock_tx)

        self.assertFalse(result["success"])
        self.assertEqual(result["success_count"], 0)
        self.assertIn("tip", result["errors"][0].lower())

    @patch('aiohttp.ClientSession.post')
    async def test_partial_bundle_send(self, mock_post):
        """Test partial bundle sending (some endpoints fail)."""
        # Mock mixed responses
        def mock_response_factory(*args, **kwargs):
            mock_resp = AsyncMock()
            endpoint = args[0] if args else ""

            if "frankfurt" in endpoint:
                mock_resp.status = 200
                mock_resp.json = AsyncMock(return_value={"result": "bundle_123"})
            else:
                mock_resp.status = 500
                mock_resp.json = AsyncMock(return_value={"error": "Server error"})

            return mock_resp

        mock_post.side_effect = lambda *args, **kwargs: AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response_factory(*args, **kwargs))
        )

        mock_tx = Mock()
        mock_tx.to_bytes.return_value.hex.return_value = "deadbeef"

        async with self.sender:
            result = await self.sender.send_bundle(mock_tx)

        self.assertTrue(result["success"])
        self.assertEqual(result["success_count"], 1)  # Only Frankfurt succeeds
        self.assertEqual(result["first_bundle_id"], "bundle_123")

    @patch('aiohttp.ClientSession.post')
    async def test_failed_bundle_send(self, mock_post):
        """Test complete bundle send failure."""
        # Mock all failures
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.json = AsyncMock(return_value={"error": "All endpoints down"})
        mock_post.return_value.__aenter__.return_value = mock_response

        mock_tx = Mock()
        mock_tx.to_bytes.return_value.hex.return_value = "deadbeef"

        async with self.sender:
            result = await self.sender.send_bundle(mock_tx)

        self.assertFalse(result["success"])
        self.assertEqual(result["success_count"], 0)
        self.assertIsNone(result["first_bundle_id"])


class TestTransactionTipBuilder(unittest.TestCase):
    """Test transaction building with tips."""

    def setUp(self):
        self.tip_manager = JitoTipManager(min_tip_lamports=10000)
        self.builder = TransactionTipBuilder(self.tip_manager)

    @patch('solders.keypair.Keypair')
    async def test_transaction_building(self, mock_keypair):
        """Test basic transaction building."""
        # Mock keypair
        mock_keypair.pubkey.return_value = Mock()
        mock_keypair.pubkey().__str__ = Mock(return_value="test_pubkey")

        # Create mock pool event
        pool_event = PoolCreationEvent(
            program_id="675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
            pool_address="pool_address",
            base_mint="base_mint",
            quote_mint="quote_mint",
            timestamp=1234567890.0,
            slot=12345,
            signature="test_signature"
        )

        # Build transaction
        result = await self.builder.build_sniping_transaction(
            pool_event=pool_event,
            buyer_keypair=mock_keypair,
            buy_amount_lamports=1_000_000_000
        )

        # Should return a transaction (even if mocked)
        self.assertIsNotNone(result)


class TestPoolCreationEvent(unittest.TestCase):
    """Test PoolCreationEvent data structure."""

    def test_event_creation(self):
        """Test pool creation event creation."""
        event = PoolCreationEvent(
            program_id="test_program",
            pool_address="test_pool",
            base_mint="base_mint",
            quote_mint="quote_mint",
            timestamp=1234567890.0,
            slot=12345,
            signature="test_sig"
        )

        self.assertEqual(event.program_id, "test_program")
        self.assertEqual(event.pool_address, "test_pool")
        self.assertEqual(event.base_mint, "base_mint")
        self.assertEqual(event.quote_mint, "quote_mint")
        self.assertEqual(event.slot, 12345)
        self.assertEqual(event.signature, "test_sig")

    def test_event_string_representation(self):
        """Test event string representation."""
        event = PoolCreationEvent(
            program_id="test",
            pool_address="pool_12345678",
            base_mint="base_87654321",
            quote_mint="quote_11223344",
            timestamp=0,
            slot=1,
            signature="sig"
        )

        repr_str = str(event)
        self.assertIn("pool_123", repr_str)  # Should match the truncated version
        self.assertIn("base_876", repr_str)
        self.assertIn("quote_11", repr_str)


if __name__ == '__main__':
    # Configure logging for tests
    import logging
    logging.basicConfig(level=logging.WARNING)

    # Run tests
    unittest.main(verbosity=2)