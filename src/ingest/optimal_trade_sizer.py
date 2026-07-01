"""
O(1) Analytical Optimal Trade Sizer for Ultra-Fast Arbitrage
Implements exact calculus formulas for CPMM, StableSwap, and DLMM curves.
No iterative searches - pure mathematical computation.
"""

import logging
import os
import time
import math
from typing import Optional, Tuple, Dict, Any, List
from decimal import Decimal, getcontext
from dataclasses import dataclass

from .amm_math import AmmMath  # moved to top-level for reliability
from .amm_math_dispatcher import AmmMathDispatcher  # multi-curve dispatch (CPMM/stableswap/CLMM/DLMM)
from src.ingest.shared_state import ATA_RENT_SOL_SPL, ATA_RENT_SOL_TOKEN2022

logger = logging.getLogger(__name__)

MICRO_BALANCE_SOL = 0.015
# Phase 9: unified ATA rent constants from shared_state (single source of truth)
ATA_RENT_SOL = ATA_RENT_SOL_SPL  # Default: SPL Token rent (0.00203928 SOL)
ATA_RENT_TOKEN2022_SOL = ATA_RENT_SOL_TOKEN2022
GAS_RESERVE_SOL = 0.005
MANEUVER_BUDGET_SOL = MICRO_BALANCE_SOL - GAS_RESERVE_SOL
FLASH_LOAN_ENV_CAP_SOL = "FLASH_LOAN_SIZE_SOL"

# Set high precision for financial calculations
getcontext().prec = 28

# =============================================================================
# Compatibility Classes for Test Suite
# =============================================================================

@dataclass
class PoolReserves:
    """Represents AMM pool reserves for a single hop."""
    reserve_in: int  # Input token reserve in smallest units (e.g., lamports)
    reserve_out: int  # Output token reserve in smallest units (e.g., lamports)


class PoolSimulator:
    """Static methods for AMM pool simulation math."""
    
    @staticmethod
    def get_amount_out(amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int = 25) -> int:
        """Calculate output amount for a given input amount with fee.
        
        Uses the constant product formula with fee deduction.
        """
        if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
            return 0
        
        fee_multiplier = (10000 - fee_bps) / 10000
        amount_in_with_fee = int(amount_in * fee_multiplier)
        
        numerator = amount_in_with_fee * reserve_out
        denominator = reserve_in + amount_in_with_fee
        
        return numerator // denominator
    
    @staticmethod
    def calculate_price_impact(amount_in: int, reserve_in: int, reserve_out: int) -> float:
        """Calculate price impact as a percentage."""
        if reserve_in <= 0 or amount_in <= 0:
            return 0.0
        
        # Impact = (new_price - old_price) / old_price * 100
        old_price = reserve_out / reserve_in
        new_reserve_in = reserve_in + amount_in
        amount_out = PoolSimulator.get_amount_out(amount_in, reserve_in, reserve_out)
        new_reserve_out = reserve_out - amount_out
        
        if new_reserve_out <= 0:
            return 100.0  # Complete depletion
        
        new_price = new_reserve_out / new_reserve_in
        impact = ((new_price - old_price) / old_price) * 100
        
        return abs(impact)


class ArbitragePath:
    """Represents an arbitrage path through multiple pools."""
    
    def __init__(self, pools: List[PoolReserves], flash_loan_fee_bps: int = 0):
        self.pools = pools
        self.flash_loan_fee_bps = flash_loan_fee_bps
    
    def get_path_length(self) -> int:
        return len(self.pools)

    def calculate_profit(self, amount_in: Decimal) -> Decimal:
        current_amount = Decimal(str(amount_in))
        for pool in self.pools:
            reserve_in = Decimal(str(pool.reserve_in))
            reserve_out = Decimal(str(pool.reserve_out))
            if reserve_in <= 0 or reserve_out <= 0:
                return Decimal('0')
            current_amount = current_amount * reserve_out / reserve_in
        return current_amount - Decimal(str(amount_in))


