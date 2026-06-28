"""
Multi-RPC Manager - Racing WebSocket Connections for Ultra-Low Latency

Implements Promise.any() pattern for WebSocket event racing across multiple
free RPC providers (Helius, QuickNode, Alchemy, etc.) to guarantee minimum
latency in arbitrage scenarios.
"""

import asyncio
import orjson
import logging
import socket
from typing import Dict, List, Optional, Set, Callable, Any
import aiohttp
from aiohttp.resolver import AbstractResolver

logger = logging.getLogger("MultiRpcManager")

# Solana SVM hard limit for one transaction: ~1,400,000 CU.
# We always keep a safety margin below it.
SOLANA_CU_HARD_LIMIT = 1_400_000


async def async_race_http_requests(
    session: aiohttp.ClientSession,
    endpoints: List[str],
    payload: dict,
    method: str = "POST",
    timeout_seconds: float = 2.0,
    label: str = "HTTP race",
) -> Optional[dict]:
    """Fire identical requests to multiple HTTP endpoints simultaneously.

    Implements the ``Promise.any`` pattern for HTTP polling: the first response that
    arrives wins; all other in-flight requests are immediately cancelled.  This
    guarantees the minimum possible latency is used for every critical call
    (blockhash fetch, quote retrieval, etc.), regardless of which endpoint happened
    to be faster on this particular millisecond.

    Args:
        session: Shared ``aiohttp.ClientSession``.
        endpoints: List of HTTP endpoint URLs to race.
        payload: Identical JSON body for each request.
        method: HTTP method, default POST.
        timeout_seconds: Per-request timeout.
        label: Human-readable label for log messages.

    Returns:
        First successful ``dict`` response, or ``None`` if all endpoints failed.
    """
    if not endpoints:
        return None

    tasks: List[asyncio.Task] = []
    for ep in endpoints:
        task = asyncio.create_task(
            _http_fetch(session, ep, payload, method, timeout_seconds, label)
        )
        tasks.append(task)

    try:
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result is not None:
                logger.debug(f"🏁 {label} won by first response in {len(tasks)}-endpoint race")
                # Cancel the rest immediately
                for t in tasks:
                    if not t.done():
                        t.cancel()
                return result
    except Exception as e:
        logger.debug(f"{label} race error: {e}")
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()

    logger.warning(f"❌ {label}: all {len(endpoints)} endpoints failed")
    return None


