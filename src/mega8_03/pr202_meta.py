"""PR-202 / META-01 — cross-market representation experiments."""

from __future__ import annotations

from typing import Sequence

from .common import PPM, AdvisoryModel, advisory_model, integer, mean_int


def learn_cross_market_representation(
    feature_rows: Sequence[Sequence[int]],
) -> AdvisoryModel:
    if not feature_rows:
        raise ValueError("feature rows are required")
    width = len(feature_rows[0])
    if width == 0 or any(len(row) != width for row in feature_rows):
        raise ValueError("feature width must be stable")
    means = [
        mean_int([integer(row[i], "feature") for row in feature_rows])
        for i in range(width)
    ]
    scales = [
        max(
            1,
            mean_int(
                [abs(integer(row[i], "feature") - means[i]) for row in feature_rows]
            ),
        )
        for i in range(width)
    ]
    return advisory_model(
        "mega8-03-cross-market",
        "cross-market-standardized-representation",
        {"means": means, "scales": scales, "sample_count": len(feature_rows)},
        calibrated=True,
        holdout_verified=False,
    )


def adapt_model_to_new_venue(
    representation: AdvisoryModel,
    target_rows: Sequence[Sequence[int]],
) -> AdvisoryModel:
    if not target_rows:
        raise ValueError("target rows are required")
    source_means = list(representation.parameters["means"])
    target_means = [
        mean_int([integer(row[i], "feature") for row in target_rows])
        for i in range(len(source_means))
    ]
    shift = [
        target - source
        for source, target in zip(source_means, target_means, strict=True)
    ]
    return advisory_model(
        "mega8-03-adapted-venue",
        "venue-adaptation",
        {"source_model": representation.evidence_sha256, "mean_shift": shift},
        calibrated=False,
        holdout_verified=False,
    )


def measure_transfer_gain(
    *,
    baseline_loss_ppm: int,
    transferred_loss_ppm: int,
) -> int:
    baseline = integer(baseline_loss_ppm, "baseline_loss_ppm", minimum=1)
    transferred = integer(transferred_loss_ppm, "transferred_loss_ppm", minimum=0)
    return (baseline - transferred) * PPM // baseline


def prevent_negative_transfer(
    *,
    transfer_gain_ppm: int,
    minimum_gain_ppm: int = 0,
) -> dict[str, int | bool]:
    gain = integer(transfer_gain_ppm, "transfer_gain_ppm")
    minimum = integer(minimum_gain_ppm, "minimum_gain_ppm")
    return {"transfer_allowed": gain >= minimum, "transfer_gain_ppm": gain}


__all__ = [
    "adapt_model_to_new_venue",
    "learn_cross_market_representation",
    "measure_transfer_gain",
    "prevent_negative_transfer",
]
