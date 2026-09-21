"""EVO-02 gauge/emission/claim/buyback epoch research."""

from typing import Any, Mapping

from .core import EvolutionError, build_candidate, contract, qualify_candidate, result


def ingest_epoch_emission_schedule(payload: Mapping[str, Any]):
    data = dict(payload)
    if data.get("token_metadata_verified") is False:
        raise EvolutionError("TOKEN_METADATA_UNKNOWN")
    if data.get("state_event_match") is False:
        raise EvolutionError("STATE_EVENT_MISMATCH")
    if data.get("epoch") is None:
        raise EvolutionError("EPOCH_UNKNOWN")
    return contract(
        "ingest_epoch_emission_schedule",
        data,
        required=("epoch", "reward_token", "rate_atoms", "start_time", "end_time"),
        integer_fields=("epoch", "rate_atoms", "start_time", "end_time"),
    )


def compute_gauge_reward_surface(payload: Mapping[str, Any]):
    data = dict(payload)
    bounded = (
        int(data.get("tvl_atoms", 0)),
        int(data.get("reward_atoms", 0)),
        int(data.get("claim_cost_atoms", 0)),
        int(data.get("price_low_atoms", 0)),
    )
    if any(abs(value) > 2**255 - 1 for value in bounded):
        raise EvolutionError("OVERFLOW")
    if int(data.get("tvl_atoms", 0)) <= 0:
        raise EvolutionError("TVL_ZERO")
    if data.get("price_low_atoms") is None:
        raise EvolutionError("PRICE_BAND_MISSING")
    marginal = max(
        0, int(data.get("reward_atoms", 0)) - int(data.get("claim_cost_atoms", 0))
    )
    return result(
        "compute_gauge_reward_surface", {**data, "marginal_reward_atoms": marginal}
    )


def estimate_incentive_vote_break_even(payload: Mapping[str, Any]):
    data = dict(payload)
    if not data.get("commitment_verified"):
        raise EvolutionError("COMMITMENT_UNVERIFIED")
    if data.get("rights_transferable") is False:
        raise EvolutionError("RIGHTS_NONTRANSFERABLE")
    if data.get("lock_cost_atoms") is None:
        raise EvolutionError("LOCK_COST_UNKNOWN")
    value = int(data.get("reward_delta_atoms", 0)) - int(data["lock_cost_atoms"])
    return result(
        "estimate_incentive_vote_break_even", {**data, "break_even_atoms": value}
    )


def forecast_fee_distributor_claim(payload: Mapping[str, Any]):
    data = dict(payload)
    if data.get("checkpoint_stale"):
        raise EvolutionError("CHECKPOINT_STALE")
    if not data.get("eligible"):
        raise EvolutionError("ELIGIBILITY_UNKNOWN")
    if data.get("claim_cost_atoms") is None:
        raise EvolutionError("CLAIM_COST_UNKNOWN")
    net = int(data.get("gross_claim_atoms", 0)) - int(data["claim_cost_atoms"])
    return result("forecast_fee_distributor_claim", {**data, "net_claim_atoms": net})


def compute_buyback_pressure_band(payload: Mapping[str, Any]):
    data = dict(payload)
    if not data.get("budget_funded"):
        raise EvolutionError("BUDGET_UNFUNDED")
    if not data.get("rules_verified"):
        raise EvolutionError("RULE_AMBIGUOUS")
    depth = int(data.get("executable_depth_atoms", 0))
    if depth <= 0:
        raise EvolutionError("LIQUIDITY_STALE")
    capacity = min(int(data.get("budget_atoms", 0)), depth)
    return result(
        "compute_buyback_pressure_band", {**data, "pressure_capacity_atoms": capacity}
    )


def detect_epoch_roll_dislocation(payload: Mapping[str, Any]):
    if int(payload.get("capacity_atoms", 0)) <= 0:
        raise EvolutionError("NO_CAPACITY")
    if int(payload.get("value_low_atoms", 0)) <= int(payload.get("cost_high_atoms", 0)):
        raise EvolutionError("INSIDE_BAND")
    if not payload.get("unwind_available"):
        raise EvolutionError("UNWIND_UNAVAILABLE")
    return contract(
        "detect_epoch_roll_dislocation",
        payload,
        integer_fields=("value_low_atoms", "cost_high_atoms", "capacity_atoms"),
        positive_edge=True,
    )


def build_incentive_rotation_candidate(payload: Mapping[str, Any]):
    if payload.get("reward_risk_unbounded"):
        raise EvolutionError("REWARD_RISK_UNBOUNDED")
    if int(payload.get("lock_duration", 0)) > int(payload.get("max_lock_duration", 0)):
        raise EvolutionError("LOCK_EXCEEDS_HORIZON")
    if not payload.get("exit_verified"):
        raise EvolutionError("MISSING_EXIT")
    return build_candidate("EVO-02", "INCENTIVE_ROTATION", payload)


def qualify_incentive_rotation(
    candidate,
    *,
    epoch_count: int,
    policy_passed: bool,
    attribution_clean: bool = True,
):
    if not attribution_clean:
        raise EvolutionError("ATTRIBUTION_LEAK")
    if epoch_count < 3:
        raise EvolutionError("EPOCH_SAMPLE_TOO_SMALL")
    return qualify_candidate(
        candidate,
        replay_count=epoch_count,
        minimum_replays=3,
        policy_passed=policy_passed,
    )
