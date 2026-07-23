from __future__ import annotations

import math

import pytest

from src.release_gate.mpr07_operations_promotion_gate import (
    CanaryBudgetEvidence,
    MPR07PromotionEvidence,
    MPR07State,
    OperatorApproval,
    SignedArtifact,
    evaluate_mpr07_promotion,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
SIG_A = "1" * 128
SIG_B = "2" * 128
NOW_MS = 1_800_000


def artifacts() -> tuple[SignedArtifact, ...]:
    return tuple(
        SignedArtifact(label=label, sha256=DIGEST_A, signature=SIG_A)
        for label in (
            "source_commit",
            "wheel",
            "image",
            "config",
            "policy",
            "soak",
            "backup",
            "rollback",
        )
    )


def approvals(bundle_hash: str = DIGEST_B) -> tuple[OperatorApproval, ...]:
    return (
        OperatorApproval(
            reviewer_id="alice",
            role="operator",
            bundle_hash=bundle_hash,
            public_key_sha256=DIGEST_A,
            signature=SIG_A,
            issued_at_ms=NOW_MS - 100_000,
            expires_at_ms=NOW_MS + 100_000,
        ),
        OperatorApproval(
            reviewer_id="bob",
            role="risk",
            bundle_hash=bundle_hash,
            public_key_sha256=DIGEST_A,
            signature=SIG_A,
            issued_at_ms=NOW_MS - 100_000,
            expires_at_ms=NOW_MS + 100_000,
        ),
        OperatorApproval(
            reviewer_id="carol",
            role="security",
            bundle_hash=bundle_hash,
            public_key_sha256=DIGEST_A,
            signature=SIG_B,
            issued_at_ms=NOW_MS - 100_000,
            expires_at_ms=NOW_MS + 100_000,
        ),
    )


def telemetry() -> dict[str, float]:
    return {
        "event_loop_lag_ratio": 0.1,
        "queue_age_ratio": 0.2,
        "memory_growth_ratio": 0.1,
        "fd_growth_ratio": 0.05,
        "backup_age_ratio": 0.2,
        "soak_age_ratio": 0.15,
    }


def canary() -> CanaryBudgetEvidence:
    return CanaryBudgetEvidence(
        wallet_capital_lamports=10_000,
        daily_loss_limit_lamports=2_000,
        max_transaction_count=1,
        fee_lamports=100,
        tip_lamports=100,
        rent_lamports=100,
        uncertainty_lamports=100,
        gross_loss_lamports=100,
    )


def clean_evidence() -> MPR07PromotionEvidence:
    return MPR07PromotionEvidence(
        evaluated_at_ms=NOW_MS,
        bundle_hash=DIGEST_B,
        telemetry=telemetry(),
        telemetry_collected_at_ms=NOW_MS - 1_000,
        artifacts=artifacts(),
        approvals=approvals(),
        canary_budget=canary(),
        rollback_triggers=(
            "failed_settlement",
            "slo_breach",
            "manual_latch",
            "late_landing",
            "evidence_mismatch",
        ),
        automatic_rollback_to_shadow=True,
        post_canary_review_required=True,
        legacy_cleanup_complete=True,
    )


def codes(report) -> set[str]:
    return {violation.code for violation in report.violations}


def test_mpr07_accepts_complete_review_only_promotion_bundle() -> None:
    report = evaluate_mpr07_promotion(clean_evidence())

    assert report.ready is True
    assert report.state is MPR07State.READY_FOR_MANUAL_TINY_CANARY_REVIEW
    assert report.violations == ()
    assert report.to_dict()["safety_boundary"] == {
        "live_execution_allowed": False,
        "signer_allowed": False,
        "sender_allowed": False,
    }


def test_mpr07_blocks_empty_or_missing_telemetry() -> None:
    evidence = clean_evidence()
    report = evaluate_mpr07_promotion(
        MPR07PromotionEvidence(
            evaluated_at_ms=evidence.evaluated_at_ms,
            bundle_hash=evidence.bundle_hash,
            telemetry={"event_loop_lag_ratio": 0.1},
            telemetry_collected_at_ms=evidence.telemetry_collected_at_ms,
            artifacts=evidence.artifacts,
            approvals=evidence.approvals,
            canary_budget=evidence.canary_budget,
            rollback_triggers=evidence.rollback_triggers,
            automatic_rollback_to_shadow=evidence.automatic_rollback_to_shadow,
            post_canary_review_required=evidence.post_canary_review_required,
            legacy_cleanup_complete=evidence.legacy_cleanup_complete,
        )
    )

    assert report.ready is False
    assert "missing_telemetry" in codes(report)


def test_mpr07_blocks_nan_stale_and_secret_like_telemetry() -> None:
    evidence = clean_evidence()
    telemetry_values = telemetry()
    telemetry_values["queue_age_ratio"] = math.nan
    telemetry_values["api_key_ratio"] = 0.1

    report = evaluate_mpr07_promotion(
        MPR07PromotionEvidence(
            evaluated_at_ms=evidence.evaluated_at_ms,
            bundle_hash=evidence.bundle_hash,
            telemetry=telemetry_values,
            telemetry_collected_at_ms=0,
            artifacts=evidence.artifacts,
            approvals=evidence.approvals,
            canary_budget=evidence.canary_budget,
            rollback_triggers=evidence.rollback_triggers,
            automatic_rollback_to_shadow=evidence.automatic_rollback_to_shadow,
            post_canary_review_required=evidence.post_canary_review_required,
            legacy_cleanup_complete=evidence.legacy_cleanup_complete,
        )
    )

    assert report.ready is False
    assert {
        "non_finite_telemetry",
        "secret_like_telemetry_key",
        "stale_telemetry",
    } <= codes(report)


def test_mpr07_blocks_missing_signed_release_artifacts() -> None:
    evidence = clean_evidence()
    report = evaluate_mpr07_promotion(
        MPR07PromotionEvidence(
            evaluated_at_ms=evidence.evaluated_at_ms,
            bundle_hash=evidence.bundle_hash,
            telemetry=evidence.telemetry,
            telemetry_collected_at_ms=evidence.telemetry_collected_at_ms,
            artifacts=evidence.artifacts[:-1],
            approvals=evidence.approvals,
            canary_budget=evidence.canary_budget,
            rollback_triggers=evidence.rollback_triggers,
            automatic_rollback_to_shadow=evidence.automatic_rollback_to_shadow,
            post_canary_review_required=evidence.post_canary_review_required,
            legacy_cleanup_complete=evidence.legacy_cleanup_complete,
        )
    )

    assert report.ready is False
    assert "missing_signed_artifact" in codes(report)


def test_mpr07_blocks_expired_revoked_or_wrong_bundle_approvals() -> None:
    evidence = clean_evidence()
    bad_approvals = (
        OperatorApproval(
            reviewer_id="alice",
            role="operator",
            bundle_hash=DIGEST_A,
            public_key_sha256=DIGEST_A,
            signature=SIG_A,
            issued_at_ms=NOW_MS - 100_000,
            expires_at_ms=NOW_MS + 100_000,
        ),
        OperatorApproval(
            reviewer_id="bob",
            role="risk",
            bundle_hash=DIGEST_B,
            public_key_sha256=DIGEST_A,
            signature=SIG_A,
            issued_at_ms=NOW_MS - 200_000,
            expires_at_ms=NOW_MS - 1,
        ),
        OperatorApproval(
            reviewer_id="carol",
            role="security",
            bundle_hash=DIGEST_B,
            public_key_sha256=DIGEST_A,
            signature=SIG_B,
            issued_at_ms=NOW_MS - 100_000,
            expires_at_ms=NOW_MS + 100_000,
            revoked=True,
        ),
    )
    report = evaluate_mpr07_promotion(
        MPR07PromotionEvidence(
            evaluated_at_ms=evidence.evaluated_at_ms,
            bundle_hash=evidence.bundle_hash,
            telemetry=evidence.telemetry,
            telemetry_collected_at_ms=evidence.telemetry_collected_at_ms,
            artifacts=evidence.artifacts,
            approvals=bad_approvals,
            canary_budget=evidence.canary_budget,
            rollback_triggers=evidence.rollback_triggers,
            automatic_rollback_to_shadow=evidence.automatic_rollback_to_shadow,
            post_canary_review_required=evidence.post_canary_review_required,
            legacy_cleanup_complete=evidence.legacy_cleanup_complete,
        )
    )

    assert report.ready is False
    assert {
        "approval_bundle_mismatch",
        "approval_expired",
        "approval_revoked",
    } <= codes(report)
    assert "missing_active_approval_role" in codes(report)


def test_mpr07_blocks_duplicate_reviewer_for_distinct_roles() -> None:
    evidence = clean_evidence()
    duplicate = OperatorApproval(
        reviewer_id="alice",
        role="risk",
        bundle_hash=DIGEST_B,
        public_key_sha256=DIGEST_A,
        signature=SIG_A,
        issued_at_ms=NOW_MS - 10,
        expires_at_ms=NOW_MS + 10_000,
    )
    report = evaluate_mpr07_promotion(
        MPR07PromotionEvidence(
            evaluated_at_ms=evidence.evaluated_at_ms,
            bundle_hash=evidence.bundle_hash,
            telemetry=evidence.telemetry,
            telemetry_collected_at_ms=evidence.telemetry_collected_at_ms,
            artifacts=evidence.artifacts,
            approvals=(evidence.approvals[0], duplicate, evidence.approvals[2]),
            canary_budget=evidence.canary_budget,
            rollback_triggers=evidence.rollback_triggers,
            automatic_rollback_to_shadow=evidence.automatic_rollback_to_shadow,
            post_canary_review_required=evidence.post_canary_review_required,
            legacy_cleanup_complete=evidence.legacy_cleanup_complete,
        )
    )

    assert report.ready is False
    assert "duplicate_reviewer" in codes(report)


def test_mpr07_blocks_aggregate_canary_loss_over_daily_limit() -> None:
    evidence = clean_evidence()
    risky_canary = CanaryBudgetEvidence(
        wallet_capital_lamports=10_000,
        daily_loss_limit_lamports=1_000,
        max_transaction_count=1,
        fee_lamports=400,
        tip_lamports=400,
        rent_lamports=400,
        uncertainty_lamports=400,
        gross_loss_lamports=400,
    )
    report = evaluate_mpr07_promotion(
        MPR07PromotionEvidence(
            evaluated_at_ms=evidence.evaluated_at_ms,
            bundle_hash=evidence.bundle_hash,
            telemetry=evidence.telemetry,
            telemetry_collected_at_ms=evidence.telemetry_collected_at_ms,
            artifacts=evidence.artifacts,
            approvals=evidence.approvals,
            canary_budget=risky_canary,
            rollback_triggers=evidence.rollback_triggers,
            automatic_rollback_to_shadow=evidence.automatic_rollback_to_shadow,
            post_canary_review_required=evidence.post_canary_review_required,
            legacy_cleanup_complete=evidence.legacy_cleanup_complete,
        )
    )

    assert report.ready is False
    assert "canary_budget_exceeded" in codes(report)


def test_mpr07_blocks_missing_rollback_review_or_legacy_cleanup() -> None:
    evidence = clean_evidence()
    report = evaluate_mpr07_promotion(
        MPR07PromotionEvidence(
            evaluated_at_ms=evidence.evaluated_at_ms,
            bundle_hash=evidence.bundle_hash,
            telemetry=evidence.telemetry,
            telemetry_collected_at_ms=evidence.telemetry_collected_at_ms,
            artifacts=evidence.artifacts,
            approvals=evidence.approvals,
            canary_budget=evidence.canary_budget,
            rollback_triggers=("failed_settlement",),
            automatic_rollback_to_shadow=False,
            post_canary_review_required=False,
            legacy_cleanup_complete=False,
        )
    )

    assert report.ready is False
    assert {
        "missing_rollback_trigger",
        "rollback_not_automatic",
        "post_canary_review_not_required",
        "legacy_cleanup_incomplete",
    } <= codes(report)


def test_mpr07_blocks_live_signer_or_sender_reachability() -> None:
    evidence = clean_evidence()
    report = evaluate_mpr07_promotion(
        MPR07PromotionEvidence(
            evaluated_at_ms=evidence.evaluated_at_ms,
            bundle_hash=evidence.bundle_hash,
            telemetry=evidence.telemetry,
            telemetry_collected_at_ms=evidence.telemetry_collected_at_ms,
            artifacts=evidence.artifacts,
            approvals=evidence.approvals,
            canary_budget=evidence.canary_budget,
            rollback_triggers=evidence.rollback_triggers,
            automatic_rollback_to_shadow=evidence.automatic_rollback_to_shadow,
            post_canary_review_required=evidence.post_canary_review_required,
            legacy_cleanup_complete=evidence.legacy_cleanup_complete,
            live_capability_enabled=True,
            signer_reachable=True,
            sender_reachable=True,
        )
    )

    assert report.ready is False
    assert "forbidden_surface_reachable" in codes(report)


def test_mpr07_evidence_hash_is_deterministic_under_reordering() -> None:
    evidence = clean_evidence()
    left = evaluate_mpr07_promotion(evidence)
    right = evaluate_mpr07_promotion(
        MPR07PromotionEvidence(
            evaluated_at_ms=evidence.evaluated_at_ms,
            bundle_hash=evidence.bundle_hash,
            telemetry=dict(reversed(list(evidence.telemetry.items()))),
            telemetry_collected_at_ms=evidence.telemetry_collected_at_ms,
            artifacts=tuple(reversed(evidence.artifacts)),
            approvals=tuple(reversed(evidence.approvals)),
            canary_budget=evidence.canary_budget,
            rollback_triggers=tuple(reversed(evidence.rollback_triggers)),
            automatic_rollback_to_shadow=evidence.automatic_rollback_to_shadow,
            post_canary_review_required=evidence.post_canary_review_required,
            legacy_cleanup_complete=evidence.legacy_cleanup_complete,
        )
    )

    assert left.evidence_hash == right.evidence_hash
