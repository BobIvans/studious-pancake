"""
CEX-DEX Lead-Lag Signal Oracle
Uses Binance WebSocket as ultra-fast oracle to front-run Solana DEXes.
Statistical arbitrage exploiting latency differences.
"""

import asyncio
import json
import logging
import socket
from typing import Dict, List, Optional, Callable, Any
from decimal import Decimal
import aiohttp
from aiohttp.resolver import AbstractResolver

logger = logging.getLogger(__name__)

class CexDexSignal:
    """CEX-DEX arbitrage signal."""
    def __init__(self, asset: str, cex_price: Decimal, dex_price: Decimal,
                 price_diff_pct: float, direction: str, confidence: float,
                 timestamp: float, volume_spike: bool = False):
        self.asset = asset
        self.cex_price = cex_price
        self.dex_price = dex_price
        self.price_diff_pct = price_diff_pct
        self.direction = direction  # 'buy_dex' or 'sell_dex'
        self.confidence = confidence
        self.timestamp = timestamp
        self.volume_spike = volume_spike

class CexDexOracle:
    """Monitors Binance WebSocket for lead-lag signals vs Solana DEXes."""

    def __init__(self, binance_ws_url: str = "wss://stream.binance.com:9443/ws",
                 pool_state_manager = None,
                 session = None):
        self.binance_ws_url = binance_ws_url
        self.pool_state_manager = pool_state_manager
        self.cex_prices: Dict[str, Dict[str, Any]] = {}  # asset -> price data
        self.signal_callbacks: List[Callable[[CexDexSignal], None]] = []
        self._stop_event = asyncio.Event()
        self.running = False
        self.price_history: Dict[str, List[Dict]] = {}  # asset -> price history
        self.max_history = 10  # Keep last 10 prices per asset
        self.session = session
        self._session_owned = session is None

    def register_signal_callback(self, callback: Callable[[CexDexSignal], None]):
        """Register callback for arbitrage signals."""
        self.signal_callbacks.append(callback)

    async def start(self):
        """Start Binance WebSocket monitoring."""
        self.running = True
        asyncio.create_task(self._binance_stream())

    async def stop(self):
        """Stop monitoring."""
        self.running = False
        self._stop_event.set()
        if self._session_owned and self.session and not self.session.closed:
            await self.session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create session with DoH resolver."""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(ttl_dns_cache=300)
            self.session = aiohttp.ClientSession(connector=connector)
            self._session_owned = True
        return self.session

    async def _binance_stream(self):
        """Connect to Binance WebSocket for real-time prices."""
        try:
            while not self._stop_event.is_set():
                try:
                    session = await self._get_session()
                    async with session.ws_connect(self.binance_ws_url) as websocket:
                        logger.info("Connected to Binance WebSocket for CEX-DEX arbitrage")

                        # Subscribe to book ticker streams for SOL and BTC
                        subscription_msg = {
                            "method": "SUBSCRIBE",
                            "params": [
                                "solusdt@bookTicker",
                                "btcusdt@bookTicker",
                                "ethusdt@bookTicker"
                            ],
                            "id": 1
                        }
                        await websocket.send_str(json.dumps(subscription_msg))

                        async for message in websocket:
                            if self._stop_event.is_set():
                                break

                            try:
                                if message.type == aiohttp.WSMsgType.TEXT:
                                    data = json.loads(message.data)
                                    await self._process_binance_update(data)
                            except json.JSONDecodeError:
                                continue

                except Exception as e:
                    logger.error(f"Binance stream error: {e}")
                    if not self._stop_event.is_set():
                        await asyncio.sleep(5)  # Reconnect
                        asyncio.create_task(self._binance_stream())
        except asyncio.CancelledError:
            logger.info("Binance WebSocket stream gracefully cancelled")
        except Exception as e:
            logger.error(f"Binance stream error: {e}")

    async def _process_binance_update(self, data: Dict[str, Any]):
        """Process Binance book ticker update."""
        try:
            if "stream" not in data or "data" not in data:
                return

            stream = data["stream"]
            ticker_data = data["data"]

            if not stream.endswith("@bookTicker"):
                return

            # Extract symbol (SOL/USDT -> SOL)
            symbol = stream.split("@")[0].replace("usdt", "").upper()
            if symbol not in ["SOL", "BTC", "ETH"]:
                return

            # Get best bid/ask prices
            best_bid = Decimal(str(ticker_data.get("b", "0")))
            best_ask = Decimal(str(ticker_data.get("a", "0")))
            volume = Decimal(str(ticker_data.get("v", "0")))  # Volume

            if best_bid <= 0 or best_ask <= 0:
                return

            # Use mid price for comparison
            mid_price = (best_bid + best_ask) / Decimal('2')
            timestamp = asyncio.get_running_loop().time()

            # Store price data
            price_data = {
                "price": mid_price,
                "bid": best_bid,
                "ask": best_ask,
                "volume": volume,
                "timestamp": timestamp
            }

            self.cex_prices[symbol] = price_data

            # Maintain price history for velocity calculation
            if symbol not in self.price_history:
                self.price_history[symbol] = []
            self.price_history[symbol].append(price_data)
            self.price_history[symbol] = self.price_history[symbol][-self.max_history:]

            # Check for lead-lag signals
            await self._check_lead_lag_signal(symbol, price_data)

        except Exception as e:
            logger.debug(f"Binance update processing error: {e}")

    async def _check_lead_lag_signal(self, asset: str, cex_price_data: Dict[str, Any]):
        """Check for CEX-DEX price discrepancies."""
        if not self.pool_state_manager:
            return

        try:
            # Get DEX price from our in-memory state
            dex_price = await self._get_dex_price(asset)
            if not dex_price:
                return

            cex_price = cex_price_data["price"]

            # Calculate price difference
            price_diff_pct = float((cex_price - dex_price) / dex_price)

            # Check for significant discrepancy (>0.3%)
            if abs(price_diff_pct) > 0.003:
                # Check for rapid price movement (<500ms significant change)
                rapid_movement = self._check_rapid_movement(asset, cex_price_data)

                # Determine direction
                if price_diff_pct > 0:
                    direction = "buy_dex"  # CEX higher, buy on DEX
                else:
                    direction = "sell_dex"  # DEX higher, sell on DEX

                # Calculate confidence based on difference magnitude and volume
                confidence = min(abs(price_diff_pct) * 1000, 1.0)  # Scale to 0-1
                if rapid_movement:
                    confidence = min(confidence * 1.5, 1.0)  # Boost for rapid movement

                # Check for volume spike
                volume_spike = self._check_volume_spike(asset, cex_price_data)

                signal = CexDexSignal(
                    asset=asset,
                    cex_price=cex_price,
                    dex_price=dex_price,
                    price_diff_pct=price_diff_pct,
                    direction=direction,
                    confidence=confidence,
                    timestamp=cex_price_data["timestamp"],
                    volume_spike=volume_spike
                )

                logger.info(f"📊 CEX-DEX Lead-Lag: {asset} | CEX: ${cex_price} | DEX: ${dex_price} | "
                           f"Diff: {price_diff_pct:.2%} | Direction: {direction} | "
                           f"Rapid: {rapid_movement} | Volume Spike: {volume_spike}")

                # Trigger callbacks
                for callback in self.signal_callbacks:
                    try:
                        await callback(signal)
                    except Exception as e:
                        logger.error(f"CEX-DEX callback error: {e}")

        except Exception as e:
            logger.debug(f"Lead-lag signal check error: {e}")

    async def _get_dex_price(self, asset: str) -> Optional[Decimal]:
        """Get DEX price from pool state manager."""
        try:
            # Map asset to token mint
            token_mint_map = {
                "SOL": "So11111111111111111111111111111111111111112",
                "BTC": "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh",  # wBTC
                "ETH": "wETHv2ZvE6W2FuDvG8GXzLtjNfH5noTfYvKvvHgMj",     # wETH placeholder
            }

            token_mint = token_mint_map.get(asset)
            if not token_mint:
                return None

            # Find pools containing this token
            token_pools = self.pool_state_manager.get_pools_by_token(token_mint)
            if not token_pools:
                return None

            # Use largest liquidity pool
            best_pool = max(token_pools, key=lambda p: p.token_a_reserve + p.token_b_reserve)

            # Calculate price (assuming paired with USDC)
            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            if best_pool.token_a_mint == token_mint and best_pool.token_b_mint == usdc_mint:
                return best_pool.token_b_reserve / best_pool.token_a_reserve
            elif best_pool.token_a_mint == usdc_mint and best_pool.token_b_mint == token_mint:
                return best_pool.token_a_reserve / best_pool.token_b_reserve

        except Exception:
            pass
        return None

    def _check_rapid_movement(self, asset: str, current_price_data: Dict[str, Any]) -> bool:
        """Check if price moved rapidly (<500ms significant change)."""
        try:
            history = self.price_history.get(asset, [])
            if len(history) < 2:
                return False

            # Check last 2 prices
            current_price = current_price_data["price"]
            previous_price = history[-2]["price"]
            time_diff = current_price_data["timestamp"] - history[-2]["timestamp"]

            if time_diff > 0.5:  # >500ms
                return False

            price_change_pct = abs(current_price - previous_price) / previous_price
            return price_change_pct > 0.001  # >0.1% change in <500ms

        except Exception:
            return False

    def _check_volume_spike(self, asset: str, current_price_data: Dict[str, Any]) -> bool:
        """Check for unusual volume spike."""
        try:
            history = self.price_history.get(asset, [])
            if len(history) < 5:
                return False

            current_volume = current_price_data["volume"]
            avg_volume = sum(h["volume"] for h in history[:-1]) / len(history[:-1])

            return current_volume > avg_volume * 2  # 2x average volume

        except Exception:
            return False

    async def execute_lead_lag_arbitrage(self, signal: CexDexSignal,
                                        optimal_trade_size: Decimal,
                                        wallet_keypair, jito_executor,
                                        execution_router) -> bool:
        """Execute CEX-DEX arbitrage by structuring an ArbitrageOpportunity."""
        try:
            logger.info(f"🎯 Structuring CEX-DEX arbitrage: {signal.asset} | "
                       f"Direction: {signal.direction} | Size: {optimal_trade_size}")

            # Map asset to token mint
            token_mint_map = {
                "SOL": "So11111111111111111111111111111111111111112",
                "BTC": "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh",
                "ETH": "7vfCXTUXx5WJV5J7pEeidpXYEPp9UUnQv9YpGP6tpX73", # wETH
            }
            token_mint = token_mint_map.get(signal.asset)
            if not token_mint:
                return False

            # Structure the opportunity for the execution router
            # We reuse the standard MarginFi/Jupiter flow
            opportunity = {
                "strategy": "cex_dex_lead_lag",
                "asset": signal.asset,
                "token_mint": token_mint,
                "direction": "BUY" if signal.direction == "buy_dex" else "SELL",
                "optimal_size": float(optimal_trade_size),
                "expected_profit_pct": signal.price_diff_pct,
                "confidence": signal.confidence,
                "timestamp": signal.timestamp
            }

            # Route to the execution engine
            # The router will fetch quotes and build the transaction
            result = await execution_router.process_opportunity(opportunity)
            
            if result and result.get("status") == "success":
                logger.info(f"✅ CEX-DEX arbitrage submitted: {signal.asset}")
                return True
            
            return False

        except Exception as e:
            logger.error(f"CEX-DEX execution error: {e}")
            return False

    def get_cex_price(self, asset: str) -> Optional[Dict[str, Any]]:
        """Get current CEX price data for asset."""
        return self.cex_prices.get(asset)

    def get_price_history(self, asset: str) -> List[Dict[str, Any]]:
        """Get price history for asset."""
        return self.price_history.get(asset, [])