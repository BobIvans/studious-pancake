"""PR-168 / PREDICT-01: calibrated resource envelopes."""

from __future__ import annotations
from typing import Sequence
from .core import Mega802Error, ResourceEnvelope, require_nonnegative_int


def _upper(samples: Sequence[int]) -> int:
    if not samples:
        raise Mega802Error("RESOURCE_SAMPLES_REQUIRED")
    values = sorted(require_nonnegative_int(v, "sample") for v in samples)
    return values[min(len(values) - 1, (9 * len(values)) // 10)]


def predict_compute_units(samples: Sequence[int], *, safety_ppm: int = 100_000) -> int:
    base = _upper(samples)
    require_nonnegative_int(safety_ppm, "safety_ppm")
    return base + base * safety_ppm // 1_000_000


def predict_account_metas(samples: Sequence[int], *, reserve: int = 2) -> int:
    return _upper(samples) + require_nonnegative_int(reserve, "reserve")


def predict_message_bytes(samples: Sequence[int], *, reserve: int = 32) -> int:
    return _upper(samples) + require_nonnegative_int(reserve, "reserve")


def calibrate_resource_predictor(
    compute_samples: Sequence[int],
    account_samples: Sequence[int],
    message_samples: Sequence[int],
) -> ResourceEnvelope:
    return ResourceEnvelope(
        compute_units=predict_compute_units(compute_samples),
        account_metas=predict_account_metas(account_samples),
        message_bytes=predict_message_bytes(message_samples),
    )
