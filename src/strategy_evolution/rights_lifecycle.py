"""EVO-08 expiry/exercise/vesting/streaming/claim lifecycle."""

from typing import Any, Mapping

from .core import EvolutionError, build_candidate, contract, qualify_candidate, result


def normalize_rights_lifecycle_event(payload: Mapping[str, Any]):
    if not payload.get("terms_verified"):
        raise EvolutionError("TERMS_UNVERIFIED")
    if not payload.get("beneficiary_known"):
        raise EvolutionError("BENEFICIARY_UNKNOWN")
    if payload.get("illegal_transition"):
        raise EvolutionError("ILLEGAL_TRANSITION")
    if payload.get("state") not in {
        "CREATED",
        "ACCRUING",
        "EXERCISABLE",
        "CLAIMABLE",
        "EXPIRED",
        "SETTLED",
        "CANCELLED",
    }:
        raise EvolutionError("ILLEGAL_TRANSITION")
    return contract(
        "normalize_rights_lifecycle_event",
        payload,
        required=("state", "right_type", "beneficiary", "finality"),
        finality=True,
    )


def estimate_expiry_exercise_flow(payload: Mapping[str, Any]):
    if payload.get("open_interest_atoms") is None:
        raise EvolutionError("OI_UNAVAILABLE")
    if not payload.get("settlement_rules_verified"):
        raise EvolutionError("SETTLEMENT_RULE_UNKNOWN")
    oi = int(payload.get("open_interest_atoms", 0))
    low = int(payload.get("exercise_low_ppm", 0))
    high = int(payload.get("exercise_high_ppm", 1_000_000))
    if not 0 <= low <= high <= 1_000_000:
        raise EvolutionError("VOL_SURFACE_MISSING")
    return result(
        "estimate_expiry_exercise_flow",
        {
            **dict(payload),
            "flow_low_atoms": oi * low // 1_000_000,
            "flow_high_atoms": oi * high // 1_000_000,
        },
    )


def price_settlement_basis(payload: Mapping[str, Any]):
    if payload.get("oracle_window_unknown"):
        raise EvolutionError("ORACLE_WINDOW_UNKNOWN")
    if payload.get("delivery_unavailable"):
        raise EvolutionError("DELIVERY_UNAVAILABLE")
    return contract(
        "price_settlement_basis",
        payload,
        integer_fields=("value_low_atoms", "cost_high_atoms"),
        positive_edge=True,
    )


def forecast_unlock_stream_supply(payload: Mapping[str, Any]):
    if payload.get("entity_map_weak"):
        raise EvolutionError("ENTITY_MAP_WEAK")
    if payload.get("stream_state_gap"):
        raise EvolutionError("STREAM_STATE_GAP")
    if payload.get("cancellation_right_unknown"):
        raise EvolutionError("CANCELLATION_RIGHT_UNKNOWN")
    total = int(payload.get("total_atoms", 0))
    vested = int(payload.get("vested_atoms", 0))
    withdrawable = int(payload.get("withdrawable_atoms", 0))
    if not 0 <= withdrawable <= vested <= total:
        raise EvolutionError("STREAM_STATE_GAP")
    return result(
        "forecast_unlock_stream_supply",
        {**dict(payload), "locked_atoms": total - vested},
    )


def detect_claim_window_mispricing(payload: Mapping[str, Any]):
    if not payload.get("eligible"):
        raise EvolutionError("INELIGIBLE")
    if not payload.get("transferable") and payload.get("secondary_candidate"):
        raise EvolutionError("NONTRANSFERABLE")
    if payload.get("window_closed"):
        raise EvolutionError("WINDOW_CLOSED")
    return contract(
        "detect_claim_window_mispricing",
        payload,
        integer_fields=("value_low_atoms", "cost_high_atoms"),
        positive_edge=True,
    )


def estimate_transferability_haircut(payload: Mapping[str, Any]):
    if payload.get("restrictions_ambiguous"):
        raise EvolutionError("RESTRICTIONS_AMBIGUOUS")
    if payload.get("jurisdiction_block"):
        raise EvolutionError("JURISDICTION_BLOCK")
    haircut = (
        1_000_000
        if not payload.get("transferable")
        else int(payload.get("liquidity_haircut_ppm", 0))
    )
    if not 0 <= haircut <= 1_000_000:
        raise EvolutionError("VENUE_UNVERIFIED")
    return result(
        "estimate_transferability_haircut", {**dict(payload), "haircut_ppm": haircut}
    )


def build_lifecycle_candidate(payload: Mapping[str, Any]):
    if not payload.get("evidence_refs"):
        raise EvolutionError("LINEAGE_GAP")
    candidate_type = str(payload.get("candidate_type", ""))
    if candidate_type not in {"EXPIRY", "UNLOCK", "CLAIM"}:
        raise EvolutionError("TYPE_MIXED")
    if not payload.get("terminal_state_known"):
        raise EvolutionError("TERMINAL_STATE_UNKNOWN")
    return build_candidate("EVO-08", candidate_type, payload)


def qualify_lifecycle_candidate(
    candidate,
    *,
    replay_count: int,
    policy_passed: bool,
    entity_concentration_ok: bool,
    replay_diverged: bool = False,
):
    if replay_diverged:
        raise EvolutionError("REPLAY_DIVERGENCE")
    if not entity_concentration_ok:
        raise EvolutionError("ENTITY_CONCENTRATION")
    return qualify_candidate(
        candidate,
        replay_count=replay_count,
        minimum_replays=3,
        policy_passed=policy_passed,
    )
