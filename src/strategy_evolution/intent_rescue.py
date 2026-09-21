"""EVO-06 intent auctions, solver residual and keeper rescue."""

from typing import Any, Mapping

from .core import EvolutionError, build_candidate, contract, qualify_candidate, result


def normalize_intent_auction(payload: Mapping[str, Any]):
    if not payload.get("payload_verified"):
        raise EvolutionError("PAYLOAD_UNVERIFIED")
    if int(payload.get("deadline", 0)) <= int(payload.get("observed_time", 0)):
        raise EvolutionError("DEADLINE_EXPIRED")
    if not payload.get("token_identity_verified"):
        raise EvolutionError("TOKEN_UNKNOWN")
    return result("normalize_intent_auction", payload)


def reconstruct_solver_score(payload: Mapping[str, Any]):
    if not payload.get("rules_verified"):
        raise EvolutionError("RULE_VERSION_UNKNOWN")
    if not payload.get("solution_feasible"):
        raise EvolutionError("SOLUTION_INFEASIBLE")
    expected = int(payload.get("user_surplus_atoms", 0)) - int(
        payload.get("fees_atoms", 0)
    )
    if int(payload.get("reported_score_atoms", expected)) != expected:
        raise EvolutionError("SCORE_MISMATCH")
    return result(
        "reconstruct_solver_score",
        {**dict(payload), "recomputed_score_atoms": expected},
    )


def estimate_batch_clearing_price(payload: Mapping[str, Any]):
    prices = tuple(int(value) for value in payload.get("feasible_prices_atoms", ()))
    if not prices:
        raise EvolutionError("NO_FEASIBLE_CLEARING")
    if payload.get("liquidity_stale"):
        raise EvolutionError("LIQUIDITY_STALE")
    return result(
        "estimate_batch_clearing_price",
        {
            **dict(payload),
            "clearing_low_atoms": min(prices),
            "clearing_high_atoms": max(prices),
        },
    )


def detect_solver_surplus_residual(payload: Mapping[str, Any]):
    if not payload.get("receipt_present"):
        raise EvolutionError("RECEIPT_MISSING")
    known = sum(
        int(payload.get(key, 0))
        for key in (
            "user_surplus_atoms",
            "solver_fee_atoms",
            "gas_atoms",
            "market_move_atoms",
        )
    )
    unexplained = int(payload.get("total_residual_atoms", 0)) - known
    if abs(unexplained) <= int(payload.get("tolerance_atoms", 0)):
        raise EvolutionError("INSIDE_TOLERANCE")
    return result(
        "detect_solver_surplus_residual",
        {**dict(payload), "unexplained_atoms": unexplained},
    )


def detect_keeper_liveness_gap(payload: Mapping[str, Any]):
    if not payload.get("trigger_verified"):
        raise EvolutionError("TRIGGER_UNVERIFIED")
    if payload.get("job_paused"):
        raise EvolutionError("JOB_PAUSED")
    if payload.get("funding_unknown"):
        raise EvolutionError("FUNDING_UNKNOWN")
    delay = int(payload.get("now", 0)) - int(payload.get("last_execution", 0))
    sla = int(payload.get("sla_seconds", 0))
    if delay <= sla:
        raise EvolutionError("INSIDE_TOLERANCE")
    return result(
        "detect_keeper_liveness_gap",
        {**dict(payload), "gap_seconds": delay - sla},
    )


def price_rescue_bounty(payload: Mapping[str, Any]):
    if not payload.get("reward_funded"):
        raise EvolutionError("REWARD_UNFUNDED")
    if payload.get("race_risk_unbounded"):
        raise EvolutionError("RACE_RISK_UNBOUNDED")
    return contract(
        "price_rescue_bounty",
        payload,
        integer_fields=("value_low_atoms", "cost_high_atoms"),
        positive_edge=True,
    )


def build_intent_rescue_candidate(payload: Mapping[str, Any]):
    candidate_type = str(payload.get("candidate_type", ""))
    if candidate_type not in {"INTENT_RESIDUAL", "KEEPER_RESCUE"}:
        raise EvolutionError("TYPE_AMBIGUOUS")
    return build_candidate("EVO-06", candidate_type, payload)


def qualify_intent_rescue(candidate, *, replay_count: int, policy_passed: bool, concurrency_passed: bool):
    if not concurrency_passed:
        raise EvolutionError("CONCURRENCY_FAIL")
    return qualify_candidate(
        candidate,
        replay_count=replay_count,
        minimum_replays=3,
        policy_passed=policy_passed,
    )
