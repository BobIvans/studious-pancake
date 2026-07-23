"""PR-203 final promotion governance gate.

This module is deliberately offline and sender-free. It validates already
materialized release, legacy-surface, assurance, approval, rollback and tiny
canary evidence before a release may be considered ready for a manual final
canary review. It never signs, submits, scales, arms live mode or mutates
runtime state.
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

PR203_SCHEMA_VERSION = "pr203.final-promotion-governance.v1"
PR203_RESULT_SCHEMA_VERSION = "pr203.final-promotion-governance-result.v1"
MAX_TINY_CANARY_CAPITAL_LAMPORTS = 50_000_000
REQUIRED_PREREQUISITES = (
    "pr200.accepted-shadow-soak",
    "pr201.accepted-release-manifest",
)
REQUIRED_ASSURANCE_ROLES = (
    "protocol-vectors",
    "signer-permit",
    "transaction-firewall",
    "accounting",
    "failure-recovery",
)
REQUIRED_APPROVAL_ROLES = (
    "release-owner",
    "independent-second-approver",
)
REQUIRED_ROLLBACK_TRIGGERS = (
    "invariant",
    "slo",
    "provider-drift",
    "balance-mismatch",
    "ambiguous-settlement",
    "approval-expiry",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class FinalPromotionGovernanceError(ValueError):
    """Raised when PR-203 governance evidence is malformed."""


class FinalPromotionState(StrEnum):
    BLOCKED = "blocked"
    READY_FOR_MANUAL_TINY_CANARY_REVIEW = "ready-for-manual-tiny-canary-review"


@dataclass(frozen=True, slots=True)
class AcceptedEvidenceRef:
    name: str
    sha256: str
    source_commit: str
    accepted: bool
    human_reviewed: bool
    reviewer: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_text(self.name, "evidence.name"))
        object.__setattr__(self, "sha256", _require_sha256(self.sha256, "sha256"))
        object.__setattr__(
            self,
            "source_commit",
            _require_git_sha(self.source_commit, "source_commit"),
        )
        _require_bool(self.accepted, "accepted")
        _require_bool(self.human_reviewed, "human_reviewed")
        object.__setattr__(
            self,
            "reviewer",
            (
                _require_text(self.reviewer, "evidence.reviewer")
                if self.human_reviewed
                else self.reviewer
            ),
        )


@dataclass(frozen=True, slots=True)
class LegacySurfaceEvidence:
    release_wheel_forbidden_imports_present: tuple[str, ...]
    release_image_forbidden_imports_present: tuple[str, ...]
    supported_entrypoint_forbidden_reachability: tuple[str, ...]
    duplicate_runtime_paths_removed: bool
    stale_pr_workflows_removed: bool
    final_docs_reduced_to_current_set: bool
    canonical_runbook_sha256: str
    architecture_doc_sha256: str
    threat_model_sha256: str
    evidence_index_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "release_wheel_forbidden_imports_present",
            "release_image_forbidden_imports_present",
            "supported_entrypoint_forbidden_reachability",
        ):
            object.__setattr__(
                self,
                field_name,
                _tuple_of_text(getattr(self, field_name), field_name),
            )
        for field_name in (
            "duplicate_runtime_paths_removed",
            "stale_pr_workflows_removed",
            "final_docs_reduced_to_current_set",
        ):
            _require_bool(getattr(self, field_name), field_name)
        for field_name in (
            "canonical_runbook_sha256",
            "architecture_doc_sha256",
            "threat_model_sha256",
            "evidence_index_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class IndependentAssuranceReview:
    role: str
    reviewer: str
    artifact_sha256: str
    source_commit: str
    accepted: bool
    reviewed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _require_text(self.role, "assurance.role"))
        object.__setattr__(
            self,
            "reviewer",
            _require_text(self.reviewer, "assurance.reviewer"),
        )
        object.__setattr__(
            self,
            "artifact_sha256",
            _require_sha256(self.artifact_sha256, "assurance.artifact_sha256"),
        )
        object.__setattr__(
            self,
            "source_commit",
            _require_git_sha(self.source_commit, "assurance.source_commit"),
        )
        _require_bool(self.accepted, "assurance.accepted")
        _require_aware(self.reviewed_at, "assurance.reviewed_at")


@dataclass(frozen=True, slots=True)
class TinyCanaryPolicy:
    release_hash: str
    config_hash: str
    strategy_id: str
    pair: str
    max_capital_lamports: int
    max_transaction_count: int
    max_daily_loss_lamports: int
    max_fee_lamports: int
    max_tip_lamports: int
    max_uncertainty_lamports: int
    manual_first_transaction_review: bool
    no_automatic_scale_up: bool

    def __post_init__(self) -> None:
        for field_name in ("release_hash", "config_hash"):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )
        for field_name in ("strategy_id", "pair"):
            object.__setattr__(
                self,
                field_name,
                _require_text(getattr(self, field_name), field_name),
            )
        for field_name in (
            "max_capital_lamports",
            "max_transaction_count",
            "max_daily_loss_lamports",
            "max_fee_lamports",
            "max_tip_lamports",
            "max_uncertainty_lamports",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_positive_int(getattr(self, field_name), field_name),
            )
        _require_bool(
            self.manual_first_transaction_review,
            "manual_first_transaction_review",
        )
        _require_bool(self.no_automatic_scale_up, "no_automatic_scale_up")


@dataclass(frozen=True, slots=True)
class DualApprovalSignature:
    approval_id: str
    approver: str
    role: str
    signed_release_hash: str
    signed_config_hash: str
    signature_sha256: str
    signed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("approval_id", "approver", "role"):
            object.__setattr__(
                self,
                field_name,
                _require_text(getattr(self, field_name), field_name),
            )
        for field_name in (
            "signed_release_hash",
            "signed_config_hash",
            "signature_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )
        _require_aware(self.signed_at, "approval.signed_at")
        _require_aware(self.expires_at, "approval.expires_at")
        if self.expires_at <= self.signed_at:
            raise FinalPromotionGovernanceError(
                "approval must expire after it is signed"
            )


@dataclass(frozen=True, slots=True)
class RollbackTriggerEvidence:
    name: str
    automatic_rollback_to_shadow: bool
    kill_switch_armed: bool
    preserves_evidence: bool
    tested: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _require_text(self.name, "trigger.name"))
        for field_name in (
            "automatic_rollback_to_shadow",
            "kill_switch_armed",
            "preserves_evidence",
            "tested",
        ):
            _require_bool(getattr(self, field_name), f"trigger.{field_name}")


@dataclass(frozen=True, slots=True)
class FinalPromotionGovernanceBundle:
    release_hash: str
    config_hash: str
    source_commit: str
    prerequisites: tuple[AcceptedEvidenceRef, ...]
    legacy_surface: LegacySurfaceEvidence
    independent_assurance: tuple[IndependentAssuranceReview, ...]
    tiny_canary: TinyCanaryPolicy
    approvals: tuple[DualApprovalSignature, ...]
    rollback_triggers: tuple[RollbackTriggerEvidence, ...]
    post_canary_finalized_evidence_required: bool
    staged_expansion_requires_new_review: bool
    assembled_at: datetime
    assembled_by: str
    schema_version: str = PR203_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR203_SCHEMA_VERSION:
            raise FinalPromotionGovernanceError("unsupported PR-203 schema")
        object.__setattr__(
            self,
            "release_hash",
            _require_sha256(self.release_hash, "release_hash"),
        )
        object.__setattr__(
            self,
            "config_hash",
            _require_sha256(self.config_hash, "config_hash"),
        )
        object.__setattr__(
            self,
            "source_commit",
            _require_git_sha(self.source_commit, "source_commit"),
        )
        for field_name in (
            "post_canary_finalized_evidence_required",
            "staged_expansion_requires_new_review",
        ):
            _require_bool(getattr(self, field_name), field_name)
        _require_aware(self.assembled_at, "assembled_at")
        object.__setattr__(
            self,
            "assembled_by",
            _require_text(self.assembled_by, "assembled_by"),
        )


@dataclass(frozen=True, slots=True)
class FinalPromotionGovernanceReadiness:
    state: FinalPromotionState
    ready_for_manual_tiny_canary_review: bool
    live_execution_allowed: bool
    canary_submission_allowed: bool
    automatic_scale_up_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_hash: str
    checks_evaluated: int
    schema_version: str = PR203_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_final_promotion_governance(
    bundle: FinalPromotionGovernanceBundle,
) -> FinalPromotionGovernanceReadiness:
    """Return PR-203 final governance readiness without enabling live execution."""

    blockers: list[str] = []
    warnings: list[str] = []
    checks = 0

    def check(condition: bool, code: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(code)

    _evaluate_prerequisites(bundle, check)
    _evaluate_legacy_surface(bundle.legacy_surface, check)
    _evaluate_assurance(bundle, check)
    _evaluate_tiny_canary(bundle, check)
    _evaluate_approvals(bundle, check)
    _evaluate_rollback(bundle.rollback_triggers, check)
    check(
        bundle.post_canary_finalized_evidence_required,
        "POST_CANARY_FINALIZED_EVIDENCE_NOT_REQUIRED",
    )
    check(
        bundle.staged_expansion_requires_new_review,
        "STAGED_EXPANSION_CAN_AUTOSCALE",
    )

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    if ready:
        warnings.append("PR203_REVIEW_ONLY_LIVE_REMAINS_DENIED")
    return FinalPromotionGovernanceReadiness(
        state=(
            FinalPromotionState.READY_FOR_MANUAL_TINY_CANARY_REVIEW
            if ready
            else FinalPromotionState.BLOCKED
        ),
        ready_for_manual_tiny_canary_review=ready,
        live_execution_allowed=False,
        canary_submission_allowed=False,
        automatic_scale_up_allowed=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        evidence_hash=_sha256_payload(bundle),
        checks_evaluated=checks,
    )


def _evaluate_prerequisites(
    bundle: FinalPromotionGovernanceBundle,
    check: Any,
) -> None:
    evidence_by_name = {item.name: item for item in bundle.prerequisites}
    check(
        len(evidence_by_name) == len(bundle.prerequisites),
        "DUPLICATE_PREREQUISITE_EVIDENCE",
    )
    for name in REQUIRED_PREREQUISITES:
        evidence = evidence_by_name.get(name)
        check(evidence is not None, f"PREREQUISITE_MISSING:{name}")
        if evidence is None:
            continue
        _evaluate_accepted_evidence(evidence, f"PREREQUISITE:{name}", check)
        check(
            evidence.source_commit == bundle.source_commit,
            f"PREREQUISITE_SOURCE_COMMIT_MISMATCH:{name}",
        )


def _evaluate_accepted_evidence(
    evidence: AcceptedEvidenceRef,
    prefix: str,
    check: Any,
) -> None:
    check(evidence.accepted, f"{prefix}:NOT_ACCEPTED")
    check(evidence.human_reviewed, f"{prefix}:NOT_HUMAN_REVIEWED")
    check(bool(evidence.reviewer.strip()), f"{prefix}:REVIEWER_MISSING")


def _evaluate_legacy_surface(surface: LegacySurfaceEvidence, check: Any) -> None:
    for item in surface.release_wheel_forbidden_imports_present:
        check(False, f"WHEEL_FORBIDDEN_IMPORT_PRESENT:{item}")
    for item in surface.release_image_forbidden_imports_present:
        check(False, f"IMAGE_FORBIDDEN_IMPORT_PRESENT:{item}")
    for item in surface.supported_entrypoint_forbidden_reachability:
        check(False, f"ENTRYPOINT_REACHES_FORBIDDEN_PATH:{item}")
    check(
        surface.duplicate_runtime_paths_removed, "DUPLICATE_RUNTIME_PATHS_NOT_REMOVED"
    )
    check(surface.stale_pr_workflows_removed, "STALE_PR_WORKFLOWS_NOT_REMOVED")
    check(
        surface.final_docs_reduced_to_current_set,
        "FINAL_DOCS_NOT_REDUCED_TO_CURRENT_SET",
    )


def _evaluate_assurance(
    bundle: FinalPromotionGovernanceBundle,
    check: Any,
) -> None:
    reviews_by_role = {review.role: review for review in bundle.independent_assurance}
    check(
        len(reviews_by_role) == len(bundle.independent_assurance),
        "DUPLICATE_ASSURANCE_ROLE",
    )
    reviewers: set[str] = set()
    for role in REQUIRED_ASSURANCE_ROLES:
        review = reviews_by_role.get(role)
        check(review is not None, f"ASSURANCE_ROLE_MISSING:{role}")
        if review is None:
            continue
        reviewers.add(review.reviewer)
        check(review.accepted, f"ASSURANCE_NOT_ACCEPTED:{role}")
        check(
            review.source_commit == bundle.source_commit,
            f"ASSURANCE_SOURCE_COMMIT_MISMATCH:{role}",
        )
        check(
            review.reviewed_at <= bundle.assembled_at,
            f"ASSURANCE_AFTER_ASSEMBLY:{role}",
        )
        check(
            review.reviewer != bundle.assembled_by, f"ASSURANCE_NOT_INDEPENDENT:{role}"
        )
    check(len(reviewers) >= 2, "ASSURANCE_REQUIRES_TWO_DISTINCT_REVIEWERS")


def _evaluate_tiny_canary(
    bundle: FinalPromotionGovernanceBundle,
    check: Any,
) -> None:
    policy = bundle.tiny_canary
    check(policy.release_hash == bundle.release_hash, "CANARY_RELEASE_HASH_MISMATCH")
    check(policy.config_hash == bundle.config_hash, "CANARY_CONFIG_HASH_MISMATCH")
    check(
        policy.max_capital_lamports <= MAX_TINY_CANARY_CAPITAL_LAMPORTS,
        "CANARY_CAPITAL_NOT_TINY",
    )
    check(policy.max_transaction_count == 1, "CANARY_REQUIRES_SINGLE_TRANSACTION")
    check(
        policy.max_daily_loss_lamports <= policy.max_capital_lamports,
        "CANARY_DAILY_LOSS_EXCEEDS_CAPITAL",
    )
    check(
        policy.max_fee_lamports <= policy.max_daily_loss_lamports,
        "CANARY_FEE_LIMIT_EXCEEDS_DAILY_LOSS",
    )
    check(
        policy.max_tip_lamports <= policy.max_daily_loss_lamports,
        "CANARY_TIP_LIMIT_EXCEEDS_DAILY_LOSS",
    )
    check(
        policy.max_uncertainty_lamports <= policy.max_daily_loss_lamports,
        "CANARY_UNCERTAINTY_EXCEEDS_DAILY_LOSS",
    )
    check(
        policy.manual_first_transaction_review,
        "FIRST_TRANSACTION_MANUAL_REVIEW_MISSING",
    )
    check(policy.no_automatic_scale_up, "CANARY_AUTOMATIC_SCALE_UP_ALLOWED")


def _evaluate_approvals(
    bundle: FinalPromotionGovernanceBundle,
    check: Any,
) -> None:
    approvals_by_role = {approval.role: approval for approval in bundle.approvals}
    check(len(approvals_by_role) == len(bundle.approvals), "DUPLICATE_APPROVAL_ROLE")
    approval_ids = {approval.approval_id for approval in bundle.approvals}
    check(len(approval_ids) == len(bundle.approvals), "DUPLICATE_APPROVAL_ID")
    approvers: set[str] = set()
    for role in REQUIRED_APPROVAL_ROLES:
        approval = approvals_by_role.get(role)
        check(approval is not None, f"APPROVAL_ROLE_MISSING:{role}")
        if approval is None:
            continue
        approvers.add(approval.approver)
        check(
            approval.signed_release_hash == bundle.release_hash,
            f"APPROVAL_RELEASE_HASH_MISMATCH:{role}",
        )
        check(
            approval.signed_config_hash == bundle.config_hash,
            f"APPROVAL_CONFIG_HASH_MISMATCH:{role}",
        )
        check(
            approval.signed_at <= bundle.assembled_at, f"APPROVAL_AFTER_ASSEMBLY:{role}"
        )
        check(bundle.assembled_at < approval.expires_at, f"APPROVAL_EXPIRED:{role}")
    check(len(approvers) >= 2, "DUAL_APPROVAL_REQUIRES_DISTINCT_APPROVERS")


def _evaluate_rollback(
    triggers: tuple[RollbackTriggerEvidence, ...],
    check: Any,
) -> None:
    trigger_by_name = {trigger.name: trigger for trigger in triggers}
    check(len(trigger_by_name) == len(triggers), "DUPLICATE_ROLLBACK_TRIGGER")
    for name in REQUIRED_ROLLBACK_TRIGGERS:
        trigger = trigger_by_name.get(name)
        check(trigger is not None, f"ROLLBACK_TRIGGER_MISSING:{name}")
        if trigger is None:
            continue
        check(
            trigger.automatic_rollback_to_shadow,
            f"ROLLBACK_NOT_AUTOMATIC:{name}",
        )
        check(trigger.kill_switch_armed, f"KILL_SWITCH_NOT_ARMED:{name}")
        check(trigger.preserves_evidence, f"ROLLBACK_DOES_NOT_PRESERVE_EVIDENCE:{name}")
        check(trigger.tested, f"ROLLBACK_TRIGGER_NOT_TESTED:{name}")


def _require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FinalPromotionGovernanceError(f"{field} must be a non-empty string")
    return value.strip()


def _require_bool(value: bool, field: str) -> None:
    if not isinstance(value, bool):
        raise FinalPromotionGovernanceError(f"{field} must be bool")


def _require_positive_int(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FinalPromotionGovernanceError(f"{field} must be a positive integer")
    return value


def _require_sha256(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise FinalPromotionGovernanceError(f"{field} must be a non-placeholder sha256")
    return lowered


def _require_git_sha(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise FinalPromotionGovernanceError(
            f"{field} must be a non-placeholder git sha"
        )
    return lowered


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FinalPromotionGovernanceError(f"{field} must be timezone-aware")


def _tuple_of_text(value: Sequence[str], field: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)):
        raise FinalPromotionGovernanceError(f"{field} must be a sequence of strings")
    normalized = tuple(_require_text(item, field) for item in value)
    if len(normalized) != len(set(normalized)):
        raise FinalPromotionGovernanceError(f"{field} must not contain duplicates")
    return normalized


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
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


__all__ = [
    "AcceptedEvidenceRef",
    "DualApprovalSignature",
    "FinalPromotionGovernanceBundle",
    "FinalPromotionGovernanceError",
    "FinalPromotionGovernanceReadiness",
    "FinalPromotionState",
    "IndependentAssuranceReview",
    "LegacySurfaceEvidence",
    "MAX_TINY_CANARY_CAPITAL_LAMPORTS",
    "PR203_RESULT_SCHEMA_VERSION",
    "PR203_SCHEMA_VERSION",
    "REQUIRED_APPROVAL_ROLES",
    "REQUIRED_ASSURANCE_ROLES",
    "REQUIRED_PREREQUISITES",
    "REQUIRED_ROLLBACK_TRIGGERS",
    "RollbackTriggerEvidence",
    "TinyCanaryPolicy",
    "evaluate_final_promotion_governance",
]
