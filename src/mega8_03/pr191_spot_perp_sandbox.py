"""PR-191 / PERP-02 — non-atomic spot/perp hedge sandbox.

Plans are research artifacts only and cannot inherit atomic/live permissions.
"""

from __future__ import annotations

from typing import Any, Mapping

from .common import EvidenceEnvelope, OfflineDecision, decision, integer, stable_hash


def build_spot_perp_hedge_plan(
    *,
    spot_amount_atomic: int,
    perp_hedge_amount_atomic: int,
    max_holding_ns: int,
    envelope: EvidenceEnvelope,
) -> dict[str, Any]:
    spot = integer(spot_amount_atomic, "spot_amount_atomic", minimum=1)
    hedge = integer(perp_hedge_amount_atomic, "perp_hedge_amount_atomic", minimum=1)
    holding = integer(max_holding_ns, "max_holding_ns", minimum=1)
    payload = {
        "spot_amount_atomic": spot,
        "perp_hedge_amount_atomic": hedge,
        "max_holding_ns": holding,
        "state_generation": envelope.state_generation,
        "atomic_profile": False,
        "execution_authority": False,
    }
    return payload | {"plan_sha256": stable_hash("mega8-03/spot-perp-plan/v1", payload)}


def reserve_margin_and_inventory(
    plan: Mapping[str, Any],
    *,
    available_margin_atomic: int,
    available_inventory_atomic: int,
    required_margin_atomic: int,
) -> dict[str, Any]:
    required = integer(required_margin_atomic, "required_margin_atomic", minimum=1)
    margin = integer(available_margin_atomic, "available_margin_atomic", minimum=0)
    inventory = integer(
        available_inventory_atomic, "available_inventory_atomic", minimum=0
    )
    spot = integer(plan["spot_amount_atomic"], "spot_amount_atomic", minimum=1)
    return {
        "margin_reserved_atomic": required if margin >= required else 0,
        "inventory_reserved_atomic": spot if inventory >= spot else 0,
        "sufficient": margin >= required and inventory >= spot,
        "reservation_is_internal_only": True,
    }


def simulate_partial_fill_risk(
    *,
    spot_filled_atomic: int,
    perp_filled_atomic: int,
    reference_price_atomic: int,
    stress_move_ppm: int,
) -> dict[str, int]:
    spot = integer(spot_filled_atomic, "spot_filled_atomic", minimum=0)
    perp = integer(perp_filled_atomic, "perp_filled_atomic", minimum=0)
    price = integer(reference_price_atomic, "reference_price_atomic", minimum=1)
    stress = integer(stress_move_ppm, "stress_move_ppm", minimum=0)
    unhedged = abs(spot - perp)
    return {
        "unhedged_atomic": unhedged,
        "stress_loss_atomic": unhedged * price * stress // 1_000_000,
    }


def reconcile_hedged_position(
    *,
    envelope: EvidenceEnvelope,
    reservation: Mapping[str, Any],
    partial_fill_risk: Mapping[str, Any],
    finalized: bool,
) -> OfflineDecision:
    reasons: list[str] = []
    if reservation.get("sufficient") is not True:
        reasons.append("MARGIN_OR_INVENTORY_INSUFFICIENT")
    if finalized is not True:
        reasons.append("HEDGE_OUTCOME_NOT_FINALIZED")
    if (
        integer(partial_fill_risk.get("unhedged_atomic"), "unhedged_atomic", minimum=0)
        > 0
    ):
        reasons.append("PARTIAL_FILL_EXPOSURE_REMAINS")
    payload = {
        "reservation": dict(reservation),
        "partial_fill_risk": dict(partial_fill_risk),
        "finalized": bool(finalized),
        "atomic_profile": False,
    }
    return decision(
        "PR-191",
        envelope=envelope,
        payload=payload,
        reasons=reasons,
        research_only=True,
    )


__all__ = [
    "build_spot_perp_hedge_plan",
    "reconcile_hedged_position",
    "reserve_margin_and_inventory",
    "simulate_partial_fill_risk",
]
