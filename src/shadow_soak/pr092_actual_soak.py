"""PR-092 actual 72h sender-free shadow-soak evidence boundary.

This module does not start discovery, simulation, signing, submission, or live
trading.  It validates that a PR-092 release-review candidate is backed by a
materialized, digest-pinned, operator-reviewed artifact bundle produced by a
real shadow/mainnet-read-only run after the PR-089..091 prerequisites.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum, StrEnum
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from src.shadow_soak.evidence import (
    MINIMUM_SOAK_SECONDS,
    ShadowSoakError,
    ShadowSoakEvidence,
    ShadowSoakThresholds,
    SoakEnvironment,
    evaluate_shadow_soak,
)

PR092_ACTUAL_SOAK_SCHEMA_VERSION = "pr092.actual-shadow-soak-evidence.v1"
PR092_ACTUAL_SOAK_RESULT_SCHEMA_VERSION = "pr092.actual-shadow-soak-readiness.v1"

REQUIRED_PR092_PREREQUISITES: tuple[str, ...] = (
    "pr089.active-sender-free-paper-composition-root",
    "pr090.unified-runtime-truth-readiness",
    "pr091.security-sbom-provenance-chaos-artifacts",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_URI_PREFIXES = ("https://", "s3://", "gs://")
_FORBIDDEN_PATH_PARTS = {
    ".",
    "..",
    "",
    "fixture",
    "fixtures",
    "testdata",
    "tmp",
    "temp",
}


class PR092ActualSoakState(StrEnum):
    """Release-review state for PR-092 evidence."""

    BLOCKED = "blocked"
    READY_FOR_MANUAL_RELEASE_REVIEW = "ready-for-manual-release-review"


class PR092ActualSoakArtifactKind(StrEnum):
    """Materialized artifacts required by the PR-092 bundle."""

    RAW_EVENTS = "raw-events"
    REPLAY_CORPUS = "replay-corpus"
    METRICS_REPORT = "metrics-report"
    OPERATOR_REVIEW = "operator-review"
    DETERMINISTIC_REPLAY_REPORT = "deterministic-replay-report"
    RUNTIME_READINESS = "runtime-readiness"
    SECURITY_PROVENANCE = "security-provenance"
    IMMUTABLE_BUNDLE = "immutable-bundle"
    BUNDLE_SIGNATURE = "bundle-signature"


REQUIRED_PR092_ARTIFACTS: tuple[PR092ActualSoakArtifactKind, ...] = (
    PR092ActualSoakArtifactKind.RAW_EVENTS,
    PR092ActualSoakArtifactKind.REPLAY_CORPUS,
    PR092ActualSoakArtifactKind.METRICS_REPORT,
    PR092ActualSoakArtifactKind.OPERATOR_REVIEW,
    PR092ActualSoakArtifactKind.DETERMINISTIC_REPLAY_REPORT,
    PR092ActualSoakArtifactKind.RUNTIME_READINESS,
    PR092ActualSoakArtifactKind.SECURITY_PROVENANCE,
    PR092ActualSoakArtifactKind.IMMUTABLE_BUNDLE,
    PR092ActualSoakArtifactKind.BUNDLE_SIGNATURE,
)


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ShadowSoakError(f"{field} must be timezone-aware")


def _sha256(value: str, field: str) -> str:
    lowered = value.lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise ShadowSoakError(f"{field} must be a non-placeholder sha256")
    if len(set(lowered)) < 8:
        raise ShadowSoakError(f"{field} must not be a low-entropy fixture sha256")
    return lowered


def _git_sha(value: str, field: str) -> str:
    lowered = value.lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise ShadowSoakError(f"{field} must be a non-placeholder git SHA")
    if len(set(lowered)) < 8:
        raise ShadowSoakError(f"{field} must not be a low-entropy fixture git SHA")
    return lowered


def _relative_path_or_uri(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ShadowSoakError(f"{field} is required")
    if cleaned.startswith(_URI_PREFIXES):
        return cleaned
    normalized = cleaned.replace("\\", "/")
    parts = normalized.split("/")
    if normalized.startswith(("/", "~")) or any(
        part.lower() in _FORBIDDEN_PATH_PARTS for part in parts
    ):
        raise ShadowSoakError(
            f"{field} must be a normalized non-fixture relative path or URI"
        )
    return normalized


def _is_uri(value: str) -> bool:
    return value.startswith(_URI_PREFIXES)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            item.name: _jsonable(getattr(value, item.name)) for item in fields(value)
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
class PR092SoakArtifactPin:
    """Digest-pinned file or immutable storage object for a real soak bundle."""

    kind: PR092ActualSoakArtifactKind
    path: str
    sha256: str
    size_bytes: int
    produced_at: datetime
    producer: str
    event_count: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PR092ActualSoakArtifactKind):
            object.__setattr__(
                self, "kind", PR092ActualSoakArtifactKind(str(self.kind))
            )
        object.__setattr__(self, "path", _relative_path_or_uri(self.path, "path"))
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))
        if isinstance(self.size_bytes, bool) or self.size_bytes <= 0:
            raise ShadowSoakError("size_bytes must be a positive integer")
        _aware(self.produced_at, "produced_at")
        if not self.producer.strip():
            raise ShadowSoakError("producer is required")
        if self.event_count is not None and (
            isinstance(self.event_count, bool) or self.event_count < 0
        ):
            raise ShadowSoakError("event_count must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class PR092PrerequisiteEvidence:
    """Human-reviewed prerequisite evidence required before PR-092 can pass."""

    name: str
    evidence_path: str
    evidence_sha256: str
    source_commit: str
    passed: bool
    human_reviewed: bool
    reviewer: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ShadowSoakError("prerequisite.name is required")
        object.__setattr__(
            self,
            "evidence_path",
            _relative_path_or_uri(self.evidence_path, "prerequisite.evidence_path"),
        )
        object.__setattr__(
            self,
            "evidence_sha256",
            _sha256(self.evidence_sha256, "prerequisite.evidence_sha256"),
        )
        object.__setattr__(
            self,
            "source_commit",
            _git_sha(self.source_commit, "prerequisite.source_commit"),
        )
        if not isinstance(self.passed, bool):
            raise ShadowSoakError("prerequisite.passed must be boolean")
        if not isinstance(self.human_reviewed, bool):
            raise ShadowSoakError("prerequisite.human_reviewed must be boolean")
        if self.human_reviewed and not self.reviewer.strip():
            raise ShadowSoakError("reviewed prerequisite must include reviewer")


@dataclass(frozen=True, slots=True)
class PR092ActualSoakManifest:
    """Actual PR-092 72h+ soak manifest for manual release review."""

    run_id: str
    soak: ShadowSoakEvidence
    prerequisites: tuple[PR092PrerequisiteEvidence, ...]
    artifacts: tuple[PR092SoakArtifactPin, ...]
    release_candidate_commit: str
    runtime_truth_sha256: str
    assembled_at: datetime
    assembled_by: str
    reviewed_by: str
    deterministic_replay_verified: bool
    no_sender_imports_observed: bool
    sender_endpoints_enabled: bool
    live_submissions_observed: int
    schema_version: str = PR092_ACTUAL_SOAK_SCHEMA_VERSION
    notes: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != PR092_ACTUAL_SOAK_SCHEMA_VERSION:
            raise ShadowSoakError("unsupported PR-092 actual soak schema")
        if not self.run_id.strip():
            raise ShadowSoakError("run_id is required")
        if self.run_id != self.soak.run_id:
            raise ShadowSoakError("manifest.run_id must match soak.run_id")
        if not self.prerequisites:
            raise ShadowSoakError("PR-092 prerequisites are required")
        if not self.artifacts:
            raise ShadowSoakError("PR-092 artifacts are required")
        prereq_names = [item.name for item in self.prerequisites]
        if len(prereq_names) != len(set(prereq_names)):
            raise ShadowSoakError("prerequisite names must be unique")
        artifact_kinds = [item.kind for item in self.artifacts]
        if len(artifact_kinds) != len(set(artifact_kinds)):
            raise ShadowSoakError("PR-092 artifact kinds must be unique")
        object.__setattr__(
            self,
            "release_candidate_commit",
            _git_sha(self.release_candidate_commit, "release_candidate_commit"),
        )
        if self.release_candidate_commit != self.soak.code_commit:
            raise ShadowSoakError("release candidate commit must match soak code_commit")
        object.__setattr__(
            self,
            "runtime_truth_sha256",
            _sha256(self.runtime_truth_sha256, "runtime_truth_sha256"),
        )
        _aware(self.assembled_at, "assembled_at")
        if self.assembled_at < self.soak.reviewed_at:
            raise ShadowSoakError("assembled_at cannot be before soak human review")
        if not self.assembled_by.strip():
            raise ShadowSoakError("assembled_by is required")
        if not self.reviewed_by.strip():
            raise ShadowSoakError("reviewed_by is required")
        for name in (
            "deterministic_replay_verified",
            "no_sender_imports_observed",
            "sender_endpoints_enabled",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ShadowSoakError(f"{name} must be boolean")
        if (
            isinstance(self.live_submissions_observed, bool)
            or self.live_submissions_observed < 0
        ):
            raise ShadowSoakError("live_submissions_observed must be non-negative int")

    @property
    def manifest_sha256(self) -> str:
        return _sha256_payload(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class PR092MaterializedArtifactCheck:
    """Result of hashing the actual files referenced by a PR-092 manifest."""

    checked: bool
    checked_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]
    hash_mismatches: tuple[str, ...]
    size_mismatches: tuple[str, ...]
    unsupported_uris: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            self.checked
            and not self.missing_paths
            and not self.hash_mismatches
            and not self.size_mismatches
            and not self.unsupported_uris
        )

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class PR092ActualSoakReadiness:
    """Fail-closed PR-092 readiness result."""

    run_id: str
    state: PR092ActualSoakState
    release_evidence_ready: bool
    live_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    manifest_sha256: str
    soak_evidence_sha256: str
    duration_seconds: int
    candidates_seen: int
    replay_pass_rate_bps: int
    artifact_check: PR092MaterializedArtifactCheck
    schema_version: str = PR092_ACTUAL_SOAK_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def check_pr092_materialized_artifacts(
    manifest: PR092ActualSoakManifest,
    artifact_root: Path | None,
) -> PR092MaterializedArtifactCheck:
    """Hash referenced PR-092 artifact files under ``artifact_root``.

    Passing ``None`` intentionally fails closed.  Remote URIs are preserved in
    the manifest for provenance, but this PR-092 gate only marks evidence ready
    after local/repository files are materialized and their bytes are hashed.
    """

    if artifact_root is None:
        return PR092MaterializedArtifactCheck(
            checked=False,
            checked_paths=(),
            missing_paths=(),
            hash_mismatches=(),
            size_mismatches=(),
            unsupported_uris=(),
        )

    root = artifact_root.resolve()
    checked_paths: list[str] = []
    missing_paths: list[str] = []
    hash_mismatches: list[str] = []
    size_mismatches: list[str] = []
    unsupported_uris: list[str] = []

    for artifact in manifest.artifacts:
        if _is_uri(artifact.path):
            unsupported_uris.append(artifact.path)
            continue
        candidate = (root / artifact.path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            missing_paths.append(artifact.path)
            continue
        if not candidate.is_file():
            missing_paths.append(artifact.path)
            continue
        payload = candidate.read_bytes()
        checked_paths.append(artifact.path)
        if hashlib.sha256(payload).hexdigest() != artifact.sha256:
            hash_mismatches.append(artifact.path)
        if len(payload) != artifact.size_bytes:
            size_mismatches.append(artifact.path)

    return PR092MaterializedArtifactCheck(
        checked=True,
        checked_paths=tuple(checked_paths),
        missing_paths=tuple(missing_paths),
        hash_mismatches=tuple(hash_mismatches),
        size_mismatches=tuple(size_mismatches),
        unsupported_uris=tuple(unsupported_uris),
    )


def evaluate_pr092_actual_shadow_soak(
    manifest: PR092ActualSoakManifest,
    *,
    artifact_root: Path | None = None,
    thresholds: ShadowSoakThresholds | None = None,
) -> PR092ActualSoakReadiness:
    """Evaluate PR-092 actual soak evidence without enabling live submission."""

    policy = thresholds or ShadowSoakThresholds(
        min_duration_seconds=MINIMUM_SOAK_SECONDS,
        min_candidates_seen=1,
        min_reconciled_outcomes=1,
    )
    fresh_evaluation = evaluate_shadow_soak(manifest.soak, policy)
    artifact_check = check_pr092_materialized_artifacts(manifest, artifact_root)
    blockers: list[str] = []
    warnings: list[str] = list(fresh_evaluation.warnings)

    def block(condition: bool, reason: str) -> None:
        if not condition:
            blockers.append(reason)

    block(
        manifest.soak.environment
        in {SoakEnvironment.SHADOW, SoakEnvironment.MAINNET_READ_ONLY},
        "RECORDED_FIXTURE_NOT_ACTUAL_SOAK",
    )
    block(
        manifest.soak.duration_seconds >= MINIMUM_SOAK_SECONDS,
        "ACTUAL_SOAK_DURATION_BELOW_72H",
    )
    block(fresh_evaluation.promotion_ready, "PR060_SHADOW_SOAK_EVALUATION_BLOCKED")
    for reason in fresh_evaluation.blockers:
        blockers.append(f"PR060:{reason}")

    prerequisites = {item.name: item for item in manifest.prerequisites}
    for name in REQUIRED_PR092_PREREQUISITES:
        prereq = prerequisites.get(name)
        if prereq is None:
            blockers.append(f"PREREQUISITE_MISSING:{name}")
            continue
        block(prereq.passed, f"PREREQUISITE_NOT_PASSED:{name}")
        block(prereq.human_reviewed, f"PREREQUISITE_NOT_REVIEWED:{name}")

    artifacts = {item.kind: item for item in manifest.artifacts}
    for kind in REQUIRED_PR092_ARTIFACTS:
        block(kind in artifacts, f"ARTIFACT_MISSING:{kind.value}")

    soak_artifacts = {
        artifact.kind.value: artifact for artifact in manifest.soak.artifacts
    }
    for kind in (
        PR092ActualSoakArtifactKind.RAW_EVENTS,
        PR092ActualSoakArtifactKind.REPLAY_CORPUS,
        PR092ActualSoakArtifactKind.METRICS_REPORT,
        PR092ActualSoakArtifactKind.OPERATOR_REVIEW,
    ):
        soak_artifact = soak_artifacts.get(kind.value)
        actual_artifact = artifacts.get(kind)
        block(soak_artifact is not None, f"SOAK_ARTIFACT_MISSING:{kind.value}")
        if soak_artifact is not None and actual_artifact is not None:
            block(
                soak_artifact.sha256 == actual_artifact.sha256,
                f"SOAK_ARTIFACT_HASH_MISMATCH:{kind.value}",
            )

    block(artifact_check.checked, "MATERIALIZED_ARTIFACT_CHECK_NOT_RUN")
    for path in artifact_check.unsupported_uris:
        blockers.append(f"ARTIFACT_URI_NOT_MATERIALIZED:{path}")
    for path in artifact_check.missing_paths:
        blockers.append(f"ARTIFACT_FILE_MISSING:{path}")
    for path in artifact_check.hash_mismatches:
        blockers.append(f"ARTIFACT_HASH_MISMATCH:{path}")
    for path in artifact_check.size_mismatches:
        blockers.append(f"ARTIFACT_SIZE_MISMATCH:{path}")

    block(
        manifest.deterministic_replay_verified,
        "DETERMINISTIC_REPLAY_NOT_VERIFIED",
    )
    block(
        manifest.no_sender_imports_observed,
        "SENDER_IMPORT_OBSERVED_DURING_SOAK",
    )
    block(not manifest.sender_endpoints_enabled, "SENDER_ENDPOINT_ENABLED_DURING_SOAK")
    block(manifest.live_submissions_observed == 0, "LIVE_SUBMISSIONS_OBSERVED")
    if manifest.soak.metrics.net_pnl_lamports < 0:
        warnings.append("NEGATIVE_ACTUAL_SOAK_NET_PNL_REQUIRES_RELEASE_REVIEW")

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    return PR092ActualSoakReadiness(
        run_id=manifest.run_id,
        state=(
            PR092ActualSoakState.READY_FOR_MANUAL_RELEASE_REVIEW
            if ready
            else PR092ActualSoakState.BLOCKED
        ),
        release_evidence_ready=ready,
        live_allowed=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        manifest_sha256=manifest.manifest_sha256,
        soak_evidence_sha256=manifest.soak.evidence_sha256,
        duration_seconds=manifest.soak.duration_seconds,
        candidates_seen=manifest.soak.metrics.candidates_seen,
        replay_pass_rate_bps=manifest.soak.replay.pass_rate_bps,
        artifact_check=artifact_check,
    )


__all__ = [
    "PR092_ACTUAL_SOAK_RESULT_SCHEMA_VERSION",
    "PR092_ACTUAL_SOAK_SCHEMA_VERSION",
    "REQUIRED_PR092_ARTIFACTS",
    "REQUIRED_PR092_PREREQUISITES",
    "PR092ActualSoakArtifactKind",
    "PR092ActualSoakManifest",
    "PR092ActualSoakReadiness",
    "PR092ActualSoakState",
    "PR092MaterializedArtifactCheck",
    "PR092PrerequisiteEvidence",
    "PR092SoakArtifactPin",
    "check_pr092_materialized_artifacts",
    "evaluate_pr092_actual_shadow_soak",
]
