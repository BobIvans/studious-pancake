"""Deterministic PR-355 research-quality protocol helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .evidence_native_core import (
    EvidenceNativeError,
    record,
    require_int,
    require_ppm,
    require_text,
)


@dataclass(frozen=True, slots=True)
class ResearchEpisode:
    episode_id: str
    feature_available_at: int
    label_available_at: int
    feature_atoms: int
    label_atoms: int

    def __post_init__(self) -> None:
        require_text(self.episode_id, "episode_id")
        feature_at = require_int(
            self.feature_available_at,
            "feature_available_at",
            minimum=0,
        )
        label_at = require_int(
            self.label_available_at,
            "label_available_at",
            minimum=0,
        )
        if label_at <= feature_at:
            raise EvidenceNativeError("EPISODE_LABEL_NOT_AFTER_FEATURE")
        require_int(self.feature_atoms, "feature_atoms")
        require_int(self.label_atoms, "label_atoms")


def form_independent_episodes(
    rows: Sequence[Mapping[str, int | str]],
    *,
    minimum_gap: int,
) -> tuple[ResearchEpisode, ...]:
    gap = require_int(minimum_gap, "minimum_gap", minimum=0)
    episodes: list[ResearchEpisode] = []
    last_feature_at: int | None = None
    for row in sorted(
        rows,
        key=lambda item: int(item["feature_available_at"]),
    ):
        feature_at = require_int(
            row.get("feature_available_at"),
            "feature_available_at",
            minimum=0,
        )
        if last_feature_at is not None and feature_at - last_feature_at < gap:
            continue
        episode = ResearchEpisode(
            episode_id=require_text(row.get("episode_id"), "episode_id"),
            feature_available_at=feature_at,
            label_available_at=require_int(
                row.get("label_available_at"),
                "label_available_at",
                minimum=0,
            ),
            feature_atoms=require_int(
                row.get("feature_atoms"),
                "feature_atoms",
            ),
            label_atoms=require_int(
                row.get("label_atoms"),
                "label_atoms",
            ),
        )
        episodes.append(episode)
        last_feature_at = feature_at
    if not episodes:
        raise EvidenceNativeError("INDEPENDENT_EPISODE_SET_EMPTY")
    return tuple(episodes)


def purged_walk_forward_split(
    episodes: Sequence[ResearchEpisode],
    *,
    train_end: int,
    embargo: int,
) -> Mapping[str, object]:
    cutoff = require_int(train_end, "train_end", minimum=0)
    embargo_value = require_int(embargo, "embargo", minimum=0)
    train = tuple(
        item for item in episodes if item.label_available_at <= cutoff
    )
    holdout = tuple(
        item
        for item in episodes
        if item.feature_available_at > cutoff + embargo_value
    )
    if not train or not holdout:
        raise EvidenceNativeError("PURGED_WALK_FORWARD_SPLIT_EMPTY")
    if any(item.label_available_at > cutoff for item in train):
        raise EvidenceNativeError("TRAINING_LABEL_LEAKAGE")
    return {
        "train": train,
        "holdout": holdout,
        "train_end": cutoff,
        "embargo": embargo_value,
    }


def _mae(labels: Sequence[int], prediction: int) -> int:
    if not labels:
        raise EvidenceNativeError("MODEL_LABELS_REQUIRED")
    return sum(abs(value - prediction) for value in labels) // len(labels)


def compare_four_model_variants(
    *,
    train_labels: Sequence[int],
    pooled_labels: Sequence[int],
    holdout_labels: Sequence[int],
    mechanism_prediction_atoms: int,
) -> Mapping[str, object]:
    train = tuple(
        require_int(value, "train_label") for value in train_labels
    )
    pooled = tuple(
        require_int(value, "pooled_label") for value in pooled_labels
    )
    holdout = tuple(
        require_int(value, "holdout_label") for value in holdout_labels
    )
    if not train or not pooled or not holdout:
        raise EvidenceNativeError("MODEL_COMPARATOR_DATA_REQUIRED")

    simple_prediction = 0
    local_prediction = sum(train) // len(train)
    pooled_prediction = sum((*train, *pooled)) // (
        len(train) + len(pooled)
    )
    mechanism_prediction = require_int(
        mechanism_prediction_atoms,
        "mechanism_prediction_atoms",
    )
    metrics = {
        "simple_baseline_mae_atoms": _mae(
            holdout,
            simple_prediction,
        ),
        "local_only_mae_atoms": _mae(
            holdout,
            local_prediction,
        ),
        "pooled_markets_mae_atoms": _mae(
            holdout,
            pooled_prediction,
        ),
        "mechanism_transfer_mae_atoms": _mae(
            holdout,
            mechanism_prediction,
        ),
    }
    best = min(metrics, key=lambda name: metrics[name])
    return record(
        "compare_four_model_variants",
        {
            **metrics,
            "best_variant": best,
            "negative_transfer": (
                metrics["mechanism_transfer_mae_atoms"]
                >= metrics["local_only_mae_atoms"]
            ),
        },
    )


def benjamini_hochberg_ppm(
    p_values_ppm: Sequence[int],
    *,
    fdr_ppm: int,
) -> Mapping[str, object]:
    alpha = require_ppm(fdr_ppm, "fdr_ppm")
    indexed = sorted(
        (
            (index, require_ppm(value, "p_value_ppm"))
            for index, value in enumerate(p_values_ppm)
        ),
        key=lambda item: item[1],
    )
    if not indexed:
        raise EvidenceNativeError("P_VALUE_SET_REQUIRED")
    accepted: list[int] = []
    total = len(indexed)
    for rank, (original_index, p_value) in enumerate(indexed, start=1):
        threshold = alpha * rank // total
        if p_value <= threshold:
            accepted.append(original_index)
    return record(
        "benjamini_hochberg_ppm",
        {
            "fdr_ppm": alpha,
            "accepted_indices": tuple(sorted(accepted)),
            "test_count": total,
        },
    )


def evaluate_probability_calibration(
    rows: Sequence[Mapping[str, int]],
) -> Mapping[str, object]:
    if not rows:
        raise EvidenceNativeError("CALIBRATION_ROWS_REQUIRED")
    absolute_errors: list[int] = []
    covered = 0
    for row in rows:
        probability = require_ppm(
            row.get("probability_ppm"),
            "probability_ppm",
        )
        outcome = require_int(
            row.get("outcome"),
            "outcome",
            minimum=0,
        )
        if outcome not in {0, 1}:
            raise EvidenceNativeError(
                "CALIBRATION_OUTCOME_BINARY_REQUIRED"
            )
        target = outcome * 1_000_000
        absolute_errors.append(abs(probability - target))
        lower = require_ppm(
            row.get("interval_low_ppm"),
            "interval_low_ppm",
        )
        upper = require_ppm(
            row.get("interval_high_ppm"),
            "interval_high_ppm",
        )
        if upper < lower:
            raise EvidenceNativeError("CALIBRATION_INTERVAL_INVERTED")
        if lower <= target <= upper:
            covered += 1
    return record(
        "evaluate_probability_calibration",
        {
            "mean_absolute_calibration_error_ppm": (
                sum(absolute_errors) // len(absolute_errors)
            ),
            "interval_coverage_ppm": (
                covered * 1_000_000 // len(rows)
            ),
            "row_count": len(rows),
        },
    )


def run_equal_budget_ablation(
    *,
    baseline_utility_units: int,
    challenger_utility_units: int,
    baseline_cost_units: int,
    challenger_cost_units: int,
    budget_units: int,
) -> Mapping[str, object]:
    budget = require_int(
        budget_units,
        "budget_units",
        minimum=0,
    )
    baseline_cost = require_int(
        baseline_cost_units,
        "baseline_cost_units",
        minimum=0,
    )
    challenger_cost = require_int(
        challenger_cost_units,
        "challenger_cost_units",
        minimum=0,
    )
    if baseline_cost > budget or challenger_cost > budget:
        raise EvidenceNativeError(
            "EQUAL_BUDGET_ABLATION_BUDGET_EXCEEDED"
        )
    baseline_utility = require_int(
        baseline_utility_units,
        "baseline_utility_units",
    )
    challenger_utility = require_int(
        challenger_utility_units,
        "challenger_utility_units",
    )
    return record(
        "run_equal_budget_ablation",
        {
            "budget_units": budget,
            "baseline_cost_units": baseline_cost,
            "challenger_cost_units": challenger_cost,
            "baseline_utility_units": baseline_utility,
            "challenger_utility_units": challenger_utility,
            "utility_delta_units": (
                challenger_utility - baseline_utility
            ),
        },
    )


def evaluate_null_control(
    *,
    observed_metric_atoms: int,
    null_metric_atoms: int,
    minimum_effect_atoms: int,
) -> Mapping[str, object]:
    observed = require_int(
        observed_metric_atoms,
        "observed_metric_atoms",
    )
    null = require_int(
        null_metric_atoms,
        "null_metric_atoms",
    )
    minimum = require_int(
        minimum_effect_atoms,
        "minimum_effect_atoms",
        minimum=0,
    )
    delta = observed - null
    return record(
        "evaluate_null_control",
        {
            "observed_metric_atoms": observed,
            "null_metric_atoms": null,
            "effect_delta_atoms": delta,
            "minimum_effect_atoms": minimum,
            "null_rejected": abs(delta) >= minimum,
        },
    )


def evaluate_detection_coverage(
    *,
    false_discoveries: int,
    discoveries: int,
    false_negatives: int,
    positives: int,
    observable_cells: int,
    covered_cells: int,
) -> Mapping[str, object]:
    fp = require_int(
        false_discoveries,
        "false_discoveries",
        minimum=0,
    )
    discovered = require_int(
        discoveries,
        "discoveries",
        minimum=0,
    )
    fn = require_int(
        false_negatives,
        "false_negatives",
        minimum=0,
    )
    positive = require_int(
        positives,
        "positives",
        minimum=0,
    )
    observable = require_int(
        observable_cells,
        "observable_cells",
        minimum=1,
    )
    covered = require_int(
        covered_cells,
        "covered_cells",
        minimum=0,
    )
    if fp > discovered or fn > positive or covered > observable:
        raise EvidenceNativeError(
            "DETECTION_COVERAGE_COUNTS_INVALID"
        )
    return record(
        "evaluate_detection_coverage",
        {
            "fdr_ppm": fp * 1_000_000 // max(1, discovered),
            "fnr_ppm": fn * 1_000_000 // max(1, positive),
            "observable_miss_ppm": (
                (observable - covered) * 1_000_000
                // observable
            ),
            "observable_cells": observable,
            "covered_cells": covered,
        },
    )


def source_value_report(
    *,
    qualified_candidates: int,
    engineering_cost_units: int,
    data_cost_units: int,
    license_cost_units: int,
    source_failures: int,
) -> Mapping[str, object]:
    qualified = require_int(
        qualified_candidates,
        "qualified_candidates",
        minimum=0,
    )
    engineering = require_int(
        engineering_cost_units,
        "engineering_cost_units",
        minimum=0,
    )
    data = require_int(
        data_cost_units,
        "data_cost_units",
        minimum=0,
    )
    license_cost = require_int(
        license_cost_units,
        "license_cost_units",
        minimum=0,
    )
    failures = require_int(
        source_failures,
        "source_failures",
        minimum=0,
    )
    total_cost = engineering + data + license_cost
    return record(
        "source_value_report",
        {
            "qualified_candidates": qualified,
            "total_cost_units": total_cost,
            "source_failures": failures,
            "qualified_per_cost_ppm": (
                qualified * 1_000_000 // max(1, total_cost)
            ),
            "blind_spot": failures > 0,
        },
    )


__all__ = [
    "ResearchEpisode",
    "benjamini_hochberg_ppm",
    "compare_four_model_variants",
    "evaluate_detection_coverage",
    "evaluate_null_control",
    "evaluate_probability_calibration",
    "form_independent_episodes",
    "purged_walk_forward_split",
    "run_equal_budget_ablation",
    "source_value_report",
]
