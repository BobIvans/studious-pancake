"""
FlywheelScaler — Capital-Aware Trading Parameter Tuning + Reputation Circuit Breaker.

Golden rule for scaling (0.017 → 1.0 SOL):
  If any specific pair produces 3 consecutive 'Slippage Exceeded' errors in a row,
  that pair is sent to the "cool-down" bin for 10 minutes.
  This protects the micro-balance from competitive blind-firing in already-drained pools.
"""

import time
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("FlywheelScaler")

@dataclass
class ScalingTier:
    min_balance: float
    max_balance: float
    max_concurrent_trades: int
    flash_loan_size: float
    jito_tip_percent: float
    min_profit_sol: float
    allowed_strategies: List[str]
    max_slippage_bps: int

# Strict risk parameters engineered to scale safely from 0.017 SOL upwards
SCALING_GRID = [
    # Tier 1: Survival Phase (0.017 - 0.05 SOL) - SOL & Stables only, tightest parameters
    ScalingTier(0.0, 0.05, 1, 0.25, 0.50, 0.0005, ["SS", "SL"], 15),
    # Tier 2: Momentum Phase (0.05 - 0.20 SOL) - Enable major pairs
    ScalingTier(0.05, 0.20, 2, 0.50, 0.40, 0.0010, ["SS", "SL", "SM"], 25),
    # Tier 3: Growth Phase (0.20 - 1.00 SOL) - Introduce wrappers & stable yield ladders
    ScalingTier(0.20, 1.00, 3, 1.00, 0.30, 0.0020, ["SS", "SL", "SM", "BT", "ET", "YL"], 35),
    # Tier 4: Professional Phase (1.00 - 10.00 SOL+) - Full strategy suite activated
    ScalingTier(1.00, 100.0, 5, 2.50, 0.25, 0.0050, ["all"], 50),
]


class PairReputationCircuitBreaker:
    """Per-pair failure tracker with configurable cooldown.

    After ``limit`` consecutive errors matching any of ``error_keywords``,
    the pair is added to a cooldown set for ``cooldown_seconds``.
    A single successful trade resets the counter regardless of where the failure was.
    """

    def __init__(
        self,
        limit: int = 3,
        cooldown_seconds: int = 600,
        error_keywords: tuple = ("slippage", "exceeded"),
    ):
        self.limit = limit
        self.cooldown_seconds = cooldown_seconds
        self.error_keywords = error_keywords

        # pair_key -> {"failures": int, "banned_until": float}
        self._state: Dict[str, Dict[str, Any]] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    def record_failure(self, pair_key: str, error_msg: str = "") -> None:
        """Increment the failure counter for *pair_key* and apply cooldown if limit hit."""
        now = time.time()
        entry = self._state.get(pair_key)
        error_lower = error_msg.lower()
        is_relevant = any(kw in error_lower for kw in self.error_keywords)

        if not is_relevant:
            # Non-tracked error — reset counter but don't ban
            self.reset(pair_key)
            return

        if entry is None or entry.get("banned_until", 0) < now:
            # Cooldown expired or first failure — reset and start fresh
            self._state[pair_key] = {
                "failures": 1,
                "banned_until": 0.0,
                "last_error": error_msg[:120],
            }
            logger.debug(f"📊 Reputation [{pair_key}]: 1st tracked failure noted")
            return

        entry["failures"] += 1
        entry["last_error"] = error_msg[:120]

        if entry["failures"] >= self.limit:
            entry["banned_until"] = now + self.cooldown_seconds
            logger.critical(
                f"🚨 REPUTATION CIRCUIT BREAKER: Pair {pair_key} banned for "
                f"{self.cooldown_seconds}s ({entry['failures']} consecutive "
                f"{'/'.join(self.error_keywords)} fails)"
            )
        else:
            remaining = self.limit - entry["failures"]
            logger.warning(
                f"⚠️ Reputation [{pair_key}]: {entry['failures']}/{self.limit} "
                f"failures ({remaining} more to cooldown)"
            )

    def record_success(self, pair_key: str) -> None:
        """Reset the failure counter for *pair_key* after a profitable trade."""
        entry = self._state.get(pair_key)
        if entry and entry.get("failures", 0) > 0:
            self.reset(pair_key)
            logger.info(f"✅ Reputation cleared: {pair_key}")

    def is_banned(self, pair_key: str) -> bool:
        """Return True if *pair_key* is currently in cooldown."""
        now = time.time()
        entry = self._state.get(pair_key)
        return bool(entry and entry.get("banned_until", 0) > now)

    def reset(self, pair_key: str) -> None:
        """Remove *pair_key* from the reputation tracker."""
        self._state.pop(pair_key, None)

    def reset_all(self) -> None:
        """Nuclear reset — clear all tracked pairs."""
        self._state.clear()
        logger.info("🔄 Reputation Circuit Breaker: all pairs reset")

    # ── Utility ────────────────────────────────────────────────────────────

    def get_reputation_params(self) -> Dict[str, Any]:
        """Return a summary of the current reputation state for logging/metrics."""
        active, banned = 0, 0
        now = time.time()
        for entry in self._state.values():
            if entry.get("banned_until", 0) > now:
                banned += 1
            elif entry.get("failures", 0) > 0:
                active += 1
        return {
            "tracked_pairs": len(self._state),
            "active_warnings": active,
            "banned_pairs": banned,
            "cooldown_secs": self.cooldown_seconds,
            "failure_limit": self.limit,
        }


