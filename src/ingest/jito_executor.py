"""JitoExecutor class that subscribes to tip_stream and sends transactions as send_bundle."""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Callable
import aiohttp
import websockets
import base58
import random
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

logger = logging.getLogger(__name__)

class JitoExecutor:
    """Executor that subscribes to Jito tip_stream and sends bundles."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        tip_stream_url: Optional[str] = None,
        bundle_endpoint: Optional[str] = None,
        timeout: float = 30.0,
        keypair: Optional[Keypair] = None
    ):
        self.keypair = keypair
        # Use environment variables with defaults
        self.session = session
        self.tip_stream_url = tip_stream_url or os.getenv(
            "JITO_TIP_STREAM_URL", "https://bundles-api-rest.jito.wtf/api/v1/bundles/tip_floor"
        )
        self.bundle_endpoint = bundle_endpoint or os.getenv(
            "JITO_RPC_URL", "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
        )
        self.endpoints = [  # Fix 89: regional shotgun
            "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles",
        ]
        self._tip_backoff = 0  # Exponential backoff counter for tip API failures
        self.timeout = timeout
        self.current_tip_data = None
        # Phase 35: Dynamic Jito Tip Accounts
        self.tip_accounts = ["96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"]
        self.tip_subscription_task = None
        self._running = False

    async def start(self):
        """Start the tip stream subscription."""
        if self._running:
            return
        self._running = True
        # Phase 35: Fetch tip accounts on startup
        await self.fetch_tip_accounts()
        self.tip_subscription_task = asyncio.create_task(self._subscribe_to_tip_stream())

    async def stop(self):
        """Stop the tip stream subscription."""
        self._running = False
        if self.tip_subscription_task:
            self.tip_subscription_task.cancel()
            try:
                await self.tip_subscription_task
            except asyncio.CancelledError:
                pass

    async def fetch_tip_accounts(self) -> bool:
        """Fetch live Jito tip accounts (Phase 35)."""
        if not self.session:
            return False
        try:
            url = "https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_accounts"
            async with self.session.get(url, timeout=5.0) as resp:
                if resp.status == 200:
                    accounts = await resp.json()
                    if accounts and isinstance(accounts, list):
                        self.tip_accounts = accounts
                        logger.info(f"🔄 Jito tip accounts updated: {len(self.tip_accounts)} active accounts")
                        return True
        except Exception as e:
            logger.warning(f"Failed to fetch dynamic Jito tip accounts: {e}")
        return False

    async def get_jito_tip(self, priority: str = "normal") -> float:
        default = 0.00009
        endpoints = [
            "https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_floor",
            "https://bundles-api-rest.jito.wtf/api/v1/bundles/tip_floor",
            "https://api.jito.wtf/api/v1/bundles/tip_floor"
        ]

        mult = {"critical": 2.8, "high": 1.8, "normal": 1.0}.get(priority, 1.0)

        for ep in endpoints:
            for attempt in range(3):
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4)) as s:
                        async with s.get(ep) as r:
                            if r.status == 200:
                                data = await r.json()
                                tip = float(data[0].get("landed_tips_25th_percentile", default))
                                final = max(tip * mult, 0.00005)
                                logger.info(f"✅ Tip loaded: {final:.8f} SOL")
                                return final
                except:
                    await asyncio.sleep(0.7)

        logger.warning(f"Tip fallback → {default}")
        return default

    async def _subscribe_to_tip_stream(self):
        """Poll Jito tip floor API with multiple endpoints and backoff."""
        while self._running:
            try:
                tip = await self.get_jito_tip()
                # Phase 35: Use dynamic tip accounts
                self.current_tip_data = {
                    "tip_floor": [{"pubkey": acc, "lamports": int(tip * 1e9)} for acc in self.tip_accounts]
                }
                self._tip_backoff = 0
            except Exception as e:
                logger.error(f"Tip floor API error: {e}")
                self._tip_backoff = min(self._tip_backoff + 1, 5)
            sleep_time = 2.5 * (2 ** self._tip_backoff)
            await asyncio.sleep(sleep_time)

    def get_current_tip_info(self) -> Optional[Dict[str, Any]]:
        """Get current tip information from polled API, with fallback to default tip."""
        if not self.current_tip_data or "tip_floor" not in self.current_tip_data:
            # Fallback to default tip if no data available
            logger.warning("No tip data available, using fallback tip")
            return {
                "recommended_tip": 85000,  # 0.000085 SOL safe fallback
                "tip_accounts": ["96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU"],  # Default Jito tip account
                "full_data": None
            }

        tip_floor = self.current_tip_data["tip_floor"]
        if not tip_floor:
            # Fallback
            logger.warning("Tip floor data empty, using fallback tip")
            return {
                "recommended_tip": 85000,
                "tip_accounts": self.tip_accounts,
                "full_data": None
            }

        # Find tip with highest lamports (recommended tip)
        best_tip = max(tip_floor, key=lambda x: x["lamports"])
        return {
            "recommended_tip": best_tip["lamports"],
            "tip_accounts": [tip["pubkey"] for tip in tip_floor],
            "full_data": self.current_tip_data
        }

    async def send_bundle(
        self,
        transactions: List[VersionedTransaction],
        tip_amount_lamports: int = 0,
    ) -> Dict[str, Any]:
        """Send a bundle of transactions via Jito.

        Args:
            transactions: List of VersionedTransaction objects
            tip_amount_lamports: Tip amount in lamports (will use tip stream if available)

        Returns:
            Dict with bundle result
        """
        # Phase 31: Enforce Jito bundle limit (Max 5 transactions)
        if len(transactions) > 5:
            logger.error(f"❌ Bundle rejected: {len(transactions)} transactions exceeds Jito limit of 5")
            return {"success": False, "error": f"Bundle limit exceeded: {len(transactions)} > 5"}

        if not self.session:
            raise RuntimeError("HTTP session not available")

        # Phase 48: Tip injection DISABLED here - only tx_builder.py does secure tip merge
        # jito_executor just forwards the already-signed tx with tip inside
        # (prevents double-tip and signature corruption)

        # Convert transactions to base58
        tx_base58 = [base58.b58encode(bytes(tx)).decode('ascii') for tx in transactions]

        bundle = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [tx_base58],
        }

        # Fix 89: Regional Bundle Shotgun - simultaneous send, first success wins
        async def _send_to_region(url):
            try:
                async with self.session.post(
                    url, json=bundle, headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return {"success": True, "bundle_id": result.get("result"), "region": url}
                    return {"success": False, "error": await resp.text(), "region": url}
            except Exception as e:
                return {"success": False, "error": str(e), "region": url}

        results = await asyncio.gather(*[_send_to_region(url) for url in self.endpoints], return_exceptions=True)
        for r in results:
            if isinstance(r, dict) and r.get("success"):
                logger.info(f"✅ Bundle landed via {r.get('region')}: {r.get('bundle_id')}")
                return r
        return {"success": False, "error": "All regional endpoints failed"}

    async def wait_for_confirmation(
        self,
        bundle_id: str,
        max_wait_time: float = 3.0,  # HFT: drop after 3s
        check_interval: float = 0.5,
    ) -> Dict[str, Any]:
        """Wait for bundle confirmation.

        Args:
            bundle_id: Bundle ID to monitor
            max_wait_time: Maximum wait time in seconds
            check_interval: Check interval in seconds

        Returns:
            Dict with confirmation status
        """
        import time
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            try:
                status_request = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getBundleStatuses",
                    "params": [[bundle_id]],
                }

                async with self.session.post(
                    self.bundle_endpoint,
                    json=status_request,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10.0)
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if "result" in result and bundle_id in result["result"]:
                            status_info = result["result"][bundle_id]
                            confirmation_status = status_info.get("confirmation_status")

                            if confirmation_status in ["confirmed", "finalized", "failed"]:
                                logger.info(f"Bundle {bundle_id} status: {confirmation_status}")
                                return {
                                    "bundle_id": bundle_id,
                                    "status": confirmation_status,
                                    "details": status_info,
                                }

                await asyncio.sleep(check_interval)

            except Exception as e:
                logger.error(f"Status check error: {e}")
                await asyncio.sleep(check_interval)

        logger.warning(f"Bundle {bundle_id} confirmation timeout")
        return {
            "bundle_id": bundle_id,
            "status": "timeout",
        }