#!/usr/bin/env python3
"""Test script for Jito Bundle Handler and Atomic Backrunning."""

import asyncio
import logging
from src.ingest.jito_bundle_handler import JitoBundleHandler, BackrunTrigger
from solders.keypair import Keypair

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_bundle_handler():
    """Test Jito bundle handler functionality."""
    logger.info("🧪 Testing Jito Bundle Handler...")

    # Create a test keypair (don't use real keys!)
    keypair = Keypair()

    # Initialize handler
    handler = JitoBundleHandler(keypair)

    # Test tip account selection
    tip_account = handler._select_tip_account()
    logger.info(f"Selected tip account: {tip_account}")

    # Test template creation
    template_key = handler.bundle_template.create_arbitrage_template(
        "So11111111111111111111111111111111111111112",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        1.0
    )
    logger.info(f"Created template: {template_key}")

    # Test tip transaction creation
    tip_tx = handler.bundle_template.create_tip_template(50000, tip_account)
    logger.info(f"Created tip transaction: {tip_tx.message.recent_blockhash}")

    logger.info("✅ Bundle handler basic functionality test passed")

async def test_backrun_trigger():
    """Test backrun trigger logic."""
    logger.info("🧪 Testing Backrun Trigger...")

    keypair = Keypair()
    handler = JitoBundleHandler(keypair)
    trigger = BackrunTrigger(handler)

    # Test migration event handling (would need real signature/blockhash)
    logger.info("Backrun trigger structure test passed (simulation skipped)")

async def main():
    """Run all tests."""
    logger.info("🚀 Starting Jito Bundle Handler Tests...")

    try:
        await test_bundle_handler()
        await test_backrun_trigger()
        logger.info("✅ All Jito bundle tests completed")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())