async def _http_fetch(
    session: aiohttp.ClientSession,
    endpoint: str,
    payload: dict,
    method: str = "POST",
    timeout_seconds: float = 2.0,
    label: str = "HTTP race",
) -> Optional[dict]:
    """Fetch from a single HTTP endpoint with short timeout."""
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        if method.upper() == "POST":
            async with session.post(endpoint, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    logger.debug(f"{label} HTTP {resp.status} from {endpoint}")
        else:
            async with session.get(endpoint, params=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    return await resp.json()
    except asyncio.TimeoutError:
        logger.debug(f"{label} timeout from {endpoint}")
    except Exception as e:
        logger.debug(f"{label} error from {endpoint}: {e}")
    return None


class RpcEndpoint:
    """Represents a single RPC endpoint configuration."""

    def __init__(self, name: str, ws_url: str, http_url: str, priority: int = 1):
        self.name = name
        self.ws_url = ws_url
        self.http_url = http_url
        self.priority = priority  # Lower number = higher priority
        self.connection = None  # Will be aiohttp ClientWebSocketResponse
        self.session: Optional[aiohttp.ClientSession] = None
        self.subscriptions: Dict[str, str] = {}  # subscription_id -> event_type
        self.is_connected = False
        self.last_event_time = 0.0
        self.event_count = 0
        self.latency_samples: List[float] = []  # Last 10 latency measurements

    def get_average_latency(self) -> float:
        """Get average latency from recent samples."""
        if not self.latency_samples:
            return float('inf')
        return sum(self.latency_samples) / len(self.latency_samples)

    def record_latency(self, latency_ms: float, slot: int = 0):
        """Record latency measurement."""
        self.latency_samples.append(latency_ms)
        if len(self.latency_samples) > 10:
            self.latency_samples.pop(0)


class MultiRpcManager:
    """
    Races multiple RPC providers for fastest event delivery.

    Uses Promise.any pattern to process events from whichever provider
    delivers them first, ignoring duplicates from slower providers.
    """

    # Default RPC endpoints - uses Helius by default if API key provided via env
    # Falls back to empty list - caller must provide private RPC URLs
    DEFAULT_ENDPOINTS = []

    def __init__(
        self,
        endpoints: Optional[List[RpcEndpoint]] = None,
        event_callback: Optional[Callable[[str, Dict], None]] = None,
        deduplication_window_ms: int = 5000,  # 5 seconds
        max_connections: int = 4
    ):
        self.endpoints = endpoints or self.DEFAULT_ENDPOINTS[:max_connections]
        self.event_callback = event_callback
        self.deduplication_window_ms = deduplication_window_ms

        # Deduplication tracking
        self.processed_events: Set[str] = set()
        self.event_timestamps: Dict[str, float] = {}

        # Performance tracking
        self.total_events = 0
        self.unique_events = 0
        self.duplicate_events = 0
        self.avg_first_response_time = 0.0
        self.latest_slot = 0
        self.degraded_nodes: set = set()

        # Connection management
        self.running = False
        self.connection_tasks: List[asyncio.Task] = []

        logger.info(f"🎯 MultiRpcManager initialized with {len(self.endpoints)} endpoints")
        for ep in self.endpoints:
            logger.info(f"   {ep.name}: {ep.ws_url}")

    async def start(self):
        """Start all RPC connections and begin racing."""
        self.running = True
        logger.info("🚀 Starting Multi-RPC racing...")

        # Start connection tasks for all endpoints
        self.connection_tasks = []
        for endpoint in self.endpoints:
            task = asyncio.create_task(self._manage_endpoint_connection(endpoint))
            self.connection_tasks.append(task)

        # Start cleanup task for old deduplication data
        cleanup_task = asyncio.create_task(self._cleanup_old_events())
        self.connection_tasks.append(cleanup_task)

    async def stop(self):
        """Stop all connections and cleanup."""
        self.running = False
        logger.info("🛑 Stopping Multi-RPC manager...")

        # Cancel all connection tasks
        for task in self.connection_tasks:
            task.cancel()

        # Close all websocket connections and sessions
        close_tasks = []
        for endpoint in self.endpoints:
            if endpoint.connection and not getattr(endpoint.connection, 'closed', True):
                close_tasks.append(endpoint.connection.close())
            if endpoint.session and not endpoint.session.closed:
                close_tasks.append(endpoint.session.close())

        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

        await asyncio.gather(*self.connection_tasks, return_exceptions=True)
        logger.info("✅ Multi-RPC manager stopped")

    async def _manage_endpoint_connection(self, endpoint: RpcEndpoint):
        """Manage connection lifecycle for a single endpoint."""
        while self.running:
            try:
                await self._connect_endpoint(endpoint)
                await self._handle_endpoint_messages(endpoint)
            except Exception as e:
                logger.warning(f"Connection error for {endpoint.name}: {e}")
                endpoint.is_connected = False
                if self.running:
                    await asyncio.sleep(5.0)  # Reconnect delay

    async def _connect_endpoint(self, endpoint: RpcEndpoint):
        """Establish WebSocket connection to endpoint."""
        logger.info(f"🔌 Connecting to {endpoint.name}...")
        # P0-2.1b: Close old session before creating new one to prevent socket leaks
        if endpoint.session and not endpoint.session.closed:
            await endpoint.session.close()
        connector = aiohttp.TCPConnector(ttl_dns_cache=300, family=socket.AF_INET)
        endpoint.session = aiohttp.ClientSession(connector=connector)
        endpoint.connection = await endpoint.session.ws_connect(
            endpoint.ws_url,
            heartbeat=15.0,
            timeout=30.0,
            receive_timeout=45.0
        )
        endpoint.is_connected = True
        logger.info(f"✅ Connected to {endpoint.name}")

    async def _handle_endpoint_messages(self, endpoint: RpcEndpoint):
        """Handle incoming messages from endpoint."""
        try:
            async for message in endpoint.connection:
                if message.type == aiohttp.WSMsgType.TEXT:
                    await self._process_message(endpoint, message.data)
        except Exception:
            logger.warning(f"Connection closed for {endpoint.name}")
            endpoint.is_connected = False

    async def _process_message(self, endpoint: RpcEndpoint, message: str):
        """Process incoming WebSocket message."""
        try:
            data = orjson.loads(message)

            # Handle subscription confirmations
            if "id" in data and "result" in data:
                logger.debug(f"Subscription confirmed on {endpoint.name}: {data['id']}")
                return

            # Handle events
            if "method" in data and data["method"] == "logsNotification":
                await self._handle_logs_event(endpoint, data["params"])

        except Exception:
            logger.error(f"Invalid JSON from {endpoint.name}: {message[:100]}...")
        except Exception as e:
            logger.error(f"Error processing message from {endpoint.name}: {e}")

    async def _handle_logs_event(self, endpoint: RpcEndpoint, params: Dict):
        """Handle logs notification event."""
        try:
            result = params["result"]
            signature = result.get("value", {}).get("signature", "")
            if not signature:
                return
            event_signature = signature
            current_time = asyncio.get_running_loop().time() * 1000  # milliseconds

            # Check for duplicates within deduplication window
            if self._is_duplicate_event(event_signature, current_time):
                self.duplicate_events += 1
                logger.debug(f"🚫 Duplicate event ignored from {endpoint.name}: {event_signature}")
                return

            # Record as processed
            self.processed_events.add(event_signature)
            self.event_timestamps[event_signature] = current_time
            self.total_events += 1
            self.unique_events += 1

            # Record latency (time since event was generated)
            # In practice, you'd calculate this from Solana slot time
            endpoint.event_count += 1

            # Create event data
            event_data = {
                "source_endpoint": endpoint.name,
                "signature": event_signature,
                "logs": result["value"]["logs"],
                "slot": result.get("context", {}).get("slot"),
                "timestamp": current_time
            }

            # Call callback if provided
            if self.event_callback:
                await self.event_callback(event_data)

            logger.info(f"🏁 Event won by {endpoint.name} (latency: {endpoint.get_average_latency():.1f}ms): {event_signature[:8]}...")

        except Exception as e:
            logger.error(f"Error handling logs event from {endpoint.name}: {e}")

    def _is_duplicate_event(self, event_signature: str, current_time: float) -> bool:
        """Check if event is a duplicate within the deduplication window."""
        last_seen = self.event_timestamps.get(event_signature, 0)
        return (current_time - last_seen) < self.deduplication_window_ms

    async def _cleanup_old_events(self):
        """Periodically clean up old event deduplication data."""
        while self.running:
            await asyncio.sleep(60)  # Cleanup every minute

            current_time = asyncio.get_running_loop().time() * 1000
            cutoff_time = current_time - self.deduplication_window_ms

            # Remove old timestamps
            expired = [sig for sig, ts in self.event_timestamps.items() if ts < cutoff_time]
            for sig in expired:
                self.event_timestamps.pop(sig, None)
                self.processed_events.discard(sig)

            if expired:
                logger.debug(f"🧹 Cleaned up {len(expired)} old event signatures")

    async def subscribe_to_logs(self, address: str, config: Optional[Dict] = None):
        """
        Subscribe to logs for an address across all connected endpoints.

        Args:
            address: Account address to monitor
            config: Subscription configuration
        """
        if config is None:
            config = {
                "mentions": [address],
                "commitment": "confirmed"
            }

        subscription_requests = []
        for endpoint in self.endpoints:
            if endpoint.is_connected and endpoint.connection:
                subscription_requests.append(
                    self._send_subscription(endpoint, "logsSubscribe", [config])
                )

        # Send all subscriptions concurrently
        if subscription_requests:
            await asyncio.gather(*subscription_requests, return_exceptions=True)

    async def _send_subscription(self, endpoint: RpcEndpoint, method: str, params: List):
        """Send subscription request to endpoint."""
        if not endpoint.connection:
            return

        subscription_id = f"{method}_{endpoint.name}_{len(endpoint.subscriptions)}"
        endpoint.subscriptions[subscription_id] = method

        request = {
            "jsonrpc": "2.0",
            "id": subscription_id,
            "method": method,
            "params": params
        }

        try:
            await endpoint.connection.send(orjson.dumps(request))
            logger.debug(f"📡 Sent {method} subscription to {endpoint.name}")
        except Exception as e:
            logger.error(f"Failed to send subscription to {endpoint.name}: {e}")

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        total_endpoints = len(self.endpoints)
        connected_endpoints = sum(1 for ep in self.endpoints if ep.is_connected)

        endpoint_stats = []
        for ep in self.endpoints:
            endpoint_stats.append({
                "name": ep.name,
                "connected": ep.is_connected,
                "events_received": ep.event_count,
                "avg_latency_ms": ep.get_average_latency()
            })

        return {
            "total_endpoints": total_endpoints,
            "connected_endpoints": connected_endpoints,
            "total_events": self.total_events,
            "unique_events": self.unique_events,
            "duplicate_events": self.duplicate_events,
            "deduplication_ratio": (self.duplicate_events / max(1, self.total_events)) * 100,
            "endpoint_stats": endpoint_stats
        }

    def set_event_callback(self, callback: Callable[[str, Dict], None]):
        """Set the event callback function."""
        self.event_callback = callback