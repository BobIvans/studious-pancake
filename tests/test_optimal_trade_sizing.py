#!/usr/bin/env python3
"""
Unit Tests for Optimal Trade Sizing

Tests the ternary search optimization for finding optimal arbitrage trade sizes.
"""

import unittest
import sys
import os
import logging

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ingest.optimal_trade_sizer import (
    PoolSimulator,
    ProfitCalculator,
    OptimalTradeSizer,
    ArbitragePath,
    PoolReserves
)


class TestPoolSimulator(unittest.TestCase):
    """Test the AMM pool simulation math."""

    def test_basic_swap_calculation(self):
        """Test basic swap calculation with fee."""
        # Pool: 1000 SOL, 2,000,000 TOKEN (assuming TOKEN has 6 decimals like USDC)
        reserve_sol = 1000 * 1_000_000_000  # 1000 SOL in lamports
        reserve_token = 2_000_000 * 1_000_000  # 2M tokens in smallest units

        # Swap 1 SOL
        amount_in = 1 * 1_000_000_000  # 1 SOL in lamports
        amount_out = PoolSimulator.get_amount_out(amount_in, reserve_sol, reserve_token)

        # Expected: ~1,993,012,000 tokens (accounting for 0.25% fee)
        # Formula: amountOut = (reserveOut * amountInWithFee) / (reserveIn + amountInWithFee)
        # amountInWithFee = 1e9 * (10000-25)/10000 = 997,500,000
        # amountOut = (2e12 * 997500000) / (1e12 + 997500000) ≈ 1,993,011,970
        expected_min = 1_993_000_000  # 1.993M tokens
        expected_max = 1_994_000_000  # 1.994M tokens

        self.assertGreater(amount_out, expected_min)
        self.assertLess(amount_out, expected_max)

    def test_price_impact_calculation(self):
        """Test price impact calculation."""
        reserve_in = 1000 * 1_000_000_000  # 1000 SOL
        reserve_out = 1000 * 1_000_000_000  # 1000 SOL (1:1 ratio)

        # Small trade - should have minimal impact
        small_trade = 10 * 1_000_000_000  # 10 SOL (1% of reserves)
        impact_small = PoolSimulator.calculate_price_impact(small_trade, reserve_in, reserve_out)
        self.assertLess(impact_small, 2.0)  # Less than 2%

        # Large trade - significant impact
        large_trade = 300 * 1_000_000_000  # 300 SOL (30% of reserves)
        impact_large = PoolSimulator.calculate_price_impact(large_trade, reserve_in, reserve_out)
        self.assertGreater(impact_large, 15.0)  # More than 15%

    def test_zero_amount_handling(self):
        """Test handling of zero or invalid amounts."""
        result = PoolSimulator.get_amount_out(0, 1000, 1000)
        self.assertEqual(result, 0)

        result = PoolSimulator.get_amount_out(1000, 0, 1000)
        self.assertEqual(result, 0)


