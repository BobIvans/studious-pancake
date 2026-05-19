#!/usr/bin/env python3
"""
Integration Test for Optimal Trade Sizing in Sniper Engine Pipeline

Tests the complete pipeline integration with optimal trade sizing.
"""

import asyncio
import sys
import os
import logging
from unittest.mock import Mock, patch, AsyncMock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ingest.optimal_trade_sizer import (
    OptimalTradeSizer,
    ArbitragePath,
    PoolReserves,
    ProfitCalculator
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@patch('aiohttp.ClientSession.post')
async def test_pipeline_integration_with_mocked_rpc(mock_post):
    """Test optimal trade sizing with mocked RPC to avoid network dependencies."""

    # Mock RPC responses
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "result": {
            "value": {
                "blockhash": "abc123",
                "lastValidBlockHeight": 100000
            }
        }
    })
    mock_post.return_value.__aenter__.return_value = mock_response

    logger.info("🚀 Testing Optimal Trade Sizing Pipeline Integration (Mocked)")

    # Create components
    trade_sizer = OptimalTradeSizer()

    # Create components
    trade_sizer = OptimalTradeSizer()

    # Test Case 1: Profitable arbitrage with optimal sizing
    logger.info("📊 Test Case 1: Profitable arbitrage scenario")

    # Create arbitrage path: SOL -> TOKEN -> SOL with price difference
    pool_a = PoolReserves(
        reserve_in=10000 * 1_000_000_000,  # 10000 SOL
        reserve_out=20000000 * 1_000_000   # 20M TOKEN
    )
    pool_b = PoolReserves(
        reserve_in=20000000 * 1_000_000,   # 20M TOKEN
        reserve_out=12000 * 1_000_000_000  # 12000 SOL (15% arbitrage)
    )

    arbitrage_path = ArbitragePath([pool_a, pool_b])

    # Find optimal trade size
    result = trade_sizer.find_optimal_trade_size(
        arbitrage_path=arbitrage_path,
        min_input_lamports=1_000_000_000,  # 1 SOL min
        max_input_lamports=None,  # Auto-calculate
        min_profit_threshold=50_000  # 0.00005 SOL min profit
    )

    if result:
        optimal_amount, max_profit = result
        logger.info(f"Optimal amount: {optimal_amount:.6f} lamports")
        logger.info(f"Max profit: {max_profit:.6f} lamports")
        # Verify the optimization worked
        calculator = ProfitCalculator()
        profit_at_optimal = calculator.calculate_expected_profit(optimal_amount, arbitrage_path)

        # Check that we're close to the reported maximum
        assert abs(profit_at_optimal - max_profit) < 10_000, "Optimization should be accurate"

        logger.info("✅ Test Case 1 passed")
    else:
        logger.error("❌ Test Case 1 failed - no optimal size found")
        return False

    # Test Case 2: Unprofitable scenario
    logger.info("📊 Test Case 2: Unprofitable scenario")

    # Balanced pools, no arbitrage opportunity
    pool_c = PoolReserves(
        reserve_in=1000 * 1_000_000_000,  # 1000 SOL
        reserve_out=2000000 * 1_000_000   # 2M TOKEN
    )
    pool_d = PoolReserves(
        reserve_in=2000000 * 1_000_000,   # 2M TOKEN
        reserve_out=1000 * 1_000_000_000  # 1000 SOL
    )

    unprofitable_path = ArbitragePath([pool_c, pool_d])

    result2 = trade_sizer.find_optimal_trade_size(unprofitable_path)

    if result2 is None:
        logger.info("✅ Test Case 2 passed - correctly identified unprofitable trade")
    else:
        logger.error("❌ Test Case 2 failed - should have rejected unprofitable trade")
        return False

    # Test Case 3: Performance benchmark
    logger.info("📊 Test Case 3: Performance benchmark")

    import time
    start_time = time.time()

    # Run optimization 100 times
    for i in range(100):
        trade_sizer.find_optimal_trade_size(arbitrage_path)

    end_time = time.time()
    avg_time = (end_time - start_time) / 100 * 1000  # milliseconds

    logger.info(f"Average optimization time: {avg_time:.2f} ms")
    assert avg_time < 10.0, f"Optimization too slow: {avg_time}ms per operation"

    logger.info("✅ Test Case 3 passed - performance acceptable")

    logger.info("🎉 All integration tests passed!")
    return True

if __name__ == "__main__":
    success = asyncio.run(test_pipeline_integration_with_mocked_rpc())
    if not success:
        sys.exit(1)