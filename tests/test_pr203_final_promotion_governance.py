from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.release_gate.final_promotion_governance_pr203 import (
    REQUIRED_ASSURANCE_ROLES,
    REQUIRED_PREREQUISITES,
    REQUIRED_ROLLBACK_TRIGGERS,
    AcceptedEvidenceRef,
    DualApprovalSignature,
    FinalPromotionGovernanceBundle,
    IndependentAssuranceReview,
    LegacySurfaceEvidence,
    RollbackTriggerEvidence,
    TinyCanaryPolicy,
    evaluate_final_promotion_governance,
)

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
COMMIT = "1" * 40
ASSEMBLED_AT = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
REVIEWED_AT = ASSEMBLED_AT - timedelta(hours=2)
EXPIRES_AT = ASSEMBLED_AT + timedelta(hours=1)


def _evidence(name: str, **overrides: object) -> AcceptedEvidenceRef:
    values = {
        "name": name,
        "sha256": DIGEST_A,
        "source_commit": COMMIT,
        "accepted": True,
        "human_reviewed": True,
        "reviewer": f"reviewer-{name}",
    }
    values.update(overrides)
    return AcceptedEvidenceRef(**values)


def _legacy_surface(**overrides: object) -> LegacySurfaceEvidence:
    values = {
        "release_wheel_forbidden_imports_present": (),
        "release_image_forbidden_imports_present": (),
        "supported_entrypoint_forbidden_reachability": (),
        "duplicate_runtime_paths_removed": True,
        "stale_pr_workflows_removed": True,
        "final_docs_reduced_to_current_set": True,
        "canonical_runbook_sha256": DIGEST_A,
        "architecture_doc_sha256": DIGEST_B,
        "threat_model_sha256": DIGEST_C,
        "evidence_index_sha256": DIGEST_D,
    }
    values.update(overrides)
    return LegacySurfaceEvidence(**values)


def _assurance(
    role: str, *, reviewer: str = "independent-a"
) -> IndependentAssuranceReview:
    return IndependentAssuranceReview(
        role=role,
        reviewer=reviewer,
        artifact_sha256=DIGEST_B,
        source_commit=COMMIT,
        accepted=True,
        reviewed_at=REVIEWED_AT,
    )


def _assurance_reviews() -> tuple[IndependentAssuranceReview, ...]:
    return tuple(
        _assurance(
            role, reviewer="independent-a" if index % 2 == 0 else "independent-b"
        )
        for index, role in enumerate(REQUIRED_ASSURANCE_ROLES)
    )


def _canary(**overrides: object) -> TinyCanaryPolicy:
    values = {
        "release_hash": DIGEST_C,
        "config_hash": DIGEST_D,
        "strategy_id": "marginfi-usdc-sol-arb-v1",
        "pair": "SOL/USDC",
        "max_capital_lamports": 10_000_000,
        "max_transaction_count": 1,
        "max_daily_loss_lamports": 5_000_000,
        "max_fee_lamports": 500_000,
        "max_tip_lamports": 500_000,
        "max_uncertainty_lamports": 1_000_000,
        "manual_first_transaction_review": True,
        "no_automatic_scale_up": True,
    }
    values.update(overrides)
    return TinyCanaryPolicy(**values)


def _approval(role: str, approver: str, **overrides: object) -> DualApprovalSignature:
    values = {
        "approval_id": f"approval-{role}",
        "approver": approver,
        "role": role,
        "signed_release_hash": DIGEST_C,
        "signed_config_hash": DIGEST_D,
        "signature_sha256": DIGEST_A,
        "signed_at": REVIEWED_AT,
        "expires_at": EXPIRES_AT,
    }
    values.update(overrides)
    return DualApprovalSignature(**values)


def _approvals(**overrides: object) -> tuple[DualApprovalSignature, ...]:
    values = {
        "release_owner": _approval("release-owner", "release-owner@example.com"),
        "second": _approval(
            "independent-second-approver",
            "risk-owner@example.com",
            signature_sha256=DIGEST_B,
        ),
    }
    values.update(overrides)
    return (values["release_owner"], values["second"])


def _rollback_trigger(name: str, **overrides: object) -> RollbackTriggerEvidence:
    values = {
        "name": name,
        "automatic_rollback_to_shadow": True,
        "kill_switch_armed": True,
        "preserves_evidence": True,
        "tested": True,
    }
    values.update(overrides)
    return RollbackTriggerEvidence(**values)


def _rollback_triggers() -> tuple[RollbackTriggerEvidence, ...]:
    return tuple(_rollback_trigger(name) for name in REQUIRED_ROLLBACK_TRIGGERS)


def _bundle(**overrides: object) -> FinalPromotionGovernanceBundle:
    values = {
        "release_hash": DIGEST_C,
        "config_hash": DIGEST_D,
        "source_commit": COMMIT,
        "prerequisites": tuple(_evidence(name) for name in REQUIRED_PREREQUISITES),
        "legacy_surface": _legacy_surface(),
        "independent_assurance": _assurance_reviews(),
        "tiny_canary": _canary(),
        "approvals": _approvals(),
        "rollback_triggers": _rollback_triggers(),
        "post_canary_finalized_evidence_required": True,
        "staged_expansion_requires_new_review": True,
        "assembled_at": ASSEMBLED_AT,
        "assembled_by": "release-assembler@example.com",
    }
    values.update(overrides)
    return FinalPromotionGovernanceBundle(**values)