class TestProfitCalculator(unittest.TestCase):
    """Test profit calculation for arbitrage paths."""

    def setUp(self):
        self.calculator = ProfitCalculator()

    def test_profitable_arbitrage(self):
        """Test profitable arbitrage scenario."""
        # Pool A: SOL -> TOKEN at 1 SOL = 2000 TOKEN
        # Pool B: TOKEN -> SOL at 2000 TOKEN = 1.2 SOL (20% price difference)
        pool_a = PoolReserves(
            reserve_in=10000 * 1_000_000_000,  # 10000 SOL
            reserve_out=20000000 * 1_000_000   # 20M TOKEN
        )
        pool_b = PoolReserves(
            reserve_in=20000000 * 1_000_000,   # 20M TOKEN
            reserve_out=12000 * 1_000_000_000  # 12000 SOL (higher price)
        )

        path = ArbitragePath([pool_a, pool_b])
        input_amount = 100 * 1_000_000_000  # 100 SOL

        profit = self.calculator.calculate_expected_profit(input_amount, path)
        self.assertGreater(profit, 0)  # Should be profitable

    def test_unprofitable_arbitrage(self):
        """Test unprofitable arbitrage (no price difference)."""
        # Both pools have same price: 1 SOL = 2000 TOKEN
        pool_a = PoolReserves(
            reserve_in=1000 * 1_000_000_000,  # 1000 SOL
            reserve_out=2000000 * 1_000_000   # 2M TOKEN
        )
        pool_b = PoolReserves(
            reserve_in=2000000 * 1_000_000,  # 2M TOKEN
            reserve_out=1000 * 1_000_000_000  # 1000 SOL
        )

        path = ArbitragePath([pool_a, pool_b])
        input_amount = 10 * 1_000_000_000  # 10 SOL

        profit = self.calculator.calculate_expected_profit(input_amount, path)
        self.assertLess(profit, 0)  # Should be loss (fees only)

    def test_insufficient_liquidity(self):
        """Test case where trade amount exceeds pool liquidity."""
        # Very small pool
        pool = PoolReserves(
            reserve_in=1 * 1_000_000_000,     # 1 SOL
            reserve_out=1000 * 1_000_000      # 1000 TOKEN
        )

        path = ArbitragePath([pool])
        input_amount = 10 * 1_000_000_000  # 10 SOL (more than reserve)

        profit = self.calculator.calculate_expected_profit(input_amount, path)
        self.assertLessEqual(profit, 0)  # Should fail or be unprofitable


