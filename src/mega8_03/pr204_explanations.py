"""PR-204 / EXPLAIN-01 — stable advisory reasons bound to immutable evidence."""

from __future__ import annotations

from typing import Mapping, Sequence

from .common import PPM, integer, mean_int, require_sha256


def compute_local_feature_attribution(
    weights_ppm: Mapping[str, int],
    feature_values: Mapping[str, int],
) -> dict[str, int]:
    if set(weights_ppm) != set(feature_values):
        raise ValueError("weights/features must have identical keys")
    return {
        key: integer(weights_ppm[key], f"weight:{key}")
        * integer(feature_values[key], f"feature:{key}")
        // PPM
        for key in sorted(weights_ppm)
    }


def emit_human_reason_code(
    attributions: Mapping[str, int],
    *,
    limit: int = 3,
) -> tuple[str, ...]:
    count = integer(limit, "limit", minimum=1)
    ranked = sorted(
        attributions.items(),
        key=lambda item: (-abs(integer(item[1], "attribution")), item[0]),
    )
    return tuple(
        f"MODEL_FEATURE_{key.upper().replace('-', '_')}_{'POS' if value >= 0 else 'NEG'}"
        for key, value in ranked[:count]
    )


def trace_model_to_evidence(
    feature_names: Sequence[str],
    evidence_by_feature: Mapping[str, str],
) -> dict[str, str]:
    trace: dict[str, str] = {}
    for feature in feature_names:
        digest = evidence_by_feature.get(feature)
        if digest is None:
            raise ValueError(f"missing evidence for feature {feature}")
        trace[str(feature)] = require_sha256(digest, f"evidence:{feature}")
    return trace


def audit_explanation_stability(
    attribution_runs: Sequence[Mapping[str, int]],
    *,
    maximum_mean_delta: int,
) -> dict[str, int | bool]:
    if len(attribution_runs) < 2:
        raise ValueError("at least two attribution runs are required")
    keys = set(attribution_runs[0])
    if any(set(run) != keys for run in attribution_runs):
        raise ValueError("attribution feature sets must match")
    deltas: list[int] = []
    for key in sorted(keys):
        values = [integer(run[key], f"attribution:{key}") for run in attribution_runs]
        center = mean_int(values)
        deltas.extend(abs(value - center) for value in values)
    mean_delta = mean_int(deltas)
    cap = integer(maximum_mean_delta, "maximum_mean_delta", minimum=0)
    return {"mean_attribution_delta": mean_delta, "stable": mean_delta <= cap}


__all__ = [
    "audit_explanation_stability",
    "compute_local_feature_attribution",
    "emit_human_reason_code",
    "trace_model_to_evidence",
]
