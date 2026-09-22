from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.pr162_operator_control_plane import (
    AuthenticatedPrincipal,
    AuthenticationMethod,
    BreakGlassGovernance,
    ControlEnvironment,
    CryptographicApproval,
    DurableApprovalLifecycle,
    OperatorActionRequest,
    OperatorControlPlaneError,
    OperatorControlPlanePackage,
    OperatorControlPlaneState,
    OperatorPermission,
    OperatorRole,
    ApprovalLifecycleState,
    ProtectedDeploymentEnvironment,
    SeparationOfDutiesPolicy,
    evaluate_operator_control_plane,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SIG = "sigstore:valid-operator-approval-signature"
CHAIN = ("issuer:github-protected-environment", "keyid:operator-key-1")


def _principal(subject: str, role: OperatorRole, **overrides: object) -> AuthenticatedPrincipal:
    values: dict[str, object] = {
        "issuer": "https://token.actions.githubusercontent.com",
        "subject": subject,
        "organization": "BobIvans/studious-pancake",
        "role_bindings": frozenset({role}),
        "authentication_method": AuthenticationMethod.GITHUB_OIDC_PROTECTED_ENVIRONMENT,
        "mfa_verified": True,
        "hardware_bound": True,
        "issued_at": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(minutes=30),
        "session_id": f"session-{subject}",
        "credential_id": f"credential-{subject}",
        "verified_claims_hash": SHA_A,
        "environment": ControlEnvironment.PRODUCTION,
        "revoked": False,
    }
    values.update(overrides)
    return AuthenticatedPrincipal(**values)  # type: ignore[arg-type]


def _request() -> OperatorActionRequest:
    return OperatorActionRequest(
        action_id="live-canary-arm-2026-07-22",
        permission=OperatorPermission.ARM_LIVE_CANARY,
        environment=ControlEnvironment.PRODUCTION,
        request_hash=SHA_A,
        policy_bundle_hash=SHA_B,
        release_artifact_hash=SHA_C,
        scope="reviewed-live-canary",
        reason="manual review of PR-162 operator-control evidence",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=20),
    )


def _approval(subject: str, permission: OperatorPermission) -> CryptographicApproval:
    request = _request()
    return CryptographicApproval(
        principal_subject=subject,
        permission=permission,
        request_hash=request.request_hash,
        policy_bundle_hash=request.policy_bundle_hash,
        release_artifact_hash=request.release_artifact_hash,
        environment=request.environment,
        scope=request.scope,
        signed_at=NOW - timedelta(seconds=30),
        expires_at=NOW + timedelta(minutes=10),
        signature=SIG,
        verification_chain=CHAIN,
    )


def _package(**overrides: object) -> OperatorControlPlanePackage:
    principals = {
        "requester": _principal("requester", OperatorRole.PAPER_OPERATOR),
        "risk": _principal("risk", OperatorRole.RISK_REVIEWER),
        "security": _principal("security", OperatorRole.SECURITY_REVIEWER),
        "approver": _principal("approver", OperatorRole.RELEASE_APPROVER),
        "armer": _principal("armer", OperatorRole.LIVE_CANARY_OPERATOR),
    }
    values: dict[str, object] = {
        "action_request": _request(),
        "principals": principals,
        "approvals": (
            _approval("requester", OperatorPermission.REQUEST_LIVE_CANARY),
            _approval("risk", OperatorPermission.REVIEW_LIVE_RISK),
            _approval("security", OperatorPermission.REVIEW_SECURITY),
            _approval("approver", OperatorPermission.APPROVE_RELEASE),
            _approval("armer", OperatorPermission.ARM_LIVE_CANARY),
        ),
        "lifecycle": DurableApprovalLifecycle(
            durable_store_id="operator-approvals.sqlite:live-canary-arm-2026-07-22",
            current_state=ApprovalLifecycleState.APPROVED,
            last_event_hash=SHA_D,
            restart_replay_protected=True,
            expired_or_revoked_reuse_blocked=True,
            audit_event_count=5,
        ),
        "separation": SeparationOfDutiesPolicy(
            requester_subject="requester",
            risk_reviewer_subject="risk",
            security_reviewer_subject="security",
            release_approver_subject="approver",
            final_armer_subject="armer",
            signer_admin_subject="signer-admin",
            treasury_admin_subject="treasury-admin",
        ),
        "break_glass": BreakGlassGovernance(enabled=False),
        "deployment_environment": ProtectedDeploymentEnvironment(
            environment_name="production",
            required_reviewers=2,
            prevents_self_review=True,
            branch_or_tag_restricted=True,
            secrets_unavailable_before_approval=True,
            administrator_bypass_disabled=True,
            workload_identity_oidc=True,
        ),
        "default_live_enabled": False,
        "env_can_enable_live": False,
        "assembled_at": NOW,
        "assembled_by": "operator-control-review",
    }
    values.update(overrides)
    return OperatorControlPlanePackage(**values)  # type: ignore[arg-type]


