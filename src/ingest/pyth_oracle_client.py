"""
Pyth Oracle Client for Real-Time Price Feeds
Hermes WebSocket integration for price feeds
"""

import asyncio
import orjson
import logging
import socket
from typing import Dict, Optional, Any
from datetime import datetime, timedelta
import aiohttp
from .oracle_streams import (
    HERMES_WS_URL,
    PYTH_FEEDS,
)
from src.config.addresses import get_all_pyth_feed_ids

logger = logging.getLogger(__name__)


class PythHermesClient:
    """
    Real-time Pyth price feed client using Hermes WebSocket.
    Maintains in-memory cache of latest prices for oracle lag detection.
    """

    def __init__(self, reconnect_interval: int = 5, session: Optional[aiohttp.ClientSession] = None):
        self.ws_url = HERMES_WS_URL
        self.reconnect_interval = reconnect_interval
        self.websocket = None
        self.running = False
        self.session = session
        self._session_owned = session is None

        # Price cache: ticker -> {"price": float, "timestamp": datetime, "confidence": float}
        self.price_cache: Dict[str, Dict[str, Any]] = {}

        # Feed ID to ticker mapping for reverse lookup
        self.feed_to_ticker = {v["feed_id"]: k for k, v in PYTH_FEEDS.items() if v.get("feed_id")}

        # Lag monitoring
        self.lag_stats: Dict[str, list] = {}

    async def start(self):
        """Start the WebSocket connection and price monitoring."""
        self.running = True
        logger.info("🚀 Starting Pyth Hermes Client...")

        while self.running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                logger.error(f"Pyth client error: {e}")
                if self.running:
                    logger.info(f"Reconnecting in {self.reconnect_interval}s...")
                    await asyncio.sleep(self.reconnect_interval)

    async def stop(self):
        """Stop the client and close connections."""
        self.running = False
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

    async def _connect_and_listen(self):
        """Connect to Hermes WS and listen for price updates."""
        try:
            session = await self._get_session()
            async with session.ws_connect(self.ws_url) as websocket:
                self.websocket = websocket
                logger.info(f"✅ Connected to Pyth Hermes: {self.ws_url}")

                subscription = {
                    "type": "subscribe",
                    "subscription_type": "price_feed_updates",
                    "price_feed_ids": get_all_pyth_feed_ids()
                }

                await websocket.send_str(orjson.dumps(subscription).decode())
                logger.info(f"📡 Subscribed to {len(get_all_pyth_feed_ids())} Pyth feeds")

                # Listen for messages
                async for msg in websocket:
                    if not self.running:
                        break
                    try:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = orjson.loads(msg.data)
                            await self._process_message(data)
                    except Exception as e:
                        logger.warning(f"Invalid JSON from Pyth: {e}")

        except Exception as e:
            logger.error(f"WebSocket connection error: {e}")
            raise

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
                status = price_info.get("status")  # "trading", "halted", "auction", "ignored", "unknown"

                # ── Pyth Feed Status Guard ───────────────────────────────────────
                # Pyth может отдавать «Last Known Price», даже если рынок акций США
                # закрыт (ночь или выходные). Игнорируем все статусы кроме "trading",
                # чтобы не торговать по устаревшей цене.
                if status and status != "trading":
                    logger.debug(f"⏭️ Pyth feed {ticker} status={status} — not trading, skipping")
                    return

                if price and publish_time:
                    # Update cache
                    self.price_cache[ticker] = {
                        "price": float(price),
                        "timestamp": datetime.fromtimestamp(publish_time),
                        "confidence": float(confidence) if confidence else 0.0,
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

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get the latest price for a ticker."""
        if ticker in self.price_cache:
            cache_entry = self.price_cache[ticker]
            # Check if price is fresh (within 3 seconds for HFT lag detection)
            if datetime.now() - cache_entry["timestamp"] < timedelta(seconds=3):
                return cache_entry["price"]
            else:
                logger.warning(f"Stale price for {ticker}: {cache_entry['timestamp']}")
        return None

    def get_price_info(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Get full price info including confidence and timestamp."""
        return self.price_cache.get(ticker)

    def get_average_lag(self, ticker: str) -> Optional[float]:
        """Get average lag for a ticker in seconds."""
        if ticker in self.lag_stats and self.lag_stats[ticker]:
            return sum(self.lag_stats[ticker]) / len(self.lag_stats[ticker])
        return None

    def get_all_prices(self) -> Dict[str, float]:
        """Get current prices for all tracked tickers."""
        return {
            ticker: info["price"]
            for ticker, info in self.price_cache.items()
            if datetime.now() - info["timestamp"] < timedelta(seconds=3)
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
                "is_fresh": price_info and (datetime.now() - price_info["timestamp"]) < timedelta(seconds=3)
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