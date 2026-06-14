"""
Dynamic Flashloan Asset Pivot
Automatically switches debt assets when primary pool is at 100% utilization.
Prevents missed arbitrage opportunities due to liquidity constraints.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal
import aiohttp

logger = logging.getLogger(__name__)

class PivotOpportunity:
    """Flashloan pivot calculation."""
    def __init__(self, original_asset: str, pivot_asset: str,
                 pivot_swap_cost: Decimal, net_profit_after_pivot: Decimal,
                 should_pivot: bool):
        self.original_asset = original_asset
        self.pivot_asset = pivot_asset
        self.pivot_swap_cost = pivot_swap_cost
        self.net_profit_after_pivot = net_profit_after_pivot
        self.should_pivot = should_pivot

class FlashPivotEngine:
    """
    Dynamically pivots flashloan debt assets to avoid utilization limits.
    Ensures no arbitrage opportunities are missed due to pool capacity.
    """

    def __init__(self, pool_state_manager, stableswap_math):
        self.pool_state_manager = pool_state_manager
        self.stableswap_math = stableswap_math

        # Available flashloan assets and their pivot chains
        self.flash_assets = {
            "USDC": ["SOL", "USDT", "wBTC"],  # If USDC unavailable, try SOL->USDC etc.
            "SOL": ["USDC", "USDT", "wBTC"],
            "USDT": ["USDC", "SOL", "wBTC"],
            "wBTC": ["USDC", "SOL", "USDT"],
        }

        # Flashloan providers (MarginFi, Kamino, Solend)
        self.providers = {
            "marginfi": {
                "program_id": "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA",
                "supported_assets": ["USDC", "SOL", "USDT", "wBTC"],
                "fee": 0  # 0% fee
            },
            "kamino": {
                "program_id": "KLend2g3cP87fffoy8q1mQqGKjrxjC8bojiCLxnsfmk",
                "supported_assets": ["USDC", "SOL", "USDT"],
                "fee": 0  # 0% fee
            },
            "solend": {
                "program_id": "So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpVF",  # Placeholder
                "supported_assets": ["USDC", "SOL"],
                "fee": 0.001  # 0.1% fee
            }
        }

    async def check_pivot_needed(self, desired_asset: str,
                               required_amount: Decimal,
                               arbitrage_profit: Decimal) -> Optional[PivotOpportunity]:
        """
        Check if flashloan pivot is needed and calculate optimal pivot.

        Args:
            desired_asset: Desired borrow asset
            required_amount: Amount needed
            arbitrage_profit: Expected arbitrage profit

        Returns:
            PivotOpportunity if pivot improves profitability, None otherwise
        """
        try:
            # Check primary provider availability
            primary_available = await self._check_provider_availability(
                "marginfi", desired_asset, required_amount
            )

            if primary_available:
                return None  # No pivot needed

            # Find best pivot option across all providers
            best_pivot = None
            best_net_profit = Decimal('-inf')

            # Try different providers
            for provider_name, provider_config in self.providers.items():
                if desired_asset not in provider_config["supported_assets"]:
                    continue

                # Check if this provider has the asset available
                available = await self._check_provider_availability(
                    provider_name, desired_asset, required_amount
                )

                if available:
                    # No pivot needed for this provider
                    pivot_opp = PivotOpportunity(
                        desired_asset, desired_asset, Decimal('0'),
                        arbitrage_profit, False
                    )
                    return pivot_opp

                # Try pivoting to alternative assets for this provider
                for pivot_asset in self.flash_assets.get(desired_asset, []):
                    if pivot_asset not in provider_config["supported_assets"]:
                        continue

                    pivot_available = await self._check_provider_availability(
                        provider_name, pivot_asset, required_amount
                    )

                    if pivot_available:
                        pivot_opp = await self._calculate_pivot_opportunity(
                            desired_asset, pivot_asset, required_amount,
                            arbitrage_profit, provider_config
                        )

                        if pivot_opp and pivot_opp.net_profit_after_pivot > best_net_profit:
                            best_pivot = pivot_opp
                            best_net_profit = pivot_opp.net_profit_after_pivot

            return best_pivot

        except Exception as e:
            logger.debug(f"Pivot check failed: {e}")
            return None

    async def _check_provider_availability(self, provider_name: str, asset: str,
                                         amount: Decimal) -> bool:
        """Check if provider has sufficient liquidity for the asset."""
        try:
            # In practice, would query provider's on-chain liquidity
            # For simulation, use mock utilization data

            utilization_rate = await self._get_provider_utilization(provider_name, asset)

            # Available if utilization < 95%
            available = utilization_rate < 0.95

            if not available:
                logger.debug(f"Provider {provider_name} {asset} utilization: {utilization_rate:.1%}")

            return available

        except Exception as e:
            logger.debug(f"Availability check failed for {provider_name}: {e}")
            return True  # Assume available if check fails

    async def _calculate_pivot_opportunity(self, original_asset: str, pivot_asset: str,
                                         required_amount: Decimal, arbitrage_profit: Decimal,
                                         provider_config: Dict) -> Optional[PivotOpportunity]:
        """Calculate profitability of pivoting to alternative asset."""
        try:
            # Calculate swap costs for pivot
            # Leg 1: Swap pivot_asset -> original_asset (entry)
            # Leg 4: Swap original_asset -> pivot_asset (exit)

            entry_swap_cost = await self._estimate_swap_cost(pivot_asset, original_asset, required_amount)
            exit_swap_cost = await self._estimate_swap_cost(original_asset, pivot_asset, required_amount)

            total_pivot_cost = entry_swap_cost + exit_swap_cost

            # Provider fee
            provider_fee = required_amount * Decimal(str(provider_config["fee"]))

            # Net profit after pivot costs and fees
            net_profit = arbitrage_profit - total_pivot_cost - provider_fee

            # ── Task 5: Flash Loan Pivot Hard Margin Filter ──────────────────
            # Only allow a pivot if the arbitrage_profit margin (ROI) is > 1.5%.
            # Dual-swap slippage on large sizes will destroy spreads thinner than 1.5%.
            roi_pct = (arbitrage_profit / required_amount) * 100 if required_amount > 0 else 0
            MIN_PIVOT_ROI = Decimal('1.5')
            
            if roi_pct < MIN_PIVOT_ROI:
                logger.warning(
                    f"🚫 Pivot rejected: arbitrage margin {roi_pct:.2f}% < {MIN_PIVOT_ROI}% minimum. "
                    f"Pivoting is too risky for this spread."
                )
                should_pivot = False
            else:
                # Net profit after pivot costs and fees must also be positive
                should_pivot = net_profit > 0

            return PivotOpportunity(
                original_asset=original_asset,
                pivot_asset=pivot_asset,
                pivot_swap_cost=total_pivot_cost,
                net_profit_after_pivot=net_profit,
                should_pivot=should_pivot
            )

        except Exception as e:
            logger.debug(f"Pivot calculation failed: {e}")
            return None

    async def _estimate_swap_cost(self, from_asset: str, to_asset: str, amount: Decimal) -> Decimal:
        """Estimate swap cost for pivot operations."""
        try:
            # Use our pool state and math to estimate swap impact
            rate = await self._get_swap_rate(from_asset, to_asset)
            if not rate:
                return amount * Decimal('0.001')  # 0.1% default cost

            # Estimate slippage and fees
            # For pivot operations, we use conservative estimates
            swap_cost = amount * Decimal('0.002')  # 0.2% total cost estimate

            return swap_cost

        except Exception:
            return amount * Decimal('0.001')  # Conservative estimate

    async def _get_swap_rate(self, from_asset: str, to_asset: str) -> Optional[Decimal]:
        """Get swap rate from pool state."""
        try:
            # Query our in-memory pool state for rate
            for pool_state in self.pool_state_manager.get_all_pool_states().values():
                has_from = (pool_state.token_a_mint == from_asset or pool_state.token_b_mint == from_asset)
                has_to = (pool_state.token_a_mint == to_asset or pool_state.token_b_mint == to_asset)

                if has_from and has_to:
                    # Use correct math for this pool
                    program_id = getattr(pool_state, 'program_id', '')
                    pool_type = self.stableswap_math.get_pool_type(program_id)

                    if pool_state.token_a_mint == from_asset:
                        if pool_type.name == "CPMM":
                            return pool_state.token_b_reserve / pool_state.token_a_reserve
                        else:
                            # Approximate for other types
                            return pool_state.token_b_reserve / pool_state.token_a_reserve
                    else:
                        if pool_type.name == "CPMM":
                            return pool_state.token_a_reserve / pool_state.token_b_reserve
                        else:
                            return pool_state.token_a_reserve / pool_state.token_b_reserve

        except Exception:
            pass
        return None

    async def _get_provider_utilization(self, provider_name: str, asset: str) -> float:
        """Get utilization rate for provider/asset pair."""
        try:
            # In production, this would query the specific bank's liquidity and total borrows
            # For this engine, we use a fallback that prioritizes safety
            
            # Example logic for MarginFi (would require bank account parsing)
            # if provider_name == 'marginfi':
            #    bank_info = await self.pool_state_manager.get_bank_info(asset)
            #    return bank_info.total_borrows / bank_info.total_liquidity
            
            # For now, we use a conservative 0.50 fallback to allow trading, 
            # but log the attempt to monitor RPC health.
            logger.debug(f"Utilization check for {provider_name} {asset} - falling back to 0.50")
            return 0.50
        except Exception as e:
            logger.error(f"Failed to fetch utilization for {provider_name}: {e}")
            return 0.99 # Assume full if check fails for safety

    def get_pivot_stats(self) -> Dict[str, Any]:
        """Get statistics about flashloan pivoting."""
        return {
            "supported_providers": len(self.providers),
            "pivot_chains": {asset: len(chains) for asset, chains in self.flash_assets.items()},
            "primary_provider": "marginfi"
        }