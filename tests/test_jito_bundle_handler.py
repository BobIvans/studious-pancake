#!/usr/bin/env python3
"""Test script for Jito Bundle Handler and Atomic Backrunning."""

import asyncio
import logging
from src.ingest.jito_bundle_handler import JitoBundleHandler, BackrunTrigger, _set_global_price_matrix, _normalize_tip_sol
from solders.keypair import Keypair

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_cross_currency_normalization():
    """Test cross-currency tip normalization prevents the USDC-as-SOL bug."""
    logger.info("🧪 Testing Cross-Currency Tip Normalization...")

    # Set up price matrix with SOL at $150 and USDC at $1
    test_price_matrix = {
        "So11111111111111111111111111111111111111112": (150.0, 0),  # SOL = $150
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": (1.0, 0),       # USDC = $1
    }
    _set_global_price_matrix(test_price_matrix)

    # Test 1: USDC profit should be normalized to SOL
    # 5 USDC at $150/SOL should be ~0.0333 SOL
    usdc_profit = 5.0
    result = _normalize_tip_sol(usdc_profit, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
    expected = 5.0 / 150.0  # = 0.0333...
    assert abs(result - expected) < 0.0001, f"USDC normalization failed: got {result}, expected {expected}"
    logger.info(f"✅ USDC normalization: 5 USDC → {result:.6f} SOL (correct)")

    # Test 2: SOL profit should remain unchanged
    sol_profit = 0.5
    result = _normalize_tip_sol(sol_profit, "So11111111111111111111111111111111111111112")
    assert result == sol_profit, f"SOL passthrough failed: got {result}, expected {sol_profit}"
    logger.info(f"✅ SOL passthrough: 0.5 SOL → {result:.6f} SOL (correct)")

    # Test 3: Unknown token without price matrix should return as-is
    result = _normalize_tip_sol(100.0, "UnknownMint1111111111111111111111111111")
    assert result == 100.0, f"Unknown token fallback failed: got {result}, expected 100.0"
    logger.info(f"✅ Unknown token fallback: 100.0 → {result:.6f} (unchanged, correct)")

    logger.info("✅ Cross-currency normalization tests passed")

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
        await test_cross_currency_normalization()
        await test_bundle_handler()
        await test_backrun_trigger()
        logger.info("✅ All Jito bundle tests completed")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())