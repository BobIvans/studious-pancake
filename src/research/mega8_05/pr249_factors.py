"""PR-249 / FACTOR-01: leakage-safe online covariance and factor research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .base import (
    ResearchArtifact,
    artifact,
    covariance,
    mean,
    require_same_length,
    variance,
)


def update_online_covariance(
    series: Mapping[str, Sequence[float]],
) -> ResearchArtifact:
    if not series:
        raise ValueError("series cannot be empty")
    names = tuple(sorted(series))
    require_same_length(*(series[name] for name in names))
    matrix = {
        left: {right: covariance(series[left], series[right]) for right in names}
        for left in names
    }
    return artifact(
        "online-covariance",
        {"assets": names, "covariance": matrix, "leakage_safe": True},
    )


def fit_dynamic_factor_model(
    series: Mapping[str, Sequence[float]],
) -> ResearchArtifact:
    if not series:
        raise ValueError("series cannot be empty")
    names = tuple(sorted(series))
    length = require_same_length(*(series[name] for name in names))
    factor = tuple(
        mean([float(series[name][index]) for name in names]) for index in range(length)
    )
    return artifact(
        "dynamic-factor-model",
        {"assets": names, "factor": factor, "window_points": length},
    )


def estimate_factor_exposures(
    series: Mapping[str, Sequence[float]],
    factor_model: ResearchArtifact,
) -> ResearchArtifact:
    factor = tuple(float(value) for value in factor_model.payload["factor"])
    factor_var = variance(factor)
    exposures = {}
    for name, values in sorted(series.items()):
        require_same_length(values, factor)
        exposures[name] = (
            covariance(tuple(float(value) for value in values), factor) / factor_var
            if factor_var > 0.0
            else 0.0
        )
    return artifact(
        "factor-exposures",
        {"factor_model": factor_model.identity, "exposures": exposures},
    )


def detect_factor_residual(
    observed: Mapping[str, float],
    exposures: ResearchArtifact,
    *,
    factor_value: float,
) -> ResearchArtifact:
    residuals = {
        name: float(observed[name]) - float(beta) * float(factor_value)
        for name, beta in exposures.payload["exposures"].items()
        if name in observed
    }
    return artifact(
        "factor-residuals",
        {
            "exposures": exposures.identity,
            "factor_value": float(factor_value),
            "residuals": residuals,
            "execution_signal": False,
        },
    )


__all__ = [
    "detect_factor_residual",
    "estimate_factor_exposures",
    "fit_dynamic_factor_model",
    "update_online_covariance",
]
