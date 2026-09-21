"""PR-250 / STATARB-01: non-atomic statistical-arbitrage research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .base import (
    Disposition,
    ResearchArtifact,
    artifact,
    covariance,
    mean,
    require_same_length,
    variance,
)


def discover_cointegrated_baskets(
    pairs: Mapping[str, tuple[Sequence[float], Sequence[float]]],
) -> ResearchArtifact:
    candidates = {}
    for pair_id, (left, right) in sorted(pairs.items()):
        require_same_length(left, right)
        right_var = variance(tuple(float(value) for value in right))
        hedge = (
            covariance(
                tuple(float(value) for value in left),
                tuple(float(value) for value in right),
            )
            / right_var
            if right_var > 0.0
            else 0.0
        )
        residual = tuple(
            float(a) - hedge * float(b) for a, b in zip(left, right, strict=True)
        )
        if len(residual) < 3:
            score = 0.0
        else:
            lagged = residual[:-1]
            current = residual[1:]
            denominator = sum(value * value for value in lagged)
            phi = (
                sum(a * b for a, b in zip(lagged, current, strict=True)) / denominator
                if denominator > 0.0
                else 1.0
            )
            score = max(0.0, 1.0 - abs(phi))
        candidates[pair_id] = {
            "hedge": hedge,
            "mean_reversion_score": score,
            "formal_cointegration_claim": False,
        }
    return artifact(
        "cointegration-candidates",
        {"candidates": candidates, "research_only": True},
    )


def estimate_hedge_vector(
    left: Sequence[float],
    right: Sequence[float],
) -> ResearchArtifact:
    require_same_length(left, right)
    right_values = tuple(float(value) for value in right)
    denominator = variance(right_values)
    beta = (
        covariance(tuple(float(value) for value in left), right_values) / denominator
        if denominator > 0.0
        else 0.0
    )
    intercept = mean(tuple(float(value) for value in left)) - beta * mean(right_values)
    return artifact("hedge-vector", {"intercept": intercept, "beta": beta})


def model_mean_reversion_half_life(
    residuals: Sequence[float],
) -> ResearchArtifact:
    values = tuple(float(value) for value in residuals)
    if len(values) < 3:
        return artifact(
            "mean-reversion-half-life",
            {"half_life": None, "statistical_not_observed_edge_duration": True},
            disposition=Disposition.UNKNOWN,
            reason="insufficient-points",
        )
    lagged = values[:-1]
    delta = tuple(b - a for a, b in zip(values[:-1], values[1:], strict=True))
    denominator = sum(value * value for value in lagged)
    slope = (
        sum(a * b for a, b in zip(lagged, delta, strict=True)) / denominator
        if denominator > 0.0
        else 0.0
    )
    half_life = None if slope >= 0.0 else 0.6931471805599453 / (-slope)
    return artifact(
        "mean-reversion-half-life",
        {
            "half_life": half_life,
            "statistical_not_observed_edge_duration": True,
        },
        disposition=Disposition.PASS if half_life is not None else Disposition.UNKNOWN,
        reason="bounded-estimate" if half_life is not None else "no-mean-reversion",
    )


def qualify_stat_arb_basket(
    *,
    preregistered: bool,
    multiple_testing_corrected: bool,
    temporal_holdout_positive: bool,
    all_costs_included: bool,
    inventory_margin_qualified: bool,
) -> ResearchArtifact:
    checks = {
        "preregistered": bool(preregistered),
        "multiple_testing_corrected": bool(multiple_testing_corrected),
        "temporal_holdout_positive": bool(temporal_holdout_positive),
        "all_costs_included": bool(all_costs_included),
        "inventory_margin_qualified": bool(inventory_margin_qualified),
        "inherits_atomic_permission": False,
    }
    passed = all(
        value for key, value in checks.items() if key != "inherits_atomic_permission"
    )
    return artifact(
        "stat-arb-qualification",
        checks,
        disposition=Disposition.PASS if passed else Disposition.BLOCKED,
        reason=(
            "research-qualified-non-atomic" if passed else "non-atomic-evidence-missing"
        ),
    )


__all__ = [
    "discover_cointegrated_baskets",
    "estimate_hedge_vector",
    "model_mean_reversion_half_life",
    "qualify_stat_arb_basket",
]
