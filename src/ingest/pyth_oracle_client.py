"""
Pyth Oracle Client for Real-Time Price Feeds
Hermes WebSocket integration for price feeds with on-chain RPC fallback.
"""

import asyncio
import orjson
import logging
import socket
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import aiohttp
from src.config.addresses import PYTH_FEEDS, HERMES_WS_URL
from src.config.addresses import get_all_pyth_feed_ids
import random

logger = logging.getLogger(__name__)


class PythHermesClient:
    """
    Real-time Pyth price feed client using Hermes WebSocket.
    Maintains in-memory cache of latest prices for oracle lag detection.
    Falls back to Hermes REST API when WebSocket is unavailable.
    """

    def __init__(self, reconnect_interval: int = 5, session: Optional[aiohttp.ClientSession] = None,
                 rpc_url: str = ""):
        self.ws_url = HERMES_WS_URL
        self.reconnect_interval = reconnect_interval
        self.websocket = None
        self.running = False
        self.session = session
        self._session_owned = session is None
        self.rpc_url = rpc_url  # Fix 70: RPC URL for on-chain fallback

        # Price cache: ticker -> {"price": float, "timestamp": datetime, "confidence": float}
        self.price_cache: Dict[str, Dict[str, Any]] = {}

        # Feed ID to ticker mapping for reverse lookup
        self.feed_to_ticker = {v["feed_id"]: k for k, v in PYTH_FEEDS.items() if v.get("feed_id")}

        # Lag monitoring
        self.lag_stats: Dict[str, list] = {}

        # Task 58: Background main loop task
        self._main_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the WebSocket connection with Auto-Recovery."""
        self.running = True
        logger.info("🚀 Starting Pyth Hermes Client with Auto-Recovery...")
        self._main_task = asyncio.create_task(self._main_loop())

    async def stop(self):
        """Stop the client and cancel all loops."""
        self.running = False
        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except (asyncio.CancelledError, Exception):
                pass
        if self.websocket:
            await self.websocket.close()
        if self._session_owned and self.session and not self.session.closed:
            await self.session.close()
        logger.info("🛑 Pyth Hermes Client stopped")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create session with DoH resolver."""
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(ttl_dns_cache=300, family=socket.AF_INET)
            self.session = aiohttp.ClientSession(connector=connector)
            self._session_owned = True
        return self.session

    async def _main_loop(self):
        """Main loop with WebSocket connection, auto-recovery, and REST fallback."""
        reconnect_delay = float(self.reconnect_interval)
        fallback_task = None

        while self.running:
            try:
                session = await self._get_session()
                logger.info("Attempting Pyth Hermes WebSocket connection...")

                async with session.ws_connect(
                    self.ws_url, heartbeat=15.0, timeout=10.0, receive_timeout=30.0
                ) as websocket:
                    self.websocket = websocket
                    logger.info("✅ Pyth Hermes WebSocket connected!")

                    # Cancel REST fallback task if it was running
                    if fallback_task and not fallback_task.done():
                        fallback_task.cancel()
                        logger.info("🔌 Stopped Pyth Hermes REST fallback (WebSocket recovered)")
                        fallback_task = None

                    reconnect_delay = float(self.reconnect_interval)  # Reset delay

                    subscription = {
                        "type": "subscribe",
                        "subscription_type": "price_feed_updates",
                        "price_feed_ids": get_all_pyth_feed_ids()
                    }
                    await websocket.send_str(orjson.dumps(subscription).decode())

                    async for msg in websocket:
                        if not self.running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = orjson.loads(msg.data)
                            await self._process_message(data)

            except Exception as e:
                logger.error(f"Pyth WebSocket connection error: {e}")
                # Spawn REST fallback if not already running
                if not fallback_task or fallback_task.done():
                    logger.info("📡 Spawning Pyth Hermes REST fallback polling task...")
                    fallback_task = asyncio.create_task(self._run_onchain_fallback_loop())

                # Jitter + Exponential backoff (Anti Thundering Herd)
                jitter = random.uniform(0.8, 1.2)
                reconnect_delay = min(reconnect_delay * 1.5, 60.0)
                sleep_duration = reconnect_delay * jitter
                logger.info(f"Reconnecting Pyth WebSocket in {sleep_duration:.1f}s...")
                await asyncio.sleep(sleep_duration)

        if fallback_task and not fallback_task.done():
            fallback_task.cancel()

    async def _process_message(self, data: dict):
        """Process incoming price update message."""
        try:
            if data.get("type") == "price_feed_update":
                # Убираем префикс 0x для совпадения с локальным реестром
                raw_feed_id = data.get("price_feed_id") or data.get("price_feed", {}).get("id", "")
                feed_id = str(raw_feed_id).replace("0x", "")
                
                ticker = self.feed_to_ticker.get(feed_id)

                if not ticker:
                    return

                price_data = data.get("price_feed", {})
                price_info = price_data.get("price", {})
                price = price_info.get("price")
                confidence = price_info.get("confidence")
                publish_time = price_info.get("publish_time")
                status = price_info.get("status")
                expo = price_info.get("expo", 0)

                if status and status != "trading":
                    logger.debug(f"⏭️ Pyth feed {ticker} status={status} — not trading, skipping")
                    return

                if price and publish_time:
                    price_val = float(price)
                    conf_val = float(confidence) if confidence else 0.0
                    conf_usd = conf_val * (10 ** expo) if expo < 0 else conf_val

                    if price_val > 0 and (conf_usd / price_val) > 0.0015:
                        logger.warning(
                            f"🚫 Pyth feed {ticker} has unsafe confidence interval: "
                            f"conf={conf_usd:.4f}, price={price_val:.4f}, ratio={conf_usd/price_val:.2%} (> 0.15%). Skipping."
                        )
                        return

                    self.price_cache[ticker] = {
                        "price": price_val,
                        "timestamp": datetime.fromtimestamp(publish_time),
                        "confidence": conf_usd,
                        "status": status,
                    }

                    # Log lag for monitoring
                    now = datetime.now()
                    lag_seconds = (now - self.price_cache[ticker]["timestamp"]).total_seconds()

                    # Track lag stats for this ticker
                    if ticker not in self.lag_stats:
                        self.lag_stats[ticker] = []
                    self.lag_stats[ticker].append(lag_seconds)

                    # Keep only last 100 measurements
                    if len(self.lag_stats[ticker]) > 100:
                        self.lag_stats[ticker] = self.lag_stats[ticker][-100:]

                    # Log significant lag
                    if lag_seconds > 10:
                        logger.warning(f"🐌 High lag for {ticker}: {lag_seconds:.1f}s")
                    elif lag_seconds <= 2:
                        logger.debug(f"⚡ Fast update {ticker}: {lag_seconds:.2f}s lag")

        except Exception as e:
            logger.error(f"Error processing Pyth message: {e}")

    async def _run_onchain_fallback_loop(self):
        """Temporary REST polling fallback — runs as a separate task."""
        while self.running:
            try:
                await self._execute_onchain_fallback_tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"REST Fallback tick failed: {e}")
            await asyncio.sleep(2.0)

    async def _execute_onchain_fallback_tick(self):
        """Single REST fetch tick for Pyth Hermes fallback."""
        if not self.rpc_url:
            return

        rest_url = "https://hermes.pyth.network/v2/updates/price/latest"
        try:
            from src.config.addresses import PYTH_FEEDS, PYTH_CORE_FEEDS
            all_feeds = {**PYTH_FEEDS, **PYTH_CORE_FEEDS}
            feed_ids = [
                v["feed_id"]
                for k, v in all_feeds.items()
                if isinstance(v, dict) and v.get("feed_id")
            ]

            params = {"ids[]": feed_ids}
            async with self.session.get(
                rest_url, params=params,
                timeout=aiohttp.ClientTimeout(total=5.0)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data.get("parsed", []):
                        raw_id = item.get("id", "").replace("0x", "")
                        ticker = self.feed_to_ticker.get(raw_id)
                        if not ticker:
                            continue
                        price_data = item.get("price", {})
                        price_str = price_data.get("price")
                        conf_str = price_data.get("conf")
                        expo = price_data.get("expo", -8)
                        publish_time = price_data.get("publish_time")
                        status = price_data.get("status", "trading")

                        if price_str is None or publish_time is None:
                            continue

                        if status and status != "trading":
                            continue

                        scale = 10 ** abs(expo)
                        price = float(price_str) / scale if expo < 0 else float(price_str)
                        confidence = float(conf_str) / scale if conf_str and expo < 0 else float(conf_str or 0)

                        if price > 0 and (confidence / price) > 0.0015:
                            logger.warning(
                                f"🚫 Pyth REST feed {ticker} has unsafe confidence: "
                                f"conf={confidence:.4f}, price={price:.4f}, ratio={confidence/price:.2%} (> 0.15%). Skipping."
                            )
                            continue

                        self.price_cache[ticker] = {
                            "price": price,
                            "timestamp": datetime.fromtimestamp(publish_time),
                            "confidence": confidence,
                            "status": status,
                        }

                        logger.debug(f"⚡ REST Pyth {ticker}: price={price}")
                else:
                    logger.warning(f"Pyth REST API returned status {resp.status}")

        except asyncio.TimeoutError:
            logger.debug("Pyth REST fallback timeout")
        except Exception as e:
            logger.debug(f"Pyth REST fallback error: {e}")

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get the latest price for a ticker."""
        if ticker in self.price_cache:
            cache_entry = self.price_cache[ticker]
            if datetime.now() - cache_entry["timestamp"] < timedelta(seconds=5):
                return cache_entry["price"]
            else:
                logger.warning(f"Stale price for {ticker}: {cache_entry['timestamp']}")
        return None

    def get_price_info(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get full price info including confidence and timestamp."""
        return self.price_cache.get(ticker)

    def get_average_lag(self, ticker: str) -> Optional[float]:
        """Get average lag for ticker in seconds."""
        if ticker in self.lag_stats and self.lag_stats[ticker]:
            return sum(self.lag_stats[ticker]) / len(self.lag_stats[ticker])
        return None

    def get_all_prices(self) -> Dict[str, float]:
        """Get current prices for all tracked tickers."""
        return {
            ticker: info["price"]
            for ticker, info in self.price_cache.items()
            if datetime.now() - info["timestamp"] < timedelta(seconds=5)
        }

    def get_lag_report(self) -> Dict[str, Dict[str, Any]]:
        """Generate lag report for monitoring."""
        report = {}
        for ticker in PYTH_FEEDS.keys():
            price_info = self.get_price_info(ticker)
            avg_lag = self.get_average_lag(ticker)

            report[ticker] = {
                "current_price": price_info["price"] if price_info else None,
                "last_update": price_info["timestamp"].isoformat() if price_info else None,
                "average_lag_seconds": avg_lag,
                "is_fresh": price_info and (datetime.now() - price_info["timestamp"]) < timedelta(seconds=5)
            }

        return report


# Global client instance
_pyth_client = None


def get_pyth_client() -> PythHermesClient:
    """Get or create global Pyth client instance."""
    global _pyth_client
    if _pyth_client is None:
        _pyth_client = PythHermesClient()
    return _pyth_client


async def start_pyth_client():
    """Start the global Pyth client."""
    client = get_pyth_client()
    await client.start()


async def stop_pyth_client():
    """Stop the global Pyth client."""
    client = get_pyth_client()
    await client.stop()