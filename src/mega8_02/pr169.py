"""PR-169 / PREDICT-02: writable-account contention."""
from __future__ import annotations
from collections import Counter
from typing import Iterable, Sequence
from .core import Mega802Error, require_nonnegative_int


def estimate_writable_lock_contention(
    writable_accounts: Sequence[str], observed_transactions: Iterable[Sequence[str]]
) -> int:
    target = set(writable_accounts)
    if not target:
        return 0
    rows = [set(row) for row in observed_transactions]
    if not rows:
        return 0
    collisions = sum(bool(target & row) for row in rows)
    return collisions * 1_000_000 // len(rows)


def build_account_conflict_features(
    observed_transactions: Iterable[Sequence[str]],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    total = 0
    for row in observed_transactions:
        total += 1
        counts.update(set(row))
    if not total:
        return {}
    return {key: value * 1_000_000 // total for key, value in sorted(counts.items())}


def predict_local_auction_competition(
    contention_ppm: int, competing_writers: int
) -> int:
    require_nonnegative_int(contention_ppm, "contention_ppm")
    require_nonnegative_int(competing_writers, "competing_writers")
    if contention_ppm > 1_000_000:
        raise Mega802Error("CONTENTION_OUT_OF_RANGE")
    return min(1_000_000, contention_ppm + competing_writers * 25_000)


def gate_high_contention_candidate(
    competition_ppm: int, *, max_ppm: int
) -> bool:
    require_nonnegative_int(competition_ppm, "competition_ppm")
    require_nonnegative_int(max_ppm, "max_ppm")
    if competition_ppm > max_ppm:
        raise Mega802Error("HIGH_CONTENTION_CANDIDATE")
    return True
