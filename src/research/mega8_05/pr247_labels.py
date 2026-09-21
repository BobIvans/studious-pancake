"""PR-247 / LABEL-01: selective-observation and missingness labels."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from .base import ResearchArtifact, artifact, finite_number, probability


_ALLOWED = {
    "observed",
    "simulated",
    "skipped",
    "censored",
    "quota-exhausted",
    "provider-gap",
    "unavailable",
}


def model_observation_selection(
    rows: Iterable[Mapping[str, Any]],
) -> ResearchArtifact:
    rows_tuple = tuple(rows)
    if not rows_tuple:
        raise ValueError("rows cannot be empty")
    selected = sum(bool(row.get("selected")) for row in rows_tuple)
    return artifact(
        "observation-selection",
        {
            "observations": len(rows_tuple),
            "selected": selected,
            "selection_rate": selected / len(rows_tuple),
        },
    )


def label_missingness_mechanism(reason: str) -> ResearchArtifact:
    normalized = reason.strip().lower()
    if normalized not in _ALLOWED:
        normalized = "unavailable"
    category = {
        "quota-exhausted": "resource-censoring",
        "provider-gap": "source-missingness",
        "censored": "right-censoring",
        "skipped": "policy-selection",
    }.get(normalized, "observed-or-unavailable")
    return artifact(
        "missingness-label",
        {"reason": normalized, "mechanism": category},
    )


def weight_selective_samples(
    selection_probabilities: Iterable[float],
    *,
    max_weight: float = 20.0,
) -> ResearchArtifact:
    cap = finite_number(max_weight, "max_weight")
    if cap < 1.0:
        raise ValueError("max_weight must be at least one")
    weights = []
    for value in selection_probabilities:
        probability_value = probability(value, "selection_probability")
        if probability_value <= 0.0:
            weights.append(cap)
        else:
            weights.append(min(cap, 1.0 / probability_value))
    if not weights:
        raise ValueError("selection probabilities cannot be empty")
    return artifact(
        "selection-weights",
        {
            "weights": tuple(weights),
            "max_weight": cap,
            "clipped": sum(weight >= cap for weight in weights),
        },
    )


def audit_selection_bias(
    labels: Iterable[str],
    weights: ResearchArtifact,
) -> ResearchArtifact:
    counts = Counter(labels)
    return artifact(
        "selection-bias-audit",
        {
            "label_counts": dict(sorted(counts.items())),
            "weights": weights.identity,
            "unsupported_regions": tuple(
                sorted(label for label, count in counts.items() if count < 2)
            ),
            "landing_label_for_unsent_allowed": False,
        },
    )


__all__ = [
    "audit_selection_bias",
    "label_missingness_mechanism",
    "model_observation_selection",
    "weight_selective_samples",
]
