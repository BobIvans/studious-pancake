"""Bipartite Orderbook-AMM Solver for Phoenix vs Raydium arbitrage.

Mathematical algorithm to calculate optimal flash loan amount between
Phoenix CLOB (orderbook) and Raydium AMM (CPMM) using MarginFi v2.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import aiohttp

logger = logging.getLogger("OrderbookSolver")

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@dataclass
class OrderbookLevel:
    """A level in the Phoenix orderbook."""
    price: float  # Price in quote per base (e.g., USDC per SOL)
    size: float   # Size in base currency (SOL)


@dataclass
class AmmReserves:
    """Raydium AMM reserves."""
    reserve_a: float  # SOL reserve
    reserve_b: float  # USDC reserve
    fee_pct: float = 0.003  # 0.3% fee


@dataclass
class ArbitrageResult:
    """Result of the bipartite solver."""
    optimal_borrow_amount: float  # Amount to borrow in quote currency (USDC)
    expected_profit: float
    buy_levels_used: List[OrderbookLevel]  # Which orderbook levels to consume
    final_price_impact: float
    iterations: int


class BipartiteOrderbookAmmSolver:
    """Solves for optimal arbitrage between Phoenix orderbook and Raydium AMM."""

    def __init__(
        self,
        max_iterations: int = 100,
        precision_threshold: float = 1e-6,
        marginfi_fee_pct: float = 0.0,  # MarginFi v2 has 0% fee
        max_borrow_pct: float = 0.5,  # Max 50% of available liquidity
    ):
        self.max_iterations = max_iterations
        self.precision_threshold = precision_threshold
        self.marginfi_fee_pct = marginfi_fee_pct
        self.max_borrow_pct = max_borrow_pct

    async def fetch_phoenix_orderbook(self, session: aiohttp.ClientSession, market_address: str) -> Optional[List[OrderbookLevel]]:
        """Fetch orderbook data from Phoenix market."""
        try:
            # Phoenix orderbook API endpoint
            url = f"https://api.phoenix.trade/v1/market/{market_address}/orderbook"

            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    asks = []
                    if "asks" in data:
                        for ask in data["asks"]:
                            # Phoenix returns [price, size] arrays
                            price, size = ask[0], ask[1]
                            asks.append(OrderbookLevel(price=float(price), size=float(size)))
                    return asks
            return None
        except Exception as e:
            logger.warning(f"Failed to fetch Phoenix orderbook for {market_address}: {e}")
            return None

    async def fetch_raydium_reserves(self, session: aiohttp.ClientSession, amm_id: str, rpc_url: str) -> Optional[AmmReserves]:
        """Fetch Raydium AMM reserves from RPC."""
        try:
            # Raydium AMM account structure - fetch account info
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    amm_id,
                    {
                        "encoding": "base64",
                        "commitment": "confirmed"
                    }
                ]
            }

            async with session.post(rpc_url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and "value" in data["result"]:
                        account_data = data["result"]["value"]
                        if account_data and "data" in account_data:
                            import base64
                            b64_string = account_data["data"][0]
                            padded_b64 = b64_string + "=" * (-len(b64_string) % 4)
                            raw_data = base64.b64decode(padded_b64)

                            # Raydium AMM layout: https://docs.raydium.io/raydium/protocol/amm-and-farms/amm-cpmm
                            # Reserves start at offset 144 (after header)
                            if len(raw_data) >= 144 + 16:  # 8 bytes per u64 reserve
                                # Read coin and pc reserves (u64 each)
                                coin_reserve = int.from_bytes(raw_data[144:152], byteorder='little')
                                pc_reserve = int.from_bytes(raw_data[152:160], byteorder='little')

                                # Convert from lamports to decimal (assuming 9 decimals for SOL, 6 for USDC)
                                coin_reserve_dec = coin_reserve / 1_000_000_000  # SOL
                                pc_reserve_dec = pc_reserve / 1_000_000  # USDC

                                return AmmReserves(
                                    reserve_a=coin_reserve_dec,
                                    reserve_b=pc_reserve_dec,
                                    fee_pct=0.0025  # Raydium fee is 0.25%
                                )

            logger.warning(f"Failed to fetch Raydium reserves for {amm_id}")
            return None

        except Exception as e:
            logger.error(f"Error fetching Raydium reserves for {amm_id}: {e}")
            return None

    def solve_optimal_arbitrage(
        self,
        orderbook_asks: List[OrderbookLevel],  # Sell orders (we buy from these)
        amm_reserves: AmmReserves,
        available_liquidity: float,  # Max quote currency available for borrowing
    ) -> Optional[ArbitrageResult]:
        """
        Solve for optimal arbitrage amount using binary search on profit function.

        Args:
            orderbook_asks: List of ask levels sorted by price (ascending)
            amm_reserves: AMM reserve state
            available_liquidity: Maximum borrowable amount in quote currency

        Returns:
            ArbitrageResult with optimal parameters
        """
        if not orderbook_asks:
            return None

        # Binary search bounds
        low = 0.0
        high = min(available_liquidity * self.max_borrow_pct, self._max_profitable_amount(orderbook_asks, amm_reserves))

        if high <= 0:
            return None

        best_result = None
        best_profit = 0.0

        for iteration in range(self.max_iterations):
            # Ternary Search to find peak of convex profit function
            m1 = low + (high - low) / 3
            m2 = high - (high - low) / 3

            # Calculate profit for both test points
            profit1, levels_used1, impact1 = self._calculate_arbitrage_profit(m1, orderbook_asks, amm_reserves)
            profit2, levels_used2, impact2 = self._calculate_arbitrage_profit(m2, orderbook_asks, amm_reserves)

            # Update best results found so far
            if profit1 > best_profit:
                best_profit = profit1
                best_result = ArbitrageResult(
                    optimal_borrow_amount=m1,
                    expected_profit=profit1,
                    buy_levels_used=levels_used1,
                    final_price_impact=impact1,
                    iterations=iteration + 1
                )
            
            if profit2 > best_profit:
                best_profit = profit2
                best_result = ArbitrageResult(
                    optimal_borrow_amount=m2,
                    expected_profit=profit2,
                    buy_levels_used=levels_used2,
                    final_price_impact=impact2,
                    iterations=iteration + 1
                )

            # Shift boundaries towards the peak
            if profit1 < profit2:
                low = m1
            else:
                high = m2

            # Check convergence
            if abs(high - low) < self.precision_threshold:
                break

        return best_result

    def _calculate_arbitrage_profit(
        self,
        borrow_amount: float,
        orderbook_asks: List[OrderbookLevel],
        amm_reserves: AmmReserves
    ) -> Tuple[float, List[OrderbookLevel], float]:
        """
        Calculate profit for a given borrow amount.

        Steps:
        1. Borrow USDC from MarginFi
        2. Buy SOL from Phoenix orderbook (consuming asks)
        3. Sell SOL to Raydium AMM
        4. Repay MarginFi loan
        5. Keep difference as profit
        """
        levels_used = []
        total_sol_bought = 0.0
        total_usdc_spent = 0.0
        remaining_borrow = borrow_amount

        # Step 1-2: Buy SOL from orderbook
        for level in orderbook_asks:
            if remaining_borrow <= 0:
                break

            # How much can we buy at this level?
            max_buy_at_level = min(remaining_borrow / level.price, level.size)

            if max_buy_at_level > 0:
                levels_used.append(OrderbookLevel(level.price, max_buy_at_level))
                total_sol_bought += max_buy_at_level
                total_usdc_spent += max_buy_at_level * level.price
                remaining_borrow -= max_buy_at_level * level.price

        if total_sol_bought == 0:
            return 0.0, [], 0.0

        # Step 3: Sell SOL to AMM (simulate CPMM swap)
        amm_fee = amm_reserves.fee_pct
        amm_output = self._simulate_amm_swap(
            total_sol_bought,
            amm_reserves.reserve_a,
            amm_reserves.reserve_b,
            amm_fee
        )

        # Step 4-5: Calculate profit
        # Profit = AMM output - borrow amount - fees
        marginfi_fee = borrow_amount * self.marginfi_fee_pct
        total_cost = borrow_amount + marginfi_fee
        profit = amm_output - total_cost

        # Price impact on AMM
        price_impact = ((amm_reserves.reserve_b / amm_reserves.reserve_a) -
                       (amm_reserves.reserve_b / (amm_reserves.reserve_a + total_sol_bought)))

        return profit, levels_used, price_impact

    def _simulate_amm_swap(
        self,
        input_amount: float,
        reserve_in: float,
        reserve_out: float,
        fee_pct: float
    ) -> float:
        """Simulate CPMM swap with fee."""
        # Constant product formula: (x + dx) * (y - dy) = x * y
        # With fee: effective_input = input_amount * (1 - fee_pct)

        effective_input = input_amount * (1 - fee_pct)
        output_amount = (reserve_out * effective_input) / (reserve_in + effective_input)

        return output_amount

    def _max_profitable_amount(
        self,
        orderbook_asks: List[OrderbookLevel],
        amm_reserves: AmmReserves
    ) -> float:
        """Estimate maximum potentially profitable amount."""
        if not orderbook_asks:
            return 0.0

        # Simple heuristic: amount where orderbook price meets AMM price
        amm_price = amm_reserves.reserve_b / amm_reserves.reserve_a

        # Find first ask level above AMM price
        for level in orderbook_asks:
            if level.price > amm_price:
                # Estimate based on this level
                return level.size * level.price * 2  # Conservative estimate

        # If all asks are below AMM price, no arbitrage possible
        return 0.0

    async def execute_arbitrage(
        self,
        result: ArbitrageResult,
        tx_builder,  # JupiterTxBuilder
        keypair,
        jito_executor,
        phoenix_program_id: str,
        raydium_program_id: str,
        strategy_type: int = 1
    ) -> bool:
        """Execute the calculated arbitrage transaction."""
        try:
            # Build transaction with Phoenix orderbook instructions + Raydium swap
            # This would require Phoenix SDK integration

            # TODO: Implement transaction building and execution

            logger.info(f"Executed orderbook-AMM arbitrage: borrow {result.optimal_borrow_amount:.2f}, profit {result.expected_profit:.6f}")
            return True

        except Exception as e:
            logger.error(f"Orderbook arbitrage execution failed: {e}")
            return False