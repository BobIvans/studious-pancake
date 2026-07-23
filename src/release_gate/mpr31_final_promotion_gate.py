"""MPR-31 final production promotion gate.

This module is a default-off, offline acceptance contract for the V11 MPR-31
cutover. It does not enable live trading, signer IPC, transaction submission,
operator sessions, treasury movement, archive writes, or canary execution.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Any

MPR31_SCHEMA_VERSION = "mpr31.final-production-promotion.v1"
REQUIRED_UPSTREAM_MPRS = frozenset({"MPR-25", "MPR-26", "MPR-27", "MPR-28", "MPR-29", "MPR-30"})
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
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MPR31Error(ValueError):
    """Raised when MPR-31 evidence is malformed before evaluation."""


class PromotionStatus(StrEnum):
    """Terminal result of the default-off MPR-31 gate."""

    READY_DEFAULT_OFF = "READY_DEFAULT_OFF"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class SignedEvidenceArtifact:
    """Signed immutable evidence artifact consumed by MPR-31."""

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
    """Evidence that one upstream mega-PR produced a signed artifact."""

    mpr_id: str
    artifact: SignedEvidenceArtifact

    def __post_init__(self) -> None:
        if self.mpr_id not in REQUIRED_UPSTREAM_MPRS:
            raise MPR31Error("MPR31_UNKNOWN_UPSTREAM_MPR")
        if self.artifact.kind not in ALLOWED_DEPENDENCY_KINDS:
            raise MPR31Error("MPR31_UNKNOWN_UPSTREAM_EVIDENCE_KIND")


@dataclass(frozen=True, slots=True)
class RootedTreasuryEvidence:
    """Rooted treasury and exposure evidence consumed by promotion."""

    wallet_balance_root_digest: str
    token_inventory_root_digest: str
    provider_quorum_digest: str
    policy_generation_digest: str
    unresolved_exposure_lamports: int
    rolling_loss_lamports: int
    daily_loss_lamports: int
    hard_latch_active: bool

    def __post_init__(self) -> None:
        _digest(self.wallet_balance_root_digest, "wallet_balance_root_digest")
        _digest(self.token_inventory_root_digest, "token_inventory_root_digest")
        _digest(self.provider_quorum_digest, "provider_quorum_digest")
        _digest(self.policy_generation_digest, "policy_generation_digest")
        _strict_non_negative_int(self.unresolved_exposure_lamports, "unresolved_exposure_lamports")
        _strict_non_negative_int(self.rolling_loss_lamports, "rolling_loss_lamports")
        _strict_non_negative_int(self.daily_loss_lamports, "daily_loss_lamports")
        _strict_bool(self.hard_latch_active, "hard_latch_active")


@dataclass(frozen=True, slots=True)
class ImmutableArchiveEvidence:
    """Remote immutable archive receipt chain."""

    exported_segment_digest: str
    remote_receipt_quorum_digest: str
    immutable_object_digest: str
    signed_head_digest: str
    retention_policy_digest: str
    replay_verified: bool

    def __post_init__(self) -> None:
        _digest(self.exported_segment_digest, "exported_segment_digest")
        _digest(self.remote_receipt_quorum_digest, "remote_receipt_quorum_digest")
        _digest(self.immutable_object_digest, "immutable_object_digest")
        _digest(self.signed_head_digest, "signed_head_digest")
        _digest(self.retention_policy_digest, "retention_policy_digest")
        _strict_bool(self.replay_verified, "replay_verified")


@dataclass(frozen=True, slots=True)
class OperatorCommandEvidence:
    """Authenticated operator command envelope."""

    principal_digest: str
    role_session_digest: str
    command_digest: str
    command_signature_digest: str
    mfa_freshness_digest: str
    not_before_ns: int
    expires_at_ns: int

    def __post_init__(self) -> None:
        _digest(self.principal_digest, "principal_digest")
        _digest(self.role_session_digest, "role_session_digest")
        _digest(self.command_digest, "command_digest")
        _digest(self.command_signature_digest, "command_signature_digest")
        _digest(self.mfa_freshness_digest, "mfa_freshness_digest")
        _strict_non_negative_int(self.not_before_ns, "not_before_ns")
        _strict_non_negative_int(self.expires_at_ns, "expires_at_ns")
        if self.not_before_ns >= self.expires_at_ns:
            raise MPR31Error("MPR31_INVALID_OPERATOR_COMMAND_WINDOW")


@dataclass(frozen=True, slots=True)
class TinyCanaryProposal:
    """Manual one-transaction canary proposal bound to release evidence."""

    manual_transaction_count: int
    max_canary_loss_lamports: int
    rollback_plan_digest: str
    post_canary_review_required: bool
    live_expansion_requested: bool

    def __post_init__(self) -> None:
        _strict_positive_int(self.manual_transaction_count, "manual_transaction_count")
        _strict_non_negative_int(self.max_canary_loss_lamports, "max_canary_loss_lamports")
        _digest(self.rollback_plan_digest, "rollback_plan_digest")
        _strict_bool(self.post_canary_review_required, "post_canary_review_required")
        _strict_bool(self.live_expansion_requested, "live_expansion_requested")


@dataclass(frozen=True, slots=True)
class FinalPromotionBundle:
    """All evidence needed by the MPR-31 final promotion gate."""

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
        _digest(self.source_digest, "source_digest")
        _digest(self.wheel_digest, "wheel_digest")
        _digest(self.image_digest, "image_digest")
        _digest(self.config_digest, "config_digest")
        _digest(self.policy_digest, "policy_digest")
        _strict_non_negative_int(self.now_ns, "now_ns")
        _strict_bool(self.live_runtime_requested, "live_runtime_requested")

    @property
    def bundle_hash(self) -> str:
        return _hash_json(
            {
                "schema": MPR31_SCHEMA_VERSION,
                "source_digest": self.source_digest,
                "wheel_digest": self.wheel_digest,
                "image_digest": self.image_digest,
                "config_digest": self.config_digest,
                "policy_digest": self.policy_digest,
                "upstream_mprs": [
                    {"mpr_id": item.mpr_id, "artifact_hash": item.artifact.artifact_hash}
                    for item in self.upstream_mprs
                ],
                "treasury": _public_payload(self.treasury),
                "archive": _public_payload(self.archive),
                "operator_command": _public_payload(self.operator_command),
                "canary": _public_payload(self.canary),
                "now_ns": self.now_ns,
                "live_runtime_requested": self.live_runtime_requested,
            }
        )


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Default-off promotion decision."""

    status: PromotionStatus
    reason_codes: tuple[str, ...]
    bundle_hash: str
    canary_authorized_default_off: bool

    @property
    def ready(self) -> bool:
        return self.status is PromotionStatus.READY_DEFAULT_OFF


