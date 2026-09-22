"""PR-162 authenticated operator control plane and separation-of-duties gate.

This module is deliberately side-effect free. It does not authenticate against a
live identity provider, mutate approval state, call GitHub, call signers, call
RPC, or enable live trading. It validates an already-collected operator-control
package and fails closed unless the evidence proves authenticated principals,
RBAC, cryptographic approvals, durable lifecycle state, and separation of duties.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

PR162_OPERATOR_CONTROL_SCHEMA = "pr162.authenticated-operator-control-plane.v1"
PR162_OPERATOR_CONTROL_RESULT_SCHEMA = (
    "pr162.authenticated-operator-control-plane-result.v1"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_RE = re.compile(r"^[A-Za-z0-9_+=:/.,@ -]{16,4096}$")


class OperatorControlPlaneError(ValueError):
    """Raised when PR-162 operator-control evidence is malformed."""


class OperatorControlPlaneState(StrEnum):
    """Fail-closed states for the PR-162 operator-control gate."""

    BLOCKED = "blocked"
    READY_FOR_MANUAL_CONTROL_PLANE_REVIEW = "ready-for-manual-control-plane-review"


class ControlEnvironment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class AuthenticationMethod(StrEnum):
    LOCAL_DEVELOPMENT = "local-development"
    GITHUB_OIDC_PROTECTED_ENVIRONMENT = "github-oidc-protected-environment"
    MTLS_CLIENT_CERTIFICATE = "mtls-client-certificate"
    SSH_SIGNED_REQUEST = "ssh-signed-request"
    GPG_SIGNED_REQUEST = "gpg-signed-request"
    SIGSTORE_SIGNED_REQUEST = "sigstore-signed-request"
    WEBAUTHN_HARDWARE_KEY = "webauthn-hardware-key"


class OperatorRole(StrEnum):
    OBSERVER = "observer"
    PAPER_OPERATOR = "paper-operator"
    INCIDENT_RESPONDER = "incident-responder"
    RISK_REVIEWER = "risk-reviewer"
    SECURITY_REVIEWER = "security-reviewer"
    RELEASE_APPROVER = "release-approver"
    SIGNER_ADMINISTRATOR = "signer-administrator"
    TREASURY_ADMINISTRATOR = "treasury-administrator"
    LIVE_CANARY_OPERATOR = "live-canary-operator"
    BREAK_GLASS_OPERATOR = "break-glass-operator"


class OperatorPermission(StrEnum):
    OBSERVE_STATUS = "observe-status"
    REQUEST_LIVE_CANARY = "request-live-canary"
    REVIEW_LIVE_RISK = "review-live-risk"
    REVIEW_SECURITY = "review-security"
    APPROVE_RELEASE = "approve-release"
    ARM_LIVE_CANARY = "arm-live-canary"
    OPERATE_BREAK_GLASS = "operate-break-glass"
    ADMINISTER_SIGNER = "administer-signer"
    ADMINISTER_TREASURY = "administer-treasury"


class ApprovalLifecycleState(StrEnum):
    REQUESTED = "requested"
    AUTHENTICATED = "authenticated"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    ARMED = "armed"
    EXECUTED = "executed"
    EXPIRED = "expired"
    REVOKED = "revoked"
    REJECTED = "rejected"


_PRODUCTION_AUTH_METHODS = frozenset(
    {
        AuthenticationMethod.GITHUB_OIDC_PROTECTED_ENVIRONMENT,
        AuthenticationMethod.MTLS_CLIENT_CERTIFICATE,
        AuthenticationMethod.SSH_SIGNED_REQUEST,
        AuthenticationMethod.GPG_SIGNED_REQUEST,
        AuthenticationMethod.SIGSTORE_SIGNED_REQUEST,
        AuthenticationMethod.WEBAUTHN_HARDWARE_KEY,
    }
)

_REQUIRED_ROLE_BY_PERMISSION: Mapping[OperatorPermission, frozenset[OperatorRole]] = {
    OperatorPermission.OBSERVE_STATUS: frozenset({OperatorRole.OBSERVER}),
    OperatorPermission.REQUEST_LIVE_CANARY: frozenset(
        {OperatorRole.PAPER_OPERATOR, OperatorRole.INCIDENT_RESPONDER}
    ),
    OperatorPermission.REVIEW_LIVE_RISK: frozenset({OperatorRole.RISK_REVIEWER}),
    OperatorPermission.REVIEW_SECURITY: frozenset({OperatorRole.SECURITY_REVIEWER}),
    OperatorPermission.APPROVE_RELEASE: frozenset({OperatorRole.RELEASE_APPROVER}),
    OperatorPermission.ARM_LIVE_CANARY: frozenset({OperatorRole.LIVE_CANARY_OPERATOR}),
    OperatorPermission.OPERATE_BREAK_GLASS: frozenset({OperatorRole.BREAK_GLASS_OPERATOR}),
    OperatorPermission.ADMINISTER_SIGNER: frozenset({OperatorRole.SIGNER_ADMINISTRATOR}),
    OperatorPermission.ADMINISTER_TREASURY: frozenset(
        {OperatorRole.TREASURY_ADMINISTRATOR}
    ),
}


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Verified operator identity evidence, not caller-supplied display text."""

    issuer: str
    subject: str
    organization: str
    role_bindings: frozenset[OperatorRole]
    authentication_method: AuthenticationMethod
    mfa_verified: bool
    hardware_bound: bool
    issued_at: datetime
    expires_at: datetime
    session_id: str
    credential_id: str
    verified_claims_hash: str
    environment: ControlEnvironment
    revoked: bool = False

    def __post_init__(self) -> None:
        _require_text(self.issuer, "principal.issuer")
        _require_text(self.subject, "principal.subject")
        _require_text(self.organization, "principal.organization")
        _require_text(self.session_id, "principal.session_id")
        _require_text(self.credential_id, "principal.credential_id")
        _require_aware_datetime(self.issued_at, "principal.issued_at")
        _require_aware_datetime(self.expires_at, "principal.expires_at")
        if self.expires_at <= self.issued_at:
            raise OperatorControlPlaneError("principal expiry must be after issuance")
        if not self.role_bindings:
            raise OperatorControlPlaneError("principal requires at least one role binding")
        for role in self.role_bindings:
            if not isinstance(role, OperatorRole):
                raise OperatorControlPlaneError("principal role binding must be OperatorRole")
        object.__setattr__(
            self,
            "verified_claims_hash",
            _require_sha256(self.verified_claims_hash, "verified_claims_hash"),
        )
        if (
            self.environment == ControlEnvironment.PRODUCTION
            and self.authentication_method not in _PRODUCTION_AUTH_METHODS
        ):
            raise OperatorControlPlaneError(
                "production principal requires externally verified authentication"
            )

    def valid_at(self, now: datetime) -> bool:
        _require_aware_datetime(now, "now")
        return self.issued_at <= now < self.expires_at and not self.revoked

    def has_permission(self, permission: OperatorPermission) -> bool:
        required = _REQUIRED_ROLE_BY_PERMISSION[permission]
        return bool(self.role_bindings.intersection(required))

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class OperatorActionRequest:
    """Exact action being approved by authenticated operators."""

    action_id: str
    permission: OperatorPermission
    environment: ControlEnvironment
    request_hash: str
    policy_bundle_hash: str
    release_artifact_hash: str
    scope: str
    reason: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.action_id, "request.action_id")
        _require_text(self.scope, "request.scope")
        _require_text(self.reason, "request.reason")
        _require_aware_datetime(self.issued_at, "request.issued_at")
        _require_aware_datetime(self.expires_at, "request.expires_at")
        if self.expires_at <= self.issued_at:
            raise OperatorControlPlaneError("request expiry must be after issuance")
        for field_name in (
            "request_hash",
            "policy_bundle_hash",
            "release_artifact_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class CryptographicApproval:
    """Signed approval bound to an exact request, policy, release and scope."""

    principal_subject: str
    permission: OperatorPermission
    request_hash: str
    policy_bundle_hash: str
    release_artifact_hash: str
    environment: ControlEnvironment
    scope: str
    signed_at: datetime
    expires_at: datetime
    signature: str
    verification_chain: tuple[str, ...]
    revoked: bool = False

    def __post_init__(self) -> None:
        _require_text(self.principal_subject, "approval.principal_subject")
        _require_text(self.scope, "approval.scope")
        _require_signature(self.signature, "approval.signature")
        if not self.verification_chain:
            raise OperatorControlPlaneError("approval requires verification chain")
        for item in self.verification_chain:
            _require_text(item, "approval.verification_chain")
        _require_aware_datetime(self.signed_at, "approval.signed_at")
        _require_aware_datetime(self.expires_at, "approval.expires_at")
        if self.expires_at <= self.signed_at:
            raise OperatorControlPlaneError("approval expiry must be after signature time")
        for field_name in (
            "request_hash",
            "policy_bundle_hash",
            "release_artifact_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )

    def matches(self, request: OperatorActionRequest) -> bool:
        return (
            self.request_hash == request.request_hash
            and self.policy_bundle_hash == request.policy_bundle_hash
            and self.release_artifact_hash == request.release_artifact_hash
            and self.environment == request.environment
            and self.scope == request.scope
        )

    def valid_at(self, now: datetime) -> bool:
        _require_aware_datetime(now, "now")
        return self.signed_at <= now < self.expires_at and not self.revoked

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class DurableApprovalLifecycle:
    """Authoritative approval lifecycle evidence replayable after restart."""

    durable_store_id: str
    current_state: ApprovalLifecycleState
    last_event_hash: str
    restart_replay_protected: bool
    expired_or_revoked_reuse_blocked: bool
    audit_event_count: int

    def __post_init__(self) -> None:
        _require_text(self.durable_store_id, "lifecycle.durable_store_id")
        object.__setattr__(
            self,
            "last_event_hash",
            _require_sha256(self.last_event_hash, "lifecycle.last_event_hash"),
        )
        if isinstance(self.audit_event_count, bool) or self.audit_event_count <= 0:
            raise OperatorControlPlaneError("lifecycle.audit_event_count must be positive")

    @property
    def durable(self) -> bool:
        return (
            self.current_state in {
                ApprovalLifecycleState.REQUESTED,
                ApprovalLifecycleState.AUTHENTICATED,
                ApprovalLifecycleState.REVIEWED,
                ApprovalLifecycleState.APPROVED,
                ApprovalLifecycleState.ARMED,
            }
            and self.restart_replay_protected
            and self.expired_or_revoked_reuse_blocked
        )

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class SeparationOfDutiesPolicy:
    """Policy proof that high-risk production operations are multi-party."""

    requester_subject: str
    risk_reviewer_subject: str
    security_reviewer_subject: str
    release_approver_subject: str
    final_armer_subject: str
    signer_admin_subject: str | None = None
    treasury_admin_subject: str | None = None
    self_review_forbidden: bool = True
    production_multi_party_required: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "requester_subject",
            "risk_reviewer_subject",
            "security_reviewer_subject",
            "release_approver_subject",
            "final_armer_subject",
        ):
            _require_text(getattr(self, field_name), f"separation.{field_name}")
        if self.signer_admin_subject is not None:
            _require_text(self.signer_admin_subject, "separation.signer_admin_subject")
        if self.treasury_admin_subject is not None:
            _require_text(self.treasury_admin_subject, "separation.treasury_admin_subject")

    @property
    def violations(self) -> tuple[str, ...]:
        violations: list[str] = []
        if not self.self_review_forbidden:
            violations.append("self-review-not-forbidden")
        if not self.production_multi_party_required:
            violations.append("production-multi-party-not-required")
        if self.requester_subject in {
            self.risk_reviewer_subject,
            self.security_reviewer_subject,
            self.release_approver_subject,
            self.final_armer_subject,
        }:
            violations.append("requester-cannot-review-approve-or-arm")
        if self.risk_reviewer_subject == self.final_armer_subject:
            violations.append("risk-reviewer-cannot-arm")
        if self.security_reviewer_subject == self.final_armer_subject:
            violations.append("security-reviewer-cannot-arm")
        if self.release_approver_subject == self.final_armer_subject:
            violations.append("release-approver-cannot-arm")
        if (
            self.signer_admin_subject is not None
            and self.treasury_admin_subject is not None
            and self.signer_admin_subject == self.treasury_admin_subject
        ):
            violations.append("signer-admin-cannot-be-treasury-approver")
        return tuple(dict.fromkeys(violations))

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class BreakGlassGovernance:
    """Break-glass controls that never bypass settlement or wallet safety."""

    enabled: bool
    incident_id: str | None = None
    short_expiry: bool = False
    two_person_approval: bool = False
    immediate_alert: bool = False
    immutable_audit: bool = False
    post_incident_review_required: bool = False
    credential_rotation_required: bool = False
    disables_message_verification: bool = False
    disables_wallet_reserve: bool = False
    disables_ambiguity_latch: bool = False
    disables_finalized_settlement: bool = False

    def __post_init__(self) -> None:
        if self.enabled:
            _require_text(self.incident_id or "", "break_glass.incident_id")

    @property
    def violations(self) -> tuple[str, ...]:
        violations: list[str] = []
        if not self.enabled:
            return ()
        required_flags = {
            "short-expiry-missing": self.short_expiry,
            "two-person-approval-missing": self.two_person_approval,
            "immediate-alert-missing": self.immediate_alert,
            "immutable-audit-missing": self.immutable_audit,
            "post-incident-review-missing": self.post_incident_review_required,
            "credential-rotation-missing": self.credential_rotation_required,
        }
        for reason, ok in required_flags.items():
            if not ok:
                violations.append(reason)
        forbidden_bypasses = {
            "break-glass-disables-message-verification": self.disables_message_verification,
            "break-glass-disables-wallet-reserve": self.disables_wallet_reserve,
            "break-glass-disables-ambiguity-latch": self.disables_ambiguity_latch,
            "break-glass-disables-finalized-settlement": self.disables_finalized_settlement,
        }
        for reason, blocked in forbidden_bypasses.items():
            if blocked:
                violations.append(reason)
        return tuple(dict.fromkeys(violations))

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class ProtectedDeploymentEnvironment:
    """Evidence that production secrets and deployment are approval-gated."""

    environment_name: str
    required_reviewers: int
    prevents_self_review: bool
    branch_or_tag_restricted: bool
    secrets_unavailable_before_approval: bool
    administrator_bypass_disabled: bool
    workload_identity_oidc: bool

    def __post_init__(self) -> None:
        _require_text(self.environment_name, "deployment.environment_name")
        if isinstance(self.required_reviewers, bool) or self.required_reviewers < 2:
            raise OperatorControlPlaneError(
                "deployment requires at least two required reviewers"
            )

    @property
    def production_ready(self) -> bool:
        return (
            self.prevents_self_review
            and self.branch_or_tag_restricted
            and self.secrets_unavailable_before_approval
            and self.administrator_bypass_disabled
            and self.workload_identity_oidc
        )

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class OperatorControlPlanePackage:
    """Full evidence package for PR-162 operator-control review."""

    action_request: OperatorActionRequest
    principals: Mapping[str, AuthenticatedPrincipal]
    approvals: Sequence[CryptographicApproval]
    lifecycle: DurableApprovalLifecycle
    separation: SeparationOfDutiesPolicy
    break_glass: BreakGlassGovernance
    deployment_environment: ProtectedDeploymentEnvironment
    default_live_enabled: bool
    env_can_enable_live: bool
    assembled_at: datetime
    assembled_by: str
    schema_version: str = PR162_OPERATOR_CONTROL_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PR162_OPERATOR_CONTROL_SCHEMA:
            raise OperatorControlPlaneError("unsupported PR-162 package schema")
        _require_aware_datetime(self.assembled_at, "package.assembled_at")
        _require_text(self.assembled_by, "package.assembled_by")
        if not self.principals:
            raise OperatorControlPlaneError("operator control package needs principals")
        if not self.approvals:
            raise OperatorControlPlaneError("operator control package needs approvals")
        for key, principal in self.principals.items():
            if key != principal.subject:
                raise OperatorControlPlaneError("principal mapping key must match subject")

    @property
    def package_sha256(self) -> str:
        return _sha256_payload(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class OperatorControlPlaneReadiness:
    state: OperatorControlPlaneState
    ready_for_manual_control_plane_review: bool
    runtime_live_enabled: bool
    supported_command_can_mutate: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    package_sha256: str
    schema_version: str = PR162_OPERATOR_CONTROL_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_operator_control_plane(
    package: OperatorControlPlanePackage,
    *,
    now: datetime | None = None,
) -> OperatorControlPlaneReadiness:
    """Evaluate PR-162 evidence without enabling live or mutating state."""

    evaluation_time = package.assembled_at if now is None else now
    _require_aware_datetime(evaluation_time, "now")
    blockers: list[str] = []
    warnings: list[str] = []

    _block(blockers, not package.default_live_enabled, "DEFAULT_LIVE_ENABLED")
    _block(blockers, not package.env_can_enable_live, "ENV_CAN_ENABLE_LIVE")
    _block(blockers, package.lifecycle.durable, "APPROVAL_LIFECYCLE_NOT_DURABLE")
    _block(
        blockers,
        package.deployment_environment.production_ready,
        "PROTECTED_DEPLOYMENT_ENVIRONMENT_INCOMPLETE",
    )

    for reason in package.separation.violations:
        blockers.append(f"SEPARATION:{reason}")
    for reason in package.break_glass.violations:
        blockers.append(f"BREAK_GLASS:{reason}")

    required_subjects = {
        package.separation.requester_subject: OperatorPermission.REQUEST_LIVE_CANARY,
        package.separation.risk_reviewer_subject: OperatorPermission.REVIEW_LIVE_RISK,
        package.separation.security_reviewer_subject: OperatorPermission.REVIEW_SECURITY,
        package.separation.release_approver_subject: OperatorPermission.APPROVE_RELEASE,
        package.separation.final_armer_subject: OperatorPermission.ARM_LIVE_CANARY,
    }
    for subject, permission in required_subjects.items():
        principal = package.principals.get(subject)
        if principal is None:
            blockers.append(f"PRINCIPAL_MISSING:{subject}")
            continue
        _check_principal(blockers, principal, permission, package.action_request, evaluation_time)

    approval_index = {
        (approval.principal_subject, approval.permission): approval
        for approval in package.approvals
    }
    for subject, permission in required_subjects.items():
        approval = approval_index.get((subject, permission))
        if approval is None:
            blockers.append(f"APPROVAL_MISSING:{subject}:{permission.value}")
            continue
        _check_approval(blockers, approval, package.action_request, evaluation_time)

    if package.action_request.expires_at <= evaluation_time:
        blockers.append("ACTION_REQUEST_EXPIRED")
    if package.assembled_at > evaluation_time:
        warnings.append("ASSEMBLED_AT_AFTER_EVALUATION_TIME")

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    return OperatorControlPlaneReadiness(
        state=(
            OperatorControlPlaneState.READY_FOR_MANUAL_CONTROL_PLANE_REVIEW
            if ready
            else OperatorControlPlaneState.BLOCKED
        ),
        ready_for_manual_control_plane_review=ready,
        runtime_live_enabled=False,
        supported_command_can_mutate=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        package_sha256=package.package_sha256,
    )


def _check_principal(
    blockers: list[str],
    principal: AuthenticatedPrincipal,
    permission: OperatorPermission,
    request: OperatorActionRequest,
    now: datetime,
) -> None:
    if principal.environment != request.environment:
        blockers.append(f"PRINCIPAL_ENVIRONMENT_MISMATCH:{principal.subject}")
    if not principal.valid_at(now):
        blockers.append(f"PRINCIPAL_NOT_VALID:{principal.subject}")
    if not principal.has_permission(permission):
        blockers.append(f"PRINCIPAL_PERMISSION_MISSING:{principal.subject}:{permission.value}")
    if request.environment == ControlEnvironment.PRODUCTION:
        if principal.authentication_method not in _PRODUCTION_AUTH_METHODS:
            blockers.append(f"PRINCIPAL_NOT_PRODUCTION_AUTHENTICATED:{principal.subject}")
        if not principal.mfa_verified:
            blockers.append(f"PRINCIPAL_MFA_MISSING:{principal.subject}")
        if not principal.hardware_bound:
            blockers.append(f"PRINCIPAL_HARDWARE_BOUND_MISSING:{principal.subject}")


def _check_approval(
    blockers: list[str],
    approval: CryptographicApproval,
    request: OperatorActionRequest,
    now: datetime,
) -> None:
    if not approval.matches(request):
        blockers.append(
            f"APPROVAL_NOT_BOUND_TO_REQUEST:{approval.principal_subject}:{approval.permission.value}"
        )
    if not approval.valid_at(now):
        blockers.append(
            f"APPROVAL_NOT_VALID:{approval.principal_subject}:{approval.permission.value}"
        )


def _block(blockers: list[str], condition: bool, reason: str) -> None:
    if not condition:
        blockers.append(reason)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, frozenset):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _stable_json(payload: Any) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise OperatorControlPlaneError(f"{field_name} must be a non-empty string")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise OperatorControlPlaneError(f"{field_name} must be timezone-aware")


def _require_sha256(value: str, field_name: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise OperatorControlPlaneError(f"{field_name} must be a non-placeholder sha256")
    return lowered


def _require_signature(value: str, field_name: str) -> None:
    if not _SIGNATURE_RE.fullmatch(str(value)):
        raise OperatorControlPlaneError(f"{field_name} must be a signed approval blob")


__all__ = [
    "AuthenticatedPrincipal",
    "AuthenticationMethod",
    "BreakGlassGovernance",
    "ControlEnvironment",
    "CryptographicApproval",
    "DurableApprovalLifecycle",
    "OperatorActionRequest",
    "OperatorControlPlaneError",
    "OperatorControlPlanePackage",
    "OperatorControlPlaneReadiness",
    "OperatorControlPlaneState",
    "OperatorPermission",
    "OperatorRole",
    "PR162_OPERATOR_CONTROL_RESULT_SCHEMA",
    "PR162_OPERATOR_CONTROL_SCHEMA",
    "ProtectedDeploymentEnvironment",
    "SeparationOfDutiesPolicy",
    "evaluate_operator_control_plane",
]
