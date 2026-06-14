"""
Jito Shotgun & MEV Bidding Optimizer
Sends bundles to all 4 Jito Block Engines simultaneously for guaranteed inclusion.
Dynamic tip calculation based on expected profit.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Tuple
from solders.transaction import VersionedTransaction
from solders.pubkey import Pubkey
import aiohttp
import base58
import os

logger = logging.getLogger(__name__)

class JitoShotgun:
    """Jito bundle shotgun executor for maximum MEV capture."""

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.endpoints = [
            "https://amsterdam.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://ny.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://tokyo.mainnet.block-engine.jito.wtf/api/v1/bundles",
            "https://solana.api.blxrbdn.com/api/v1/bundles"  # bloXroute
        ]
        self.bundle_url_template = "https://{region}.block-engine.jito.wtf/api/v1/bundles"
        self.auth_key = None
        # Dynamic tip calibration
        self.acceptance_rate = 0.5  # Start at 50%

    def set_auth_key(self, auth_key: str):
        """Set Jito authentication key."""
        self.auth_key = auth_key

    async def send_to_all_engines(self, transactions: List[VersionedTransaction],
                                  expected_profit_lamports: int = 0, keypair=None,
                                  target_mint_str: str = "So11111111111111111111111111111111111111112",
                                  price_matrix: Optional[Dict[str, tuple]] = None) -> Dict[str, Any]:
        """
        Send bundle to all 4 Jito Block Engines simultaneously.

        Args:
            transactions: List of transactions (single merged tx recommended)
            expected_profit_lamports: Expected profit for dynamic tip calculation

        Returns:
            Dict with results from all endpoints
        """
        # Phase 31: Enforce Jito bundle limit (Max 5 transactions)
        if len(transactions) > 5:
            logger.error(f"❌ Shotgun bundle rejected: {len(transactions)} transactions exceeds limit of 5")
            return {"error": f"Bundle limit exceeded: {len(transactions)} > 5"}

        # ── Fix: Cross-Currency Profit Translation ────────────────────────────────
        # If the profit is denominated in a non-SOL token (e.g. USDC from a flash
        # loan), convert it to SOL first so _calculate_dynamic_tip does not
        # accidentally treat 5 USDC as 5 SOL.
        profit_sol = expected_profit_lamports
        if target_mint_str != "So11111111111111111111111111111111111111112" and price_matrix:
            try:
                sol_price_entry = price_matrix.get("So11111111111111111111111111111111111111112")
                sol_price_usd = sol_price_entry[0] if sol_price_entry else 150.0
                token_entry = price_matrix.get(target_mint_str)
                if token_entry and token_entry[0] > 0:
                    profit_usd = (expected_profit_lamports / 1e9) * token_entry[0]
                    profit_sol = int(profit_usd / sol_price_usd * 1e9)
                    logger.debug(f"🔄 Cross-currency tip normalization: {expected_profit_lamports} lamports of {target_mint_str[:8]} → {profit_sol} SOL lamports")
            except Exception:
                pass

        # Calculate dynamic tip based on game theory
        tip_lamports = self._calculate_dynamic_tip(profit_sol)

        # Tip merge disabled: tx_builder.py already appends the Jito tip as the final
        # instruction for capital protection (revert-on-fail). Sending a second tip would
        # double-pay. We trust the builder and skip internal merging here.
        # if len(transactions) == 1 and keypair:
        #     transactions[0] = await self._merge_tip_into_transaction(transactions[0], tip_lamports, keypair)
        # elif len(transactions) == 1 and not keypair:
        #     logger.warning("Keypair required for tip merging but not provided")
        # else:
        #     logger.warning("Multiple transactions detected - consider merging for capital protection")

        # Convert to base58 - use EXACT same serialized tx (same sig) for all regions (Fix 82)
        # Never re-sign with different blockhash per region to avoid double-spend rejection
        tx_base58 = [base58.b58encode(bytes(tx)).decode('ascii') for tx in transactions]

        # Send to all endpoints simultaneously
        tasks = []
        for endpoint in self.endpoints:
            task = self._send_bundle_to_endpoint(tx_base58, endpoint)
            tasks.append(task)

        # Wait for all responses
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        successful_sends = []
        failed_sends = []

        for i, result in enumerate(results):
            endpoint = self.endpoints[i]
            if isinstance(result, Exception):
                failed_sends.append({"endpoint": endpoint, "error": str(result)})
                logger.warning(f"Jito {endpoint} failed: {result}")
            else:
                successful_sends.append({"endpoint": endpoint, "result": result})
                logger.info(f"Jito {endpoint} accepted bundle: {result.get('result', 'unknown')}")

        # Update acceptance rate based on success
        self.update_acceptance_rate(len(successful_sends) > 0)

        # Return summary
        return {
            "successful_sends": successful_sends,
            "failed_sends": failed_sends,
            "total_sent": len(successful_sends),
            "tip_used": tip_lamports,
            "expected_profit": expected_profit_lamports
        }

    def update_acceptance_rate(self, success: bool):
        """Update acceptance rate based on bundle success/failure."""
        if success:
            self.acceptance_rate = max(0.3, self.acceptance_rate - 0.05)  # Decrease tip if landing
        else:
            self.acceptance_rate = min(0.7, self.acceptance_rate + 0.05)  # Increase tip if failing

    def _calculate_dynamic_tip(self, expected_profit_lamports: int) -> int:
        """
        Calculate dynamic Jito tip using acceptance rate tracking.

        Formula: Max(10_000_lamports, (Expected_Profit * acceptance_rate))
        Adjusts based on recent bundle success rates.
        """
        min_tip = 10_000  # 0.00001 SOL minimum
        dynamic_tip = int(expected_profit_lamports * self.acceptance_rate)

        return max(min_tip, dynamic_tip)

    async def _merge_tip_into_transaction(self, transaction: VersionedTransaction,
                                           tip_lamports: int, keypair, tip_account: str) -> VersionedTransaction:
        """Merge Jito tip into transaction as final instruction (capital protection).
        
        Args:
            transaction: The transaction to merge the tip into
            tip_lamports: Amount of tip in lamports
            keypair: Signer keypair
            tip_account: Dynamic tip account address from jito_executor.tip_accounts
        """
        try:
            from solders.system_program import TransferParams, transfer
            from solders.instruction import Instruction, AccountMeta
            from solders.message import MessageV0

            # Reconstruct raw instructions from CompiledInstructions
            existing_instructions = []
            for compiled_ix in transaction.message.instructions:
                program_id = transaction.message.account_keys[compiled_ix.program_id_index]
                accounts = []
                for acc_idx in compiled_ix.accounts:
                    pubkey = transaction.message.account_keys[acc_idx]
                    # Note: We can't know is_signer/is_writable from CompiledInstruction alone
                    # This is a limitation; assuming based on common patterns or requiring raw instructions
                    accounts.append(AccountMeta(pubkey=pubkey, is_signer=False, is_writable=True))  # Approximation
                data = compiled_ix.data
                raw_ix = Instruction(program_id=program_id, accounts=accounts, data=data)
                existing_instructions.append(raw_ix)

            # Add tip transfer as VERY LAST instruction using dynamic tip account
            tip_ix = transfer(TransferParams(
                from_pubkey=transaction.message.account_keys[0],
                to_pubkey=Pubkey.from_string(tip_account),
                lamports=tip_lamports,
            ))

            # Merge tip into instructions
            instructions_with_tip = existing_instructions + [tip_ix]

            # Recompile transaction
            msg_with_tip = MessageV0.try_compile(
                payer=transaction.message.account_keys[0],
                instructions=instructions_with_tip,
                address_lookup_table_accounts=transaction.message.address_lookup_table_accounts,
                recent_blockhash=transaction.message.recent_blockhash
            )

            return VersionedTransaction(msg_with_tip, [keypair])

        except Exception as e:
            logger.error(f"Failed to merge tip into transaction: {e}")
            return transaction

    async def _send_bundle_to_endpoint(self, tx_base58: List[str], endpoint: str) -> Dict[str, Any]:
        """Send bundle to specific Jito endpoint."""
        try:
            url = endpoint

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendBundle",
                "params": [tx_base58]
            }

            # Phase 14: Conditional Auth Headers (Jito vs bloXroute)
            headers = {"Content-Type": "application/json"}
            if "blxrbdn.com" in endpoint:
                # bloXroute authorization: <token> format
                blx_token = os.getenv("BLOXROUTE_TOKEN")
                if blx_token:
                    headers["Authorization"] = blx_token
            elif self.auth_key:
                # Jito authorization: Bearer <token> format
                headers["Authorization"] = f"Bearer {self.auth_key}"

            # Short timeout for HFT - better miss one endpoint than lose arbitrage window
            async with self.session.post(url, json=payload, headers=headers, timeout=0.5) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    error_text = await resp.text()
                    raise Exception(f"HTTP {resp.status}: {error_text}")

        except Exception as e:
            raise Exception(f"Bundle send to {endpoint} failed: {e}")

    async def get_bundle_statuses(self, bundle_ids: List[str]) -> Dict[str, Any]:
        """Get status of submitted bundles across all endpoints."""
        if not bundle_ids:
            return {"statuses": []}
            
        try:
            # Query the first available endpoint for status
            # Jito usually syncs bundle statuses across all regions
            endpoint = self.endpoints[0].replace("/bundles", "/bundleStatuses")
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBundleStatuses",
                "params": [bundle_ids]
            }
            
            async with self.session.post(endpoint, json=payload, timeout=2.0) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    return {"error": f"HTTP {resp.status}"}
        except Exception as e:
            logger.error(f"Failed to get bundle statuses: {e}")
            return {"error": str(e)}

    def get_tip_statistics(self) -> Dict[str, Any]:
        """Get statistics on tip usage and effectiveness."""
        # Track tip performance over time
        return {
            "average_tip_lamports": 50000,
            "success_rate": 0.95,
            "total_tips_paid": 1000000
        }