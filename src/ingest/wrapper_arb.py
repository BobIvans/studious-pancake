"""
BTC Wrapper Peg Arbitrage — Arbitrage between cbBTC, wBTC, tBTC peg deviations.

Exploits temporary price deviations between wrapped Bitcoin variants.
When one BTC wrapper trades at a discount vs another (e.g. cbBTC < wBTC),
we: Flash loan USDC → Buy cheap BTC → Sell expensive BTC → Repay USDC.
This is a pure mathematical arb: all BTC wrappers should trade at 1:1 peg.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any

from src.ingest.shared_state import to_ui_amount

logger = logging.getLogger(__name__)

# Mainnet mint addresses
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
CB_BTC_MINT = "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij"     # Coinbase BTC
WBTC_MINT = "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh"     # Wormhole BTC
TBTC_MINT = "6DNSN2BJsaPFdFFc1zP37kkeNe4Usc1Sqkzr9C9vPWcU"     # Threshold BTC

# All BTC wrappers for circular arb
BTC_WRAPPERS = [CB_BTC_MINT, WBTC_MINT, TBTC_MINT]
BTC_WRAPPER_LABELS = {
    CB_BTC_MINT: "cbBTC",
    WBTC_MINT: "wBTC",
    TBTC_MINT: "tBTC",
}


class WrapperPegArb:
    """
    BTC Wrapper Peg Arbitrage strategy.

    Detects price deviations between BTC wrapper tokens and executes
    a 3-leg flash loan arbitrage: USDC → Cheap BTC → Expensive BTC → USDC.

    All routes go through Jupiter API — no custom DEX math needed.
    """

    def __init__(
        self,
        session,
        tx_builder,
        optimal_trade_sizer=None,
        execution_router=None,
        min_profit_sol: float = 0.0005,
        price_matrix: Optional[Dict[str, tuple]] = None,
    ):
        self.session = session
        self.tx_builder = tx_builder
        self.optimal_trade_sizer = optimal_trade_sizer
        self.execution_router = execution_router
        self.min_profit_sol = min_profit_sol
        self.price_matrix = price_matrix or {}

    async def scan_and_execute(self, usdc_borrow_lamports: int) -> Dict[str, Any]:
        """
        Scan all BTC wrapper pairs for peg deviations and execute if profitable.

        Args:
            usdc_borrow_lamports: Available USDC borrow amount from MarginFi

        Returns:
            Execution result dict
        """
        results = []
        # Check all pairs: buy cheap wrapper, sell expensive wrapper
        for cheap_mint in BTC_WRAPPERS:
            for expensive_mint in BTC_WRAPPERS:
                if cheap_mint == expensive_mint:
                    continue

                result = await self._check_and_execute_pair(
                    cheap_mint=cheap_mint,
                    expensive_mint=expensive_mint,
                    usdc_borrow_lamports=usdc_borrow_lamports,
                )
                if result and result.get("status") == "success":
                    results.append(result)

        return {
            "status": "success" if results else "no_opportunity",
            "trades": results,
            "count": len(results),
        }

    async def _check_and_execute_pair(
        self,
        cheap_mint: str,
        expensive_mint: str,
        usdc_borrow_lamports: int,
    ) -> Dict[str, Any]:
        """
        Check a single BTC wrapper pair for peg deviation and execute.

        Route: USDC → cheap_BTC → expensive_BTC → USDC
        """
        cheap_label = BTC_WRAPPER_LABELS.get(cheap_mint, cheap_mint[:8])
        expensive_label = BTC_WRAPPER_LABELS.get(expensive_mint, expensive_mint[:8])

        logger.info(f"🔍 Checking peg: {cheap_label} -> {expensive_label}")

        try:
            # Step 1: Get quote for USDC → cheap BTC (first leg)
            leg1_quote = await self._get_jupiter_quote(
                input_mint=USDC_MINT,
                output_mint=cheap_mint,
                amount=usdc_borrow_lamports,
            )
            if not leg1_quote:
                logger.debug(f"{cheap_label}→{expensive_label}: no leg1 quote")
                return {"status": "no_quote", "pair": f"{cheap_label}→{expensive_label}"}

            cheap_btc_out = int(leg1_quote.get("outAmount", 0))
            if cheap_btc_out <= 0:
                return {"status": "no_liquidity", "pair": f"{cheap_label}→{expensive_label}"}

            # Step 2: Get quote for cheap BTC → expensive BTC (second leg)
            leg2_quote = await self._get_jupiter_quote(
                input_mint=cheap_mint,
                output_mint=expensive_mint,
                amount=cheap_btc_out,
            )
            if not leg2_quote:
                logger.debug(f"{cheap_label}→{expensive_label}: no leg2 quote")
                return {"status": "no_quote", "pair": f"{cheap_label}→{expensive_label}"}

            expensive_btc_out = int(leg2_quote.get("outAmount", 0))

            # Step 3: Get ExactOut quote for expensive BTC → USDC (third leg — repay)
            # Use ExactOut to guarantee we get exactly usdc_borrow_lamports USDC,
            # leaving any residual expensive_btc as pure profit.
            leg3_quote = await self._get_jupiter_quote(
                input_mint=expensive_mint,
                output_mint=USDC_MINT,
                amount=usdc_borrow_lamports,
                swap_mode="ExactOut",
            )
            if not leg3_quote:
                logger.debug(f"{cheap_label}→{expensive_label}: no leg3 quote")
                return {"status": "no_quote", "pair": f"{cheap_label}→{expensive_label}"}

            # With ExactOut, outAmount is fixed at usdc_borrow_lamports;
            # inAmount tells us how much expensive_btc must be spent.
            expensive_btc_spent = int(leg3_quote.get("inAmount", 0))
            usdc_out = int(leg3_quote.get("outAmount", 0))
            residual_expensive_btc = expensive_btc_out - expensive_btc_spent

            # Profit = residual expensive_btc valued at the swap rate from this quote
            if residual_expensive_btc > 0 and expensive_btc_spent > 0:
                rate = usdc_out / expensive_btc_spent
                profit_lamports = int(residual_expensive_btc * rate)
            else:
                profit_lamports = usdc_out - usdc_borrow_lamports
            if profit_lamports <= 0:
                logger.debug(f"{cheap_label}→{expensive_label}: no profit ({profit_lamports} lamports)")
                return {
                    "status": "not_profitable",
                    "pair": f"{cheap_label}→{expensive_label}",
                    "profit_lamports": profit_lamports,
                }

            # Convert USDC profit to SOL using live price from price_matrix
            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            sol_mint = "So11111111111111111111111111111111111111112"
            sol_price_usd = 150.0
            sol_entry = self.price_matrix.get(sol_mint)
            if sol_entry:
                sol_price_usd = sol_entry[0]
            profit_usdc = to_ui_amount(profit_lamports, 6)
            profit_sol = profit_usdc / sol_price_usd

            if profit_sol < self.min_profit_sol:
                logger.debug(
                    f"{cheap_label}→{expensive_label}: profit {profit_sol:.6f} SOL "
                    f"below threshold {self.min_profit_sol:.6f}"
                )
                return {
                    "status": "below_threshold",
                    "pair": f"{cheap_label}→{expensive_label}",
                    "profit_sol": profit_sol,
                }

            logger.info(
                f"💰 BTC peg arb: {cheap_label}→{expensive_label} | "
                f"borrow={usdc_borrow_lamports/1e6:.2f} USDC | "
                f"profit={profit_sol:.6f} SOL"
            )

            # Execute via execution_router
            if self.execution_router:
                opportunity = {
                    "strategy": "wrapper_peg",
                    "pair": f"{cheap_label}→{expensive_label}",
                    "cheap_mint": cheap_mint,
                    "expensive_mint": expensive_mint,
                    "borrow_amount_lamports": usdc_borrow_lamports,
                    "expected_profit_sol": profit_sol,
                    "leg1_quote": leg1_quote,
                    "leg2_quote": leg2_quote,
                    "leg3_quote": leg3_quote,
                    "cheap_btc_out": cheap_btc_out,
                    "expensive_btc_out": expensive_btc_out,
                    "usdc_out": usdc_out,
                    "jito_tip_pct": 0.40,  # 40% of profit goes to Jito tip
                }
                return await self.execution_router.execute_arbitrage_opportunity(opportunity)
            else:
                return {
                    "status": "no_router",
                    "pair": f"{cheap_label}→{expensive_label}",
                    "profit_sol": profit_sol,
                }

        except Exception as e:
            logger.error(f"BTC peg arb error {cheap_label}→{expensive_label}: {e}")
            return {"status": "error", "message": str(e)}

    async def _get_jupiter_quote(
        self, input_mint: str, output_mint: str, amount: int, swap_mode: str = "ExactIn"
    ) -> Optional[Dict]:
        """Fetch a quote from Jupiter Quote API."""
        import os
        import aiohttp

        url = os.getenv("JUPITER_QUOTE_API", "https://api.jup.ag/swap/v2/quote")
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(int(amount)),
            "slippageBps": "10",
            "onlyDirectRoutes": "false",
            "restrictIntermediateTokens": "false",
            "maxAccounts": "28",
            "swapMode": swap_mode,
        }
        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with self.session.get(url, params=params, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception as e:
            logger.debug(f"Jupiter quote error {input_mint[:8]}→{output_mint[:8]}: {e}")
            return None
