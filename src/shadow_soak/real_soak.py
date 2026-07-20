"""PR-079 real shadow-soak evidence package boundary.

PR-060 defines the generic shadow-soak evaluator.  PR-079 is stricter: it
accepts only immutable, operator-reviewed artifacts from an actual long-running
shadow/mainnet-read-only run and keeps live submission unavailable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

from src.shadow_soak.evidence import (
    MINIMUM_SOAK_SECONDS,
    ShadowSoakError,
    ShadowSoakEvaluation,
    ShadowSoakEvidence,
    ShadowSoakThresholds,
    SoakEnvironment,
    evaluate_shadow_soak,
)

REAL_SOAK_SCHEMA_VERSION = "pr079.real-shadow-soak-package.v1"
REAL_SOAK_RESULT_SCHEMA_VERSION = "pr079.real-shadow-soak-readiness.v1"

REQUIRED_PREREQUISITES: tuple[str, ...] = (
    "pr076.production-paper-shadow-runner",
    "pr077.data-lifecycle-observability",
    "pr078.security-sbom-chaos-evidence",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class RealShadowSoakState(StrEnum):
    """Promotion state for real PR-079 evidence."""

    BLOCKED = "blocked"
    READY_FOR_RELEASE_EVIDENCE = "ready-for-release-evidence"


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ShadowSoakError(f"{field} must be timezone-aware")


def _sha256(value: str, field: str) -> str:
    lowered = value.lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise ShadowSoakError(f"{field} must be a non-placeholder sha256")
    return lowered


def _git_sha(value: str, field: str) -> str:
    lowered = value.lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise ShadowSoakError(f"{field} must be a non-placeholder git SHA")
    return lowered


def _relative_or_uri(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ShadowSoakError(f"{field} is required")
    if cleaned.startswith(("http://", "https://", "s3://", "gs://")):
        return cleaned
    normalized = cleaned.replace("\\", "/")
    parts = normalized.split("/")
    if (
        normalized.startswith(("/", "~"))
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ShadowSoakError(f"{field} must be a normalized relative path or URI")
    return normalized


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            item.name: _jsonable(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _stable_json(payload: Any) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SoakPrerequisiteEvidence:
    """Human-reviewed upstream evidence required before PR-079 can pass."""

    name: str
    evidence_sha256: str
    passed: bool
    human_reviewed: bool
    source_commit: str
    reviewer: str
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ShadowSoakError("prerequisite.name is required")
        object.__setattr__(
            self,
            "evidence_sha256",
            _sha256(self.evidence_sha256, "prerequisite.evidence_sha256"),
        )
        if not isinstance(self.passed, bool):
            raise ShadowSoakError("prerequisite.passed must be boolean")
        if not isinstance(self.human_reviewed, bool):
            raise ShadowSoakError("prerequisite.human_reviewed must be boolean")
        object.__setattr__(
            self,
            "source_commit",
            _git_sha(self.source_commit, "prerequisite.source_commit"),
        )
        if self.human_reviewed and not self.reviewer.strip():
            raise ShadowSoakError("reviewed prerequisite must include reviewer")


@dataclass(frozen=True, slots=True)
class ImmutableSoakBundle:
    """Digest-pinned immutable storage reference for PR-079 artifacts."""

    uri: str
    sha256: str
    signed: bool
    signature_sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "uri", _relative_or_uri(self.uri, "bundle.uri"))
        object.__setattr__(
            self,
            "sha256",
            _sha256(self.sha256, "bundle.sha256"),
        )
        if not isinstance(self.signed, bool):
            raise ShadowSoakError("bundle.signed must be boolean")
        object.__setattr__(
            self,
            "signature_sha256",
            _sha256(self.signature_sha256, "bundle.signature_sha256"),
        )
        if isinstance(self.size_bytes, bool) or self.size_bytes <= 0:
            raise ShadowSoakError("bundle.size_bytes must be a positive integer")


@dataclass(frozen=True, slots=True)
class RealShadowSoakPackage:
    """PR-079 package assembled from a real 72h+ shadow/read-only soak."""

    soak: ShadowSoakEvidence
    soak_evaluation: ShadowSoakEvaluation
    prerequisites: tuple[SoakPrerequisiteEvidence, ...]
    immutable_bundle: ImmutableSoakBundle
    assembled_at: datetime
    assembled_by: str
    no_sender_observed: bool
    live_submissions_observed: int
    replay_verified_after_collection: bool
    minimum_sample_threshold: int = 1
    schema_version: str = REAL_SOAK_SCHEMA_VERSION
    notes: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != REAL_SOAK_SCHEMA_VERSION:
            raise ShadowSoakError("unsupported PR-079 package schema")
        _aware(self.assembled_at, "assembled_at")
        if not self.assembled_by.strip():
            raise ShadowSoakError("assembled_by is required")
        if self.assembled_at < self.soak.reviewed_at:
            raise ShadowSoakError("assembled_at cannot be before human review")
        if not self.prerequisites:
            raise ShadowSoakError("at least one prerequisite evidence item is required")
        names = [item.name for item in self.prerequisites]
        if len(names) != len(set(names)):
            raise ShadowSoakError("prerequisite names must be unique")
        if not isinstance(self.no_sender_observed, bool):
            raise ShadowSoakError("no_sender_observed must be boolean")
        if (
            isinstance(self.live_submissions_observed, bool)
            or self.live_submissions_observed < 0
        ):
            raise ShadowSoakError("live_submissions_observed must be non-negative int")
        if not isinstance(self.replay_verified_after_collection, bool):
            raise ShadowSoakError("replay_verified_after_collection must be boolean")
        if (
            isinstance(self.minimum_sample_threshold, bool)
            or self.minimum_sample_threshold <= 0
        ):
            raise ShadowSoakError("minimum_sample_threshold must be a positive integer")

    @property
    def package_sha256(self) -> str:
        return _sha256_payload(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class RealShadowSoakReadiness:
    """Fail-closed PR-079 readiness result."""

    run_id: str
    state: RealShadowSoakState
    release_evidence_ready: bool
    live_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    package_sha256: str
    soak_evidence_sha256: str
    immutable_bundle_sha256: str
    duration_seconds: int
    candidates_seen: int
    replay_pass_rate_bps: int
    schema_version: str = REAL_SOAK_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_real_shadow_soak(
    package: RealShadowSoakPackage,
    thresholds: ShadowSoakThresholds | None = None,
) -> RealShadowSoakReadiness:
    """Evaluate PR-079 evidence without enabling live submission."""

    policy = thresholds or ShadowSoakThresholds(
        min_candidates_seen=package.minimum_sample_threshold,
        min_reconciled_outcomes=1,
    )
    fresh_evaluation = evaluate_shadow_soak(package.soak, policy)
    blockers: list[str] = []
    warnings: list[str] = list(fresh_evaluation.warnings)

    def block(condition: bool, reason: str) -> None:
        if not condition:
            blockers.append(reason)

    block(
        package.soak.environment
        in {SoakEnvironment.SHADOW, SoakEnvironment.MAINNET_READ_ONLY},
        "RECORDED_FIXTURE_NOT_REAL_SOAK",
    )
    block(
        package.soak.duration_seconds >= MINIMUM_SOAK_SECONDS,
        "REAL_SOAK_DURATION_BELOW_72H",
    )
    block(
        package.soak.metrics.candidates_seen >= package.minimum_sample_threshold,
        "REAL_SOAK_SAMPLE_THRESHOLD_NOT_MET",
    )
    block(
        package.soak_evaluation.run_id == package.soak.run_id,
        "SOAK_EVALUATION_RUN_ID_MISMATCH",
    )
    block(
        package.soak_evaluation.evidence_sha256 == package.soak.evidence_sha256,
        "SOAK_EVALUATION_HASH_MISMATCH",
    )
    block(
        fresh_evaluation.evidence_sha256 == package.soak_evaluation.evidence_sha256,
        "STALE_SOAK_EVALUATION_ATTACHED",
    )
    block(fresh_evaluation.promotion_ready, "PR060_SHADOW_SOAK_EVALUATION_BLOCKED")
    for reason in fresh_evaluation.blockers:
        blockers.append(f"PR060:{reason}")

    prerequisites = {item.name: item for item in package.prerequisites}
    for name in REQUIRED_PREREQUISITES:
        prereq = prerequisites.get(name)
        if prereq is None:
            blockers.append(f"PREREQUISITE_MISSING:{name}")
            continue
        block(prereq.passed, f"PREREQUISITE_NOT_PASSED:{name}")
        block(prereq.human_reviewed, f"PREREQUISITE_NOT_REVIEWED:{name}")

    block(package.immutable_bundle.signed, "IMMUTABLE_BUNDLE_NOT_SIGNED")
    block(package.no_sender_observed, "SENDER_WAS_OBSERVED_DURING_SOAK")
    block(package.live_submissions_observed == 0, "LIVE_SUBMISSIONS_OBSERVED")
    block(
        package.replay_verified_after_collection,
        "REPLAY_NOT_VERIFIED_AFTER_COLLECTION",
    )
    if package.soak.metrics.net_pnl_lamports < 0:
        warnings.append("NEGATIVE_REAL_SOAK_NET_PNL_REQUIRES_RELEASE_REVIEW")

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    return RealShadowSoakReadiness(
        run_id=package.soak.run_id,
        state=(
            RealShadowSoakState.READY_FOR_RELEASE_EVIDENCE
            if ready
            else RealShadowSoakState.BLOCKED
        ),
        release_evidence_ready=ready,
        live_allowed=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        package_sha256=package.package_sha256,
        soak_evidence_sha256=package.soak.evidence_sha256,
        immutable_bundle_sha256=package.immutable_bundle.sha256,
        duration_seconds=package.soak.duration_seconds,
        candidates_seen=package.soak.metrics.candidates_seen,
        replay_pass_rate_bps=package.soak.replay.pass_rate_bps,
    )


__all__ = [
    "REAL_SOAK_RESULT_SCHEMA_VERSION",
    "REAL_SOAK_SCHEMA_VERSION",
    "REQUIRED_PREREQUISITES",
    "ImmutableSoakBundle",
    "RealShadowSoakPackage",
    "RealShadowSoakReadiness",
    "RealShadowSoakState",
    "SoakPrerequisiteEvidence",
    "evaluate_real_shadow_soak",
]
