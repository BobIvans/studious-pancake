"""PR-269 / RL-EXEC-01: conservative offline execution-policy research."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega806Error, require_int, require_text, stable_hash


def build_execution_trajectory_dataset(
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    dataset = []
    for row in rows:
        action = require_text(row.get("action"), "action")
        reward = require_int(row.get("reward"), "reward")
        if row.get("available_at") is None or row.get("decision_at") is None:
            raise Mega806Error("MISSING_AVAILABILITY_TIME")
        if int(row["available_at"]) > int(row["decision_at"]):
            raise Mega806Error("FUTURE_DATA_LEAKAGE")
        dataset.append(
            {
                "action": action,
                "reward": reward,
                "supported": row.get("supported") is True,
            }
        )
    return tuple(dataset)


def train_offline_execution_policy(
    trajectories: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    totals: dict[str, list[int]] = {}
    for row in trajectories:
        if row.get("supported") is not True:
            continue
        action = require_text(row.get("action"), "action")
        totals.setdefault(action, []).append(require_int(row.get("reward"), "reward"))
    if not totals:
        raise Mega806Error("NO_SUPPORTED_ACTIONS")
    means = {
        action: sum(values) // len(values) for action, values in totals.items()
    }
    best = max(means, key=lambda action: (means[action], action))
    return {
        "action": best,
        "means": means,
        "policy_sha256": stable_hash(means),
        "advisory_only": True,
    }


def evaluate_execution_policy_offline(
    policy: Mapping[str, object],
    trajectories: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    action = require_text(policy.get("action"), "action")
    matched = [
        require_int(row.get("reward"), "reward")
        for row in trajectories
        if row.get("action") == action and row.get("supported") is True
    ]
    if not matched:
        raise Mega806Error("SUPPORT_MISMATCH")
    return {"support": len(matched), "mean_reward": sum(matched) // len(matched)}


def gate_policy_deployment(
    evaluation: Mapping[str, int], *, baseline_reward: int
) -> str:
    baseline_reward = require_int(baseline_reward, "baseline_reward")
    if int(evaluation.get("support", 0)) <= 0:
        raise Mega806Error("INSUFFICIENT_SUPPORT")
    if int(evaluation.get("mean_reward", -(10**30))) <= baseline_reward:
        raise Mega806Error("BASELINE_NOT_BEATEN")
    return "ADVISORY_SHADOW_ONLY"
