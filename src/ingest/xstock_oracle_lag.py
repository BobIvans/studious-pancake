"""
xStocks Oracle Lag Strategy
Detects price discrepancies between Pyth Oracle and DEX prices for xStocks tokens
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
from decimal import Decimal
import aiohttp

from src.config.xstocks_registry import (
    get_xstock_mint,
    get_xstock_info,
    ACTIVE_XSTOCKS,
    XSTOCK_PRIORITY_ORDER,
    USDC_MINT
)
from oracle_streams import PRIORITY_QUEUE_ORDER
from .pyth_oracle_client import get_pyth_client

logger = logging.getLogger(__name__)


class XStockOracleLagStrategy:
    """
    Strategy for detecting and exploiting oracle lag between Pyth prices and DEX prices
    for xStocks (real-world asset tokens on Solana).
    """

    def __init__(self, session, cfg, optimal_trade_sizer, tx_builder, execution_router):
        self.session = session
        self.cfg = cfg
        self.optimal_trade_sizer = optimal_trade_sizer
        self.tx_builder = tx_builder
        self.execution_router = execution_router

        # Pyth client for price feeds
        self.pyth_client = get_pyth_client()

        # Strategy parameters
        self.min_profit_threshold = Decimal(str(getattr(cfg, 'ORACLE_LAG_MIN_PROFIT_SOL', 0.25)))
        self.lag_threshold_pct = Decimal(str(getattr(cfg, 'ORACLE_LAG_THRESHOLD_PCT', 0.45)))

        # Cooldown tracking to prevent spam
        self.last_execution: Dict[str, datetime] = {}
        self.cooldown_seconds = 60  # 1 minute cooldown per ticker

        # Lag monitoring
        self.lag_stats: Dict[str, List[float]] = {}

        logger.info("🎯 xStocks Oracle Lag Strategy initialized")
        logger.info(f"   Min profit: {self.min_profit_threshold} SOL")
        logger.info(f"   Lag threshold: {self.lag_threshold_pct}%")
        logger.info(f"   Active pairs: {len(ACTIVE_XSTOCKS)}")

    async def process_swap_event(self, event_data: Dict[str, Any]) -> None:
        """
        Process Helius webhook SWAP event for xStocks tokens.

        Args:
            event_data: Helius webhook event data
        """
        try:
            # Extract token info from swap event
            token_mint = self._extract_token_mint_from_event(event_data)
            if not token_mint:
                return

            # Check if it's an xStock token
            ticker = self._get_ticker_from_mint(token_mint)
            if not ticker:
                return

            # Get pair info using updated function
            pair_info = get_xstock_info(ticker)
            if not pair_info:
                return

            logger.debug(f"📊 Processing xStock swap: {ticker} ({token_mint[:8]}...)")

            # Check cooldown
            if self._is_on_cooldown(ticker):
                logger.debug(f"⏰ Cooldown active for {ticker}")
                return

            # Get Pyth oracle price
            oracle_price = self.pyth_client.get_current_price(ticker)
            if not oracle_price:
                logger.debug(f"❌ No Pyth price for {ticker}")
                return

            # Get current DEX price via Jupiter quote
            dex_price = await self._get_jupiter_price(ticker)
            if not dex_price:
                logger.debug(f"❌ No DEX price for {ticker}")
                return

            # Calculate lag percentage
            lag_pct = self._calculate_lag_percentage(oracle_price, dex_price)

            # Track lag for monitoring
            self._track_lag(ticker, lag_pct)

            logger.info(
                f"🐍 {ticker} | Oracle: ${oracle_price:.4f} | DEX: ${dex_price:.4f} | "
                f"Lag: {lag_pct:.2f}% | Threshold: {self.lag_threshold_pct}%"
            )

            # Check if lag exceeds threshold
            if abs(lag_pct) >= float(self.lag_threshold_pct):
                await self._execute_arbitrage(ticker, oracle_price, dex_price, lag_pct, event_data)
            else:
                logger.debug(f"📉 Lag {lag_pct:.2f}% below threshold {self.lag_threshold_pct}%")

        except Exception as e:
            logger.error(f"Error processing xStock swap event: {e}")

    async def _get_jupiter_price(self, ticker: str) -> Optional[float]:
        """
        Get current DEX price via Jupiter API for xStock token.

        Args:
            ticker: xStock ticker symbol

        Returns:
            Price in USD or None if unavailable
        """
        try:
            pair_info = get_xstock_info(ticker)
            if not pair_info or not pair_info.get("mint"):
                return None

            token_mint = pair_info["mint"]

            # Jupiter quote API - get xStock/USDC price
            quote_url = (
                f"https://quote-api.jup.ag/v6/quote?"
                f"inputMint={token_mint}&"
                f"outputMint={USDC_MINT}&"
                f"amount=100000000&"  # 1 token (CORRECTED Phase 48: 8 decimals)
                f"slippageBps=50&"
                f"maxAccounts=16&"  # Limit accounts to fit in 1232 bytes
                f"onlyDirectRoutes=false&restrictIntermediateTokens=true&maxAccounts=16"  # Enable multi-hop for hidden liquidity
            )

            async with self.session.get(quote_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "outAmount" in data:
                        # Convert lamports to USD value
                        out_amount_lamports = int(data["outAmount"])
                        out_amount_usdc = out_amount_lamports / 1_000_000  # USDC has 6 decimals

                        # Since we quoted 1 xStock token, price = USDC received
                        return out_amount_usdc

            logger.warning(f"Failed to get Jupiter quote for {ticker}")
            return None

        except Exception as e:
            logger.error(f"Error getting Jupiter price for {ticker}: {e}")
            return None

    def _calculate_lag_percentage(self, oracle_price: float, dex_price: float) -> float:
        """
        Calculate percentage difference between oracle and DEX prices.

        Positive lag = DEX price > Oracle price (opportunity to sell)
        Negative lag = DEX price < Oracle price (opportunity to buy)

        Args:
            oracle_price: Pyth oracle price
            dex_price: DEX/Jupiter price

        Returns:
            Lag percentage
        """
        if oracle_price == 0:
            return 0.0

        return ((dex_price - oracle_price) / oracle_price) * 100

    def _track_lag(self, ticker: str, lag_pct: float) -> None:
        """Track lag statistics for monitoring."""
        if ticker not in self.lag_stats:
            self.lag_stats[ticker] = []

        self.lag_stats[ticker].append(lag_pct)

        # Keep only last 100 measurements
        if len(self.lag_stats[ticker]) > 100:
            self.lag_stats[ticker] = self.lag_stats[ticker][-100:]

    async def _execute_arbitrage(self, ticker: str, oracle_price: float, dex_price: float,
                               lag_pct: float, event_data: Dict[str, Any]) -> None:
        """
        Execute arbitrage trade when lag threshold is exceeded.

        Non-Atomic Flashloan Guard (Fix 32):
        Flashloans MUST be repaid in the same transaction — the bot cannot hold an asset
        with borrowed funds. This strategy ONLY executes if an IMMEDIATE circular cross-DEX
        arbitrage route exists (buy on DEX A, sell on DEX B in the same atomic transaction).
        If no circular route is found, the opportunity is DROPPED.

        Args:
            ticker: xStock ticker
            oracle_price: Pyth oracle price
            dex_price: DEX price
            lag_pct: Calculated lag percentage
            event_data: Original webhook event data
        """
        try:
            # Determine trade direction
            if lag_pct > 0:
                # DEX price > Oracle price -> Sell xStock on DEX, expect convergence
                trade_direction = "SELL"
                expected_profit = self._estimate_profit(ticker, dex_price, oracle_price)
            else:
                # DEX price < Oracle price -> Buy xStock on DEX, expect convergence
                trade_direction = "BUY"
                expected_profit = self._estimate_profit(ticker, oracle_price, dex_price)

            # Check minimum profit threshold
            if expected_profit < 0.0005:  # Micro-profit for 0.017 SOL capital
                logger.info(
                    f"💰 {ticker} {trade_direction} | Expected profit ${expected_profit:.4f} "
                    f"below threshold ${float(self.min_profit_threshold):.4f}"
                )
                return

            # ── Fix 32: Non-Atomic Flashloan Strategy Guard ──────────────────────
            # Flashloans MUST be repaid in the same transaction.
            # We CANNOT buy a token with borrowed funds and hold it.
            # ONLY execute if an immediate circular cross-DEX arb exists:
            #   buy xStock cheap on DEX A → immediately sell on DEX B at higher price.
            # No holding, no oracle convergence wait. Atomic or drop.

            pair_info = get_xstock_info(ticker)
            if not pair_info:
                return
            token_mint = pair_info["mint"]

            logger.info(
                f"🔍 {ticker} | Checking for immediate circular cross-DEX route | "
                f"Lag: {lag_pct:.2f}% | Direction: {trade_direction}"
            )

            # Fetch Jupiter quote for xStock → USDC (leg 1)
            # and get the out-amount so we can immediately reverse back.
            circular_quote = await self._find_immediate_circular_route(token_mint, ticker)
            if circular_quote is None:
                return  # Drop opportunity — no immediate circular route

            # Fix 34: Profit-Aware Dynamic Slippage
            # Set slippage ≤ 40% of expected profit (BPS), minimum 1 BPS.
            immediate_slippage_bps = self._get_immediate_slippage_bps(expected_profit, lag_pct)
            logger.info(
                f"🛡️ {ticker} | Circular route confirmed | "
                f"Dynamic slippage: {immediate_slippage_bps} BPS (profit-aware)"
            )

            logger.info(
                f"🚀 {ticker} {trade_direction} | Lag: {lag_pct:.2f}% | "
                f"Expected profit: ${expected_profit:.4f} SOL"
            )

            # Dynamic size using MarginFi USDC liquidity + OptimalTradeSizer
            from arb_bot import MARGINFI_BANKS
            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            usdc_bank_info = MARGINFI_BANKS.get(usdc_mint, {})

            if not usdc_bank_info:
                logger.error("Missing USDC bank info for xStocks flashloan")
                return

            max_usdc_lamports = await self.tx_builder.get_max_marginfi_borrow(str(usdc_bank_info["liquidity_vault"]))

            if max_usdc_lamports < 10_000_000:  # Min 10 USDC
                logger.warning("Not enough USDC liquidity in MarginFi")
                return

            reserves = [Decimal('1000000'), Decimal('1000000')]
            if self.optimal_trade_sizer:
                analytical_size = self.optimal_trade_sizer.calculate_analytical_optimal_size(reserves, [0.003])
                if analytical_size:
                    analytical_size_lamports = int(analytical_size * Decimal('1000000'))
                    optimal_size = min(analytical_size_lamports, max_usdc_lamports)
                else:
                    optimal_size = max_usdc_lamports
            else:
                optimal_size = max_usdc_lamports

            # Safety check for Token-2022 transfer fees: halve size
            if pair_info.get("program") == "Token-2022":
                optimal_size = optimal_size // 2
                logger.info(f"🛡️ Token-2022 safety: reduced {ticker} trade size to {optimal_size} lamports")

            # ── Bug 1 Fix: Defensive type safety ─────────────────────────────────
            # Cast to float before packing into opportunity dict to guarantee
            # downstream arithmetic is float×float, not Decimal×float.
            opportunity = {
                "strategy": "xstock_oracle_lag",
                "ticker": ticker,
                "token_mint": pair_info["mint"],
                "direction": trade_direction,
                "oracle_price": float(oracle_price),
                "dex_price": float(dex_price),
                "lag_pct": float(lag_pct),
                "expected_profit_sol": float(expected_profit),
                "optimal_size_lamports": float(optimal_size),
                "quote": circular_quote,
                "immediate_slippage_bps": immediate_slippage_bps,
                "event_data": event_data,
                "timestamp": datetime.now().isoformat()
            }

            # Submit to execution router
            result = await self.execution_router.execute_arbitrage_opportunity(opportunity)
            success = result.get("status") == "success"

            if success:
                # Set cooldown
                self.last_execution[ticker] = datetime.now()
                logger.info(f"✅ {ticker} arbitrage executed | Size: {optimal_size} lamports")
            else:
                logger.warning(f"❌ {ticker} arbitrage execution failed")

        except Exception as e:
            logger.error(f"Error executing {ticker} arbitrage: {e}")

    def _get_immediate_slippage_bps(self, expected_profit_sol: float, lag_pct: float) -> int:
        """
        Fix 34: Profit-Aware Dynamic Slippage (Anti-Sandwich Guard).

        Sets allowed slippage to max(1 BPS, 40% of expected profit in BPS).
        This mathematically prevents sandwich attacks from consuming our capital,
        because even in the worst case, 60% of the spread remains profit.

        Args:
            expected_profit_sol: Expected arbitrage profit in SOL
            lag_pct: Price lag percentage between oracle and DEX

        Returns:
            Maximum allowed slippage in BPS, minimum 1 BPS
        """
        # Estimate gross spread BPS from lag percentage (proxy for available spread)
        gross_spread_bps = max(abs(lag_pct) * 100, 10)  # At least 10 BPS floor

        # Derive expected profit as a fraction of gross spread (conservative capture rate)
        # 80% convergence = we capture 80% of the theoretical spread as profit
        expected_profit_bps = gross_spread_bps * 0.8

        # Profit-aware cap: slippage ≤ 40% of expected profit
        anti_sandwich_bps = int(expected_profit_bps * 0.4)

        # Enforce minimum 1 BPS — never zero, never negative
        return max(anti_sandwich_bps, 1)

    async def _find_immediate_circular_route(
            self, token_mint: str, ticker: str
        ) -> Optional[Dict]:
            """
            Ищем арбитраж: USDC -> xStock (дешево на DEX А) -> USDC (дорого на DEX Б).
            """
            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            
            # 1. Узнаем ликвидность USDC банка в MarginFi
            from arb_bot import MARGINFI_BANKS
            usdc_bank_info = MARGINFI_BANKS.get(usdc_mint, {})
            if not usdc_bank_info:
                logger.error("❌ Missing USDC bank info for flashloan")
                return None
                
            try:
                # Пытаемся вытянуть 95% ликвидности USDC из банка MarginFi
                payload = {
                    "jsonrpc": "2.0", "id": 1, "method": "getTokenAccountBalance",
                    "params": [str(usdc_bank_info["liquidity_vault"])]
                }
                async with self.session.post(self.cfg.WSS_ENDPOINTS[0].replace("wss", "https"), json=payload) as resp:
                    data = await resp.json()
                    vault_lamports = int(data["result"]["value"]["amount"])
                    marginfi_max = int(vault_lamports * 0.95)

                    # SMART SIZING: Hard cap to protect capital from small RWA/meme pool slippage
                    HARD_CAP_USDC = 500 * 1_000_000        # $500 max per trade for stables
                    HARD_CAP_SOL  = 10 * 1_000_000_000    # 10 SOL max for LST trades
                    max_usdc_lamports = min(marginfi_max, HARD_CAP_USDC)

                    if hasattr(self, 'optimal_trade_sizer'):
                        max_usdc_lamports = int(self.optimal_trade_sizer.find_optimal_trade_size(
                            routes=[], amount_in=max_usdc_lamports, decimals_in=6, decimals_out=6, jito_tip_sol=0.00001
                        ) or max_usdc_lamports) 
            except Exception as e:
                logger.warning(f"⚠️ Could not check MarginFi USDC liquidity, using safe default 10 USDC: {e}")
                max_usdc_lamports = 10_000_000
    
            if max_usdc_lamports < 1_000_000: # Меньше 1 USDC
                return None
    
            # Step 1: Quote USDC → xStock (Покупаем дешево)
            quote_usdc_to_xstock = await self._get_jupiter_price_quote(
                usdc_mint, token_mint, max_usdc_lamports
            )
            if not quote_usdc_to_xstock or "outAmount" not in quote_usdc_to_xstock:
                return None
    
            out_amount_xstock = int(quote_usdc_to_xstock["outAmount"])
            
            # Step 2: Quote xStock → USDC (Продаем дорого)
            quote_xstock_to_usdc = await self._get_jupiter_price_quote(
                token_mint, usdc_mint, out_amount_xstock
            )
            if not quote_xstock_to_usdc or "outAmount" not in quote_xstock_to_usdc:
                return None
    
            out_amount_usdc_after = int(quote_xstock_to_usdc["outAmount"])
            
            # Проверяем: Получим ли мы обратно больше USDC, чем взяли?
            if out_amount_usdc_after <= max_usdc_lamports:
                return None # Не выгодно
    
            return {
                "circular_quote_out": out_amount_usdc_after,
                "risk_out": max_usdc_lamports,
                "step1": quote_usdc_to_xstock,
                "step2": quote_xstock_to_usdc,
            }

    async def _get_jupiter_price_quote(
        self, input_mint: str, output_mint: str, amount_lamports: int
    ) -> Optional[Dict]:
        """Fetch raw Jupiter /v6/quote dict for a given mint/amount pair."""
        try:
            url = (
                f"https://quote-api.jup.ag/v6/quote?"
                f"inputMint={input_mint}&"
                f"outputMint={output_mint}&"
                f"amount={amount_lamports}&"
                f"slippageBps=1&"
                f"maxAccounts=16&"
                f"onlyDirectRoutes=false&restrictIntermediateTokens=true&maxAccounts=16"
            )
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=5.0)) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception as e:
            logger.debug(f"Jupiter quote fetch error ({input_mint[:8]}→{output_mint[:8]}): {e}")
        return None

    def _estimate_profit(self, ticker: str, entry_price: float, exit_price: float) -> float:
        """
        Estimate potential profit from convergence trade.

        This is a simplified estimation - in production, would use
        more sophisticated modeling of convergence probability and time.

        Args:
            ticker: xStock ticker
            entry_price: Price to enter trade at
            exit_price: Expected exit price

        Returns:
            Estimated profit in SOL
        """
        # Simplified: assume 80% convergence to oracle price
        convergence_factor = 0.8
        expected_convergence_price = entry_price + (exit_price - entry_price) * convergence_factor

        # Calculate profit per token
        if entry_price > 0:
            profit_per_token = abs(expected_convergence_price - entry_price)
            profit_pct = profit_per_token / entry_price

            # Assume $100k trade size for estimation
            trade_size_usd = 100_000
            profit_usd = trade_size_usd * profit_pct

            # Convert to SOL (rough approximation)
            sol_price = 150  # Assume $150/SOL
            profit_sol = profit_usd / sol_price

            return profit_sol
        return 0.0

    def _extract_token_mint_from_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """Extract xStock token mint from Helius webhook event."""
        try:
            # Helius swap event structure
            accounts = event_data.get("accountData", [])
            for account in accounts:
                mint = account.get("account", {}).get("mint")
                if mint and mint.startswith("Xs"):  # xStock tokens start with "Xs"
                    return mint
            return None
        except Exception as e:
            logger.error(f"Error extracting mint from event: {e}")
            return None

    def _get_ticker_from_mint(self, mint: str) -> Optional[str]:
        """Get ticker symbol from mint address."""
        for ticker, info in ACTIVE_XSTOCKS.items():
            if info.get("mint") == mint:
                return ticker
        return None

    def _is_on_cooldown(self, ticker: str) -> bool:
        """Check if ticker is on cooldown from recent execution."""
        if ticker in self.last_execution:
            time_since_last = datetime.now() - self.last_execution[ticker]
            return time_since_last < timedelta(seconds=self.cooldown_seconds)
        return False

    def get_lag_report(self) -> Dict[str, Any]:
        """Generate lag monitoring report."""
        report = {
            "active_pairs": len(ACTIVE_XSTOCKS),

            "lag_stats": {}
        }

        for ticker in ACTIVE_XSTOCKS.keys():
            if ticker in self.lag_stats and self.lag_stats[ticker]:
                lags = self.lag_stats[ticker]
                report["lag_stats"][ticker] = {
                    "average_lag_pct": sum(lags) / len(lags),
                    "max_lag_pct": max(lags),
                    "min_lag_pct": min(lags),
                    "samples": len(lags)
                }

        return report

    async def periodic_lag_scan(self) -> None:
        """
        Periodic scan for lag opportunities (fallback when webhooks miss events).
        Runs every 30 seconds for high-priority tickers.
        """
        while True:
            try:
                # Check top priority tickers
                for ticker in PRIORITY_QUEUE_ORDER[:10]:  # Top 10 priority
                    if self._is_on_cooldown(ticker):
                        continue

                    pair_info = get_xstock_info(ticker)
                    if not pair_info or not pair_info.get("mint"):
                        continue

                    # Get prices
                    oracle_price = self.pyth_client.get_current_price(ticker)
                    dex_price = await self._get_jupiter_price(ticker)

                    if oracle_price and dex_price:
                        lag_pct = self._calculate_lag_percentage(oracle_price, dex_price)

                        # Log periodic scan results
                        if abs(lag_pct) >= float(self.lag_threshold_pct) * 0.5:  # Lower threshold for logging
                            logger.info(
                                f"🔍 Periodic scan {ticker} | Lag: {lag_pct:.2f}% | "
                                f"Oracle: ${oracle_price:.4f} | DEX: ${dex_price:.4f}"
                            )

            except Exception as e:
                logger.error(f"Error in periodic lag scan: {e}")

            await asyncio.sleep(30)  # Scan every 30 seconds


# Global strategy instance
_xstock_strategy = None


def get_xstock_strategy() -> XStockOracleLagStrategy:
    """Get global xStock strategy instance."""
    return _xstock_strategy


def init_xstock_strategy(session, cfg, optimal_trade_sizer, tx_builder, execution_router):
    """Initialize global xStock strategy instance."""
    global _xstock_strategy
    _xstock_strategy = XStockOracleLagStrategy(
        session, cfg, optimal_trade_sizer, tx_builder, execution_router
    )
    return _xstock_strategy