"""JitoExecutor class that subscribes to tip_stream and sends transactions as send_bundle."""

import asyncio
import json
import logging
import os
import time
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
        logger.critical("🚨 JITO TIP ACCOUNTS OUTDATED: Using hardcoded fallback! Update via fetch_tip_accounts() API.")
        self.tip_subscription_task = None
        self._tip_accounts_refresh_task = None  # Fix 95: 10-min periodic refresh
        self._running = False

        # ─── Ghost Balance Recovery ───────────────────────────────────────────
        # Track bundles whose confirmed/denied status is still unknown.
        # If a bundle confirms we remove it here.
        # The background reconciliation task removes stale entries (> 8 s old) and
        # pushes the deducted amount back into the global virtual_balance so
        # the bot never "freezes" just because Jito silently dropped a bundle.
        self.pending_bundles: Dict[str, Dict[str, Any]] = {}
        self._reconciliation_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the tip stream subscription and reconciliation task."""
        if self._running:
            return
        self._running = True
        # Phase 35: Fetch tip accounts on startup
        await self.fetch_tip_accounts()
        self.tip_subscription_task = asyncio.create_task(self._subscribe_to_tip_stream())
        # Fix 95: Refresh Jito tip_accounts list every 10 min (they rotate; hardcoded is stale after a few minutes)
        self._tip_accounts_refresh_task = asyncio.create_task(self._periodic_tip_accounts_refresh())
        # Ghost Balance Recovery: background reconciliation every 8 s
        self._reconciliation_task = asyncio.create_task(self._reconcile_pending())

    async def stop(self):
        """Stop all background tasks."""
        self._running = False
        for task in (self.tip_subscription_task, self._tip_accounts_refresh_task, self._reconciliation_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.tip_subscription_task = None
        self._tip_accounts_refresh_task = None  # Fix 95
        self._reconciliation_task = None

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
            logger.warning("JitoExecutor: No tip data available from stream, using fallback tip account.")
            return {
                "recommended_tip": 85000,  # 0.000085 SOL safe fallback
                "tip_accounts": self.tip_accounts,  # dynamic (previously fetched) or hardcoded fallback
                "full_data": None
            }

        tip_floor = self.current_tip_data["tip_floor"]
        if not tip_floor:
            # Fallback
            logger.warning("JitoExecutor: Tip floor data empty, using fallback tip account.")
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

    # ─── Ghost Balance Recovery ────────────────────────────────────────────────

    def _record_pending(self, bundle_id: str, deducted_amount: float) -> None:
        """Register a bundle in the pending set with its virtual-balance deduction."""
        if bundle_id and deducted_amount > 0:
            self.pending_bundles[bundle_id] = {
                "deducted": deducted_amount,
                "sent_at": time.time(),
                "refunded": False,
            }

    def _confirm_pending(self, bundle_id: str) -> None:
        """Remove a bundle from the pending set on confirmed landing."""
        entry = self.pending_bundles.pop(bundle_id, None)
        if entry:
            logger.debug(
                f"✅ Bundle {bundle_id[:12]} confirmed — "
                f"deducted {entry['deducted']:.8f} SOL kept final."
            )

    async def _reconcile_pending(self) -> None:
        """Background task: every 8 s, refund ghost bundles (no confirmation after 8 s)."""
        while self._running:
            try:
                now = time.time()
                stale_seconds = 8.0  # Jito confirms in < 400 ms; >8 s = ghost
                refunded_total = 0.0

                for bid, meta in list(self.pending_bundles.items()):
                    if meta.get("refunded"):
                        continue
                    if now - meta.get("sent_at", now) < stale_seconds:
                        continue
                    refund = meta["deducted"]
                    meta["refunded"] = True
                    refunded_total += refund
                    # Push back into global virtual_balance
                    try:
                        from arb_bot import stats, stats_lock
                        async with stats_lock:  # type: ignore[misc]
                            stats["virtual_balance"] += refund
                        logger.warning(
                            f"⚡ Bundle Dropped: Reconciled — ghost bundle {bid[:12]} "
                            f"refunded {refund:.8f} SOL "
                            f"→ virtual_balance (gone after {(now - meta['sent_at']):.1f}s)"
                        )
                    except Exception as _e:
                        logger.debug(f"Ghost balance refund unavailable: {_e}")

                self.pending_bundles = {
                    k: v for k, v in self.pending_bundles.items()
                    if not v.get("refunded")
                }

                if refunded_total > 0:
                    logger.info(f"🔄 Reconciliation: {refunded_total:.8f} SOL ghost refunded")

            except Exception as _e:
                logger.debug(f"Reconciliation error: {_e}")
            await asyncio.sleep(8.0)

    # ─── Periodic Jito Tip-Accounts Refresh (Fix 95) ──────────────────────────
    async def _periodic_tip_accounts_refresh(self) -> None:
        """Refresh Jito tip_accounts list every 10 min."""
        while self._running:
            try:
                await asyncio.sleep(600)  # 10 minutes
                refreshed = await self.fetch_tip_accounts()
                if refreshed:
                    logger.info(f"🔄 Jito tip_accounts refreshed: {len(self.tip_accounts)} accounts active (10-min poll)")
            except Exception as e:
                logger.debug(f"Tip-accounts periodic refresh error: {e}")
                await asyncio.sleep(60)

    async def send_bundle(
        self,
        transactions: List[VersionedTransaction],
        tip_amount_lamports: int = 0,
        deducted_amount: float = 0.0,
    ) -> Dict[str, Any]:
        """Send a bundle of transactions via Jito.

        Args:
            transactions: List of VersionedTransaction objects
            tip_amount_lamports: Tip amount in lamports (will use tip stream if available)
            deducted_amount: Amount already deducted from virtual_balance (for ghost recovery)

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
                bundle_id = r.get("bundle_id", "")
                logger.info(f"✅ Bundle landed via {r.get('region')}: {bundle_id}")
                # Ghost Balance Recovery: record this bundle for reconciliation
                if bundle_id and deducted_amount > 0:
                    self._record_pending(bundle_id, deducted_amount)
                return r
        return {"success": False, "error": "All regional endpoints failed"}

    async def wait_for_confirmation(
        self,
        bundle_id: str,
        max_wait_time: float = 0.8,  # HFT: 2 slots ≈ 800ms, then ghost
        check_interval: float = 0.4,
    ) -> Dict[str, Any]:
        """Wait for bundle confirmation.

        Args:
            bundle_id: Bundle ID to monitor
            max_wait_time: Maximum wait time in seconds (800ms HFT = 2 Solana slots)
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
                                # Ghost Balance Recovery: remove from pending — confirmed path handles balance
                                self._confirm_pending(bundle_id)
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