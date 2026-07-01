"""G2TipManager — Dynamic Jito Tip Strategy + ExecutionGuard Circuit Breaker."""

import asyncio
import logging
import time
from collections import defaultdict

logger = logging.getLogger("G2TipManager")


class G2TipManager:
    """Determines dynamic Jito tip amounts based on strategy type and expected profit."""

    def __init__(self):
        self.base_tips = {
            "LST_EPOCH": 15000,
            "SANCTUM_ROUTER": 15000,
            "GRADUATION": 35000,
            "DEFAULT": 50000,  # Jito Relay floor is ~50k lamports
        }
        self.max_tip = 150000  # Maximum 0.00015 SOL (capital protection!)
        self.escalation = 1.5
        self.history = defaultdict(list)

    def get_initial_tip(self, strategy: str, exp_profit_sol: float) -> int:
        """Determine the starting tip based on strategy and expected profit.

        Args:
            strategy: Strategy name (e.g. "LST_EPOCH")
            exp_profit_sol: Expected profit in SOL

        Returns:
            Tip amount in lamports
        """
        pct = 0.30 if strategy in ["LST_EPOCH", "SANCTUM_ROUTER"] else 0.45
        calculated_tip = int(exp_profit_sol * pct * 1_000_000_000)

        base = self.base_tips.get(strategy, self.base_tips["DEFAULT"])
        return max(base, min(calculated_tip, self.max_tip))


class ExecutionGuard:
    """Circuit breaker that pauses execution after consecutive failures.

    Prevents capital drain by stopping trading when the network/strategy
    is failing repeatedly (e.g. Jito issues, slippage cascades).
    """

    BACKOFF_STAGES = [60, 300, 1800]  # 60s → 300s → 1800s → permanent halt

    def __init__(self):
        self.fail_streak = 0
        self.pause_until = 0

    def record_success(self):
        """Reset the fail streak on successful execution."""
        self.fail_streak = 0

    def record_failure(self):
        """Increment fail streak and trigger exponential backoff."""
        self.fail_streak += 1
        if self.fail_streak >= 4:
            stage = min(self.fail_streak - 1, len(self.BACKOFF_STAGES))
            if stage >= len(self.BACKOFF_STAGES):
                self.pause_until = float('inf')
                logger.critical(
                    "🚨 CIRCUIT BREAKER: permanent halt after repeated failures. Manual restart required."
                )
            else:
                backoff = self.BACKOFF_STAGES[stage - 1] if stage > 0 else self.BACKOFF_STAGES[0]
                self.pause_until = time.time() + backoff
                logger.warning(
                    f"🚨 CIRCUIT BREAKER: {self.fail_streak} failures in a row. "
                    f"Pausing execution for {backoff} seconds."
                )

    def can_execute(self) -> bool:
        """Check if execution is allowed.

        Returns:
            True if we can execute, False if circuit breaker is active.
        """
        if self.pause_until == float('inf'):
            return False
        return time.time() >= self.pause_until
