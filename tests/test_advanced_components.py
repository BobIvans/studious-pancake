#!/usr/bin/env python3
"""Test script for advanced trading components."""

import asyncio
import logging
from decimal import Decimal
from src.ingest.optimal_trade_sizer import OptimalTradeSizer, VelocitySlippageManager, ArbitragePath, PoolReserves

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_optimal_sizing():
    """Test optimal trade sizing."""
    logger.info("🧪 Testing Optimal Trade Sizing...")

    sizer = OptimalTradeSizer()

    # Mock quote data
    quote1 = {"outAmount": "1000000000"}  # 1 SOL out
    quote2 = {"outAmount": "1020000000"}  # 1.02 SOL out

    result = sizer.find_optimal_trade_size(
        quote1=quote1,
        quote2=quote2,
        base_mint_decimals=9,
        intermediate_mint_decimals=9,
        working_cap_sol=1.0
    )

    logger.info(f"Optimal amount: {result}")

async def test_slippage_manager():
    """Test dynamic slippage."""
    logger.info("🧪 Testing Velocity Slippage Manager...")

    manager = VelocitySlippageManager()

    # Simulate high velocity (many transactions)
    for i in range(15):
        manager.record_transaction(i * 0.05)  # 20 tx/sec

    slippage = manager.get_dynamic_slippage()
    logger.info(f"High velocity slippage: {slippage:.1%}")

    # Test safety check
    is_safe = manager.validate_slippage_safety(
        expected_out=Decimal('1.05'),
        borrowed_amount=Decimal('1.0'),
        total_fees=Decimal('0.01'),
        slippage=slippage
    )
    logger.info(f"Safety check passed: {is_safe}")

async def test_arbitrage_path():
    """Test arbitrage path calculations."""
    logger.info("🧪 Testing Arbitrage Path...")

    # Create a simple arbitrage path
    pools = [
        PoolReserves(reserve_in=Decimal('1000'), reserve_out=Decimal('1000')),
        PoolReserves(reserve_in=Decimal('1000'), reserve_out=Decimal('1000'))
    ]
    path = ArbitragePath(pools)

    profit = path.calculate_profit(Decimal('10'))
    logger.info(f"Path profit: {profit}")

async def main():
    """Run all tests."""
    logger.info("🚀 Starting Advanced Components Tests...")

    try:
        await test_optimal_sizing()
        await test_slippage_manager()
        await test_arbitrage_path()
        logger.info("✅ All tests completed")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())