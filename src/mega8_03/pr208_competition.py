"""PR-208 / COMPETE-01 — empirical competition/capacity adjustment."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import PPM, integer, mean_int, require_rows


def cluster_competitor_archetypes(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    require_rows(rows, "competitor_rows")
    buckets: dict[str, list[str]] = {}
    for row in rows:
        speed = integer(row.get("latency_ms", 0), "latency_ms", minimum=0)
        size = integer(row.get("typical_size_atomic", 0), "typical_size_atomic", minimum=0)
        archetype = (
            "fast-large"
            if speed <= 100 and size > 1_000
            else "fast-small"
            if speed <= 100
            else "slow-large"
            if size > 1_000
            else "slow-small"
        )
        buckets.setdefault(archetype, []).append(str(row.get("public_actor_id", "")))
    return tuple(
        {"archetype": name, "public_actor_ids": tuple(sorted(actor for actor in actors if actor)), "count": len(actors)}
        for name, actors in sorted(buckets.items())
    )


def estimate_crowding_regime(
    *,
    competitor_count: int,
    attempts_per_episode_ppm: int,
    landed_share_ppm: int,
) -> dict[str, int | str]:
    count = integer(competitor_count, "competitor_count", minimum=0)
    attempts = integer(attempts_per_episode_ppm, "attempts_per_episode_ppm", minimum=0)
    landed = integer(landed_share_ppm, "landed_share_ppm", minimum=0)
    score = count * 100_000 + attempts // 4 + landed // 4
    regime = "high" if score >= 1_000_000 else "medium" if score >= 400_000 else "low"
    return {"crowding_score_ppm": score, "regime": regime}


def model_alpha_capacity_decay(
    sizes_atomic: Sequence[int],
    net_atomic: Sequence[int],
) -> dict[str, int | None]:
    if not sizes_atomic or len(sizes_atomic) != len(net_atomic):
        raise ValueError("size/net arrays must align")
    rows = sorted(
        (
            integer(size, "size_atomic", minimum=1),
            integer(net, "net_atomic"),
        )
        for size, net in zip(sizes_atomic, net_atomic, strict=True)
    )
    positive = [size for size, net in rows if net > 0]
    capacity = max(positive) if positive else None
    first_nonpositive = next((size for size, net in rows if net <= 0), None)
    return {
        "largest_positive_size_atomic": capacity,
        "first_nonpositive_size_atomic": first_nonpositive,
    }


def adjust_candidate_for_competition(
    *,
    conservative_net_atomic: int,
    crowding_penalty_ppm: int,
    decay_penalty_ppm: int,
) -> dict[str, int | bool]:
    net = integer(conservative_net_atomic, "conservative_net_atomic")
    crowding = min(PPM, integer(crowding_penalty_ppm, "crowding_penalty_ppm", minimum=0))
    decay = min(PPM, integer(decay_penalty_ppm, "decay_penalty_ppm", minimum=0))
    retained_ppm = max(0, PPM - crowding - decay)
    adjusted = net * retained_ppm // PPM
    return {
        "adjusted_net_atomic": adjusted,
        "retained_alpha_ppm": retained_ppm,
        "admitted_for_research_ranking": adjusted > 0,
        "execution_authority": False,
    }


__all__ = [
    "adjust_candidate_for_competition",
    "cluster_competitor_archetypes",
    "estimate_crowding_regime",
    "model_alpha_capacity_decay",
]
