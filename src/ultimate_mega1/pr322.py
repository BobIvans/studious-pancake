"""PR-322 / NF-991..995: L2 sequencer recovery, fees and finality."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import ContractResult, UltimateMegaError, record, require_nonnegative, stable_hash


def read_l2_sequencer_health_witness(
    *,
    status: int | None,
    status_started_at: int | None,
    feed_updated_at: int | None,
    now: int,
    max_feed_age: int,
) -> ContractResult:
    now = require_nonnegative(now, "now")
    age_limit = require_nonnegative(max_feed_age, "max_feed_age")
    if status is None or status_started_at is None or feed_updated_at is None:
        raise UltimateMegaError("FEED_UNKNOWN")
    started = require_nonnegative(status_started_at, "status_started_at")
    updated = require_nonnegative(feed_updated_at, "feed_updated_at")
    if updated > now or now - updated > age_limit:
        raise UltimateMegaError("FEED_UNKNOWN")
    if status != 0:
        raise UltimateMegaError("SEQUENCER_DOWN")
    return record("read_l2_sequencer_health_witness", {"status": status, "status_started_at": started, "feed_updated_at": updated, "healthy": True})


def enforce_sequencer_recovery_window(
    witness: Mapping[str, Any],
    *,
    now: int,
    grace_seconds: int,
) -> ContractResult:
    now = require_nonnegative(now, "now")
    grace = require_nonnegative(grace_seconds, "grace_seconds")
    started = require_nonnegative(int(witness["status_started_at"]), "status_started_at")
    elapsed = now - started
    if elapsed < grace:
        return record(
            "enforce_sequencer_recovery_window",
            {"elapsed": elapsed, "grace_seconds": grace, "analysis_allowed": True, "execution_allowed": False},
            status="BLOCKED",
            blockers=("GRACE_NOT_ELAPSED",),
        )
    return record("enforce_sequencer_recovery_window", {"elapsed": elapsed, "grace_seconds": grace, "analysis_allowed": True, "execution_allowed": True})


def estimate_l2_full_fee_components(
    *,
    execution_fee: int,
    l1_data_fee: int | None,
    operator_fee: int | None,
    l1_fee_applicable: bool,
    operator_fee_applicable: bool,
    upgrade_rule_known: bool,
) -> ContractResult:
    if not upgrade_rule_known:
        raise UltimateMegaError("UNKNOWN_UPGRADE_FEE_RULE")
    execution = require_nonnegative(execution_fee, "execution_fee")
    l1 = require_nonnegative(l1_data_fee or 0, "l1_data_fee") if l1_fee_applicable else 0
    operator = require_nonnegative(operator_fee or 0, "operator_fee") if operator_fee_applicable else 0
    return record("estimate_l2_full_fee_components", {"execution_fee": execution, "l1_data_fee": l1, "operator_fee": operator, "total_fee": execution + l1 + operator})


def bind_l2_finality_observation(
    *,
    included: bool,
    safe: bool,
    finalized: bool,
    withdrawal_challenge_complete: bool,
    custodial_credit_available: bool,
) -> ContractResult:
    if finalized and not safe or safe and not included:
        raise UltimateMegaError("FINALITY_LEVEL_UNPROVEN")
    level = "FINALIZED" if finalized else "SAFE" if safe else "INCLUDED" if included else "UNSEEN"
    settled_withdrawal = finalized and withdrawal_challenge_complete and custodial_credit_available
    return record(
        "bind_l2_finality_observation",
        {"level": level, "withdrawal_challenge_complete": withdrawal_challenge_complete, "custodial_credit_available": custodial_credit_available, "settled_withdrawal": settled_withdrawal},
        status="OK" if finalized else "INCOMPLETE",
        blockers=() if finalized else ("FINALITY_LEVEL_UNPROVEN",),
    )


def verify_l2_fee_and_recovery_cases(
    cases: Sequence[Mapping[str, Any]],
) -> ContractResult:
    failures = []
    for idx, case in enumerate(cases):
        estimated = require_nonnegative(int(case.get("estimated_fee", 0)), f"estimated_fee_{idx}")
        actual = require_nonnegative(int(case.get("actual_fee", 0)), f"actual_fee_{idx}")
        if estimated != actual:
            failures.append((idx, estimated, actual))
        if case.get("sequencer_down") and case.get("execution_allowed"):
            failures.append((idx, "sequencer", "unsafe-execution"))
    if failures:
        raise UltimateMegaError("FEE_ACCOUNTING_MISMATCH")
    return record("verify_l2_fee_and_recovery_cases", {"case_count": len(cases), "verified": True, "cases_hash": stable_hash("l2-cases", cases)})
