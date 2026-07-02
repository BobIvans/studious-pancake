"""Smart Retry Engine - Universal transaction recalculation without cooldown blocks."""

import asyncio
import logging
from typing import Dict, Any, Optional, Callable, Tuple

logger = logging.getLogger(__name__)

class SmartRetryEngine:
    """Universal smart retry logic that recalculates trade size instead of cooling down.
    
    When simulation fails due to slippage/liquidity, immediately recalculates
    optimal borrow size and refetches quotes rather than blocking the strategy.
    """

    MIN_FLASH_LOAN_SIZE_LAMPORTS = 10_000_000  # 0.01 SOL floor — dust-sized flashloans waste gas
    
    @staticmethod
    def should_retry(reason: str) -> Tuple[bool, str]:
        """Determine if retry should be attempted and what mode to use."""
        reason_lower = reason.lower()
        if any(kw in reason_lower for kw in ["slippage", "liquidity", "depth"]):
            return True, "slippage"
        if any(kw in reason_lower for kw in ["accountnotfound", "rent", "insufficient", "mtu", "size"]):
            return True, "route"
        return False, "unknown"
    
    @staticmethod
    def calculate_retry_amount(
        original_amount: int,
        expected_profit: float,
        mode: str,
        retry_count: int = 0
    ) -> Tuple[int, float]:
        """Calculate reduced amount and profit for retry.
        
        Args:
            original_amount: Original borrow amount in lamports
            expected_profit: Original expected profit in SOL
            mode: "slippage" or "route"
            retry_count: Number of previous retries
            
        Returns:
            Tuple of (new_amount_lamports, new_expected_profit_sol)
        """
        # Exponential decay: 50% reduction per retry, but enforce MIN_FLASH_LOAN_SIZE_LAMPORTS floor
        decay_factor = 0.5 ** (retry_count + 1)
        raw_amount = int(original_amount * decay_factor)
        if raw_amount < SmartRetryEngine.MIN_FLASH_LOAN_SIZE_LAMPORTS:
            return -1, 0.0  # abort signal: flashloan below minimum viable size
        new_amount = raw_amount
        new_profit = max(expected_profit * decay_factor, 0.0)
        return new_amount, new_profit
    
    @staticmethod
    async def execute_retry(
        opportunity: Dict[str, Any],
        refetch_func: Callable,
        execute_func: Callable,
        jito_bidding_manager: Any = None,
        original_amount: int = 0,
        original_profit: float = 0.0,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Execute smart retry with recalculated parameters.
        
        Args:
            opportunity: Original opportunity dict
            refetch_func: Async function to rebuild quotes (must accept amount, amount_lamports, etc.)
            execute_func: Async function to re-execute opportunity
            jito_bidding_manager: For dynamic tip calculation
            original_amount: Original borrow amount
            original_profit: Original expected profit in SOL
            reason: Failure reason string
            
        Returns:
            Result dict from retry execution
        """
        retry_state = opportunity.get("_smart_retry", {})
        retry_count = retry_state.get("count", 0)
        
        # Fix 65: Max 3 retries with exponential backoff
        max_retries = 3
        if retry_count >= max_retries:
            return {"status": "error", "message": f"Retry exhausted ({max_retries}/{max_retries}): {reason}"}
        
        should_retry, mode = SmartRetryEngine.should_retry(reason)
        if not should_retry:
            return {"status": "error", "message": reason}
        
        # Exponential backoff: delay = 0.5 * (2 ** retry_count) seconds
        delay = 0.5 * (2 ** retry_count)
        logger.warning(f"🔄 SmartRetry Engine: attempt {retry_count + 1}/{max_retries}, "
                       f"mode={mode}, backing off {delay:.1f}s...")
        await asyncio.sleep(delay)
        
        from src.ingest.blockhash_racing import get_blockhash_manager
        bh_mgr = get_blockhash_manager()
        if bh_mgr:
            await bh_mgr.fetch_fresh_blockhash()
        
        retry_opportunity = dict(opportunity)
        retry_opportunity["_smart_retry"] = {"used": True, "count": retry_count + 1, "mode": mode}
        
        # Calculate new parameters
        new_amount, new_profit = SmartRetryEngine.calculate_retry_amount(
            original_amount, original_profit, mode, retry_count
        )
        
        logger.warning(f"🔄 SmartRetry Engine: {mode} mode, amount {original_amount} → {new_amount}, profit {original_profit:.6f} → {new_profit:.6f}")
        
        # Refetch quotes with reduced amount
        try:
            # Ensure smart retry strictly uses onlyDirectRoutes=True to prevent rent traps
            retry_quote = await refetch_func(
                opportunity.get("quote", {}),
                new_amount,
                only_direct_routes=True
            )
            if not retry_quote:
                return {"status": "error", "message": f"Quote rebuild failed for {mode}: {reason}"}
            retry_opportunity["quote"] = retry_quote
        except Exception as e:
            logger.warning(f"SmartRetry quote rebuild error: {e}")
            return {"status": "error", "message": f"Quote rebuild error: {e}"}
        
        # Update amounts
        if mode == "slippage":
            retry_opportunity["optimal_size_lamports"] = new_amount
            retry_opportunity["expected_profit_sol"] = new_profit
        else:
            retry_opportunity["borrow_amount"] = new_amount
            retry_opportunity["expected_profit_lamports"] = int(new_profit * 1e9)
        
        return await execute_func(retry_opportunity)