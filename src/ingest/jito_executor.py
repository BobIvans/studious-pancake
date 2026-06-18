"""JitoExecutor — HTTP REST bundle submission to regional endpoints.

Replaces gRPC with HTTP POST shotgun (aiohttp).
The "first-accepted-wins" regional shotgun semantics are preserved.
Auth: REST API is fully public — no JWT handshake needed.
"""

from __future__ import annotations

import asyncio
import base58
import logging
import os
import time
from typing import Any, Dict, List, Optional, Callable
import aiohttp
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

logger = logging.getLogger(__name__)

# ── Jito HTTP endpoints ───────────────────────────────────────────────────────
JITO_STATUS_ENDPOINT = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"

# ── Regional Block Engine HTTP endpoints ──────────────────────────────────────
JITO_HTTP_ENDPOINTS: List[str] = [
    "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles",
    "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1/bundles",
    "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
    "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles",
]


class JitoExecutor:
    """Executor that subscribes to Jito tip stream and fires bundles via HTTP REST."""

    def __init__(
        self,
        session:        Optional[aiohttp.ClientSession] = None,
        tip_stream_url: Optional[str]                     = None,
        bundle_endpoint: Optional[str]                    = None,
        timeout:        float                             = 30.0,
        keypair:        Optional[Keypair]                 = None,
    ):
        self.keypair          = keypair
        self.session          = session
        self.bundle_endpoint  = bundle_endpoint or os.getenv(
            "JITO_RPC_URL", JITO_STATUS_ENDPOINT
        )
        self.endpoints        = JITO_HTTP_ENDPOINTS
        self.timeout          = timeout
        self.current_tip_data = None

        # Phase 35: Dynamic Jito tip accounts
        self.tip_accounts = [
            "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
            "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bLmis",
            "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLk",
            "ADuUkR4vqLUMWXxW9gh6D6L8pMSawDBQW5ypTcRqMoKY",
            "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
            "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
            "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
            "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBVCmLzFZu"
        ]
        self.tip_subscription_task     = None
        self._tip_accounts_refresh_task: Optional[asyncio.Task] = None
        self._running                  = False

        # ── Ghost Balance Recovery ────────────────────────────────────────────
        self.pending_bundles: Dict[str, Dict[str, Any]]       = {}
        self._reconciliation_task: Optional[asyncio.Task]     = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self.fetch_tip_accounts()

        self.tip_subscription_task        = asyncio.create_task(self._subscribe_to_tip_stream())
        self._tip_accounts_refresh_task   = asyncio.create_task(self._periodic_tip_accounts_refresh())
        self._reconciliation_task         = asyncio.create_task(self._reconcile_pending())

    async def stop(self) -> None:
        self._running = False
        for task in (self.tip_subscription_task,
                     self._tip_accounts_refresh_task,
                     self._reconciliation_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.tip_subscription_task       = None
        self._tip_accounts_refresh_task  = None
        self._reconciliation_task        = None

    # ── Tip account management ──────────────────────────────────────────────────

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
                        logger.info(f"🔄 Jito tip accounts updated: {len(self.tip_accounts)} active")
                        return True
        except Exception as exc:
            logger.warning(f"Tip-account fetch failed: {exc}")
        return False

    async def get_jito_tip(self, priority: str = "normal") -> float:
        default = 0.00009
        endpoints = [
            "https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_floor",
            "https://bundles-api-rest.jito.wtf/api/v1/bundles/tip_floor",
            "https://api.jito.wtf/api/v1/bundles/tip_floor",
        ]
        mult = {"critical": 2.8, "high": 1.8, "normal": 1.0}.get(priority, 1.0)
        for ep in endpoints:
            for attempt in range(3):
                try:
                    async with aiohttp.ClientSession() as s:
                        async with s.get(ep) as r:
                            if r.status == 200:
                                data = await r.json()
                                tip_value = None

                                if isinstance(data, list) and len(data) > 0:
                                    tip_value = data[0].get("landed_tips_25th_percentile")
                                elif isinstance(data, dict):
                                    tip_value = data.get("landed_tips_25th_percentile")

                                if tip_value is not None:
                                    return max(float(tip_value) * mult, 0.00005)
                except Exception:
                    await asyncio.sleep(0.7)
        logger.warning(f"Tip fallback → {default}")
        return default

    async def _subscribe_to_tip_stream(self) -> None:
        """Background tip-rotation loop."""
        self._tip_backoff = 0
        while self._running:
            try:
                tip = await self.get_jito_tip()
                self.current_tip_data = {
                    "tip_floor": [
                        {"pubkey": acc, "lamports": int(tip * 1e9)}
                        for acc in self.tip_accounts
                    ]
                }
                self._tip_backoff = 0
            except Exception as exc:
                logger.error(f"Tip stream error: {exc}")
                self._tip_backoff = min(self._tip_backoff + 1, 5)
            sleep_time = 2.5 * (2 ** self._tip_backoff)
            await asyncio.sleep(sleep_time)

    def get_current_tip_info(self) -> Optional[Dict[str, Any]]:
        if not self.current_tip_data or "tip_floor" not in self.current_tip_data:
            return {
                "recommended_tip": 85_000,
                "tip_accounts":    self.tip_accounts,
                "full_data":       None,
            }
        tip_floor = self.current_tip_data["tip_floor"]
        if not tip_floor:
            return {
                "recommended_tip": 85_000,
                "tip_accounts":    self.tip_accounts,
                "full_data":       None,
            }
        best = max(tip_floor, key=lambda x: x["lamports"])
        return {
            "recommended_tip": best["lamports"],
            "tip_accounts":    [t["pubkey"] for t in tip_floor],
            "full_data":       self.current_tip_data,
        }

    async def get_jito_rtt_ms(self) -> float:
        """Measure network RTT to Jito endpoint."""
        if not self.session:
            return 0.0
        try:
            url = "https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_accounts"
            start = time.time()
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
                if resp.status == 200:
                    await resp.json()
                    return (time.time() - start) * 1000
        except Exception:
            pass
        return 999.0

    async def _periodic_tip_accounts_refresh(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(600)
                refreshed = await self.fetch_tip_accounts()
                if refreshed:
                    logger.info(
                        f"🔄 Jito tip_accounts refreshed: "
                        f"{len(self.tip_accounts)} active (10-min poll)"
                    )
            except Exception as exc:
                logger.debug(f"Periodic tip-accounts refresh error: {exc}")
                await asyncio.sleep(60)

    # ── Ghost Balance Recovery ─────────────────────────────────────────────────

    def _record_pending(self, bundle_id: str, deducted_amount: float) -> None:
        if bundle_id and deducted_amount > 0:
            self.pending_bundles[bundle_id] = {
                "deducted": deducted_amount,
                "sent_at":  time.time(),
                "refunded": False,
            }

    def _confirm_pending(self, bundle_id: str) -> None:
        entry = self.pending_bundles.pop(bundle_id, None)
        if entry:
            logger.debug(
                f"✅ Bundle {bundle_id[:12]} confirmed — "
                f"deducted {entry['deducted']:.8f} SOL kept final."
            )

    async def _reconcile_pending(self) -> None:
        while self._running:
            try:
                now            = time.time()
                stale_seconds  = 8.0
                refunded_total = 0.0

                for bid, meta in list(self.pending_bundles.items()):
                    if meta.get("refunded"):
                        continue
                    if now - meta.get("sent_at", now) < stale_seconds:
                        continue
                    refund       = meta["deducted"]
                    meta["refunded"] = True
                    refunded_total += refund
                    try:
                        from src.ingest.shared_state import stats, stats_lock
                        async with stats_lock:  # type: ignore[misc]
                            stats["virtual_balance"] += refund
                        logger.warning(
                            f"⚡ Ghost bundle {bid[:12]} refunded {refund:.8f} SOL"
                        )
                    except Exception as exc:
                        logger.debug(f"Ghost-balance refund unavailable: {exc}")

                self.pending_bundles = {
                    k: v for k, v in self.pending_bundles.items()
                    if not v.get("refunded")
                }

                if refunded_total > 0:
                    logger.info(f"🔄 Reconciliation: {refunded_total:.8f} SOL ghost refunded")

            except Exception as exc:
                logger.debug(f"Reconciliation error: {exc}")
            await asyncio.sleep(8.0)

    # ── HTTP SendBundle ─────────────────────────────────────────────────────────

    async def send_bundle(
        self,
        transactions:         List[VersionedTransaction],
        tip_amount_lamports:  int          = 0,
        deducted_amount:      float        = 0.0,
    ) -> Dict[str, Any]:
        """Fire a bundle to all 4 regional endpoints via HTTP POST; first success wins."""

        # ── ИСПРАВЛЕНИЕ: Абсолютный блокиратор реальных транзакций в Paper Mode ──
        if str(os.getenv("PAPER_TRADING_ONLY", "false")).lower() == "true":
            logger.info("🧪 [PAPER MODE JITO] Блокировка отправки бандла на Mainnet.")
            fake_id = "paper_bundle_" + str(int(time.time() * 1000))
            if deducted_amount > 0:
                self._record_pending(fake_id, deducted_amount)
                # confirmer_task will handle reconciliation
            return {"success": True, "bundle_id": fake_id, "region": "paper_simulator"}

        if len(transactions) > 5:
            logger.error(
                f"❌ Bundle rejected: {len(transactions)} txns > Jito limit of 5"
            )
            return {
                "success": False,
                "error":   f"Bundle limit exceeded: {len(transactions)} > 5",
            }

        # Encode transactions to Base58 for HTTP API
        tx_base58_list = [base58.b58encode(bytes(tx)).decode("ascii") for tx in transactions]

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [tx_base58_list]
        }

        headers = {"Content-Type": "application/json"}

        logger.debug(
            f"🔫 HTTP Shotgun: firing bundle to {len(self.endpoints)} regions"
        )

        tasks = []
        for url in self.endpoints:
            tasks.append(asyncio.create_task(self._send_http(url, payload, headers)))

        done_pending = set()
        first_success: Optional[Dict[str, Any]] = None

        while tasks and first_success is None:
            done_now, tasks = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED, timeout=3.0
            )
            done_pending |= done_now
            for t in done_now:
                try:
                    result = t.result()
                except Exception:
                    result = {"success": False, "error": "exception", "region": "unknown"}
                if isinstance(result, dict) and result.get("success"):
                    first_success = result
                    break

            for t in tasks:
                t.cancel()
            if first_success:
                break

        if first_success:
            bundle_id = first_success.get("bundle_id", "")
            logger.info(
                f"✅ Bundle landed via {first_success.get('region')}: {bundle_id}"
            )
            if bundle_id and deducted_amount > 0:
                self._record_pending(bundle_id, deducted_amount)
            return first_success

        logger.error("⚠️ All HTTP regional endpoints returned failure")
        return {"success": False, "error": "All HTTP regional endpoints failed"}

    async def _send_http(
        self,
        endpoint:    str,
        payload:     dict,
        headers:     dict,
    ) -> Dict[str, Any]:
        if not self.session:
            return {"success": False, "error": "No session", "region": endpoint}
        try:
            async with self.session.post(endpoint, json=payload, headers=headers, timeout=5.0) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data:
                        return {
                            "success":  True,
                            "bundle_id": data["result"],
                            "region":   endpoint,
                        }
                    return {"success": False, "error": f"JSON-RPC error: {data}", "region": endpoint}
                return {"success": False, "error": f"HTTP {resp.status}", "region": endpoint}
        except Exception as exc:
            return {"success": False, "error": str(exc), "region": endpoint}

    # ── Status confirmation ────────────────────────────────────────────────────

    async def wait_for_confirmation(
        self,
        bundle_id:       str,
        max_wait_time:   float  = 3.0,
        check_interval:  float  = 0.5,
    ) -> Dict[str, Any]:
        start = time.time()
        while time.time() - start < max_wait_time:
            try:
                if self.session:
                    status_request = {
                        "jsonrpc": "2.0", "id": 1,
                        "method":  "getBundleStatuses",
                        "params":  [[bundle_id]],
                    }
                    async with self.session.post(
                        self.bundle_endpoint,
                        json=status_request,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=5.0),
                    ) as resp:
                        if resp.status == 200:
                            result = await resp.json()
                            if "result" in result and result["result"]["value"]:
                                for item in result["result"]["value"]:
                                    if item and item.get("bundle_id") == bundle_id:
                                        info = item
                                        confirmation = info.get("confirmation_status", "")
                                        if confirmation in {"confirmed", "finalized"}:
                                            logger.info(f"Bundle {bundle_id} status: {confirmation}")
                                            self._confirm_pending(bundle_id)
                                            return {
                                                "bundle_id": bundle_id,
                                                "status":    confirmation,
                                                "details":   info,
                                            }
                                        elif confirmation == "failed":
                                            return {
                                                "bundle_id": bundle_id,
                                                "status":    "failed",
                                                "details":   info,
                                            }
                                        break
            except Exception as exc:
                logger.error(f"Status check error: {exc}")
            await asyncio.sleep(check_interval)

        logger.warning(f"Bundle {bundle_id} confirmation timeout")
        return {"bundle_id": bundle_id, "status": "timeout"}