class MPR31FinalPromotionGate:
    """Fail-closed final promotion contract for MPR-31."""

    def evaluate(self, bundle: FinalPromotionBundle) -> PromotionDecision:
        reasons: list[str] = []
        observed_mprs: dict[str, UpstreamMprEvidence] = {}

        for item in bundle.upstream_mprs:
            if item.mpr_id in observed_mprs:
                reasons.append("MPR31_DUPLICATE_UPSTREAM_MPR")
            observed_mprs[item.mpr_id] = item
            if bundle.now_ns < item.artifact.issued_at_ns:
                reasons.append(f"MPR31_UPSTREAM_NOT_YET_VALID:{item.mpr_id}")
            if bundle.now_ns >= item.artifact.expires_at_ns:
                reasons.append(f"MPR31_UPSTREAM_EXPIRED:{item.mpr_id}")

        for mpr_id in sorted(REQUIRED_UPSTREAM_MPRS - observed_mprs.keys()):
            reasons.append(f"MPR31_MISSING_UPSTREAM:{mpr_id}")

        if bundle.live_runtime_requested:
            reasons.append("MPR31_LIVE_RUNTIME_MUST_REMAIN_DEFAULT_OFF")
        if bundle.canary.live_expansion_requested:
            reasons.append("MPR31_CANARY_EXPANSION_FORBIDDEN")
        if bundle.canary.manual_transaction_count != 1:
            reasons.append("MPR31_CANARY_MUST_BE_ONE_MANUAL_TRANSACTION")
        if not bundle.canary.post_canary_review_required:
            reasons.append("MPR31_POST_CANARY_REVIEW_REQUIRED")
        if bundle.treasury.hard_latch_active:
            reasons.append("MPR31_HARD_LATCH_ACTIVE")
        if bundle.treasury.unresolved_exposure_lamports != 0:
            reasons.append("MPR31_UNRESOLVED_EXPOSURE")
        if bundle.treasury.daily_loss_lamports > bundle.canary.max_canary_loss_lamports:
            reasons.append("MPR31_DAILY_LOSS_EXCEEDS_CANARY_LIMIT")
        if bundle.treasury.rolling_loss_lamports > bundle.canary.max_canary_loss_lamports:
            reasons.append("MPR31_ROLLING_LOSS_EXCEEDS_CANARY_LIMIT")
        if not bundle.archive.replay_verified:
            reasons.append("MPR31_ARCHIVE_REPLAY_NOT_VERIFIED")
        if bundle.now_ns < bundle.operator_command.not_before_ns:
            reasons.append("MPR31_OPERATOR_COMMAND_NOT_YET_VALID")
        if bundle.now_ns >= bundle.operator_command.expires_at_ns:
            reasons.append("MPR31_OPERATOR_COMMAND_EXPIRED")

        status = PromotionStatus.BLOCKED if reasons else PromotionStatus.READY_DEFAULT_OFF
        canary_default_off = status is PromotionStatus.READY_DEFAULT_OFF
        if canary_default_off:
            reasons.append("MPR31_READY_FOR_ONE_MANUAL_CANARY_DEFAULT_OFF")
        return PromotionDecision(
            status=status,
            reason_codes=tuple(reasons),
            bundle_hash=bundle.bundle_hash,
            canary_authorized_default_off=canary_default_off,
        )


def _public_payload(value: object) -> dict[str, Any]:
    if not is_dataclass(value):
        raise TypeError("expected dataclass payload")
    return {field.name: getattr(value, field.name) for field in fields(value)}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _digest(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise MPR31Error(f"{name} must be a lowercase sha256 digest")


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
    "ImmutableArchiveEvidence",
    "MPR31Error",
    "MPR31FinalPromotionGate",
    "MPR31_SCHEMA_VERSION",
    "OperatorCommandEvidence",
    "PromotionDecision",
    "PromotionStatus",
    "REQUIRED_UPSTREAM_MPRS",
    "RootedTreasuryEvidence",
    "SignedEvidenceArtifact",
    "TinyCanaryProposal",
    "UpstreamMprEvidence",
]
