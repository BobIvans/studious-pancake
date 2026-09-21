"""PR-251 / REGIME-01: structural-break and regime applicability evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .base import Disposition, ResearchArtifact, artifact, mean, variance


def detect_structural_break(
    values: Sequence[float],
    *,
    minimum_relative_shift: float = 0.25,
) -> ResearchArtifact:
    points = tuple(float(value) for value in values)
    if len(points) < 6:
        return artifact(
            "structural-break",
            {"detected": False, "support": len(points)},
            disposition=Disposition.UNKNOWN,
            reason="insufficient-support",
        )
    midpoint = len(points) // 2
    before = mean(points[:midpoint])
    after = mean(points[midpoint:])
    scale = max(abs(before), 1e-12)
    shift = abs(after - before) / scale
    detected = shift >= float(minimum_relative_shift)
    return artifact(
        "structural-break",
        {"detected": detected, "relative_shift": shift, "split": midpoint},
    )


def infer_market_regime(
    returns: Sequence[float],
) -> ResearchArtifact:
    values = tuple(float(value) for value in returns)
    if len(values) < 3:
        regime = "unknown"
        disposition = Disposition.UNKNOWN
    else:
        drift = mean(values)
        volatility = variance(values) ** 0.5
        if volatility == 0.0:
            regime = "quiet"
        elif abs(drift) > volatility:
            regime = "directional"
        elif volatility > abs(drift) * 4:
            regime = "volatile"
        else:
            regime = "mixed"
        disposition = Disposition.PASS
    return artifact(
        "market-regime",
        {"regime": regime, "known_at_decision_time": True},
        disposition=disposition,
        reason="regime-inferred" if regime != "unknown" else "unknown-regime",
    )


def route_policy_by_regime(
    regime: ResearchArtifact,
    policies: Mapping[str, str],
) -> ResearchArtifact:
    name = str(regime.payload["regime"])
    policy = policies.get(name, "no-trade")
    known = name != "unknown" and name in policies
    return artifact(
        "regime-policy-route",
        {"regime": name, "policy": policy, "fallback": not known},
        disposition=Disposition.PASS if known else Disposition.BLOCKED,
        reason="qualified-regime-policy" if known else "unknown-regime-no-trade",
    )


def archive_regime_transition(
    previous: ResearchArtifact,
    current: ResearchArtifact,
) -> ResearchArtifact:
    return artifact(
        "regime-transition",
        {
            "previous": previous.identity,
            "current": current.identity,
            "previous_regime": previous.payload["regime"],
            "current_regime": current.payload["regime"],
            "history_rewritten": False,
        },
    )


__all__ = [
    "archive_regime_transition",
    "detect_structural_break",
    "infer_market_regime",
    "route_policy_by_regime",
]