def test_pr162_ready_package_remains_manual_review_only() -> None:
    result = evaluate_operator_control_plane(_package(), now=NOW)

    assert result.state == OperatorControlPlaneState.READY_FOR_MANUAL_CONTROL_PLANE_REVIEW
    assert result.ready_for_manual_control_plane_review is True
    assert result.runtime_live_enabled is False
    assert result.supported_command_can_mutate is False
    assert result.blockers == ()
    assert len(result.package_sha256) == 64


def test_pr162_arbitrary_local_human_cannot_become_production_principal() -> None:
    with pytest.raises(OperatorControlPlaneError, match="production principal"):
        _principal(
            "any-arbitrary-text",
            OperatorRole.LIVE_CANARY_OPERATOR,
            authentication_method=AuthenticationMethod.LOCAL_DEVELOPMENT,
        )


def test_pr162_live_request_review_and_arm_cannot_be_same_identity() -> None:
    package = _package(
        separation=SeparationOfDutiesPolicy(
            requester_subject="requester",
            risk_reviewer_subject="requester",
            security_reviewer_subject="security",
            release_approver_subject="approver",
            final_armer_subject="requester",
        )
    )

    result = evaluate_operator_control_plane(package, now=NOW)

    assert result.state == OperatorControlPlaneState.BLOCKED
    assert "SEPARATION:requester-cannot-review-approve-or-arm" in result.blockers
    assert "SEPARATION:risk-reviewer-cannot-arm" in result.blockers


def test_pr162_approval_must_be_bound_to_exact_request_and_policy() -> None:
    bad_approval = replace(
        _approval("approver", OperatorPermission.APPROVE_RELEASE),
        policy_bundle_hash="e" * 64,
    )
    package = _package(
        approvals=(
            _approval("requester", OperatorPermission.REQUEST_LIVE_CANARY),
            _approval("risk", OperatorPermission.REVIEW_LIVE_RISK),
            _approval("security", OperatorPermission.REVIEW_SECURITY),
            bad_approval,
            _approval("armer", OperatorPermission.ARM_LIVE_CANARY),
        )
    )

    result = evaluate_operator_control_plane(package, now=NOW)

    assert result.state == OperatorControlPlaneState.BLOCKED
    assert (
        "APPROVAL_NOT_BOUND_TO_REQUEST:approver:approve-release" in result.blockers
    )


def test_pr162_revoked_or_expired_principal_cannot_approve() -> None:
    principals = dict(_package().principals)
    principals["risk"] = _principal(
        "risk",
        OperatorRole.RISK_REVIEWER,
        revoked=True,
    )
    package = _package(principals=principals)

    result = evaluate_operator_control_plane(package, now=NOW)

    assert result.state == OperatorControlPlaneState.BLOCKED
    assert "PRINCIPAL_NOT_VALID:risk" in result.blockers


def test_pr162_missing_role_permission_blocks_action() -> None:
    principals = dict(_package().principals)
    principals["armer"] = _principal("armer", OperatorRole.OBSERVER)
    package = _package(principals=principals)

    result = evaluate_operator_control_plane(package, now=NOW)

    assert result.state == OperatorControlPlaneState.BLOCKED
    assert "PRINCIPAL_PERMISSION_MISSING:armer:arm-live-canary" in result.blockers


def test_pr162_no_single_env_or_default_can_enable_live() -> None:
    package = _package(default_live_enabled=True, env_can_enable_live=True)

    result = evaluate_operator_control_plane(package, now=NOW)

    assert result.state == OperatorControlPlaneState.BLOCKED
    assert "DEFAULT_LIVE_ENABLED" in result.blockers
    assert "ENV_CAN_ENABLE_LIVE" in result.blockers


def test_pr162_break_glass_never_bypasses_safety_controls() -> None:
    package = _package(
        break_glass=BreakGlassGovernance(
            enabled=True,
            incident_id="INC-2026-07-22-001",
            short_expiry=True,
            two_person_approval=True,
            immediate_alert=True,
            immutable_audit=True,
            post_incident_review_required=True,
            credential_rotation_required=True,
            disables_message_verification=True,
        )
    )

    result = evaluate_operator_control_plane(package, now=NOW)

    assert result.state == OperatorControlPlaneState.BLOCKED
    assert "BREAK_GLASS:break-glass-disables-message-verification" in result.blockers


def test_pr162_placeholder_hashes_are_rejected() -> None:
    with pytest.raises(OperatorControlPlaneError, match="non-placeholder sha256"):
        _principal(
            "requester",
            OperatorRole.PAPER_OPERATOR,
            verified_claims_hash="0" * 64,
        )
