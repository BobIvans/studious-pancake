"""
Oracle WebSocket Streams - Pyth Hermes API Integration
Real-time price feeds from Pyth Network.
Triggers arbitrage when Oracle price deviates from AMM price by >0.25%.
Supports PriorityQueue for multiple simultaneous signals.
"""

import asyncio
import orjson
import logging
import time
import socket
from typing import Dict, List, Optional, Callable, Any
from decimal import Decimal

import aiohttp
from queue import PriorityQueue

logger = logging.getLogger(__name__)

# Pyth Price Feeds Registry
PYTH_FEEDS = {
}

# Priority order for multiple signals (highest profit first)
PRIORITY_ORDER = [

]

class OraclePrice:
    """Oracle price data point."""
    def __init__(self, token_symbol: str, price: Decimal, confidence: Decimal,
                 timestamp: float, source: str):
        self.token_symbol = token_symbol
        self.price = price
        self.confidence = confidence
        self.timestamp = timestamp
        self.source = source

class OracleStreams:
    """Real-time oracle price streaming via Pyth Hermes WebSocket."""

    def __init__(self, pyth_ws_url: str = "wss://hermes.pyth.network/ws",
                 chainlink_ws_url: Optional[str] = None,
                 pool_state_manager=None,
                 optimal_trade_sizer=None,
                 opportunity_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
                 session: Optional[aiohttp.ClientSession] = None):
        self.pyth_ws_url = pyth_ws_url
        self.chainlink_ws_url = chainlink_ws_url
        self.pool_state_manager = pool_state_manager
        self.optimal_trade_sizer = optimal_trade_sizer
        self.opportunity_callback = opportunity_callback
        self.oracle_prices: Dict[str, OraclePrice] = {}
        self.price_callbacks: List[Callable[[str, OraclePrice], None]] = []
        self.running = False
        self.session = session
        self._session_owned = session is None
        self.pyth_ws = None
        self.chainlink_ws = None

        # PriorityQueue for handling multiple simultaneous signals
        # Priority based on expected profit (lower number = higher priority)
        import itertools
        self.counter = itertools.count()
        self.signal_queue = PriorityQueue()
        self.signal_processor_task: Optional[asyncio.Task] = None

        # Track active signals to prevent duplicates
        self.active_signals: Dict[str, float] = {}

    def register_price_callback(self, callback: Callable[[str, OraclePrice], None]):
        """Register callback for price updates."""
        self.price_callbacks.append(callback)

    async def start(self):
        """Start oracle WebSocket streams and signal processor."""
        self.running = True

        asyncio.create_task(self._pyth_stream())

        # Start Chainlink stream if provided
        if self.chainlink_ws_url:
            asyncio.create_task(self._chainlink_stream())

        # Start signal processor for PriorityQueue handling
        self.signal_processor_task = asyncio.create_task(self._process_signal_queue())

    async def stop(self):
        """Stop all streams and signal processor."""
        self.running = False
        if self.signal_processor_task:
            self.signal_processor_task.cancel()
            try:
                await self.signal_processor_task
            except asyncio.CancelledError:
                pass
        if self.pyth_ws:
            await self.pyth_ws.close()
        if self.chainlink_ws:
            await self.chainlink_ws.close()
        if self._session_owned and self.session and not self.session.closed:
            await self.session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create session with DoH resolver."""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(ttl_dns_cache=300, family=socket.AF_INET)
            self.session = aiohttp.ClientSession(connector=connector)
            self._session_owned = True
        return self.session

    async def _pyth_stream(self):
        """Connect to Pyth Hermes WebSocket for real-time prices."""
        try:
            session = await self._get_session()
            async with session.ws_connect(self.pyth_ws_url) as websocket:
                self.pyth_ws = websocket
                logger.info(f"Connected to Pyth Hermes WebSocket: {self.pyth_ws_url}")

                feed_ids = list(PYTH_FEEDS.values())

                subscription_msg = {
                    "type": "subscribe",
                    "subscription_type": "price_feed_updates",
                    "price_feed_ids": feed_ids
                }
                await websocket.send_str(orjson.dumps(subscription_msg).decode())

                async for message in websocket:
                    if not self.running:
                        break

                    if message.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = orjson.loads(message.data)
                            await self._process_pyth_update(data)
                        except Exception:
                            continue

        except Exception as e:
            logger.error(f"Pyth stream error: {e}")
            if self.running:
                await asyncio.sleep(5)  # Reconnect delay
                asyncio.create_task(self._pyth_stream())

    async def _chainlink_stream(self):
        """Connect to Chainlink Data Streams WebSocket."""
        try:
            session = await self._get_session()
            async with session.ws_connect(self.chainlink_ws_url) as websocket:
                self.chainlink_ws = websocket
                logger.info(f"Connected to Chainlink WebSocket: {self.chainlink_ws_url}")

                # Chainlink subscription logic would go here
                # Similar structure to Pyth but with Chainlink-specific feeds
                subscription_msg = {
                    "jsonrpc": "2.0",
                    "method": "subscribe",
                    "params": ["price_feeds"]  # Placeholder
                }
                await websocket.send_str(orjson.dumps(subscription_msg).decode())

                async for message in websocket:
                    if not self.running:
                        break

                    if message.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = orjson.loads(message.data)
                            await self._process_chainlink_update(data)
                        except Exception:
                            continue

        except Exception as e:
            logger.error(f"Chainlink stream error: {e}")

    async def _process_pyth_update(self, data: Dict[str, Any]):
        """Process Pyth Hermes price update message."""
        try:
            # Hermes WebSocket format: {"type": "price_update", "price_feed": {...}}
            if data.get("type") != "price_feed_update" or "price_feed" not in data:
                return

            price_feed = data["price_feed"]
            feed_id = price_feed.get("id")

            # Find ticker by feed_id
            ticker = None
            for t, fid in PYTH_FEEDS.items():
                if fid == feed_id:
                    ticker = t
                    break

            if not ticker:
                return

            # Extract price data from Hermes format
            price_data = price_feed.get("price", {})
            raw_price = Decimal(str(price_data.get("price", 0)))
            expo = int(price_data.get("expo", 0))
            price = raw_price * (Decimal('10') ** expo)  # Apply exponent for actual price
            confidence = Decimal(str(price_data.get("confidence", 0))) * (Decimal('10') ** expo)
            
            # Latency Check
            publish_time = price_data.get("publish_time")
            now = time.time()
            if publish_time and (now - publish_time) > 1.0:
                logger.warning(f"⚠️ Pyth stale data for {ticker}: {now - publish_time:.2f}s old. Discarding.")
                return

            timestamp = publish_time or now

            if price <= 0:
                return

            oracle_price = OraclePrice(
                token_symbol=ticker,
                price=price,
                confidence=confidence,
                timestamp=timestamp,
                source="pyth_hermes"
            )

            self.oracle_prices[ticker] = oracle_price

            # Check for Oracle Lag arbitrage opportunity
            if opportunity:
                # Add to PriorityQueue with tie-breaker
                priority = PRIORITY_ORDER.index(ticker) if ticker in PRIORITY_ORDER else 99
                self.signal_queue.put((priority, next(self.counter), opportunity))
                
                # Trigger external opportunity callback if provided
                if self.opportunity_callback:
                    if asyncio.iscoroutinefunction(self.opportunity_callback):
                        await self.opportunity_callback(opportunity)
                    else:
                        self.opportunity_callback(opportunity)

            # Trigger callbacks for arbitrage evaluation
            for callback in self.price_callbacks:
                try:
                    await callback(ticker, oracle_price)
                except Exception as e:
                    logger.error(f"Oracle callback error: {e}")

            logger.debug(f"🐍 Pyth Hermes update: {ticker} = ${price} (confidence: {confidence})")

        except Exception as e:
            logger.debug(f"Pyth Hermes update processing error: {e}")

        """Check for Oracle Lag arbitrage opportunity."""
        try:
            # This would query AMM pools for current price and compare with oracle
            # For now, placeholder - would integrate with pool state manager
            # Return opportunity dict if profitable discrepancy found

            # Placeholder logic: simulate checking against AMM price
            amm_price = await self._get_amm_price(ticker)
            if not amm_price:
                return None

            price_diff_pct = abs(oracle_price.price - amm_price) / amm_price

            # Fix 4 (Pyth Confidence Interval): Skip signals that lie within the oracle's
            # confidence band — this is market noise, not arbitrage. Jupiter slippage alone
            # would eat the entire spread before it reaches 1.2× the confidence margin.
            confidence_pct = float(oracle_price.confidence) / float(oracle_price.price)
            if confidence_pct > price_diff_pct * 1.2:
                logger.debug(
                    f"🐍 Pyth noise skip {ticker}: confidence {confidence_pct:.4%} > "
                    f"1.2 × spread {price_diff_pct:.4%} — no real arbitrage signal"
                )
                return None

            if price_diff_pct > 0.0025:
                direction = "oracle_higher" if oracle_price.price > amm_price else "amm_higher"

                # Calculate expected profit (simplified)
                expected_profit_pct = price_diff_pct * 0.8  # Conservative capture rate

                return {
                    "ticker": ticker,
                    "oracle_price": oracle_price.price,
                    "amm_price": amm_price,
                    "price_diff_pct": price_diff_pct,
                    "direction": direction,
                    "expected_profit_pct": expected_profit_pct,
                    "timestamp": oracle_price.timestamp
                }

        except Exception as e:
            logger.debug(f"Oracle lag check error for {ticker}: {e}")

        return None

    async def _get_amm_price(self, ticker: str) -> Optional[Decimal]:
        """Get current AMM price for ticker using PoolStateManager."""
        if not self.pool_state_manager:
            return None
            
        try:
            # Query pool state for this ticker
            pool_state = self.pool_state_manager.get_pool_by_ticker(ticker)
            if pool_state:
                # Calculate price from reserves
                return pool_state.reserve_y / pool_state.reserve_x
        except Exception as e:
            logger.debug(f"Failed to get AMM price for {ticker}: {e}")
            
        return None

    async def _process_signal_queue(self):
        """Process PriorityQueue signals, executing highest profit opportunities first."""
        while self.running:
            try:
                # Get next highest priority signal (non-blocking)
                if not self.signal_queue.empty():
                    priority, _, opportunity = self.signal_queue.get_nowait()

                    ticker = opportunity["ticker"]

                    # Check if we recently processed this signal
                    now = time.time()
                    if ticker in self.active_signals:
                        if now - self.active_signals[ticker] < 5.0:  # 5 second cooldown
                            continue

                    self.active_signals[ticker] = now

                    # Execute arbitrage for this opportunity

                    # Clean old active signals
                    cutoff = now - 30.0
                    self.active_signals = {k: v for k, v in self.active_signals.items() if v > cutoff}

                await asyncio.sleep(0.1)  # Brief pause between checks

            except Exception as e:
                logger.error(f"Signal queue processing error: {e}")
                await asyncio.sleep(1)


    async def _process_chainlink_update(self, data: Dict[str, Any]):
        """Process Chainlink price update."""
        try:
            # Chainlink data structure processing
            # Similar to Pyth but with different field names
            logger.debug(f"Chainlink update: {data}")
            # Implementation would mirror Pyth processing

        except Exception as e:
            logger.debug(f"Chainlink update processing error: {e}")

    def get_oracle_price(self, token_symbol: str) -> Optional[OraclePrice]:
        """Get current oracle price for token."""
        return self.oracle_prices.get(token_symbol)

    def get_all_oracle_prices(self) -> Dict[str, OraclePrice]:
        """Get all current oracle prices."""
        return self.oracle_prices.copy()

    def get_price_age(self, token_symbol: str) -> Optional[float]:
        """Get how old the oracle price is in seconds."""
        price = self.oracle_prices.get(token_symbol)
        if price:
            return time.time() - price.timestamp
        return None

    async def check_oracle_vs_amm(self, token_symbol: str, amm_price: Decimal,
                                 threshold_pct: float = 0.0025) -> Optional[Dict[str, Any]]:
        """
        Check for oracle vs AMM price discrepancy.

        Args:
            token_symbol: Token symbol to check
            amm_price: Current AMM pool price
            threshold_pct: Minimum discrepancy threshold (0.25% default)

        Returns:
            Dict with discrepancy info if above threshold, None otherwise
        """
        oracle_price = self.get_oracle_price(token_symbol)
        if not oracle_price:
            return None

        price_diff_pct = abs(oracle_price.price - amm_price) / amm_price

        if price_diff_pct > threshold_pct:
            direction = "oracle_higher" if oracle_price.price > amm_price else "amm_higher"

            return {
                "token_symbol": token_symbol,
                "oracle_price": oracle_price.price,
                "amm_price": amm_price,
                "price_diff_pct": price_diff_pct,
                "direction": direction,
                "oracle_age_seconds": self.get_price_age(token_symbol),
                "trigger_threshold": threshold_pct
            }

        return None

    def calculate_optimal_trade_size(self, oracle_price: Decimal, amm_price: Decimal,
                                   reserve_x: Decimal, reserve_y: Decimal,
                                   fee_pct: float = 0.003) -> Optional[Decimal]:
        """
        Calculate Optimal Input Size for Oracle Lag arbitrage using mathematical formula.

        The optimal size makes the post-trade AMM price equal to the oracle price,
        maximizing profit while minimizing slippage.

        Args:
            oracle_price: Oracle price (target price)
            amm_price: Current AMM price
            reserve_x: Reserve of input token in pool
            reserve_y: Reserve of output token in pool
            fee_pct: Trading fee percentage (0.3% for most AMMs)

        Returns:
            Optimal input amount, or None if calculation fails
        """
        try:
            if amm_price <= 0 or oracle_price <= 0 or reserve_x <= 0 or reserve_y <= 0:
                return None

            # For CPMM (x * y = k): dx = (sqrt(k * p_o / p_a) - x) / (1 - fee)
            # Where p_o is oracle price, p_a is AMM price

            k = reserve_x * reserve_y
            fee_factor = 1 - fee_pct

            # Optimal input: solve for dx where final_price = oracle_price
            # dx = (sqrt(k * p_o / p_a) - x) / (1 - fee)
            sqrt_term = (k * oracle_price / amm_price).sqrt()
            dx = (sqrt_term - reserve_x) / fee_factor

            # Ensure positive and reasonable size
            if dx > 0 and dx < reserve_x * 0.1:  # Max 10% of pool
                return dx

        except Exception as e:
            logger.debug(f"Optimal size calculation error: {e}")

        return None