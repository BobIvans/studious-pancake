"""EVO-07 blockspace, preconfirmation and data-publication optionality."""

from typing import Any, Mapping

from .core import EvolutionError, build_candidate, qualify_candidate, result


def ingest_inclusion_market_quote(payload: Mapping[str, Any]):
    if not payload.get("terms_verified"):
        raise EvolutionError("TERMS_UNVERIFIED")
    if int(payload.get("expiry", 0)) <= int(payload.get("observed_time", 0)):
        raise EvolutionError("TARGET_EXPIRED")
    if not payload.get("source_id"):
        raise EvolutionError("SOURCE_UNKNOWN")
    return result("ingest_inclusion_market_quote", payload)


def estimate_inclusion_probability_curve(payload: Mapping[str, Any]):
    points = tuple((int(bid), int(ppm)) for bid, ppm in payload.get("points", ()))
    if len(points) < 3:
        raise EvolutionError("SAMPLE_SMALL")
    ordered = tuple(sorted(points))
    previous = -1
    for _bid, ppm in ordered:
        if ppm < previous or not 0 <= ppm <= 1_000_000:
            raise EvolutionError("CALIBRATION_FAIL")
        previous = ppm
    return result(
        "estimate_inclusion_probability_curve",
        {**dict(payload), "points": ordered, "monotone": True},
    )


def price_preconfirmation_option(payload: Mapping[str, Any]):
    if not payload.get("guarantee_enforceable"):
        raise EvolutionError("GUARANTEE_UNENFORCEABLE")
    if payload.get("loss_unknown"):
        raise EvolutionError("LOSS_UNKNOWN")
    if payload.get("quote_stale"):
        raise EvolutionError("QUOTE_STALE")
    value = (
        int(payload.get("guaranteed_value_atoms", 0))
        - int(payload.get("baseline_value_atoms", 0))
        - int(payload.get("premium_atoms", 0))
    )
    return result(
        "price_preconfirmation_option",
        {**dict(payload), "option_value_atoms": value},
    )


def estimate_blob_calldata_cost_surface(payload: Mapping[str, Any]):
    if payload.get("fee_state_stale"):
        raise EvolutionError("FEE_STATE_STALE")
    if not payload.get("compression_verified"):
        raise EvolutionError("COMPRESSION_UNVERIFIED")
    cheapest = min(
        int(payload.get("blob_cost_atoms", 0)),
        int(payload.get("calldata_cost_atoms", 0)),
    )
    return result(
        "estimate_blob_calldata_cost_surface",
        {**dict(payload), "cheapest_cost_atoms": cheapest},
    )


def detect_da_mode_switch(payload: Mapping[str, Any]):
    if not payload.get("safety_equivalent"):
        raise EvolutionError("SAFETY_NOT_EQUIVALENT")
    saving = int(payload.get("current_cost_atoms", 0)) - int(
        payload.get("alternative_cost_atoms", 0)
    )
    if saving <= int(payload.get("minimum_saving_atoms", 0)):
        raise EvolutionError("SAVING_INSIDE_BAND")
    if payload.get("deadline_risk"):
        raise EvolutionError("DEADLINE_RISK")
    return result(
        "detect_da_mode_switch", {**dict(payload), "saving_atoms": saving}
    )


def allocate_inclusion_budget(payload: Mapping[str, Any]):
    budget = int(payload.get("budget_atoms", 0))
    options = tuple((int(fee), int(value)) for fee, value in payload.get("options", ()))
    feasible = [
        (fee, value - fee)
        for fee, value in options
        if fee <= budget and value - fee > 0
    ]
    if not feasible:
        raise EvolutionError("NET_NONPOSITIVE")
    fee, net = max(feasible, key=lambda row: (row[1], -row[0]))
    return result(
        "allocate_inclusion_budget",
        {**dict(payload), "selected_fee_atoms": fee, "worst_case_net_atoms": net},
    )


def build_blockspace_candidate(payload: Mapping[str, Any]):
    if payload.get("target_mismatch"):
        raise EvolutionError("TARGET_MISMATCH")
    return build_candidate(
        "EVO-07", str(payload.get("candidate_type", "BLOCKSPACE_OPTION")), payload
    )


def qualify_blockspace_candidate(candidate, *, replay_count: int, policy_passed: bool, calibration_drift: bool, safety_downgrade: bool):
    if calibration_drift:
        raise EvolutionError("CALIBRATION_DRIFT")
    if safety_downgrade:
        raise EvolutionError("SAFETY_DOWNGRADE")
    return qualify_candidate(
        candidate,
        replay_count=replay_count,
        minimum_replays=3,
        policy_passed=policy_passed,
    )
