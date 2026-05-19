"""
Zero-Dust Guard & Crash Recovery
Automatically cleans stranded Token Accounts (value < $1.00) and recovers ATA rent (0.002 SOL per account).
Critical for protecting the 0.17 SOL budget from accumulation of low-value dust.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set
from decimal import Decimal
import aiohttp
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.keypair import Keypair
from solders.rpc.requests import GetProgramAccounts, GetAccountInfo
from solders.rpc.config import RpcAccountInfoConfig

logger = logging.getLogger(__name__)

class DustSweeper:
    """Sweeps dust and recovers rent from stranded Token Accounts."""

    def __init__(self, wallet_keypair: Keypair, rpc_url: str, session: aiohttp.ClientSession):
        self.wallet_keypair = wallet_keypair
        self.rpc_url = rpc_url
        self.session = session
        self.spl_token_program = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        
        # Phase 48: Golden ATAs that should NEVER be closed (Capital Protection)
        self.wsol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
        self.usdc_mint = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
        from src.config.xstocks_registry import is_xstock_token
        from spl.token.instructions import get_associated_token_address
        # Token-2022 Program ID for xStocks
        TOKEN_2022_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EP2rHEjaChQX6n57TR5m")

        if is_xstock_token(self.wsol_mint):
            self.wsol_ata = str(get_associated_token_address(wallet_keypair.pubkey(), self.wsol_mint, TOKEN_2022_PROGRAM_ID))
        else:
            self.wsol_ata = str(get_associated_token_address(wallet_keypair.pubkey(), self.wsol_mint))

        if is_xstock_token(self.usdc_mint):
            self.usdc_ata = str(get_associated_token_address(wallet_keypair.pubkey(), self.usdc_mint, TOKEN_2022_PROGRAM_ID))
        else:
            self.usdc_ata = str(get_associated_token_address(wallet_keypair.pubkey(), self.usdc_mint))
        self.golden_atas = {self.wsol_ata, self.usdc_ata}

    async def sweep_on_startup(self) -> int:
        """Sweep dust on bot startup. Returns SOL recovered."""
        logger.info("🧹 Starting dust sweep on startup...")
        recovered_lamports = await self._sweep_dust()
        recovered_sol = recovered_lamports / 1_000_000_000
        logger.info(f"✅ Startup sweep complete. Recovered: {recovered_sol:.6f} SOL")
        return recovered_lamports

    async def sweep_on_shutdown(self) -> int:
        """Sweep dust on bot shutdown. Returns SOL recovered."""
        logger.info("🧹 Starting dust sweep on shutdown...")
        recovered_lamports = await self._sweep_dust()
        recovered_sol = recovered_lamports / 1_000_000_000
        logger.info(f"✅ Shutdown sweep complete. Recovered: {recovered_sol:.6f} SOL")
        return recovered_lamports

    async def _sweep_dust(self) -> int:
        """Core dust sweeping logic."""
        try:
            # Find all Token Accounts owned by our wallet
            token_accounts = await self._get_wallet_token_accounts()

            if not token_accounts:
                logger.debug("No token accounts found")
                return 0

            # Filter for dust/empty accounts
            dust_accounts = []
            total_rent_recovered = 0

            for account_info in token_accounts:
                account_address = account_info["pubkey"]
                account_data = account_info.get("account", {})

                # Check if account has zero balance (dust)
                info = account_data.get("data", {}).get("parsed", {}).get("info", {})
                token_amount = info.get("tokenAmount", {})
                raw_amount = int(token_amount.get("amount", "0"))
                mint = info.get("mint")

                is_dust = await self._is_dust_account(account_data)

                if is_dust:
                    # Phase 48: Protect Golden ATAs from being swept
                    if str(account_address) in self.golden_atas:
                        logger.debug(f"Skipping golden ATA: {account_address}")
                        continue

                    dust_accounts.append({
                        "address": account_address,
                        "amount": raw_amount,
                        "mint": mint
                    })
                    # Estimate rent recovery (0.002 SOL = 2_000_000 lamports)
                    total_rent_recovered += 2_000_000

            if not dust_accounts:
                logger.debug("No dust accounts to clean")
                return 0

            # Close dust accounts in batches
            batch_size = 10  # Solana transaction limits
            total_recovered = 0

            for i in range(0, len(dust_accounts), batch_size):
                batch = dust_accounts[i:i + batch_size]
                recovered = await self._close_dust_accounts_batch(batch)
                total_recovered += recovered

            return total_recovered

        except Exception as e:
            logger.error(f"Dust sweep failed: {e}")
            return 0

    async def _get_wallet_token_accounts(self) -> List[Dict]:
        """Get all Token Accounts owned by our wallet."""
        try:
            # Use lightweight getTokenAccountsByOwner instead of heavy getProgramAccounts
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    str(self.wallet_keypair.pubkey()),
                    {
                        "programId": str(self.spl_token_program)
                    },
                    {
                        "encoding": "jsonParsed"
                    }
                ]
            }

            async with self.session.post(self.rpc_url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("result", [])
                else:
                    logger.error(f"Failed to get token accounts: {resp.status}")
                    return []

        except Exception as e:
            logger.error(f"Token account query failed: {e}")
            return []

    async def _is_dust_account(self, account_data: Dict) -> bool:
        """
        Determine if a token account should be swept.

        Fix #5 — Aggressive ATA Rent Recovery:
        With CLOSE_ATAS_ON_EXIT=true, any non-golden token account holding
        less than 1.0 ui_amount is treated as dust.  This catches "large dust"
        remnants such as 0.5 USDC or 0.1 JUP left behind by partially-failed
        swaps.  Each such abandoned account locks 0.002 SOL in ATA rent; at
        0.017 SOL total capital, even 8 stranded accounts would drain the
        entire budget.

        When CLOSE_ATAS_ON_EXIT is false/unset, the previous conservative
        threshold (< 0.01) is used so normal sweeping stays cheap.
        """
        try:
            parsed_data = account_data.get("data", {}).get("parsed", {})
            info = parsed_data.get("info", {})

            ui_amount = float(info.get("tokenAmount", {}).get("uiAmountString", "0"))
            mint = info.get("mint", "")

            # Never close the primary working-capital ATAs.
            CORE_GOLDEN_MINTS = {
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                "So11111111111111111111111111111111111111112",  # wSOL
                "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
                "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo",  # PYUSD
            }
            if mint in CORE_GOLDEN_MINTS:
                return False

            # xStock ATAs: only sweep if completely empty (Token-2022 overhead).
            if mint.startswith("Xs"):
                return ui_amount == 0

            # For non-golden/other tokens, only sweep if the quantity is < 0.05.
            dust_threshold = 0.05
            return ui_amount < dust_threshold

        except Exception:
            return False

    def _build_burn_instruction(self, token_account: str, mint: str, amount: int):
        """Build Burn instruction for SPL token (Phase 41)."""
        try:
            from spl.token.instructions import BurnParams, burn
            
            burn_params = BurnParams(
                program_id=self.spl_token_program,
                account=Pubkey.from_string(token_account),
                mint=Pubkey.from_string(mint),
                owner=self.wallet_keypair.pubkey(),
                amount=amount
            )
            return burn(burn_params)
        except Exception as e:
            logger.debug(f"Burn instruction build failed: {e}")
            return None

    async def _close_dust_accounts_batch(self, batch: List[Dict]) -> int:
        """Close a batch of dust token accounts and recover rent."""
        try:
            close_instructions = []

            for entry in batch:
                account_addr = entry["address"]
                amount = entry["amount"]
                mint = entry["mint"]
                is_dust = amount > 0 or entry.get("is_dust_zero_balance", False)
                
                if not is_dust:
                    continue
                
                # Fix 52 / Phase 41: Burn-before-close — flush any non-zero residue first
                if amount > 0:
                    burn_ix = self._build_burn_instruction(account_addr, mint, amount)
                    if burn_ix:
                        close_instructions.append(burn_ix)
                        logger.debug(f"🔥 Burning {amount} lamports from {account_addr[:8]}…")

                # CloseAccount after draining: zero-balance accounts close cleanly
                close_ix = self._build_close_account_instruction(account_addr)
                if close_ix:
                    close_instructions.append(close_ix)

            if not close_instructions:
                return 0

            # Build and send transaction
            tx = await self._build_bulk_close_transaction(close_instructions)
            success = await self._send_transaction(tx)

            if success:
                # Return estimated rent recovered
                rent_per_account = 2_000_000  # 0.002 SOL in lamports
                # Count only close instructions
                closed_count = sum(1 for ix in close_instructions if b"\x09" in ix.data) # 9 is CloseAccount discriminator
                return closed_count * rent_per_account
            else:
                return 0

        except Exception as e:
            logger.error(f"Batch close failed: {e}")
            return 0

    def _build_close_account_instruction(self, token_account: str):
        """Build CloseAccount instruction for SPL token."""
        try:
            from spl.token.instructions import CloseAccountParams, close_account

            close_params = CloseAccountParams(
                account=Pubkey.from_string(token_account),
                dest=self.wallet_keypair.pubkey(),
                owner=self.wallet_keypair.pubkey(),
                program_id=self.spl_token_program
            )

            return close_account(close_params)

        except Exception as e:
            logger.debug(f"Close instruction build failed: {e}")
            return None

    async def _build_bulk_close_transaction(self, close_instructions: List) -> VersionedTransaction:
        """Build transaction for bulk account closing."""
        try:
            # Get recent blockhash
            blockhash = await self._get_recent_blockhash()

            # Add compute unit limits
            from solders.compute_budget import set_compute_unit_limit
            cu_limit_ix = set_compute_unit_limit(200_000)

            all_instructions = [cu_limit_ix] + close_instructions

            # Fix 2: Validate Compute Budget instruction ordering before compile
            from src.ingest.tx_builder import validate_cb_ordering
            if not validate_cb_ordering(all_instructions):
                logger.error("CRITICAL: ComputeBudget instruction not at index 0. Transaction aborted to prevent SVM panic.")
                return None

            message = MessageV0.try_compile(
                payer=self.wallet_keypair.pubkey(),
                instructions=all_instructions,
                address_lookup_table_accounts=[],
                recent_blockhash=blockhash
            )

            return VersionedTransaction(message, [self.wallet_keypair])

        except Exception as e:
            logger.error(f"Bulk transaction build failed: {e}")
            raise

    async def _send_transaction(self, tx: VersionedTransaction) -> bool:
        """Send transaction to network."""
        try:
            import base64
            tx_b64 = base64.b64encode(tx.serialize()).decode('ascii')

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [tx_b64, {"encoding": "base64"}]
            }

            async with self.session.post(self.rpc_url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data:
                        logger.info(f"Dust sweep transaction sent: {data['result']}")
                        return True

            return False

        except Exception as e:
            logger.error(f"Transaction send failed: {e}")
            return False

    async def _get_recent_blockhash(self) -> Pubkey:
        """Get recent blockhash."""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getRecentBlockhash",
                "params": []
            }

            async with self.session.post(self.rpc_url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    blockhash_str = data.get("result", {}).get("value", {}).get("blockhash")
                    if blockhash_str:
                        return Pubkey.from_string(blockhash_str)

        except Exception as e:
            logger.debug(f"Blockhash fetch failed: {e}")

        # Fallback
        return Pubkey.from_string("11111111111111111111111111111112")

    def get_dust_stats(self) -> Dict[str, Any]:
        """Get statistics about dust sweeping."""
        return {
            "wallet": str(self.wallet_keypair.pubkey()),
            "rpc_url": self.rpc_url,
            "rent_per_account_lamports": 2_000_000,
            "rent_per_account_sol": 0.002
        }