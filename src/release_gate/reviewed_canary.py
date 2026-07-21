"""PR-107 reviewed limited-live canary package gate.

This module is still an offline release-review boundary. It validates that a
human-controlled canary package references real upstream PR-104/105/106 evidence,
uses tiny exposure, has one outstanding submission, and preserves rollback and
kill-switch controls. It never signs, submits, polls, resends, or enables live by
itself.
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

PR107_REVIEWED_CANARY_SCHEMA = "pr107.reviewed-limited-canary-package.v1"
PR107_REVIEWED_CANARY_RESULT_SCHEMA = "pr107.reviewed-limited-canary-result.v1"
PR104_RELEASE_EVIDENCE_NAME = "pr104.security-sbom-provenance-chaos-package"
PR105_SHADOW_SOAK_EVIDENCE_NAME = "pr105.real-shadow-soak-bundle"
PR106_SENDER_LIFECYCLE_EVIDENCE_NAME = "pr106.sender-lifecycle-disabled-evidence"
PR107_TYPE = "reviewed-limited-live-canary"
MAX_TINY_EXPOSURE_LAMPORTS = 50_000_000
REQUIRED_PR107_SIGNOFFS = (
    "release-owner-signoff",
    "security-owner-signoff",
    "risk-owner-signoff",
    "operator-final-arm-signoff",
)
REQUIRED_PR107_LATCHES = (
    "loss-limit",
    "failure-limit",
    "stale-data",
    "ambiguity",
    "manual-kill-switch",
    "indeterminate-outcome",
    "reserve-breach",
    "post-trade-reconciliation-failure",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ReviewedCanaryError(ValueError):
    """Raised when PR-107 reviewed canary evidence is malformed."""


class ReviewedCanaryState(StrEnum):
    BLOCKED = "blocked"
    READY_FOR_MANUAL_CANARY_REVIEW = "ready-for-manual-canary-review"


@dataclass(frozen=True, slots=True)
class ReviewedCanaryEvidenceRef:
    name: str
    sha256: str
    source_commit: str
    passed: bool
    human_reviewed: bool
    reviewer: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ReviewedCanaryError("evidence.name is required")
        object.__setattr__(self, "sha256", _require_sha256(self.sha256, "sha256"))
        object.__setattr__(
            self,
            "source_commit",
            _require_git_sha(self.source_commit, "source_commit"),
        )
        _require_bool(self.passed, "passed")
        _require_bool(self.human_reviewed, "human_reviewed")
        if self.human_reviewed and not self.reviewer.strip():
            raise ReviewedCanaryError("reviewed evidence must include reviewer")


@dataclass(frozen=True, slots=True)
class ReviewedCanaryAllowlistEntry:
    pair: str
    provider: str
    program_id: str
    max_exposure_lamports: int
    protected_reserve_lamports: int
    reviewed: bool

    def __post_init__(self) -> None:
        for field_name in ("pair", "provider", "program_id"):
            if not str(getattr(self, field_name)).strip():
                raise ReviewedCanaryError(f"allowlist.{field_name} is required")
        object.__setattr__(
            self,
            "max_exposure_lamports",
            _require_positive_int(
                self.max_exposure_lamports,
                "allowlist.max_exposure_lamports",
            ),
        )
        object.__setattr__(
            self,
            "protected_reserve_lamports",
            _require_positive_int(
                self.protected_reserve_lamports,
                "allowlist.protected_reserve_lamports",
            ),
        )
        _require_bool(self.reviewed, "allowlist.reviewed")


@dataclass(frozen=True, slots=True)
class ReviewedCanaryLatch:
    name: str
    armed: bool
    tested: bool
    blocks_on_trigger: bool

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ReviewedCanaryError("latch.name is required")
        _require_bool(self.armed, "latch.armed")
        _require_bool(self.tested, "latch.tested")
        _require_bool(self.blocks_on_trigger, "latch.blocks_on_trigger")


@dataclass(frozen=True, slots=True)
class ReviewedLimitedCanaryPackage:
    code_commit: str
    config_sha256: str
    contract_pins_sha256: str
    rollback_plan_sha256: str
    pr104_release_evidence: ReviewedCanaryEvidenceRef
    pr105_shadow_soak: ReviewedCanaryEvidenceRef
    pr106_sender_lifecycle: ReviewedCanaryEvidenceRef
    allowlist: Sequence[ReviewedCanaryAllowlistEntry]
    latches: Sequence[ReviewedCanaryLatch]
    human_signoffs: Mapping[str, datetime]
    max_exposure_lamports: int
    protected_reserve_lamports: int
    max_outstanding_submissions: int
    default_live_enabled: bool
    env_can_enable_live: bool
    manual_kill_switch_armed: bool
    post_trade_reconciliation_required: bool
    rollback_requires_code_change: bool
    indeterminate_outcome_open: bool
    one_outstanding_submission_enforced: bool
    isolated_signer_reviewed: bool
    assembled_at: datetime
    assembled_by: str
    schema_version: str = PR107_REVIEWED_CANARY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != PR107_REVIEWED_CANARY_SCHEMA:
            raise ReviewedCanaryError("unsupported PR-107 package schema")
        object.__setattr__(
            self,
            "code_commit",
            _require_git_sha(self.code_commit, "code_commit"),
        )
        for field_name in (
            "config_sha256",
            "contract_pins_sha256",
            "rollback_plan_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_sha256(getattr(self, field_name), field_name),
            )
        if not self.allowlist:
            raise ReviewedCanaryError("allowlist cannot be empty")
        if not self.latches:
            raise ReviewedCanaryError("latches cannot be empty")
        object.__setattr__(
            self,
            "max_exposure_lamports",
            _require_positive_int(
                self.max_exposure_lamports,
                "max_exposure_lamports",
            ),
        )
        object.__setattr__(
            self,
            "protected_reserve_lamports",
            _require_positive_int(
                self.protected_reserve_lamports,
                "protected_reserve_lamports",
            ),
        )
        object.__setattr__(
            self,
            "max_outstanding_submissions",
            _require_positive_int(
                self.max_outstanding_submissions,
                "max_outstanding_submissions",
            ),
        )
        for flag in (
            "default_live_enabled",
            "env_can_enable_live",
            "manual_kill_switch_armed",
            "post_trade_reconciliation_required",
            "rollback_requires_code_change",
            "indeterminate_outcome_open",
            "one_outstanding_submission_enforced",
            "isolated_signer_reviewed",
        ):
            _require_bool(getattr(self, flag), flag)
        _require_aware_datetime(self.assembled_at, "assembled_at")
        if not self.assembled_by.strip():
            raise ReviewedCanaryError("assembled_by is required")
        for signoff in self.human_signoffs.values():
            _require_aware_datetime(signoff, "human_signoffs")

    @property
    def package_sha256(self) -> str:
        return _sha256_payload(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class ReviewedCanaryReadiness:
    state: ReviewedCanaryState
    ready_for_manual_canary_review: bool
    default_live_enabled: bool
    runtime_live_enabled: bool
    supported_command_can_submit: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    package_sha256: str
    max_exposure_lamports: int
    max_outstanding_submissions: int
    schema_version: str = PR107_REVIEWED_CANARY_RESULT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_pr107_reviewed_canary_package(
    package: ReviewedLimitedCanaryPackage,
) -> ReviewedCanaryReadiness:
    blockers: list[str] = []
    warnings: list[str] = []

    _check_evidence(
        blockers,
        package.pr104_release_evidence,
        PR104_RELEASE_EVIDENCE_NAME,
        "PR104",
    )
    _check_evidence(
        blockers,
        package.pr105_shadow_soak,
        PR105_SHADOW_SOAK_EVIDENCE_NAME,
        "PR105",
    )
    _check_evidence(
        blockers,
        package.pr106_sender_lifecycle,
        PR106_SENDER_LIFECYCLE_EVIDENCE_NAME,
        "PR106",
    )
    _block(
        blockers,
        package.max_exposure_lamports <= MAX_TINY_EXPOSURE_LAMPORTS,
        "CANARY_EXPOSURE_NOT_TINY",
    )
    _block(
        blockers,
        package.max_outstanding_submissions == 1,
        "CANARY_REQUIRES_ONE_OUTSTANDING_SUBMISSION",
    )
    _block(
        blockers,
        package.one_outstanding_submission_enforced,
        "ONE_OUTSTANDING_SUBMISSION_NOT_ENFORCED",
    )
    _block(blockers, not package.default_live_enabled, "DEFAULT_LIVE_ENABLED")
    _block(blockers, not package.env_can_enable_live, "ENV_CAN_ENABLE_LIVE")
    _block(blockers, package.manual_kill_switch_armed, "MANUAL_KILL_NOT_ARMED")
    _block(
        blockers,
        package.post_trade_reconciliation_required,
        "POST_TRADE_RECONCILIATION_NOT_REQUIRED",
    )
    _block(
        blockers,
        not package.rollback_requires_code_change,
        "ROLLBACK_REQUIRES_CODE_CHANGE",
    )
    _block(
        blockers,
        not package.indeterminate_outcome_open,
        "INDETERMINATE_OUTCOME_OPEN",
    )
    _block(blockers, package.isolated_signer_reviewed, "SIGNER_BOUNDARY_NOT_REVIEWED")

    signoffs = set(package.human_signoffs)
    for required in REQUIRED_PR107_SIGNOFFS:
        _block(blockers, required in signoffs, f"SIGNOFF_MISSING:{required}")
        signoff_at = package.human_signoffs.get(required)
        if signoff_at is not None:
            _block(
                blockers,
                signoff_at <= package.assembled_at,
                f"SIGNOFF_AFTER_ASSEMBLY:{required}",
            )

    latch_by_name = {latch.name: latch for latch in package.latches}
    for required in REQUIRED_PR107_LATCHES:
        latch = latch_by_name.get(required)
        if latch is None:
            blockers.append(f"LATCH_MISSING:{required}")
            continue
        _block(blockers, latch.armed, f"LATCH_NOT_ARMED:{required}")
        _block(blockers, latch.tested, f"LATCH_NOT_TESTED:{required}")
        _block(blockers, latch.blocks_on_trigger, f"LATCH_DOES_NOT_BLOCK:{required}")

    for entry in package.allowlist:
        prefix = f"{entry.pair}:{entry.provider}:{entry.program_id}"
        _block(blockers, entry.reviewed, f"ALLOWLIST_NOT_REVIEWED:{prefix}")
        _block(
            blockers,
            entry.max_exposure_lamports <= package.max_exposure_lamports,
            f"ALLOWLIST_EXPOSURE_EXCEEDS_PACKAGE:{prefix}",
        )
        _block(
            blockers,
            entry.protected_reserve_lamports >= package.protected_reserve_lamports,
            f"ALLOWLIST_RESERVE_TOO_LOW:{prefix}",
        )

    if package.max_exposure_lamports > package.protected_reserve_lamports:
        warnings.append("EXPOSURE_EXCEEDS_PROTECTED_RESERVE_REVIEW_REQUIRED")

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    return ReviewedCanaryReadiness(
        state=(
            ReviewedCanaryState.READY_FOR_MANUAL_CANARY_REVIEW
            if ready
            else ReviewedCanaryState.BLOCKED
        ),
        ready_for_manual_canary_review=ready,
        default_live_enabled=False,
        runtime_live_enabled=False,
        supported_command_can_submit=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        package_sha256=package.package_sha256,
        max_exposure_lamports=package.max_exposure_lamports,
        max_outstanding_submissions=package.max_outstanding_submissions,
    )


def _check_evidence(
    blockers: list[str],
    evidence: ReviewedCanaryEvidenceRef,
    expected_name: str,
    prefix: str,
) -> None:
    _block(blockers, evidence.name == expected_name, f"{prefix}_WRONG_EVIDENCE_NAME")
    _block(blockers, evidence.passed, f"{prefix}_EVIDENCE_BLOCKED")
    _block(blockers, evidence.human_reviewed, f"{prefix}_EVIDENCE_NOT_REVIEWED")


def _block(blockers: list[str], condition: bool, reason: str) -> None:
    if not condition:
        blockers.append(reason)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
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


def _require_sha256(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise ReviewedCanaryError(f"{field} must be a non-placeholder sha256")
    return lowered


def _require_git_sha(value: str, field: str) -> str:
    lowered = str(value).lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise ReviewedCanaryError(f"{field} must be a non-placeholder git sha")
    return lowered


def _require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReviewedCanaryError(f"{field} must be a positive integer")
    return value


def _require_bool(value: Any, field: str) -> None:
    if not isinstance(value, bool):
        raise ReviewedCanaryError(f"{field} must be bool")


def _require_aware_datetime(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReviewedCanaryError(f"{field} must be timezone-aware")


__all__ = [
    "MAX_TINY_EXPOSURE_LAMPORTS",
    "PR104_RELEASE_EVIDENCE_NAME",
    "PR105_SHADOW_SOAK_EVIDENCE_NAME",
    "PR106_SENDER_LIFECYCLE_EVIDENCE_NAME",
    "PR107_REVIEWED_CANARY_RESULT_SCHEMA",
    "PR107_REVIEWED_CANARY_SCHEMA",
    "PR107_TYPE",
    "REQUIRED_PR107_LATCHES",
    "REQUIRED_PR107_SIGNOFFS",
    "ReviewedCanaryAllowlistEntry",
    "ReviewedCanaryError",
    "ReviewedCanaryEvidenceRef",
    "ReviewedCanaryLatch",
    "ReviewedCanaryReadiness",
    "ReviewedCanaryState",
    "ReviewedLimitedCanaryPackage",
    "evaluate_pr107_reviewed_canary_package",
]
