"""PR-198 / HAWKES-01 — bounded exponential-kernel event-intensity research."""

from __future__ import annotations

import math
from typing import Sequence

from .common import PPM, AdvisoryModel, advisory_model, integer


def fit_hawkes_event_model(
    event_times_ns: Sequence[int],
    *,
    observation_horizon_ns: int,
) -> AdvisoryModel:
    horizon = integer(observation_horizon_ns, "observation_horizon_ns", minimum=1)
    times = sorted(
        integer(value, "event_time_ns", minimum=0) for value in event_times_ns
    )
    if not times:
        raise ValueError("event times are required")
    if times[-1] > horizon:
        raise ValueError("event lies outside observation horizon")
    intervals = [right - left for left, right in zip(times, times[1:])]
    positive = [value for value in intervals if value > 0]
    median_gap = sorted(positive)[len(positive) // 2] if positive else horizon
    short = sum(value <= median_gap for value in positive)
    branching_ppm = (
        0 if not positive else min(900_000, short * 500_000 // len(positive))
    )
    return advisory_model(
        "mega8-03-hawkes",
        "exponential-kernel-intensity",
        {
            "event_count": len(times),
            "horizon_ns": horizon,
            "baseline_events_per_horizon_ppm": len(times) * PPM,
            "kernel_half_life_ns": max(1, median_gap),
            "branching_ratio_ppm": branching_ppm,
        },
        calibrated=True,
        holdout_verified=False,
    )


def estimate_cross_venue_excitation(
    source_times_ns: Sequence[int],
    target_times_ns: Sequence[int],
    *,
    window_ns: int,
) -> dict[str, int]:
    window = integer(window_ns, "window_ns", minimum=1)
    sources = sorted(
        integer(value, "source_time_ns", minimum=0) for value in source_times_ns
    )
    targets = sorted(
        integer(value, "target_time_ns", minimum=0) for value in target_times_ns
    )
    if not sources:
        raise ValueError("source events are required")
    excited = sum(
        any(source < target <= source + window for target in targets)
        for source in sources
    )
    return {
        "source_count": len(sources),
        "excited_share_ppm": excited * PPM // len(sources),
    }


def forecast_event_intensity(
    model: AdvisoryModel,
    *,
    elapsed_since_last_event_ns: int,
) -> dict[str, int]:
    elapsed = integer(
        elapsed_since_last_event_ns, "elapsed_since_last_event_ns", minimum=0
    )
    params = model.parameters
    half_life = integer(params["kernel_half_life_ns"], "kernel_half_life_ns", minimum=1)
    branch = integer(params["branching_ratio_ppm"], "branching_ratio_ppm", minimum=0)
    decay = math.exp(-math.log(2) * elapsed / half_life)
    return {
        "relative_intensity_ppm": PPM + int(branch * decay),
        "elapsed_since_last_event_ns": elapsed,
    }


def validate_intensity_gain(
    *,
    model_log_loss_ppm: int,
    baseline_log_loss_ppm: int,
    minimum_gain_ppm: int,
) -> dict[str, int | bool]:
    model = integer(model_log_loss_ppm, "model_log_loss_ppm", minimum=0)
    baseline = integer(baseline_log_loss_ppm, "baseline_log_loss_ppm", minimum=1)
    gain = (baseline - model) * PPM // baseline
    return {
        "relative_gain_ppm": gain,
        "holdout_gain_verified": gain >= integer(minimum_gain_ppm, "minimum_gain_ppm"),
    }


__all__ = [
    "estimate_cross_venue_excitation",
    "fit_hawkes_event_model",
    "forecast_event_intensity",
    "validate_intensity_gain",
]
