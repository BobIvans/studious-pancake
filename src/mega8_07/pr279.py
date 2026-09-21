"""PR-279 / CAPITAL-04: evidence-based reinvestment budgets."""

from __future__ import annotations

from typing import Mapping

from .core import CapitalEvidence, Mega807Error, require_nonnegative, stable_hash


def compute_reinvestment_budget(capital: CapitalEvidence, *, now: int) -> int:
    capital.evidence.assert_usable(now=now)
    spendable_balance = max(0, capital.available_balance - capital.protected_reserve)
    return min(capital.finalized_profit, spendable_balance, capital.capacity_limit)


def apply_growth_policy(budget: int, *, current_scale: int, max_growth_ppm: int) -> int:
    amount = require_nonnegative(budget, "budget")
    scale = require_nonnegative(current_scale, "current_scale")
    growth = require_nonnegative(max_growth_ppm, "max_growth_ppm")
    if growth > 1_000_000:
        raise Mega807Error("GROWTH_RATE_EXCEEDS_100_PERCENT")
    growth_cap = scale * growth // 1_000_000
    return min(amount, growth_cap)


def cap_profit_redeployment(
    proposed: int, *, capacity_limit: int, protected_reserve_shortfall: int = 0
) -> int:
    proposal = require_nonnegative(proposed, "proposed")
    capacity = require_nonnegative(capacity_limit, "capacity_limit")
    shortfall = require_nonnegative(
        protected_reserve_shortfall, "protected_reserve_shortfall"
    )
    if shortfall:
        return 0
    return min(proposal, capacity)


def reconcile_growth_cycle(
    *, starting_capital: int, redeployed: int, finalized_delta: int
) -> dict[str, int | str]:
    start = require_nonnegative(starting_capital, "starting_capital")
    used = require_nonnegative(redeployed, "redeployed")
    if isinstance(finalized_delta, bool) or not isinstance(finalized_delta, int):
        raise Mega807Error("FINALIZED_DELTA_MUST_BE_INTEGER")
    ending = start + finalized_delta
    if ending < 0:
        raise Mega807Error("NEGATIVE_FINALIZED_CAPITAL")
    payload = {
        "starting": start,
        "redeployed": used,
        "delta": finalized_delta,
        "ending": ending,
    }
    return {**payload, "cycle_sha256": stable_hash("mega8-07-growth-cycle", payload)}
