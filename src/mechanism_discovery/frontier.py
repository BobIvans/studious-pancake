"""PR-355 active market-frontier scheduling research."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .evidence_native_core import EvidenceNativeError, record, require_int, require_ppm, require_text


def estimate_marketpack_information_value(payload: Mapping[str, Any]):
    before = require_int(payload.get("uncertainty_before_ppm"), "uncertainty_before_ppm", minimum=0)
    after = require_int(payload.get("uncertainty_after_ppm"), "uncertainty_after_ppm", minimum=0)
    relevance = require_ppm(payload.get("decision_relevance_ppm"), "decision_relevance_ppm")
    reduction = max(0, before - after)
    value_ppm = min(1_000_000, reduction * relevance // 1_000_000)
    return record(
        "estimate_marketpack_information_value",
        {"uncertainty_reduction_ppm": reduction, "decision_relevance_ppm": relevance, "information_value_ppm": value_ppm},
    )


def estimate_marketpack_onboarding_cost(payload: Mapping[str, Any]):
    components = {
        name: require_int(payload.get(name, 0), name, minimum=0)
        for name in ("engineering_cost_units", "data_cost_units", "license_cost_units", "operational_cost_units")
    }
    return record(
        "estimate_marketpack_onboarding_cost",
        {**components, "total_cost_units": sum(components.values())},
    )


def score_research_frontier(payload: Mapping[str, Any]):
    value = require_ppm(payload.get("information_value_ppm"), "information_value_ppm")
    cost = require_int(payload.get("cost_units"), "cost_units", minimum=1)
    reproducibility = require_ppm(payload.get("reproducibility_ppm"), "reproducibility_ppm")
    score = value * reproducibility // (1_000_000 * cost)
    return record(
        "score_research_frontier",
        {
            "candidate_id": require_text(payload.get("candidate_id"), "candidate_id"),
            "score_units": score,
            "information_value_ppm": value,
            "cost_units": cost,
            "reproducibility_ppm": reproducibility,
        },
    )


def allocate_capture_budget_by_frontier(
    candidates: Sequence[Mapping[str, Any]],
    *,
    budget_units: int,
):
    remaining = require_int(budget_units, "budget_units", minimum=0)
    ordered = sorted(
        (
            {
                "candidate_id": require_text(row.get("candidate_id"), "candidate_id"),
                "score_units": require_int(row.get("score_units"), "score_units", minimum=0),
                "cost_units": require_int(row.get("cost_units"), "cost_units", minimum=1),
            }
            for row in candidates
        ),
        key=lambda row: (-row["score_units"], row["candidate_id"]),
    )
    admitted = []
    for row in ordered:
        if row["cost_units"] <= remaining:
            admitted.append(row["candidate_id"])
            remaining -= row["cost_units"]
    return record(
        "allocate_capture_budget_by_frontier",
        {"budget_units": budget_units, "admitted": tuple(admitted), "remaining_units": remaining},
    )


def audit_frontier_selection_bias(payload: Mapping[str, Any]):
    selected_misses = require_int(payload.get("selected_misses"), "selected_misses", minimum=0)
    selected_total = require_int(payload.get("selected_total"), "selected_total", minimum=1)
    sentinel_misses = require_int(payload.get("sentinel_misses"), "sentinel_misses", minimum=0)
    sentinel_total = require_int(payload.get("sentinel_total"), "sentinel_total", minimum=1)
    selected_rate = selected_misses * 1_000_000 // selected_total
    sentinel_rate = sentinel_misses * 1_000_000 // sentinel_total
    return record(
        "audit_frontier_selection_bias",
        {
            "selected_miss_ppm": selected_rate,
            "sentinel_miss_ppm": sentinel_rate,
            "selection_bias_warning": sentinel_rate > selected_rate,
        },
    )


def retire_low_value_marketpack(payload: Mapping[str, Any]):
    incremental = require_int(payload.get("incremental_utility_units"), "incremental_utility_units")
    cost = require_int(payload.get("ongoing_cost_units"), "ongoing_cost_units", minimum=0)
    baseline = require_int(payload.get("baseline_utility_units"), "baseline_utility_units")
    retire = incremental <= 0 or incremental - cost <= baseline
    return record(
        "retire_low_value_marketpack",
        {
            "marketpack_id": require_text(payload.get("marketpack_id"), "marketpack_id"),
            "retire": retire,
            "reason": "NO_INCREMENTAL_VALUE" if retire else "RETAIN_RESEARCH_ONLY",
        },
    )
