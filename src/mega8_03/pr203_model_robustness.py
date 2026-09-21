"""PR-203 / ROBUST-01 — adversarial model/data qualification."""

from __future__ import annotations

from typing import Mapping, Sequence

from .common import PPM, integer, mean_int


def generate_adversarial_features(
    features: Mapping[str, int],
    *,
    perturbation_ppm: int,
) -> tuple[dict[str, int], dict[str, int]]:
    perturb = integer(perturbation_ppm, "perturbation_ppm", minimum=0)
    up: dict[str, int] = {}
    down: dict[str, int] = {}
    for key, value in sorted(features.items()):
        base = integer(value, f"feature:{key}")
        delta = abs(base) * perturb // PPM
        up[key] = base + delta
        down[key] = base - delta
    return down, up


def test_model_data_poisoning(
    clean_scores_ppm: Sequence[int],
    poisoned_scores_ppm: Sequence[int],
) -> dict[str, int]:
    if not clean_scores_ppm or len(clean_scores_ppm) != len(poisoned_scores_ppm):
        raise ValueError("clean/poisoned scores must align")
    deltas = [
        abs(integer(clean, "clean_score") - integer(poisoned, "poisoned_score"))
        for clean, poisoned in zip(clean_scores_ppm, poisoned_scores_ppm, strict=True)
    ]
    return {
        "mean_score_shift_ppm": mean_int(deltas),
        "max_score_shift_ppm": max(deltas),
    }


def detect_distribution_attack(
    baseline_features: Sequence[int],
    current_features: Sequence[int],
) -> dict[str, int]:
    if not baseline_features or not current_features:
        raise ValueError("baseline/current features are required")
    baseline = mean_int([integer(v, "baseline_feature") for v in baseline_features])
    current = mean_int([integer(v, "current_feature") for v in current_features])
    denominator = max(1, abs(baseline))
    return {"mean_shift_ppm": abs(current - baseline) * PPM // denominator}


def quarantine_unsafe_model(
    *,
    poisoning_shift_ppm: int,
    distribution_shift_ppm: int,
    maximum_poisoning_shift_ppm: int,
    maximum_distribution_shift_ppm: int,
) -> dict[str, object]:
    reasons: list[str] = []
    if integer(poisoning_shift_ppm, "poisoning_shift_ppm", minimum=0) > integer(
        maximum_poisoning_shift_ppm, "maximum_poisoning_shift_ppm", minimum=0
    ):
        reasons.append("MODEL_POISONING_SENSITIVITY_EXCEEDED")
    if integer(distribution_shift_ppm, "distribution_shift_ppm", minimum=0) > integer(
        maximum_distribution_shift_ppm, "maximum_distribution_shift_ppm", minimum=0
    ):
        reasons.append("MODEL_DISTRIBUTION_ATTACK_SUSPECTED")
    return {
        "quarantined": bool(reasons),
        "reason_codes": tuple(reasons),
        "execution_authority": False,
    }


__all__ = [
    "detect_distribution_attack",
    "generate_adversarial_features",
    "quarantine_unsafe_model",
    "test_model_data_poisoning",
]
