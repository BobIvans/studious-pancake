"""
Zero-Dust Guard & Crash Recovery
Automatically cleans stranded Token Accounts (value < $1.00) and recovers ATA rent (0.00203928 SOL per account).
Critical for protecting the 0.015 SOL budget from accumulation of low-value dust.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set
from decimal import Decimal
import aiohttp
from solders.pubkey import Pubkey
from solders.hash import Hash
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
        self._fail_tracker = {}
        self._blacklist = set()
        self.spl_token_program = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        self.spl_token_2022_program = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EP2rHEjaChQX6n57TR5m")
        self.usdc_mint = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
        self.wsol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
        from spl.token.instructions import get_associated_token_address
        self.usdc_ata = str(get_associated_token_address(wallet_keypair.pubkey(), self.usdc_mint))
        self.wsol_ata = str(get_associated_token_address(wallet_keypair.pubkey(), self.wsol_mint))
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

    async def sweep_after_successful_tx(self) -> int:
        """Light post-tx dust sweep — called by execution_router after confirmed arbitrage.
        Skips startup/shutdown log noise; returns lamports recovered for metrics."""
        logger.debug("🧹 Post-tx dust sweep...")
        recovered = await self._sweep_dust()
        if recovered > 0:
            logger.info(f"✅ Post-tx sweep recovered {recovered / 1e9:.6f} SOL")
        return recovered

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

                # ── ПЕРВАЯ ЛИНИЯ ЗАЩИТЫ: Никогда не трогать Golden ATAs ──────────
                # Абсолютная защита wSOL и USDC ATAs от sweep, даже если звание
                # dust_check вдруг вернёт True из-за ошибки парса.
                if str(account_address) in self.golden_atas:
                    continue

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

                    # Phase 8: Skip blacklisted accounts to avoid burning gas on broken accounts
                    if str(account_address) in self._blacklist:
                        logger.debug(f"Skipping blacklisted dust account: {account_address}")
                        continue

                    dust_accounts.append({
                        "address": account_address,
                        "amount": raw_amount,
                        "mint": mint
                    })
                    # Estimate rent recovery (0.00203928 SOL = 2_039_280 lamports)
                    total_rent_recovered += 2_039_280

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
        """Get all Token Accounts owned by our wallet (classic SPL + Token-2022)."""
        all_accounts = []
        for program_id in [self.spl_token_program, self.spl_token_2022_program]:
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenAccountsByOwner",
                    "params": [
                        str(self.wallet_keypair.pubkey()),
                        {
                            "programId": str(program_id)
                        },
                        {
                            "encoding": "jsonParsed"
                        }
                    ]
                }

                async with self.session.post(self.rpc_url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        accounts = data.get("result", {}).get("value", [])
                        all_accounts.extend(accounts)
                    else:
                        logger.error(f"Failed to get token accounts for {program_id}: {resp.status}")

            except Exception as e:
                logger.error(f"Token account query failed for {program_id}: {e}")

        return all_accounts

    async def _is_dust_account(self, account_data: Dict) -> bool:
        """
        Determine if a token account should be swept.

        P0-13: Added USD value check via Pyth price feeder.
        Only sweeps if the total USD value is less than $1.00.
        If price cannot be obtained, conservatively returns False (not dust).

        Fix #5 — Aggressive ATA Rent Recovery for 0.017 SOL capital:
        - Core Golden (USDC, wSOL): НИКОГДА не трогаем
        - Zero-balance не-golden: dust (no USD risk)
        - Все остальные: < $1.00 = dust, >= $1.00 = keep
        """
        try:
            data_field = account_data.get("data", {})
            # ── ИСПРАВЛЕНИЕ: Если RPC не смог распарсить аккаунт, он возвращает list. Пропускаем его. ──
            if isinstance(data_field, list):
                return False
            parsed_data = data_field.get("parsed", {})
            info = parsed_data.get("info", {})

            ui_amount = float(info.get("tokenAmount", {}).get("uiAmountString", "0"))
            mint = info.get("mint", "")
            raw_amount = int(info.get("tokenAmount", {}).get("amount", "0"))

            # ── АБСОЛЮТНАЯ ЗАЩИТА: Никогда не трогать SOL и USDC ──────────
            if mint in [
                "So11111111111111111111111111111111111111112",  # wSOL
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # jitoSOL
                "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",  # mSOL
                "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",  # bSOL
                "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",  # INF
            ]:
                return False

            # Zero balance — всегда dust (кроме golden, уже проверено выше)
            if ui_amount == 0:
                return True

            # P0-13: USD value check — only sweep if < $1.00
            usd_price = None
            try:
                from src.ingest.pyth_core_price_feeder import get_pyth_core_feeder
                feeder = get_pyth_core_feeder()
                if feeder is not None:
                    usd_price = feeder.get_price(mint)
            except Exception:
                pass

            if usd_price is not None and usd_price > 0:
                usd_value = ui_amount * usd_price
                # Only dust if < $1.00
                if usd_value >= 1.0:
                    return False
                logger.debug(
                    f"💸 Dust check: {mint[:8]} amount={ui_amount:.6f} "
                    f"@ ${usd_price:.4f} = ${usd_value:.2f} < $1.00 — is dust"
                )
                return True

            # Price unavailable — conservative: assume NOT dust (P0-13 safety)
            logger.debug(
                f"⚠️ Dust check: {mint[:8]} amount={ui_amount:.6f}, "
                f"no price data — safe default: NOT dust"
            )
            return False

        except Exception:
            return False

    def _build_burn_instruction(self, token_account: str, mint: str, amount: int):
        """Build Burn instruction for SPL token (Phase 41)."""
        try:
            from spl.token.instructions import BurnParams, burn

            program_id = self.spl_token_program

            burn_params = BurnParams(
                program_id=program_id,
                account=Pubkey.from_string(token_account),
                mint=Pubkey.from_string(mint),
                owner=self.wallet_keypair.pubkey(),
                amount=amount,
                signers=[self.wallet_keypair]
            )
            return burn(burn_params)
        except Exception as e:
            logger.debug(f"Burn instruction build failed: {e}")
            return None

    async def _close_dust_accounts_batch(self, batch: List[Dict]) -> int:
        """Close a batch of dust token accounts and recover rent."""
        try:
            close_instructions = []
            valid_batch = []

            for entry in batch:
                account_addr = entry["address"]
                amount = entry["amount"]
                mint = entry["mint"]

                # Phase 8: Skip blacklisted accounts
                if str(account_addr) in self._blacklist:
                    logger.debug(f"Skipping blacklisted account in batch: {account_addr}")
                    continue

                is_dust = amount > 0 or entry.get("is_dust_zero_balance", False)
                
                if not is_dust:
                    continue
                
                # Task 14: Final safety check for Token-2022 (extensions can hide balance)
                # If amount > 0, we'll try to burn, but if it fails we shouldn't close.
                # Burn before close for non-zero residue
                if amount > 0:
                    burn_ix = self._build_burn_instruction(account_addr, mint, amount)
                    if burn_ix:
                        close_instructions.append(burn_ix)
                        logger.debug(f"🔥 Burning {amount} lamports from {account_addr[:8]}…")

                close_ix = self._build_close_account_instruction(account_addr, mint=mint)
                if close_ix:
                    close_instructions.append(close_ix)
                    valid_batch.append(account_addr)

            if not close_instructions:
                return 0

            # Build and send transaction
            tx = await self._build_bulk_close_transaction(close_instructions)
            success = await self._send_transaction(tx)

            if success:
                # Clear failures on success
                for addr in valid_batch:
                    self._fail_tracker.pop(str(addr), None)
                    # СИНХРОНИЗАЦИЯ КЭША ATA_CACHE
                    try:
                        import src.ingest.shared_state as _shared_state
                        _shared_state.ATA_CACHE.discard(str(addr))
                    except Exception:
                        pass
                
                # Return estimated rent recovered
                rent_per_account = 2_039_280  # Exact rent-exemption lamports
                closed_count = len(valid_batch)
                return closed_count * rent_per_account
            else:
                # Task 14: Track failures
                for addr in valid_batch:
                    addr_str = str(addr)
                    self._fail_tracker[addr_str] = self._fail_tracker.get(addr_str, 0) + 1
                    if self._fail_tracker[addr_str] >= 2:
                        logger.warning(f"🚫 Blacklisting dust account {addr_str[:8]} after 2 failures")
                        self._blacklist.add(addr_str)
                return 0

        except Exception as e:
            logger.error(f"Batch close failed: {e}")
            return 0

    def _build_close_account_instruction(self, token_account: str, mint: Optional[str] = None):
        """Build CloseAccount instruction for SPL/Token-2022 token.

        Args:
            token_account: Token account address to close.
                  correct program ID (Tokenz… vs Tokenkeg…) is used.
                  If None, falls back to classic SPL Token program.
        """
        try:
            from spl.token.instructions import CloseAccountParams, close_account

            program_id = self.spl_token_program

            close_params = CloseAccountParams(
                account=Pubkey.from_string(token_account),
                dest=self.wallet_keypair.pubkey(),
                owner=self.wallet_keypair.pubkey(),
                program_id=program_id,
                signers=[],
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
            from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
            cu_limit_ix = set_compute_unit_limit(200_000)
            # FIX 9 (Dust Sweeper Mempool Freezing): Add priority fee instruction
            # so garbage-collection transactions don't get stuck in the mempool.
            # 100_000 micro-lamports = 0.00001 SOL priority fee — negligible but vital.
            cu_price_ix = set_compute_unit_price(100_000)

            all_instructions = [cu_limit_ix, cu_price_ix] + close_instructions

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
        import os
        if str(os.getenv("PAPER_TRADING_ONLY", "false")).lower() == "true":
            return True
        try:
            import base64
            tx_b64 = base64.b64encode(bytes(tx)).decode('ascii')

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

    async def _get_recent_blockhash(self) -> Hash:
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
                        return Hash.from_string(blockhash_str)

        except Exception as e:
            logger.debug(f"Blockhash fetch failed: {e}")

        # Fallback
        return Hash.from_string("11111111111111111111111111111111")

    def get_dust_stats(self) -> Dict[str, Any]:
        """Get statistics about dust sweeping."""
        return {
            "wallet": str(self.wallet_keypair.pubkey()),
            "rpc_url": self.rpc_url,
            "rent_per_account_lamports": 2_039_280,
            "rent_per_account_sol": 0.00203928
        }