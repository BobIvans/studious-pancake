"""
In-Memory Pool State Manager
Maintains real-time pool reserves via WebSocket accountSubscribe.
No RPC polling - pure event-driven updates for 450+ pairs.
"""

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Callable, Any
from decimal import Decimal
import aiohttp
from solders.pubkey import Pubkey

logger = logging.getLogger(__name__)

class PoolReserve:
    """Pool reserve data structure."""
    __slots__ = ("token_a_reserve", "token_b_reserve", "token_a_mint", "token_b_mint", "pool_address", "pool_type", "last_update")
    def __init__(self, token_a_reserve: Decimal, token_b_reserve: Decimal,
                 token_a_mint: str, token_b_mint: str, pool_address: str,
                 pool_type: str = "cpmm"):
        self.token_a_reserve = token_a_reserve
        self.token_b_reserve = token_b_reserve
        self.token_a_mint = token_a_mint
        self.token_b_mint = token_b_mint
        self.pool_address = pool_address
        self.pool_type = pool_type  # 'cpmm', 'stableswap', 'dlmm'
        self.last_update = asyncio.get_event_loop().time()

class PoolStateManager:
    """Manages in-memory pool states updated via WebSocket."""

    def __init__(self, websocket_url: str, pool_addresses: List[str]):
        self.websocket_url = websocket_url
        self.pool_addresses = pool_addresses
        self.pool_states: Dict[str, PoolReserve] = {}
        self.arbitrage_callbacks: List[Callable] = []
        self.websocket = None
        self.running = False
        self.subscription_ids: Dict[str, int] = {}  # pool_address -> subscription_id
        self.sub_to_pool: Dict[int, str] = {}      # subscription_id -> pool_address

        # State synchronization settings
        self.last_sync_time = 0
        self.sync_interval = 600  # Sync every 10 minutes (OPTIMIZED FOR CREDITS)
        self.state_drift_threshold = 400  # Max acceptable drift in ms
        
        # Phase 40: WebSocket Watchdog
        self.last_msg_time = 0
        self.last_slot_msg_time = 0  # Fix 55: slot-subscribe heartbeat
        self.watchdog_task = None

    def register_arbitrage_callback(self, callback: Callable[[str, PoolReserve], None]):
        """Register callback for arbitrage evaluation when pool updates."""
        self.arbitrage_callbacks.append(callback)

    async def sync_pool_states(self):
        """Force synchronization of all pool states with blockchain."""
        try:
            current_time = asyncio.get_event_loop().time()
            if current_time - self.last_sync_time < self.sync_interval:
                return  # Too soon for another sync

            logger.debug(f"Syncing {len(self.pool_addresses)} pool states with blockchain")

            # Batch fetch all pool accounts
            if self.pool_addresses:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getMultipleAccounts",
                    "params": [
                        self.pool_addresses,
                        {"encoding": "jsonParsed", "commitment": "confirmed"}
                    ]
                }

                async with aiohttp.ClientSession() as session:
                    http_url = self.websocket_url.replace('wss://', 'https://').replace('ws://', 'http://')
                    async with session.post(http_url, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            accounts = data.get("result", {}).get("value", [])

                            for i, account_data in enumerate(accounts):
                                if account_data and i < len(self.pool_addresses):
                                    pool_address = self.pool_addresses[i]
                                    pool_reserve = await self._decode_pool_reserves(pool_address, account_data)
                                    if pool_reserve:
                                        self.pool_states[pool_address] = pool_reserve

            self.last_sync_time = current_time
            logger.debug("Pool state synchronization complete")

        except Exception as e:
            logger.warning(f"Failed to sync pool states: {e}")

    def is_state_fresh(self, pool_address: str) -> bool:
        """Check if pool state is fresh enough for arbitrage."""
        if pool_address not in self.pool_states:
            return False

        pool_reserve = self.pool_states[pool_address]
        current_time = asyncio.get_event_loop().time()
        age_ms = (current_time - pool_reserve.last_update) * 1000

        return age_ms < self.state_drift_threshold

    async def _watchdog(self):
        """Fix 55: Slot-subscribe heartbeat — hard-exit bot if slot stream is dead > 3s."""
        import os, signal
        while self.running:
            try:
                now = asyncio.get_event_loop().time()
                # Slot-stream check (post-hook — subscription id 999)
                if self.last_slot_msg_time > 0 and (now - self.last_slot_msg_time) > 3.0:
                    logger.critical(
                        "🚨 SLOT WATCHDOG: No slot received for >3s (7.5 slots). "
                        "WebSocket is ghosting — forcing hard exit so PM2/Docker restarts us."
                    )
                    # Force-terminate the process; supervisor restarts cleanly
                    os._exit(1)

                # Backwards-compat: also close WS if it's completely dead (5s any-message gap)
                if self.websocket and self.last_msg_time > 0:
                    if now - self.last_msg_time > 5.0:
                        logger.warning("🚨 WebSocket watchdog: No messages for 5s! Force reconnecting...")
                        await self.websocket.close()

                await asyncio.sleep(0.25)  # 4 Hz scan — catches slot loss within 1 heartbeat
            except Exception as e:
                logger.debug(f"Watchdog tick error (non-fatal): {e}")
                await asyncio.sleep(0.25)

    async def _subscribe_to_slots(self, ws):
        """Subscribe to slot updates for heartbeat (Fix 55)."""
        try:
            msg = {
                "jsonrpc": "2.0",
                "id": 999,
                "method": "slotSubscribe",
                "params": []
            }
            await ws.send_json(msg)
        except Exception as e:
            logger.warning(f"Slot subscription failed: {e}")

    async def _handle_slot_notification(self, notification: Dict[str, Any]):
        """Fix 55: Handle slot notification for heartbeat watchdog."""
        try:
            params = notification.get("params", {})
            result = params.get("result", {})
            if result:  # slot notification has non-empty result
                self.last_slot_msg_time = asyncio.get_event_loop().time()
        except Exception:
            pass

    async def start(self):
        """Start WebSocket connection and subscribe to all pools with auto-reconnect."""
        self.running = True
        reconnect_delay = 1.0  # Start with 1 second delay
        last_heal = time.time()

        while self.running:
            # Phase 25: Clear subscription tracking to prevent memory leaks on reconnect
            self.subscription_ids.clear()
            self.sub_to_pool.clear()
            
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        self.websocket_url,
                        heartbeat=15.0,
                        timeout=30.0,
                        compress=15,
                        receive_timeout=45.0
                    ) as ws:
                        self.websocket = ws
                        logger.info(f"Connected to WebSocket: {self.websocket_url}")
                        reconnect_delay = 1.0  # Reset delay on successful connection
                        self.last_msg_time = asyncio.get_event_loop().time()
                        
                        # Phase 40: Launch watchdog and slot heartbeat
                        if not self.watchdog_task or self.watchdog_task.done():
                            self.watchdog_task = asyncio.create_task(self._watchdog())
                        await self._subscribe_to_slots(ws)

                        # Send accountSubscribe for all pool addresses
                        for pool_addr in self.pool_addresses:
                            subscription_id = await self._subscribe_to_pool(ws, pool_addr)
                            if subscription_id:
                                self.subscription_ids[pool_addr] = subscription_id
                                logger.debug(f"Subscribed to pool: {pool_addr} (ID: {subscription_id})")

                        # Listen for account + slot notifications
                        async for msg in ws:
                            self.last_msg_time = asyncio.get_event_loop().time()
                            if not self.running:
                                break
                            # Fix 66: Self-healing WebSocket every 60min
                            if time.time() - last_heal > 3600:
                                logger.info("🔄 Self-healing WS: clearing state + re-subscribing")
                                self.pool_states.clear()
                                last_heal = time.time()
                                break  # force reconnect cycle

                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = msg.json()
                                # Fix 55: detect slotSubscribe notification by result shape
                                result = data.get("params", {}).get("result", {})
                                if result and isinstance(result, dict) and "slot" in result:
                                    self.last_slot_msg_time = self.last_msg_time
                                else:
                                    await self._handle_account_notification(data)
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error(f"WebSocket error: {msg}")
                                break

            except Exception as e:
                logger.error(f"PoolStateManager connection error: {e}")
                if self.running:
                    logger.info(f"Reconnecting in {reconnect_delay} seconds...")
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 60.0)  # Exponential backoff, max 60s

        logger.info("PoolStateManager stopped")

    async def stop(self):
        """Stop the WebSocket connection."""
        self.running = False
        if self.watchdog_task:
            self.watchdog_task.cancel()
        if self.websocket:
            await self.websocket.close()

    async def _subscribe_to_pool(self, ws, pool_address: str) -> Optional[int]:
        """Subscribe to a specific pool address."""
        try:
            subscription_msg = {
                "jsonrpc": "2.0",
                "id": len(self.subscription_ids) + 1,  # Unique ID
                "method": "accountSubscribe",
                "params": [
                    pool_address,
                    {
                        "encoding": "jsonParsed",
                        "commitment": "confirmed"
                    }
                ]
            }
            await ws.send_json(subscription_msg)
            
            # Wait for subscription confirmation
            try:
                response = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                subscription_id = response.get("result")
                if subscription_id:
                    self.sub_to_pool[subscription_id] = pool_address
                    return subscription_id
            except Exception as e:
                logger.error(f"Failed to get subscription ID for {pool_address}: {e}")
            
            return None
        except Exception as e:
            logger.debug(f"Failed to subscribe to pool {pool_address}: {e}")
            return None

    async def _handle_account_notification(self, notification: Dict[str, Any]):
        """Process account notification and update pool state."""
        try:
            params = notification.get("params", {})
            result = params.get("result", {})
            context = result.get("context", {})
            account_data = result.get("value", {})

            if not account_data:
                return

            sub_id = params.get("subscription")
            if not sub_id:
                return

            account_pubkey = self.sub_to_pool.get(sub_id)
            if not account_pubkey:
                return

            # Decode pool reserves based on pool type
            pool_reserve = await self._decode_pool_reserves(account_pubkey, account_data)
            if pool_reserve:
                self.pool_states[account_pubkey] = pool_reserve

                # Trigger arbitrage evaluation for updated pool
                for callback in self.arbitrage_callbacks:
                    try:
                        await callback(account_pubkey, pool_reserve)
                    except Exception as e:
                        logger.error(f"Arbitrage callback error: {e}")

        except Exception as e:
            logger.debug(f"Account notification processing error: {e}")

    async def _decode_pool_reserves(self, pool_address: str, account_data: Dict[str, Any]) -> Optional[PoolReserve]:
        """Decode reserves from account data based on DEX program."""
        try:
            # Raydium CPMM decoding
            if "parsed" in account_data and "info" in account_data["parsed"]:
                info = account_data["parsed"]["info"]

                token_a_reserve = Decimal(str(info.get("tokenAAmount", 0)))
                token_b_reserve = Decimal(str(info.get("tokenBAmount", 0)))
                token_a_mint = info.get("mintA", "")
                token_b_mint = info.get("mintB", "")

                if token_a_reserve > 0 and token_b_reserve > 0:
                    return PoolReserve(
                        token_a_reserve, token_b_reserve,
                        token_a_mint, token_b_mint, pool_address, "cpmm"
                    )

            # Meteora DLMM decoding (simplified)
            elif "data" in account_data and len(account_data["data"]) > 0:
                # Decode Meteora active bin data
                # This would decode specific Meteora layout for active bin reserves
                logger.debug(f"Meteora DLMM update for {pool_address}")
                # Placeholder - would need Meteora-specific decoding
                pass

            # Saber Stableswap decoding (placeholder)
            elif pool_address.startswith("SS"):  # Saber program ID prefix
                logger.debug(f"Saber Stableswap update for {pool_address}")
                # Placeholder - would need Saber-specific decoding
                pass

        except Exception as e:
            logger.debug(f"Pool reserve decoding error: {e}")

        return None

    def get_pool_state(self, pool_address: str) -> Optional[PoolReserve]:
        """Get current pool state from memory."""
        return self.pool_states.get(pool_address)

    def get_all_pool_states(self) -> Dict[str, PoolReserve]:
        """Get all current pool states."""
        return self.pool_states.copy()

    def get_pools_by_token(self, token_mint: str) -> List[PoolReserve]:
        """Get all pools containing a specific token."""
        return [
            pool for pool in self.pool_states.values()
            if pool.token_a_mint == token_mint or pool.token_b_mint == token_mint
        ]

    def get_pool_count(self) -> int:
        """Get total number of tracked pools."""
        return len(self.pool_states)

    def get_update_stats(self) -> Dict[str, Any]:
        """Get statistics about pool updates."""
        if not self.pool_states:
            return {"pools": 0, "updates_per_second": 0}

        current_time = asyncio.get_event_loop().time()
        recent_updates = sum(
            1 for pool in self.pool_states.values()
            if current_time - pool.last_update < 60  # Last minute
        )

        return {
            "pools": len(self.pool_states),
            "recent_updates": recent_updates,
            "updates_per_second": recent_updates / 60.0 if recent_updates > 0 else 0
        }