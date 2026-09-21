"""PR-318 / NF-971..975: exact executable option payoff packages."""

from __future__ import annotations

from itertools import product
from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_int, require_nonnegative, require_positive, stable_hash


def normalize_option_settlement_family(
    instruments: Sequence[Mapping[str, Any]],
) -> ContractResult:
    if not instruments:
        raise UltimateMegaError("SPECS_STALE")
    fields = ("option_style", "expiry", "settlement_asset", "settlement_index", "exercise_style")
    first = tuple(instruments[0].get(field) for field in fields)
    for instrument in instruments[1:]:
        if tuple(instrument.get(field) for field in fields) != first:
            raise UltimateMegaError("INCOMPATIBLE_SETTLEMENT")
    return record(
        "normalize_option_settlement_family",
        {"family_key": first, "instrument_ids": tuple(str(x.get("instrument_id")) for x in instruments)},
    )


def construct_executable_payoff_matrix(
    *,
    strikes: Sequence[int],
    scenarios: Sequence[int],
    bid_ask: Mapping[int, tuple[int, int]],
    lot_step: int,
) -> ContractResult:
    step = require_positive(lot_step, "lot_step")
    if not strikes or not scenarios:
        raise UltimateMegaError("MISSING_TAIL_BOUND")
    rows = {}
    for strike in strikes:
        strike = require_nonnegative(strike, "strike")
        if strike not in bid_ask:
            raise UltimateMegaError("DEPTH_UNAVAILABLE")
        bid, ask = bid_ask[strike]
        if bid < 0 or ask < bid:
            raise UltimateMegaError("DEPTH_UNAVAILABLE")
        rows[strike] = {
            "bid": bid,
            "ask": ask,
            "call_payoffs": tuple(max(0, int(spot) - strike) for spot in scenarios),
            "put_payoffs": tuple(max(0, strike - int(spot)) for spot in scenarios),
        }
    return record("construct_executable_payoff_matrix", {"lot_step": step, "scenarios": tuple(scenarios), "rows": rows})


def solve_integer_option_package(
    candidates: Sequence[Mapping[str, Any]],
    *,
    max_lots: int,
    search_budget: int,
) -> ContractResult:
    max_lots = require_positive(max_lots, "max_lots")
    search_budget = require_positive(search_budget, "search_budget")
    if len(candidates) * (max_lots + 1) > search_budget:
        return record(
            "solve_integer_option_package",
            {"solver_status": "UNKNOWN", "optimality_claim": False},
            status="UNKNOWN",
            blockers=("SOLVER_TIMEOUT",),
        )
    best = None
    for candidate in candidates:
        cost = require_int(int(candidate.get("cost_per_lot", 0)), "cost_per_lot")
        min_payoff = require_int(int(candidate.get("min_payoff_per_lot", 0)), "min_payoff_per_lot")
        for lots in range(1, max_lots + 1):
            net = (min_payoff - cost) * lots
            row = (net, lots, str(candidate.get("id", "")))
            if best is None or row > best:
                best = row
    if best is None:
        raise UltimateMegaError("UNBOUNDED_MODEL")
    return record(
        "solve_integer_option_package",
        {"solver_status": "FEASIBLE", "min_net": best[0], "lots": best[1], "candidate_id": best[2], "optimality_claim": True},
    )


def recheck_option_payoff_certificate(
    *,
    scenario_payoffs: Sequence[int],
    costs: int,
    required_margin: int,
    collateral: int,
) -> ContractResult:
    if not scenario_payoffs:
        raise UltimateMegaError("MISSING_TAIL_BOUND")
    cost = require_nonnegative(costs, "costs")
    margin = require_nonnegative(required_margin, "required_margin")
    collateral = require_nonnegative(collateral, "collateral")
    if collateral < margin:
        raise UltimateMegaError("NUMERIC_TOLERANCE_FALSE_PROFIT")
    exact = tuple(require_int(x, "scenario_payoff") - cost for x in scenario_payoffs)
    if min(exact) < 0:
        raise UltimateMegaError("NUMERIC_TOLERANCE_FALSE_PROFIT")
    return record("recheck_option_payoff_certificate", {"scenario_net_payoffs": exact, "minimum_net": min(exact), "exact_integer_recheck": True})


def simulate_option_leg_fill_failures(
    *,
    leg_sizes: Mapping[str, int],
    filled_sizes: Mapping[str, int],
    early_assignment_loss: int = 0,
    margin_call_loss: int = 0,
) -> ContractResult:
    exposure = {}
    for leg, size in leg_sizes.items():
        expected = require_int(size, f"size_{leg}")
        filled = require_int(filled_sizes.get(leg, 0), f"filled_{leg}")
        exposure[leg] = expected - filled
    losses = require_nonnegative(early_assignment_loss, "early_assignment_loss") + require_nonnegative(margin_call_loss, "margin_call_loss")
    unhedged = any(v != 0 for v in exposure.values())
    return record(
        "simulate_option_leg_fill_failures",
        {"unhedged_exposure": exposure, "stress_loss": losses, "atomic": False},
        status="INCOMPLETE" if unhedged else "OK",
        blockers=("UNHEDGED_LEG_EXPOSURE",) if unhedged else (),
    )
