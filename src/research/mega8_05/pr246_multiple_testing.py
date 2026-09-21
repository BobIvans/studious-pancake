"""PR-246 / EXPERIMENT-02: multiple-testing and false-discovery controls."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from .base import Disposition, ResearchArtifact, artifact, probability


def enumerate_hypothesis_family(
    hypotheses: Iterable[str],
    *,
    exclusions: Iterable[str] = (),
) -> ResearchArtifact:
    family = tuple(sorted(set(hypotheses)))
    excluded = tuple(sorted(set(exclusions)))
    if not family:
        raise ValueError("hypothesis family cannot be empty")
    return artifact(
        "hypothesis-family",
        {
            "hypotheses": family,
            "exclusions": excluded,
            "denominator": len(family),
        },
    )


def apply_multiple_test_correction(
    pvalues: Mapping[str, float],
    *,
    method: str = "benjamini-hochberg",
) -> ResearchArtifact:
    if not pvalues:
        raise ValueError("pvalues cannot be empty")
    checked = {
        key: probability(value, f"pvalue:{key}") for key, value in pvalues.items()
    }
    method_key = method.lower()
    if method_key == "bonferroni":
        adjusted = {
            key: min(1.0, value * len(checked)) for key, value in checked.items()
        }
    elif method_key == "benjamini-hochberg":
        ordered = sorted(checked.items(), key=lambda item: (item[1], item[0]))
        raw: dict[str, float] = {}
        count = len(ordered)
        for rank, (key, value) in enumerate(ordered, start=1):
            raw[key] = min(1.0, value * count / rank)
        adjusted = {}
        running = 1.0
        for key, _ in reversed(ordered):
            running = min(running, raw[key])
            adjusted[key] = running
    else:
        raise ValueError("unsupported correction method")
    return artifact(
        "multiple-test-correction",
        {
            "method": method_key,
            "adjusted_pvalues": {key: adjusted[key] for key in sorted(adjusted)},
            "tested_count": len(checked),
        },
    )


def estimate_false_discovery_rate(
    correction: ResearchArtifact,
    *,
    alpha: float,
) -> ResearchArtifact:
    threshold = probability(alpha, "alpha")
    adjusted = correction.payload["adjusted_pvalues"]
    discoveries = tuple(
        sorted(key for key, value in adjusted.items() if float(value) <= threshold)
    )
    estimated = len(discoveries) / max(1, len(adjusted))
    return artifact(
        "false-discovery-summary",
        {
            "alpha": threshold,
            "discoveries": discoveries,
            "discovery_fraction": estimated,
        },
    )


def gate_discovery_claim(
    correction: ResearchArtifact,
    hypothesis_id: str,
    *,
    alpha: float,
    economic_effect_positive: bool,
    executable_evidence_present: bool,
) -> ResearchArtifact:
    adjusted = correction.payload["adjusted_pvalues"]
    if hypothesis_id not in adjusted:
        raise ValueError("hypothesis is outside corrected family")
    passed = (
        float(adjusted[hypothesis_id]) <= probability(alpha, "alpha")
        and bool(economic_effect_positive)
        and bool(executable_evidence_present)
    )
    return artifact(
        "discovery-claim-gate",
        {
            "hypothesis_id": hypothesis_id,
            "adjusted_pvalue": float(adjusted[hypothesis_id]),
            "economic_effect_positive": bool(economic_effect_positive),
            "executable_evidence_present": bool(executable_evidence_present),
        },
        disposition=Disposition.PASS if passed else Disposition.BLOCKED,
        reason="corrected-claim-supported" if passed else "claim-not-promotable",
    )


__all__ = [
    "apply_multiple_test_correction",
    "enumerate_hypothesis_family",
    "estimate_false_discovery_rate",
    "gate_discovery_claim",
]
