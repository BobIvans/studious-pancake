"""PR-199 / GNN-01 — offline dynamic-graph experiment boundary.

The reference implementation intentionally uses deterministic graph statistics as
the canonical baseline.  A future GNN challenger must beat it before promotion.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .common import AdvisoryModel, PPM, advisory_model, integer, mean_int, require_rows


def encode_dynamic_market_graph(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
) -> tuple[int, ...]:
    require_rows(nodes, "nodes")
    node_ids = [str(row.get("node_id", "")) for row in nodes]
    if any(not value for value in node_ids) or len(set(node_ids)) != len(node_ids):
        raise ValueError("node identities must be unique/non-empty")
    degrees = {node_id: 0 for node_id in node_ids}
    total_weight = 0
    for edge in edges:
        left = str(edge.get("source", ""))
        right = str(edge.get("target", ""))
        if left not in degrees or right not in degrees:
            raise ValueError("edge references unknown node")
        degrees[left] += 1
        degrees[right] += 1
        total_weight += integer(edge.get("weight_atomic", 0), "weight_atomic", minimum=0)
    return (
        len(nodes),
        len(edges),
        sum(degrees.values()),
        max(degrees.values(), default=0),
        total_weight,
    )


def train_graph_anomaly_model(
    encoded_states: Sequence[Sequence[int]],
) -> AdvisoryModel:
    if not encoded_states:
        raise ValueError("encoded graph states are required")
    width = len(encoded_states[0])
    if width == 0 or any(len(row) != width for row in encoded_states):
        raise ValueError("graph encodings must have stable width")
    means = [mean_int([integer(row[i], "feature") for row in encoded_states]) for i in range(width)]
    scales = [
        max(1, mean_int([abs(integer(row[i], "feature") - means[i]) for row in encoded_states]))
        for i in range(width)
    ]
    return advisory_model(
        "mega8-03-graph-anomaly",
        "deterministic-graph-baseline",
        {"means": means, "scales": scales, "sample_count": len(encoded_states)},
        calibrated=True,
        holdout_verified=False,
    )


def score_graph_state_transition(
    model: AdvisoryModel,
    encoded_state: Sequence[int],
) -> int:
    means = list(model.parameters["means"])
    scales = list(model.parameters["scales"])
    if len(encoded_state) != len(means):
        raise ValueError("graph state width mismatch")
    score = sum(
        abs(integer(value, "feature") - integer(mean, "mean"))
        * PPM
        // integer(scale, "scale", minimum=1)
        for value, mean, scale in zip(encoded_state, means, scales, strict=True)
    )
    return score // len(means)


def compare_graph_baseline(
    challenger_scores: Sequence[int],
    baseline_scores: Sequence[int],
    labels: Sequence[int],
) -> dict[str, int | bool]:
    if not challenger_scores or not (
        len(challenger_scores) == len(baseline_scores) == len(labels)
    ):
        raise ValueError("score/label arrays must align")
    def separation(scores: Sequence[int]) -> int:
        positives = [integer(s, "score") for s, y in zip(scores, labels, strict=True) if y == 1]
        negatives = [integer(s, "score") for s, y in zip(scores, labels, strict=True) if y == 0]
        if not positives or not negatives:
            return 0
        return mean_int(positives) - mean_int(negatives)
    challenger = separation(challenger_scores)
    baseline = separation(baseline_scores)
    return {
        "challenger_separation": challenger,
        "baseline_separation": baseline,
        "challenger_beats_baseline": challenger > baseline,
    }


__all__ = [
    "compare_graph_baseline",
    "encode_dynamic_market_graph",
    "score_graph_state_transition",
    "train_graph_anomaly_model",
]
