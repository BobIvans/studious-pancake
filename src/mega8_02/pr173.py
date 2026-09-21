"""PR-173 / SOLVER-05: robust quote/capacity uncertainty."""

from __future__ import annotations
from typing import Sequence
from .core import Mega802Error, empirical_interval, require_nonnegative_int


def estimate_quote_uncertainty(samples: Sequence[int]) -> tuple[int, int]:
    return empirical_interval(samples)


def build_capacity_confidence_envelope(samples: Sequence[int]) -> tuple[int, int]:
    return empirical_interval(samples, margin_ppm=150_000)


def optimize_worst_case_net(
    *, gross_out_low: int, input_amount: int, fixed_cost: int
) -> int:
    for value, field in (
        (gross_out_low, "gross_out_low"),
        (input_amount, "input_amount"),
        (fixed_cost, "fixed_cost"),
    ):
        require_nonnegative_int(value, field)
    return gross_out_low - input_amount - fixed_cost


def reject_fragile_opportunity(worst_case_net: int, *, minimum_net: int = 1) -> bool:
    if worst_case_net < minimum_net:
        raise Mega802Error("FRAGILE_OPPORTUNITY")
    return True
