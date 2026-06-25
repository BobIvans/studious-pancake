"""
wSOL Wrapping Engine for Solana Arbitrage Transactions

AMMs do not accept native SOL; they require wSOL (Wrapped SOL).
This module dynamically analyzes arbitrage paths and injects wrapping/unwrapping
instructions when the flashloan provides native SOL or when final output needs
to be converted back to SOL for repayment.
"""

import asyncio
import logging
import aiohttp
import time
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal
from solders.hash import Hash
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.system_program import TransferParams, transfer
from spl.token.instructions import get_associated_token_address, sync_native, close_account, CloseAccountParams, SyncNativeParams, create_associated_token_account
try:
    from spl.token.instructions import create_idempotent_associated_token_account
    CREATE_ATA_FUNCTION = create_idempotent_associated_token_account
except ImportError:
    CREATE_ATA_FUNCTION = create_associated_token_account
from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID

logger = logging.getLogger(__name__)

# Fix 67: Balance lock flags moved to shared_state.py to eliminate circular imports.
# Previously imported arb_bot, which caused recursive module execution.
import src.ingest.shared_state as _shared_state_lock


def _balance_lock_can_trade() -> bool:
    """Check if trading is allowed (not paused after wSOL unwrap)."""
    if _shared_state_lock._balance_lock_paused and time.time() < _shared_state_lock._balance_lock_pause_until:
        return False
    if _shared_state_lock._balance_lock_paused and time.time() >= _shared_state_lock._balance_lock_pause_until:
        _shared_state_lock._balance_lock_paused = False
        _shared_state_lock._balance_lock_pause_until = 0.0
    return True

# Constants
SOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111112")


