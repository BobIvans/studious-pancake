"""PR-255 / MICRO-01: adverse selection, markouts, and fill quality."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega806Error, mean_int, require_int, require_ppm


def compute_markout_curve(
    fill_price: int, horizon_prices: Mapping[int, int], *, side: str
) -> tuple[tuple[int, int], ...]:
    fill_price = require_int(fill_price, "fill_price")
    if fill_price <= 0 or side not in {"buy", "sell"}:
        raise Mega806Error("invalid fill price or side")
    sign = 1 if side == "buy" else -1
    rows = []
    for horizon, price in sorted(horizon_prices.items()):
        if horizon <= 0 or price <= 0:
            raise Mega806Error("invalid horizon or price")
        markout_ppm = sign * (price - fill_price) * 1_000_000 // fill_price
        rows.append((horizon, markout_ppm))
    if not rows:
        raise Mega806Error("horizon prices are required")
    return tuple(rows)


def estimate_adverse_selection(markouts_ppm: Sequence[int]) -> int:
    if not markouts_ppm:
        raise Mega806Error("markouts are required")
    return max(0, -mean_int([require_int(x, "markout") for x in markouts_ppm]))


def predict_fill_quality(
    markouts_ppm: Sequence[int], *, toxicity_ppm: int, uncertainty_ppm: int = 0
) -> int:
    toxicity_ppm = require_ppm(toxicity_ppm, "toxicity_ppm")
    uncertainty_ppm = require_ppm(uncertainty_ppm, "uncertainty_ppm")
    adverse = estimate_adverse_selection(markouts_ppm)
    return max(0, 1_000_000 - min(1_000_000, adverse + toxicity_ppm + uncertainty_ppm))


def gate_toxic_fill(
    markouts_ppm: Sequence[int], *, max_adverse_ppm: int, max_toxicity_ppm: int
) -> bool:
    max_adverse_ppm = require_ppm(max_adverse_ppm, "max_adverse_ppm")
    max_toxicity_ppm = require_ppm(max_toxicity_ppm, "max_toxicity_ppm")
    adverse = estimate_adverse_selection(markouts_ppm)
    if adverse > max_adverse_ppm:
        raise Mega806Error("ADVERSE_SELECTION_LIMIT")
    if any(abs(require_int(x, "markout")) > max_toxicity_ppm for x in markouts_ppm):
        raise Mega806Error("TOXIC_MARKOUT")
    return True
