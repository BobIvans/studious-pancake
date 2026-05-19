"""
Graph Mathematics for Ultra-Fast Arbitrage Discovery
Implements Bellman-Ford algorithm with logarithmic weights for instant arbitrage detection.
"""

import logging
import math
import time
from typing import Dict, List, Tuple, Optional, Set, Callable
from decimal import Decimal, getcontext
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Set high precision for calculations
getcontext().prec = 28

@dataclass
class PoolReserves:
    """Represents reserves in an AMM pool."""
    __slots__ = ("reserve_in", "reserve_out")
    reserve_in: Decimal
    reserve_out: Decimal

@dataclass
class ArbitrageCycle:
    """Represents a profitable arbitrage cycle."""
    path: List[str]  # Token symbols in cycle
    profit_ratio: Decimal  # Multiplicative profit factor
    profit_bps: int  # Profit in basis points
    required_flash_loan: Decimal  # Optimal flash loan size

@dataclass
class TokenNode:
    """Token node in arbitrage graph."""
    symbol: str
    mint: str
    decimals: int
    reserve_in: Optional[Decimal] = None
    reserve_out: Optional[Decimal] = None

class ArbitrageGraph:
    """
    Micro-graph for arbitrage discovery using Bellman-Ford with logarithmic weights.

    Key Insight: Convert exchange rates to logarithmic weights where:
    - weight = -ln(rate) for each edge
    - Sum of weights along cycle = ln(1/rate_product)
    - Negative cycle sum = profitable arbitrage (rate_product > 1)
    """

    def __init__(self, max_tokens: int = 20):
        self.nodes: Dict[str, TokenNode] = {}  # symbol -> node
        self.edges: Dict[Tuple[str, str], Decimal] = {}  # (from, to) -> log weight
        self.max_tokens = max_tokens
        self.last_update = 0.0
        self.cycle_callback: Optional[Callable] = None
        self.oracle_callback: Optional[Callable] = None

    def add_token(self, symbol: str, mint: str, decimals: int) -> None:
        """Add token to arbitrage graph."""
        if len(self.nodes) >= self.max_tokens:
            logger.warning(f"Graph full ({self.max_tokens} tokens), cannot add {symbol}")
            return

        self.nodes[symbol] = TokenNode(symbol, mint, decimals)
        logger.debug(f"Added token {symbol} to arbitrage graph")

    def update_pool_rate(self, token_a: str, token_b: str, rate_a_to_b: Decimal,
                        reserve_a: Optional[Decimal] = None, reserve_b: Optional[Decimal] = None) -> None:
        """
        Update exchange rate between two tokens.

        Args:
            token_a: Source token symbol
            token_b: Target token symbol
            rate_a_to_b: Exchange rate (how much B you get for 1 A)
            reserve_a: Reserve of token A in pool
            reserve_b: Reserve of token B in pool
        """
        if token_a not in self.nodes or token_b not in self.nodes:
            return

        if rate_a_to_b <= 0:
            return

        # Calculate logarithmic weight: weight = -ln(rate)
        # This makes profitable cycles have negative total weight
        try:
            log_weight = -Decimal(math.log(float(rate_a_to_b)))
        except (ValueError, OverflowError):
            return

        # Update edge in both directions (bidirectional graph)
        self.edges[(token_a, token_b)] = log_weight
        # Reverse rate for opposite direction
        reverse_rate = Decimal('1') / rate_a_to_b
        self.edges[(token_b, token_a)] = -Decimal(math.log(float(reverse_rate)))

        # Update reserves if provided
        if reserve_a is not None:
            self.nodes[token_a].reserve_in = reserve_a
        if reserve_b is not None:
            self.nodes[token_b].reserve_out = reserve_b

        self.last_update = time.time()
        logger.debug(f"Updated rate {token_a}->{token_b}: {rate_a_to_b}")

        # If rates updated, check for arbitrage
        cycles = self.detect_arbitrage_cycles()
        if cycles and self.cycle_callback:
            for cycle in cycles:
                asyncio.create_task(self.cycle_callback(cycle))

    def detect_arbitrage_cycles(self, max_hops: int = 3) -> List[ArbitrageCycle]:
        """
        Detect profitable arbitrage cycles using Bellman-Ford algorithm.

        Args:
            max_hops: Maximum number of hops in arbitrage cycle (2 or 3 recommended)

        Returns:
            List of profitable arbitrage cycles
        """
        if len(self.nodes) < 3:
            return []

        profitable_cycles = []

        # Run Bellman-Ford from each starting node
        for start_symbol in self.nodes.keys():
            cycles = self._bellman_ford_from_source(start_symbol, max_hops)
            profitable_cycles.extend(cycles)

        # Remove duplicates and sort by profitability
        unique_cycles = self._deduplicate_cycles(profitable_cycles)
        unique_cycles.sort(key=lambda x: x.profit_bps, reverse=True)

        return unique_cycles[:5]  # Return top 5 most profitable

    def _bellman_ford_from_source(self, source: str, max_hops: int) -> List[ArbitrageCycle]:
        """
        Run Bellman-Ford from single source to detect negative cycles.
        Modified to detect arbitrage cycles within max_hops.
        """
        nodes = list(self.nodes.keys())
        distances = {node: Decimal('inf') for node in nodes}
        predecessors = {node: None for node in nodes}

        distances[source] = Decimal('0')

        # Relax edges |V| - 1 times
        for _ in range(len(nodes) - 1):
            for (u, v), weight in self.edges.items():
                if distances[u] != Decimal('inf') and distances[u] + weight < distances[v]:
                    distances[v] = distances[u] + weight
                    predecessors[v] = u

        # Check for negative cycles (arbitrage opportunities)
        cycles = []
        for (u, v), weight in self.edges.items():
            if distances[u] != Decimal('inf') and distances[u] + weight < distances[v]:
                # Found negative cycle, reconstruct it
                cycle = self._reconstruct_cycle(predecessors, v, max_hops)
                if cycle and len(cycle) >= 3 and len(cycle) <= max_hops + 1:
                    profit_ratio = self._calculate_cycle_profit(cycle)
                    if profit_ratio > Decimal('1.001'):  # > 0.1% profit
                        profit_bps = int((profit_ratio - Decimal('1')) * Decimal('10000'))
                        optimal_loan = self._calculate_optimal_flash_loan(cycle)

                        arb_cycle = ArbitrageCycle(
                            path=cycle,
                            profit_ratio=profit_ratio,
                            profit_bps=profit_bps,
                            required_flash_loan=optimal_loan
                        )
                        cycles.append(arb_cycle)

        return cycles

    def _reconstruct_cycle(self, predecessors: Dict, start: str, max_length: int) -> Optional[List[str]]:
        """Reconstruct arbitrage cycle from Bellman-Ford predecessors."""
        cycle = []
        current = start

        # Follow predecessors, allowing cycle to close
        for _ in range(max_length + 2):
            if current is None:
                break
            cycle.append(current)
            # Check if we've closed the cycle
            if current in cycle[:-1]:  # Current node appears earlier in cycle
                # Find the start of the cycle
                cycle_start = cycle.index(current)
                return cycle[cycle_start:][::-1]  # Return the cycle reversed to correct order
            current = predecessors.get(current)

        return None

    def _calculate_cycle_profit(self, cycle: List[str]) -> Decimal:
        """Calculate multiplicative profit ratio for a cycle."""
        if len(cycle) < 3:
            return Decimal('1')

        profit_ratio = Decimal('1')
        for i in range(len(cycle) - 1):
            u, v = cycle[i], cycle[i + 1]
            if (u, v) in self.edges:
                # Convert back from log weight: rate = exp(-weight)
                weight = self.edges[(u, v)]
                rate = Decimal(math.exp(float(-weight)))
                profit_ratio *= rate

        return profit_ratio

    def _calculate_optimal_flash_loan(self, cycle: List[str]) -> Decimal:
        """
        Calculate optimal flash loan size for arbitrage cycle.
        Uses simplified analytical formula for CPMM pools.
        """
        if len(cycle) < 3:
            return Decimal('0')

        # For complex cycles, use conservative estimate
        # In practice, this would use the calculus formula
        base_token = cycle[0]
        if base_token in self.nodes:
            # Estimate based on typical pool liquidity
            return Decimal('10')  # 10 base tokens

        return Decimal('1')

    def _deduplicate_cycles(self, cycles: List[ArbitrageCycle]) -> List[ArbitrageCycle]:
        """Remove duplicate cycles (same path, different rotation)."""
        seen_paths = set()
        unique_cycles = []

        for cycle in cycles:
            # Normalize path (rotate to start with lexicographically smallest token)
            path_tuple = tuple(cycle.path)
            min_rotation = min(path_tuple[i:] + path_tuple[:i] for i in range(len(path_tuple)))
            path_key = tuple(min_rotation)

            if path_key not in seen_paths:
                seen_paths.add(path_key)
                unique_cycles.append(cycle)

        return unique_cycles

    def integrate_pool_updates(self, pool_state_manager):
        """Integrate with PoolStateManager for real-time updates."""
        from src.ingest.pool_state_manager import PoolStateManager

        async def on_pool_update(pool_address: str, pool_reserve):
            """Callback when pool reserves update."""
            # Update graph edges with new rates
            if hasattr(pool_reserve, 'token_a_mint') and hasattr(pool_reserve, 'token_b_mint'):
                rate_a_to_b = pool_reserve.token_a_reserve / pool_reserve.token_b_reserve
                self.update_pool_rate(
                    pool_reserve.token_a_mint,
                    pool_reserve.token_b_mint,
                    rate_a_to_b,
                    pool_reserve.token_a_reserve,
                    pool_reserve.token_b_reserve
                )

                # Run arbitrage detection immediately
                cycles = self.detect_arbitrage_cycles()
                if cycles:
                    logger.info(f"🚨 Arbitrage detected from pool update: {cycles[0].path}")
                    if self.cycle_callback:
                        for cycle in cycles:
                            asyncio.create_task(self.cycle_callback(cycle))

        pool_state_manager.register_arbitrage_callback(on_pool_update)

    def integrate_oracle_updates(self, oracle_streams):
        """Integrate with OracleStreams for price discrepancies."""
        from src.ingest.oracle_streams import OracleStreams

        async def on_oracle_update(symbol: str, oracle_price):
            """Callback when oracle price updates."""
            # Check against local AMM prices for discrepancies
            amm_price = self._get_amm_price_for_symbol(symbol)
            if amm_price:
                price_diff_pct = abs(oracle_price.price - amm_price) / amm_price
                if price_diff_pct > 0.0025:  # >0.25%
                    logger.info(f"💰 Oracle lag detected: {symbol} | Oracle: ${oracle_price.price} | AMM: ${amm_price}")
                    if self.oracle_callback:
                        asyncio.create_task(self.oracle_callback(symbol, oracle_price, amm_price))

        oracle_streams.register_price_callback(on_oracle_update)

    def register_cycle_callback(self, callback: Callable):
        """Register callback for profitable arbitrage cycles."""
        self.cycle_callback = callback

    def register_oracle_callback(self, callback: Callable):
        """Register callback for oracle lag discrepancies."""
        self.oracle_callback = callback

    def _get_amm_price_for_symbol(self, symbol: str) -> Optional[Decimal]:
        """Get AMM price for a token symbol (simplified implementation)."""
        # This would integrate with pool state manager to get current AMM price
        # For now, return None (would be implemented in full integration)
        return None

    def get_graph_stats(self) -> Dict:
        """Get statistics about the arbitrage graph."""
        return {
            'nodes': len(self.nodes),
            'edges': len(self.edges),
            'last_update': self.last_update,
            'density': len(self.edges) / (len(self.nodes) * (len(self.nodes) - 1)) if len(self.nodes) > 1 else 0
        }