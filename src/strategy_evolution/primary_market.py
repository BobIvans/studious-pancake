"""EVO-04 primary issuance, async vault and redemption-window basis."""

from typing import Any, Mapping

from .core import (
    EvolutionError,
    assert_transition,
    build_candidate,
    contract,
    qualify_candidate,
    result,
)

TRANSITIONS = {
    "REQUESTED": ("PENDING", "CANCELLED"),
    "PENDING": ("CLAIMABLE", "CANCELLED"),
    "CLAIMABLE": ("CLAIMED",),
    "CLAIMED": (),
    "CANCELLED": (),
}


def normalize_primary_market_terms(payload: Mapping[str, Any]):
    if not payload.get("terms_verified"):
        raise EvolutionError("TERMS_UNVERIFIED")
    if not payload.get("eligible"):
        raise EvolutionError("ACCESS_RESTRICTED")
    if not payload.get("settlement_asset"):
        raise EvolutionError("SETTLEMENT_UNKNOWN")
    return contract(
        "normalize_primary_market_terms",
        payload,
        integer_fields=("fee_atoms", "min_atoms", "max_atoms", "cutoff_time"),
    )


def track_async_vault_request(payload: Mapping[str, Any]):
    if payload.get("event_gap"):
        raise EvolutionError("EVENT_GAP")
    current = str(payload.get("current_state"))
    target = str(payload.get("target_state"))
    assert_transition(current, target, TRANSITIONS)
    if payload.get("controller") != payload.get("expected_controller"):
        raise EvolutionError("CONTROLLER_MISMATCH")
    return result("track_async_vault_request", {**dict(payload), "state": target})


def estimate_next_nav_oracle_window(payload: Mapping[str, Any]):
    if not payload.get("calendar_known"):
        raise EvolutionError("CALENDAR_MISSING")
    if payload.get("source_stale"):
        raise EvolutionError("SOURCE_STALE")
    earliest = int(payload.get("earliest", -1))
    latest = int(payload.get("latest", -1))
    if earliest < 0 or latest < earliest:
        raise EvolutionError("WINDOW_UNBOUNDED")
    return result(
        "estimate_next_nav_oracle_window",
        {**dict(payload), "window_width": latest - earliest},
    )


def price_mint_redeem_latency(payload: Mapping[str, Any]):
    if payload.get("claim_uncertain"):
        raise EvolutionError("CLAIM_UNCERTAIN")
    if payload.get("funding_curve_missing"):
        raise EvolutionError("FUNDING_CURVE_MISSING")
    if payload.get("fx_unknown"):
        raise EvolutionError("FX_UNKNOWN")
    total = sum(
        int(payload.get(key, 0))
        for key in (
            "carry_atoms",
            "fee_atoms",
            "failure_haircut_atoms",
            "opportunity_cost_atoms",
        )
    )
    return result(
        "price_mint_redeem_latency",
        {**dict(payload), "settlement_cost_atoms": total},
    )


def detect_primary_secondary_basis(payload: Mapping[str, Any]):
    if int(payload.get("value_low_atoms", 0)) <= int(payload.get("cost_high_atoms", 0)):
        raise EvolutionError("NEGATIVE_WORST_CASE")
    if not payload.get("eligible"):
        raise EvolutionError("NOT_ELIGIBLE")
    if payload.get("cutoff_missed"):
        raise EvolutionError("CUTOFF_MISSED")
    return contract(
        "detect_primary_secondary_basis",
        payload,
        integer_fields=("value_low_atoms", "cost_high_atoms"),
        positive_edge=True,
    )


def size_settlement_inventory(payload: Mapping[str, Any]):
    requested = payload.get("requested_atoms")
    capacity = int(payload.get("capacity_atoms", 0))
    if requested is not None and int(requested) > capacity:
        raise EvolutionError("CAP_EXCEEDED")
    if int(payload.get("duration_seconds", 0)) > int(
        payload.get("max_duration_seconds", 0)
    ):
        raise EvolutionError("DURATION_EXCEEDED")
    size = min(
        int(payload.get("capital_atoms", 0)),
        int(payload.get("capacity_atoms", 0)),
        int(payload.get("concentration_cap_atoms", 0)),
    )
    if size <= 0:
        raise EvolutionError("CAPITAL_UNAVAILABLE")
    return result(
        "size_settlement_inventory",
        {**dict(payload), "reserved_atoms": size, "terminal_release_only": True},
    )


def build_primary_market_candidate(payload: Mapping[str, Any]):
    if not payload.get("evidence_refs"):
        raise EvolutionError("LINEAGE_GAP")
    if not payload.get("primary_leg_proven"):
        raise EvolutionError("PRIMARY_LEG_UNPROVEN")
    if not payload.get("hedge_present"):
        raise EvolutionError("HEDGE_MISSING")
    return build_candidate("EVO-04", "PRIMARY_SECONDARY_BASIS", payload)


def qualify_primary_market(
    candidate, *, replay_count: int, policy_passed: bool, reconciliation_passed: bool
):
    if replay_count < 3:
        raise EvolutionError("SETTLEMENT_SAMPLE_SMALL")
    if not reconciliation_passed:
        raise EvolutionError("RECONCILIATION_FAIL")
    return qualify_candidate(
        candidate,
        replay_count=replay_count,
        minimum_replays=3,
        policy_passed=policy_passed,
    )