def test_final_promotion_governance_ready_is_still_review_only() -> None:
    report = evaluate_final_promotion_governance(_bundle())

    assert report.ready_for_manual_tiny_canary_review is True
    assert report.live_execution_allowed is False
    assert report.canary_submission_allowed is False
    assert report.automatic_scale_up_allowed is False
    assert report.blockers == ()
    assert report.state.value == "ready-for-manual-tiny-canary-review"
    assert report.evidence_hash


def test_missing_accepted_prerequisite_blocks_canary_governance() -> None:
    report = evaluate_final_promotion_governance(
        _bundle(prerequisites=(_evidence(REQUIRED_PREREQUISITES[0]),))
    )

    assert report.ready_for_manual_tiny_canary_review is False
    assert f"PREREQUISITE_MISSING:{REQUIRED_PREREQUISITES[1]}" in report.blockers


def test_legacy_import_surface_must_be_empty_in_wheel_image_and_entrypoint() -> None:
    report = evaluate_final_promotion_governance(
        _bundle(
            legacy_surface=_legacy_surface(
                release_wheel_forbidden_imports_present=("src.legacy_arb_bot",),
                release_image_forbidden_imports_present=("src.execution.live_control",),
                supported_entrypoint_forbidden_reachability=("src.execution.senders",),
                duplicate_runtime_paths_removed=False,
            )
        )
    )

    assert "WHEEL_FORBIDDEN_IMPORT_PRESENT:src.legacy_arb_bot" in report.blockers
    assert (
        "IMAGE_FORBIDDEN_IMPORT_PRESENT:src.execution.live_control" in report.blockers
    )
    assert "ENTRYPOINT_REACHES_FORBIDDEN_PATH:src.execution.senders" in report.blockers
    assert "DUPLICATE_RUNTIME_PATHS_NOT_REMOVED" in report.blockers


def test_independent_assurance_requires_all_roles_and_not_assembler() -> None:
    report = evaluate_final_promotion_governance(
        _bundle(
            independent_assurance=(
                _assurance(
                    "protocol-vectors", reviewer="release-assembler@example.com"
                ),
            )
        )
    )

    assert "ASSURANCE_NOT_INDEPENDENT:protocol-vectors" in report.blockers
    assert "ASSURANCE_ROLE_MISSING:signer-permit" in report.blockers
    assert "ASSURANCE_REQUIRES_TWO_DISTINCT_REVIEWERS" in report.blockers


def test_tiny_canary_budget_single_transaction_and_no_scale_up_are_mandatory() -> None:
    report = evaluate_final_promotion_governance(
        _bundle(
            tiny_canary=_canary(
                max_capital_lamports=100_000_000,
                max_transaction_count=2,
                max_daily_loss_lamports=150_000_000,
                no_automatic_scale_up=False,
            )
        )
    )

    assert "CANARY_CAPITAL_NOT_TINY" in report.blockers
    assert "CANARY_REQUIRES_SINGLE_TRANSACTION" in report.blockers
    assert "CANARY_DAILY_LOSS_EXCEEDS_CAPITAL" in report.blockers
    assert "CANARY_AUTOMATIC_SCALE_UP_ALLOWED" in report.blockers


def test_dual_approval_is_bound_distinct_and_expiring() -> None:
    same_person = _approval("independent-second-approver", "release-owner@example.com")
    report = evaluate_final_promotion_governance(
        _bundle(
            approvals=_approvals(
                second=same_person,
            )
        )
    )
    expired = evaluate_final_promotion_governance(
        _bundle(
            approvals=_approvals(
                second=_approval(
                    "independent-second-approver",
                    "risk-owner@example.com",
                    signed_release_hash=DIGEST_A,
                    expires_at=ASSEMBLED_AT,
                )
            )
        )
    )

    assert "DUAL_APPROVAL_REQUIRES_DISTINCT_APPROVERS" in report.blockers
    assert (
        "APPROVAL_RELEASE_HASH_MISMATCH:independent-second-approver" in expired.blockers
    )
    assert "APPROVAL_EXPIRED:independent-second-approver" in expired.blockers


def test_every_rollback_trigger_must_block_and_preserve_evidence() -> None:
    report = evaluate_final_promotion_governance(
        _bundle(
            rollback_triggers=(
                _rollback_trigger(
                    "invariant",
                    automatic_rollback_to_shadow=False,
                    preserves_evidence=False,
                    tested=False,
                ),
            )
        )
    )

    assert "ROLLBACK_NOT_AUTOMATIC:invariant" in report.blockers
    assert "ROLLBACK_DOES_NOT_PRESERVE_EVIDENCE:invariant" in report.blockers
    assert "ROLLBACK_TRIGGER_NOT_TESTED:invariant" in report.blockers
    assert "ROLLBACK_TRIGGER_MISSING:slo" in report.blockers


def test_post_canary_evidence_and_staged_expansion_review_are_required() -> None:
    report = evaluate_final_promotion_governance(
        _bundle(
            post_canary_finalized_evidence_required=False,
            staged_expansion_requires_new_review=False,
        )
    )

    assert "POST_CANARY_FINALIZED_EVIDENCE_NOT_REQUIRED" in report.blockers
    assert "STAGED_EXPANSION_CAN_AUTOSCALE" in report.blockers
