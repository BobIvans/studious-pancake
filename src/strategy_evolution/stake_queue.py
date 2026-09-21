"""EVO-03 validator/restaking queue and slash-risk basis."""

from typing import Any, Mapping

from .core import EvolutionError, build_candidate, contract, qualify_candidate, result


def ingest_validator_queue_state(payload: Mapping[str, Any]):
    if payload.get("queue_gap"):
        raise EvolutionError("QUEUE_GAP")
    return contract(
        "ingest_validator_queue_state",
        payload,
        required=("activation_queue", "exit_queue", "churn_limit", "finality"),
        integer_fields=("activation_queue", "exit_queue", "churn_limit"),
        finality=True,
    )


def estimate_validator_activation_exit_eta(payload: Mapping[str, Any]):
    churn = int(payload.get("churn_limit", 0))
    epoch_seconds = int(payload.get("epoch_seconds", 0))
    if churn <= 0:
        raise EvolutionError("CONSTANTS_UNVERIFIED")
    if epoch_seconds <= 0:
        raise EvolutionError("ETA_UNBOUNDED")
    queue = max(
        int(payload.get("activation_queue", 0)), int(payload.get("exit_queue", 0))
    )
    epochs = (queue + churn - 1) // churn
    return result(
        "estimate_validator_activation_exit_eta",
        {
            **dict(payload),
            "eta_earliest": epochs * epoch_seconds,
            "eta_stress": (epochs + 2) * epoch_seconds,
        },
    )


def price_withdrawal_request_fee(payload: Mapping[str, Any]):
    if not payload.get("active"):
        raise EvolutionError("PREDEPLOY_INACTIVE")
    base = int(payload.get("base_fee_atoms", 0))
    excess = int(payload.get("excess_requests", 0))
    if base < 0 or excess < 0:
        raise EvolutionError("STATE_UNAVAILABLE")
    return result(
        "price_withdrawal_request_fee",
        {**dict(payload), "request_fee_atoms": base * (2 ** min(excess, 32))},
    )


def normalize_restaking_withdrawal_state(payload: Mapping[str, Any]):
    if not payload.get("delegation_graph_complete"):
        raise EvolutionError("GRAPH_INCOMPLETE")
    if payload.get("delay_seconds") is None:
        raise EvolutionError("DELAY_UNKNOWN")
    if payload.get("claim_state") not in {"QUEUED", "DELAY", "CLAIMABLE", "CLAIMED"}:
        raise EvolutionError("CLAIM_AMBIGUOUS")
    return contract(
        "normalize_restaking_withdrawal_state",
        payload,
        integer_fields=("delay_seconds", "withdrawal_atoms"),
    )


def model_slashing_loss_distribution(payload: Mapping[str, Any]):
    if not payload.get("rules_verified"):
        raise EvolutionError("RULES_UNVERIFIED")
    losses = tuple(int(value) for value in payload.get("loss_scenarios_atoms", ()))
    if not losses:
        raise EvolutionError("EXPOSURE_UNKNOWN")
    if payload.get("correlation_unbounded"):
        raise EvolutionError("CORRELATION_UNBOUNDED")
    return result(
        "model_slashing_loss_distribution",
        {
            **dict(payload),
            "loss_low_atoms": min(losses),
            "loss_high_atoms": max(losses),
            "probabilities_fabricated": False,
        },
    )


def compute_stake_liquidity_basis(payload: Mapping[str, Any]):
    if payload.get("quote_stale"):
        raise EvolutionError("QUOTE_STALE")
    if int(payload.get("duration_seconds", 0)) <= 0:
        raise EvolutionError("DURATION_ZERO")
    if payload.get("exit_cost_atoms") is None:
        raise EvolutionError("EXIT_COST_UNKNOWN")
    return contract(
        "compute_stake_liquidity_basis",
        payload,
        integer_fields=("value_low_atoms", "cost_high_atoms"),
        positive_edge=True,
    )


def build_stake_queue_candidate(payload: Mapping[str, Any]):
    if not payload.get("independent_exit"):
        raise EvolutionError("ONE_WAY_LIQUIDITY")
    if payload.get("loss_tail_unbounded"):
        raise EvolutionError("LOSS_TAIL_UNBOUNDED")
    return build_candidate("EVO-03", "STAKE_QUEUE_BASIS", payload)


def qualify_stake_queue(
    candidate, *, replay_count: int, policy_passed: bool, stress_passed: bool
):
    if not stress_passed:
        raise EvolutionError("STRESS_FAIL")
    return qualify_candidate(
        candidate,
        replay_count=replay_count,
        minimum_replays=3,
        policy_passed=policy_passed,
    )
