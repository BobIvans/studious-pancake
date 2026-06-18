"""
Pyth Core Price Feeder (Task 13)
==================================
Lightweight Hermes WebSocket subscriber for SOL, USDC, USDT prices.

Bypasses the Jupiter Price API (which has 10-30s cache lag) for core
tokens used in Jito tip calculation.  Pyth Hermes updates every ~400ms
directly from validators — at least 25x fresher.

Usage:
    feeder = PythCorePriceFeeder()
    await feeder.connect()
    price = feeder.get_price("So11111111111111111111111111111111111111112")
    # → 150.42  (real-time SOL/USD)
"""

import asyncio
import orjson
import logging
import time
from typing import Dict, Optional, Any, Callable

import aiohttp

from src.config.addresses import PYTH_CORE_FEEDS, get_mint_for_core_feed

logger = logging.getLogger(__name__)

# Default Hermes WebSocket URL
HERMES_WS_URL = "wss://hermes.pyth.network/ws"

# Mint string → price_cache key mapping
MINT_TO_CORE_TICKER = {}
for _ticker, _info in PYTH_CORE_FEEDS.items():
    if _info.get("mint"):
        MINT_TO_CORE_TICKER[_info["mint"]] = _ticker


class PythCorePriceFeeder:
    """
    Lightweight Hermes WebSocket subscriber for SOL, USDC, USDT prices.

    Maintains an in-memory price dict that can be consumed by
    arb_bot's _set_global_price_matrix() or normalize_profit_to_sol().

    Uses a separate Hermes connection from the xStocks Pyth client
    to avoid cross-contamination and keep the subscription small (3 feeds).

    ═══════════════════════════════════════════════════════════════════════
    SINGLETON PATTERN (Task 13 fix):
    Must be created ONCE at bot startup and reused across all update_prices
    cycles. Creating a new instance every iteration would never establish a
    WebSocket connection, making as_price_matrix() always return {}.
    Use get_pyth_core_feeder() to get the global instance.
    ═══════════════════════════════════════════════════════════════════════
    """

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self.ws_url = HERMES_WS_URL
        self.websocket = None
        self.running = False
        self.session = session
        self._session_owned = session is None

        # price_cache: mint_str -> {"price_usd": float, "timestamp": float}
        self.price_cache: Dict[str, Dict[str, float]] = {}

        # Callback fired on every price update — arb_bot pipes this into
        # _set_global_price_matrix()
        self.on_price_update: Optional[Callable[[Dict[str, tuple]], None]] = None

        self._task: Optional[asyncio.Task] = None

    @property
    def feed_ids(self) -> list:
        """Get the 3 Hermes feed IDs for SOL, USDC, USDT."""
        return [info["feed_id"] for info in PYTH_CORE_FEEDS.values() if info.get("feed_id")]

    async def start(self, on_price_update: Optional[Callable[[Dict[str, tuple]], None]] = None):
        """
        Start the WebSocket connection in a background task.

        Args:
            on_price_update: Optional callback receiving a price_matrix dict
                             e.g. {"So111...": (150.42, timestamp)}
                             which arb_bot can pipe into _set_global_price_matrix()
        """
        self.on_price_update = on_price_update
        self.running = True
        self._task = asyncio.create_task(self._run())
        logger.info(
            f"🚀 PythCorePriceFeeder started: {len(self.feed_ids)} feeds "
            f"(SOL/USDC/USDT)"
        )

    async def stop(self):
        """Stop the WebSocket connection."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self.websocket:
            await self.websocket.close()
        if self._session_owned and self.session and not self.session.closed:
            await self.session.close()
        logger.info("🛑 PythCorePriceFeeder stopped")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create session with DoH resolver."""
        if self.session is None or self.session.closed:
            from src.ingest.rpc_multiplexing import DoHResolver
            connector = aiohttp.TCPConnector(resolver=DoHResolver(), ttl_dns_cache=300)
            self.session = aiohttp.ClientSession(connector=connector)
            self._session_owned = True
        return self.session

    async def _run(self):
        """Internal task runner that loops _connect_and_listen with reconnect."""
        reconnect_delay = 5.0
        while self.running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"PythCorePriceFeeder connection lost, reconnecting in {reconnect_delay}s: {e}")
                await asyncio.sleep(reconnect_delay)

    async def _connect_and_listen(self):
        """Connect to Hermes WS, subscribe, and listen for price updates."""
        try:
            session = await self._get_session()
            async with session.ws_connect(self.ws_url) as websocket:
                self.websocket = websocket
                logger.debug("✅ PythCorePriceFeeder connected to Hermes")

                subscription = {
                    "type": "subscribe",
                    "subscription_type": "price_feed_updates",
                    "price_feed_ids": self.feed_ids,
                }
                await websocket.send_str(orjson.dumps(subscription).decode())
                logger.debug(
                    f"📡 PythCorePriceFeeder subscribed to {len(self.feed_ids)} core feeds"
                )

                async for message in websocket:
                    if not self.running:
                        break
                    try:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            data = orjson.loads(message.data)
                            await self._process_message(data)
                    except Exception as e:
                        logger.debug(f"Pyth core message parse error: {e}")

        except Exception as e:
            logger.warning(f"PythCorePriceFeeder WS error: {e}")
            raise

    async def _process_message(self, data: dict):
        """Process a Hermes price update and pipe it into the callback."""
        try:
            if data.get("type") != "price_feed_update":
                return

            # Убираем префикс 0x для совпадения с локальным реестром
            raw_feed_id = data.get("price_feed_id") or data.get("price_feed", {}).get("id", "")
            feed_id = str(raw_feed_id).replace("0x", "")
            
            mint_str = get_mint_for_core_feed(feed_id)
            if not mint_str:
                return  # Not a core feed we're tracking

            price_feed = data.get("price_feed", {})
            price_info = price_feed.get("price", {})
            raw_price = price_info.get("price")
            expo = price_info.get("expo", 0)
            publish_time = price_info.get("publish_time")

            if raw_price is None:
                return

            # Pyth uses exponents: price * 10^expo
            price_usd = float(raw_price) * (10 ** expo)
            timestamp = publish_time or time.time()

            # Update cache
            self.price_cache[mint_str] = {
                "price_usd": price_usd,
                "timestamp": timestamp,
            }

            # Fire callback with a price_matrix-like dict
            if self.on_price_update:
                matrix = {mint_str: (price_usd, timestamp)}
                try:
                    self.on_price_update(matrix)
                except Exception as cb_err:
                    logger.debug(f"Pyth price callback error: {cb_err}")

            logger.debug(
                f"🐍 Pyth core: {mint_str[:8]} = ${price_usd:.4f} "
                f"(expo={expo})"
            )

        except Exception as e:
            logger.debug(f"Pyth core price processing error: {e}")

    def get_price(self, mint_str: str) -> Optional[float]:
        """
        Get the latest price for a mint string.

        Returns None if:
        - The mint is not core (SOL/USDC/USDT)
        - No price has been received yet
        - The cached price is >30s old
        """
        entry = self.price_cache.get(mint_str)
        if entry is None:
            return None
        age = time.time() - entry["timestamp"]
        if age > 30.0:
            logger.debug(f"Pyth core price stale for {mint_str[:8]}: {age:.0f}s old")
            return None
        return entry["price_usd"]

    def get_all_prices(self) -> Dict[str, float]:
        """
        Get all non-stale core prices as mint_str -> price_usd.
        """
        now = time.time()
        return {
            mint: entry["price_usd"]
            for mint, entry in self.price_cache.items()
            if now - entry["timestamp"] < 30.0
        }

    def as_price_matrix(self) -> Dict[str, tuple]:
        """
        Return prices as a dict compatible with _set_global_price_matrix():
            {mint_str: (price_usd, timestamp)}
        """
        now = time.time()
        return {
            mint: (entry["price_usd"], entry["timestamp"])
            for mint, entry in self.price_cache.items()
            if now - entry["timestamp"] < 30.0
        }


# ── Singleton (Task 13) ────────────────────────────────────────────────────
# Created once at bot startup. update_prices() should call get_pyth_core_feeder()
# to get the already-running instance instead of creating a new one each cycle.
_GLOBAL_PYTH_CORE_FEEDER: Optional[PythCorePriceFeeder] = None


def get_pyth_core_feeder() -> Optional[PythCorePriceFeeder]:
    """Get the global PythCorePriceFeeder singleton.

    Returns None if the feeder hasn't been started yet (e.g. first call
    before the startup sequence). update_prices() checks for None and
    gracefully falls back to Jupiter prices.
    """
    return _GLOBAL_PYTH_CORE_FEEDER


def init_pyth_core_feeder() -> PythCorePriceFeeder:
    """Create (or return existing) global PythCorePriceFeeder singleton.

    Called once from arb_bot.py's startup sequence before the
    update_prices() loop begins.
    """
    global _GLOBAL_PYTH_CORE_FEEDER
    if _GLOBAL_PYTH_CORE_FEEDER is None:
        _GLOBAL_PYTH_CORE_FEEDER = PythCorePriceFeeder()
    return _GLOBAL_PYTH_CORE_FEEDER