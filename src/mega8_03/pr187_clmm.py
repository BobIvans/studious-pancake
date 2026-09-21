"""PR-187 / CLMM-01 — deterministic CLMM/DLMM range residual research."""

from __future__ import annotations

from typing import Any, Mapping

from .common import EvidenceEnvelope, OfflineDecision, PPM, decision, integer


def measure_clmm_range_pressure(
    *,
    current_index: int,
    lower_index: int,
    upper_index: int,
    active_liquidity_atomic: int,
) -> dict[str, int]:
    current = integer(current_index, "current_index")
    lower = integer(lower_index, "lower_index")
    upper = integer(upper_index, "upper_index")
    liquidity = integer(active_liquidity_atomic, "active_liquidity_atomic", minimum=0)
    if lower >= upper or current < lower or current > upper:
        raise ValueError("current index must lie inside a non-empty range")
    width = upper - lower
    distance = min(current - lower, upper - current)
    pressure = PPM - min(PPM, (2 * distance * PPM) // width)
    return {
        "range_width": width,
        "boundary_distance": distance,
        "pressure_ppm": pressure,
        "active_liquidity_atomic": liquidity,
    }


def detect_rebalance_residual(
    *,
    reference_price_ppm: int,
    post_rebalance_price_ppm: int,
    minimum_dislocation_ppm: int,
) -> dict[str, int | bool]:
    reference = integer(reference_price_ppm, "reference_price_ppm", minimum=1)
    observed = integer(post_rebalance_price_ppm, "post_rebalance_price_ppm", minimum=1)
    minimum = integer(minimum_dislocation_ppm, "minimum_dislocation_ppm", minimum=0)
    signed = observed - reference
    magnitude = abs(signed) * PPM // reference
    return {
        "signed_price_delta": signed,
        "dislocation_ppm": magnitude,
        "actionable_offline": magnitude >= minimum,
    }


def estimate_fee_growth_dislocation(
    *,
    observed_fee_growth_atomic: int,
    expected_fee_growth_atomic: int,
    position_liquidity_atomic: int,
) -> dict[str, int]:
    observed = integer(
        observed_fee_growth_atomic, "observed_fee_growth_atomic", minimum=0
    )
    expected = integer(
        expected_fee_growth_atomic, "expected_fee_growth_atomic", minimum=0
    )
    liquidity = integer(
        position_liquidity_atomic, "position_liquidity_atomic", minimum=1
    )
    delta = observed - expected
    return {
        "fee_growth_delta_atomic": delta,
        "fee_growth_delta_per_liquidity_ppm": delta * PPM // liquidity,
    }


def emit_clmm_position_candidate(
    *,
    envelope: EvidenceEnvelope,
    range_pressure: Mapping[str, Any],
    residual: Mapping[str, Any],
    fee_growth: Mapping[str, Any],
    minimum_net_atomic: int,
    conservative_net_atomic: int,
) -> OfflineDecision:
    reasons: list[str] = []
    net = integer(conservative_net_atomic, "conservative_net_atomic")
    minimum = integer(minimum_net_atomic, "minimum_net_atomic")
    if residual.get("actionable_offline") is not True:
        reasons.append("CLMM_RESIDUAL_BELOW_THRESHOLD")
    if net <= minimum:
        reasons.append("CLMM_NET_BELOW_THRESHOLD")
    payload = {
        "range_pressure": dict(range_pressure),
        "residual": dict(residual),
        "fee_growth": dict(fee_growth),
        "conservative_net_atomic": net,
    }
    return decision(
        "PR-187",
        envelope=envelope,
        payload=payload,
        reasons=reasons,
        research_only=True,
    )


__all__ = [
    "detect_rebalance_residual",
    "emit_clmm_position_candidate",
    "estimate_fee_growth_dislocation",
    "measure_clmm_range_pressure",
]
