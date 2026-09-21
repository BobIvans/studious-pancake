"""PR-196 / UQ-01 — distribution-free integer uncertainty envelopes."""

from __future__ import annotations

from typing import Sequence

from .common import PPM, integer, ppm, quantile_int


def fit_conformal_net_interval(
    calibration_errors_atomic: Sequence[int],
    *,
    miscoverage_ppm: int,
) -> dict[str, int]:
    alpha = ppm(miscoverage_ppm, "miscoverage_ppm")
    if alpha >= PPM:
        raise ValueError("miscoverage must be below 1.0")
    absolute = [abs(integer(value, "calibration_error_atomic")) for value in calibration_errors_atomic]
    radius = quantile_int(absolute, PPM - alpha)
    return {
        "radius_atomic": radius,
        "miscoverage_ppm": alpha,
        "calibration_count": len(absolute),
    }


def fit_conformal_latency_interval(
    calibration_errors_ns: Sequence[int],
    *,
    miscoverage_ppm: int,
) -> dict[str, int]:
    alpha = ppm(miscoverage_ppm, "miscoverage_ppm")
    if alpha >= PPM:
        raise ValueError("miscoverage must be below 1.0")
    absolute = [abs(integer(value, "calibration_error_ns")) for value in calibration_errors_ns]
    radius = quantile_int(absolute, PPM - alpha)
    return {
        "radius_ns": radius,
        "miscoverage_ppm": alpha,
        "calibration_count": len(absolute),
    }


def compute_prediction_set(
    *,
    point_estimate: int,
    radius: int,
    lower_floor: int | None = None,
) -> tuple[int, int]:
    point = integer(point_estimate, "point_estimate")
    width = integer(radius, "radius", minimum=0)
    lower = point - width
    if lower_floor is not None:
        lower = max(lower, integer(lower_floor, "lower_floor"))
    return lower, point + width


def gate_on_uncertainty_budget(
    *,
    conservative_net_interval: tuple[int, int],
    latency_interval_ns: tuple[int, int],
    minimum_net_atomic: int,
    maximum_latency_ns: int,
) -> dict[str, object]:
    net_low, net_high = conservative_net_interval
    latency_low, latency_high = latency_interval_ns
    for value, field in (
        (net_low, "net_low"),
        (net_high, "net_high"),
        (latency_low, "latency_low"),
        (latency_high, "latency_high"),
    ):
        integer(value, field)
    reasons: list[str] = []
    if net_low <= integer(minimum_net_atomic, "minimum_net_atomic"):
        reasons.append("NET_UNCERTAINTY_TOO_HIGH")
    if latency_high > integer(maximum_latency_ns, "maximum_latency_ns", minimum=0):
        reasons.append("LATENCY_UNCERTAINTY_TOO_HIGH")
    return {"admitted_offline": not reasons, "reason_codes": tuple(reasons)}


__all__ = [
    "compute_prediction_set",
    "fit_conformal_latency_interval",
    "fit_conformal_net_interval",
    "gate_on_uncertainty_budget",
]
