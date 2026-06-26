"""
Dynamic K-Hop Transaction Stitcher with Native Instruction Chaining
Automatically constructs multi-hop DEX transactions from arbitrage paths.
Uses native MarginFi flashloan introspection to bypass CPI depth limits.
Caps at 4 hops to fit Solana transaction limits (1232 bytes).
"""

import asyncio
import logging
import math
import os
import aiohttp
from typing import List, Dict, Optional, Any
from decimal import Decimal
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.transaction import VersionedTransaction
from solders.message import MessageV0
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from src.ingest.tx_builder import validate_cb_ordering

COMPUTE_BUDGET_PROG = Pubkey.from_string("ComputeBudget111111111111111111111111111111")

_TOKEN_MINT_MAP = {
    "SOL": "So11111111111111111111111111111111111111112",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}

logger = logging.getLogger(__name__)


class HopInstruction:
    """Represents a single hop in the arbitrage path."""

    def __init__(
        self,
        dex_name: str,
        instruction: Instruction,
        input_amount: Decimal,
        expected_output: Decimal,
        accounts: List[AccountMeta],
    ):
        self.dex_name = dex_name
        self.instruction = instruction
        self.input_amount = input_amount
        self.expected_output = expected_output
        self.accounts = accounts


class KHopStitcher:
    """Stitches multi-hop arbitrage paths into executable transactions."""

    def __init__(self, wallet_keypair):
        self.wallet_keypair = wallet_keypair
        self.max_hops = 4  # Solana transaction limit constraint
        self.max_tx_size = 1232  # bytes

    async def stitch_arbitrage_path(
        self,
        arbitrage_path: List[str],
        hop_amounts: List[Decimal],
        dex_protocols: List[str],
        flashloan_asset: str,
        flashloan_amount: Decimal,
        jito_tip_lamports: int,
        tx_builder: Optional[Any] = None,
        wsol_manager: Optional[Any] = None,
        alt_manager: Optional[Any] = None,
        use_jito: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Stitch a multi-hop arbitrage path into a native instruction-chained transaction.

        Uses MarginFi's flashloan introspection to bypass custom Anchor contract and CPI limits.

        Args:
            arbitrage_path: List of token symbols (e.g., ['SOL', 'USDC', 'SOL'])
            hop_amounts: Input amounts for each hop
            dex_protocols: DEX protocol for each hop (raydium, orca, meteora, sanctum)
            flashloan_asset: Asset to flashloan ('SOL' for native SOL)
            flashloan_amount: Amount to flashloan
            jito_tip_lamports: Jito tip amount
            tx_builder: JupiterTxBuilder instance for native chaining
            wsol_manager: WSOLManager for wrapping/unwrapping
            alt_manager: ALTCacheManager for ALT resolution

        Returns:
            Transaction dict with instructions and metadata, or None on failure
        """
        try:
            if len(arbitrage_path) < 3 or len(arbitrage_path) > self.max_hops + 1:
                logger.warning(f"Invalid path length: {len(arbitrage_path)}")
                return None

            # Build Jupiter swap instructions for each hop
            dex_swap_instructions = []
            if tx_builder and hasattr(tx_builder, 'session') and tx_builder.session:
                for i in range(len(arbitrage_path) - 1):
                    from_token = arbitrage_path[i]
                    to_token = arbitrage_path[i + 1]
                    amount_in = int(
                        (hop_amounts[i] if i < len(hop_amounts) else hop_amounts[-1]) * 1e9
                    )
                    from_mint = _TOKEN_MINT_MAP.get(from_token, from_token)
                    to_mint = _TOKEN_MINT_MAP.get(to_token, to_token)

                    quote = await self._get_jupiter_quote(
                        tx_builder.session, from_mint, to_mint, amount_in
                    )
                    if quote:
                        ixs, _ = await tx_builder.get_swap_instructions(
                            quote, str(self.wallet_keypair.pubkey()), use_custom_cu=True
                        )
                        dex_swap_instructions.extend(ixs)

            if not dex_swap_instructions:
                logger.warning("No DEX swap instructions built via Jupiter")
                return None

            # Use native instruction chaining instead of custom contract
            if not tx_builder:
                logger.error("tx_builder required for native chaining")
                return None

            borrow_amount_lamports = math.ceil(
                flashloan_amount * 1_000_000_000
            )  # Convert SOL to lamports (ceil to ensure full repayment)

            # Build secure flashloan arbitrage transaction wrapped in Anchor
            # Expected min profit = 0.1% for safety, or pass from sizer
            expected_min_profit_lamports = 1000  # Placeholder for 0.000001 SOL

            # Use real MarginFi config
            marginfi_config = {
                "program_id": "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA",
                "marginfi_group": "4qp6Fx6tnZkY5Wropq9wUYgtFxXKwE6viZxFHg3rdAG8",
                "marginfi_account": "Fk4G5NB5e1NyULQCCpTNLWCmChCW2UbDwpkEofqAiHk2",
                "bank_pubkey": "2s37akK2eyBbp8DZgCm7RtsaEz8eWhVKGfHGA3cKMEW2",
                "bank_liquidity_vault": "2s37YhpR...",
                "bank_liquidity_vault_authority": "...",
            }

            tx_data = await tx_builder.build_native_flashloan_tx(
                wallet_pubkey=str(self.wallet_keypair.pubkey()),
                arbitrage_path=arbitrage_path,
                borrow_amount_lamports=borrow_amount_lamports,
                expected_min_profit_lamports=expected_min_profit_lamports,
                dex_swap_instructions=dex_swap_instructions,
                marginfi_config=marginfi_config,
                jito_tip_lamports=jito_tip_lamports,
                wsol_manager=wsol_manager,
                pool_state_manager=None,  # Would be passed
                use_jito=use_jito,
            )

            if not tx_data:
                logger.warning("Failed to build native flashloan arbitrage transaction")
                return None

            # Validate final transaction size
            all_instructions = tx_data["instructions"]
            if not await self._validate_transaction_size(all_instructions):
                logger.warning("Final transaction exceeds size limit")
                return None

            logger.info(
                f"✅ Stitched native arbitrage: path={arbitrage_path} | "
                f"hops={len(arbitrage_path)-1} | borrow={flashloan_amount:.4f} {flashloan_asset} | "
                f"ixs={len(all_instructions)} | tip={jito_tip_lamports} lamports"
            )

            return tx_data

        except Exception as e:
            logger.error(f"Native stitching failed: {e}")
            return None

    # Fix 36: All DEX-specific instruction builders removed.
    # Real swap assembly happens via JupiterTxBuilder in tx_builder.py.
    # These were empty stubs returning instructions with accounts=[] and data=b"",
    # which would break any transaction they were included in.
        """Validate that stitched transaction fits Solana limits."""
        try:
            # Rough size estimation
            total_size = 0
            for ix in instructions:
                # Estimate size based on accounts and data
                total_size += len(ix.accounts) * 32 + len(ix.data)

            return total_size <= self.max_tx_size

        except Exception:
            return False

    async def _build_transaction(
        self, instructions: List[Instruction]
    ) -> VersionedTransaction:
        """Build VersionedTransaction from instructions."""
        try:
            # Get recent blockhash (would be injected)
            blockhash = "11111111111111111111111111111112"  # Placeholder

            # ── FIX 2: Compute Budget Strict Ordering check ────────────────
            if not validate_cb_ordering(
                instructions, "k_hop_stitcher._build_transaction"
            ):
                logger.critical(
                    "CRITICAL: ComputeBudget ordering violation in k_hop_stitcher. Skipping TX."
                )
                raise RuntimeError("ComputeBudget instructions not at index 0/1")
            # ─────────────────────────────────────────────────────────────────
            message = MessageV0.try_compile(
                payer=self.wallet_keypair.pubkey(),
                instructions=instructions,
                address_lookup_table_accounts=[],
                recent_blockhash=Pubkey.from_string(blockhash),
            )

            return VersionedTransaction(message, [self.wallet_keypair])

        except Exception as e:
            logger.error(f"Transaction build failed: {e}")
            raise

    # Fix 36: All DEX-specific instruction builders removed.
    # Real swap assembly happens via JupiterTxBuilder in tx_builder.py.
    # These were empty stubs returning instructions with accounts=[] and data=b"",
    # which would break any transaction they were included in.
