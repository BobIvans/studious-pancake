"""PR-200 / TEMPORAL-01 — leakage-safe temporal benchmark contracts."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import AdvisoryModel, PPM, advisory_model, integer, mean_int, quantile_int, require_rows


def build_temporal_sequence_dataset(
    rows: Sequence[Mapping[str, Any]],
    *,
    window: int,
) -> tuple[tuple[tuple[int, ...], ...], ...]:
    require_rows(rows, "rows")
    width = integer(window, "window", minimum=1)
    ordered = sorted(rows, key=lambda row: integer(row.get("available_at_ns"), "available_at_ns", minimum=0))
    features = [tuple(integer(value, "feature") for value in row.get("features", ())) for row in ordered]
    if not features or any(not row for row in features):
        raise ValueError("temporal features are required")
    if len({len(row) for row in features}) != 1:
        raise ValueError("feature width must be stable")
    return tuple(tuple(features[i - width + 1 : i + 1]) for i in range(width - 1, len(features)))


def train_temporal_anomaly_model(
    sequences: Sequence[Sequence[Sequence[int]]],
) -> AdvisoryModel:
    if not sequences:
        raise ValueError("temporal sequences are required")
    terminal = [tuple(seq[-1]) for seq in sequences if seq]
    if not terminal:
        raise ValueError("temporal sequences cannot be empty")
    width = len(terminal[0])
    if any(len(row) != width for row in terminal):
        raise ValueError("temporal feature width mismatch")
    means = [mean_int([integer(row[i], "feature") for row in terminal]) for i in range(width)]
    return advisory_model(
        "mega8-03-temporal",
        "temporal-terminal-baseline",
        {"terminal_means": means, "sample_count": len(terminal)},
        calibrated=True,
        holdout_verified=False,
    )


def score_sequence_survival(
    model: AdvisoryModel,
    sequence: Sequence[Sequence[int]],
) -> int:
    if not sequence:
        raise ValueError("sequence is required")
    means = list(model.parameters["terminal_means"])
    terminal = sequence[-1]
    if len(terminal) != len(means):
        raise ValueError("sequence feature width mismatch")
    distance = sum(abs(integer(v, "feature") - integer(m, "mean")) for v, m in zip(terminal, means, strict=True))
    return max(0, PPM - min(PPM, distance))


def benchmark_inference_latency(
    latencies_ns: Sequence[int],
    *,
    maximum_p95_ns: int,
) -> dict[str, int | bool]:
    if not latencies_ns:
        raise ValueError("latency samples are required")
    values = [integer(value, "latency_ns", minimum=0) for value in latencies_ns]
    p50 = quantile_int(values, 500_000)
    p95 = quantile_int(values, 950_000)
    cap = integer(maximum_p95_ns, "maximum_p95_ns", minimum=0)
    return {"p50_ns": p50, "p95_ns": p95, "within_latency_budget": p95 <= cap}


__all__ = [
    "benchmark_inference_latency",
    "build_temporal_sequence_dataset",
    "score_sequence_survival",
    "train_temporal_anomaly_model",
]
