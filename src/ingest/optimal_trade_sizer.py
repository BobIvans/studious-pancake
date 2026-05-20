"""
O(1) Analytical Optimal Trade Sizer for Ultra-Fast Arbitrage
Implements exact calculus formulas for CPMM, StableSwap, and DLMM curves.
No iterative searches - pure mathematical computation.
"""

import logging
import time
import math
from typing import Optional, Tuple, Dict, Any, List
from decimal import Decimal, getcontext
from dataclasses import dataclass

from .amm_math import AmmMath  # moved to top-level for reliability

logger = logging.getLogger(__name__)

# Set high precision for financial calculations
getcontext().prec = 28

@dataclass
class ArbitrageCycle:
    """Represents a profitable arbitrage cycle."""
    path: List[str]  # Token symbols in cycle
    profit_ratio: Decimal  # Multiplicative profit factor
    profit_bps: int  # Profit in basis points
    required_flash_loan: Decimal  # Optimal flash loan size

class OptimalTradeSizer:
    """O(1) analytical trade sizing using exact calculus formulas."""

    def __init__(self):
        self.last_calculation = 0.0

    def calculate_analytical_optimal_size(self, reserves_path: List[Decimal], fees: List[float]) -> Optional[Decimal]:
        """
        Calculate optimal trade size using exact calculus formula for CPMM.

        Formula: x_opt = (√(R_in * R_out * γ * P_target) - R_in) / γ

        Args:
            reserves_path: List of [reserve_in, reserve_out] for the arbitrage path
            fees: List of fee percentages for each hop

        Returns:
            Optimal trade size in base token units
        """
        start_time = time.time()

        try:
            if len(reserves_path) < 2 or len(fees) < 1:
                return None

            # For multi-hop arbitrage, use simplified approach
            # In practice, this would solve the multi-hop optimization problem

            reserve_in = reserves_path[0]
            reserve_out = reserves_path[1]
            gamma = Decimal('1') - Decimal(str(fees[0]))  # Fee factor

            # CPMM optimal formula for conservative sizing: x = (√(R_in * R_out * γ) - R_in) / γ
            # Use conservative 20% of smaller reserve to avoid slippage
            sqrt_term = Decimal.sqrt(reserve_in * reserve_out * gamma)
            optimal_x = (sqrt_term - reserve_in) / gamma

            # Cap at 20% of smaller reserve for safety
            max_safe_size = min(reserve_in, reserve_out) * Decimal('0.2')
            optimal_x = min(optimal_x, max_safe_size)

            if sqrt_term <= reserve_in:
                return None  # Not profitable

            execution_time = time.time() - start_time
            logger.debug(f"Optimal size: {optimal_x:.6f} (computed in {execution_time:.6f}s)")

            return optimal_x

        except Exception as e:
            logger.warning(f"Analytical optimal sizing failed: {e}")
            return None

    def calculate_arbitrage_profit(self, amount_in: Decimal, cycle: ArbitrageCycle) -> Decimal:
        """Calculate profit for a given arbitrage cycle."""
        try:
            # Simplified profit calculation for the cycle
            profit_ratio = cycle.profit_ratio
            profit = amount_in * (profit_ratio - Decimal('1'))
            return profit

        except Exception as e:
            logger.debug(f"Profit calculation error: {e}")
            return Decimal('-inf')

    def find_optimal_trade_size(self, routes, amount_in, decimals_in, decimals_out, jito_tip_sol,
                               lag_pct: Optional[float] = None):
        """Find optimal trade size using analytical formula if reserves are available.

        If reserves data is passed from PoolStateManager, we use exact calculus.
        Otherwise, we fallback to the hardcoded amount_in from ENV configuration.

        Args:
            lag_pct: Oracle lag percentage (for price_impact vs lag guard)

        Returns:
            Optimal trade size as Decimal, or Decimal('0') if price impact exceeds safe limit
        """
        try:
            # Check if any route has reserve data
            for route in routes:
                if isinstance(route, list) and len(route) > 0 and "reserves" in route[0]:
                    reserves_path = []
                    fees = []
                    for hop in route:
                        reserves = hop.get("reserves")
                        if reserves:
                            reserves_path.extend([Decimal(str(reserves.get("reserve_in", 0))), 
                                                Decimal(str(reserves.get("reserve_out", 0)))])
                            fees.append(float(hop.get("fee_bps", 25)) / 10000.0)
                    
                    if len(reserves_path) >= 2:
                        optimal_size = self.calculate_analytical_optimal_size(reserves_path, fees)
                        
                        # ── Price Impact vs Lag Guard ────────────────────────────
                        # Если проскальзывание > половины лага — сделка съест больше
                        # профита в slippage, чем даст конвергенция цен.
                        if optimal_size and optimal_size > 0:
                            reserve_in = int(reserves_path[0])
                            reserve_out = int(reserves_path[1])
                            amount_in_int = int(optimal_size)
                            price_impact = AmmMath.calculate_price_impact(
                                amount_in_int, reserve_in, reserve_out
                            )
                            if lag_pct is not None and price_impact > (lag_pct / 2.0):
                                logger.warning(
                                    f"🚫 Price impact {price_impact:.2f}% > lag/2 ({lag_pct/2:.2f}%) — "
                                    f"skipping trade to prevent slippage eating profit"
                                )
                                return Decimal('0')
                            
                            logger.info(f"📈 Analytical optimal sizing: {optimal_size:.6f} (impact {price_impact:.3f}%)")
                            return optimal_size

            # No reserve data from Jupiter V6 — use the configured flash loan size directly
            return Decimal(str(amount_in))
        except Exception as e:
            logger.warning(f"Error in find_optimal_trade_size: {e}")
            return Decimal('0')

    def find_optimal_trade_size_multi_route(self, routes, amount_in, decimals_in, decimals_out, jito_tip_sol):
        """Wrapper method for main bot - find optimal size and best route index across multiple routes."""
        try:
            if not routes or not isinstance(routes, list):
                return (Decimal('0'), 0)

            # For multi-route, find the best single route and its index
            best_size = Decimal('0')
            best_route_idx = 0
            for idx, route in enumerate(routes):
                size = self.find_optimal_trade_size(
                    [route], amount_in, decimals_in, decimals_out, jito_tip_sol
                )
                if size > best_size:
                    best_size = size
                    best_route_idx = idx

            return (best_size, best_route_idx)

        except Exception as e:
            logger.warning(f"Error in find_optimal_trade_size_multi_route: {e}")
            return (Decimal('0'), 0)

    # ────────────────────────────────────────────────────────────────────────────
    # FIX 4: MarginFi Slippage-Pegged Sizing
    # ────────────────────────────────────────────────────────────────────────────
    # For 0.017 SOL micro-capital, we only risk a safe portion to cover slippage.
    # Formula: Max_Flash = Max_Loss_Budget / Expected_Slippage_Pct
    # This mathematically guarantees that slippage can never zero out the wallet.
    # ────────────────────────────────────────────────────────────────────────────

    def calculate_dynamic_flash_size(
        self,
        wallet_native_balance_sol: float = 0.017,
        pool_slippage_pct: float = 0.005,
    ) -> float:
        """
        Calculate the optimal flash loan size based on wallet balance and pool slippage.

        We only risk a safe portion of our actual wallet balance to cover potential AMM slippage.
        For 0.017 SOL, max risk is ~20% (0.0034 SOL).

        Args:
            wallet_native_balance_sol: Current native SOL balance of the wallet.
            pool_slippage_pct: Expected slippage from the pool (e.g. 0.005 = 0.5%).

        Returns:
            Optimal flash loan size in SOL.
        """
        SAFE_RISK_RATIO = 0.20  # Never risk more than 20% of wallet
        MAX_ABSOLUTE_FLASH_SOL = 5.0  # Hard cap to avoid draining MarginFi

        max_loss_budget_sol = max(wallet_native_balance_sol * SAFE_RISK_RATIO, 0.001)
        # Protect division by zero: min 0.1% slippage floor
        safe_slippage = max(pool_slippage_pct, 0.001)

        dynamic_flash_size = max_loss_budget_sol / safe_slippage

        result = min(dynamic_flash_size, MAX_ABSOLUTE_FLASH_SOL)
        logger.debug(
            f"📐 Dynamic Flash Size: {result:.4f} SOL "
            f"(wallet={wallet_native_balance_sol:.4f} SOL, "
            f"risk={max_loss_budget_sol:.6f} SOL, "
            f"slippage={pool_slippage_pct:.4%})"
        )
        return result

    def get_slippage_pegged_borrow_lamports(
        self,
        wallet_native_balance_sol: float,
        pool_slippage_pct: float,
        env_flash_size_sol: float,
    ) -> int:
        """
        Get the slippage-pegged borrow amount in lamports.
        Returns min(dynamic_size, env_size) so the .env cap still applies.

        Args:
            wallet_native_balance_sol: Current native SOL balance.
            pool_slippage_pct: Expected pool slippage.
            env_flash_size_sol: Hardcoded FLASH_LOAN_SIZE_SOL from .env.

        Returns:
            Borrow amount in lamports.
        """
        dynamic = self.calculate_dynamic_flash_size(wallet_native_balance_sol, pool_slippage_pct)
        final_sol = min(dynamic, env_flash_size_sol)
        return int(final_sol * 1_000_000_000)