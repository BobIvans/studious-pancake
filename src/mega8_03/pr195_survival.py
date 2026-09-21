"""PR-195 / SURV-01 — censored opportunity duration analysis."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .common import (
    PPM,
    AdvisoryModel,
    advisory_model,
    bounded_probability_ppm,
    integer,
    require_rows,
)


def fit_kaplan_meier_survival(
    durations_ns: Sequence[int],
    observed_events: Sequence[bool],
) -> AdvisoryModel:
    if len(durations_ns) != len(observed_events) or not durations_ns:
        raise ValueError("durations and event flags must be equally non-empty")
    rows = sorted(
        (
            integer(duration, "duration_ns", minimum=1),
            bool(event),
        )
        for duration, event in zip(durations_ns, observed_events, strict=True)
    )
    at_risk = len(rows)
    survival_ppm = PPM
    curve: list[tuple[int, int, int]] = []
    for duration in sorted({item[0] for item in rows}):
        events = sum(d == duration and event for d, event in rows)
        censored = sum(d == duration and not event for d, event in rows)
        if events:
            survival_ppm = survival_ppm * (at_risk - events) // at_risk
            curve.append((duration, survival_ppm, at_risk))
        at_risk -= events + censored
    return advisory_model(
        "mega8-03-survival-km",
        "kaplan-meier",
        {
            "curve": curve,
            "sample_count": len(rows),
            "event_count": sum(observed_events),
            "censored_count": len(rows) - sum(observed_events),
        },
        calibrated=True,
        holdout_verified=False,
    )


def fit_parametric_edge_duration(
    durations_ns: Sequence[int],
    observed_events: Sequence[bool],
) -> AdvisoryModel:
    if len(durations_ns) != len(observed_events) or not durations_ns:
        raise ValueError("durations and event flags must be equally non-empty")
    exposure = sum(integer(value, "duration_ns", minimum=1) for value in durations_ns)
    events = sum(bool(value) for value in observed_events)
    median_ns = None if events == 0 else int(math.log(2) * exposure / events)
    return advisory_model(
        "mega8-03-survival-exponential",
        "exponential-duration",
        {
            "event_count": events,
            "total_exposure_ns": exposure,
            "median_duration_ns": median_ns,
        },
        calibrated=events > 0,
        holdout_verified=False,
    )


def handle_censored_opportunities(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    require_rows(rows, "opportunities")
    right_censored = 0
    observed = 0
    total_exposure = 0
    for row in rows:
        total_exposure += integer(row.get("duration_ns"), "duration_ns", minimum=1)
        if row.get("event_observed") is True:
            observed += 1
        else:
            right_censored += 1
    return {
        "sample_count": len(rows),
        "observed_event_count": observed,
        "right_censored_count": right_censored,
        "censoring_share_ppm": bounded_probability_ppm(right_censored, len(rows)),
        "total_exposure_ns": total_exposure,
    }


def calibrate_duration_predictions(
    predicted_ns: Sequence[int],
    observed_ns: Sequence[int],
    censored: Sequence[bool],
) -> dict[str, int | None]:
    if not predicted_ns or not (
        len(predicted_ns) == len(observed_ns) == len(censored)
    ):
        raise ValueError("prediction calibration arrays must align")
    errors: list[int] = []
    censored_covered = 0
    censored_total = 0
    for predicted, observed, is_censored in zip(
        predicted_ns, observed_ns, censored, strict=True
    ):
        p = integer(predicted, "predicted_ns", minimum=0)
        o = integer(observed, "observed_ns", minimum=0)
        if is_censored:
            censored_total += 1
            censored_covered += p >= o
        else:
            errors.append(abs(p - o))
    return {
        "uncensored_mae_ns": None if not errors else sum(errors) // len(errors),
        "censored_lower_bound_coverage_ppm": (
            None
            if censored_total == 0
            else bounded_probability_ppm(censored_covered, censored_total)
        ),
    }


__all__ = [
    "calibrate_duration_predictions",
    "fit_kaplan_meier_survival",
    "fit_parametric_edge_duration",
    "handle_censored_opportunities",
]
