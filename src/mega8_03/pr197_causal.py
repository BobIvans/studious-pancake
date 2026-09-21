"""PR-197 / CAUSAL-01 — causal hypotheses remain hypotheses until holdout evidence."""

from __future__ import annotations

from collections import Counter
import math
from typing import Any, Mapping, Sequence

from .common import AdvisoryModel, PPM, advisory_model, integer, require_rows


def build_causal_event_graph(
    events: Sequence[Mapping[str, Any]],
    *,
    maximum_lag_ns: int,
) -> dict[str, object]:
    require_rows(events, "events")
    lag = integer(maximum_lag_ns, "maximum_lag_ns", minimum=1)
    ordered = sorted(
        (
            str(row.get("event_id", "")),
            str(row.get("event_type", "")),
            integer(row.get("available_at_ns"), "available_at_ns", minimum=0),
        )
        for row in events
    )
    if any(not event_id or not event_type for event_id, event_type, _ in ordered):
        raise ValueError("event identity/type is required")
    edges: list[tuple[str, str, int]] = []
    for left_index, left in enumerate(ordered):
        for right in ordered[left_index + 1 :]:
            delta = right[2] - left[2]
            if delta <= 0:
                continue
            if delta > lag:
                break
            edges.append((left[0], right[0], delta))
    return {"nodes": tuple(item[0] for item in ordered), "precedence_edges": tuple(edges)}


def estimate_transfer_entropy(
    source_bits: Sequence[int],
    target_bits: Sequence[int],
) -> dict[str, int]:
    if len(source_bits) != len(target_bits) or len(source_bits) < 3:
        raise ValueError("binary series must align and contain >=3 observations")
    source = [integer(value, "source_bit", minimum=0) for value in source_bits]
    target = [integer(value, "target_bit", minimum=0) for value in target_bits]
    if any(value not in (0, 1) for value in (*source, *target)):
        raise ValueError("transfer entropy inputs must be binary")
    triples = Counter((target[i], target[i - 1], source[i - 1]) for i in range(1, len(source)))
    yx = Counter((yp, xp) for _, yp, xp in triples.elements())
    yy = Counter((y, yp) for y, yp, _ in triples.elements())
    yp = Counter(yp for _, yp, _ in triples.elements())
    n = len(source) - 1
    te = 0.0
    for (y, y_prev, x_prev), count in triples.items():
        p_joint = count / n
        p_y_given_yx = count / yx[(y_prev, x_prev)]
        p_y_given_y = yy[(y, y_prev)] / yp[y_prev]
        te += p_joint * math.log2(p_y_given_yx / p_y_given_y)
    return {"transfer_entropy_microbits": max(0, int(te * PPM)), "sample_count": n}


def test_event_precedence_hypothesis(
    cause_times_ns: Sequence[int],
    effect_times_ns: Sequence[int],
    *,
    maximum_lag_ns: int,
) -> dict[str, int]:
    if not cause_times_ns or not effect_times_ns:
        raise ValueError("cause/effect samples are required")
    lag = integer(maximum_lag_ns, "maximum_lag_ns", minimum=1)
    effects = sorted(integer(value, "effect_time_ns", minimum=0) for value in effect_times_ns)
    successes = 0
    causes = [integer(value, "cause_time_ns", minimum=0) for value in cause_times_ns]
    for cause in causes:
        if any(cause < effect <= cause + lag for effect in effects):
            successes += 1
    return {
        "cause_count": len(causes),
        "preceded_effect_count": successes,
        "precedence_share_ppm": successes * PPM // len(causes),
    }


def promote_causal_feature(
    *,
    feature_id: str,
    preregistered: bool,
    holdout_gain_ppm: int,
    minimum_gain_ppm: int,
    stable_across_replays: bool,
) -> AdvisoryModel:
    gain = integer(holdout_gain_ppm, "holdout_gain_ppm")
    minimum = integer(minimum_gain_ppm, "minimum_gain_ppm", minimum=0)
    promoted = preregistered and stable_across_replays and gain >= minimum
    return advisory_model(
        f"causal-{feature_id}",
        "causal-feature-hypothesis",
        {
            "feature_id": feature_id,
            "holdout_gain_ppm": gain,
            "minimum_gain_ppm": minimum,
            "promoted_for_research_ranking": promoted,
            "causal_truth_claimed": False,
        },
        calibrated=promoted,
        holdout_verified=promoted,
    )


__all__ = [
    "build_causal_event_graph",
    "estimate_transfer_entropy",
    "promote_causal_feature",
    "test_event_precedence_hypothesis",
]
