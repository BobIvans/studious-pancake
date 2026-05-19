"""
wSOL Wrapping Engine for Solana Arbitrage Transactions

AMMs do not accept native SOL; they require wSOL (Wrapped SOL).
This module dynamically analyzes arbitrage paths and injects wrapping/unwrapping
instructions when the flashloan provides native SOL or when final output needs
to be converted back to SOL for repayment.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal
from solders.pubkey import Pubkey
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

# Constants
SOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111112")


class WSOLManager:
    """
    Manages dynamic SOL/wSOL wrapping for arbitrage transactions.

    Analyzes arbitrage paths to determine when wrapping/unwrapping is needed:
    - Wrap SOL to wSOL before AMM swaps that don't accept native SOL
    - Unwrap wSOL back to SOL for flashloan repayment when needed
    """

    def __init__(self, wallet_pubkey: Pubkey):
        self.wallet_pubkey = wallet_pubkey
        self.wsol_mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
        self.usdc_mint = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
        from src.config.xstocks_registry import is_xstock_token
        # Token-2022 Program ID for xStocks
        TOKEN_2022_PROGRAM_ID = Pubkey.from_string("TokenzQdBNbLqP5VEhdkAS6EP2rHEjaChQX6n57TR5m")

        if is_xstock_token(self.wsol_mint):
            self.wsol_ata = get_associated_token_address(wallet_pubkey, self.wsol_mint, TOKEN_2022_PROGRAM_ID)
        else:
            self.wsol_ata = get_associated_token_address(wallet_pubkey, self.wsol_mint)

        if is_xstock_token(self.usdc_mint):
            self.usdc_ata = get_associated_token_address(wallet_pubkey, self.usdc_mint, TOKEN_2022_PROGRAM_ID)
        else:
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

    def inject_unwrap_instructions(
        self,
        instructions: List[Instruction],
        insert_position: int = -1
    ) -> List[Instruction]:
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
        Phase 48: Abandoning unwrapping via CloseAccount to preserve ATA rent (0.002 SOL).
        Keeping profit in wSOL is acceptable for our 0.017 SOL budget.
        """
        return []

    def get_wsol_ata(self) -> Pubkey:
        """Get the wSOL ATA for the wallet."""
        return self.wsol_ata

    def is_sol_token(self, token_symbol: str) -> bool:
        """Check if token symbol represents SOL."""
        return token_symbol.upper() in ['SOL', 'WSOL', 'NATIVE_SOL']