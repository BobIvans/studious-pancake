"""RPC Multiplexing Engine for racing multiple WebSocket providers."""

import socket
import asyncio
import logging
import time
import aiohttp
import orjson
import requests
from typing import List, Dict, Any, Optional, Set, TYPE_CHECKING
import random
from contextlib import asynccontextmanager
import hashlib
from decimal import Decimal
from solders.keypair import Keypair

if TYPE_CHECKING:
    from .optimal_trade_sizer import OptimalTradeSizer, VelocitySlippageManager
    from .pre_trade_guard import PreTradeGuard

logger = logging.getLogger(__name__)

_DNS_CACHE = {}

async def _async_doh_query(session: aiohttp.ClientSession, hostname: str) -> list[str]:
    """Non-blocking async DoH resolver using aiohttp with local IP pinning."""
    now = time.time()
    cache_entry = _DNS_CACHE.get(hostname)
    if cache_entry and now - cache_entry['time'] < 300:
        return cache_entry['ips']

    providers = [
        ("https://8.8.8.8/resolve", "application/json", {"Host": "dns.google"}),
        ("https://1.1.1.1/dns-query", "application/dns-json", {"Host": "cloudflare-dns.com"}),
    ]

    for url_base, accept, extra_headers in providers:
        try:
            headers = {"Accept": accept, "User-Agent": "Mozilla/5.0"}
            headers.update(extra_headers)
            timeout = aiohttp.ClientTimeout(total=0.5)
            async with session.get(f"{url_base}?name={hostname}&type=A", headers=headers, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ips = [ans["data"] for ans in data.get("Answer", []) if ans.get("type") == 1]
                    if ips:
                        _DNS_CACHE[hostname] = {'ips': ips, 'time': now}
                        return ips
        except Exception:
            continue
    return []

from .jito_bundle_handler import JitoBundleHandler, BackrunTrigger, _set_global_price_matrix

class WSSConnection:
    """Manages a single WebSocket connection with auto-reconnect."""

    def __init__(self, url: str, name: str, reconnect_delay: float = 1.0):
        self.url = url
        self.name = name
        self.reconnect_delay = reconnect_delay
        self.websocket = None
        self.connected = False
        self.last_pong = time.time()
        self.subscriptions: Dict[int, Dict] = {}
        self.session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> bool:
        """Establish WebSocket connection."""
        try:
            if self.session and not self.session.closed:
                await self.session.close()
            _connector = aiohttp.TCPConnector(family=socket.AF_INET, ttl_dns_cache=300)
            self.session = aiohttp.ClientSession(connector=_connector)
            self.websocket = await self.session.ws_connect(
                self.url,
                heartbeat=15.0,
                timeout=30.0,
                compress=15,
                receive_timeout=45.0
            )
            self.connected = True
            logger.info(f"✅ Connected to {self.name}: {self.url}")
            return True
        except Exception as e:
            logger.warning(f"❌ Failed to connect to {self.name}: {e}")
            self.connected = False
            if self.session and not self.session.closed:
                await self.session.close()
                self.session = None
            return False

    async def disconnect(self):
        """Close WebSocket connection and release the HTTP session."""
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()
        if self.session and not self.session.closed:
            await self.session.close()
        self.connected = False
        logger.info(f"🔌 Disconnected from {self.name}")

    # FIX 291: Lightweight pool balance change detection via accountSubscribe
    async def subscribe_pool_accounts(self, pool_addresses: List[str]):
        """Subscribe to account balance changes for pool detection (lighter than logsSubscribe)."""
        if not self.connected or not self.websocket:
            return
        for addr in pool_addresses:
            sub_id = len(self.subscriptions) + 1
            payload = {
                "jsonrpc": "2.0",
                "id": sub_id,
                "method": "accountSubscribe",
                "params": [
                    addr,
                    {"encoding": "jsonParsed", "commitment": "processed"}
                ]
            }
            await self.websocket.send_str(orjson.dumps(payload).decode())
            self.subscriptions[sub_id] = {
                "type": "account_update",
                "pool_address": addr,
                "active": True
            }
        logger.debug(f"📡 Subscribed to processed account updates for {len(pool_addresses)} pools")

    async def subscribe_logs(self, addresses: List[str]) -> Optional[List[int]]:
        """Subscribe to logs for specific addresses (one subscription per address)."""
        if not self.connected or not self.websocket:
            return None

        try:
            subscription_ids = []
            for address in addresses:
                subscription_id = len(self.subscriptions) + 1
                params = {
                    "jsonrpc": "2.0",
                    "id": subscription_id,
                    "method": "logsSubscribe",
                    "params": [
                        {"mentions": [address]},  # Only one address per subscription
                        {"commitment": "processed"},  # FIX 289
                    ]
                }

                await self.websocket.send_str(orjson.dumps(params).decode())
                self.subscriptions[subscription_id] = {
                    "type": "logs",
                    "addresses": [address],
                    "active": True
                }
                subscription_ids.append(subscription_id)

                # Small delay to avoid rate limiting
                await asyncio.sleep(0.05)

            logger.debug(f"📡 {self.name} subscribed to logs for {len(addresses)} addresses ({len(subscription_ids)} subscriptions)")
            return subscription_ids

        except Exception as e:
            logger.error(f"Failed to subscribe {self.name}: {e}")
            return None

    async def receive_message(self) -> Optional[Dict[str, Any]]:
        """Receive next message from WebSocket."""
        if not self.connected or not self.websocket:
            return None

        try:
            msg = await self.websocket.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                return orjson.loads(msg.data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error(f"WebSocket error on {self.name}: {self.websocket.exception()}")
                self.connected = False
                return None
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                logger.warning(f"WebSocket closed on {self.name}")
                self.connected = False
                return None
        except Exception as e:
            logger.error(f"Error receiving from {self.name}: {e}")
            self.connected = False
            return None

        return None


class BlockhashManager:
    """Manages high-frequency blockhash fetching from multiple RPCs."""
    def __init__(self, endpoints: List[str], interval: float = 0.5):
        self.endpoints = endpoints
        self.interval = interval
        self.latest_blockhash: Optional[str] = None
        self.last_update = 0
        self.running = False

    async def start(self, session: aiohttp.ClientSession):
        self.running = True
        import src.ingest.shared_state as _ss
        _ss.retain_background_task(asyncio.create_task(self._race_blockhashes(session)))

    async def _race_blockhashes(self, session: aiohttp.ClientSession):
        while self.running:
            tasks = [self._fetch_blockhash(session, url) for url in self.endpoints]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for res in results:
                if isinstance(res, str):
                    self.latest_blockhash = res
                    self.last_update = time.time()
                    break
            
            await asyncio.sleep(self.interval)

    async def _fetch_blockhash(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        try:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash", "params": [{"commitment": "processed"}]}  # FIX 289
            async with session.post(url, json=payload, timeout=0.5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["result"]["value"]["blockhash"]
        except Exception:
            pass
        return None

class TransactionDeduplicator:
    """Deduplicates transaction events using in-memory cache."""

    def __init__(self, ttl_seconds: int = 10):
        self.cache: Dict[str, float] = {}
        self.ttl = ttl_seconds

    def is_duplicate(self, signature: str) -> bool:
        """Check if transaction signature was already seen."""
        current_time = time.time()

        # Clean expired entries
        expired = [sig for sig, timestamp in self.cache.items()
                  if current_time - timestamp > self.ttl]
        for sig in expired:
            del self.cache[sig]

        # Check if signature exists
        if signature in self.cache:
            return True

        # Add to cache
        self.cache[signature] = current_time
        return False

    def size(self) -> int:
        """Get current cache size."""
        current_time = time.time()
        # Clean and count
        self.cache = {sig: ts for sig, ts in self.cache.items()
                     if current_time - ts <= self.ttl}
        return len(self.cache)


class RPCMultiplexingEngine:
    """Races multiple RPC providers for fastest event detection."""

    def __init__(self, wss_endpoints: List[str], rpc_endpoints: List[str], deduplication_ttl: int = 10):
        self.endpoints = wss_endpoints
        self.rpc_endpoints = rpc_endpoints
        self.connections: List[WSSConnection] = []
        self.deduplicator = TransactionDeduplicator(deduplication_ttl)
        self.blockhash_manager = BlockhashManager(rpc_endpoints)
        self.event_queue = asyncio.Queue(maxsize=1000)  # FIXED: Ограничение очереди для предотвращения OOM
        self.running = False
        self.tasks: List[asyncio.Task] = []

    async def start(self, monitored_addresses: List[str], session: Optional[aiohttp.ClientSession] = None):
        """Start multiplexing engine with monitored addresses."""
        logger.info(f"🚀 Starting RPC Multiplexing Engine with {len(self.endpoints)} providers")

        if session:
            await self.blockhash_manager.start(session)

        # Initialize connections
        for i, url in enumerate(self.endpoints):
            name = f"RPC-{i+1}"
            conn = WSSConnection(url, name)
            self.connections.append(conn)

        # Start connection management
        self.running = True
        self.tasks = [
            asyncio.create_task(self._manage_connection(conn, monitored_addresses))
            for conn in self.connections
        ]

        # Start event processor
        self.tasks.append(asyncio.create_task(self._process_events()))

        logger.info("✅ RPC Multiplexing Engine started")

    async def stop(self):
        """Stop multiplexing engine."""
        logger.info("🛑 Stopping RPC Multiplexing Engine")
        self.running = False

        # Cancel all tasks
        for task in self.tasks:
            task.cancel()

        # Close all connections
        for conn in self.connections:
            await conn.disconnect()

        # Wait for tasks to complete
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def get_next_event(self, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """Get next deduplicated event from the queue."""
        try:
            return await asyncio.wait_for(self.event_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def _manage_connection(self, conn: WSSConnection, addresses: List[str]):
        """Manage connection lifecycle with auto-reconnect and exponential backoff with jitter."""
        reconnect_delay = float(conn.reconnect_delay)
        while self.running:
            try:
                # Connect
                if not await conn.connect():
                    jitter = random.uniform(0.8, 1.2)
                    reconnect_delay = min(reconnect_delay * 1.5, 60.0)
                    sleep_duration = reconnect_delay * jitter
                    logger.warning(f"Connection failed for {conn.name}. Retrying in {sleep_duration:.1f}s...")
                    await asyncio.sleep(sleep_duration)
                    continue

                # Subscribe to logs
                subscription_ids = await conn.subscribe_logs(addresses)
                if subscription_ids is None or len(subscription_ids) == 0:
                    await conn.disconnect()
                    jitter = random.uniform(0.8, 1.2)
                    reconnect_delay = min(reconnect_delay * 1.5, 60.0)
                    sleep_duration = reconnect_delay * jitter
                    logger.warning(f"Subscription failed for {conn.name}. Retrying in {sleep_duration:.1f}s...")
                    await asyncio.sleep(sleep_duration)
                    continue

                # Reset backoff on success
                reconnect_delay = float(conn.reconnect_delay)

                # Listen for messages
                while self.running and conn.connected:
                    msg = await conn.receive_message()
                    if msg:
                        await self._handle_message(msg, conn.name)
                    else:
                        # Connection lost, break to reconnect
                        break

            except Exception as e:
                logger.error(f"Connection error for {conn.name}: {e}")

            # Cleanup and wait before reconnect
            await conn.disconnect()
            if self.running:
                jitter = random.uniform(0.8, 1.2)
                reconnect_delay = min(reconnect_delay * 1.5, 60.0)
                sleep_duration = reconnect_delay * jitter
                logger.warning(f"Reconnecting {conn.name} in {sleep_duration:.1f}s...")
                await asyncio.sleep(sleep_duration)

    async def _handle_message(self, msg: Dict[str, Any], source: str):
        """Handle incoming WebSocket message."""
        try:
            if "method" in msg and msg["method"] == "logsNotification":
                await self._handle_logs_notification(msg["params"]["result"], source)
            elif "id" in msg and any(msg["id"] in conn.subscriptions for conn in self.connections):
                # Subscription confirmation
                logger.debug(f"Subscription confirmed on {source}")
        except Exception as e:
            logger.error(f"Error handling message from {source}: {e}")

    async def _handle_logs_notification(self, result: Dict[str, Any], source: str):
        """Handle logs notification with deduplication."""
        try:
            signature = result.get("value", {}).get("signature")
            if not signature:
                return

            # Check for duplicates
            if self.deduplicator.is_duplicate(signature):
                logger.debug(f"🔄 Duplicate event ignored from {source}: {signature[:8]}...")
                return

            # Create event
            event = {
                "type": "logs",
                "signature": signature,
                "logs": result["value"]["logs"],
                "source": source,
                "timestamp": time.time(),
                "raw": result
            }

            # Add to queue
            await self.event_queue.put(event)
            logger.info(f"🎯 New event from {source}: {signature[:8]}... (cache size: {self.deduplicator.size()})")

        except Exception as e:
            logger.error(f"Error processing logs from {source}: {e}")

    async def _process_events(self):
        """Process events from queue (placeholder for future processing)."""
        while self.running:
            try:
                # This could be extended to do pre-processing
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Event processor error: {e}")



class ExecutionPipeline:
    """Execution Pipeline — orchestrates RPC events through the full trade pipeline."""

    def __init__(
        self,
        wss_endpoints: List[str],
        rpc_endpoints: List[str],
        monitored_addresses: List[str],
        trade_sizer: 'OptimalTradeSizer',
        pre_trade_guard: 'PreTradeGuard',
        keypair: Keypair,
        slippage_manager: Optional['VelocitySlippageManager'] = None,
        session: Optional[aiohttp.ClientSession] = None,
        price_matrix: Optional[Dict[str, tuple]] = None,
        tx_builder: Optional[Any] = None,
    ):
        self.rpc_engine = RPCMultiplexingEngine(wss_endpoints, rpc_endpoints)
        self.monitored_addresses = monitored_addresses
        self.trade_sizer = trade_sizer
        self.slippage_manager = slippage_manager
        self.pre_trade_guard = pre_trade_guard

        # Jito bundle components
        self.bundle_handler = JitoBundleHandler(keypair, session, tx_builder=tx_builder)
        self.backrun_trigger = BackrunTrigger(self.bundle_handler)
        self.running = False

        if price_matrix:
            _set_global_price_matrix(price_matrix)

    async def start(self):
        """Start the execution pipeline."""
        logger.info("🚀 Starting Execution Pipeline")
        self.running = True

        # Start RPC multiplexing
        await self.rpc_engine.start(self.monitored_addresses)

        # Start event processing loop
        import src.ingest.shared_state as _ss
        _ss.retain_background_task(asyncio.create_task(self._process_events()))

    async def stop(self):
        """Stop the execution pipeline."""
        logger.info("🛑 Stopping Execution Pipeline")
        self.running = False
        await self.rpc_engine.stop()

    async def _process_events(self):
        """Process events from RPC engine."""
        while self.running:
            try:
                event = await self.rpc_engine.get_next_event(timeout=1.0)
                if event:
                    await self._handle_event(event)
            except Exception as e:
                logger.error(f"Event processing error: {e}")

    async def _handle_event(self, event: Dict[str, Any]):
        """Handle a single event through the pipeline."""
        try:
            logger.info(f"🔥 Processing event: {event['signature'][:8]}...")

            # PR-021: Pump/log-string migration backruns are disabled. Verified
            # Pump migration state must come from src.venues.pump snapshots only.
            if self._is_migration_event(event):
                logger.warning("PUMP_LEGACY_HEURISTIC_DISABLED")
                return

            # Step 1: Parse event for pool/token info
            pool_info = self._parse_pool_event(event)
            if not pool_info:
                return

            # Step 2: Security Shield
            if not await self._run_security_checks(pool_info):
                return

            # Step 3: Velocity-based slippage
            dynamic_slippage = self.slippage_manager.get_dynamic_slippage() if self.slippage_manager else 0.5

            # Step 4: Optimal trade sizing
            optimal_amount = await self._calculate_optimal_size(pool_info, dynamic_slippage)
            if not optimal_amount:
                logger.info("❌ No profitable trade size found")
                return

            # Step 5: Execute via Jito
            await self._execute_trade(pool_info, optimal_amount, dynamic_slippage)

        except Exception as e:
            logger.error(f"Event handling error: {e}")

    def _is_migration_event(self, event: Dict[str, Any]) -> bool:
        """Legacy log-string migration detection is disabled for Pump V2."""
        return False

    async def _trigger_backrun(self, event: Dict[str, Any]):
        """Disabled compatibility shell; no Pump observation may create a bundle."""
        logger.warning("PUMP_LEGACY_HEURISTIC_DISABLED")
        return None

    def _parse_pool_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parse pool creation/migration event."""
        # Placeholder - would parse actual event data
        # Return pool info: base_mint, quote_mint, vault_addresses, etc.
        return {"base_mint": "So11111111111111111111111111111111111111112", "quote_mint": "placeholder"}

    async def _run_security_checks(self, pool_info: Dict[str, Any]) -> bool:
        """Run security and liquidity validation."""
        # Check token security
        for mint_key in ["base_mint", "quote_mint"]:
            if mint_key in pool_info:
                is_secure, reason = await self.pre_trade_guard.validate_token_security(
                    pool_info[mint_key]
                )
                if not is_secure:
                    logger.info(f"🚫 Security check failed for {pool_info[mint_key][:8]}: {reason}")
                    return False

        return True

    async def _calculate_optimal_size(self, pool_info: Dict[str, Any], slippage: float) -> Optional[Decimal]:
        """Calculate optimal trade size."""
        # Placeholder - would use real quotes and arbitrage logic
        return None

    async def _execute_trade(self, pool_info: Dict[str, Any], amount: Decimal, slippage: float):
        """Execute trade via Jito bundle."""
        # Placeholder - would create and send Jito bundle
        logger.info(f"💰 Would execute trade: {amount} tokens with {slippage:.1%} slippage")