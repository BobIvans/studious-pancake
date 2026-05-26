"""Jito Bundle Client — HTTP REST Submission (Free Resources).

This client uses Jito's JSON-RPC HTTP API to submit bundles, eliminating the need
for complex gRPC dependencies and paid tier resources.
"""

from __future__ import annotations

import asyncio
import base58
import logging
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
        api_key:     Optional[str]       = None,
        max_retries: int                 = 2,
        keypair:     Optional[Keypair]   = None,
        session:     Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self.endpoints   = endpoints or JITO_HTTP_ENDPOINTS
        self.api_key     = api_key
        self.max_retries = max_retries
        self.keypair     = keypair
        self.session     = session
        self._session_owned = session is None

        # Dynamic tip accounts (Phase 35)
        self.tip_accounts: List[str] = []
        self.background_tasks: set = set()

    # ── Context manager ────────────────────────────────────────────────────────

    async def __aenter__(self) -> "JitoBundleClient":
        if self._session_owned and self.session is None:
            self.session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(force_close=False, ttl_dns_cache=300)
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
        """Start background tasks including Jito auth refresh."""
        if self.keypair and self.session:
            task = asyncio.create_task(self._maintain_jito_auth_loop())
            self.background_tasks.add(task)

    async def _maintain_jito_auth_loop(self) -> None:
        """Maintains Jito Searcher authentication by refreshing JWT every 9 minutes."""
        while True:
            try:
                jwt_token = await self._authenticate_jito()
                if jwt_token:
                    self.api_key = jwt_token
                else:
                    logger.warning("⚠️ Jito Auth refresh failed — retrying in 30s...")
                    await asyncio.sleep(30)
                    continue
            except Exception as e:
                logger.error(f"Jito auth loop error: {e}")
            await asyncio.sleep(540)  # Refresh every 9 minutes

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

    # ── Jito Searcher Authentication Handshake (Phase 49) ───────────────────────

    async def _authenticate_jito(self) -> Optional[str]:
        if not self.keypair or not self.session:
            return None
        try:
            challenge_url = "https://mainnet.block-engine.jito.wtf/api/v1/auth/challenge"
            payload = {"key": str(self.keypair.pubkey())}
            async with self.session.post(challenge_url, json=payload, timeout=5.0) as resp:
                if resp.status != 200:
                    logger.warning(f"Jito challenge failed: HTTP {resp.status}")
                    return None
                data = await resp.json()
                challenge = data.get("value", "")

            if not challenge:
                return None

            message = f"{str(self.keypair.pubkey())}-{challenge}"
            signature_bytes = self.keypair.sign_message(message.encode("utf-8"))
            signature_b58 = base58.b58encode(bytes(signature_bytes)).decode("ascii")

            token_url = "https://mainnet.block-engine.jito.wtf/api/v1/auth/token"
            token_payload = {
                "key": str(self.keypair.pubkey()),
                "challenge": message,
                "client_sig": signature_b58,
            }
            async with self.session.post(token_url, json=token_payload, timeout=5.0) as resp:
                if resp.status == 200:
                    token_data = await resp.json()
                    access_token = token_data.get("access_token", {}).get("value")
                    logger.info("🔑 Jito Searcher Authentication successful! JWT token acquired.")
                    return access_token
                else:
                    logger.warning(f"Jito token generation failed: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"Jito authentication handshake failed: {e}")
        return None

    # ── Blockhash ───────────────────────────────────────────────────────────────

    async def _get_recent_blockhash(self) -> Optional[Hash]:
        if not self.session:
            return None
        try:
            async with self.session.post(
                "https://api.mainnet-beta.solana.com",
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
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

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
        
        # Use NY endpoint as default for status queries
        endpoint = "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles"
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
