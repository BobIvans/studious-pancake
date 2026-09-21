"""PR-252 / LEADLAG-01: multi-scale information-flow research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .base import (
    Disposition,
    ResearchArtifact,
    artifact,
    correlation,
    require_same_length,
)


def estimate_multiscale_lead_lag(
    leader: Sequence[float],
    follower: Sequence[float],
    *,
    max_lag: int = 3,
) -> ResearchArtifact:
    require_same_length(leader, follower)
    if max_lag < 1:
        raise ValueError("max_lag must be positive")
    scores = {}
    for lag in range(1, min(max_lag, len(leader) - 1) + 1):
        scores[str(lag)] = correlation(leader[:-lag], follower[lag:])
    return artifact(
        "multiscale-lead-lag",
        {"scores": scores, "clock_uncertainty_required": True},
    )


def build_information_flow_graph(
    links: Mapping[str, ResearchArtifact],
) -> ResearchArtifact:
    edges = {
        key: value.payload["scores"]
        for key, value in sorted(links.items())
    }
    return artifact(
        "information-flow-graph",
        {"edges": edges, "time_versioned": True},
    )


def test_lead_lag_stability(
    train: ResearchArtifact,
    holdout: ResearchArtifact,
    *,
    tolerance: float = 0.25,
) -> ResearchArtifact:
    common = sorted(set(train.payload["scores"]) & set(holdout.payload["scores"]))
    stable = bool(common) and all(
        abs(
            float(train.payload["scores"][lag])
            - float(holdout.payload["scores"][lag])
        )
        <= tolerance
        for lag in common
    )
    return artifact(
        "lead-lag-stability",
        {"lags": tuple(common), "stable": stable},
        disposition=Disposition.PASS if stable else Disposition.REJECT,
        reason="holdout-stable" if stable else "lead-lag-instability",
    )


def promote_predictive_link(
    stability: ResearchArtifact,
    *,
    stale_data_alternative_rejected: bool,
    common_cause_alternative_tested: bool,
) -> ResearchArtifact:
    passed = (
        stability.disposition is Disposition.PASS
        and bool(stale_data_alternative_rejected)
        and bool(common_cause_alternative_tested)
    )
    return artifact(
        "predictive-feature-link",
        {
            "stability": stability.identity,
            "stale_data_alternative_rejected": bool(
                stale_data_alternative_rejected
            ),
            "common_cause_alternative_tested": bool(
                common_cause_alternative_tested
            ),
            "execution_authority": False,
        },
        disposition=Disposition.PASS if passed else Disposition.BLOCKED,
        reason="feature-link-only" if passed else "alternatives-not-resolved",
    )


__all__ = [
    "build_information_flow_graph",
    "estimate_multiscale_lead_lag",
    "promote_predictive_link",
    "test_lead_lag_stability",
]
