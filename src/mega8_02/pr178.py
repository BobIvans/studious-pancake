"""PR-178 / ORACLE-02: schedule, confidence and lag mechanics."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from .core import Mega802Error, require_nonnegative_int, require_positive_int


@dataclass(frozen=True, slots=True)
class OracleSample:
    publish_time: int
    receive_time: int
    price: int
    confidence: int


def model_oracle_publish_schedule(samples: Sequence[OracleSample]) -> tuple[int, int]:
    if len(samples) < 2:
        raise Mega802Error("ORACLE_SCHEDULE_REQUIRES_TWO_SAMPLES")
    ordered = sorted(samples, key=lambda item: item.publish_time)
    intervals = [
        ordered[i].publish_time - ordered[i - 1].publish_time
        for i in range(1, len(ordered))
    ]
    if any(value <= 0 for value in intervals):
        raise Mega802Error("NON_MONOTONIC_ORACLE_PUBLISH_TIME")
    intervals.sort()
    return intervals[len(intervals) // 2], max(intervals)


def score_confidence_band_dislocation(
    *, market_price: int, oracle_price: int, confidence: int
) -> int:
    require_positive_int(market_price, "market_price")
    require_positive_int(oracle_price, "oracle_price")
    require_nonnegative_int(confidence, "confidence")
    distance = abs(market_price - oracle_price)
    return max(0, distance - confidence)


def detect_oracle_update_lag(sample: OracleSample, *, max_lag: int) -> int:
    lag = sample.receive_time - sample.publish_time
    if lag < 0:
        raise Mega802Error("ORACLE_TIME_REVERSAL")
    if lag > max_lag:
        raise Mega802Error("ORACLE_UPDATE_LAG")
    return lag


def route_oracle_signal_to_workers(
    signal: int, workers: Sequence[str], *, minimum_signal: int
) -> tuple[str, ...]:
    if signal < minimum_signal:
        return ()
    return tuple(sorted(set(worker for worker in workers if worker)))
