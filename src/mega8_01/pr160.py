"""PR-160 / NF-389..392: value-of-information quota allocation."""

from __future__ import annotations

from collections.abc import Mapping

from .common import artifact, fail_closed, require_non_negative_int, require_positive_int, require_text


def estimate_query_information_value(
    query_id: str,
    expected_uncertainty_reduction_microunits: int,
    quota_cost_units: int,
):
    qid = require_text(query_id, "query_id")
    gain = require_non_negative_int(
        expected_uncertainty_reduction_microunits,
        "expected_uncertainty_reduction_microunits",
    )
    cost = require_positive_int(quota_cost_units, "quota_cost_units")
    score = gain // cost
    return artifact(
        child="PR-160",
        nf="NF-389",
        action="estimate_query_information_value",
        subject_id=qid,
        payload={"gain_microunits": gain, "quota_cost_units": cost, "value_score": score},
    )


def allocate_source_quota_portfolio(
    allocation_id: str,
    value_scores: Mapping[str, int],
    total_quota_units: int,
):
    aid = require_text(allocation_id, "allocation_id")
    quota = require_non_negative_int(total_quota_units, "total_quota_units")
    checked = {
        require_text(source, "source"): require_non_negative_int(score, "value_score")
        for source, score in value_scores.items()
    }
    ordered = tuple(sorted(checked, key=lambda source: (-checked[source], source)))
    remaining = quota
    allocation: dict[str, int] = {}
    for source in ordered:
        if remaining <= 0:
            allocation[source] = 0
            continue
        allocation[source] = 1
        remaining -= 1
    return artifact(
        child="PR-160",
        nf="NF-390",
        action="allocate_source_quota_portfolio",
        subject_id=aid,
        payload={"allocation": allocation, "unallocated_quota_units": remaining},
    )


def adapt_sampling_cadence(
    source_id: str,
    current_interval_ms: int,
    information_value_score: int,
    minimum_interval_ms: int,
    maximum_interval_ms: int,
):
    source = require_text(source_id, "source_id")
    current = require_positive_int(current_interval_ms, "current_interval_ms")
    value = require_non_negative_int(information_value_score, "information_value_score")
    minimum = require_positive_int(minimum_interval_ms, "minimum_interval_ms")
    maximum = require_positive_int(maximum_interval_ms, "maximum_interval_ms")
    if minimum > maximum:
        return fail_closed(
            child="PR-160",
            nf="NF-391",
            action="adapt_sampling_cadence",
            subject_id=source,
            reason="INCONSISTENT_STATE",
        )
    proposed = current // 2 if value > 0 else current * 2
    bounded = min(maximum, max(minimum, proposed))
    return artifact(
        child="PR-160",
        nf="NF-391",
        action="adapt_sampling_cadence",
        subject_id=source,
        payload={"current_interval_ms": current, "next_interval_ms": bounded},
    )


def audit_quota_allocation_gain(
    allocation_id: str,
    baseline_gain_microunits: int,
    allocated_gain_microunits: int,
    quota_units_used: int,
):
    aid = require_text(allocation_id, "allocation_id")
    baseline = require_non_negative_int(baseline_gain_microunits, "baseline_gain_microunits")
    allocated = require_non_negative_int(allocated_gain_microunits, "allocated_gain_microunits")
    used = require_non_negative_int(quota_units_used, "quota_units_used")
    return artifact(
        child="PR-160",
        nf="NF-392",
        action="audit_quota_allocation_gain",
        subject_id=aid,
        payload={
            "baseline_gain_microunits": baseline,
            "allocated_gain_microunits": allocated,
            "incremental_gain_microunits": allocated - baseline,
            "quota_units_used": used,
        },
    )
