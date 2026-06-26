"""
Local Router - Micro-Graph Arbitrage Routing

Provides ultra-fast local routing through predefined micro-graphs without external API calls.
Supports Jupiter fallback for complex routes and integrates with pool state management.
"""

import asyncio
import os
import logging
from typing import Dict, List, Optional, Tuple, Any
import aiohttp

from .amm_math import AmmMath
from .pool_state_manager import PoolStateManager, PoolReserve

logger = logging.getLogger("LocalRouter")


class ArbitrageRoute:
    """Represents an arbitrage route with calculated profit."""

    def __init__(self, path: List[Dict], total_amount_in: int, total_amount_out: int, profit_sol: float):
        self.path = path  # List of hop dicts with pool_address, input/output tokens, amounts
        self.total_amount_in = total_amount_in
        self.total_amount_out = total_amount_out
        self.profit_sol = profit_sol

    def is_profitable(self, min_profit_sol: float = 0.001) -> bool:
        """Check if route is profitable after fees."""
        return self.profit_sol >= min_profit_sol

    def get_transaction_size_estimate(self) -> int:
        """Estimate transaction size in bytes for this route."""
        # Rough estimate: base transaction + instructions per hop
        base_size = 300  # Base transaction overhead
        per_hop_size = 100  # Per swap instruction
        return base_size + (len(self.path) * per_hop_size)

    def exceeds_size_limit(self, max_size_bytes: int = 1232) -> bool:
        """Check if route would exceed Solana transaction size limit."""
        return self.get_transaction_size_estimate() > max_size_bytes