class WSOLManager:
    """
    Manages dynamic SOL/wSOL wrapping for arbitrage transactions.

    Analyzes arbitrage paths to determine when wrapping/unwrapping is needed:
    - Wrap SOL to wSOL before AMM swaps that don't accept native SOL
    - Unwrap wSOL back to SOL for flashloan repayment when needed
    - Auto-unwrap wSOL when native balance drops below threshold (Fix 1)
    """

    def __init__(self, wallet_pubkey: Pubkey, keypair: Optional[Keypair] = None, session: Optional[aiohttp.ClientSession] = None):
        self.wallet_pubkey = wallet_pubkey
        self.keypair = keypair
        self.session = session
        self.wsol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
        self.usdc_mint = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
        self.wsol_ata = get_associated_token_address(wallet_pubkey, self.wsol_mint)
        self.usdc_ata = get_associated_token_address(wallet_pubkey, self.usdc_mint)

        # Phase 48: ATA Cache (Golden ATAs that should NEVER be closed)
        self.golden_atas = {
            str(self.wsol_ata): "wSOL",
            str(self.usdc_ata): "USDC"
        }

    def analyze_path_for_wrapping(
        self,
        arbitrage_path: List[str],
        flashloan_asset: str,
        flashloan_amount: int
    ) -> Dict[str, Any]:
        """
        Analyze arbitrage path to determine wrapping requirements.

        Args:
            arbitrage_path: List of token symbols (e.g., ['SOL', 'USDC', 'SOL'])
            flashloan_asset: Asset being flashloaned
            flashloan_amount: Amount being flashloaned in lamports

        Returns:
            Dict with wrapping analysis:
            {
                'needs_initial_wrap': bool,
                'needs_final_unwrap': bool,
                'initial_wrap_amount': int or None,
                'final_unwrap_amount': int or None
            }
        """
        analysis = {
            'needs_initial_wrap': False,
            'needs_final_unwrap': False,
            'initial_wrap_amount': None,
            'final_unwrap_amount': None
        }

        # Check if flashloan provides native SOL
        if flashloan_asset.upper() == 'SOL':
            # First hop determines if wrapping is needed
            first_hop = arbitrage_path[0].upper()
            if first_hop == 'SOL':
                # AMMs require wSOL for swaps, so we need to wrap
                analysis['needs_initial_wrap'] = True
                analysis['initial_wrap_amount'] = flashloan_amount

        # Check if final output is wSOL that needs unwrapping for repayment
        final_token = arbitrage_path[-1].upper()
        if final_token == 'SOL' and flashloan_asset.upper() == 'SOL':
            # If we end with SOL but flashloan expects native SOL,
            # we might need to unwrap (depending on AMM output format)
            # Most AMMs output wSOL, so we typically need to unwrap
            analysis['needs_final_unwrap'] = True
            # final_unwrap_amount will be calculated after swaps

        logger.debug(f"wSOL analysis for path {arbitrage_path}: {analysis}")
        return analysis

    def inject_wrap_instructions(
        self,
        instructions: List[Instruction],
        wrap_amount: int,
        insert_position: int = 0
    ) -> List[Instruction]:
        """
        Inject SOL->wSOL wrapping instructions into transaction.

        Args:
            instructions: Original instruction list
            wrap_amount: Amount of SOL to wrap (in lamports)
            insert_position: Where to insert wrapping instructions

        Returns:
            Modified instruction list with wrapping injected
        """
        wrap_instructions = self._create_wrap_instructions(wrap_amount)

        # Insert wrapping instructions at specified position
        modified_instructions = (
            instructions[:insert_position] +
            wrap_instructions +
            instructions[insert_position:]
        )

        logger.debug(f"Injected {len(wrap_instructions)} wrapping instructions at position {insert_position}")
        return modified_instructions

    def inject_unwrap_instructions(self, instructions: List[Instruction], insert_position: int = -1) -> List[Instruction]:
        """
        Inject wSOL->SOL unwrapping instructions into transaction.

        Args:
            instructions: Original instruction list
            insert_position: Where to insert unwrapping instructions (-1 for end)

        Returns:
            Modified instruction list with unwrapping injected
        """
        unwrap_instructions = self._create_unwrap_instructions()

        if insert_position == -1:
            # Insert at end
            modified_instructions = instructions + unwrap_instructions
        else:
            modified_instructions = (
                instructions[:insert_position] +
                unwrap_instructions +
                instructions[insert_position:]
            )

        logger.debug(f"Injected {len(unwrap_instructions)} unwrapping instructions at position {insert_position}")
        return modified_instructions

    def _create_wrap_instructions(self, amount: int) -> List[Instruction]:
        """
        Create instructions to wrap SOL into wSOL.

        Phase 48 (MTU Optimization): CreateIdempotentATA removed from arb TX.
        The wSOL ATA is held permanently (golden ATA) and must be pre-funded
        via the DustSweeper or manual wrap, not created per-transaction.
        AMMs accept wSOL directly; Jupiter routes handle syncNative internally.

        Returns:
            List of wrapping instructions (empty — wrap/pre-fund ATA externally)
        """
        # Phase 48: Zero-instruction wrap — ATA is held permanently
        # Any required syncNative is handled by Jupiter swap-instructions
        return []

    def _create_unwrap_instructions(self) -> List[Instruction]:
        """
        Create instructions to unwrap wSOL back to Native SOL.

        Fix 1 (Capital Death Spiral): After profitable Jupiter swaps, profits land
        in the wSOL ATA as wSOL tokens. Jito tips, however, are paid from Native SOL.
        With a 0.017 SOL budget, 3 successive trades drain native balance below the
        0.005 SOL minimum, causing InsufficientFundsForFee even though the wSOL ATA
        holds the profit.

        Solution: Close the wSOL ATA (CloseAccount) to extract all lamports back
        to the main wallet as Native SOL. Jupiter sets the wSOL token balance equal
        to the total lamports in the ATA account via SyncNative during swap output.
        The close_account instruction transfers ALL lamports (token balance + 0.002 SOL
        ATA rent) back to the destination wallet as Native SOL lamports.

        The caller should insert these instructions BEFORE any system-program transfers
        (Jito tips) so that Native SOL is replenished before tip payment is attempted.

        Note: The wSOL ATA is re-created automatically on the next Jupiter swap via
        CREATE_ATA_FUNCTION (idempotent — no cost if account already exists).
        """
        wallet = self.wallet_pubkey
        wsol_mint = self.wsol_mint

        prog_id = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

        # CloseAccount transfers all wSOL tokens + 0.002 SOL ATA rent
        # back to the main wallet as Native SOL lamports
        close_ix = close_account(CloseAccountParams(
            program_id=prog_id,
            account=self.wsol_ata,
            dest=wallet,
            owner=wallet,
            signers=[],
        ))

        logger.debug(
            f"🔓 wSOL unwrap: closing ATA {self.wsol_ata} "
            f"→ recovers rent + all wSOL tokens as Native SOL"
        )
        return [close_ix]

    async def check_and_unwrap_wsol(
        self,
        rpc_url: str,
        native_balance_sol: float,
        unwrap_threshold_sol: Optional[float] = None,
        min_wsol_sol: float = 0.004,
    ) -> bool:
        """
        Check if wSOL ATA balance should be unwrapped to Native SOL and execute the unwrap.

        Fix 1 (Capital Death Spiral): Jupiter swap profits land in the wSOL ATA while
        Jito tips drain Native SOL. With a 0.015 SOL budget, 3-4 trades exhaust the native
        balance even though wSOL keeps accumulating. The existing `wallet_balance_listener`
        only checks every 10 seconds — too slow for HFT.

        This method is called at the START of every trade cycle (hot path, 0.5-1s cadence).
        If wSOL balance exceeds the threshold AND native balance is below threshold, the
        wSOL ATA is closed via a standalone RPC transaction — lamports immediately return
        to native SOL wallet. Jupiter recreates the ATA on the next swap
        (idempotent ATA creation is free if the account already exists).

        Args:
            rpc_url: RPC URL for wSOL balance query
            native_balance_sol: Current Native SOL balance (already known to caller)
            unwrap_threshold_sol: Native below this → consider unwrapping (defaults to Config.MIN_RESERVE_SOL)
            min_wsol_sol: Only unwrap if wSOL balance >= this (covers 0.002 SOL rent + profit)

        Returns:
            True if wSOL was unwrapped, False if no action needed.
        """
        import os
        if str(os.getenv("PAPER_TRADING_ONLY", "false")).lower() == "true":
            return True
        # Fix 74+78: Safe session fallback + safe str() casting on wsol_ata
        _session = self.session
        _session_owned = False
        if _session is None:
            try:
                _session = aiohttp.ClientSession()
                _session_owned = True
                logger.debug("Fix 74: Created ad-hoc aiohttp session for check_and_unwrap_wsol")
            except Exception as e:
                logger.debug(f"wSOL unwrap: failed to create session: {e}")
                return False

        wsol_balance_lamports = 0
        
        if unwrap_threshold_sol is None:
            import os
            unwrap_threshold_sol = float(os.getenv("MIN_RESERVE_SOL", "0.010"))

        # Only run the check when native balance is already below threshold
        if native_balance_sol >= unwrap_threshold_sol:
            if _session_owned:
                await _session.close()
            return False

        try:
            # Fix 78: Safe str() casting on wsol_ata for RPC queries
            wsol_ata_str = str(self.wsol_ata)
            query_payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenAccountBalance",
                "params": [wsol_ata_str]
            }
            timeout = aiohttp.ClientTimeout(total=2.0)
            async with _session.post(rpc_url, json=query_payload, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and "value" in data["result"]:
                        wsol_balance_lamports = int(data["result"]["value"]["amount"])
        except Exception as e:
            logger.debug(f"wSOL balance query failed: {e}")
            if _session_owned:
                await _session.close()
            return False

        wsol_balance_sol = wsol_balance_lamports / 1e9

        if wsol_balance_lamports < int(min_wsol_sol * 1e9):
            logger.debug(
                f"💧 wSOL balance {wsol_balance_sol:.4f} SOL < {min_wsol_sol} SOL "
                f"(native={native_balance_sol:.4f} SOL < {unwrap_threshold_sol} SOL) — unwrap threshold not met"
            )
            if _session_owned:
                await _session.close()
            return False

        logger.info(
            f"🔓 Fix 1: wSOL unwrap triggered — "
            f"native={native_balance_sol:.4f} SOL < {unwrap_threshold_sol} SOL, "
            f"wSOL={wsol_balance_sol:.4f} SOL exceeds {min_wsol_sol} SOL threshold"
        )

        # Close wSOL ATA → all lamports (tokens + rent) return as Native SOL
        unwrap_ixs = self._create_unwrap_instructions()
        if not unwrap_ixs:
            if _session_owned:
                await _session.close()
            return False

        # Build and send a standalone CloseAccount transaction via RPC
        from solders.message import MessageV0
        from solders.transaction import VersionedTransaction
        from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
        import base64

        try:
            cu_limit_ix = set_compute_unit_limit(50_000)
            cu_price_ix = set_compute_unit_price(20_000)
            all_ixs = [cu_limit_ix, cu_price_ix] + unwrap_ixs

            # Use helius direct URL for fresh blockhash
            helius_url = rpc_url  # rpc_url IS the direct RPC HTTP URL
            bh_payload = {"jsonrpc": "2.0", "id": 1, "method": "getLatestBlockhash",
                          "params": [{"commitment": "confirmed"}]}
            async with _session.post(helius_url, json=bh_payload, timeout=aiohttp.ClientTimeout(total=2.0)) as bh_resp:
                if bh_resp.status != 200:
                    logger.warning("wSOL unwrap: failed to get blockhash")
                    return False
                bh_data = await bh_resp.json()
                bh_str = bh_data["result"]["value"]["blockhash"]

            msg = MessageV0.try_compile(
                payer=self.wallet_pubkey,
                instructions=all_ixs,
                address_lookup_table_accounts=[],
                recent_blockhash=Hash.from_string(bh_str)
            )
            if self.keypair is None:
                logger.error("wSOL unwrap: keypair is None — cannot sign transaction")
                return False
            tx = VersionedTransaction(msg, [self.keypair])

            tx_b64 = base64.b64encode(bytes(tx)).decode("ascii")
            send_payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "sendTransaction",
                "params": [tx_b64, {"encoding": "base64"}]
            }
            async with _session.post(helius_url, json=send_payload, timeout=aiohttp.ClientTimeout(total=3.0)) as send_resp:
                if send_resp.status == 200:
                    result = await send_resp.json()
                    if "result" in result:
                        # Fix 67: Use shared_state instead of import arb_bot
                        _shared_state_lock.set_balance_lock_paused(True, 0.4)
                        logger.info(
                            f"✅ wSOL unwrap sent: {wsol_balance_sol:.4f} wSOL → Native SOL. "
                            f"Paused next trade for 400ms to allow account state convergence."
                        )
                        return True
                    else:
                        logger.warning(f"wSOL unwrap send rejected: {result}")
                else:
                    logger.warning(f"wSOL unwrap HTTP {send_resp.status}")
        except Exception as e:
            logger.warning(f"wSOL unwrap transaction failed: {e}")
        finally:
            if _session_owned:
                await _session.close()

        return False

    def get_wsol_ata(self) -> Pubkey:
        """Get the wSOL ATA for the wallet."""
        return self.wsol_ata

    def is_sol_token(self, token_symbol: str) -> bool:
        """Check if token symbol represents SOL."""
        return token_symbol.upper() in ['SOL', 'WSOL', 'NATIVE_SOL']