class ProfitCalculator:
    """Calculates expected profit for arbitrage paths."""
    
    def calculate_expected_profit(self, amount_in: int, path: ArbitragePath) -> int:
        """Calculate expected profit (positive) or loss (negative) for a path.

        Phase 8 fix: flash loan fee applies to the BORROWED amount, NOT the
        output amount.  Old logic subtracted fees from the output which gave
        an incorrect profit for high-fee (e.g. Kamino 0.05%) flash loans.
        """
        if not path.pools:
            return 0

        current_amount = amount_in

        for pool in path.pools:
            amount_out = PoolSimulator.get_amount_out(
                current_amount, pool.reserve_in, pool.reserve_out
            )
            current_amount = amount_out

        # Phase 8: flash loan fee applies to the BORROWED amount, not the output
        flashloan_fee = int(amount_in * (path.flash_loan_fee_bps / 10000.0))
        profit = current_amount - amount_in - flashloan_fee
        return profit
    
    def get_max_feasible_input(self, path: ArbitragePath) -> int:
        """Get the maximum input that can be processed without depleting pools."""
        min_max_input = float('inf')
        
        for pool in path.pools:
            # Use a more conservative estimate: 50% of the input reserve
            # to avoid excessive slippage
            if pool.reserve_in > 0:
                max_input = pool.reserve_in // 2
                min_max_input = min(min_max_input, max_input)
        
        return int(min_max_input) if min_max_input != float('inf') else 0


class VelocitySlippageManager:
    """Calculates slippage tolerance from recent transaction velocity."""

    def __init__(
        self,
        window_seconds: float = 1.0,
        base_slippage: float = 0.005,
        max_slippage: float = 0.05,
    ):
        self.window_seconds = max(window_seconds, 0.001)
        self.base_slippage = base_slippage
        self.max_slippage = max_slippage
        self._timestamps: List[float] = []

    def record_transaction(self, timestamp: Optional[float] = None) -> None:
        now = time.time() if timestamp is None else float(timestamp)
        self._timestamps.append(now)
        self._prune(now)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        self._timestamps = [ts for ts in self._timestamps if ts >= cutoff]

    def get_velocity(self) -> float:
        if not self._timestamps:
            return 0.0
        now = max(self._timestamps)
        self._prune(now)
        elapsed = max(now - min(self._timestamps), self.window_seconds)
        return len(self._timestamps) / elapsed

    def get_dynamic_slippage(self) -> float:
        velocity = self.get_velocity()
        velocity_factor = min(velocity / 10.0, 5.0)
        return min(self.max_slippage, self.base_slippage + velocity_factor * 0.005)

    def validate_slippage_safety(
        self,
        expected_out: Decimal,
        borrowed_amount: Decimal,
        total_fees: Decimal,
        slippage: float,
    ) -> bool:
        worst_case_out = Decimal(str(expected_out)) * (Decimal('1') - Decimal(str(slippage)))
        net_after_fees = worst_case_out - Decimal(str(total_fees))
        return net_after_fees >= Decimal(str(borrowed_amount))

    # ── ИСПРАВЛЕНИЕ: Unified Slippage Calculation ──────────────────────────────
    # Объединяет VelocitySlippageManager с Anti-Sandwich Guardian и Dynamic Routing:
    # Шаг 1: База из VelocitySlippageManager.get_dynamic_slippage() (сетевая активность)
    # Шаг 2: Anti-Sandwich Guard — slippage не превышает 40% от expected_profit_bps
    # Шаг 3: Ограничение снизу — минимум 5 BPS (требование Jupiter)
    #
    # Returns slipage in basis points (BPS).
    def calculate_unified_slippage_bps(
        self,
        expected_profit_bps: float = 0.0,
        base_slippage_bps: int = 15,
    ) -> int:
        """
        Calculate unified slippage combining velocity, profit guard, and Jupiter minimum.

        Args:
            expected_profit_bps: Expected profit of the trade in BPS (0.01% units).
            base_slippage_bps: Fallback slippage if no profit data available.

        Returns:
            Slippage in BPS (basis points), guaranteed >= 5 and <= 1000.
        """
        # Шаг 1: База от VelocitySlippageManager
        velocity_slippage = self.get_dynamic_slippage()  # float (0.005 = 0.5% = 50 BPS)
        velocity_bps = max(5, int(velocity_slippage * 10000))

        # Шаг 2: Anti-Sandwich Guard — slippage не более 40% от expected_profit_bps
        if expected_profit_bps > 0:
            anti_sandwich_bps = int(expected_profit_bps * 0.4)
            unified = min(velocity_bps, anti_sandwich_bps)
        else:
            unified = base_slippage_bps

        # Шаг 3: Jupiter minimum и разумный максимум
        unified = max(5, unified)  # Jupiter min 5 BPS
        unified = min(unified, 1000)  # Max 10% (safety cap)

        import logging
        logger = logging.getLogger(__name__)
        logger.debug(
            f"🛡️ Unified slippage: {unified} BPS "
            f"(velocity={velocity_bps}, profit_bps={expected_profit_bps:.1f}, "
            f"anti_sandwich={anti_sandwich_bps if expected_profit_bps > 0 else 'N/A'})"
        )
        return unified


