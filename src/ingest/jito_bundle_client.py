"""Jito Bundle Client for sending real transactions via Jito bundles."""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Set
import aiohttp
import base58
from solders.keypair import Keypair
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.hash import Hash

from src.ingest.jito_priority_context import JitoPriorityContext

logger = logging.getLogger(__name__)

# Jito Bundle API endpoint
JITO_BUNDLE_ENDPOINT = "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles"  # Single NY endpoint for Helius (avoids blockhash geo-delay)



class JitoBundleClient:
    """Client for sending transaction bundles via Jito."""

    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self.session = session
        self.timeout = timeout
        self.max_retries = max_retries
        self._session_owned = session is None
        # Phase 35: Dynamic Jito Tip Accounts — must call fetch_tip_accounts() at startup
        self.tip_accounts: List[str] = []
        logger.warning("JitoBundleClient: tip_accounts initialized empty. Call fetch_tip_accounts() at startup to retrieve dynamic accounts from Jito API.")
        self.background_tasks: Set[asyncio.Task] = set()

    async def __aenter__(self):
        if self._session_owned and self.session is None:
            connector = aiohttp.TCPConnector(keepalive_timeout=300, limit=100)
            self.session = aiohttp.ClientSession(connector=connector)  # Fix 85: persistent keep-alive
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Добавить в __aexit__:
        if self.background_tasks:
            for task in self.background_tasks:
                if not task.done():
                    task.cancel()
        
        if self._session_owned and self.session:
            await self.session.close()

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
                        return True
        except Exception:
            pass
        return False

    def _select_tip_account(self) -> str:
        """Select a random tip account for load balancing."""
        import random
        return random.choice(self.tip_accounts)

    def _build_tip_instruction(
        self,
        payer_keypair: Keypair,
        tip_amount_lamports: int,
        tip_account: str,
    ) -> Any:
        """Build a SOL transfer instruction to tip Jito."""
        from solders.pubkey import Pubkey

        transfer_ix = transfer(
            TransferParams(
                from_pubkey=payer_keypair.pubkey(),
                to_pubkey=Pubkey.from_string(tip_account),
                lamports=tip_amount_lamports,
            )
        )
        return transfer_ix

    async def _get_recent_blockhash(self) -> Optional[Hash]:
        """Get recent blockhash for transaction construction.

        IMPORTANT: Never use a hardcoded/fake blockhash. Jito Block Engine
        will reject the entire bundle with BlockhashNotFound if the
        blockhash is stale or invalid. Always use a real blockhash obtained
        from RPC within the last ~150 blocks.
        """
        if not self.session:
            logger.error("No session available to fetch blockhash")
            return None

        try:
            async with self.session.post(
                "https://api.mainnet-beta.solana.com",
                json={"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash"},
                timeout=aiohttp.ClientTimeout(total=3.0),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and "value" in data["result"]:
                        return Hash.from_string(data["result"]["value"]["blockhash"])
        except Exception as e:
            logger.error(f"Failed to fetch recent blockhash: {e}")

        return None

    async def build_and_send_bundle(
        self,
        swap_instructions: List[Any],
        payer_keypair: Keypair,
        jito_context: JitoPriorityContext,
        recent_blockhash: Optional[Hash] = None,
    ) -> Dict[str, Any]:
        """Build and send a transaction bundle to Jito.

        Args:
            swap_instructions: List of swap instructions to include in bundle
            payer_keypair: Keypair for signing transactions
            jito_context: Jito priority context with tip information
            recent_blockhash: Recent blockhash (optional, will fetch if not provided)

        Returns:
            Dict containing bundle ID and status information
        """
        try:
            if recent_blockhash is None:
                recent_blockhash = await self._get_recent_blockhash()

            if recent_blockhash is None:
                logger.error("Cannot send bundle: failed to fetch recent blockhash")
                return {
                    "success": False,
                    "error": "Failed to fetch recent blockhash",
                    "bundle_id": None,
                }

            # Select tip account
            tip_account = self._select_tip_account()

            # Combine swap instructions with tip
            # NOTE: tx_builder.py already appends the Jito tip instruction as the FINAL
            # instruction inside the transaction for capital protection (revert-on-fail).
            # appending a second tip here would double-pay.  We pass swap_instructions
            # straight through so the embedded tip is preserved.
            all_instructions = swap_instructions

            # Build message
            message = MessageV0.try_compile(
                payer_keypair.pubkey(),
                all_instructions,
                [],
                recent_blockhash,
            )

            # Create versioned transaction
            transaction = VersionedTransaction(message, [payer_keypair])

            # Convert to bundle format
            bundle = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": [[base58.b58encode(bytes(transaction)).decode('ascii')]],
            }

            # Send bundle
            return await self._send_bundle_request(bundle)

        except Exception as e:
            logger.error(f"Error building/sending bundle: {e}")
            return {
                "success": False,
                "error": str(e),
                "bundle_id": None,
            }

    async def _send_bundle_request(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        """Send bundle request to Jito API."""
        if not self.session:
            raise RuntimeError("Client session not available")

        for attempt in range(self.max_retries):
            try:
                async with self.session.post(
                    JITO_BUNDLE_ENDPOINT,
                    json=bundle,
                    headers={"Content-Type": "application/json"},
                    timeout=self.timeout,
                ) as response:
                    result = await response.json()

                    if response.status == 200:
                        bundle_id = result.get("result")
                        logger.info(f"Bundle sent successfully, ID: {bundle_id}")
                        return {
                            "success": True,
                            "bundle_id": bundle_id,
                            "status": "sent",
                        }
                    else:
                        error_msg = result.get("error", {}).get("message", "Unknown error")
                        logger.warning(f"Bundle send failed (attempt {attempt + 1}): {error_msg}")

                        if attempt == self.max_retries - 1:
                            return {
                                "success": False,
                                "error": error_msg,
                                "bundle_id": None,
                            }

            except asyncio.TimeoutError:
                logger.warning(f"Bundle send timeout (attempt {attempt + 1})")
                if attempt == self.max_retries - 1:
                    return {
                        "success": False,
                        "error": "Request timeout",
                        "bundle_id": None,
                    }

            except Exception as e:
                logger.error(f"Bundle send error (attempt {attempt + 1}): {e}")
                if attempt == self.max_retries - 1:
                    return {
                        "success": False,
                        "error": str(e),
                        "bundle_id": None,
                    }

            # Wait before retry
            await asyncio.sleep(0.5 * (2 ** attempt))

        return {
            "success": False,
            "error": "Max retries exceeded",
            "bundle_id": None,
        }

    async def get_bundle_statuses(self, bundle_ids: List[str]) -> Dict[str, Any]:
        """Get status of one or more bundles.

        Args:
            bundle_ids: List of bundle IDs to check

        Returns:
            Dict mapping bundle IDs to their status information
        """
        if not self.session:
            raise RuntimeError("Client session not available")

        if not bundle_ids:
            return {}

        try:
            status_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBundleStatuses",
                "params": [bundle_ids],
            }

            async with self.session.post(
                JITO_BUNDLE_ENDPOINT,
                json=status_request,
                headers={"Content-Type": "application/json"},
                timeout=self.timeout,
            ) as response:
                result = await response.json()

                if response.status == 200 and "result" in result:
                    statuses = result["result"]
                    logger.debug(f"Retrieved bundle statuses for {len(bundle_ids)} bundles")
                    return statuses
                else:
                    error_msg = result.get("error", {}).get("message", "Unknown error")
                    logger.error(f"Failed to get bundle statuses: {error_msg}")
                    return {}

        except Exception as e:
            logger.error(f"Error getting bundle statuses: {e}")
            return {}

    async def wait_for_bundle_confirmation(
        self,
        bundle_id: str,
        max_wait_time: float = 3.0,  # HFT: drop after 3s
        check_interval: float = 0.5,
    ) -> Dict[str, Any]:
        """Wait for bundle confirmation.

        Args:
            bundle_id: Bundle ID to monitor
            max_wait_time: Maximum time to wait in seconds
            check_interval: How often to check status in seconds

        Returns:
            Dict with final bundle status
        """
        import time
        start_time = time.time()

        while time.time() - start_time < max_wait_time:
            try:
                statuses = await self.get_bundle_statuses([bundle_id])

                if bundle_id in statuses:
                    status_info = statuses[bundle_id]
                    confirmation_status = status_info.get("confirmation_status")

                    if confirmation_status in ["confirmed", "finalized", "failed"]:
                        logger.info(f"Bundle {bundle_id} reached final status: {confirmation_status}")
                        return {
                            "bundle_id": bundle_id,
                            "status": confirmation_status,
                            "details": status_info,
                        }

                await asyncio.sleep(check_interval)

            except Exception as e:
                logger.error(f"Error checking bundle status: {e}")
                await asyncio.sleep(check_interval)

        logger.warning(f"Bundle {bundle_id} confirmation timeout after {max_wait_time}s")
        return {
            "bundle_id": bundle_id,
            "status": "timeout",
            "details": {},
        }