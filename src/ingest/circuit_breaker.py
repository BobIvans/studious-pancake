import json
import logging
import os
from datetime import datetime
from typing import Tuple

logger = logging.getLogger("CircuitBreaker")


class CapitalProtection:
    """Persistent capital protection with JSON-backed state across restarts."""

    def __init__(self, starting_balance_sol: float, state_path: str = "circuit_breaker_state.json"):
        self.starting_balance = starting_balance_sol
        self.state_path = state_path
        self.realized_pnl_sol = 0.0
        self.weekly_realized_pnl_sol = 0.0
        self.failed_attempt_costs_sol = 0.0
        self.consecutive_losses = 0
        self.consecutive_failed_attempts = 0
        self.last_daily_reset = datetime.utcnow()
        self.last_weekly_reset = datetime.utcnow()
        self.load_state()

    def save_state(self):
        """Persist loss counters and timestamps to disk."""
        try:
            payload = {
                "realized_pnl_sol": self.realized_pnl_sol,
                "weekly_realized_pnl_sol": self.weekly_realized_pnl_sol,
                "failed_attempt_costs_sol": self.failed_attempt_costs_sol,
                "consecutive_losses": self.consecutive_losses,
                "consecutive_failed_attempts": self.consecutive_failed_attempts,
                "last_daily_reset": self.last_daily_reset.isoformat(),
                "last_weekly_reset": self.last_weekly_reset.isoformat(),
            }
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as exc:
            logger.error(f"Failed to save circuit breaker state: {exc}")

    def load_state(self):
        """Restore persisted loss counters and timestamps if available."""
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.realized_pnl_sol = float(payload.get("realized_pnl_sol", 0.0))
            self.weekly_realized_pnl_sol = float(payload.get("weekly_realized_pnl_sol", 0.0))
            self.failed_attempt_costs_sol = float(payload.get("failed_attempt_costs_sol", 0.0))
            self.consecutive_losses = int(payload.get("consecutive_losses", 0))
            self.consecutive_failed_attempts = int(payload.get("consecutive_failed_attempts", 0))
            self.last_daily_reset = datetime.fromisoformat(
                payload.get("last_daily_reset", datetime.utcnow().isoformat())
            )
            self.last_weekly_reset = datetime.fromisoformat(
                payload.get("last_weekly_reset", datetime.utcnow().isoformat())
            )
            logger.info("Loaded persisted circuit breaker state successfully.")
        except Exception as exc:
            logger.error(f"Failed to load circuit breaker state: {exc}")

    @property
    def daily_realized_loss_limit_sol(self) -> float:
        return min(0.005, self.starting_balance * 0.33)

    @property
    def weekly_realized_loss_limit_sol(self) -> float:
        return max(self.daily_realized_loss_limit_sol * 3, self.starting_balance * 0.20)

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
            logger.warning(
                f"📉 Trade recorded as loss ({pnl_sol:.6f} SOL). Consecutive losses: {self.consecutive_losses}"
            )
        else:
            self.consecutive_losses = 0
        self.save_state()

    def record_failed_attempt(self, cost_sol: float):
        """Record a failed trading attempt cost."""
        self.failed_attempt_costs_sol += cost_sol
        self.consecutive_failed_attempts += 1
        logger.warning(
            f"🚫 Failed attempt recorded (cost={cost_sol:.6f} SOL). "
            f"Consecutive failed attempts: {self.consecutive_failed_attempts}"
        )
        self.save_state()

    def should_stop(self) -> Tuple[bool, str]:
        """Check all risk limits without mutating state."""
        now = datetime.utcnow()

        if self.consecutive_failed_attempts >= 5:
            return True, "5 consecutive failed attempts: trading halted"

        if self.realized_pnl_sol < -self.daily_realized_loss_limit_sol:
            return True, (
                f"Daily realized loss limit reached: {self.realized_pnl_sol:.6f} SOL "
                f"< -{self.daily_realized_loss_limit_sol:.6f} SOL"
            )

        if self.weekly_realized_pnl_sol < -self.weekly_realized_loss_limit_sol:
            return True, (
                f"Weekly realized loss limit reached: {self.weekly_realized_pnl_sol:.6f} SOL "
                f"< -{self.weekly_realized_loss_limit_sol:.6f} SOL"
            )

        if self.failed_attempt_costs_sol > self.max_daily_failed_cost_sol:
            return True, (
                f"Daily failed attempt cost limit reached: {self.failed_attempt_costs_sol:.6f} SOL "
                f"> {self.max_daily_failed_cost_sol:.6f} SOL"
            )

        if self.consecutive_losses >= 3:
            return True, f"Consecutive losses limit reached: {self.consecutive_losses} losses in a row"

        if self.weekly_realized_pnl_sol < -self.max_drawdown_sol:
            return True, (
                f"Max drawdown reached: {self.weekly_realized_pnl_sol:.6f} SOL "
                f"< -{self.max_drawdown_sol:.6f} SOL"
            )

        return False, ""

    def reset_if_needed(self):
        """Reset daily/weekly counters if the time window has elapsed."""
        now = datetime.utcnow()
        mutated = False
        if (now - self.last_daily_reset).total_seconds() > 86400:
            self.realized_pnl_sol = 0.0
            self.failed_attempt_costs_sol = 0.0
            self.last_daily_reset = now
            mutated = True
        if (now - self.last_weekly_reset).total_seconds() > 604800:
            self.weekly_realized_pnl_sol = 0.0
            self.last_weekly_reset = now
            mutated = True
        if mutated:
            self.save_state()
