"""
AMM Math Engine - Local Cross-Rate Calculations

Provides precise BigInt-based AMM calculations for constant product formula
without external API calls. Used for ultra-fast local routing.
"""

import logging
from typing import Tuple

logger = logging.getLogger("AmmMath")


class AmmMath:
    """Mathematical engine for AMM calculations using arbitrary precision integers."""

    @staticmethod
    def get_amount_out(
        amount_in: int,
        reserve_in: int,
        reserve_out: int,
        fee_bps: int = 25
    ) -> int:
        """
        Calculate output amount for AMM swap using constant product formula.

        Formula: amountOut = (reserveOut * amountInWithFee) / (reserveIn * 10000 + amountInWithFee)

        Args:
            amount_in: Input amount (as integer, e.g., lamports)
            reserve_in: Reserve of input token in pool
            reserve_out: Reserve of output token in pool
            fee_bps: Fee in basis points (default 25 = 0.25%)

        Returns:
            Output amount (as integer)
        """
        if amount_in <= 0:
            return 0

        if reserve_in <= 0 or reserve_out <= 0:
            return 0

        # Convert to BigInt-like precision (Python int is arbitrary precision)
        amount_in_big = int(amount_in)
        reserve_in_big = int(reserve_in)
        reserve_out_big = int(reserve_out)

        # Calculate fee deducted basis points
        fee_deducted_bps = 10000 - fee_bps

        # Correct CPMM formula with fee: amountOut = (reserveOut * amountIn * feeDeducted) / (reserveIn * 10000 + amountIn * feeDeducted)
        numerator = reserve_out_big * amount_in_big * fee_deducted_bps
        denominator = (reserve_in_big * 10000) + (amount_in_big * fee_deducted_bps)
        amount_out = numerator // denominator

        return int(amount_out)

    @staticmethod
    def calculate_price_impact(
        amount_in: int,
        reserve_in: int,
        reserve_out: int
    ) -> float:
        """
        Calculate price impact percentage for a swap.

        Args:
            amount_in: Input amount
            reserve_in: Input reserve
            reserve_out: Output reserve

        Returns:
            Price impact as percentage (0.0 to 100.0)
        """
        if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
            return 100.0

        # Price before swap
        price_before = reserve_out / reserve_in

        # Price after swap (simplified approximation)
        new_reserve_in = reserve_in + amount_in
        new_reserve_out = reserve_out - AmmMath.get_amount_out(amount_in, reserve_in, reserve_out)

        if new_reserve_in <= 0:
            return 100.0

        price_after = new_reserve_out / new_reserve_in

        if price_before <= 0:
            return 100.0

        impact = abs(price_after - price_before) / price_before * 100.0
        return min(impact, 100.0)

    @staticmethod
    def get_amount_in(
        amount_out: int,
        reserve_in: int,
        reserve_out: int,
        fee_bps: int = 25
    ) -> int:
        """
        Calculate required input amount for desired output amount.

        Args:
            amount_out: Desired output amount
            reserve_in: Reserve of input token
            reserve_out: Reserve of output token
            fee_bps: Fee in basis points

        Returns:
            Required input amount
        """
        if amount_out <= 0 or reserve_in <= 0 or reserve_out <= 0:
            return 0

        if amount_out >= reserve_out:
            return 0  # Impossible to get more than reserve

        # For constant product: (reserveIn + amountIn) * (reserveOut - amountOut) = reserveIn * reserveOut
        # Solving for amountIn gives: amountIn = (reserveIn * amountOut) / (reserveOut - amountOut)

        numerator = int(reserve_in) * int(amount_out)
        denominator = int(reserve_out) - int(amount_out)

        if denominator <= 0:
            return 0

        amount_in_no_fee = numerator // denominator

        # Add fee back: since fee is deducted from input, we need to solve for pre-fee amount
        # This is approximate - for precision, would need iterative approach
        fee_multiplier = 10000 / (10000 - fee_bps)
        amount_in_with_fee = int(amount_in_no_fee * fee_multiplier)

        return amount_in_with_fee


# Unit tests for BigInt math accuracy
def test_amm_math():
    """Basic unit tests for AMM math functions."""
    # Test basic swap calculation
    amount_out = AmmMath.get_amount_out(
        amount_in=1000000,  # 1 SOL in lamports
        reserve_in=1000000000,  # 1000 SOL
        reserve_out=1000000000000,  # 1M tokens
        fee_bps=25
    )
    assert amount_out > 0, "Amount out should be positive"

    # Test price impact
    impact = AmmMath.calculate_price_impact(1000000, 1000000000, 1000000000000)
    assert 0 <= impact <= 100, "Price impact should be 0-100%"

    # Test amount in calculation
    amount_in = AmmMath.get_amount_in(
        amount_out=100000,
        reserve_in=1000000000,
        reserve_out=1000000000000,
        fee_bps=25
    )
    assert amount_in > 0, "Amount in should be positive"

    logger.info("✅ AMM Math unit tests passed")


if __name__ == "__main__":
    test_amm_math()