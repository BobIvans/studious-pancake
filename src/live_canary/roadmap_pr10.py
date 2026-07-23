"""Roadmap PR-10 final limited-live canary admission foundation.

This module is intentionally review-only. It evaluates whether immutable evidence
for roadmap PR-01 through PR-09 is coherent enough for a later, independently
reviewed activation change. It never imports a signer or sender, never enables
live mode, and never grants submission authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

PR10_REQUEST_SCHEMA_VERSION = "roadmap.pr10.canary-request.v1"
PR10_RESULT_SCHEMA_VERSION = "roadmap.pr10.canary-readiness.v1"
PR10_EVIDENCE_SCHEMA_VERSION = "roadmap.pr10.prerequisite-evidence.v1"
PR10_SCOPE_SCHEMA_VERSION = "roadmap.pr10.canary-scope.v1"

# Deliberate compile-time deny. A later independent PR must change this only after
# PR-01 through PR-09 are merged, qualified, release-bound, and human-approved.
COMPILE_TIME_CANARY_ENABLED = False

EXPECTED_PREREQUISITES = tuple(f"PR-{index:02d}" for index in range(1, 10))
REQUIRED_LATCHES = (
    "manual-kill-switch",
    "daily-loss-limit",
    "consecutive-failure-limit",
    "stale-data",
    "rpc-divergence",
    "reconciliation-ambiguity",
    "indeterminate-settlement",
    "reserve-breach",
)
ALLOWED_TRANSPORTS = frozenset({"rpc", "jito-single"})
MAX_CANARY_EXPOSURE_LAMPORTS = 5_000_000
MAX_REQUEST_TTL_MS = 15 * 60 * 1000

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class PR10CanaryError(ValueError):
    """Raised when PR-10 evidence or a request is structurally malformed."""


class PR10CanaryState(StrEnum):
    BLOCKED = "blocked"
    READY_FOR_INDEPENDENT_ACTIVATION_REVIEW = "ready-for-independent-activation-review"


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PR10CanaryError(f"{field} must be a non-empty string")
    return value.strip()


def _required_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise PR10CanaryError(f"{field} must be boolean")
    return value


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PR10CanaryError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PR10CanaryError(f"{field} must be a non-negative integer")
    return value


def _sha256(value: Any, field: str) -> str:
    normalized = _required_text(value, field).lower()
    if not _SHA256_RE.fullmatch(normalized) or normalized == "0" * 64:
        raise PR10CanaryError(f"{field} must be a non-placeholder sha256")
    return normalized


def _git_sha(value: Any, field: str) -> str:
    normalized = _required_text(value, field).lower()
    if not _GIT_SHA_RE.fullmatch(normalized) or normalized == "0" * 40:
        raise PR10CanaryError(f"{field} must be a non-placeholder git sha")
    return normalized


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def _stable_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PR10PrerequisiteEvidence:
    roadmap_pr: str
    artifact_sha256: str
    source_commit: str
    release_digest_sha256: str
    policy_bundle_sha256: str
    reviewer_id: str
    reviewed_at_ms: int
    expires_at_ms: int
    passed: bool
    human_reviewed: bool
    immutable: bool
    synthetic: bool
    schema_version: str = PR10_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR10_EVIDENCE_SCHEMA_VERSION:
            raise PR10CanaryError("unsupported prerequisite evidence schema")
        if self.roadmap_pr not in EXPECTED_PREREQUISITES:
            raise PR10CanaryError("roadmap_pr must be PR-01 through PR-09")
        object.__setattr__(
            self, "artifact_sha256", _sha256(self.artifact_sha256, "artifact_sha256")
        )
        object.__setattr__(
            self, "source_commit", _git_sha(self.source_commit, "source_commit")
        )
        object.__setattr__(
            self,
            "release_digest_sha256",
            _sha256(self.release_digest_sha256, "release_digest_sha256"),
        )
        object.__setattr__(
            self,
            "policy_bundle_sha256",
            _sha256(self.policy_bundle_sha256, "policy_bundle_sha256"),
        )
        object.__setattr__(
            self, "reviewer_id", _required_text(self.reviewer_id, "reviewer_id")
        )
        _positive_int(self.reviewed_at_ms, "reviewed_at_ms")
        _positive_int(self.expires_at_ms, "expires_at_ms")
        if self.expires_at_ms <= self.reviewed_at_ms:
            raise PR10CanaryError("evidence expiry must follow review time")
        for field in ("passed", "human_reviewed", "immutable", "synthetic"):
            _required_bool(getattr(self, field), field)

    @property
    def evidence_sha256(self) -> str:
        return _digest(self)


@dataclass(frozen=True, slots=True)
class PR10CanaryScope:
    pair: str
    provider: str
    program_ids: tuple[str, ...]
    transport: str
    max_exposure_lamports: int
    protected_reserve_lamports: int
    max_network_fee_lamports: int
    max_priority_fee_lamports: int
    max_jito_tip_lamports: int
    reviewed: bool
    schema_version: str = PR10_SCOPE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR10_SCOPE_SCHEMA_VERSION:
            raise PR10CanaryError("unsupported canary scope schema")
        object.__setattr__(self, "pair", _required_text(self.pair, "scope.pair"))
        object.__setattr__(
            self, "provider", _required_text(self.provider, "scope.provider")
        )
        programs = tuple(
            _required_text(program_id, "scope.program_ids")
            for program_id in self.program_ids
        )
        if not programs or len(programs) != len(set(programs)):
            raise PR10CanaryError("scope.program_ids must be non-empty and unique")
        object.__setattr__(self, "program_ids", programs)
        transport = _required_text(self.transport, "scope.transport")
        if transport not in ALLOWED_TRANSPORTS:
            raise PR10CanaryError("scope.transport must be rpc or jito-single")
        object.__setattr__(self, "transport", transport)
        _positive_int(self.max_exposure_lamports, "scope.max_exposure_lamports")
        _positive_int(
            self.protected_reserve_lamports,
            "scope.protected_reserve_lamports",
        )
        _nonnegative_int(
            self.max_network_fee_lamports,
            "scope.max_network_fee_lamports",
        )
        _nonnegative_int(
            self.max_priority_fee_lamports,
            "scope.max_priority_fee_lamports",
        )
        _nonnegative_int(
            self.max_jito_tip_lamports,
            "scope.max_jito_tip_lamports",
        )
        _required_bool(self.reviewed, "scope.reviewed")
        if transport == "rpc" and self.max_jito_tip_lamports != 0:
            raise PR10CanaryError("rpc scope cannot include a Jito tip")
        if transport == "jito-single" and self.max_jito_tip_lamports <= 0:
            raise PR10CanaryError("jito-single scope requires a positive tip cap")

    @property
    def scope_sha256(self) -> str:
        return _digest(self)


@dataclass(frozen=True, slots=True)
class PR10CanaryRequest:
    release_digest_sha256: str
    policy_bundle_sha256: str
    code_commit: str
    environment: str
    cluster_genesis_sha256: str
    requested_by: str
    release_approved_by: str
    risk_approved_by: str
    operator_armed_by: str
    requested_at_ms: int
    expires_at_ms: int
    scopes: Sequence[PR10CanaryScope]
    latches: Mapping[str, bool]
    minimum_wallet_reserve_lamports: int
    max_outstanding_submissions: int
    runtime_default_live_enabled: bool
    environment_activation_requested: bool
    ai_authority: bool
    rollback_to_shadow_without_code_change: bool
    post_trade_reconciliation_required: bool
    unresolved_settlement: bool
    active_exposure_open: bool
    isolated_signer_boundary_reviewed: bool
    finalized_settlement_boundary_reviewed: bool
    protected_deployment_reviewed: bool
    schema_version: str = PR10_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR10_REQUEST_SCHEMA_VERSION:
            raise PR10CanaryError("unsupported PR-10 request schema")
        object.__setattr__(
            self,
            "release_digest_sha256",
            _sha256(self.release_digest_sha256, "release_digest_sha256"),
        )
        object.__setattr__(
            self,
            "policy_bundle_sha256",
            _sha256(self.policy_bundle_sha256, "policy_bundle_sha256"),
        )
        object.__setattr__(
            self, "code_commit", _git_sha(self.code_commit, "code_commit")
        )
        object.__setattr__(
            self, "environment", _required_text(self.environment, "environment")
        )
        object.__setattr__(
            self,
            "cluster_genesis_sha256",
            _sha256(self.cluster_genesis_sha256, "cluster_genesis_sha256"),
        )
        for field in (
            "requested_by",
            "release_approved_by",
            "risk_approved_by",
            "operator_armed_by",
        ):
            object.__setattr__(self, field, _required_text(getattr(self, field), field))
        _positive_int(self.requested_at_ms, "requested_at_ms")
        _positive_int(self.expires_at_ms, "expires_at_ms")
        if self.expires_at_ms <= self.requested_at_ms:
            raise PR10CanaryError("request expiry must follow request time")
        if self.expires_at_ms - self.requested_at_ms > MAX_REQUEST_TTL_MS:
            raise PR10CanaryError("request TTL exceeds the PR-10 maximum")
        scopes = tuple(self.scopes)
        if not scopes:
            raise PR10CanaryError("at least one canary scope is required")
        object.__setattr__(self, "scopes", scopes)
        _positive_int(
            self.minimum_wallet_reserve_lamports,
            "minimum_wallet_reserve_lamports",
        )
        _positive_int(
            self.max_outstanding_submissions,
            "max_outstanding_submissions",
        )
        for field in (
            "runtime_default_live_enabled",
            "environment_activation_requested",
            "ai_authority",
            "rollback_to_shadow_without_code_change",
            "post_trade_reconciliation_required",
            "unresolved_settlement",
            "active_exposure_open",
            "isolated_signer_boundary_reviewed",
            "finalized_settlement_boundary_reviewed",
            "protected_deployment_reviewed",
        ):
            _required_bool(getattr(self, field), field)
        for latch, armed in self.latches.items():
            _required_text(latch, "latch")
            _required_bool(armed, f"latches.{latch}")

    @property
    def request_sha256(self) -> str:
        return _digest(self)


@dataclass(frozen=True, slots=True)
class PR10CanaryReadiness:
    state: PR10CanaryState
    prerequisites_complete: bool
    ready_for_independent_activation_review: bool
    compile_time_canary_enabled: bool
    runtime_live_enabled: bool
    submission_allowed: bool
    supported_command_can_submit: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    request_sha256: str
    schema_version: str = PR10_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_pr10_canary_foundation(
    evidence: Sequence[PR10PrerequisiteEvidence],
    request: PR10CanaryRequest,
    *,
    now_ms: int,
) -> PR10CanaryReadiness:
    """Evaluate PR-10 prerequisites without enabling or invoking live execution."""

    _positive_int(now_ms, "now_ms")
    blockers: list[str] = []
    warnings: list[str] = []

    def block(condition: bool, reason: str) -> None:
        if not condition:
            blockers.append(reason)

    evidence_by_pr: dict[str, PR10PrerequisiteEvidence] = {}
    for evidence_item in evidence:
        if evidence_item.roadmap_pr in evidence_by_pr:
            blockers.append(f"DUPLICATE_PREREQUISITE:{evidence_item.roadmap_pr}")
            continue
        evidence_by_pr[evidence_item.roadmap_pr] = evidence_item

    unexpected = sorted(set(evidence_by_pr) - set(EXPECTED_PREREQUISITES))
    for roadmap_pr in unexpected:
        blockers.append(f"UNEXPECTED_PREREQUISITE:{roadmap_pr}")

    reviewers: set[str] = set()
    for roadmap_pr in EXPECTED_PREREQUISITES:
        item = evidence_by_pr.get(roadmap_pr)
        if item is None:
            blockers.append(f"PREREQUISITE_MISSING:{roadmap_pr}")
            continue
        reviewers.add(item.reviewer_id)
        block(item.passed, f"PREREQUISITE_FAILED:{roadmap_pr}")
        block(item.human_reviewed, f"PREREQUISITE_NOT_HUMAN_REVIEWED:{roadmap_pr}")
        block(item.immutable, f"PREREQUISITE_NOT_IMMUTABLE:{roadmap_pr}")
        block(not item.synthetic, f"PREREQUISITE_SYNTHETIC:{roadmap_pr}")
        block(now_ms <= item.expires_at_ms, f"PREREQUISITE_EXPIRED:{roadmap_pr}")
        block(
            item.source_commit == request.code_commit,
            f"PREREQUISITE_COMMIT_MISMATCH:{roadmap_pr}",
        )
        block(
            item.release_digest_sha256 == request.release_digest_sha256,
            f"PREREQUISITE_RELEASE_MISMATCH:{roadmap_pr}",
        )
        block(
            item.policy_bundle_sha256 == request.policy_bundle_sha256,
            f"PREREQUISITE_POLICY_MISMATCH:{roadmap_pr}",
        )

    block(len(reviewers) >= 2, "PREREQUISITE_REVIEWER_DIVERSITY_MISSING")
    block(now_ms <= request.expires_at_ms, "CANARY_REQUEST_EXPIRED")
    block(
        request.max_outstanding_submissions == 1,
        "CANARY_REQUIRES_ONE_OUTSTANDING_SUBMISSION",
    )
    block(len(request.scopes) == 1, "CANARY_REQUIRES_EXACTLY_ONE_SCOPE")
    for scope in request.scopes:
        block(scope.reviewed, "CANARY_SCOPE_NOT_REVIEWED")
        block(
            scope.max_exposure_lamports <= MAX_CANARY_EXPOSURE_LAMPORTS,
            "CANARY_EXPOSURE_EXCEEDS_TINY_CAP",
        )
        block(
            scope.protected_reserve_lamports >= request.minimum_wallet_reserve_lamports,
            "CANARY_SCOPE_RESERVE_BELOW_REQUEST",
        )

    for latch in REQUIRED_LATCHES:
        block(request.latches.get(latch) is True, f"LATCH_NOT_ARMED:{latch}")

    role_ids = {
        request.requested_by,
        request.release_approved_by,
        request.risk_approved_by,
        request.operator_armed_by,
    }
    block(len(role_ids) == 4, "SEPARATION_OF_DUTIES_VIOLATION")
    block(not request.runtime_default_live_enabled, "RUNTIME_DEFAULT_LIVE_ENABLED")
    block(
        not request.environment_activation_requested,
        "ENVIRONMENT_ONLY_ACTIVATION_FORBIDDEN",
    )
    block(not request.ai_authority, "AI_AUTHORITY_FORBIDDEN")
    block(
        request.rollback_to_shadow_without_code_change,
        "ROLLBACK_WITHOUT_CODE_CHANGE_NOT_PROVEN",
    )
    block(
        request.post_trade_reconciliation_required,
        "POST_TRADE_RECONCILIATION_NOT_REQUIRED",
    )
    block(not request.unresolved_settlement, "UNRESOLVED_SETTLEMENT_PRESENT")
    block(not request.active_exposure_open, "ACTIVE_EXPOSURE_PRESENT")
    block(
        request.isolated_signer_boundary_reviewed,
        "ISOLATED_SIGNER_BOUNDARY_NOT_REVIEWED",
    )
    block(
        request.finalized_settlement_boundary_reviewed,
        "FINALIZED_SETTLEMENT_BOUNDARY_NOT_REVIEWED",
    )
    block(
        request.protected_deployment_reviewed,
        "PROTECTED_DEPLOYMENT_NOT_REVIEWED",
    )

    if request.environment.lower() in {"local", "development", "dev", "test"}:
        warnings.append("CANARY_ENVIRONMENT_REQUIRES_PROTECTED_PRODUCTION_REVIEW")

    unique_blockers = tuple(dict.fromkeys(blockers))
    prerequisites_complete = not unique_blockers
    return PR10CanaryReadiness(
        state=(
            PR10CanaryState.READY_FOR_INDEPENDENT_ACTIVATION_REVIEW
            if prerequisites_complete
            else PR10CanaryState.BLOCKED
        ),
        prerequisites_complete=prerequisites_complete,
        ready_for_independent_activation_review=prerequisites_complete,
        compile_time_canary_enabled=COMPILE_TIME_CANARY_ENABLED,
        runtime_live_enabled=False,
        submission_allowed=False,
        supported_command_can_submit=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        request_sha256=request.request_sha256,
    )


__all__ = [
    "ALLOWED_TRANSPORTS",
    "COMPILE_TIME_CANARY_ENABLED",
    "EXPECTED_PREREQUISITES",
    "MAX_CANARY_EXPOSURE_LAMPORTS",
    "MAX_REQUEST_TTL_MS",
    "PR10CanaryError",
    "PR10CanaryReadiness",
    "PR10CanaryRequest",
    "PR10CanaryScope",
    "PR10CanaryState",
    "PR10PrerequisiteEvidence",
    "REQUIRED_LATCHES",
    "evaluate_pr10_canary_foundation",
]
