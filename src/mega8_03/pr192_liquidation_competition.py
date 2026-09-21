"""PR-192 / LIQ-03 — competition and cascade analytics over canonical liquidation data."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import (
    EvidenceEnvelope,
    OfflineDecision,
    PPM,
    decision,
    integer,
    require_rows,
)


def estimate_liquidation_competition(
    *,
    competing_signatures: int,
    landed_competitors: int,
    observation_windows: int,
) -> dict[str, int]:
    signatures = integer(competing_signatures, "competing_signatures", minimum=0)
    landed = integer(landed_competitors, "landed_competitors", minimum=0)
    windows = integer(observation_windows, "observation_windows", minimum=1)
    if landed > signatures:
        raise ValueError("landed competitors cannot exceed observed signatures")
    return {
        "competition_events_per_window_ppm": signatures * PPM // windows,
        "landed_share_ppm": landed * PPM // max(1, signatures),
    }


def cluster_liquidation_queue(
    rows: Sequence[Mapping[str, Any]],
    *,
    bucket_width_ppm: int,
) -> tuple[dict[str, Any], ...]:
    require_rows(rows, "liquidations")
    width = integer(bucket_width_ppm, "bucket_width_ppm", minimum=1)
    buckets: dict[int, list[str]] = {}
    for row in rows:
        health = integer(row.get("health_ppm"), "health_ppm")
        bucket = health // width
        buckets.setdefault(bucket, []).append(str(row.get("position_id", "")))
    return tuple(
        {"bucket": bucket, "position_ids": tuple(sorted(ids)), "count": len(ids)}
        for bucket, ids in sorted(buckets.items())
    )


def simulate_liquidation_cascade(
    rows: Sequence[Mapping[str, Any]],
    *,
    price_shock_ppm: int,
) -> dict[str, int]:
    require_rows(rows, "positions")
    shock = integer(price_shock_ppm, "price_shock_ppm", minimum=0)
    triggered = 0
    debt = 0
    for row in rows:
        buffer_ppm = integer(
            row.get("health_buffer_ppm"), "health_buffer_ppm", minimum=0
        )
        if shock >= buffer_ppm:
            triggered += 1
            debt += integer(row.get("debt_atomic", 0), "debt_atomic", minimum=0)
    return {
        "triggered_positions": triggered,
        "triggered_debt_atomic": debt,
        "counterfactual": True,
    }


def rank_tail_liquidations(
    candidates: Sequence[Mapping[str, Any]],
    *,
    envelope: EvidenceEnvelope,
) -> tuple[OfflineDecision, ...]:
    require_rows(candidates, "candidates")
    decisions: list[OfflineDecision] = []
    for row in candidates:
        bonus = integer(row.get("bonus_atomic"), "bonus_atomic", minimum=0)
        exit_cost = integer(row.get("exit_cost_atomic"), "exit_cost_atomic", minimum=0)
        competition_cost = integer(
            row.get("competition_cost_atomic"), "competition_cost_atomic", minimum=0
        )
        net = bonus - exit_cost - competition_cost
        payload = dict(row) | {"conservative_net_atomic": net}
        reasons = () if net > 0 else ("LIQUIDATION_NET_NOT_POSITIVE",)
        decisions.append(
            decision(
                "PR-192",
                envelope=envelope,
                payload=payload,
                reasons=reasons,
                research_only=True,
            )
        )
    return tuple(
        sorted(
            decisions,
            key=lambda item: int(item.payload["conservative_net_atomic"]),
            reverse=True,
        )
    )


__all__ = [
    "cluster_liquidation_queue",
    "estimate_liquidation_competition",
    "rank_tail_liquidations",
    "simulate_liquidation_cascade",
]
