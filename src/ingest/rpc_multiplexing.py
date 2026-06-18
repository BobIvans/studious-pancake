"""RPC Multiplexing Engine for racing multiple WebSocket providers."""

import asyncio
import orjson
import logging
import time
import socket
import aiohttp
import urllib.request
import json
import ssl
from typing import Optional
from aiohttp.resolver import ThreadedResolver, AbstractResolver

def resolve_doh_via_ip(hostname: str) -> Optional[list[str]]:
    """Query multiple DoH APIs directly via IP address (bypasses system DNS).

    Uses parallel resolution across multiple DoH providers for fault tolerance.
    If all providers fail, raises gaierror to prevent StopIteration in aiohappyeyeballs.
    """
    # Список надежных DoH-провайдеров (включая unblocked Яндекс для РФ сетей)
    doh_providers = [
        ("https://8.8.8.8/resolve", "dns.google"),
        ("https://1.1.1.1/dns-query", "cloudflare-dns.com"),
        ("https://9.9.9.9/resolve", "dns.quad9.net"),
        ("https://77.88.8.1/resolve", "dns.yandex.ru")
    ]

    def _try_single_provider(url_base: str, host_header: str) -> Optional[list[str]]:
        url = f"{url_base}?name={hostname}&type=A"
        try:
            headers = {"Host": host_header, "Accept": "application/dns-json"}
            req = urllib.request.Request(url, headers=headers)
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=context, timeout=2.0) as response:
                data = json.loads(response.read().decode())
                ips = []
                for answer in data.get("Answer", []):
                    if answer.get("type") == 1:  # A record
                        ips.append(answer["data"])
                return ips if ips else None
        except Exception:
            return None

    results = []
    for url_base, host_header in doh_providers:
        ips = _try_single_provider(url_base, host_header)
        if ips:
            return ips
        results.append((url_base, host_header))

    # All providers failed - raise gaierror instead of returning empty list
    # This prevents StopIteration in aiohappyeyeballs on Python 3.13
    raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")


class DoHResolver(AbstractResolver):
    async def resolve(self, host: str, port: int = 0, family: int = 0) -> list[dict]:
        # Fast path: skip DoH for raw IP addresses
        try:
            socket.inet_aton(host)
            return [{
                'hostname': host,
                'host': host,
                'port': port,
                'family': socket.AF_INET,
                'proto': 0,
                'flags': 0
            }]
        except socket.error:
            pass

        # Попытка разрешить имя через кастомный список DoH
        try:
            ips = await asyncio.to_thread(resolve_doh_via_ip, host)
        except socket.gaierror:
            # DoH resolution failed, fallback to system resolver
            try:
                addr_infos = await asyncio.to_thread(socket.getaddrinfo, host, port, socket.AF_INET)
                return [
                    {
                        'hostname': host,
                        'host': info[4][0],
                        'port': port,
                        'family': socket.AF_INET,
                        'proto': 0,
                        'flags': 0
                    }
                    for info in addr_infos
                ]
            except Exception:
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known") from None

        return [
            {
                'hostname': host,
                'host': ip,
                'port': port,
                'family': socket.AF_INET,
                'proto': 0,
                'flags': 0
            }
            for ip in ips
        ]

    async def close(self) -> None:
        """Required by AbstractResolver for cleanup."""
        pass

from typing import List, Dict, Any, Optional, Set, TYPE_CHECKING
from contextlib import asynccontextmanager
import hashlib
from solders.keypair import Keypair
from decimal import Decimal
from .jito_bundle_handler import JitoBundleHandler, BackrunTrigger, _set_global_price_matrix

if TYPE_CHECKING:
    from .optimal_trade_sizer import OptimalTradeSizer, VelocitySlippageManager
    from .pre_trade_guard import PreTradeGuard

logger = logging.getLogger(__name__)

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
            _connector = aiohttp.TCPConnector(family=socket.AF_INET, resolver=DoHResolver(), ttl_dns_cache=300)
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
                        {"commitment": "confirmed"}
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
        asyncio.create_task(self._race_blockhashes(session))

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
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash", "params": [{"commitment": "confirmed"}]}
            async with session.post(url, json=payload, timeout=0.5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["result"]["value"]["blockhash"]
        except:
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
        self.event_queue = asyncio.Queue()
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
        """Manage connection lifecycle with auto-reconnect."""
        while self.running:
            try:
                # Connect
                if not await conn.connect():
                    await asyncio.sleep(conn.reconnect_delay)
                    continue

                # Subscribe to logs
                subscription_ids = await conn.subscribe_logs(addresses)
                if subscription_ids is None or len(subscription_ids) == 0:
                    await conn.disconnect()
                    await asyncio.sleep(conn.reconnect_delay)
                    continue

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
                await asyncio.sleep(conn.reconnect_delay)

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
    """Unified execution pipeline integrating all components."""

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
    ):
        self.rpc_engine = RPCMultiplexingEngine(wss_endpoints, rpc_endpoints)
        self.monitored_addresses = monitored_addresses
        self.trade_sizer = trade_sizer
        self.slippage_manager = slippage_manager
        self.pre_trade_guard = pre_trade_guard

        # Jito bundle components
        self.bundle_handler = JitoBundleHandler(keypair, session)
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
        asyncio.create_task(self._process_events())

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

            # Check if this is a migration/backrun opportunity
            if self._is_migration_event(event):
                await self._trigger_backrun(event)
                return  # Backrun triggered, skip normal flow

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
        """Check if event indicates pool creation/migration."""
        logs = event.get("logs", [])
        signature = event.get("signature", "")

        # Check for known migration indicators
        migration_indicators = [
            "InitializePool",  # Raydium
            "Migration",       # Pump.fun
            "CreatePool",      # Other AMMs
            "InitializeInstruction"  # General pool init
        ]

        for log in logs:
            if any(indicator in log for indicator in migration_indicators):
                return True

        return False

    async def _trigger_backrun(self, event: Dict[str, Any]):
        """Trigger atomic backrun for migration event."""
        try:
            signature = event["signature"]

            # Extract pool info from event (simplified)
            # In production, would parse actual logs for mint addresses
            base_mint = "So11111111111111111111111111111111111111112"  # SOL as default
            quote_mint = "placeholder_mint"  # Would be extracted from logs

            # Get recent blockhash (would be cached)
            recent_blockhash = "11111111111111111111111111111111"  # Placeholder

            await self.backrun_trigger.on_migration_event(
                signature=signature,
                base_mint=base_mint,
                quote_mint=quote_mint,
                recent_blockhash=recent_blockhash
            )

        except Exception as e:
            logger.error(f"Backrun trigger failed: {e}")

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