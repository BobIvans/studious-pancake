"""Jito Bundle Client — HTTP REST Submission (Free Resources).

This client uses Jito's JSON-RPC HTTP API to submit bundles, eliminating the need
for complex gRPC dependencies and paid tier resources.
"""

from __future__ import annotations

import asyncio
import base58
import logging
import os
import socket
import time
from typing import Any, Dict, List, Optional
import aiohttp

from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.transaction import VersionedTransaction

logger = logging.getLogger(__name__)

# ── Jito regional Block Engine HTTP endpoints ─────────────────────────────────
JITO_HTTP_ENDPOINTS: List[str] = [
    "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles",
    "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1/bundles",
    "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
    "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles",
]


class JitoBundleClient:
    """HTTP-based Jito bundle client — 100% free resources, zero gRPC overhead."""

    def __init__(
        self,
        endpoints:   Optional[List[str]] = None,
        max_retries: int                 = 2,
        keypair:     Optional[Keypair]   = None,
        session:     Optional[aiohttp.ClientSession] = None,
        rpc_url:     Optional[str]       = None,
    ) -> None:
        self.endpoints   = endpoints or JITO_HTTP_ENDPOINTS
        self.max_retries = max_retries
        self.keypair     = keypair
        self.session     = session
        self.rpc_url     = (
            rpc_url
            or os.getenv("HELIUS_GATEKEEPER_URL", "").strip()
            or os.getenv("RPC_URL_1", "").strip()
            or os.getenv("RPC_URL", "").strip()
        )
        self._session_owned = session is None

        # Dynamic tip accounts (Phase 35)
        self.tip_accounts: List[str] = []
        self.background_tasks: set = set()

    # ── Context manager ────────────────────────────────────────────────────────

    async def __aenter__(self) -> "JitoBundleClient":
        if self._session_owned and self.session is None:
            self.session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(force_close=False, ttl_dns_cache=300, family=socket.AF_INET)
            )
        return self

    async def __aexit__(self, *_: Any) -> None:
        for t in self.background_tasks:
            if not t.done():
                t.cancel()
        self.background_tasks.clear()

        if self._session_owned and self.session:
            await self.session.close()

    # ── Lifecycle ────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start background tasks."""
        pass

    # ── Tip account management ──────────────────────────────────────────────────

    async def fetch_tip_accounts(self) -> bool:
        """Fetch live Jito tip accounts (Phase 35)."""
        if not self.session:
            return False
        try:
            async with self.session.get(
                "https://mainnet.block-engine.jito.wtf/api/v1/bundles/tip_accounts",
                timeout=5.0,
            ) as resp:
                if resp.status == 200:
                    self.tip_accounts = await resp.json()
                    return bool(self.tip_accounts)
        except Exception as e:
            logger.debug(f"Failed to fetch tip accounts: {e}")
        return False

    def _select_tip_account(self) -> str:
        import random
        return (
            random.choice(self.tip_accounts)
            if self.tip_accounts
            else "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"
        )

    # ── Blockhash ───────────────────────────────────────────────────────────────

    async def _get_recent_blockhash(self, rpc_url: Optional[str] = None) -> Optional[Hash]:
        # Phase 21: Try BlockhashRacingManager cache first (0ms vs 100ms+ HTTP POST)
        try:
            from src.ingest.blockhash_racing import get_blockhash_manager
            bh_mgr = get_blockhash_manager()
            if bh_mgr and bh_mgr.current_blockhash:
                logger.debug("⚡ Phase 21: Using cached blockhash from BlockhashRacingManager")
                return bh_mgr.current_blockhash
        except Exception:
            pass

        if not self.session:
            return None
        endpoint = (rpc_url or self.rpc_url or "").strip()
        if not endpoint:
            logger.error("No RPC URL configured for blockhash fetch; refusing to use public Solana RPC")
            return None
        try:
            async with self.session.post(
                endpoint,
                json={"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash"},
                timeout=aiohttp.ClientTimeout(total=3.0),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return Hash.from_string(
                        data["result"]["value"]["blockhash"]
                    )
        except Exception as exc:
            logger.error(f"Failed to fetch blockhash: {exc}")
        return None

    # ── HTTP bundle submission ──────────────────────────────────────────────────

    async def build_and_send_bundle(
        self,
        swap_instructions: List[Any],
        payer_keypair:    Keypair,
        recent_blockhash: Optional[Hash] = None,
    ) -> Dict[str, Any]:
        """Отправка бандла через бесплатный Jito REST API (HTTP POST)"""
        # PAPER TRADING SAFETY: never send real bundles in simulation mode
        import os
        if str(os.getenv("PAPER_TRADING_ONLY", "false")).lower() == "true":
            logger.info("📄 Paper Trading: bypassing Jito bundle send (build_and_send_bundle)")
            import time
            return {"success": True, "bundle_id": f"paper_{int(time.time())}", "endpoint": "paper"}
        try:
            if recent_blockhash is None:
                recent_blockhash = await self._get_recent_blockhash()
            if not recent_blockhash:
                return {"success": False, "error": "No blockhash", "bundle_id": None}

            # Сборка транзакции
            message = MessageV0.try_compile(
                payer_keypair.pubkey(), swap_instructions, [], recent_blockhash,
            )
            transaction = VersionedTransaction(message, [payer_keypair])

            # Для HTTP API Jito транзакция ДОЛЖНА быть строкой Base58
            tx_base58 = base58.b58encode(bytes(transaction)).decode("ascii")

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": [[tx_base58]]
            }

            # Выстреливаем по всем бесплатным HTTP-эндпоинтам (Shotgun)
            tasks = []
            for endpoint in self.endpoints:
                tasks.append(asyncio.create_task(self._send_http_request(endpoint, payload)))

            # Ждем первый успешный ответ
            if not tasks:
                return {"success": False, "error": "No endpoints configured", "bundle_id": None}

            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=3.0)
            
            # Отменяем зависшие задачи
            for task in pending:
                task.cancel()
                
            # Безопасно гасим возможные исключения в отмененных задачах (защита от утечки памяти)
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            # Проверяем успешные
            for task in done:
                try:
                    res = task.result()
                    if res.get("success"):
                        return res
                except Exception as e:
                    logger.debug(f"HTTP Shotgun task failed: {e}")

            return {"success": False, "error": "All HTTP endpoints failed", "bundle_id": None}

        except Exception as exc:
            logger.error(f"build_and_send_bundle error: {exc}")
            return {"success": False, "error": str(exc), "bundle_id": None}

    async def _send_http_request(self, url: str, payload: dict) -> dict:
        """Внутренний метод отправки одного HTTP запроса."""
        if not self.session:
            return {"success": False, "error": "No session"}
        try:
            headers = {"Content-Type": "application/json"}

            async with self.session.post(url, json=payload, headers=headers, timeout=2.0) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data:
                        return {"success": True, "bundle_id": data["result"], "url": url}
                    return {"success": False, "error": f"JSON-RPC error: {data}", "url": url}
                return {"success": False, "error": f"HTTP {resp.status}", "url": url}
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}

    # ── Status query ────────────────────────────────────────────────────────────

    async def get_bundle_statuses(self, bundle_ids: List[str]) -> Dict[str, Any]:
        """Get status of one or more bundles via HTTP POST."""
        if not self.session or not bundle_ids:
            return {}
        
        # Use the global Jito Block Engine endpoint for status queries so all regions are visible.
        endpoint = "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
        try:
            async with self.session.post(
                endpoint,
                json={
                    "jsonrpc": "2.0", "id": 1,
                    "method":  "getBundleStatuses",
                    "params":  [bundle_ids],
                },
                timeout=5.0,
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    if "result" in result and result["result"]["value"]:
                        # API returns a list of status objects
                        statuses = {}
                        for item in result["result"]["value"]:
                            if item and "bundle_id" in item:
                                statuses[item["bundle_id"]] = item
                        return statuses
        except Exception as exc:
            logger.error(f"get_bundle_statuses error: {exc}")
        return {}

    async def wait_for_bundle_confirmation(
        self,
        bundle_id:    str,
        max_wait_time: float = 3.0,
        check_interval: float = 0.5,
    ) -> Dict[str, Any]:
        start = time.time()
        while time.time() - start < max_wait_time:
            statuses = await self.get_bundle_statuses([bundle_id])
            if bundle_id in statuses:
                info           = statuses[bundle_id]
                confirmation   = info.get("confirmation_status", "")
                if confirmation in {"confirmed", "finalized"}:
                    return {"bundle_id": bundle_id, "status": confirmation, "details": info}
                elif confirmation == "failed":
                     return {"bundle_id": bundle_id, "status": "failed", "details": info}
            await asyncio.sleep(check_interval)
        return {"bundle_id": bundle_id, "status": "timeout", "details": {}}
