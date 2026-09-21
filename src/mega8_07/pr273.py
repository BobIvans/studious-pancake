"""PR-273 / GPU-01: optional offline GPU benchmark laboratory."""

from __future__ import annotations

from typing import Mapping, Sequence

from .core import Mega807Error, require_nonnegative, require_positive


def build_gpu_feature_batch(
    rows: Sequence[Mapping[str, int]], feature_order: Sequence[str]
) -> tuple[tuple[int, ...], ...]:
    if not rows or not feature_order:
        raise Mega807Error("GPU_BATCH_EMPTY")
    return tuple(
        tuple(require_nonnegative(row[name], name) for name in feature_order)
        for row in rows
    )


def run_gpu_simulation_batch(
    batch: Sequence[Sequence[int]],
    *,
    scale_numerator: int,
    scale_denominator: int,
) -> tuple[tuple[int, ...], ...]:
    require_positive(scale_numerator, "scale_numerator")
    require_positive(scale_denominator, "scale_denominator")
    return tuple(
        tuple(
            require_nonnegative(value, "feature") * scale_numerator // scale_denominator
            for value in row
        )
        for row in batch
    )


def benchmark_gpu_economics(
    *, cpu_total_us: int, gpu_transfer_us: int, gpu_compute_us: int
) -> dict[str, int]:
    cpu = require_positive(cpu_total_us, "cpu_total_us")
    transfer = require_nonnegative(gpu_transfer_us, "gpu_transfer_us")
    compute = require_nonnegative(gpu_compute_us, "gpu_compute_us")
    gpu_total = transfer + compute
    return {
        "cpu_total_us": cpu,
        "gpu_total_us": gpu_total,
        "gain_us": cpu - gpu_total,
    }


def reject_unjustified_gpu_path(
    benchmark: Mapping[str, int], *, minimum_gain_us: int
) -> bool:
    gain = int(benchmark.get("gain_us", 0))
    require_nonnegative(minimum_gain_us, "minimum_gain_us")
    if gain < minimum_gain_us:
        raise Mega807Error("GPU_PATH_NOT_JUSTIFIED")
    return True