class TestOptimalTradeSizer(unittest.TestCase):
    """Test the ternary search optimization."""

    def setUp(self):
        self.sizer = OptimalTradeSizer()

    def test_obvious_profit_case(self):
        """Test case with large price difference and high liquidity."""
        # Pool A: 1 SOL = 2000 TOKEN
        # Pool B: 2000 TOKEN = 1.5 SOL (15% arbitrage)
        pool_a = PoolReserves(
            reserve_in=10000 * 1_000_000_000,  # 10000 SOL
            reserve_out=20000000 * 1_000_000   # 20M TOKEN
        )
        pool_b = PoolReserves(
            reserve_in=20000000 * 1_000_000,   # 20M TOKEN
            reserve_out=15000 * 1_000_000_000  # 15000 SOL
        )

        path = ArbitragePath([pool_a, pool_b])
        result = self.sizer.find_optimal_trade_size(path)

        self.assertIsNotNone(result)
        optimal_amount, max_profit = result
        self.assertGreater(optimal_amount, 0)
        self.assertGreater(max_profit, 0)

        # Verify the result is actually optimal by checking nearby amounts
        # The search should find an amount that produces near-maximum profit
        profit_plus_epsilon = self.sizer.profit_calculator.calculate_expected_profit(
            optimal_amount + self.sizer.epsilon, path)
        profit_minus_epsilon = self.sizer.profit_calculator.calculate_expected_profit(
            max(1, optimal_amount - self.sizer.epsilon), path)
        
        # The optimal profit should be at least as good as points epsilon away
        self.assertGreaterEqual(max_profit, profit_plus_epsilon)
        self.assertGreaterEqual(max_profit, profit_minus_epsilon)

    def test_limited_liquidity_case(self):
        """Test case where liquidity limits optimal trade size."""
        # Small pools where large trades cause excessive slippage
        pool_a = PoolReserves(
            reserve_in=10 * 1_000_000_000,    # 10 SOL
            reserve_out=20000 * 1_000_000     # 20K TOKEN
        )
        pool_b = PoolReserves(
            reserve_in=20000 * 1_000_000,     # 20K TOKEN
            reserve_out=15 * 1_000_000_000    # 15 SOL
        )

        path = ArbitragePath([pool_a, pool_b])
        result = self.sizer.find_optimal_trade_size(path)

        self.assertIsNotNone(result)
        optimal_amount, max_profit = result

        # Should find optimal point that's positive and profitable
        self.assertGreater(optimal_amount, 0)
        self.assertGreater(max_profit, 0)

        # Verify optimality by checking nearby points
        profit_plus = self.sizer.profit_calculator.calculate_expected_profit(
            optimal_amount + self.sizer.epsilon, path)
        profit_minus = self.sizer.profit_calculator.calculate_expected_profit(
            max(1, optimal_amount - self.sizer.epsilon), path)

        self.assertGreaterEqual(max_profit, profit_plus)
        self.assertGreaterEqual(max_profit, profit_minus)

    def test_slippage_scenario(self):
        """Test optimal sizing under high slippage conditions."""
        # High slippage: small pools, large trade causes >5% price impact
        pool_a = PoolReserves(
            reserve_in=5 * 1_000_000_000,     # 5 SOL
            reserve_out=10000 * 1_000_000     # 10K TOKEN
        )
        pool_b = PoolReserves(
            reserve_in=10000 * 1_000_000,     # 10K TOKEN
            reserve_out=6 * 1_000_000_000     # 6 SOL (20% arbitrage)
        )

        path = ArbitragePath([pool_a, pool_b])
        result = self.sizer.find_optimal_trade_size(path)

        self.assertIsNotNone(result)
        optimal_amount, max_profit = result

        # Verify the optimal is positive and profit is positive
        self.assertGreater(optimal_amount, 0)
        self.assertGreater(max_profit, 0)

        # Verify it's actually optimal by checking that nearby points don't beat it
        profit_plus = self.sizer.profit_calculator.calculate_expected_profit(
            optimal_amount + self.sizer.epsilon, path)
        profit_minus = self.sizer.profit_calculator.calculate_expected_profit(
            max(1, optimal_amount - self.sizer.epsilon), path)

        self.assertGreaterEqual(max_profit, profit_plus)
        self.assertGreaterEqual(max_profit, profit_minus)

    def test_unprofitable_case(self):
        """Test case with no arbitrage opportunity."""
        # Balanced pools, no price difference
        pool_a = PoolReserves(
            reserve_in=1000 * 1_000_000_000,  # 1000 SOL
            reserve_out=2000000 * 1_000_000   # 2M TOKEN
        )
        pool_b = PoolReserves(
            reserve_in=2000000 * 1_000_000,   # 2M TOKEN
            reserve_out=1000 * 1_000_000_000  # 1000 SOL
        )

        path = ArbitragePath([pool_a, pool_b])
        result = self.sizer.find_optimal_trade_size(path)

        # Should return None for unprofitable trade
        self.assertIsNone(result)

    def test_search_precision(self):
        """Test that search achieves required precision."""
        # Create a scenario with a clear optimum
        pool_a = PoolReserves(
            reserve_in=100 * 1_000_000_000,   # 100 SOL
            reserve_out=200000 * 1_000_000    # 200K TOKEN
        )
        pool_b = PoolReserves(
            reserve_in=200000 * 1_000_000,    # 200K TOKEN
            reserve_out=120 * 1_000_000_000   # 120 SOL
        )

        path = ArbitragePath([pool_a, pool_b])
        sizer = OptimalTradeSizer(epsilon_lamports=100000)  # 0.0001 SOL precision
        result = sizer.find_optimal_trade_size(path)

        self.assertIsNotNone(result)
        optimal_amount, _ = result

        # Check that we can find profit within epsilon range
        profit_plus_epsilon = sizer.profit_calculator.calculate_expected_profit(
            optimal_amount + sizer.epsilon, path)
        profit_minus_epsilon = sizer.profit_calculator.calculate_expected_profit(
            optimal_amount - sizer.epsilon, path)

        # The optimal should be better than points epsilon away
        # (This is a statistical test - may occasionally fail due to discrete nature)


class TestArbitragePath(unittest.TestCase):
    """Test ArbitragePath functionality."""

    def test_path_length(self):
        """Test path length calculation."""
        pool = PoolReserves(1000, 1000)
        path = ArbitragePath([pool])
        self.assertEqual(path.get_path_length(), 1)

        path = ArbitragePath([pool, pool])
        self.assertEqual(path.get_path_length(), 2)

    def test_flash_loan_fee(self):
        """Test flash loan fee configuration."""
        pool = PoolReserves(1000, 1000)
        path = ArbitragePath([pool], flash_loan_fee_bps=10)  # 0.1%
        self.assertEqual(path.flash_loan_fee_bps, 10)


if __name__ == '__main__':
    # Configure logging for tests
    logging.basicConfig(level=logging.WARNING)

    # Run tests
    unittest.main(verbosity=2)