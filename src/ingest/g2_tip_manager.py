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
            "XSTOCKS_LAG": 25000,
            "GRADUATION": 35000,
            "DEFAULT": 15000,
        }
        self.max_tip = 150000  # Maximum 0.00015 SOL (capital protection!)
        self.escalation = 1.5
        self.history = defaultdict(list)

    def get_initial_tip(self, strategy: str, exp_profit_sol: float) -> int:
        """Determine the starting tip based on strategy and expected profit.

        Args:
            strategy: Strategy name (e.g. "LST_EPOCH", "XSTOCKS_LAG")
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

    def __init__(self):
        self.fail_streak = 0
        self.pause_until = 0

    def record_success(self):
        """Reset the fail streak on successful execution."""
        self.fail_streak = 0

    def record_failure(self):
        """Increment fail streak and trigger pause if >= 4 consecutive failures."""
        self.fail_streak += 1
        if self.fail_streak >= 4:
            self.pause_until = time.time() + 120  # 2 minute pause
            self.fail_streak = 0
            logger.warning(
                "🚨 CIRCUIT BREAKER: 4 failures in a row. "
                "Pausing execution for 120 seconds."
            )

    def can_execute(self) -> bool:
        """Check if execution is allowed.

        Returns:
            True if we can execute, False if circuit breaker is active.
        """
        return time.time() >= self.pause_until
