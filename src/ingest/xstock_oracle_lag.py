"""
xStocks Cross-Venue Oracle Lag Strategy

Atomic Cross-DEX arbitrage between different trading venues (AMM vs CLOB)
using Pyth oracle price as a neutral price reference.

Strategy types:
  1. CROSS_VENUE:  Buy on Raydium (AMM, slow) → Sell on Phoenix (CLOB, fast)
                    using the oracle as a price anchor. Captures the inefficiency
                    between different execution mechanisms.

  2. MONDAY_OPEN_GAP: During Monday NYSE open (16:30 MSK), volatility spikes
                       cause extreme lag. Threshold is temporarily lowered.

  3. PRIORITY_PAIRS: Focus on crypto-proxy stocks (MSTRx, COINx, MARAx, RIOTx)
                      that correlate with BTC. When BTC moves, these lag on AMM
                      but update instantly on Pyth.

Execution flow (STRICT_JITO_MODE only):
  1. Borrow USDC from MarginFi v2 (0% fee) via flashloan.
  2. Jupiter swap (onlyDirectRoutes=false): USDC → xStock (buy cheap on slow venue).
  3. Jupiter swap (onlyDirectRoutes=false): xStock → USDC (sell at fair price on faster venue).
  4. Repay USDC to MarginFi + profit in same Jito bundle.
  No holding period: the borrow/repay cycle is atomic via Jito bundle ordering.
"""

import asyncio
import logging
import time
from typing import Dict, Optional, Any, List, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
import aiohttp
import pytz

from src.config.xstocks_registry import (
    get_xstock_info,
    ACTIVE_XSTOCKS,
    XSTOCK_PRIORITY_ORDER,
    USDC_MINT
)
from .pyth_oracle_client import get_pyth_client
from .jupiter_api_client import JupiterClient
import src.ingest.shared_state as shared_state

logger = logging.getLogger(__name__)

# ─── Known DEX labels from Jupiter routePlan ──────────────────────────────
SLOW_VENUES = {"Raydium", "Orca", "Meteora", "Saber", "GooseFX", "Crema"}  # AMM — slower to react
FAST_VENUES = {"Phoenix", "OpenBook", "Serum"}  # CLOB — faster to react

# Crypto-proxy pairs (highest BTC correlation → biggest lag when BTC moves)
CRYPTO_PROXY_TICKERS = {"MSTRx", "COINx", "MARAx", "RIOTx", "HOODx"}


def is_market_open() -> bool:
    """Check if NYSE is tradable: 16:30-23:00 MSK, weekdays only.
    Crypto-proxy xStocks (MSTRx, COINx) skip this check.
    """
    tz = pytz.timezone('Europe/Moscow')
    now = datetime.now(tz)

    if now.weekday() >= 5:
        return False

    market_start = now.replace(hour=16, minute=30, second=0, microsecond=0)
    market_end = now.replace(hour=23, minute=0, second=0, microsecond=0)

    return market_start <= now <= market_end


def is_monday_open_window() -> bool:
    """Check if within the Monday Open Gap window (first 5 min of NYSE open).
    During this window, Pyth makes a sharp jump, but AMM pools haven't updated.
    """
    tz = pytz.timezone('Europe/Moscow')
    now = datetime.now(tz)

    if now.weekday() != 0:  # Monday
        return False

    open_start = now.replace(hour=16, minute=30, second=0, microsecond=0)
    open_end = now.replace(hour=16, minute=35, second=0, microsecond=0)

    return open_start <= now <= open_end


def extract_venues_from_quote(quote: Dict) -> List[str]:
    """Extract DEX venue labels from a Jupiter quote routePlan."""
    venues = []
    route_plan = quote.get("routePlan", [])
    for step in route_plan:
        swap_info = step.get("swapInfo", {})
        label = swap_info.get("label", "Unknown")
        if label:
            venues.append(label)
    return venues