class FlywheelScaler:
    """Dynamically adjusts trading parameters based on account balance growth.

    Integrated with ``PairReputationCircuitBreaker`` to automatically check pair
    cooldown status before any trade reaches the hot path.
    """

    def __init__(self, initial_balance: float = 0.017):
        self.initial_balance = initial_balance
        self.rent_per_ata = 0.00204  # SOL rent exemption fee
        self.min_gas_reserve = 0.005  # STRICT_GAS_TANK floor

        # Reputation Circuit Breaker — per-pair slippage cooldown
        self.reputation = PairReputationCircuitBreaker(
            limit=3,
            cooldown_seconds=600,   # 10 minutes
            error_keywords=("slippage",),
        )

    def get_tier(self, current_balance: float) -> ScalingTier:
        """Finds the active scaling tier based on current balance."""
        for tier in SCALING_GRID:
            if tier.min_balance <= current_balance < tier.max_balance:
                return tier
        return SCALING_GRID[-1]

    def pre_calculate_ata_budget(self, virtual_balance: float, jito_tip_sol: float, priority_fee_sol: float) -> int:
        """
        Pre-calculates the maximum number of new ATAs we can afford to open
        without violating our safety gas floor.
        """
        available_room = virtual_balance - self.min_gas_reserve - jito_tip_sol - priority_fee_sol
        if available_room <= 0:
            return 0
        return int(available_room // self.rent_per_ata)

    # ── Backward compatibility wrapper ───────────────────────────────────────

    def get_trading_params(self, current_balance_sol: float) -> dict:
        """Return dynamic trading parameters appropriate for the current balance."""
        tier = self.get_tier(current_balance_sol)
        return {
            "max_concurrent_trades": tier.max_concurrent_trades,
            "jito_tip_pct": tier.jito_tip_percent,
            "min_net_profit_sol": tier.min_profit_sol,
            "allowed_strategies": tier.allowed_strategies,
            "max_slippage_bps": tier.max_slippage_bps,
            "flash_loan_size": tier.flash_loan_size
        }

    # ── Reputation-aware pair gating ─────────────────────────────────────────

    def is_pair_allowed(self, pair_key: str) -> bool:
        """Return True if *pair_key* is not currently in slippage cooldown."""
        return not self.reputation.is_banned(pair_key)

    def record_pair_slippage(self, pair_key: str, error_msg: str = "") -> None:
        """Record a slippage failure for a pair."""
        self.reputation.record_failure(pair_key, error_msg)

    def record_pair_success(self, pair_key: str) -> None:
        """Reset the failure counter for a pair after a successful trade."""
        self.reputation.record_success(pair_key)

    # ── Diagnostic ───────────────────────────────────────────────────────────

    def get_reputation_status(self) -> Dict[str, Any]:
        """Return full reputation-state dict for admin / health-check endpoints."""
        return self.reputation.get_reputation_params()
