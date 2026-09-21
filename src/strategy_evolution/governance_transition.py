"""EVO-01 governance/timelock transition pricing."""

from typing import Any, Mapping

from .core import EvolutionError, build_candidate, contract, qualify_candidate, result


def normalize_governance_event(payload: Mapping[str, Any]):
    data = dict(payload)
    if data.get("event_kind") not in {"PROPOSE", "QUEUE", "CANCEL", "EXECUTE"}:
        raise EvolutionError("UNKNOWN_ABI")
    if data.get("reorged"):
        raise EvolutionError("REORGED_EVENT")
    return contract(
        "normalize_governance_event",
        data,
        required=("raw_event", "chain_domain", "event_time", "observed_time"),
        finality=True,
    )


def decode_parameter_delta(payload: Mapping[str, Any]):
    data = dict(payload)
    if not data.get("interface_verified"):
        raise EvolutionError("UNVERIFIED_INTERFACE")
    if data.get("selector_kind") != "PARAMETER":
        raise EvolutionError("NON_PARAMETER_ACTION")
    return contract(
        "decode_parameter_delta",
        data,
        required=("parameter", "old_value", "new_value"),
        integer_fields=("old_value", "new_value"),
    )


def simulate_post_change_state(payload: Mapping[str, Any]):
    data = dict(payload)
    if data.get("unsupported_delta"):
        raise EvolutionError("UNSUPPORTED_DELTA")
    if data.get("invariant_break"):
        raise EvolutionError("INVARIANT_BREAK")
    state = dict(data.get("pre_state", {}))
    state.update(dict(data.get("deltas", {})))
    return result("simulate_post_change_state", {"post_state": state, "remote_write": False})


def price_transition_window(payload: Mapping[str, Any]):
    return contract(
        "price_transition_window",
        payload,
        required=("value_low_atoms", "cost_high_atoms", "capacity_atoms"),
        integer_fields=(
            "value_low_atoms",
            "value_high_atoms",
            "cost_low_atoms",
            "cost_high_atoms",
            "capacity_atoms",
        ),
        positive_edge=True,
    )


def detect_pre_post_activation_basis(payload: Mapping[str, Any]):
    data = dict(payload)
    if data.get("stale_market"):
        raise EvolutionError("STALE_MARKET")
    if data.get("slot_skew"):
        raise EvolutionError("SLOT_SKEW")
    price = int(data.get("market_price_atoms", 0))
    low = int(data.get("post_low_atoms", 0))
    high = int(data.get("post_high_atoms", 0))
    direction = "BELOW" if price < low else "ABOVE" if price > high else "INSIDE"
    if direction == "INSIDE":
        raise EvolutionError("INSIDE_BAND")
    return result("detect_pre_post_activation_basis", {**data, "direction": direction})


def bound_governance_execution_uncertainty(payload: Mapping[str, Any]):
    data = dict(payload)
    if data.get("clock_mode") not in {"BLOCK", "TIMESTAMP"}:
        raise EvolutionError("CLOCK_MISMATCH")
    if not data.get("executor_known"):
        raise EvolutionError("EXECUTOR_UNKNOWN")
    earliest = int(data.get("earliest_execution", -1))
    latest = int(data.get("latest_execution", -1))
    if earliest < 0 or latest < earliest:
        raise EvolutionError("WINDOW_UNBOUNDED")
    return result(
        "bound_governance_execution_uncertainty",
        {**data, "window_width": latest - earliest},
    )


def build_governance_transition_candidate(payload: Mapping[str, Any]):
    if int(payload.get("expires_at", 0)) > int(
        payload.get("execution_latest", payload.get("expires_at", 0))
    ):
        raise EvolutionError("TTL_EXCEEDS_WINDOW")
    return build_candidate("EVO-01", "GOVERNANCE_TRANSITION", payload)


def qualify_governance_transition(candidate, *, replay_count: int, policy_passed: bool, drift: bool = False):
    return qualify_candidate(
        candidate,
        replay_count=replay_count,
        minimum_replays=3,
        policy_passed=policy_passed,
        drift=drift,
    )
