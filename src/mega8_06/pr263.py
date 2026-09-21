"""PR-263 / NETWORK-01: measured read/stream region routing."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega806Error, require_nonnegative_int, require_ppm, require_text


def probe_rpc_region_quality(sample: Mapping[str, object]) -> dict[str, object]:
    region = require_text(sample.get("region"), "region")
    latency_us = require_nonnegative_int(sample.get("latency_us"), "latency_us")
    gap_ppm = require_ppm(sample.get("gap_ppm", 0), "gap_ppm")
    fork_agreement_ppm = require_ppm(
        sample.get("fork_agreement_ppm", 0), "fork_agreement_ppm"
    )
    reliability_ppm = require_ppm(
        sample.get("reliability_ppm", 0), "reliability_ppm"
    )
    return {
        "region": region,
        "latency_us": latency_us,
        "gap_ppm": gap_ppm,
        "fork_agreement_ppm": fork_agreement_ppm,
        "reliability_ppm": reliability_ppm,
        "quota_remaining": require_nonnegative_int(
            sample.get("quota_remaining", 0), "quota_remaining"
        ),
    }


def score_stream_path(sample: Mapping[str, object]) -> int:
    row = probe_rpc_region_quality(sample)
    latency_penalty = min(1_000_000, int(row["latency_us"]) // 10)
    score = (
        int(row["fork_agreement_ppm"]) * 4
        + int(row["reliability_ppm"]) * 3
        + (1_000_000 - int(row["gap_ppm"])) * 2
        + (1_000_000 - latency_penalty)
    ) // 10
    return max(0, min(1_000_000, score))


def route_read_request(
    samples: Sequence[Mapping[str, object]],
    *,
    critical: bool = False,
    min_fork_agreement_ppm: int = 990_000,
) -> str:
    if not samples:
        raise Mega806Error("NO_READ_PATH")
    min_fork_agreement_ppm = require_ppm(
        min_fork_agreement_ppm, "min_fork_agreement_ppm"
    )
    qualified = []
    for sample in samples:
        row = probe_rpc_region_quality(sample)
        if row["quota_remaining"] <= 0:
            continue
        if critical and row["fork_agreement_ppm"] < min_fork_agreement_ppm:
            continue
        qualified.append((score_stream_path(row), str(row["region"])))
    if not qualified:
        raise Mega806Error("NO_COHERENT_READ_PATH")
    return max(qualified, key=lambda item: (item[0], item[1]))[1]


def quarantine_degraded_region(
    sample: Mapping[str, object], *, min_score_ppm: int
) -> bool:
    min_score_ppm = require_ppm(min_score_ppm, "min_score_ppm")
    return score_stream_path(sample) < min_score_ppm
