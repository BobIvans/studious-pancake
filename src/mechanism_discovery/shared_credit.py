"""PR-355 Aave-v4-style Hub/Spoke shared-credit research specialization."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .evidence_native_core import EvidenceNativeError, record, require_int, require_ppm, require_text


def map_hub_spoke_liquidity(payload: Mapping[str, Any]):
    hub = require_int(payload.get("hub_reserve_atoms"), "hub_reserve_atoms", minimum=0)
    spokes = []
    total_draw = 0
    total_add = 0
    for row in payload.get("spokes", ()):
        spoke_id = require_text(row.get("spoke_id"), "spoke_id")
        draw = require_int(row.get("draw_atoms", 0), "draw_atoms", minimum=0)
        add = require_int(row.get("add_atoms", 0), "add_atoms", minimum=0)
        cap = require_int(row.get("cap_atoms"), "cap_atoms", minimum=0)
        if draw > cap:
            raise EvidenceNativeError("SPOKE_DRAW_EXCEEDS_CAP")
        total_draw += draw
        total_add += add
        spokes.append({"spoke_id": spoke_id, "draw_atoms": draw, "add_atoms": add, "cap_atoms": cap})
    available = hub + total_add - total_draw
    if available < 0:
        raise EvidenceNativeError("HUB_SHARED_LIQUIDITY_INSOLVENT")
    return record(
        "map_hub_spoke_liquidity",
        {
            "hub_reserve_atoms": hub,
            "spokes": tuple(spokes),
            "total_draw_atoms": total_draw,
            "total_add_atoms": total_add,
            "available_atoms": available,
        },
    )


def normalize_spoke_risk_parameters(payload: Mapping[str, Any]):
    ltv = require_ppm(payload.get("ltv_ppm"), "ltv_ppm")
    liquidation = require_ppm(payload.get("liquidation_threshold_ppm"), "liquidation_threshold_ppm")
    premium = require_ppm(payload.get("risk_premium_ppm", 0), "risk_premium_ppm")
    if liquidation < ltv:
        raise EvidenceNativeError("LIQUIDATION_THRESHOLD_BELOW_LTV")
    return record(
        "normalize_spoke_risk_parameters",
        {
            "spoke_id": require_text(payload.get("spoke_id"), "spoke_id"),
            "ltv_ppm": ltv,
            "liquidation_threshold_ppm": liquidation,
            "risk_premium_ppm": premium,
            "health_convention": require_text(payload.get("health_convention"), "health_convention"),
        },
    )


def compute_shared_liquidity_bottleneck(payload: Mapping[str, Any]):
    hub = require_int(payload.get("hub_available_atoms"), "hub_available_atoms", minimum=0)
    competing = require_int(payload.get("competing_claims_atoms", 0), "competing_claims_atoms", minimum=0)
    spoke_cap = require_int(payload.get("spoke_cap_atoms"), "spoke_cap_atoms", minimum=0)
    requested = require_int(payload.get("requested_atoms"), "requested_atoms", minimum=0)
    shared = max(0, hub - competing)
    admissible = min(requested, spoke_cap, shared)
    return record(
        "compute_shared_liquidity_bottleneck",
        {
            "shared_after_competition_atoms": shared,
            "admissible_atoms": admissible,
            "bottlenecked": admissible < requested,
            "double_count_prevented": True,
        },
    )


def simulate_cross_spoke_utilization(
    initial_hub_atoms: int,
    events: Sequence[Mapping[str, Any]],
):
    balance = require_int(initial_hub_atoms, "initial_hub_atoms", minimum=0)
    trace = []
    for index, event in enumerate(events):
        kind = require_text(event.get("kind"), "kind").upper()
        amount = require_int(event.get("amount_atoms"), "amount_atoms", minimum=0)
        if kind == "DRAW":
            if amount > balance:
                raise EvidenceNativeError("SEQUENTIAL_SHARED_CAPACITY_EXHAUSTED")
            balance -= amount
        elif kind == "ADD":
            balance += amount
        else:
            raise EvidenceNativeError("SHARED_CREDIT_EVENT_UNKNOWN")
        trace.append({"sequence": index, "kind": kind, "amount_atoms": amount, "hub_after_atoms": balance})
    return record(
        "simulate_cross_spoke_utilization",
        {"initial_hub_atoms": initial_hub_atoms, "final_hub_atoms": balance, "trace": tuple(trace)},
    )


def detect_hub_spoke_basis(payload: Mapping[str, Any]):
    hub_rate = require_ppm(payload.get("hub_rate_ppm"), "hub_rate_ppm")
    spoke_rate = require_ppm(payload.get("spoke_rate_ppm"), "spoke_rate_ppm")
    local_capacity = require_int(payload.get("local_capacity_atoms"), "local_capacity_atoms", minimum=0)
    shared_capacity = require_int(payload.get("shared_capacity_atoms"), "shared_capacity_atoms", minimum=0)
    return record(
        "detect_hub_spoke_basis",
        {
            "rate_basis_ppm": spoke_rate - hub_rate,
            "local_capacity_atoms": local_capacity,
            "shared_capacity_atoms": shared_capacity,
            "capacity_overstatement_atoms": max(0, local_capacity - shared_capacity),
        },
    )


def qualify_shared_credit_route(payload: Mapping[str, Any]):
    required = ("hub_state_id", "spoke_state_id", "risk_generation", "capacity_generation")
    missing = tuple(field for field in required if not payload.get(field))
    coherent = bool(payload.get("same_snapshot", False)) and not missing
    return record(
        "qualify_shared_credit_route",
        {"qualified": coherent, "missing": missing, "same_snapshot": bool(payload.get("same_snapshot", False))},
    )
