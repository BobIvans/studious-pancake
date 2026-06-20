"""
Wrapped Asset 1:1 Peg Enforcer
Fast-path arbitrage for BTC/ETH wrappers where 1 BTC = 1 BTC mathematically.
Zero oracle risk, pure deterministic edge.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from solders.pubkey import Pubkey

logger = logging.getLogger(__name__)

class WrapperPegOpportunity:
    """Detected wrapper peg deviation opportunity."""
    def __init__(self, cheap_wrapper: str, expensive_wrapper: str, 
                 peg_deviation_pct: float, pool_address: str,
                 optimal_flashloan_usdc: Decimal, expected_profit_usdc: Decimal):
        self.cheap_wrapper = cheap_wrapper
        self.expensive_wrapper = expensive_wrapper
        self.peg_deviation_pct = peg_deviation_pct
        self.pool_address = pool_address
        self.optimal_flashloan_usdc = optimal_flashloan_usdc
        self.expected_profit_usdc = expected_profit_usdc

class WrapperArbEnforcer:
    """
    Enforces 1:1 peg between wrapped assets (cbBTC/wBTC/tBTC).
    Fast-path scanner that bypasses Bellman-Ford for direct peg checks.
    """
    
    def __init__(self, pool_state_manager):
        self.pool_state_manager = pool_state_manager
        self.wrapper_pairs = [
            ("cbBTC", "wBTC"),
            ("wBTC", "tBTC"), 
            ("cbBTC", "tBTC"),
            ("wETH", "SOL")  # ETH wrapper vs native
        ]
        self.peg_threshold_pct = 0.003  # 0.3% deviation triggers (increased from 0.15% for higher conviction trades with 0.017 SOL capital)
        self.opportunity_callbacks: List = []
        
    def register_opportunity_callback(self, callback):
        """Register callback for peg opportunities."""
        self.opportunity_callbacks.append(callback)
        
    async def scan_wrapper_pegs(self):
        """Scan all wrapper pairs for peg deviations."""
        opportunities = []
        
        for wrapper_a, wrapper_b in self.wrapper_pairs:
            opp = await self._check_wrapper_pair(wrapper_a, wrapper_b)
            if opp:
                opportunities.append(opp)
                
        # Execute best opportunity
        if opportunities:
            best_opp = max(opportunities, key=lambda x: x.expected_profit_usdc)
            await self._execute_wrapper_arbitrage(best_opp)
            
        return opportunities
        
    async def _check_wrapper_pair(self, wrapper_a: str, wrapper_b: str) -> Optional[WrapperPegOpportunity]:
        """Check if wrapper pair has peg deviation."""
        try:
            # Get direct pool rates (bypass graph for speed)
            rate_a_to_b = await self._get_direct_pool_rate(wrapper_a, wrapper_b)
            rate_b_to_a = await self._get_direct_pool_rate(wrapper_b, wrapper_a)
            
            if not rate_a_to_b or not rate_b_to_a:
                return None
                
            # Calculate peg ratio (should be 1.0 for perfect peg)
            peg_ratio = rate_a_to_b
            
            # Check for significant deviation
            deviation_pct = abs(peg_ratio - Decimal('1.0')) / Decimal('1.0')
            
            if deviation_pct > self.peg_threshold_pct:
                # Determine which wrapper is cheaper
                if peg_ratio < Decimal('1.0'):
                    # wrapper_a is cheaper than wrapper_b
                    cheap_wrapper = wrapper_a
                    expensive_wrapper = wrapper_b
                else:
                    # wrapper_b is cheaper than wrapper_a  
                    cheap_wrapper = wrapper_b
                    expensive_wrapper = wrapper_a
                    
                # Calculate optimal arbitrage size using O(1) formula
                optimal_size, expected_profit = await self._calculate_peg_arbitrage_size(
                    cheap_wrapper, expensive_wrapper, deviation_pct
                )
                
                if optimal_size > 0:
                    pool_addr = await self._find_arbitrage_pool(cheap_wrapper, expensive_wrapper)
                    
                    return WrapperPegOpportunity(
                        cheap_wrapper=cheap_wrapper,
                        expensive_wrapper=expensive_wrapper,
                        peg_deviation_pct=float(deviation_pct),
                        pool_address=pool_addr or "",
                        optimal_flashloan_usdc=optimal_size,
                        expected_profit_usdc=expected_profit
                    )
                    
        except Exception as e:
            logger.debug(f"Wrapper pair check failed: {e}")
            
        return None
        
    async def _get_direct_pool_rate(self, from_token: str, to_token: str) -> Optional[Decimal]:
        """Get direct exchange rate from pool (fast-path)."""
        TOKEN_MINTS = {
            "cbBTC": "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij",
            "wBTC": "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh",
            "tBTC": "6DNSN2BJsaPFdFFc1zP37kkeNe4Usc1Sqkzr9C9vPWcU",
            "wETH": "7vfCXTUXx5WJV5J7pEeidpXYEPp9UUnQv9YpGP6tpX73",
            "SOL": "So11111111111111111111111111111111111111112"
        }
        from_mint = TOKEN_MINTS.get(from_token, from_token)
        to_mint = TOKEN_MINTS.get(to_token, to_token)

        try:
            # Query our in-memory pool state for direct rate
            # This bypasses the full graph for speed

            # Find pools containing both tokens
            candidate_pools = []
            for pool_addr, pool_state in self.pool_state_manager.get_all_pool_states().items():
                if (pool_state.token_a_mint == from_mint or pool_state.token_b_mint == from_mint) and \
                   (pool_state.token_a_mint == to_mint or pool_state.token_b_mint == to_mint):
                    candidate_pools.append(pool_state)

            if not candidate_pools:
                return None

            # Use largest liquidity pool
            best_pool = max(candidate_pools, key=lambda p: p.token_a_reserve + p.token_b_reserve)

            # Calculate rate
            if best_pool.token_a_mint == from_mint and best_pool.token_b_mint == to_mint:
                rate = best_pool.token_b_reserve / best_pool.token_a_reserve
            elif best_pool.token_a_mint == to_mint and best_pool.token_b_mint == from_mint:
                rate = best_pool.token_a_reserve / best_pool.token_b_reserve
            else:
                return None

            return rate

        except Exception:
            return None
            
    async def _calculate_peg_arbitrage_size(self, cheap_wrapper: str, expensive_wrapper: str, 
                                          deviation_pct: Decimal) -> Tuple[Decimal, Decimal]:
        """Calculate optimal arbitrage size for peg enforcement."""
        try:
            # For peg arbitrage: Flashloan USDC -> Buy cheap wrapper -> Swap to expensive -> Sell to USDC
            
            # Conservative sizing based on deviation
            base_size_usdc = Decimal('1000')  # Start with $1000
            
            # Scale by deviation (larger deviation = larger opportunity)
            scaling_factor = min(deviation_pct * Decimal('1000'), Decimal('10'))  # Cap at 10x
            optimal_size = base_size_usdc * scaling_factor
            
            # Estimate profit (simplified)
            profit_per_unit = deviation_pct * optimal_size * Decimal('0.5')  # Conservative estimate
            expected_profit = profit_per_unit
            
            return optimal_size, expected_profit
            
        except Exception:
            return Decimal('0'), Decimal('0')
            
    async def _find_arbitrage_pool(self, token_a: str, token_b: str) -> Optional[str]:
        """Find best pool for arbitrage execution."""
        try:
            # Find pool with both tokens and highest liquidity
            best_pool = None
            max_liquidity = 0
            
            for pool_addr, pool_state in self.pool_state_manager.get_all_pool_states().items():
                has_token_a = (pool_state.token_a_mint == token_a or 
                             pool_state.token_b_mint == token_a)
                has_token_b = (pool_state.token_a_mint == token_b or 
                              pool_state.token_b_mint == token_b)
                              
                if has_token_a and has_token_b:
                    liquidity = pool_state.token_a_reserve + pool_state.token_b_reserve
                    if liquidity > max_liquidity:
                        max_liquidity = liquidity
                        best_pool = pool_addr
                        
            return best_pool
            
        except Exception:
            return None
            
    async def _execute_wrapper_arbitrage(self, opportunity: WrapperPegOpportunity):
        """Execute wrapper peg arbitrage."""
        try:
            logger.info(f"🎯 Executing wrapper peg arbitrage: "
                       f"{opportunity.cheap_wrapper} -> {opportunity.expensive_wrapper} | "
                       f"Deviation: {opportunity.peg_deviation_pct:.2%} | "
                       f"Size: ${opportunity.optimal_flashloan_usdc} | "
                       f"Expected Profit: ${opportunity.expected_profit_usdc}")
            
            # Build transaction using K-Hop Stitcher
            # Flashloan USDC -> Buy cheap -> Swap to expensive -> Sell to USDC -> Repay
            
            # Implementation would use:
            # - Flashloan borrow USDC
            # - Swap USDC -> cheap_wrapper on Raydium
            # - Swap cheap_wrapper -> expensive_wrapper (if needed)
            # - Swap expensive_wrapper -> USDC on Raydium  
            # - Flashloan repay USDC
            # - Jito tip
            
            # For now, log the opportunity
            for callback in self.opportunity_callbacks:
                try:
                    await callback(opportunity)
                except Exception as e:
                    logger.error(f"Wrapper callback error: {e}")
                    
        except Exception as e:
            logger.error(f"Wrapper arbitrage execution failed: {e}")