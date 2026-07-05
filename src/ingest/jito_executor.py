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
    "https://bundles.jito.wtf/api/v1/bundles",
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
        # FIX 206: Use regional fallback for status queries (use module-level constant; self.endpoints not yet initialized)
        self.bundle_endpoint  = bundle_endpoint or os.getenv(
            "JITO_RPC_URL", JITO_HTTP_ENDPOINTS[0] if JITO_HTTP_ENDPOINTS else JITO_STATUS_ENDPOINT
        )
        if str(os.getenv("STRICT_JITO_MODE", "false")).lower() == "true":
            self.endpoints = JITO_HTTP_ENDPOINTS
        else:
            self.endpoints = JITO_HTTP_ENDPOINTS
        self.timeout          = timeout
        self.current_tip_data = None

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
        # FIX 251: Launch TCP window warmer to keep connections hot
        self._tcp_window_warmer_task        = asyncio.create_task(self._tcp_window_warmer())
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
        self._tcp_window_warmer_task       = None
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
            "https://bundles.jito.wtf/api/v1/bundles/tip_floor",
            "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles/tip_floor",
            "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1/bundles/tip_floor",
            "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles/tip_floor",
            "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles/tip_floor",
        ]
        mult = {"critical": 2.8, "high": 1.8, "normal": 1.0}.get(priority, 1.0)
        
        session_to_use = self.session
        temp_session = None
        if session_to_use is None or session_to_use.closed:
            import os
            proxy_url = os.getenv("PROXY_URL")
            if proxy_url and proxy_url.startswith("socks5"):
                try:
                    from aiohttp_socks import ProxyConnector
                    connector = ProxyConnector.from_url(proxy_url, limit=10)
                except ImportError:
                    connector = None
            else:
                connector = None
            temp_session = aiohttp.ClientSession(connector=connector)
            session_to_use = temp_session

        try:
            for ep in endpoints:
                for attempt in range(3):
                    try:
                        async with session_to_use.get(ep) as r:
                            if r.status == 200:
                                data = await r.json()
                                tip_value = None

                                if isinstance(data, list) and len(data) > 0:
                                    tip_value = data[0].get("landed_tips_25th_percentile")
                                elif isinstance(data, dict):
                                    tip_value = data.get("landed_tips_25th_percentile")

                                if tip_value is not None:
                                    if temp_session:
                                        await temp_session.close()
                                    return max(float(tip_value) * mult, 0.00005)
                    except Exception:
                        await asyncio.sleep(0.7)
            logger.warning(f"Tip fallback → {default}")
            return default
        finally:
            if temp_session and not temp_session.closed:
                await temp_session.close()

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
        """Return cached RTT to Jito endpoint (background poll every 30s).
        
        FIX 253: Eliminates 100-300ms blocking HTTP latency from the hot path.
        Uses background polling with fire-and-forget update task.
        """
        if not hasattr(self, "_cached_rtt"):
            self._cached_rtt = 50.0  # Reasonable default before first measure
            self._last_rtt_poll = 0.0
        
        now = time.time()
        if now - self._last_rtt_poll > 30.0:
            self._last_rtt_poll = now
            
            async def _update_rtt():
                if not self.session:
                    return
                try:
                    url = "https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_accounts"
                    start = time.time()
                    async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
                        if resp.status == 200:
                            await resp.json()
                            self._cached_rtt = (time.time() - start) * 1000
                except Exception:
                    self._cached_rtt = 999.0  # Network error
            
            # Fire-and-forget background task — never blocks hot path
            task = asyncio.create_task(_update_rtt())
            if hasattr(shared_state, "active_tasks"):
                shared_state.active_tasks.add(task)
                task.add_done_callback(shared_state.active_tasks.discard)
        
        return self._cached_rtt

    # FIX 251: Прогрев TCP-соединений со всеми регионами Jito (исключение задержки холодного старта)
    async def _tcp_window_warmer(self) -> None:
        """Удерживает TCP-соединения со всеми регионами Jito прогретыми (раз в 2.5 сек)."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getTipAccounts", "params": []}
        headers = {"Content-Type": "application/json"}
        while self._running:
            try:
                tasks = []
                for ep in self.endpoints:
                    tasks.append(
                        self.session.post(ep, json=payload, headers=headers, timeout=0.5)
                    )
                responses = await asyncio.gather(*tasks, return_exceptions=True)
                for resp in responses:
                    if isinstance(resp, aiohttp.ClientResponse):
                        await resp.release()
            except Exception:
                pass
            await asyncio.sleep(2.5)

    # FIX 296: Adaptive tip boost for micro-trades (Blue Ocean strategy)
    def calculate_blue_ocean_tip(self, expected_profit_sol: float, base_tip_lamports: int = 85000) -> int:
        if expected_profit_sol <= 0.001:
            tip_pct = 0.80
        else:
            tip_pct = 0.40
        return max(int(expected_profit_sol * tip_pct * 1e9), base_tip_lamports)

    async def _periodic_tip_accounts_refresh(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(60)  # FIX 273: Снижено с 600 до 60 секунд для исключения слепой зоны
                refreshed = await self.fetch_tip_accounts()
                if refreshed:
                    logger.debug(
                        f"🔄 Jito tip_accounts refreshed: "
                        f"{len(self.tip_accounts)} active (1-min poll)"
                    )
            except Exception as exc:
                logger.debug(f"Periodic tip-accounts refresh error: {exc}")
                await asyncio.sleep(10)  # FIX 273: Быстрый повтор при ошибке

    # ── Ghost Balance Recovery ─────────────────────────────────────────────────

    # FIX 177: Append transaction signatures to memory cache when logging pending bundles
    def _record_pending(self, bundle_id: str, deducted_amount: float, signatures: Optional[List[str]] = None) -> None:
        if bundle_id and deducted_amount > 0:
            self.pending_bundles[bundle_id] = {
                "deducted": deducted_amount,
                "sent_at":  time.time(),
                "refunded": False,
                "signatures": signatures or []  # FIX 177
            }

    def _confirm_pending(self, bundle_id: str) -> None:
        entry = self.pending_bundles.pop(bundle_id, None)
        if entry:
            # FIX 246: Check if bundle was already refunded (late landing correction)
            if entry.get("refunded", False):
                deducted = entry.get("deducted", 0.0)
                if deducted > 0:
                    async def _re_deduct():
                        async with shared_state.stats_lock:
                            shared_state.stats["virtual_balance"] = max(
                                0.0, shared_state.stats["virtual_balance"] - deducted
                            )
                    asyncio.create_task(_re_deduct())
                    logger.warning(
                        f"⚠️ Late Landing Correction: Bundle {bundle_id[:12]} confirmed AFTER refund! "
                        f"Re-deducting {deducted:.8f} SOL from virtual_balance."
                    )
            else:
                logger.debug(
                    f"✅ Bundle {bundle_id[:12]} confirmed — "
                    f"deducted {entry['deducted']:.8f} SOL kept final."
                )
            # Этап 1: Update inflight bundle status to confirmed
            try:
                from src.ingest.shared_state import data_aggregator
                if data_aggregator and hasattr(data_aggregator, 'update_inflight_status'):
                    asyncio.create_task(data_aggregator.update_inflight_status(bundle_id, 'confirmed'))
            except Exception:
                pass

    def _cancel_pending(self, bundle_id: str) -> None:
        """Remove a bundle from pending_bundles without applying double-refund.
        Used when the caller (check_bundle_confirmation) manually refunds the balance.
        """
        entry = self.pending_bundles.pop(bundle_id, None)
        if entry:
            logger.debug(f"⚙️ Bundle {bundle_id[:12]} cancelled and removed from Jito memory queue (refunded by caller).")

    async def _reconcile_pending(self) -> None:
        while self._running:
            try:
                now            = time.time()
                stale_seconds  = 15.0  # FIX 207: Extended to 15s to cover Jito late landings and prevent double-refunds
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
                        from src.ingest.shared_state import stats, stats_lock, data_aggregator
                        async with stats_lock:  # type: ignore[misc]
                            stats["virtual_balance"] += refund
                        logger.warning(
                            f"⚡ Ghost bundle {bid[:12]} refunded {refund:.8f} SOL"
                        )
                        # Этап 1: Update inflight bundle status to refunded
                        if data_aggregator and hasattr(data_aggregator, 'update_inflight_status'):
                            try:
                                await data_aggregator.update_inflight_status(bid, 'refunded')
                            except Exception:
                                pass
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

        # FIX 286: gRPC Jito fallback — use gRPC if JITO_AUTH_KEY is set
        if self.keypair and os.getenv("JITO_AUTH_KEY"):
            try:
                return await self._send_grpc_bundle(transactions)
            except Exception as e:
                logger.warning(f"gRPC bundle send failed: {e}. Falling back to REST shotgun.")

        if len(transactions) > 5:
            logger.error(
                f"❌ Bundle rejected: {len(transactions)} txns > Jito limit of 5"
            )
            return {
                "success": False,
                "error":   f"Bundle limit exceeded: {len(transactions)} > 5",
            }

        # FIX 165: Validate transaction (1232B) and bundle (32KiB) byte size limits
        total_bundle_size = 0
        for i, tx in enumerate(transactions):
            tx_size = len(bytes(tx))
            if tx_size > 1232:
                logger.error(f"❌ Jito bundle rejected: transaction at index {i} is {tx_size}B (exceeds 1232B Solana limit)")
                return {"success": False, "error": f"Transaction {i} size exceeds 1232B limit"}
            total_bundle_size += tx_size

        if total_bundle_size > 32768:
            logger.error(f"❌ Jito bundle rejected: total bundle size {total_bundle_size}B exceeds 32KiB limit")
            return {"success": False, "error": "Total bundle size exceeds 32KiB limit"}

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

            # R2-8: Gather and await cancelled tasks to avoid dangling aiohttp requests
            cancelled_tasks = [t for t in tasks if not t.done()]
            for t in cancelled_tasks:
                t.cancel()
            if cancelled_tasks:
                # FIX 255: Non-blocking background cancellation — never blocks hot path
                task = asyncio.create_task(asyncio.gather(*cancelled_tasks, return_exceptions=True))
                if hasattr(shared_state, "active_tasks"):
                    shared_state.active_tasks.add(task)
                    task.add_done_callback(shared_state.active_tasks.discard)
            if first_success:
                break

        if first_success:
            bundle_id = first_success.get("bundle_id", "")
            logger.info(
                f"✅ Bundle landed via {first_success.get('region')}: {bundle_id}"
            )
            if bundle_id and deducted_amount > 0:
                # FIX 177: Extract signature for better post-landing diagnostics
                sigs = [str(tx.signatures[0]) if tx.signatures else "unknown" for tx in transactions]
                self._record_pending(bundle_id, deducted_amount, sigs)
            return first_success

        logger.error("⚠️ All HTTP regional endpoints returned failure")
        return {"success": False, "error": "All HTTP regional endpoints failed"}

    async def _send_grpc_bundle(self, transactions) -> Dict[str, Any]:
        """FIX 286: gRPC bundle send stub — implement when gRPC client is available."""
        logger.warning("gRPC bundle send not implemented — falling back to REST")
        raise NotImplementedError("gRPC Jito client not available")

    async def _send_http(
        self,
        endpoint:    str,
        payload:     dict,
        headers:     dict,
    ) -> Dict[str, Any]:
        if not self.session:
            return {"success": False, "error": "No session", "region": endpoint}
        
        request_headers = dict(headers)
        
        # FIX 286: Inject x-jito-auth UUID header for authenticated Jito REST API
        auth_key = os.getenv("JITO_AUTH_KEY") or getattr(self, "keypair", None)
        if auth_key:
            request_headers["x-jito-auth"] = str(auth_key)
        
        try:
            import orjson
            raw_body = orjson.dumps(payload)
            request_headers["Content-Length"] = str(len(raw_body))
            
            async with self.session.post(
                endpoint, data=raw_body, headers=request_headers, timeout=5.0
            ) as resp:
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
        max_wait_time:   float  = 5.0,
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
