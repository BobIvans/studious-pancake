"""
Transaction Prebuilder - Pre-positioning Module

Creates transaction templates in memory to save 50-100ms during execution.
Pre-builds flash-loan transaction structure with all instructions except dynamic data.
Phase 30: Ensures blockhashes are NOT cached and TTL is strictly limited to 30s.
"""

import logging
import time
import copy
from typing import Dict, List, Optional, Any, Tuple
from spl.token.constants import ASSOCIATED_TOKEN_PROGRAM_ID

logger = logging.getLogger("TransactionPrebuilder")

class TransactionPrebuilder:
    """Pre-builds transaction templates for flash-loan arbitrage."""

    def __init__(self, template_expiry_seconds: int = 30):
        # Phase 30: Strictly limit TTL to 30 seconds to prevent blockhash expiry
        self.template_expiry_seconds = template_expiry_seconds
        # Key: (in_mint, out_mint), Value: {instructions, alts, timestamp}
        self.templates: Dict[Tuple[str, str], Dict[str, Any]] = {}

        logger.info(f"🔨 TransactionPrebuilder initialized (TTL: {template_expiry_seconds}s)")

    def cache_template(self, in_mint: str, out_mint: str, instructions: List[Any], alts: List[Any]):
        """Cache instructions and ALTs for a pair. NEVER cache blockhash here.

        BLOCKS caching if the instruction list contains dynamic instructions
        that may change between calls (CreateATA, SyncNative, etc.), preventing
        stale repay-index references from cached templates.
        """
        ATA_PROGRAM = str(ASSOCIATED_TOKEN_PROGRAM_ID)
        from spl.token.constants import TOKEN_PROGRAM_ID
        from solders.system_program import ID as SYSTEM_PROGRAM_ID
        # FIX 212: Prevent caching of dynamic instructions (System transfers, SyncNative)
        ATTACHED_PROGRAM_IDS = {
            ATA_PROGRAM,
            str(TOKEN_PROGRAM_ID),
            str(SYSTEM_PROGRAM_ID)
        }
        has_dynamic = any(
            str(ix.program_id) in ATTACHED_PROGRAM_IDS
            for ix in instructions
        )
        if has_dynamic:
            logger.debug(
                f"Skipping cache for {in_mint[:8]} -> {out_mint[:8]}: "
                "dynamic instructions (CreateATA/SyncNative) detected — caching skipped"
            )
            return
        self.templates[(in_mint, out_mint)] = {
            "instructions": instructions,
            "alts": alts,
            "timestamp": time.time()
        }
        logger.debug(f"Cached template for {in_mint[:8]} -> {out_mint[:8]}")

    def get_template(self, in_mint: str, out_mint: str) -> Optional[Dict[str, Any]]:
        """Get pre-built transaction template for a pair if not expired."""
        template = self.templates.get((in_mint, out_mint))
        if template:
            if time.time() - template["timestamp"] < self.template_expiry_seconds:
                return copy.deepcopy(template)  # FIX 213: Prevent cache poisoning by returning a deep copy
            else:
                # Cleanup expired template
                del self.templates[(in_mint, out_mint)]
        return None

    def get_template_stats(self):
        """Get statistics about built templates."""
        return {
            "template_count": len(self.templates),
            "expiry_seconds": self.template_expiry_seconds
        }