import logging
from datetime import datetime
from typing import Tuple, Optional

logger = logging.getLogger("CircuitBreaker")


class CapitalProtection:
    def __init__(self, starting_balance_sol: float):
        self.starting_balance = starting_balance_sol
        self.realized_pnl_sol = 0.0
        self.weekly_realized_pnl_sol = 0.0
        self.failed_attempt_costs_sol = 0.0
        self.consecutive_losses = 0
        self.consecutive_failed_attempts = 0
        self.last_daily_reset = datetime.utcnow()
        self.last_weekly_reset = datetime.utcnow()

    @property
    def daily_realized_loss_limit_sol(self) -> float:
        return min(0.005, self.starting_balance * 0.33)

    @property
    def weekly_realized_loss_limit_sol(self) -> float:
        return max(0.003, self.starting_balance * 0.20)

    @property
    def max_daily_failed_cost_sol(self) -> float:
        return min(0.002, self.starting_balance * 0.10)

    @property
    def max_drawdown_sol(self) -> float:
        return self.starting_balance * 0.33

    def record_trade(self, pnl_sol: float):
        """Record the realized PnL of a completed trade."""
        self.realized_pnl_sol += pnl_sol
        self.weekly_realized_pnl_sol += pnl_sol

        if pnl_sol < 0:
            self.consecutive_losses += 1
            logger.warning(f"📉 Trade recorded as loss ({pnl_sol:.6f} SOL). Consecutive losses: {self.consecutive_losses}")
        else:
            self.consecutive_losses = 0

    def record_failed_attempt(self, cost_sol: float):
        """Record a failed trading attempt cost (e.g. failed simulation, Jito drop)."""
        self.failed_attempt_costs_sol += cost_sol
        self.consecutive_failed_attempts += 1
        logger.warning(
            f"🚫 Failed attempt recorded (cost={cost_sol:.6f} SOL). "
            f"Consecutive failed attempts: {self.consecutive_failed_attempts}"
        )

    def should_stop(self) -> Tuple[bool, str]:
        """Check all risk limits without mutating state."""
        now = datetime.utcnow()

        if self.consecutive_failed_attempts >= 5:
            return True, f"5 consecutive failed attempts: trading halted"

        if self.realized_pnl_sol < -self.daily_realized_loss_limit_sol:
            return True, f"Daily realized loss limit reached: {self.realized_pnl_sol:.6f} SOL < -{self.daily_realized_loss_limit_sol:.6f} SOL"

        if self.weekly_realized_pnl_sol < -self.weekly_realized_loss_limit_sol:
            return True, f"Weekly realized loss limit reached: {self.weekly_realized_pnl_sol:.6f} SOL < -{self.weekly_realized_loss_limit_sol:.6f} SOL"

        if self.failed_attempt_costs_sol > self.max_daily_failed_cost_sol:
            return True, f"Daily failed attempt cost limit reached: {self.failed_attempt_costs_sol:.6f} SOL > {self.max_daily_failed_cost_sol:.6f} SOL"

        if self.consecutive_losses >= 3:
            return True, f"Consecutive losses limit reached: {self.consecutive_losses} losses in a row"

        if self.weekly_realized_pnl_sol < -self.max_drawdown_sol:
            return True, f"Max drawdown reached: {self.weekly_realized_pnl_sol:.6f} SOL < -{self.max_drawdown_sol:.6f} SOL"

        return False, ""

    def reset_if_needed(self):
        """Reset daily/weekly counters if the time window has elapsed."""
        now = datetime.utcnow()
        if (now - self.last_daily_reset).total_seconds() > 86400:
            self.realized_pnl_sol = 0.0
            self.failed_attempt_costs_sol = 0.0
            self.last_daily_reset = now
        if (now - self.last_weekly_reset).total_seconds() > 604800:
            self.weekly_realized_pnl_sol = 0.0
            self.last_weekly_reset = now
