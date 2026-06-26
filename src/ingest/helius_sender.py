#!/usr/bin/env python3
"""
Helius Sender Integration for Solana Transactions

Sends transactions via Helius RPC Sender with priority fees and tips.
"""

import os
import random
import base64
import logging
from typing import Optional, List
import aiohttp
from solders.system_program import transfer, TransferParams
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

logger = logging.getLogger("HeliusSender")

class HeliusSender:
    """Helius Sender for high-speed transaction submission."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        sender_urls: List[str],
        tip_accounts: List[str],
    ):
        self.session = session
        self.sender_urls = sender_urls
        self.tip_accounts = tip_accounts

    def get_random_tip_account(self) -> str:
        """Get random tip account."""
        return random.choice(self.tip_accounts)

    async def send_via_helius_sender(
        self,
        signed_tx: VersionedTransaction,
    ) -> Optional[str]:
        """Send transaction via Helius Sender.

        Fix 41: Removed unused tip_lamports and priority_fee_micro_lamports params.
        These were never actually embedded into the transaction — Helius Sender
        simply relays the pre-signed tx as-is. Tip and fee must be set at build time.
        """
        try:
            tx_b64 = base64.b64encode(bytes(signed_tx)).decode('ascii')

            payload = {
                "jsonrpc": "2.0",
                "id": "helius-sender",
                "method": "sendTransaction",
                "params": [
                    tx_b64,
                    {
                        "skipPreflight": True,
                        "maxRetries": 0,
                        "preflightCommitment": "processed",
                        "minContextSlot": None,
                    }
                ]
            }

            for url in self.sender_urls:
                try:
                    async with self.session.post(
                        url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=5.0)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("result"):
                                logger.info(f"✅ Helius sender tx: {data['result']}")
                                return data["result"]
                            else:
                                logger.error(f"Helius sender error: {data.get('error')}")
                        else:
                            logger.warning(f"Helius sender HTTP {resp.status}")
                except Exception as e:
                    logger.warning(f"Helius sender failed on {url}: {e}")

            return None
        except Exception as err:
            logger.error(f"Helius sender failed: {err}")
            return None

class TransactionSender:
    """Unified transaction sender with Helius primary."""

    def __init__(self, helius_sender: HeliusSender):
        self.helius_sender = helius_sender

    async def send_transaction(
        self,
        signed_tx: VersionedTransaction,
    ) -> Optional[str]:
        """Send transaction with Helius primary."""
        result = await self.helius_sender.send_via_helius_sender(
            signed_tx
        )
        return result

    async def send_with_retry(
        self,
        signed_tx: VersionedTransaction,
        max_retries: int = 3,
    ) -> Optional[str]:
        """Send with retry.

        Fix 41: Removed unused fee/tip params — Helius Sender does not embed them.
        """
        for attempt in range(max_retries):
            result = await self.send_transaction(signed_tx)
            if result:
                return result
            logger.warning(f"Send attempt {attempt + 1} failed, retrying")
        return None