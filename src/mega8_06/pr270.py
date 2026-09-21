"""PR-270 / RL-BID-01: safe offline priority-fee/tip bidding policy."""

from __future__ import annotations
from typing import Mapping, Sequence
from .core import Mega806Error, require_nonnegative_int, require_ppm, require_text


def build_fee_bid_dataset(
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    dataset = []
    for row in rows:
        bid = require_nonnegative_int(row.get("bid"), "bid")
        cost = require_nonnegative_int(row.get("cost"), "cost")
        if row.get("outcome") not in {"landed", "not_landed", "unknown"}:
            raise Mega806Error("INVALID_BID_OUTCOME")
        dataset.append(
            {
                "regime": require_text(row.get("regime"), "regime"),
                "bid": bid,
                "cost": cost,
                "outcome": row.get("outcome"),
            }
        )
    return tuple(dataset)


def train_safe_bid_policy(
    rows: Sequence[Mapping[str, object]], *, hard_cap: int
) -> dict[str, int]:
    hard_cap = require_nonnegative_int(hard_cap, "hard_cap")
    landed = [
        row
        for row in rows
        if row.get("outcome") == "landed" and int(row["bid"]) <= hard_cap
    ]
    if not landed:
        raise Mega806Error("NO_LANDED_SUPPORT_WITHIN_CAP")
    best = min(landed, key=lambda row: (int(row["cost"]), int(row["bid"])))
    return {"recommended_bid": int(best["bid"]), "hard_cap": hard_cap}


def calibrate_bid_risk(
    rows: Sequence[Mapping[str, object]], *, candidate_bid: int
) -> dict[str, int]:
    candidate_bid = require_nonnegative_int(candidate_bid, "candidate_bid")
    comparable = [
        row
        for row in rows
        if int(row["bid"]) <= candidate_bid and row.get("outcome") != "unknown"
    ]
    if not comparable:
        raise Mega806Error("INSUFFICIENT_BID_SUPPORT")
    landed = sum(row.get("outcome") == "landed" for row in comparable)
    inclusion_ppm = landed * 1_000_000 // len(comparable)
    avg_cost = sum(int(row["cost"]) for row in comparable) // len(comparable)
    return {"inclusion_ppm": inclusion_ppm, "average_cost": avg_cost}


def select_guarded_fee_bid(
    policy: Mapping[str, int],
    calibration: Mapping[str, int],
    *,
    max_overpayment: int,
    min_inclusion_ppm: int,
) -> int:
    max_overpayment = require_nonnegative_int(max_overpayment, "max_overpayment")
    min_inclusion_ppm = require_ppm(min_inclusion_ppm, "min_inclusion_ppm")
    if int(calibration.get("inclusion_ppm", 0)) < min_inclusion_ppm:
        raise Mega806Error("INCLUSION_RISK_TOO_HIGH")
    bid = min(int(policy["recommended_bid"]), int(policy["hard_cap"]))
    if bid - int(calibration.get("average_cost", 0)) > max_overpayment:
        raise Mega806Error("OVERPAYMENT_LIMIT")
    return bid
