"""Canonical MPR-2612 final production release/promotion authority.

The historical MPR-31 structural gate remains as a fail-closed compatibility
surface. Final release authority is derived by :class:`MPR2612FinalReleaseGate`.
No code in this module enables live execution.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Callable

MPR31_SCHEMA_VERSION = "mpr31.final-production-promotion.v1"
MPR2612_SCHEMA_VERSION = "mpr-2612.final-release-gate.v1"
TARGET_PRODUCT_STATE = "production-ready-default-off"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

REQUIRED_UPSTREAM_MPRS = frozenset(
    {"MPR-25", "MPR-26", "MPR-27", "MPR-28", "MPR-29", "MPR-30"}
)
ALLOWED_DEPENDENCY_KINDS = frozenset(
    {
        "artifact-truth",
        "durable-authority",
        "rooted-provider-plane",
        "exact-economic-execution",
        "continuous-paper-shadow-soak",
        "cryptographic-submission-boundary",
    }
)


class MPR31Error(ValueError):
    """Raised when final-release evidence is malformed."""


class PromotionStatus(StrEnum):
    READY_DEFAULT_OFF = "READY_DEFAULT_OFF"
    BLOCKED = "BLOCKED"


class ReleaseState(StrEnum):
    UNQUALIFIED = "UNQUALIFIED"
    QUALIFIED_DEFAULT_OFF = "QUALIFIED_DEFAULT_OFF"
    RELEASE_REVIEW_PENDING = "RELEASE_REVIEW_PENDING"
    RELEASED_PRODUCTION_DEFAULT_OFF = "RELEASED_PRODUCTION_DEFAULT_OFF"
    RELEASE_SUSPENDED = "RELEASE_SUSPENDED"
    RELEASE_REVOKED = "RELEASE_REVOKED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass(frozen=True, slots=True)
class SignedEvidenceArtifact:
    kind: str
    digest: str
    signature_digest: str
    reviewer_digests: tuple[str, ...]
    issued_at_ns: int
    expires_at_ns: int
    size_bytes: int
    immutable_uri: str

    def __post_init__(self) -> None:
        _require_text(self.kind, "kind")
        _digest(self.digest, "digest")
        _digest(self.signature_digest, "signature_digest")
        _strict_non_negative_int(self.issued_at_ns, "issued_at_ns")
        _strict_non_negative_int(self.expires_at_ns, "expires_at_ns")
        _strict_positive_int(self.size_bytes, "size_bytes")
        _require_text(self.immutable_uri, "immutable_uri")
        if self.issued_at_ns >= self.expires_at_ns:
            raise MPR31Error("MPR31_INVALID_EVIDENCE_TIME_WINDOW")
        if not self.reviewer_digests:
            raise MPR31Error("MPR31_REVIEWER_DIGEST_REQUIRED")
        for reviewer_digest in self.reviewer_digests:
            _digest(reviewer_digest, "reviewer_digest")
        if len(set(self.reviewer_digests)) != len(self.reviewer_digests):
            raise MPR31Error("MPR31_DUPLICATE_REVIEWER_DIGEST")

    @property
    def artifact_hash(self) -> str:
        return _hash_json(_public_payload(self) | {"schema": MPR31_SCHEMA_VERSION})


@dataclass(frozen=True, slots=True)
class UpstreamMprEvidence:
    mpr_id: str
    artifact: SignedEvidenceArtifact

    def __post_init__(self) -> None:
        if self.mpr_id not in REQUIRED_UPSTREAM_MPRS:
            raise MPR31Error("MPR31_UNKNOWN_UPSTREAM_MPR")
        if self.artifact.kind not in ALLOWED_DEPENDENCY_KINDS:
            raise MPR31Error("MPR31_UNKNOWN_UPSTREAM_EVIDENCE_KIND")


@dataclass(frozen=True, slots=True)
class RootedTreasuryEvidence:
    wallet_balance_root_digest: str
    token_inventory_root_digest: str
    provider_quorum_digest: str
    policy_generation_digest: str
    unresolved_exposure_lamports: int
    rolling_loss_lamports: int
    daily_loss_lamports: int
    hard_latch_active: bool

    def __post_init__(self) -> None:
        for name in (
            "wallet_balance_root_digest",
            "token_inventory_root_digest",
            "provider_quorum_digest",
            "policy_generation_digest",
        ):
            _digest(getattr(self, name), name)
        _strict_non_negative_int(
            self.unresolved_exposure_lamports,
            "unresolved_exposure_lamports",
        )
        _strict_non_negative_int(
            self.rolling_loss_lamports,
            "rolling_loss_lamports",
        )
        _strict_non_negative_int(
            self.daily_loss_lamports,
            "daily_loss_lamports",
        )
        _strict_bool(self.hard_latch_active, "hard_latch_active")


@dataclass(frozen=True, slots=True)
class ImmutableArchiveEvidence:
    exported_segment_digest: str
    remote_receipt_quorum_digest: str
    immutable_object_digest: str
    signed_head_digest: str
    retention_policy_digest: str
    replay_verified: bool

    def __post_init__(self) -> None:
        for name in (
            "exported_segment_digest",
            "remote_receipt_quorum_digest",
            "immutable_object_digest",
            "signed_head_digest",
            "retention_policy_digest",
        ):
            _digest(getattr(self, name), name)
        _strict_bool(self.replay_verified, "replay_verified")


@dataclass(frozen=True, slots=True)
class OperatorCommandEvidence:
    principal_digest: str
    role_session_digest: str
    command_digest: str
    command_signature_digest: str
    mfa_freshness_digest: str
    not_before_ns: int
    expires_at_ns: int

    def __post_init__(self) -> None:
        for name in (
            "principal_digest",
            "role_session_digest",
            "command_digest",
            "command_signature_digest",
            "mfa_freshness_digest",
        ):
            _digest(getattr(self, name), name)
        _strict_non_negative_int(self.not_before_ns, "not_before_ns")
        _strict_non_negative_int(self.expires_at_ns, "expires_at_ns")
        if self.not_before_ns >= self.expires_at_ns:
            raise MPR31Error("MPR31_INVALID_OPERATOR_COMMAND_WINDOW")


@dataclass(frozen=True, slots=True)
class TinyCanaryProposal:
    manual_transaction_count: int
    max_canary_loss_lamports: int
    rollback_plan_digest: str
    post_canary_review_required: bool
    live_expansion_requested: bool

    def __post_init__(self) -> None:
        _strict_positive_int(
            self.manual_transaction_count,
            "manual_transaction_count",
        )
        _strict_non_negative_int(
            self.max_canary_loss_lamports,
            "max_canary_loss_lamports",
        )
        _digest(self.rollback_plan_digest, "rollback_plan_digest")
        _strict_bool(
            self.post_canary_review_required,
            "post_canary_review_required",
        )
        _strict_bool(
            self.live_expansion_requested,
            "live_expansion_requested",
        )


@dataclass(frozen=True, slots=True)
class FinalPromotionBundle:
    """Historical MPR-31 input retained for compatibility only."""

    source_digest: str
    wheel_digest: str
    image_digest: str
    config_digest: str
    policy_digest: str
    upstream_mprs: tuple[UpstreamMprEvidence, ...]
    treasury: RootedTreasuryEvidence
    archive: ImmutableArchiveEvidence
    operator_command: OperatorCommandEvidence
    canary: TinyCanaryProposal
    now_ns: int
    live_runtime_requested: bool = False

    def __post_init__(self) -> None:
        for name in (
            "source_digest",
            "wheel_digest",
            "image_digest",
            "config_digest",
            "policy_digest",
        ):
            _digest(getattr(self, name), name)
        _strict_non_negative_int(self.now_ns, "now_ns")
        _strict_bool(self.live_runtime_requested, "live_runtime_requested")

    @property
    def bundle_hash(self) -> str:
        return _hash_json(_public_payload(self))


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    status: PromotionStatus
    reason_codes: tuple[str, ...]
    bundle_hash: str
    canary_authorized_default_off: bool

    @property
    def ready(self) -> bool:
        return self.status is PromotionStatus.READY_DEFAULT_OFF


@dataclass(frozen=True, slots=True)
class MPR2611Qualification:
    schema_version: str
    release_id: str
    source_commit: str
    source_tree_digest: str
    wheel_digest: str
    runtime_image_digest: str
    signer_image_digest: str | None
    config_generation_digest: str
    policy_generation_digest: str
    production_debt_digest: str
    runtime_authority_digest: str
    dependency_closure_digest: str
    sbom_provenance_digest: str
    platform_matrix_digest: str
    predecessor_evidence_digest: str
    qualification_semantic_digest: str
    production_qualification_passed: bool
    eligible_for_release_review: bool
    release_claim_allowed: bool
    live_enabled: bool
    unresolved_p0_blockers: int

    def __post_init__(self) -> None:
        _require_text(self.schema_version, "schema_version")
        _require_text(self.release_id, "release_id")
        _commit_id(self.source_commit, "source_commit")
        for name in (
            "source_tree_digest",
            "wheel_digest",
            "runtime_image_digest",
            "config_generation_digest",
            "policy_generation_digest",
            "production_debt_digest",
            "runtime_authority_digest",
            "dependency_closure_digest",
            "sbom_provenance_digest",
            "platform_matrix_digest",
            "predecessor_evidence_digest",
            "qualification_semantic_digest",
        ):
            _digest(getattr(self, name), name)
        if self.signer_image_digest is not None:
            _digest(self.signer_image_digest, "signer_image_digest")
        for name in (
            "production_qualification_passed",
            "eligible_for_release_review",
            "release_claim_allowed",
            "live_enabled",
        ):
            _strict_bool(getattr(self, name), name)
        _strict_non_negative_int(
            self.unresolved_p0_blockers,
            "unresolved_p0_blockers",
        )

    @property
    def semantic_digest(self) -> str:
        payload = _public_payload(self).copy()
        payload.pop("qualification_semantic_digest")
        return _hash_json(payload)


@dataclass(frozen=True, slots=True)
class ReleaseProposal:
    release_id: str
    source_commit: str
    source_tree_digest: str
    wheel_digest: str
    runtime_image_digest: str
    signer_image_digest: str | None
    config_generation_digest: str
    policy_generation_digest: str
    qualification_digest: str
    runtime_authority_digest: str
    production_surface_digest: str
    production_debt_digest: str
    sbom_provenance_digest: str
    platform_matrix_digest: str
    rollback_target_generation: int
    created_at_ns: int
    not_before_ns: int
    expires_at_ns: int
    proposer_principal: str
    proposal_nonce: str
    requested_state: ReleaseState = ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF
    live_enabled: bool = False
    unrestricted_live_allowed: bool = False
    automatic_scale_up_allowed: bool = False

    def __post_init__(self) -> None:
        _require_text(self.release_id, "release_id")
        _commit_id(self.source_commit, "source_commit")
        for name in (
            "source_tree_digest",
            "wheel_digest",
            "runtime_image_digest",
            "config_generation_digest",
            "policy_generation_digest",
            "qualification_digest",
            "runtime_authority_digest",
            "production_surface_digest",
            "production_debt_digest",
            "sbom_provenance_digest",
            "platform_matrix_digest",
        ):
            _digest(getattr(self, name), name)
        if self.signer_image_digest is not None:
            _digest(self.signer_image_digest, "signer_image_digest")
        _strict_non_negative_int(
            self.rollback_target_generation,
            "rollback_target_generation",
        )
        _strict_non_negative_int(self.created_at_ns, "created_at_ns")
        _strict_non_negative_int(self.not_before_ns, "not_before_ns")
        _strict_non_negative_int(self.expires_at_ns, "expires_at_ns")
        if not (self.created_at_ns <= self.not_before_ns < self.expires_at_ns):
            raise MPR31Error("MPR2612_INVALID_PROPOSAL_WINDOW")
        _require_text(self.proposer_principal, "proposer_principal")
        _require_text(self.proposal_nonce, "proposal_nonce")
        for name in (
            "live_enabled",
            "unrestricted_live_allowed",
            "automatic_scale_up_allowed",
        ):
            _strict_bool(getattr(self, name), name)

    @property
    def proposal_digest(self) -> str:
        return _hash_json(_public_payload(self))


@dataclass(frozen=True, slots=True)
class ReleaseApproval:
    principal_id: str
    public_key_id: str
    role: str
    release_id: str
    proposal_digest: str
    qualification_digest: str
    issued_at_ns: int
    not_before_ns: int
    expires_at_ns: int
    signature: str

    def __post_init__(self) -> None:
        for name in (
            "principal_id",
            "public_key_id",
            "role",
            "release_id",
            "signature",
        ):
            _require_text(getattr(self, name), name)
        _digest(self.proposal_digest, "proposal_digest")
        _digest(self.qualification_digest, "qualification_digest")
        for name in ("issued_at_ns", "not_before_ns", "expires_at_ns"):
            _strict_non_negative_int(getattr(self, name), name)
        if not (self.issued_at_ns <= self.not_before_ns < self.expires_at_ns):
            raise MPR31Error("MPR2612_INVALID_APPROVAL_WINDOW")

    def signed_payload(self) -> bytes:
        payload = {
            "schema_version": MPR2612_SCHEMA_VERSION,
            "principal_id": self.principal_id,
            "public_key_id": self.public_key_id,
            "role": self.role,
            "release_id": self.release_id,
            "proposal_digest": self.proposal_digest,
            "qualification_digest": self.qualification_digest,
            "issued_at_ns": self.issued_at_ns,
            "not_before_ns": self.not_before_ns,
            "expires_at_ns": self.expires_at_ns,
        }
        return _canonical_json(payload).encode("utf-8")


@dataclass(frozen=True, slots=True)
class FinalReleaseDecision:
    state: ReleaseState
    allowed: bool
    reason_codes: tuple[str, ...]
    release_id: str
    proposal_digest: str
    qualification_digest: str
    production_ready: bool
    release_claim_allowed: bool
    product_state: str
    live_enabled: bool = False
    unrestricted_live_allowed: bool = False
    automatic_scale_up_allowed: bool = False


SignatureVerifier = Callable[[ReleaseApproval, bytes], bool]
QualificationVerifier = Callable[[MPR2611Qualification], bool]
TrustResolver = Callable[[ReleaseApproval], str | None]


class MPR2612FinalReleaseGate:
    """Canonical fail-closed MPR-2612 release-review gate."""

    def __init__(
        self,
        *,
        qualification_verifier: QualificationVerifier,
        signature_verifier: SignatureVerifier,
        trust_resolver: TrustResolver,
        minimum_human_approvals: int = 2,
    ) -> None:
        if minimum_human_approvals < 2:
            raise MPR31Error("MPR2612_MINIMUM_TWO_HUMANS_REQUIRED")
        self.qualification_verifier = qualification_verifier
        self.signature_verifier = signature_verifier
        self.trust_resolver = trust_resolver
        self.minimum_human_approvals = minimum_human_approvals

    def evaluate(
        self,
        qualification: MPR2611Qualification,
        proposal: ReleaseProposal,
        approvals: tuple[ReleaseApproval, ...],
        *,
        now_ns: int,
        hard_safety_latch_active: bool = False,
    ) -> FinalReleaseDecision:
        _strict_non_negative_int(now_ns, "now_ns")
        _strict_bool(
            hard_safety_latch_active,
            "hard_safety_latch_active",
        )
        reasons: list[str] = []

        self._check_qualification(qualification, reasons)
        self._check_bindings(qualification, proposal, reasons)
        self._check_proposal(
            proposal,
            now_ns=now_ns,
            hard_safety_latch_active=hard_safety_latch_active,
            reasons=reasons,
        )
        self._check_approvals(
            qualification,
            proposal,
            approvals,
            now_ns=now_ns,
            reasons=reasons,
        )

        final_reasons = tuple(sorted(set(reasons)))
        allowed = not final_reasons
        return FinalReleaseDecision(
            state=(
                ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF
                if allowed
                else ReleaseState.RELEASE_REVIEW_PENDING
            ),
            allowed=allowed,
            reason_codes=final_reasons,
            release_id=proposal.release_id,
            proposal_digest=proposal.proposal_digest,
            qualification_digest=qualification.qualification_semantic_digest,
            production_ready=allowed,
            release_claim_allowed=allowed,
            product_state=(TARGET_PRODUCT_STATE if allowed else "not-production-ready"),
            live_enabled=False,
            unrestricted_live_allowed=False,
            automatic_scale_up_allowed=False,
        )

    def _check_qualification(
        self,
        qualification: MPR2611Qualification,
        reasons: list[str],
    ) -> None:
        if not qualification.schema_version.lower().startswith("mpr-2611"):
            reasons.append("BLOCKED_QUALIFICATION_SCHEMA")
        if qualification.semantic_digest != qualification.qualification_semantic_digest:
            reasons.append("BLOCKED_QUALIFICATION_DIGEST")
        if not self.qualification_verifier(qualification):
            reasons.append("BLOCKED_QUALIFICATION_VERIFIER")
        if (
            not qualification.production_qualification_passed
            or not qualification.eligible_for_release_review
        ):
            reasons.append("BLOCKED_QUALIFICATION")
        if qualification.release_claim_allowed or qualification.live_enabled:
            reasons.append("BLOCKED_QUALIFICATION_PRIVILEGE_ESCALATION")
        if qualification.unresolved_p0_blockers:
            reasons.append("BLOCKED_QUALIFICATION_P0")

    @staticmethod
    def _check_bindings(
        qualification: MPR2611Qualification,
        proposal: ReleaseProposal,
        reasons: list[str],
    ) -> None:
        bindings = (
            (
                proposal.release_id,
                qualification.release_id,
                "BLOCKED_RELEASE_ID_MISMATCH",
            ),
            (
                proposal.source_commit,
                qualification.source_commit,
                "BLOCKED_SOURCE_COMMIT_MISMATCH",
            ),
            (
                proposal.source_tree_digest,
                qualification.source_tree_digest,
                "BLOCKED_SOURCE_TREE_MISMATCH",
            ),
            (
                proposal.wheel_digest,
                qualification.wheel_digest,
                "BLOCKED_WHEEL_MISMATCH",
            ),
            (
                proposal.runtime_image_digest,
                qualification.runtime_image_digest,
                "BLOCKED_RUNTIME_IMAGE_MISMATCH",
            ),
            (
                proposal.signer_image_digest,
                qualification.signer_image_digest,
                "BLOCKED_SIGNER_IMAGE_MISMATCH",
            ),
            (
                proposal.config_generation_digest,
                qualification.config_generation_digest,
                "BLOCKED_CONFIG_GENERATION_MISMATCH",
            ),
            (
                proposal.policy_generation_digest,
                qualification.policy_generation_digest,
                "BLOCKED_POLICY_GENERATION_MISMATCH",
            ),
            (
                proposal.qualification_digest,
                qualification.qualification_semantic_digest,
                "BLOCKED_QUALIFICATION_LINEAGE",
            ),
            (
                proposal.runtime_authority_digest,
                qualification.runtime_authority_digest,
                "BLOCKED_RUNTIME_AUTHORITY_MISMATCH",
            ),
            (
                proposal.production_debt_digest,
                qualification.production_debt_digest,
                "BLOCKED_PRODUCTION_DEBT_MISMATCH",
            ),
            (
                proposal.sbom_provenance_digest,
                qualification.sbom_provenance_digest,
                "BLOCKED_SBOM_PROVENANCE_MISMATCH",
            ),
            (
                proposal.platform_matrix_digest,
                qualification.platform_matrix_digest,
                "BLOCKED_PLATFORM_MATRIX_MISMATCH",
            ),
        )
        for observed, expected, reason in bindings:
            if observed != expected:
                reasons.append(reason)

    @staticmethod
    def _check_proposal(
        proposal: ReleaseProposal,
        *,
        now_ns: int,
        hard_safety_latch_active: bool,
        reasons: list[str],
    ) -> None:
        if proposal.requested_state is not ReleaseState.RELEASED_PRODUCTION_DEFAULT_OFF:
            reasons.append("BLOCKED_INVALID_TARGET_STATE")
        if (
            proposal.live_enabled
            or proposal.unrestricted_live_allowed
            or proposal.automatic_scale_up_allowed
        ):
            reasons.append("BLOCKED_AUTOMATIC_LIVE_REQUEST")
        if now_ns < proposal.not_before_ns:
            reasons.append("BLOCKED_PROPOSAL_NOT_YET_VALID")
        if now_ns >= proposal.expires_at_ns:
            reasons.append("BLOCKED_PROPOSAL_EXPIRED")
        if hard_safety_latch_active:
            reasons.append("BLOCKED_HARD_SAFETY_LATCH")

    def _check_approvals(
        self,
        qualification: MPR2611Qualification,
        proposal: ReleaseProposal,
        approvals: tuple[ReleaseApproval, ...],
        *,
        now_ns: int,
        reasons: list[str],
    ) -> None:
        principals: set[str] = set()
        public_keys: set[str] = set()
        for approval in approvals:
            if approval.release_id != proposal.release_id:
                reasons.append("BLOCKED_APPROVAL_WRONG_RELEASE")
                continue
            if approval.proposal_digest != proposal.proposal_digest:
                reasons.append("BLOCKED_APPROVAL_WRONG_PROPOSAL")
                continue
            if (
                approval.qualification_digest
                != qualification.qualification_semantic_digest
            ):
                reasons.append("BLOCKED_APPROVAL_WRONG_QUALIFICATION")
                continue
            if now_ns < approval.not_before_ns:
                reasons.append("BLOCKED_APPROVAL_NOT_YET_VALID")
                continue
            if now_ns >= approval.expires_at_ns:
                reasons.append("BLOCKED_APPROVAL_EXPIRED")
                continue
            resolved_principal = self.trust_resolver(approval)
            if resolved_principal != approval.principal_id:
                reasons.append("BLOCKED_REVIEWER_IDENTITY")
                continue
            if not self.signature_verifier(
                approval,
                approval.signed_payload(),
            ):
                reasons.append("BLOCKED_SIGNATURE_AUTHENTICITY")
                continue
            if (
                approval.principal_id in principals
                or approval.public_key_id in public_keys
            ):
                reasons.append("BLOCKED_DISTINCT_HUMAN_REVIEW")
                continue
            principals.add(approval.principal_id)
            public_keys.add(approval.public_key_id)
        if len(principals) < self.minimum_human_approvals:
            reasons.append("BLOCKED_HUMAN_APPROVALS")


class MPR31FinalPromotionGate:
    """Historical structural gate; never sufficient for final release."""

    def evaluate(self, bundle: FinalPromotionBundle) -> PromotionDecision:
        reasons = ["MPR2612_CANONICAL_RELEASE_GATE_REQUIRED"]
        if bundle.live_runtime_requested:
            reasons.append("MPR31_LIVE_RUNTIME_MUST_REMAIN_DEFAULT_OFF")
        if bundle.canary.live_expansion_requested:
            reasons.append("MPR31_CANARY_EXPANSION_FORBIDDEN")
        if bundle.treasury.hard_latch_active:
            reasons.append("MPR31_HARD_LATCH_ACTIVE")
        if bundle.treasury.unresolved_exposure_lamports:
            reasons.append("MPR31_UNRESOLVED_EXPOSURE")
        return PromotionDecision(
            status=PromotionStatus.BLOCKED,
            reason_codes=tuple(sorted(set(reasons))),
            bundle_hash=bundle.bundle_hash,
            canary_authorized_default_off=False,
        )


def _public_payload(value: object) -> dict[str, Any]:
    if not is_dataclass(value):
        raise TypeError("expected dataclass payload")
    return {
        field.name: _canonical_value(getattr(value, field.name))
        for field in fields(value)
    }


def _canonical_value(value: object) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: _canonical_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonical_value(item) for key, item in value.items()}
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _digest(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise MPR31Error(f"{name} must be a lowercase sha256 digest")


def _commit_id(value: str, name: str) -> None:
    if not isinstance(value, str) or not _GIT_OBJECT_ID.fullmatch(value):
        raise MPR31Error(f"{name} must be a lowercase git object id")


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise MPR31Error(f"{name} must be non-empty text")


def _strict_bool(value: bool, name: str) -> None:
    if type(value) is not bool:
        raise MPR31Error(f"{name} must be bool")


def _strict_non_negative_int(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise MPR31Error(f"{name} must be a non-negative integer")


def _strict_positive_int(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise MPR31Error(f"{name} must be a positive integer")


__all__ = [
    "ALLOWED_DEPENDENCY_KINDS",
    "FinalPromotionBundle",
    "FinalReleaseDecision",
    "ImmutableArchiveEvidence",
    "MPR31Error",
    "MPR31FinalPromotionGate",
    "MPR31_SCHEMA_VERSION",
    "MPR2611Qualification",
    "MPR2612FinalReleaseGate",
    "MPR2612_SCHEMA_VERSION",
    "OperatorCommandEvidence",
    "PromotionDecision",
    "PromotionStatus",
    "REQUIRED_UPSTREAM_MPRS",
    "ReleaseApproval",
    "ReleaseProposal",
    "ReleaseState",
    "RootedTreasuryEvidence",
    "SignedEvidenceArtifact",
    "TARGET_PRODUCT_STATE",
    "TinyCanaryProposal",
    "UpstreamMprEvidence",
]