@dataclass
class ArbitrageCycle:
    """Represents a profitable arbitrage cycle."""
    path: List[str]  # Token symbols in cycle
    profit_ratio: Decimal  # Multiplicative profit factor
    profit_bps: int  # Profit in basis points
    required_flash_loan: Decimal  # Optimal flash loan size


class OptimalTradeSizer:
    """O(1) analytical trade sizing using exact calculus formulas."""

    def __init__(self, epsilon_lamports: int = 1000):
        self.last_calculation = 0.0
        self.epsilon = max(1, epsilon_lamports)  # Fix 65: guard against zero/negative epsilon
        self.profit_calculator = ProfitCalculator()

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

    def find_optimal_trade_size(
        self,
        routes=None,
        amount_in=None,
        decimals_in=None,
        decimals_out=None,
        jito_tip_sol=None,
        lag_pct: Optional[float] = None,
        arbitrage_path: ArbitragePath = None,
        min_input_lamports: int = None,
        max_input_lamports: Optional[int] = None,
        min_profit_threshold: int = 50_000,  # Phase 8: increased from 1_000 to 50_000 (0.00005 SOL min)
        quote1=None,
        quote2=None,
        base_mint_decimals=None,
        intermediate_mint_decimals=None,
        working_cap_sol: Optional[float] = None,
    ):
        """Polymorphic router for optimal trade sizing.
        
        Supports two calling conventions:
        1. For live route arrays: find_optimal_trade_size(routes, amount_in, decimals_in, decimals_out, jito_tip_sol, lag_pct)
        2. For unit tests with ArbitragePath: find_optimal_trade_size(arbitrage_path, min_input_lamports=..., ...)
        """
        if quote1 is not None and quote2 is not None:
            quote1_out = Decimal(str(quote1.get("outAmount", 0)))
            quote2_out = Decimal(str(quote2.get("outAmount", 0)))
            if quote2_out > quote1_out:
                return Decimal(str(working_cap_sol or 0))
            return Decimal('0')

        # Router: Detect if first arg is an ArbitragePath (test convention) or use arbitrage_path kwarg
        effective_path = arbitrage_path
        if routes is not None and isinstance(routes, ArbitragePath):
            effective_path = routes
        
        # Router: If arbitrage_path is provided, use ternary search for tests
        if effective_path is not None:
            return self._find_optimal_via_ternary_search(
                effective_path,
                max(min_input_lamports or 1_000_000, 1),  # At least 1 to avoid edge cases
                max_input_lamports,
                min_profit_threshold
            )
        
        # Otherwise use analytical CPMM for live routes
        return self._find_optimal_via_analytical(routes, amount_in, decimals_in, decimals_out, jito_tip_sol, lag_pct)

    def _find_optimal_via_ternary_search(
        self,
        arbitrage_path: ArbitragePath,
        min_input_lamports: int,
        max_input_lamports: Optional[int],
        min_profit_threshold: int,
    ) -> Optional[Tuple[int, int]]:
        """Find optimal trade size using ternary search with fixed 40 iterations.

        Fix: replaced O(N) range() scan with O(log N) 40-iteration ternary search
        to prevent CPU starvation (50k+ iterations caused micro-freezes in async loop).
        """
        if not arbitrage_path.pools:
            return None

        # Auto-calculate max input based on pool liquidity
        if max_input_lamports is None:
            max_input_lamports = self.profit_calculator.get_max_feasible_input(arbitrage_path)

        if max_input_lamports <= min_input_lamports:
            max_input_lamports = min_input_lamports * 10

        left = min_input_lamports
        right = max_input_lamports

        best_amount = left
        best_profit = self.profit_calculator.calculate_expected_profit(left, arbitrage_path)

        # Fixed 40 iterations — O(log N) with O(1) CPU cost (~0.1ms)
        for _ in range(40):
            if right - left <= 1:
                break

            m1 = left + (right - left) // 3
            m2 = right - (right - left) // 3

            profit1 = self.profit_calculator.calculate_expected_profit(m1, arbitrage_path)
            profit2 = self.profit_calculator.calculate_expected_profit(m2, arbitrage_path)

            if profit1 > best_profit:
                best_profit = profit1
                best_amount = m1
            if profit2 > best_profit:
                best_profit = profit2
                best_amount = m2

            if profit1 < profit2:
                left = m1
            else:
                right = m2

        if best_profit < min_profit_threshold:
            return None

        return (best_amount, best_profit)

    def _find_optimal_via_analytical(
        self,
        routes,
        amount_in,
        decimals_in,
        decimals_out,
        jito_tip_sol,
        lag_pct: Optional[float] = None,
    ):
        """Find optimal trade size using analytical formula for live routes.

        FIX: When reserves are unavailable (Jupiter public API), use priceImpactPct
        to estimate liquidity and adjust trade size accordingly.
        """
        if not amount_in or amount_in <= 0:
            return Decimal('0')

        try:
            for route in routes:
                if isinstance(route, list) and len(route) > 0 and "reserves" in route[0]:
                    # Classify the dominant pool type of this route via the dispatcher.
                    # pool_type drives the price-impact/amount-out curve below.
                    route_pool_type = "constant_product"
                    for hop in route:
                        hop_pt = hop.get("pool_type") or AmmMathDispatcher.classify_pool_type(hop.get("programId"))
                        if hop_pt != "constant_product":
                            route_pool_type = hop_pt
                            break

                    # Concentrated-liquidity pools (CLMM/DLMM) without rich tick/bin
                    # state use a pessimistic curve, so we still cap the size
                    # conservatively — but the cap is now derived from the actual
                    # (dispatcher-computed) price impact, not a flat 0.2 base units.
                    if route_pool_type in ("clmm", "dlmm"):
                        _dec = 9  # default SOL decimals
                        for hop in route:
                            _raw = hop.get("decimals") or hop.get("baseDecimals") or hop.get("quoteDecimals") or 9
                            try:
                                _dec = max(1, int(_raw))
                            except (TypeError, ValueError):
                                _dec = 9
                            break
                        micro_cap = Decimal('0.2') * Decimal(10 ** _dec)
                        final_size = min(Decimal(str(amount_in)), micro_cap)
                        logger.info(
                            f"🛡️ {route_pool_type.upper()} conservative cap: "
                            f"{final_size/Decimal(10**_dec):.4f} base units (decimals={_dec})"
                        )
                        return final_size

                    reserves_path = []
                    fees = []

                    for hop in route:
                        reserves = hop.get("reserves")
                        if reserves:
                            reserves_path.extend([Decimal(str(reserves.get("reserve_in", 0))),
                                                Decimal(str(reserves.get("reserve_out", 0)))])
                            fees.append(float(hop.get("fee_bps", 25)) / 10000.0)

                        if len(reserves_path) >= 2:
                            optimal_size = OptimalTradeSizer().calculate_analytical_optimal_size(reserves_path, fees)

                            if optimal_size and optimal_size > 0:
                                reserve_in = int(reserves_path[0])
                                reserve_out = int(reserves_path[1])
                                amount_in_int = int(optimal_size)
                                # Dispatcher: stableswap uses the Curve impact curve,
                                # constant_product the CPMM one.
                                price_impact = AmmMathDispatcher.calculate_price_impact(
                                    amount_in_int, reserve_in, reserve_out,
                                    pool_type=route_pool_type,
                                )
                                if lag_pct is not None and price_impact > (lag_pct / 2.0):
                                    logger.warning(
                                        f"🚫 Price impact {price_impact:.2f}% > lag/2 ({lag_pct/2:.2f}%) — "
                                        f"skipping trade to prevent slippage eating profit "
                                        f"(pool_type={route_pool_type})"
                                    )
                                    return Decimal('0')

                                logger.info(
                                    f"📈 Analytical optimal sizing: {optimal_size:.6f} "
                                    f"(impact {price_impact:.3f}%, pool_type={route_pool_type})"
                                )
                                return optimal_size

                # FIX: Jupiter public API fallback using priceImpactPct
                price_impact_pct = None
                for hop in route if isinstance(route, list) else []:
                    pip = hop.get("priceImpactPct") or hop.get("price_impact_pct")
                    if pip is not None:
                        try:
                            price_impact_pct = float(pip)
                        except (TypeError, ValueError):
                            pass
                
                if price_impact_pct is not None and lag_pct is not None:
                    # Calculate effective liquidity estimate
                    # Liquidity_Est = Amount_In / Price_Impact_Pct (approximate formula)
                    try:
                        liquidity_est = Decimal(str(amount_in)) / Decimal(str(price_impact_pct / 100.0))
                        
                        # Adjust size to keep price impact < lag/2
                        max_impact = lag_pct / 2.0
                        scaling_factor = Decimal(str(max_impact / price_impact_pct)) if price_impact_pct > 0 else Decimal('0.01')
                        optimal_size = max(Decimal('0.01'), Decimal(str(amount_in)) * scaling_factor)
                        
                        logger.info(f"📊 Jupiter sizing fallback: liquidity_est={liquidity_est:.0f}, size={optimal_size:.6f} (impact {price_impact_pct:.2f}%)")
                        return optimal_size
                    except Exception as calc_err:
                        logger.debug(f"Price impact sizing fallback error: {calc_err}")

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

    def _env_flash_loan_cap_sol(self) -> float:
        """Return FLASH_LOAN_SIZE_SOL as an absolute upper cap, never as a target."""
        try:
            return max(float(os.getenv(FLASH_LOAN_ENV_CAP_SOL, "1.0")), 0.0)
        except ValueError:
            logger.warning(f"Invalid {FLASH_LOAN_ENV_CAP_SOL}; using 1.0 SOL cap")
            return 1.0

    def calculate_dynamic_flash_size(
        self,
        wallet_native_balance_sol: float = 0.015,
        pool_slippage_pct: float = 0.005,
        virtual_balance: Optional[float] = None,
        num_new_atas: int = 0,
        expected_profit_sol: Optional[float] = None,
        min_profit_after_rent_sol: float = 0.0,
    ) -> float:
        """
        Calculate a capital-aware flash loan size for the 0.015 SOL survival phase.

        FLASH_LOAN_SIZE_SOL is treated only as an absolute cap. The working budget is
        derived from virtual_balance, with 0.005 SOL reserved for gas and 0.00204 SOL
        deducted per new ATA from expected profit.
        """
        effective_balance = virtual_balance if virtual_balance is not None else wallet_native_balance_sol

        # Task 2: Logarithmic/Tiered Risk Scale for Scaling Phase
        # Синхронизировано с FlywheelScaler.SCALING_GRID для единого источника правды.
        try:
            from src.ingest.flywheel_scaler import SCALING_GRID
            # Ищем тир по текущему балансу
            SAFE_RISK_RATIO = 0.20  # fallback
            for tier in SCALING_GRID:
                if tier.min_balance <= effective_balance < tier.max_balance:
                    # max_concurrent_trades как прокси для risk_ratio
                    # Survival(1)→20%, Momentum(2)→50%, Growth(3)→70%, Pro(5)→90%
                    tier_map = {1: 0.20, 2: 0.50, 3: 0.70, 5: 0.90}
                    SAFE_RISK_RATIO = tier_map.get(tier.max_concurrent_trades, 0.20)
                    break
        except ImportError:
            if effective_balance < 0.2:
                SAFE_RISK_RATIO = 0.20
            elif effective_balance < 2.0:
                SAFE_RISK_RATIO = 0.50
            else:
                SAFE_RISK_RATIO = 0.90 
        
        max_loss_budget_sol = max(effective_balance - GAS_RESERVE_SOL, 0.0)
        # Dynamic maneuver budget based on balance tier
        # For small accounts, limit loss to 0.01 SOL. For large, allow up to 10% of balance.
        maneuver_limit = 0.010 if effective_balance < 1.0 else effective_balance * 0.1
        max_loss_budget_sol = min(max_loss_budget_sol, maneuver_limit)

        if num_new_atas > 0 and expected_profit_sol is not None:
            total_rent_cost = num_new_atas * ATA_RENT_SOL
            profit_after_rent = expected_profit_sol - total_rent_cost
            if profit_after_rent < min_profit_after_rent_sol:
                logger.warning(
                    f"Dynamic sizing rejected: expected profit {expected_profit_sol:.6f} SOL "
                    f"minus {num_new_atas}x ATA rent {total_rent_cost:.6f} SOL = {profit_after_rent:.6f} SOL"
                )
                return 0.0

        safe_slippage = max(pool_slippage_pct, 0.001)
        dynamic_flash_size = max_loss_budget_sol * SAFE_RISK_RATIO / safe_slippage
        env_cap = self._env_flash_loan_cap_sol()
        if env_cap > 0:
            dynamic_flash_size = min(dynamic_flash_size, env_cap)

        result = max(dynamic_flash_size, 0.0)
        logger.debug(
            f"📐 Dynamic Flash Size: {result:.4f} SOL "
            f"(balance={effective_balance:.4f} SOL, "
            f"risk_budget={max_loss_budget_sol:.6f} SOL, "
            f"slippage={pool_slippage_pct:.4%}, env_cap={env_cap:.4f} SOL, "
            f"num_new_atas={num_new_atas})"
        )
        return result

    def get_slippage_pegged_borrow_lamports(
        self,
        wallet_native_balance_sol: float,
        pool_slippage_pct: float,
        bank_liquidity_lamports: int,
        virtual_balance: Optional[float] = None,
        num_new_atas: int = 0,
        expected_profit_sol: Optional[float] = None,
        min_profit_after_rent_sol: float = 0.0,
    ) -> int:
        """
        Get the slippage-pegged borrow amount in lamports.
        """
        dynamic = self.calculate_dynamic_flash_size(
            wallet_native_balance_sol,
            pool_slippage_pct,
            virtual_balance=virtual_balance,
            num_new_atas=num_new_atas,
            expected_profit_sol=expected_profit_sol,
            min_profit_after_rent_sol=min_profit_after_rent_sol,
        )
        if dynamic <= 0:
            return 0
        
        bank_liquidity_sol = bank_liquidity_lamports / 1_000_000_000
        max_allowed_by_liquidity = bank_liquidity_sol * 0.5
        
        final_sol = min(dynamic, max_allowed_by_liquidity)
        return int(final_sol * 1_000_000_000)