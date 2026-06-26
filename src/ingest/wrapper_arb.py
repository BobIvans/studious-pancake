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
                 optimal_flashloan_usdc: Decimal, expected_profit_usdc: Decimal,
                 amount_lamports: int = 0, expected_profit_lamports: int = 0):
        self.cheap_wrapper = cheap_wrapper
        self.expensive_wrapper = expensive_wrapper
        self.peg_deviation_pct = peg_deviation_pct
        self.pool_address = pool_address
        self.optimal_flashloan_usdc = optimal_flashloan_usdc
        self.expected_profit_usdc = expected_profit_usdc
        self.amount_lamports = amount_lamports
        self.expected_profit_lamports = expected_profit_lamports

class WrapperArbEnforcer:
    """
    Enforces 1:1 peg between wrapped assets (cbBTC/wBTC/tBTC).
    Fast-path scanner that bypasses Bellman-Ford for direct peg checks.
    Uses Jupiter three-hop circular quotes for rate discovery.
    """
    
    def __init__(self, tx_builder=None):
        self.tx_builder = tx_builder
        self.wrapper_pairs = [
            ("cbBTC", "wBTC"),
            ("wBTC", "tBTC"), 
            ("cbBTC", "tBTC"),
        ]
        self.peg_threshold_pct = 0.003
        self.opportunity_callbacks: List = []
        self.usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        
    def register_opportunity_callback(self, callback):
        """Register callback for peg opportunities."""
        self.opportunity_callbacks.append(callback)
        
    async def scan_wrapper_pegs(self):
        """Scan all wrapper pairs for peg deviations using Jupiter three-hop quotes."""
        opportunities = []
        
        for wrapper_a, wrapper_b in self.wrapper_pairs:
            opp = await self._check_wrapper_pair(wrapper_a, wrapper_b)
            if opp:
                opportunities.append(opp)
                
        # Execute best opportunity
        if opportunities:
            best_opp = max(opportunities, key=lambda x: x.expected_profit_lamports)
            for callback in self.opportunity_callbacks:
                try:
                    await callback(best_opp)
                except Exception as e:
                    logger.error(f"Wrapper callback error: {e}")
            
        return opportunities
        
    async def _check_wrapper_pair(self, wrapper_a: str, wrapper_b: str) -> Optional[WrapperPegOpportunity]:
        """Check if wrapper pair has peg deviation using Jupiter three-hop circular quote."""
        try:
            if not self.tx_builder:
                return None
                
            # Try both directions: USDC -> A -> B -> USDC and USDC -> B -> A -> USDC
            for first, second in [(wrapper_a, wrapper_b), (wrapper_b, wrapper_a)]:
                quote = await self.tx_builder.get_three_hop_circular_quote(
                    input_mint=self.usdc_mint,
                    middle_mint_1=first,
                    middle_mint_2=second,
                    amount_lamports=int(100_000_000_000),  # $100 USDC
                )
                
                if quote and quote.get("gross_profit_lamports", 0) > 0:
                    deviation_pct = abs(quote.get("effective_rate", 1.0) - 1.0)
                    
                    if deviation_pct > self.peg_threshold_pct:
                        if deviation_pct < 0.01:  # Sanity check: max 1% deviation
                            return WrapperPegOpportunity(
                                cheap_wrapper=first if quote.get("cheaper", first) == first else second,
                                expensive_wrapper=second if quote.get("cheaper", first) == first else first,
                                peg_deviation_pct=deviation_pct,
                                pool_address="",
                                optimal_flashloan_usdc=Decimal("1000"),
                                expected_profit_usdc=Decimal(str(quote["gross_profit_lamports"] / 1e6)),
                                expected_profit_lamports=quote["gross_profit_lamports"],
                                amount_lamports=int(quote.get("input_amount_lamports", 100_000_000_000)),
                            )
            
        except Exception as e:
            logger.debug(f"Wrapper pair check failed: {e}")
            
        return None
        
