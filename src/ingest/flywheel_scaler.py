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

from src.ingest.shared_state import ATA_RENT_SOL_SPL, ATA_RENT_SOL_TOKEN2022, pair_reputation

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

# Strict risk parameters engineered for the current 0.015 SOL survival phase.
MICRO_BALANCE_SOL = 0.015
GAS_RESERVE_SOL = 0.005
MANEUVER_BUDGET_SOL = MICRO_BALANCE_SOL - GAS_RESERVE_SOL
# Phase 9: unified constants from shared_state (single source of truth)
ATA_RENT_SOL = ATA_RENT_SOL_TOKEN2022  # Conservative default: Token-2022 rent (LSTs use T22)

SCALING_GRID = [
    # Tier 1: Survival Phase (0.0 - 0.03 SOL) - SOL & Stables only, tightest parameters
    ScalingTier(0.0, 0.03, 1, MANEUVER_BUDGET_SOL, 0.50, 0.00005, ["SS", "SL"], 15),
    # Tier 1.5: Growth Phase (0.03 - 0.05 SOL) - Smooth upgrade jump
    ScalingTier(0.03, 0.05, 1, 0.10, 0.45, 0.00007, ["SS", "SL"], 18),
    # Tier 2: Momentum Phase (0.05 - 0.20 SOL) - Enable major pairs
    ScalingTier(0.05, 0.20, 2, 0.50, 0.40, 0.0010, ["SS", "SL", "SM"], 25),
    # Tier 3: Growth Phase (0.20 - 1.00 SOL) - Introduce wrappers & stable yield ladders
    ScalingTier(0.20, 1.00, 3, 1.00, 0.30, 0.0020, ["SS", "SL", "SM", "BT", "ET", "YL"], 35),
    # Tier 4: Professional Phase (1.00 - 10.00 SOL+) - Full strategy suite activated
    ScalingTier(1.00, 100.0, 5, 2.50, 0.25, 0.0050, ["all"], 50),
]


class DynamicThresholds:
    """Balance-aware thresholds for survival-mode trading."""

    def __init__(self, wallet_balance_sol: float):
        self.balance = wallet_balance_sol

    @property
    def min_profit_sol(self) -> float:
        if self.balance < 0.020:
            return 0.0001
        elif self.balance < 0.100:
            return 0.0002
        elif self.balance < 1.000:
            return 0.0003
        return 0.0005

    @property
    def max_borrow_sol(self) -> float:
        balance = self.balance
        if balance < 0.03:
            return min(0.10, balance * 3)
        elif balance < 0.05:
            return min(0.15, balance * 3)
        elif balance < 0.20:
            return min(0.50, balance * 5)
        elif balance < 1.00:
            return min(1.00, balance * 10)
        else:
            return min(2.50, balance * 10)

    @property
    def max_new_atas_per_trade(self) -> int:
        # Survival mode: allow up to 2 new ATAs only if it leaves a ≥0.005 SOL buffer
        # after reserving rent for both accounts (0.00204 SOL each).
        if self.balance < 0.020:
            return 2 if (self.balance - (2 * 0.00204)) >= 0.005 else 0
        if self.balance < 0.100:
            return 1
        if self.balance < 1.000:
            return 2
        return 4

    @property
    def hard_floor_sol(self) -> float:
        # Phase 10: exact minimum gas reserve — no longer scales with balance.
        # 0.005 SOL is the precise gas floor for one flashloan + Jito tip.
        return 0.0050


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
        error_keywords: tuple = ("slippage", "insufficient", "liquidity", "simulation failed", "blockhash"),
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
        self.rent_per_ata = ATA_RENT_SOL
        self.min_gas_reserve = 0.005
        self.reputation = pair_reputation
        # Fix 49: Hysteresis — track previous tier to prevent flapping at boundaries
        self._current_tier_index: int = 0
        self._hysteresis_buffer: float = 0.95  # 5% buffer: need 5% below threshold to downgrade

    def get_tier(self, current_balance: float) -> ScalingTier:
        """Finds the active scaling tier based on current balance.

        Fix 49: Hysteresis — prevents flapping when balance oscillates near boundaries.
        Upgrades are instant (balance >= min_balance of next tier).
        Downgrades need balance < min_balance * 0.95 (5% buffer).
        """
        target_index = self._current_tier_index

        for i, tier in enumerate(SCALING_GRID):
            if tier.min_balance <= current_balance < tier.max_balance:
                target_index = i
                break
            # Handle edge: balance >= max_balance of all tiers
            if current_balance >= SCALING_GRID[-1].min_balance:
                target_index = len(SCALING_GRID) - 1
                break

        # Apply hysteresis on downgrade
        if target_index < self._current_tier_index:
            current_tier = SCALING_GRID[self._current_tier_index]
            # Only downgrade if balance is 5% below the next tier's threshold
            if current_balance >= current_tier.min_balance * self._hysteresis_buffer:
                target_index = self._current_tier_index  # Stay in current tier

        self._current_tier_index = target_index
        return SCALING_GRID[target_index]

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
        dynamic = DynamicThresholds(current_balance_sol)
        return {
            "max_concurrent_trades": tier.max_concurrent_trades,
            "jito_tip_pct": tier.jito_tip_percent,
            "min_net_profit_sol": dynamic.min_profit_sol,
            "max_borrow_sol": dynamic.max_borrow_sol,
            "max_new_atas_per_trade": dynamic.max_new_atas_per_trade,
            "hard_floor_sol": dynamic.hard_floor_sol,
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
