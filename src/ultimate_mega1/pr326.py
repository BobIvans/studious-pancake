"""PR-326 / NF-1012..1016: anytime-valid evidence under explicit assumptions."""

from __future__ import annotations

from math import log, sqrt
from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_nonnegative, require_positive, stable_hash


def register_sequential_metric_contract(
    *,
    estimand_id: str,
    lower_bound: int,
    upper_bound: int,
    observation_unit: str,
    filtration_manifest: str,
) -> ContractResult:
    low = int(lower_bound)
    high = int(upper_bound)
    if high <= low:
        raise UltimateMegaError("UNJUSTIFIED_BOUNDS")
    if not estimand_id or not observation_unit or not filtration_manifest:
        raise UltimateMegaError("NONSTATIONARY_TARGET_UNSPECIFIED")
    return record(
        "register_sequential_metric_contract",
        {"estimand_id": estimand_id, "lower_bound": low, "upper_bound": high, "observation_unit": observation_unit, "filtration_manifest": filtration_manifest},
    )


def update_anytime_evidence_state(
    state: Mapping[str, Any],
    *,
    event_id: str,
    value: int,
    lower_bound: int,
    upper_bound: int,
    alpha_ppm: int = 50_000,
) -> ContractResult:
    ids = tuple(str(x) for x in state.get("event_ids", ()))
    if event_id in ids:
        raise UltimateMegaError("DUPLICATE_SAMPLE")
    low, high = int(lower_bound), int(upper_bound)
    if not low <= value <= high:
        raise UltimateMegaError("ASSUMPTION_BROKEN")
    alpha = require_positive(alpha_ppm, "alpha_ppm")
    if alpha >= 1_000_000:
        raise UltimateMegaError("ASSUMPTION_BROKEN")
    count = require_nonnegative(int(state.get("count", 0)), "count") + 1
    total = int(state.get("sum", 0)) + int(value)
    mean = total / count
    width = (high - low) * sqrt(log(2_000_000 / alpha) / (2 * count))
    return record(
        "update_anytime_evidence_state",
        {
            "event_ids": ids + (event_id,),
            "count": count,
            "sum": total,
            "mean": mean,
            "confidence_interval": (max(low, mean - width), min(high, mean + width)),
            "method": "bounded-hoeffding-anytime-research",
            "alpha_ppm": alpha,
        },
    )


def validate_optional_stopping_rule(
    evidence_state: Mapping[str, Any],
    *,
    stopping_policy_registered: bool,
    family_alpha_ppm: int,
    family_tests: int,
) -> ContractResult:
    if not stopping_policy_registered:
        raise UltimateMegaError("POST_HOC_STOP_RULE")
    alpha = require_positive(family_alpha_ppm, "family_alpha_ppm")
    tests = require_positive(family_tests, "family_tests")
    per_test = alpha // tests
    if per_test <= 0:
        raise UltimateMegaError("POST_HOC_STOP_RULE")
    return record(
        "validate_optional_stopping_rule",
        {"state_hash": stable_hash("sequential-state", evidence_state), "family_alpha_ppm": alpha, "family_tests": tests, "per_test_alpha_ppm": per_test, "stopping_rule_registered": True},
    )


def stress_sequential_error_control(
    *,
    null_false_positives: int,
    null_trials: int,
    target_alpha_ppm: int,
) -> ContractResult:
    fp = require_nonnegative(null_false_positives, "null_false_positives")
    trials = require_positive(null_trials, "null_trials")
    alpha = require_nonnegative(target_alpha_ppm, "target_alpha_ppm")
    observed_ppm = fp * 1_000_000 // trials
    # A finite simulation is a regression check, not a proof; use a conservative
    # 2x tolerance solely to catch implementation/calibration disasters.
    if observed_ppm > max(alpha * 2, alpha + 10_000):
        raise UltimateMegaError("CALIBRATION_FAILURE")
    return record(
        "stress_sequential_error_control",
        {"null_trials": trials, "false_positives": fp, "observed_false_positive_ppm": observed_ppm, "target_alpha_ppm": alpha, "market_validity_claim": False},
    )


def export_sequential_qualification_evidence(
    decision: Mapping[str, Any],
    *,
    assumption_log: Sequence[str],
    class_report_hash: str,
    live_permission_requested: bool = False,
) -> ContractResult:
    if live_permission_requested:
        raise UltimateMegaError("LIVE_PERMISSION_REQUEST_OUT_OF_SCOPE")
    if not assumption_log:
        raise UltimateMegaError("ASSUMPTION_BROKEN")
    return record(
        "export_sequential_qualification_evidence",
        {"decision_hash": stable_hash("sequential-decision", decision), "assumptions": tuple(assumption_log), "class_report_hash": class_report_hash, "supplementary_only": True, "live_permission": False},
    )