class LocalRouter:
    """Micro-graph router for local arbitrage calculations."""

    # Predefined micro-graph paths (MAX 3 hops for Solana transaction size limit of 1232 bytes)
    MICRO_GRAPH_PATHS = [
        # Path A: SOL -> TOKEN -> SOL (2 hops - 832 bytes estimated)
        [
            {"input_token": "SOL", "output_token": "TOKEN", "hop_type": "swap"},
            {"input_token": "TOKEN", "output_token": "SOL", "hop_type": "swap"}
        ],
        # Path B: SOL -> USDC -> TOKEN -> SOL (3 hops - 1032 bytes estimated)
        [
            {"input_token": "SOL", "output_token": "USDC", "hop_type": "swap"},
            {"input_token": "USDC", "output_token": "TOKEN", "hop_type": "swap"},
            {"input_token": "TOKEN", "output_token": "SOL", "hop_type": "swap"}
        ]
        # Note: Removed Path C to stay under 3-hop limit
        # Path C would be 4 hops total which exceeds Solana's 1232 byte limit
    ]

    # Maximum hops allowed (Solana transaction size limit)
    MAX_HOPS = 3

    # Flash loan fee (0.05%)
    FLASH_LOAN_FEE_BPS = 5

    def __init__(
        self,
        pool_state_manager: PoolStateManager,
        jupiter_api_url: str = os.getenv("JUPITER_QUOTE_API", "https://api.jup.ag/swap/v1/quote"),
        session: Optional[aiohttp.ClientSession] = None
    ):
        self.pool_state_manager = pool_state_manager
        self.jupiter_api_url = jupiter_api_url
        self.session = session
        self._session_owned = session is None

        # Address Lookup Table cache (5 minute TTL)
        self.lut_cache: Dict[str, Dict] = {}
        self.lut_cache_ttl = 300  # 5 minutes

    async def __aenter__(self):
        if self._session_owned and self.session is None:
            self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session_owned and self.session:
            await self.session.close()

    async def find_optimal_route(
        self,
        token_address: str,
        amount_in_sol: int,
        min_profit_sol: float = 0.001
    ) -> Optional[ArbitrageRoute]:
        """
        Find the most profitable route for a token using local micro-graph.

        Args:
            token_address: Token to arbitrage
            amount_in_sol: Amount of SOL to flash loan (in lamports)
            min_profit_sol: Minimum profit threshold

        Returns:
            Best ArbitrageRoute or None if no profitable route found
        """
        best_route = None
        best_profit = 0.0

        # Skip if pool data indicates concentrated liquidity (CLMM)
        if self._is_concentrated_liquidity_pool(token_address):
            logger.debug(f"Skipping CLMM pool for {token_address}")
            return None

        # Try each micro-graph path
        for path_template in self.MICRO_GRAPH_PATHS:
            route = await self._calculate_route_profit(
                path_template, token_address, amount_in_sol
            )

            if route and route.is_profitable(min_profit_sol) and not route.exceeds_size_limit():
                if route.profit_sol > best_profit:
                    best_route = route
                    best_profit = route.profit_sol

        if best_route:
            logger.info(f"🎯 Best local route found: {best_route.profit_sol:.6f} SOL profit")
        else:
            logger.debug(f"No profitable local routes for {token_address}")

        return best_route

    async def _calculate_route_profit(
        self,
        path_template: List[Dict],
        token_address: str,
        amount_in_sol: int
    ) -> Optional[ArbitrageRoute]:
        """Calculate profit for a specific route template."""
        try:
            path = []
            current_amount = amount_in_sol

            for hop in path_template:
                pool_address = self._get_pool_for_hop(hop, token_address)
                if not pool_address:
                    return None

                reserves = self.pool_state_manager.get_pool_reserves(pool_address)
                if not reserves or reserves.is_stale():
                    logger.debug(f"Stale or missing reserves for pool {pool_address}")
                    return None

                # Determine input/output reserves based on hop direction
                if hop["input_token"] == "SOL":
                    reserve_in = reserves.quote_reserve  # SOL is quote in most pools
                    reserve_out = reserves.base_reserve
                elif hop["output_token"] == "SOL":
                    reserve_in = reserves.base_reserve
                    reserve_out = reserves.quote_reserve
                else:
                    # Token-to-token hop - need to determine which is which
                    # This is simplified - in practice would need token mint addresses
                    reserve_in = reserves.base_reserve
                    reserve_out = reserves.quote_reserve

                # Calculate output amount
                amount_out = AmmMath.get_amount_out(
                    current_amount, reserve_in, reserve_out, fee_bps=25  # 0.25% swap fee
                )

                if amount_out <= 0:
                    return None

                # Record hop details
                hop_details = {
                    "pool_address": pool_address,
                    "input_token": hop["input_token"],
                    "output_token": hop["output_token"],
                    "amount_in": current_amount,
                    "amount_out": amount_out,
                    "reserve_in": reserve_in,
                    "reserve_out": reserve_out
                }
                path.append(hop_details)

                current_amount = amount_out

            # Calculate final profit
            flash_loan_fee = (amount_in_sol * self.FLASH_LOAN_FEE_BPS) // 10000
            total_cost = amount_in_sol + flash_loan_fee
            profit_sol = (current_amount - total_cost) / 1_000_000_000  # Convert to SOL

            route = ArbitrageRoute(path, amount_in_sol, current_amount, profit_sol)
            return route

        except Exception as e:
            logger.error(f"Error calculating route profit: {e}")
            return None

    def _get_pool_for_hop(self, hop: Dict, token_address: str) -> Optional[str]:
        """Get pool address for a specific hop by looking up active pool states."""
        try:
            # Token mapping for common symbols/placeholders
            MINT_MAP = {
                "SOL": "So11111111111111111111111111111111111111112",
                "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
            }
            
            # Resolve placeholders
            input_token = hop["input_token"]
            output_token = hop["output_token"]
            
            input_mint = token_address if input_token == "TOKEN" else MINT_MAP.get(input_token, input_token)
            output_mint = token_address if output_token == "TOKEN" else MINT_MAP.get(output_token, output_token)

            # Loop through all pools in the manager to find a match
            pool_states = self.pool_state_manager.get_all_pool_states()
            for addr, state in pool_states.items():
                # Check if pool matches both tokens (order doesn't matter for CPMM)
                if (state.token_a_mint == input_mint and state.token_b_mint == output_mint) or \
                   (state.token_a_mint == output_mint and state.token_b_mint == input_mint):
                    return addr

            return None
        except Exception as e:
            logger.error(f"Error finding pool for hop: {e}")
            return None

    def _is_concentrated_liquidity_pool(self, token_address: str) -> bool:
        """Check if token trades on concentrated liquidity pools (CLMM)."""
        # Check pool program IDs that indicate CLMM (X*Y=K doesn't work directly)
        # For tokens that only exist on CLMM, skip local calculation
        # This would need integration with pool registry to check program IDs

        # Placeholder logic - in practice would query pool registry
        # Raydium CLMM: CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK
        # Orca Whirlpools: whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc

        # For now, assume CPMM pools are used unless configured otherwise
        # Real implementation would check against known CLMM pools
        return False

    async def get_jupiter_fallback_route(
        self,
        token_address: str,
        amount_in_sol: int,
        slippage_bps: int = 50
    ) -> Optional[ArbitrageRoute]:
        """
        Get arbitrage route using Jupiter API as fallback.

        Args:
            token_address: Token to arbitrage
            amount_in_sol: Amount of SOL to use
            slippage_bps: Slippage tolerance in basis points

        Returns:
            ArbitrageRoute from Jupiter or None
        """
        try:
            # Jupiter expects input/output mint addresses
            sol_mint = "So11111111111111111111111111111111111111112"  # Wrapped SOL mint

            params = {
                "inputMint": sol_mint,
                "outputMint": token_address,
                "amount": str(int(amount_in_sol)),  # Task 16: strict int→string to avoid HTTP 400
                "slippageBps": slippage_bps,
                "onlyDirectRoutes": "true",  # Task 14: force direct routes for micro-balance safety
                "maxAccounts": 20  # Limit for transaction size
            }

            async with self.session.get(f"{self.jupiter_api_url}/quote", params=params) as response:
                if response.status != 200:
                    logger.debug(f"Jupiter quote failed: {response.status}")
                    return None

                quote_data = await response.json()

                # Check if route exists and is profitable
                if "outAmount" not in quote_data:
                    return None

                out_amount = int(quote_data["outAmount"])
                price_impact_pct = float(quote_data.get("priceImpactPct", 0))

                # Calculate profit (simplified)
                flash_loan_fee = (amount_in_sol * self.FLASH_LOAN_FEE_BPS) // 10000
                total_cost = amount_in_sol + flash_loan_fee
                profit_sol = (out_amount - total_cost) / 1_000_000_000

                if profit_sol <= 0:
                    return None

                # Create route from Jupiter data
                path = [{
                    "pool_address": "jupiter_route",
                    "input_token": "SOL",
                    "output_token": token_address,
                    "amount_in": amount_in_sol,
                    "amount_out": out_amount,
                    "jupiter_data": quote_data
                }]

                route = ArbitrageRoute(path, amount_in_sol, out_amount, profit_sol)
                await self._resolve_address_lookup_tables(route)

                return route

        except Exception as e:
            logger.error(f"Error getting Jupiter fallback route: {e}")
            return None

    async def _resolve_address_lookup_tables(self, route: ArbitrageRoute):
        """Resolve and cache Address Lookup Tables for Jupiter routes."""
        import time

        # Check Jupiter route data for LUT addresses
        jupiter_data = route.path[0].get("jupiter_data", {})
        lut_addresses = jupiter_data.get("addressLookupTableAddresses", [])

        for lut_address in lut_addresses:
            if lut_address in self.lut_cache:
                # Check if cache is still valid
                cached_time = self.lut_cache[lut_address].get("timestamp", 0)
                if time.time() - cached_time < self.lut_cache_ttl:
                    continue

            # Fetch LUT data from RPC (placeholder - would need RPC client)
            # In practice: getAccountInfo with encoding: "base64"
            # Then parse the LUT data structure
            logger.debug(f"Would fetch LUT: {lut_address}")

            # Cache placeholder
            self.lut_cache[lut_address] = {
                "address": lut_address,
                "data": None,  # Would contain parsed LUT data
                "timestamp": time.time()
            }

        # Clean old cache entries
        current_time = time.time()
        expired = [addr for addr, data in self.lut_cache.items()
                  if current_time - data.get("timestamp", 0) > self.lut_cache_ttl]
        for addr in expired:
            del self.lut_cache[addr]

    async def find_route_with_fallback(
        self,
        token_address: str,
        amount_in_sol: int,
        min_profit_sol: float = 0.001
    ) -> Optional[ArbitrageRoute]:
        """
        Find route using local router first, then Jupiter fallback.

        Args:
            token_address: Token to arbitrage
            amount_in_sol: Amount of SOL to use
            min_profit_sol: Minimum profit threshold

        Returns:
            Best route from local or Jupiter
        """
        # Try local routing first
        local_route = await self.find_optimal_route(token_address, amount_in_sol, min_profit_sol)
        if local_route:
            return local_route

        # Fallback to Jupiter
        logger.debug(f"No local route found for {token_address}, trying Jupiter fallback")
        jupiter_route = await self.get_jupiter_fallback_route(token_address, amount_in_sol)
        if jupiter_route and jupiter_route.is_profitable(min_profit_sol):
            return jupiter_route

        return None