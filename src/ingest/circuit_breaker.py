import logging
from datetime import datetime
from typing import Tuple, Optional

logger = logging.getLogger("CircuitBreaker")


class CapitalProtection:
    def __init__(self, starting_balance_sol: float):
        self.starting_balance = starting_balance_sol
        self.daily_pnl_sol = 0.0
        self.weekly_pnl_sol = 0.0
        self.consecutive_losses = 0
        self.consecutive_failed_attempts = 0
        self.last_daily_reset = datetime.utcnow()
        self.last_weekly_reset = datetime.utcnow()

    @property
    def daily_limit_sol(self) -> float:
        return min(0.005, self.starting_balance * 0.33)  # survival phase

    @property
    def weekly_limit_sol(self) -> float:
        return max(0.003, self.starting_balance * 0.20)  # 20%

    @property
    def max_drawdown_sol(self) -> float:
        return self.starting_balance * 0.33  # 33%

    def record_trade(self, pnl_sol: float):
        """Record the realized PnL of a completed trade."""
        self.daily_pnl_sol += pnl_sol
        self.weekly_pnl_sol += pnl_sol

        if pnl_sol < 0:
            self.consecutive_losses += 1
            logger.warning(f"📉 Trade recorded as loss ({pnl_sol:.6f} SOL). Consecutive losses: {self.consecutive_losses}")
        else:
            self.consecutive_losses = 0

    def record_failed_attempt(self, cost_sol: float):
        """Record a failed trading attempt (e.g. failed simulation, Jito drop)."""
        self.consecutive_failed_attempts += 1
        self.daily_pnl_sol -= cost_sol
        self.weekly_pnl_sol -= cost_sol
        logger.warning(
            f"🚫 Failed attempt recorded (cost={cost_sol:.6f} SOL). "
            f"Consecutive failed attempts: {self.consecutive_failed_attempts}"
        )

    def should_stop(self) -> Tuple[bool, str]:
        """Check time resets and verify all risk limits."""
        now = datetime.utcnow()

        if self.consecutive_failed_attempts >= 5:
            return True, f"5 consecutive failed attempts: trading halted"

        if (now - self.last_daily_reset).total_seconds() > 86400:
            self.daily_pnl_sol = 0.0
            self.last_daily_reset = now

        if (now - self.last_weekly_reset).total_seconds() > 604800:
            self.weekly_pnl_sol = 0.0
            self.last_weekly_reset = now

        # Check limits (Note: pnl is negative for losses)
        if self.daily_pnl_sol < -self.daily_limit_sol:
            return True, f"Daily loss limit reached: {self.daily_pnl_sol:.6f} SOL < -{self.daily_limit_sol:.6f} SOL"

        if self.weekly_pnl_sol < -self.weekly_limit_sol:
            return True, f"Weekly loss limit reached: {self.weekly_pnl_sol:.6f} SOL < -{self.weekly_limit_sol:.6f} SOL"

        if self.consecutive_losses >= 3:
            return True, f"Consecutive losses limit reached: {self.consecutive_losses} losses in a row"

        if self.weekly_pnl_sol < -self.max_drawdown_sol:
            return True, f"Max drawdown reached: {self.weekly_pnl_sol:.6f} SOL < -{self.max_drawdown_sol:.6f} SOL"

        return False, ""
