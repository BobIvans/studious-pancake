"""PR-205 / OPE-01 — offline policy evaluation with explicit support checks."""

from __future__ import annotations

from typing import Sequence

from .common import PPM, integer, mean_int


def compute_importance_weights(
    logged_propensity_ppm: Sequence[int],
    target_propensity_ppm: Sequence[int],
    *,
    maximum_weight_ppm: int,
) -> tuple[int, ...]:
    if not logged_propensity_ppm or len(logged_propensity_ppm) != len(target_propensity_ppm):
        raise ValueError("propensity arrays must align")
    cap = integer(maximum_weight_ppm, "maximum_weight_ppm", minimum=1)
    weights: list[int] = []
    for logged, target in zip(logged_propensity_ppm, target_propensity_ppm, strict=True):
        log_p = integer(logged, "logged_propensity_ppm", minimum=1)
        target_p = integer(target, "target_propensity_ppm", minimum=0)
        weights.append(min(cap, target_p * PPM // log_p))
    return tuple(weights)


def estimate_offline_policy_value(
    rewards_atomic: Sequence[int],
    importance_weights_ppm: Sequence[int],
) -> int:
    if not rewards_atomic or len(rewards_atomic) != len(importance_weights_ppm):
        raise ValueError("rewards/weights must align")
    weighted = [
        integer(reward, "reward_atomic") * integer(weight, "weight_ppm", minimum=0) // PPM
        for reward, weight in zip(rewards_atomic, importance_weights_ppm, strict=True)
    ]
    return mean_int(weighted)


def run_doubly_robust_estimator(
    rewards_atomic: Sequence[int],
    logged_q_atomic: Sequence[int],
    target_q_atomic: Sequence[int],
    importance_weights_ppm: Sequence[int],
) -> int:
    if not rewards_atomic or not (
        len(rewards_atomic)
        == len(logged_q_atomic)
        == len(target_q_atomic)
        == len(importance_weights_ppm)
    ):
        raise ValueError("doubly robust arrays must align")
    terms = []
    for reward, logged_q, target_q, weight in zip(
        rewards_atomic,
        logged_q_atomic,
        target_q_atomic,
        importance_weights_ppm,
        strict=True,
    ):
        terms.append(
            integer(target_q, "target_q_atomic")
            + integer(weight, "weight_ppm", minimum=0)
            * (integer(reward, "reward_atomic") - integer(logged_q, "logged_q_atomic"))
            // PPM
        )
    return mean_int(terms)


def reject_unsupported_policy_shift(
    importance_weights_ppm: Sequence[int],
    *,
    maximum_weight_ppm: int,
    minimum_effective_sample_ppm: int,
) -> dict[str, int | bool]:
    if not importance_weights_ppm:
        raise ValueError("importance weights are required")
    weights = [integer(value, "weight_ppm", minimum=0) for value in importance_weights_ppm]
    total = sum(weights)
    squares = sum(value * value for value in weights)
    ess_ppm = 0 if squares == 0 else total * total * PPM // (len(weights) * squares)
    supported = max(weights) <= integer(maximum_weight_ppm, "maximum_weight_ppm", minimum=1)
    supported = supported and ess_ppm >= integer(
        minimum_effective_sample_ppm, "minimum_effective_sample_ppm", minimum=0
    )
    return {"supported": supported, "effective_sample_ppm": ess_ppm, "max_weight_ppm": max(weights)}


__all__ = [
    "compute_importance_weights",
    "estimate_offline_policy_value",
    "reject_unsupported_policy_shift",
    "run_doubly_robust_estimator",
]