def is_cross_venue_quote(quote: Dict) -> Tuple[bool, List[str]]:
    """Check if this quote uses venues different from our target."""
    venues = extract_venues_from_quote(quote)
    is_fast = any(v in FAST_VENUES for v in venues)
    is_slow = any(v in SLOW_VENUES for v in venues)
    return (is_fast or is_slow), venues


class XStockOracleLagStrategy:
    """
    Cross-Venue Oracle Lag Arbitrage Strategy.

    Detects price discrepancies between Pyth Oracle and DEX prices for xStocks tokens,
    then executes atomic cross-venue arbitrage between slow AMM pools (Raydium/Orca)
    and fast CLOB markets (Phoenix/OpenBook).

    The strategy only executes if the round-trip spread covers:
      - 0.6% total swap fees (0.3% entry + 0.3% exit)
      - 0.002 SOL minimum profit
      - Jito tip (variable)
    """

    def __init__(self, session, cfg, keypair, optimal_trade_sizer, tx_builder, execution_router, ata_cache=None, data_aggregator=None):
        self.session = session
        self.cfg = cfg
        self.keypair = keypair
        self.optimal_trade_sizer = optimal_trade_sizer
        self.tx_builder = tx_builder
        self.execution_router = execution_router
        self.ata_cache = ata_cache
        self.data_aggregator = data_aggregator

        # Jupiter client for smart routing
        self.jupiter_client = JupiterClient(session=session)

        # Pyth client for price feeds
        self.pyth_client = get_pyth_client()

        # ─── Strategy type ──────────────────────────────────────────────────
        self.strategy_type = getattr(cfg, 'XSTOCK_STRATEGY_TYPE', 'CROSS_VENUE')

        # ─── Thresholds ─────────────────────────────────────────────────────
        # Base threshold: 0.75% — higher than 0.6% round-trip fees
        configured_lag_pct = getattr(cfg, 'ORACLE_LAG_THRESHOLD_PCT', 0.75)
        self.lag_threshold_pct = Decimal(str(configured_lag_pct))

        # Minimum profit: 0.002 SOL to cover gas + Jito tip + keep positive EV
        configured_min_profit = getattr(cfg, 'ORACLE_LAG_MIN_PROFIT_SOL', 0.002)
        wallet_balance_sol = getattr(cfg, 'WALLET_SOL_BALANCE', 0.017)
        if wallet_balance_sol < 1.0:
            self.min_profit_threshold = Decimal('0.002')
            logger.info(f"💰 Micro-profit mode: balance={wallet_balance_sol} SOL < 1 SOL, threshold=0.002 SOL")
        else:
            self.min_profit_threshold = Decimal(str(configured_min_profit))

        # Max price impact: 0.3% — prevents slippage from eating all profit
        self.max_price_impact_pct = float(getattr(cfg, 'MAX_PRICE_IMPACT_PCT', 0.3))

        # Phoenix orderbook integration toggle
        self.use_phoenix = getattr(cfg, 'XSTOCK_USE_PHOENIX', False)

        # ─── Monday Open Gap ────────────────────────────────────────────────
        # During Monday open, reduce threshold to 0.3% (volatility covers fees)
        self.monday_open_reduced_threshold = Decimal('0.3')

        # Cooldown tracking to prevent spam
        self.last_execution: Dict[str, datetime] = {}
        self.cooldown_seconds = 60

        # Lag monitoring
        self.lag_stats: Dict[str, List[float]] = {}

        # Stats
        self.total_opportunities_found = 0
        self.total_cross_venue_opps = 0
        self.total_executed = 0

        logger.info("🎯 xStocks Cross-Venue Oracle Lag Strategy initialized")
        logger.info(f"   Strategy type: {self.strategy_type}")
        logger.info(f"   Min profit: {self.min_profit_threshold} SOL")
        logger.info(f"   Lag threshold: {self.lag_threshold_pct}%")
        logger.info(f"   Max price impact: {self.max_price_impact_pct}%")
        logger.info(f"   Use Phoenix: {self.use_phoenix}")
        logger.info(f"   Active pairs: {len(ACTIVE_XSTOCKS)}")
        logger.info(f"   Crypto-proxy pairs: {sorted(CRYPTO_PROXY_TICKERS)}")

    async def process_swap_event(self, event_data: Dict[str, Any]) -> None:
        """Process Helius webhook SWAP event for xStocks tokens."""
        try:
            token_mint = self._extract_token_mint_from_event(event_data)
            if not token_mint:
                return

            ticker = self._get_ticker_from_mint(token_mint)
            if not ticker:
                return

            pair_info = get_xstock_info(ticker)
            if not pair_info:
                return

            # Skip illiquid proxies
            if ticker in ["IBITx", "SLVx"]:
                return

            # Market hours check (skip for crypto-proxy — trade 24/7)
            category = pair_info.get("category", "")
            if category != "crypto_proxy" and not is_market_open():
                return

            # Check cooldown
            if self._is_on_cooldown(ticker):
                return

            # Get oracle price
            oracle_price = self.pyth_client.get_current_price(ticker)
            if not oracle_price:
                return

            # Get cross-venue quotes from Jupiter
            result = await self._evaluate_cross_venue_opportunity(ticker, oracle_price)
            if result:
                self.total_opportunities_found += 1
                await self._execute_cross_venue_arbitrage(ticker, oracle_price, result)

        except Exception as e:
            logger.error(f"Error processing xStock swap event: {e}")

    async def _evaluate_cross_venue_opportunity(
        self, ticker: str, oracle_price: float
    ) -> Optional[Dict]:
        """
        Evaluate cross-venue arbitrage opportunity for a ticker.

        Steps:
          1. Get Jupiter quote: USDC → xStock (buy side, all venues)
          2. Chain: use buy output → quote xStock → USDC (sell side, all venues)
          3. Check if the two legs use DIFFERENT venues (cross-venue edge)
          4. Calculate actual round-trip USDC return vs input
          5. Check if spread covers fees + minimum profit

        Returns:
            Dict with opportunity data or None
        """
        pair_info = get_xstock_info(ticker)
        if not pair_info or not pair_info.get("mint"):
            return None

        token_mint = str(pair_info["mint"])
        usdc_mint_str = str(USDC_MINT)

        # ── Priority pairs filter ───────────────────────────────────────────
        if not is_monday_open_window() and ticker not in CRYPTO_PROXY_TICKERS:
            logger.debug(f"🔍 {ticker} non-priority, scanning with higher threshold")

        # ── Step 1: Get buy quote (USDC → xStock) ──────────────────────────
        # Use a small fixed amount for price discovery
        price_discovery_amount = 100_000  # 0.1 USDC lamports (6 decimals)
        buy_quote = await self._get_jupiter_quote(
            usdc_mint_str, token_mint, price_discovery_amount,
            only_direct_routes=False
        )
        if not buy_quote or "error" in buy_quote:
            return None

        # Extract actual xStock output from buy quote
        out_amount_xstock = int(buy_quote.get("outAmount", 0))
        if out_amount_xstock <= 0:
            return None

        # ── Step 2: Chain — use buy output as sell input ───────────────────
        # ExactIn: swap all xStock back to USDC to capture profit in native asset
        sell_quote = await self._get_jupiter_quote(
            token_mint, usdc_mint_str, out_amount_xstock,
            only_direct_routes=False,
        )
        if not sell_quote or "error" in sell_quote:
            return None

        # Extract actual USDC return from sell quote
        out_amount_usdc = int(sell_quote.get("outAmount", 0))
        if out_amount_usdc <= 0:
            return None

        # ── Step 3: Extract venue information ──────────────────────────────
        buy_venues = extract_venues_from_quote(buy_quote)
        sell_venues = extract_venues_from_quote(sell_quote)

        logger.debug(
            f"🔀 {ticker} | Buy venues: {buy_venues or ['None']} | "
            f"Sell venues: {sell_venues or ['None']} | "
            f"In: {price_discovery_amount} USDC → Out: {out_amount_usdc} USDC"
        )

        # ── Step 4: Calculate actual round-trip spread ──────────────────────
        # Direct comparison: USDC in vs USDC out (same unit!)
        round_trip_pct = ((out_amount_usdc - price_discovery_amount) / price_discovery_amount) * 100

        # Check if this is a true cross-venue opportunity
        is_cross_venue = (
            buy_venues and sell_venues
            and (set(buy_venues) & SLOW_VENUES or set(sell_venues) & SLOW_VENUES)
            and (set(buy_venues) & FAST_VENUES or set(sell_venues) & FAST_VENUES)
        )

        # DEX fee overhead: 0.6% (0.3% entry + 0.3% exit)
        fee_overhead_pct = 0.6
        effective_spread = round_trip_pct - fee_overhead_pct

        # Determine threshold (lower during Monday Open Gap)
        current_threshold = (
            self.monday_open_reduced_threshold
            if is_monday_open_window()
            else self.lag_threshold_pct
        )

        # ── Log the opportunity ─────────────────────────────────────────────
        if is_cross_venue:
            self.total_cross_venue_opps += 1
            logger.info(
                f"🔄 {ticker} | Cross-Venue: {buy_venues}→{sell_venues} | "
                f"USDC {price_discovery_amount} → {out_amount_usdc} | "
                f"Round-trip: {round_trip_pct:.2f}% | Net: {effective_spread:.2f}% | "
                f"Oracle: ${oracle_price:.4f}"
            )
        else:
            logger.debug(
                f"📊 {ticker} | Same-venue: {buy_venues}→{sell_venues} | "
                f"Round-trip: {round_trip_pct:.2f}% (cross-venue preferred)"
            )

        # ── Step 5: Check if spread is sufficient ───────────────────────────
        if effective_spread < float(current_threshold) and not is_cross_venue:
            logger.debug(
                f"📉 {ticker} | Spread {effective_spread:.2f}% < "
                f"threshold {current_threshold}% (or not cross-venue)"
            )
            return None

        # ── Calculate optimal trade size ─────────────────────────────────────
        trade_amount = await self._calculate_trade_size(
            ticker, token_mint, effective_spread, oracle_price
        )
        if trade_amount <= 0:
            return None

        # ── Estimate profit ──────────────────────────────────────────────────
        expected_profit_sol = self._estimate_profit_sol(trade_amount, effective_spread)
        if expected_profit_sol < float(self.min_profit_threshold):
            logger.debug(
                f"💰 {ticker} | Expected profit {expected_profit_sol:.6f} SOL < "
                f"threshold {self.min_profit_threshold} SOL"
            )
            return None

        # Compute implied prices for logging (same unit: USDC per xStock)
        buy_price = price_discovery_amount / out_amount_xstock if out_amount_xstock > 0 else 0.0
        sell_price = out_amount_usdc / out_amount_xstock if out_amount_xstock > 0 else 0.0

        return {
            "ticker": ticker,
            "token_mint": token_mint,
            "buy_quote": buy_quote,
            "sell_quote": sell_quote,
            "buy_venues": buy_venues,
            "sell_venues": sell_venues,
            "is_cross_venue": is_cross_venue,
            "round_trip_pct": round_trip_pct,
            "effective_spread": effective_spread,
            "oracle_price": oracle_price,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "trade_amount_lamports": trade_amount,
            "expected_profit_sol": expected_profit_sol,
            "current_threshold": float(current_threshold),
            "is_monday_open": is_monday_open_window(),
        }

    async def _get_jupiter_quote(
        self, input_mint: str, output_mint: str, amount: int,
        only_direct_routes: bool = False,
    ) -> Optional[Dict]:
        """Get Jupiter quote with smart routing (Iris).

        MTU Safety: slippageBps kept ≥ 30 to avoid QuoteNotFound errors on volatile pairs.
        """
        try:
            quote = await self.jupiter_client.get_quote(
                input_mint=input_mint,
                output_mint=output_mint,
                amount=int(amount),  # Task 16: strict int→string (safe int cast)
                slippage_bps=max(30, 100),  # min 30 bps, default 100
                only_direct_routes=only_direct_routes,
            )
            return quote
        except Exception as e:
            logger.debug(f"Jupiter quote error ({input_mint[:8]}→{output_mint[:8]}): {e}")
            return None

    async def _calculate_trade_size(
        self, ticker: str, token_mint: str, effective_spread: float, oracle_price: float
    ) -> int:
        """Calculate optimal trade size with slippage protection.

        Conservative sizing for xStocks with thin liquidity:
        - Base: 10 USDC for micro-capital (0.017 SOL wallet)
        - Scale up for larger spreads, but cap at 50 USDC
        - Apply price impact guard: impact must not exceed spread/2
        """
        # Start with conservative base for micro-capital
        base_trade_usdc = Decimal('10_000_000')  # 10 USDC in lamports

        # Scale with spread: larger spread = larger opportunity
        spread_factor = Decimal(str(min(effective_spread / 0.6, 3.0)))  # max 3x
        trade_size = int(base_trade_usdc * spread_factor)

        # Cap at 50 USDC for thin xStock liquidity
        max_trade = 50_000_000  # 50 USDC
        trade_size = min(trade_size, max_trade)

        # Safety: halve for Token-2022 (transfer fees)
        pair_info = get_xstock_info(ticker)
        if pair_info and pair_info.get("program") == "Token-2022":
            trade_size = trade_size // 2
            logger.debug(f"🛡️ Token-2022 safety: reduced {ticker} size to {trade_size} lamports")

        return trade_size

    def _estimate_profit_sol(self, trade_amount_lamports: int, effective_spread_pct: float) -> float:
        """Estimate profit in SOL for a given trade size and spread."""
        if effective_spread_pct <= 0:
            return 0.0

        # Convert trade amount from USDC lamports to SOL equivalent
        trade_usdc = trade_amount_lamports / 1_000_000
        # Rough SOL price assumption: $150/SOL
        sol_price = 150.0
        profit_usdc = trade_usdc * (effective_spread_pct / 100.0)
        profit_sol = profit_usdc / sol_price
        return profit_sol

    async def _execute_cross_venue_arbitrage(
        self, ticker: str, oracle_price: float, opportunity: Dict
    ) -> None:
        """Execute cross-venue arbitrage via flashloan + Jito bundle."""
        try:
            ticker_name = opportunity["ticker"]
            token_mint = opportunity["token_mint"]
            trade_amount = opportunity["trade_amount_lamports"]
            expected_profit = opportunity["expected_profit_sol"]
            buy_venues = opportunity.get("buy_venues", [])
            sell_venues = opportunity.get("sell_venues", [])
            effective_spread = opportunity["effective_spread"]

            logger.info(
                f"🚀 {ticker_name} | Cross-Venue: {buy_venues}→{sell_venues} | "
                f"Size: {trade_amount} lamports | "
                f"Expected profit: {expected_profit:.6f} SOL | "
                f"Spread: {effective_spread:.2f}%"
            )

            # ── Get real-time quotes with actual trade size ─────────────────
            usdc_mint_str = str(USDC_MINT)
            buy_quote = await self._get_jupiter_quote(
                usdc_mint_str, token_mint, trade_amount,
                only_direct_routes=False
            )
            if not buy_quote or "error" in buy_quote:
                logger.warning(f"❌ {ticker_name} buy quote failed at execution time")
                return

            # Get the actual expected out-amount from the buy quote
            actual_out = int(buy_quote.get("outAmount", 0))
            if actual_out <= 0:
                logger.warning(f"❌ {ticker_name} buy quote zero out amount")
                return

            # ExactIn: swap all xStock back to USDC
            sell_quote = await self._get_jupiter_quote(
                token_mint, usdc_mint_str, actual_out,
                only_direct_routes=False,
            )
            if not sell_quote or "error" in sell_quote:
                logger.warning(f"❌ {ticker_name} sell quote failed at execution time")
                return

            # ── Price Impact Filter (Fix 76): abort if total impact > spread/2 ──────
            # Extract priceImpactPct from both quotes (Jupiter returns "0.5%" or "0.5")
            try:
                buy_impact_str = buy_quote.get("priceImpactPct", "0").replace("%", "")
                sell_impact_str = sell_quote.get("priceImpactPct", "0").replace("%", "")
                buy_impact = float(buy_impact_str) if buy_impact_str else 0.0
                sell_impact = float(sell_impact_str) if sell_impact_str else 0.0
                total_impact = buy_impact + sell_impact
                if total_impact > (effective_spread / 2.0):
                    logger.warning(
                        f"🚫 {ticker_name} trade aborted: Total price impact {total_impact:.3f}% "
                        f"is too high compared to effective spread {effective_spread:.3f}%"
                    )
                    return
            except Exception as impact_err:
                logger.debug(f"Price impact filter parse error (non-fatal): {impact_err}")

            # ── ExactIn Safety: Validate debt coverage via otherAmountThreshold ─────
            worst_case_out = int(sell_quote.get("otherAmountThreshold", sell_quote.get("outAmount", 0)))
            if worst_case_out < trade_amount:
                logger.warning(
                    f"🚫 {ticker_name} trade cancelled: worst-case out {worst_case_out} < debt {trade_amount} "
                    f"(slippage risk)"
                )
                return

            actual_return = int(sell_quote.get("outAmount", 0))
            actual_profit_lamports = actual_return - trade_amount  # USDC lamports (6 decimals)
            actual_profit_usdc = actual_profit_lamports / 1_000_000   # 6 decimals for USDC
            sol_price = float(self.pyth_client.get_current_price("SOL") or 150.0)
            actual_profit_sol = actual_profit_usdc / sol_price  # Convert USDC profit → SOL equivalent

            if actual_profit_sol < float(self.min_profit_threshold):
                logger.warning(
                    f"💰 {ticker_name} | Actual profit {actual_profit_sol:.6f} SOL < "
                    f"threshold {self.min_profit_threshold} SOL — skipping"
                )
                return

            # ── Build and execute transaction ──────────────────────────────
            from arb_bot import MARGINFI_BANKS

            usdc_bank_info = MARGINFI_BANKS.get(str(USDC_MINT), {})
            if not usdc_bank_info:
                logger.error("Missing USDC bank info for xStocks flashloan")
                return

            # Build the opportunity dict for the execution router
            execution_opportunity = {
                "strategy": "xstock_oracle_lag",
                "ticker": ticker_name,
                "token_mint": token_mint,
                "direction": "BUY_LOW_SELL_HIGH",
                "oracle_price": float(oracle_price),
                "buy_price": float(opportunity["buy_price"]),
                "sell_price": float(opportunity["sell_price"]),
                "effective_spread": float(effective_spread),
                "expected_profit_sol": float(actual_profit_sol),
                "optimal_size_lamports": float(trade_amount),
                "quote": {
                    "circular_quote_out": actual_return,
                    "risk_out": trade_amount,
                    "step1": buy_quote,
                    "step2": sell_quote,
                    "buy_venues": buy_venues,
                    "sell_venues": sell_venues,
                    "is_cross_venue": opportunity.get("is_cross_venue", False),
                },
                "timestamp": datetime.now().isoformat(),
            }

            # ── Task 22: Webhook-Driven Paper Trading Interceptor ───────────────
            if self.cfg and getattr(self.cfg, 'PAPER_TRADING_ONLY', False):
                logger.info(f"🧪 [PAPER MODE] Simulation passed! Estimated Profit: {actual_profit_sol:.6f} SOL. Skipping real Jito submission.")
                
                if self.data_aggregator:
                    paper_trade_record = {
                        "trade_id": f"paper_{int(time.time())}",
                        "route": f"{ticker_name} Oracle Lag",
                        "token_in": usdc_mint_str,
                        "token_out": token_mint,
                        "amount": float(trade_amount) / 1e6,
                        "actual_profit": float(actual_profit_sol),
                        "balance_after": shared_state.stats.get("virtual_balance", 0.0) + float(actual_profit_sol),
                        "dex_pair": f"{ticker_name}/USDC",
                        "confidence": 1.0
                    }
                    await shared_state.data_aggregator.log_paper_trade(paper_trade_record)
                
                async with shared_state.stats_lock:
                    shared_state.stats["virtual_balance"] += float(actual_profit_sol)
                    shared_state.stats["trades"] += 1
                    
                return

            # Submit to execution router
            result = await self.execution_router.execute_arbitrage_opportunity(execution_opportunity)
            success = result.get("status") == "success"

            if success:
                self.total_executed += 1
                self.last_execution[ticker_name] = datetime.now()
                logger.info(
                    f"✅ {ticker_name} cross-venue arbitrage executed | "
                    f"Profit: {actual_profit_sol:.6f} SOL | "
                    f"Total executed: {self.total_executed}"
                )
            else:
                logger.warning(f"❌ {ticker_name} arbitrage execution failed: {result.get('message', 'unknown')}")

        except Exception as e:
            logger.error(f"Error executing {ticker} cross-venue arbitrage: {e}")

    async def periodic_lag_scan(self) -> None:
        """
        Periodic scan for cross-venue opportunities.

        Scanning strategy:
          - High priority (crypto-proxy): every 10 seconds
          - Medium priority (magnificent seven): every 30 seconds
          - Low priority (ETF/index): every 60 seconds
        Also refreshes wallet balance for dynamic threshold adjustment.
        """
        scan_intervals = {
            "high": 10,    # Crypto-proxy: MSTRx, COINx, MARAx, RIOTx
            "medium": 30,  # Magnificent seven: NVDAx, TSLAx, etc.
            "low": 60,     # ETF/index: SPYx, QQQx, GLDx
        }
        last_balance_check = 0.0
        last_cleanup = 0.0

        while True:
            try:
                now = time.time()

                # Periodic cleanup of blacklisted accounts (every 10 min)
                if now - last_cleanup > 600:
                    last_cleanup = now
                    self._cleanup_blacklisted_accounts()

                # Refresh wallet balance every 5 min
                if now - last_balance_check > 300:
                    last_balance_check = now
                    await self._refresh_wallet_balance()

                # ── Check crypto-proxy pairs first (highest edge) ───────────
                for ticker in sorted(CRYPTO_PROXY_TICKERS):
                    if self._is_on_cooldown(ticker):
                        continue
                    pair_info = get_xstock_info(ticker)
                    if not pair_info or not pair_info.get("mint"):
                        continue
                    oracle_price = self.pyth_client.get_current_price(ticker)
                    if not oracle_price:
                        continue
                    result = await self._evaluate_cross_venue_opportunity(ticker, oracle_price)
                    if result:
                        self.total_opportunities_found += 1
                        await self._execute_cross_venue_arbitrage(ticker, oracle_price, result)

                # ── All other active xStock pairs ───────────────────────────
                for ticker in XSTOCK_PRIORITY_ORDER:
                    if ticker in CRYPTO_PROXY_TICKERS:
                        continue  # Already scanned above
                    if self._is_on_cooldown(ticker):
                        continue

                    pair_info = get_xstock_info(ticker)
                    if not pair_info or not pair_info.get("mint"):
                        continue

                    category = pair_info.get("category", "")
                    # Skip non-crypto assets outside market hours
                    if category != "crypto_proxy" and not is_market_open():
                        continue

                    # Determine scan frequency
                    freq = pair_info.get("scan_frequency", "low")
                    interval = scan_intervals.get(freq, 30)
                    # Check if this ticker was scanned recently
                    last_scan_key = f"scan_{ticker}"
                    last_scan = getattr(self, last_scan_key, 0)
                    if now - last_scan < interval:
                        continue
                    setattr(self, last_scan_key, now)

                    oracle_price = self.pyth_client.get_current_price(ticker)
                    if not oracle_price:
                        continue

                    result = await self._evaluate_cross_venue_opportunity(ticker, oracle_price)
                    if result:
                        self.total_opportunities_found += 1
                        await self._execute_cross_venue_arbitrage(ticker, oracle_price, result)

            except Exception as e:
                logger.error(f"Error in periodic scan: {e}")

            await asyncio.sleep(5)  # Main loop tick: 5 seconds

    async def _refresh_wallet_balance(self):
        """Refresh wallet balance for dynamic threshold adjustment."""
        try:
            if not hasattr(self.cfg, 'MARGINFI_ACCOUNT_PUBKEY') or not self.cfg.MARGINFI_ACCOUNT_PUBKEY:
                return

            rpc_url = getattr(self.cfg, 'WSS_ENDPOINTS', ["https://api.mainnet-beta.solana.com"])[0]
            rpc_url = rpc_url.replace("wss://", "https://").replace("ws://", "http://")

            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getBalance",
                "params": [self.cfg.MARGINFI_ACCOUNT_PUBKEY, {"commitment": "confirmed"}],
            }
            timeout = aiohttp.ClientTimeout(total=3.0)
            async with self.session.post(rpc_url, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    sol_balance = float(data.get("result", {}).get("value", 0)) / 1e9

                    old_threshold = float(self.min_profit_threshold)
                    configured_min = getattr(self.cfg, 'ORACLE_LAG_MIN_PROFIT_SOL', 0.002)
                    if sol_balance < 1.0:
                        self.min_profit_threshold = Decimal('0.002')
                    else:
                        self.min_profit_threshold = Decimal(str(configured_min))

                    if float(self.min_profit_threshold) != old_threshold:
                        logger.info(
                            f"💰 Balance={sol_balance:.4f} SOL → "
                            f"min_profit_threshold={self.min_profit_threshold} SOL"
                        )
        except Exception as e:
            logger.debug(f"Balance refresh failed: {e}")

    def _extract_token_mint_from_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """Extract xStock token mint from Helius webhook event."""
        try:
            accounts = event_data.get("accountData", [])
            for account in accounts:
                mint = account.get("account", {}).get("mint")
                if mint and str(mint).startswith("Xs"):
                    return str(mint)
            return None
        except Exception as e:
            logger.error(f"Error extracting mint from event: {e}")
            return None

    def _get_ticker_from_mint(self, mint: str) -> Optional[str]:
        """Get ticker symbol from mint address."""
        for ticker, info in ACTIVE_XSTOCKS.items():
            mint_val = info.get("mint")
            if mint_val and str(mint_val) == mint:
                return ticker
        return None

    def _cleanup_blacklisted_accounts(self) -> None:
        """Clean up blacklisted accounts from dust_sweeper (if available)."""
        try:
            from .dust_sweeper import dust_sweeper
            if dust_sweeper and hasattr(dust_sweeper, '_blacklist'):
                # Clear old entries from blacklist (older than 1 hour)
                # This is a soft cleanup - blacklist is for preventing repeated failed closes
                pass
        except Exception:
            pass

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
            "strategy_type": self.strategy_type,
            "min_profit_threshold": float(self.min_profit_threshold),
            "lag_threshold_pct": float(self.lag_threshold_pct),
            "total_opportunities_found": self.total_opportunities_found,
            "total_cross_venue_opps": self.total_cross_venue_opps,
            "total_executed": self.total_executed,
            "lag_stats": {},
        }

        for ticker in ACTIVE_XSTOCKS.keys():
            if ticker in self.lag_stats and self.lag_stats[ticker]:
                lags = self.lag_stats[ticker]
                report["lag_stats"][ticker] = {
                    "average_lag_pct": sum(lags) / len(lags),
                    "max_lag_pct": max(lags),
                    "min_lag_pct": min(lags),
                    "samples": len(lags),
                }

        return report


# Global strategy instance
_xstock_strategy = None


def get_xstock_strategy() -> Optional[XStockOracleLagStrategy]:
    """Get global xStock strategy instance."""
    return _xstock_strategy


def init_xstock_strategy(session, cfg, optimal_trade_sizer, tx_builder, execution_router):
    """Initialize global xStock strategy instance."""
    global _xstock_strategy
    _xstock_strategy = XStockOracleLagStrategy(
        session, cfg, optimal_trade_sizer, tx_builder, execution_router
    )
    return _xstock_strategy
