"""
In-Memory Pool State Manager
Dual-path: prefers Yellowstone gRPC (sub-50ms from validator RAM); falls back
to the legacy WebSocket accountSubscribe path if no gRPC relay is configured.
"""

import asyncio
import logging
import os
import time
import socket
from typing import Any, Callable, Dict, List, Optional
from decimal import Decimal

import aiohttp
from aiohttp.resolver import AbstractResolver
from solders.pubkey import Pubkey

logger = logging.getLogger(__name__)


class PoolReserve:
    """Pool reserve data structure."""
    __slots__ = (
        "token_a_reserve", "token_b_reserve",
        "token_a_mint", "token_b_mint",
        "pool_address", "pool_type", "last_update",
    )

    def __init__(
        self,
        token_a_reserve: Decimal, token_b_reserve: Decimal,
        token_a_mint: str,   token_b_mint: str,
        pool_address: str,
        pool_type: str = "cpmm",
    ) -> None:
        self.token_a_reserve = token_a_reserve
        self.token_b_reserve = token_b_reserve
        self.token_a_mint    = token_a_mint
        self.token_b_mint    = token_b_mint
        self.pool_address    = pool_address
        self.pool_type       = pool_type
        self.last_update     = asyncio.get_running_loop().time()


class PoolStateManager:
    """Maintains in-memory pool states, updated via gRPC or WebSocket.

    Parameters
    ----------
    websocket_url:
        WSS RPC endpoint (used as fallback or for REST sync).
    pool_addresses:
        Full list of pool account addresses to track.
    high_liquidity_pools:
        Subset of pools that are high-TVL — served by REST sync, not streaming.
    grpc_stream:
        Optional pre-configured ``YellowstoneStream`` instance.  When provided,
        gRPC is the *preferred* path; WebSocket is not opened at all.
    """

    def __init__(
        self,
        websocket_url:       str,
        pool_addresses:      List[str],
        high_liquidity_pools: Optional[set]                       = None,
        grpc_stream:         Optional[Any]                        = None,
    ) -> None:
        self.websocket_url       = websocket_url
        self.pool_addresses      = pool_addresses
        self.grpc_stream         = grpc_stream          # Yellowstone gRPC (preferred)

        self.pool_states: Dict[str, PoolReserve] = {}
        self.arbitrage_callbacks: List[Callable]  = []

        # WebSocket state (only used when grpc_stream is None)
        self.websocket    = None
        self.running      = False
        self.subscription_ids: Dict[str, int] = {}
        self.sub_to_pool:      Dict[int, str]  = {}

        # Fix 5: High-liquidity pool partitioning
        self.high_liquidity_pools: set = high_liquidity_pools or set()
        self.wss_pools: List[str] = []
        self.rest_pools: List[str] = []

        # REST sync settings
        self.last_sync_time        = 0
        self.sync_interval         = 600
        self.state_drift_threshold = 400

        # Phase 40 / Fix 55: WebSocket watchdog (WebSocket path only)
        self.last_msg_time         = 0
        self.last_slot_msg_time    = 0
        self.watchdog_task         = None

        # gRPC one-shot callable for _handle_account_notification
        self._grpc_update_handler: Optional[Callable] = None

    # ── Callback registration ──────────────────────────────────────────────────

    def register_arbitrage_callback(self, callback: Callable) -> None:
        self.arbitrage_callbacks.append(callback)

    # ── State accessors ─────────────────────────────────────────────────────────

    def is_state_fresh(self, pool_address: str) -> bool:
        pool = self.pool_states.get(pool_address)
        if pool is None:
            return False
        age_ms = (asyncio.get_running_loop().time() - pool.last_update) * 1000
        return age_ms < self.state_drift_threshold

    def get_pool_state(self, pool_address: str) -> Optional[PoolReserve]:
        return self.pool_states.get(pool_address)

    def get_all_pool_states(self) -> Dict[str, PoolReserve]:
        return self.pool_states.copy()

    def get_pools_by_token(self, token_mint: str) -> List[PoolReserve]:
        return [
            p for p in self.pool_states.values()
            if p.token_a_mint == token_mint or p.token_b_mint == token_mint
        ]

    def get_pool_count(self) -> int:
        return len(self.pool_states)

    def get_update_stats(self) -> Dict[str, Any]:
        now = asyncio.get_running_loop().time()
        recent = sum(
            1 for p in self.pool_states.values()
            if now - p.last_update < 60
        )
        return {
            "pools":  len(self.pool_states),
            "recent_updates": recent,
            "updates_per_second": recent / 60.0 if recent else 0.0,
        }

    # ── Partitioning (Fix 5) ────────────────────────────────────────────────────

    def _partition_pools(self) -> None:
        if not self.high_liquidity_pools:
            self.wss_pools  = list(self.pool_addresses)
            self.rest_pools = []
            return
        self.wss_pools  = [p for p in self.pool_addresses if p not in self.high_liquidity_pools]
        self.rest_pools = [p for p in self.pool_addresses if p in self.high_liquidity_pools]
        if self.rest_pools:
            logger.info(
                f"Fix 5 Partition: {len(self.rest_pools)} high-Liq pools → REST; "
                f"{len(self.wss_pools)} low-Liq pools → stream"
            )

    # ── REST sync ───────────────────────────────────────────────────────────────

    async def sync_pool_states(self) -> None:
        now = asyncio.get_running_loop().time()
        if now - self.last_sync_time < self.sync_interval:
            return

        try:
            http_url = (
                self.websocket_url
                .replace("wss://", "https://")
                .replace("ws://", "http://")
            )
            if not self.pool_addresses:
                return

            payload = {
                "jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                "params": [self.pool_addresses, {"encoding": "jsonParsed", "commitment": "confirmed"}],
            }
            connector = aiohttp.TCPConnector(ttl_dns_cache=300, family=socket.AF_INET)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(http_url, json=payload) as resp:
                    if resp.status == 200:
                        data        = await resp.json()
                        accounts    = data.get("result", {}).get("value", [])
                        for i, acct_data in enumerate(accounts):
                            if acct_data and i < len(self.pool_addresses):
                                addr     = self.pool_addresses[i]
                                reserve  = await self._decode_pool_reserves(addr, acct_data)
                                if reserve:
                                    self.pool_states[addr] = reserve
            self.last_sync_time = now
        except Exception as exc:
            logger.warning(f"Pool state sync failed: {exc}")

    # ── gRPC STARTPATH ─────────────────────────────────────────────────────────

    def _make_grpc_handler(self) -> Callable:
        """Return a sync/async callable suitable for use as a YellowstoneStream callback."""
        _self = self   # capture for use in closure

        async def _handler(update: Dict[str, Any]) -> None:
            await _self._handle_account_notification(update)

        return _handler

    # ── Unified account notification dispatcher ────────────────────────────────
    # Accepts both a WebSocket raw-JSON dict and a Yellowstone gRPC update dict.
    # WebSocket shape: {"params": {"result": {"value": {...}}, "subscription": <id>}}
    # gRPC shape:      {"pubkey": <str>,  "data": <bytes>, "slot": <int>, "owner": <bytes>}

    async def _handle_account_notification(
        self, notification: Dict[str, Any]
    ) -> None:
        """Decode and store pool reserves from a raw account notification."""
        try:
            # ── Shared: decode raw account bytes ──────────────────────────────────
            # gRPC path: put data bytes into the standard "value" shape expected
            # by _decode_pool_reserves, which reads "parsed" / "data" sub-keys.
            if "data" in notification and isinstance(notification["data"], bytes):
                _raw_b64 = notification["data"].hex()  # betterproto gives .data as bytes
                account_data = {
                    "data":  [_raw_b64, "base64"],
                    "owner": notification.get("owner", b"").decode(),
                    "executable": False,
                    "lamports":   0,
                }
                account_pubkey = notification.get("pubkey", "")
            else:
                # ── WebSocket path ─────────────────────────────────────────────────
                params = notification.get("params", {})
                result = params.get("result", {})
                if not result:
                    return
                sub_id    = params.get("subscription")
                account_address = (
                    self.sub_to_pool.get(sub_id)  # type: ignore[assignment]
                    if sub_id
                    else None
                )
                if not account_address:
                    return
                account_pubkey   = account_address
                account_data     = result.get("value", {})
                if not account_data:
                    return

            reserve = await self._decode_pool_reserves(account_pubkey, account_data)
            if reserve:
                self.pool_states[account_pubkey] = reserve
                for cb in self.arbitrage_callbacks:
                    try:
                        await cb(account_pubkey, reserve)
                    except Exception as exc:
                        logger.error(f"Arbitrage callback error: {exc}")

        except Exception as exc:
            logger.debug(f"Account notification processing error: {exc}")

    # ── START ───────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start streaming: gRPC (preferred) or WebSocket fallback."""
        self.running = True
        self._partition_pools()

        # ── gRPC path (preferred) ─────────────────────────────────────────────────
        if self.grpc_stream is not None:
            logger.info(
                f"PoolStateManager ▶ gRPC path  "
                f"| accounts={len(self.pool_addresses)}  "
                f"| endpoint={self.grpc_stream.grpc_endpoint}"
            )
            # Register every pool address for real-time account updates
            _handler = self._make_grpc_handler()
            for addr in self.wss_pools:
                self.grpc_stream.register_account_callback(addr, _handler)

            # Connect the gRPC stream
            await self.grpc_stream.connect()
            logger.info(
                f"PoolStateManager ▶ Yellowstone gRPC: "
                f"{len(self.grpc_stream.account_callbacks)} accounts subscribed"
            )
            return

        # ── WebSocket fallback ───────────────────────────────────────────────────
        logger.info("PoolStateManager ▶ WebSocket fallback path (gRPC not configured)")
        reconnect_delay = 1.0
        last_heal       = time.time()

        while self.running:
            self.subscription_ids.clear()
            self.sub_to_pool.clear()
            try:
                connector = aiohttp.TCPConnector(ttl_dns_cache=300, family=socket.AF_INET)
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.ws_connect(
                        self.websocket_url,
                        heartbeat=15.0,
                        timeout=30.0,
                        compress=15,
                        receive_timeout=45.0,
                    ) as ws:
                        self.websocket           = ws
                        reconnect_delay          = 1.0
                        self.last_msg_time       = asyncio.get_running_loop().time()
                        if not self.watchdog_task or self.watchdog_task.done():
                            self.watchdog_task = asyncio.create_task(self._watchdog())
                        await self._subscribe_to_slots(ws)

                        for pool_addr in self.wss_pools:
                            sub_id = await self._subscribe_to_pool(ws, pool_addr)
                            if sub_id:
                                self.subscription_ids[pool_addr] = sub_id

                        async for msg in ws:
                            self.last_msg_time = asyncio.get_running_loop().time()
                            if not self.running:
                                break
                            if time.time() - last_heal > 3600:
                                logger.info("🔄 Self-healing WS: clearing + re-subscribing")
                                self.pool_states.clear()
                                last_heal = time.time()
                                break

                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = msg.json()
                                result = data.get("params", {}).get("result", {})
                                if result and isinstance(result, dict) and "slot" in result:
                                    self.last_slot_msg_time = self.last_msg_time
                                else:
                                    await self._handle_account_notification(data)
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error(f"WebSocket error: {msg}")
                                break
            except Exception as exc:
                logger.error(f"PoolStateManager WebSocket error: {exc}")
                if self.running:
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 60.0)

        logger.info("PoolStateManager stopped")

    async def stop(self) -> None:
        self.running = False
        if self.watchdog_task:
            self.watchdog_task.cancel()
        if self.grpc_stream:
            await self.grpc_stream.disconnect()
        if self.websocket:
            await self.websocket.close()

    # ── WebSocket internals (only active in WebSocket fallback path) ─────────────

    async def _watchdog(self) -> None:
        while self.running:
            try:
                now = asyncio.get_running_loop().time()
                if self.last_slot_msg_time > 0 and (now - self.last_slot_msg_time) > 3.0:
                    logger.warning(
                        "🚨 SLOT WATCHDOG: No slot for >3s — forcing reconnect"
                    )
                    if getattr(self, "websocket", None) and not self.websocket.closed:
                        await self.websocket.close()

                if (
                    getattr(self, "websocket", None)
                    and self.last_msg_time > 0
                    and (now - self.last_msg_time) > 5.0
                ):
                    logger.warning("🚨 WS Watchdog: 5s no-msg — force reconnect")
                    await self.websocket.close()

                await asyncio.sleep(0.25)
            except Exception as exc:
                logger.debug(f"Watchdog error: {exc}")
                await asyncio.sleep(0.25)

    async def _subscribe_to_slots(self, ws) -> None:
        try:
            await ws.send_json({
                "jsonrpc": "2.0", "id": 999,
                "method":  "slotSubscribe", "params": [],
            })
        except Exception as exc:
            logger.warning(f"Slot subscription failed: {exc}")

    async def _subscribe_to_pool(self, ws, pool_address: str) -> Optional[int]:
        try:
            await ws.send_json({
                "jsonrpc": "2.0",
                "id":      len(self.subscription_ids) + 1,
                "method":  "accountSubscribe",
                "params": [
                    pool_address,
                    {"encoding": "jsonParsed", "commitment": "confirmed"},
                ],
            })
            resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            sub_id = resp.get("result")
            if sub_id:
                self.sub_to_pool[sub_id] = pool_address
                return sub_id
        except Exception as exc:
            logger.debug(f"Pool subscribe failed [{pool_address[:8]}]: {exc}")
        return None

    # ── Pool reserve decoding ─────────────────────────────────────────────────────

    async def _decode_pool_reserves(
        self, pool_address: str, account_data: Dict[str, Any]
    ) -> Optional[PoolReserve]:
        try:
            if "parsed" in account_data and "info" in account_data["parsed"]:
                info               = account_data["parsed"]["info"]
                token_a_reserve    = Decimal(str(info.get("tokenAAmount", 0)))
                token_b_reserve    = Decimal(str(info.get("tokenBAmount", 0)))
                token_a_mint       = info.get("mintA", "")
                token_b_mint       = info.get("mintB", "")
                if token_a_reserve > 0 and token_b_reserve > 0:
                    return PoolReserve(
                        token_a_reserve, token_b_reserve,
                        token_a_mint, token_b_mint,
                        pool_address, "cpmm",
                    )
            elif "data" in account_data and len(account_data["data"]) > 0:
                logger.debug(f"Meteora DLMM update for {pool_address[:8]}")
            elif str(pool_address).startswith("SS"):
                logger.debug(f"Saber Stableswap update for {pool_address[:8]}")
        except Exception as exc:
            logger.debug(f"Pool reserve decode error: {exc}")
        return None
