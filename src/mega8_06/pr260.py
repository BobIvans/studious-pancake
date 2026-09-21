"""PR-260 / TAIL-01: correlated stress and CVaR-style budgets."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega806Error, cvar_upper, require_int, require_nonnegative_int


def build_correlated_stress_scenarios(
    exposures: Mapping[str, int],
    scenarios: Sequence[Mapping[str, int]],
) -> tuple[int, ...]:
    if not exposures or not scenarios:
        raise Mega806Error("exposures and scenarios are required")
    losses = []
    for scenario in scenarios:
        loss = 0
        for key, exposure in exposures.items():
            exposure = require_nonnegative_int(exposure, f"exposure:{key}")
            shock_ppm = require_int(scenario.get(key, 0), f"shock:{key}")
            if shock_ppm < 0:
                loss += exposure * min(1_000_000, -shock_ppm) // 1_000_000
        losses.append(loss)
    return tuple(losses)


def compute_tail_loss_distribution(losses: Sequence[int]) -> tuple[int, ...]:
    return tuple(sorted(require_nonnegative_int(x, "loss") for x in losses))


def estimate_cvar_budget(losses: Sequence[int], *, tail_ppm: int = 50_000) -> int:
    return cvar_upper(losses, tail_ppm)


def gate_tail_exposure(
    losses: Sequence[int], *, max_cvar: int, tail_ppm: int = 50_000
) -> bool:
    max_cvar = require_nonnegative_int(max_cvar, "max_cvar")
    observed = estimate_cvar_budget(losses, tail_ppm=tail_ppm)
    if observed > max_cvar:
        raise Mega806Error("TAIL_BUDGET_EXCEEDED")
    return True
