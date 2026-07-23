"""MPR-07 operations authority and signed promotion gate.

This module validates already-materialized promotion evidence for the V4 MPR-07
boundary. It is deliberately offline and sender-free: it never imports signer,
sender, wallet, RPC, Jito, provider, or transaction submission code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Mapping, Sequence

SCHEMA_VERSION = "mpr07.operations-promotion-gate.v1"
PRODUCT_ID = "studious-pancake.mpr07.operations-promotion-gate"

_REQUIRED_TELEMETRY_KEYS = (
    "event_loop_lag_ratio",
    "queue_age_ratio",
    "memory_growth_ratio",
    "fd_growth_ratio",
    "backup_age_ratio",
    "soak_age_ratio",
)
_REQUIRED_ARTIFACTS = (
    "source_commit",
    "wheel",
    "image",
    "config",
    "policy",
    "soak",
    "backup",
    "rollback",
)
_REQUIRED_ROLLBACK_TRIGGERS = (
    "failed_settlement",
    "slo_breach",
    "manual_latch",
    "late_landing",
    "evidence_mismatch",
)
_SECRET_MARKERS = (
    "secret",
    "private_key",
    "api_key",
    "apikey",
    "token",
    "authorization",
    "bearer",
    "mnemonic",
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{128}$")


class MPR07State(StrEnum):
    """Final review-only promotion verdict."""

    READY_FOR_MANUAL_TINY_CANARY_REVIEW = "ready-for-manual-tiny-canary-review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class SignedArtifact:
    """One content-addressed release/promotion artifact."""

    label: str
    sha256: str
    signature: str

    def __post_init__(self) -> None:
        _identifier(self.label, "artifact.label")
        _sha256(self.sha256, "artifact.sha256")
        _signature(self.signature, "artifact.signature")

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "sha256": self.sha256,
            "signature": self.signature,
        }


@dataclass(frozen=True, slots=True)
class OperatorApproval:
    """Identity-backed approval over the exact promotion bundle."""

    reviewer_id: str
    role: str
    bundle_hash: str
    public_key_sha256: str
    signature: str
    issued_at_ms: int
    expires_at_ms: int
    revoked: bool = False

    def __post_init__(self) -> None:
        _identifier(self.reviewer_id, "approval.reviewer_id")
        _identifier(self.role, "approval.role")
        _sha256(self.bundle_hash, "approval.bundle_hash")
        _sha256(self.public_key_sha256, "approval.public_key_sha256")
        _signature(self.signature, "approval.signature")
        _non_negative_int(self.issued_at_ms, "approval.issued_at_ms")
        _non_negative_int(self.expires_at_ms, "approval.expires_at_ms")
        if self.expires_at_ms <= self.issued_at_ms:
            raise ValueError("approval expiry must be after issue time")
        if not isinstance(self.revoked, bool):
            raise TypeError("approval.revoked must be boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "reviewer_id": self.reviewer_id,
            "role": self.role,
            "bundle_hash": self.bundle_hash,
            "public_key_sha256": self.public_key_sha256,
            "signature": self.signature,
            "issued_at_ms": self.issued_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "revoked": self.revoked,
        }


@dataclass(frozen=True, slots=True)
class CanaryBudgetEvidence:
    """Worst-case one-transaction canary risk envelope."""

    wallet_capital_lamports: int
    daily_loss_limit_lamports: int
    max_transaction_count: int
    fee_lamports: int
    tip_lamports: int
    rent_lamports: int
    uncertainty_lamports: int
    gross_loss_lamports: int

    def __post_init__(self) -> None:
        for name in (
            "wallet_capital_lamports",
            "daily_loss_limit_lamports",
            "max_transaction_count",
            "fee_lamports",
            "tip_lamports",
            "rent_lamports",
            "uncertainty_lamports",
            "gross_loss_lamports",
        ):
            _non_negative_int(getattr(self, name), f"canary.{name}")
        if self.wallet_capital_lamports <= 0:
            raise ValueError("wallet capital must be positive")
        if self.daily_loss_limit_lamports <= 0:
            raise ValueError("daily loss limit must be positive")
        if self.max_transaction_count != 1:
            raise ValueError("MPR-07 canary must be exactly one transaction")

    @property
    def worst_case_lamports(self) -> int:
        return (
            self.fee_lamports
            + self.tip_lamports
            + self.rent_lamports
            + self.uncertainty_lamports
            + self.gross_loss_lamports
        )

    def within_limits(self) -> bool:
        return (
            self.worst_case_lamports <= self.wallet_capital_lamports
            and self.worst_case_lamports <= self.daily_loss_limit_lamports
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "wallet_capital_lamports": self.wallet_capital_lamports,
            "daily_loss_limit_lamports": self.daily_loss_limit_lamports,
            "max_transaction_count": self.max_transaction_count,
            "fee_lamports": self.fee_lamports,
            "tip_lamports": self.tip_lamports,
            "rent_lamports": self.rent_lamports,
            "uncertainty_lamports": self.uncertainty_lamports,
            "gross_loss_lamports": self.gross_loss_lamports,
            "worst_case_lamports": self.worst_case_lamports,
        }


@dataclass(frozen=True, slots=True)
class MPR07PromotionEvidence:
    """Complete offline evidence bundle for MPR-07 review-gate evaluation."""

    evaluated_at_ms: int
    bundle_hash: str
    telemetry: Mapping[str, float]
    telemetry_collected_at_ms: int
    artifacts: Sequence[SignedArtifact]
    approvals: Sequence[OperatorApproval]
    canary_budget: CanaryBudgetEvidence
    rollback_triggers: Sequence[str]
    automatic_rollback_to_shadow: bool
    post_canary_review_required: bool
    legacy_cleanup_complete: bool
    live_capability_enabled: bool = False
    signer_reachable: bool = False
    sender_reachable: bool = False

    def __post_init__(self) -> None:
        _non_negative_int(self.evaluated_at_ms, "evaluated_at_ms")
        _sha256(self.bundle_hash, "bundle_hash")
        _non_negative_int(self.telemetry_collected_at_ms, "telemetry_collected_at_ms")
        if self.telemetry_collected_at_ms > self.evaluated_at_ms:
            raise ValueError("telemetry cannot be collected in the future")
        if not self.telemetry:
            raise ValueError("telemetry must not be empty")
        if not self.artifacts:
            raise ValueError("artifacts must not be empty")
        if not self.approvals:
            raise ValueError("approvals must not be empty")
        for flag in (
            "automatic_rollback_to_shadow",
            "post_canary_review_required",
            "legacy_cleanup_complete",
            "live_capability_enabled",
            "signer_reachable",
            "sender_reachable",
        ):
            if not isinstance(getattr(self, flag), bool):
                raise TypeError(f"{flag} must be boolean")


@dataclass(frozen=True, slots=True)
class MPR07Violation:
    code: str
    subject: str
    detail: str

    def __post_init__(self) -> None:
        _identifier(self.code, "violation.code")
        if not self.subject:
            raise ValueError("violation.subject must not be empty")
        if not self.detail:
            raise ValueError("violation.detail must not be empty")

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "subject": self.subject,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class MPR07PromotionReport:
    schema_version: str
    product_id: str
    state: MPR07State
    evidence_hash: str
    violations: tuple[MPR07Violation, ...]
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_allowed: bool = False

    @property
    def ready(self) -> bool:
        return self.state is MPR07State.READY_FOR_MANUAL_TINY_CANARY_REVIEW

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_id": self.product_id,
            "state": self.state.value,
            "ready": self.ready,
            "evidence_hash": self.evidence_hash,
            "violation_count": len(self.violations),
            "violations": [violation.to_dict() for violation in self.violations],
            "safety_boundary": {
                "live_execution_allowed": self.live_execution_allowed,
                "signer_allowed": self.signer_allowed,
                "sender_allowed": self.sender_allowed,
            },
        }


def evaluate_mpr07_promotion(
    evidence: MPR07PromotionEvidence,
    *,
    max_telemetry_age_ms: int = 300_000,
    required_roles: Sequence[str] = ("operator", "risk", "security"),
) -> MPR07PromotionReport:
    """Evaluate MPR-07 promotion evidence without enabling live execution."""

    if max_telemetry_age_ms <= 0:
        raise ValueError("max_telemetry_age_ms must be positive")

    violations: list[MPR07Violation] = []
    _check_telemetry(evidence, max_telemetry_age_ms, violations)
    _check_artifacts(evidence, violations)
    _check_approvals(evidence, required_roles, violations)
    _check_canary(evidence, violations)
    _check_rollback(evidence, violations)
    _check_forbidden_surfaces(evidence, violations)

    ordered = tuple(sorted(violations, key=lambda item: (item.code, item.subject)))
    return MPR07PromotionReport(
        schema_version=SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        state=(
            MPR07State.BLOCKED
            if ordered
            else MPR07State.READY_FOR_MANUAL_TINY_CANARY_REVIEW
        ),
        evidence_hash=_evidence_hash(evidence),
        violations=ordered,
    )


def _check_telemetry(
    evidence: MPR07PromotionEvidence,
    max_age_ms: int,
    violations: list[MPR07Violation],
) -> None:
    missing = [key for key in _REQUIRED_TELEMETRY_KEYS if key not in evidence.telemetry]
    for key in missing:
        violations.append(
            MPR07Violation(
                "missing_telemetry",
                key,
                "required observability/readiness metric is absent",
            )
        )
    if evidence.evaluated_at_ms - evidence.telemetry_collected_at_ms > max_age_ms:
        violations.append(
            MPR07Violation(
                "stale_telemetry",
                "telemetry_collected_at_ms",
                "telemetry is older than the allowed freshness window",
            )
        )
    for key, value in evidence.telemetry.items():
        _identifier(key, f"telemetry:{key}")
        if any(marker in key.lower() for marker in _SECRET_MARKERS):
            violations.append(
                MPR07Violation(
                    "secret_like_telemetry_key",
                    key,
                    "telemetry key name suggests secret-bearing data",
                )
            )
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            violations.append(
                MPR07Violation(
                    "non_finite_telemetry",
                    key,
                    "telemetry value must be a finite number",
                )
            )
            continue
        if float(value) < 0.0 or float(value) > 1.0:
            violations.append(
                MPR07Violation(
                    "telemetry_out_of_budget",
                    key,
                    "telemetry ratio must be inside the normalized 0..1 SLO envelope",
                )
            )


def _check_artifacts(
    evidence: MPR07PromotionEvidence,
    violations: list[MPR07Violation],
) -> None:
    by_label = {artifact.label: artifact for artifact in evidence.artifacts}
    for label in _REQUIRED_ARTIFACTS:
        if label not in by_label:
            violations.append(
                MPR07Violation(
                    "missing_signed_artifact",
                    label,
                    "promotion bundle is missing a required signed artifact",
                )
            )


def _check_approvals(
    evidence: MPR07PromotionEvidence,
    required_roles: Sequence[str],
    violations: list[MPR07Violation],
) -> None:
    if len(set(required_roles)) != len(tuple(required_roles)):
        raise ValueError("required roles must be unique")
    active_by_role: dict[str, OperatorApproval] = {}
    seen_reviewers: set[str] = set()
    for approval in evidence.approvals:
        if approval.bundle_hash != evidence.bundle_hash:
            violations.append(
                MPR07Violation(
                    "approval_bundle_mismatch",
                    approval.reviewer_id,
                    "approval is not bound to the evaluated promotion bundle",
                )
            )
        if approval.issued_at_ms > evidence.evaluated_at_ms:
            violations.append(
                MPR07Violation(
                    "approval_not_yet_valid",
                    approval.reviewer_id,
                    "approval issue time is after trusted evaluation time",
                )
            )
        if approval.expires_at_ms <= evidence.evaluated_at_ms:
            violations.append(
                MPR07Violation(
                    "approval_expired",
                    approval.reviewer_id,
                    "approval expired before trusted evaluation time",
                )
            )
        if approval.revoked:
            violations.append(
                MPR07Violation(
                    "approval_revoked",
                    approval.reviewer_id,
                    "approval is revoked",
                )
            )
        if approval.reviewer_id in seen_reviewers:
            violations.append(
                MPR07Violation(
                    "duplicate_reviewer",
                    approval.reviewer_id,
                    "distinct approval roles must be backed by distinct identities",
                )
            )
        seen_reviewers.add(approval.reviewer_id)
        if (
            approval.bundle_hash == evidence.bundle_hash
            and approval.issued_at_ms <= evidence.evaluated_at_ms < approval.expires_at_ms
            and not approval.revoked
        ):
            active_by_role.setdefault(approval.role, approval)

    for role in required_roles:
        if role not in active_by_role:
            violations.append(
                MPR07Violation(
                    "missing_active_approval_role",
                    role,
                    "promotion requires a current non-revoked approval for this role",
                )
            )


def _check_canary(
    evidence: MPR07PromotionEvidence,
    violations: list[MPR07Violation],
) -> None:
    if not evidence.canary_budget.within_limits():
        violations.append(
            MPR07Violation(
                "canary_budget_exceeded",
                "worst_case_lamports",
                "fee+tip+rent+uncertainty+loss must fit wallet capital and daily limit",
            )
        )


def _check_rollback(
    evidence: MPR07PromotionEvidence,
    violations: list[MPR07Violation],
) -> None:
    configured = set(evidence.rollback_triggers)
    for trigger in evidence.rollback_triggers:
        _identifier(trigger, f"rollback:{trigger}")
    for trigger in _REQUIRED_ROLLBACK_TRIGGERS:
        if trigger not in configured:
            violations.append(
                MPR07Violation(
                    "missing_rollback_trigger",
                    trigger,
                    "required rollback trigger is not configured",
                )
            )
    if not evidence.automatic_rollback_to_shadow:
        violations.append(
            MPR07Violation(
                "rollback_not_automatic",
                "automatic_rollback_to_shadow",
                "tiny canary must rollback automatically to shadow on trigger",
            )
        )
    if not evidence.post_canary_review_required:
        violations.append(
            MPR07Violation(
                "post_canary_review_not_required",
                "post_canary_review_required",
                "every expansion requires independent post-canary review",
            )
        )
    if not evidence.legacy_cleanup_complete:
        violations.append(
            MPR07Violation(
                "legacy_cleanup_incomplete",
                "legacy_cleanup_complete",
                "promotion cannot proceed with stale production-reachable surfaces",
            )
        )


def _check_forbidden_surfaces(
    evidence: MPR07PromotionEvidence,
    violations: list[MPR07Violation],
) -> None:
    forbidden = {
        "live_capability_enabled": evidence.live_capability_enabled,
        "signer_reachable": evidence.signer_reachable,
        "sender_reachable": evidence.sender_reachable,
    }
    for subject, enabled in forbidden.items():
        if enabled:
            violations.append(
                MPR07Violation(
                    "forbidden_surface_reachable",
                    subject,
                    "MPR-07 gate is review-only and cannot enable live/signer/sender",
                )
            )


def _evidence_hash(evidence: MPR07PromotionEvidence) -> str:
    payload = {
        "domain": "studious-pancake/mpr07/operations-promotion-gate",
        "evaluated_at_ms": evidence.evaluated_at_ms,
        "bundle_hash": evidence.bundle_hash,
        "telemetry": dict(sorted(evidence.telemetry.items())),
        "telemetry_collected_at_ms": evidence.telemetry_collected_at_ms,
        "artifacts": [
            artifact.to_dict()
            for artifact in sorted(evidence.artifacts, key=lambda item: item.label)
        ],
        "approvals": [
            approval.to_dict()
            for approval in sorted(
                evidence.approvals,
                key=lambda item: (item.role, item.reviewer_id),
            )
        ],
        "canary_budget": evidence.canary_budget.to_dict(),
        "rollback_triggers": sorted(evidence.rollback_triggers),
        "automatic_rollback_to_shadow": evidence.automatic_rollback_to_shadow,
        "post_canary_review_required": evidence.post_canary_review_required,
        "legacy_cleanup_complete": evidence.legacy_cleanup_complete,
        "live_capability_enabled": evidence.live_capability_enabled,
        "signer_reachable": evidence.signer_reachable,
        "sender_reachable": evidence.sender_reachable,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a stable identifier")
    return value


def _sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return value


def _signature(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SIGNATURE_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase 64-byte signature hex")
    return value


def _non_negative_int(value: int, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value
