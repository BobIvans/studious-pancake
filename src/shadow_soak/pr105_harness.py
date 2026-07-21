"""PR-105 sender-free shadow-soak harness planning boundary.

The PR-092 gate validates completed 72-hour evidence. This module defines the
reviewable run harness that operators can start before such evidence exists. It
never connects to RPC, imports a sender, signs, submits, polls, or waits 72h by
itself; it only plans and validates the sender-free artifact contract that a real
long-running process must satisfy later.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum, StrEnum
import hashlib
import json
import re
from typing import Any

from src.shadow_soak.evidence import (
    MINIMUM_SOAK_SECONDS,
    ShadowSoakError,
    SoakEnvironment,
)
from src.shadow_soak.pr092_actual_soak import (
    PR092ActualSoakArtifactKind,
    REQUIRED_PR092_ARTIFACTS,
    REQUIRED_PR092_PREREQUISITES,
)

PR105_HARNESS_SCHEMA_VERSION = "pr105.sender-free-shadow-soak-harness.v1"
PR105_HARNESS_RESULT_SCHEMA_VERSION = "pr105.sender-free-shadow-soak-readiness.v1"

_REQUIRED_STAGE_STREAMS: tuple[str, ...] = (
    "discovery",
    "capital",
    "planner",
    "compiler",
    "simulation",
    "reconciliation",
    "lifecycle",
)
_REQUIRED_TELEMETRY_STREAMS: tuple[str, ...] = (
    "rejections",
    "latency",
    "quota",
    "staleness",
    "message-hash",
    "repayment",
)
_ARTIFACT_FILENAMES: Mapping[PR092ActualSoakArtifactKind, str] = {
    PR092ActualSoakArtifactKind.RAW_EVENTS: "raw-events.jsonl",
    PR092ActualSoakArtifactKind.REPLAY_CORPUS: "replay-corpus.jsonl",
    PR092ActualSoakArtifactKind.METRICS_REPORT: "metrics.json",
    PR092ActualSoakArtifactKind.OPERATOR_REVIEW: "operator-review.md",
    PR092ActualSoakArtifactKind.DETERMINISTIC_REPLAY_REPORT: "replay-report.json",
    PR092ActualSoakArtifactKind.RUNTIME_READINESS: "runtime-readiness.json",
    PR092ActualSoakArtifactKind.SECURITY_PROVENANCE: "security-provenance.json",
    PR092ActualSoakArtifactKind.IMMUTABLE_BUNDLE: "immutable-bundle.tar.zst",
    PR092ActualSoakArtifactKind.BUNDLE_SIGNATURE: "immutable-bundle.sig",
}
_RUN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN_PATH_PARTS = {"", ".", "..", "tmp", "temp", "fixture", "fixtures"}


class PR105HarnessState(StrEnum):
    """Machine-readable state for the sender-free soak harness."""

    BLOCKED = "blocked"
    READY_TO_START = "ready-to-start"
    RUNNING = "running"
    READY_FOR_PR092_ASSEMBLY = "ready-for-pr092-assembly"


class PR105HarnessCommand(StrEnum):
    """Operational steps in the planned sender-free harness."""

    RECORD_START = "record-start"
    RUN_SHADOW_CYCLE = "run-shadow-cycle"
    RECORD_TELEMETRY = "record-telemetry"
    FINALIZE_METRICS = "finalize-metrics"
    VERIFY_REPLAY = "verify-replay"
    SEAL_BUNDLE = "seal-bundle"


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ShadowSoakError(f"{field} must be timezone-aware")


def _git_sha(value: str, field: str) -> str:
    lowered = value.lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise ShadowSoakError(f"{field} must be a non-placeholder git SHA")
    if len(set(lowered)) < 8:
        raise ShadowSoakError(f"{field} must not be a low-entropy fixture git SHA")
    return lowered


def _run_id(value: str) -> str:
    cleaned = value.strip()
    if not _RUN_ID_RE.fullmatch(cleaned):
        raise ShadowSoakError("run_id must be a normalized non-fixture slug")
    lowered = cleaned.lower()
    forbidden = {"tmp", "temp", "fixture", "fixtures"}
    if any(part in forbidden for part in lowered.split("-")):
        raise ShadowSoakError("run_id must not point to temporary or fixture evidence")
    return lowered


def _relative_path(value: str, field: str) -> str:
    cleaned = value.strip().replace("\\", "/")
    parts = cleaned.split("/")
    if cleaned.startswith(("/", "~")) or any(
        part.lower() in _FORBIDDEN_PATH_PARTS for part in parts
    ):
        raise ShadowSoakError(f"{field} must be a normalized non-fixture path")
    return cleaned


def _positive(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ShadowSoakError(f"{field} must be a positive integer")


def _non_negative(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ShadowSoakError(f"{field} must be a non-negative integer")


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
class PR105HarnessArtifactTarget:
    """Planned artifact that must later be materialized for PR-092 evaluation."""

    kind: PR092ActualSoakArtifactKind
    path: str
    produced_by: PR105HarnessCommand
    required_before_pr092: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PR092ActualSoakArtifactKind):
            object.__setattr__(
                self,
                "kind",
                PR092ActualSoakArtifactKind(str(self.kind)),
            )
        if not isinstance(self.produced_by, PR105HarnessCommand):
            object.__setattr__(
                self,
                "produced_by",
                PR105HarnessCommand(str(self.produced_by)),
            )
        object.__setattr__(self, "path", _relative_path(self.path, "artifact.path"))
        if not isinstance(self.required_before_pr092, bool):
            raise ShadowSoakError("required_before_pr092 must be boolean")


@dataclass(frozen=True, slots=True)
class PR105HarnessStep:
    """One sender-free command boundary in the long-running soak harness."""

    command: PR105HarnessCommand
    description: str
    required_streams: tuple[str, ...]
    produces: tuple[PR092ActualSoakArtifactKind, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.command, PR105HarnessCommand):
            object.__setattr__(self, "command", PR105HarnessCommand(str(self.command)))
        if not self.description.strip():
            raise ShadowSoakError("harness step description is required")
        if not self.required_streams:
            raise ShadowSoakError("harness step must declare required streams")
        for stream in self.required_streams:
            if not stream.strip():
                raise ShadowSoakError("required stream names cannot be empty")
        for item in self.produces:
            if not isinstance(item, PR092ActualSoakArtifactKind):
                PR092ActualSoakArtifactKind(str(item))


@dataclass(frozen=True, slots=True)
class PR105ShadowSoakHarnessConfig:
    """Operator-provided plan for one real sender-free shadow soak run."""

    run_id: str
    code_commit: str
    operator: str
    started_at: datetime
    environment: SoakEnvironment = SoakEnvironment.SHADOW
    duration_seconds: int = MINIMUM_SOAK_SECONDS
    artifact_prefix: str = "artifacts/pr105"
    minimum_sample_threshold: int = 1
    cycle_interval_seconds: int = 15
    sender_enabled: bool = False
    live_submission_enabled: bool = False
    submission_endpoints_enabled: bool = False
    allow_recorded_fixtures: bool = False
    schema_version: str = PR105_HARNESS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR105_HARNESS_SCHEMA_VERSION:
            raise ShadowSoakError("unsupported PR-105 harness schema")
        object.__setattr__(self, "run_id", _run_id(self.run_id))
        object.__setattr__(
            self,
            "code_commit",
            _git_sha(self.code_commit, "code_commit"),
        )
        if not self.operator.strip():
            raise ShadowSoakError("operator is required")
        _aware(self.started_at, "started_at")
        if not isinstance(self.environment, SoakEnvironment):
            object.__setattr__(
                self,
                "environment",
                SoakEnvironment(str(self.environment)),
            )
        object.__setattr__(
            self,
            "artifact_prefix",
            _relative_path(self.artifact_prefix, "artifact_prefix"),
        )
        _positive(self.duration_seconds, "duration_seconds")
        _positive(self.minimum_sample_threshold, "minimum_sample_threshold")
        _positive(self.cycle_interval_seconds, "cycle_interval_seconds")
        if self.duration_seconds < MINIMUM_SOAK_SECONDS:
            raise ShadowSoakError("PR-105 soak duration must be at least 72 hours")
        if (
            self.environment is SoakEnvironment.RECORDED
            and not self.allow_recorded_fixtures
        ):
            raise ShadowSoakError("PR-105 harness cannot use recorded fixtures")
        for name in (
            "sender_enabled",
            "live_submission_enabled",
            "submission_endpoints_enabled",
            "allow_recorded_fixtures",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ShadowSoakError(f"{name} must be boolean")


@dataclass(frozen=True, slots=True)
class PR105ShadowSoakHarnessPlan:
    """Reviewable, sender-free plan for a real long-running soak."""

    run_id: str
    state: PR105HarnessState
    code_commit: str
    environment: SoakEnvironment
    started_at: datetime
    planned_end_at: datetime
    artifact_prefix: str
    artifacts: tuple[PR105HarnessArtifactTarget, ...]
    steps: tuple[PR105HarnessStep, ...]
    required_pr092_prerequisites: tuple[str, ...]
    live_allowed: bool
    sender_enabled: bool
    submission_endpoints_enabled: bool
    pr092_evidence_claimed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    schema_version: str = PR105_HARNESS_SCHEMA_VERSION

    @property
    def plan_sha256(self) -> str:
        return _sha256_payload(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


@dataclass(frozen=True, slots=True)
class PR105HarnessRunSnapshot:
    """Observed progress for a sender-free soak run."""

    run_id: str
    observed_at: datetime
    started_at: datetime
    ended_at: datetime | None
    events_recorded: int
    candidates_seen: int
    materialized_artifact_paths: tuple[str, ...]
    replay_verified: bool
    operator_review_recorded: bool
    sender_imports_observed: bool
    submission_endpoints_enabled: bool
    live_submissions_observed: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _run_id(self.run_id))
        _aware(self.observed_at, "observed_at")
        _aware(self.started_at, "started_at")
        if self.ended_at is not None:
            _aware(self.ended_at, "ended_at")
            if self.ended_at < self.started_at:
                raise ShadowSoakError("ended_at cannot be before started_at")
        for name in (
            "events_recorded",
            "candidates_seen",
            "live_submissions_observed",
        ):
            _non_negative(getattr(self, name), name)
        object.__setattr__(
            self,
            "materialized_artifact_paths",
            tuple(
                _relative_path(path, "materialized_artifact_path")
                for path in self.materialized_artifact_paths
            ),
        )
        for name in (
            "replay_verified",
            "operator_review_recorded",
            "sender_imports_observed",
            "submission_endpoints_enabled",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ShadowSoakError(f"{name} must be boolean")


@dataclass(frozen=True, slots=True)
class PR105HarnessReadiness:
    """Fail-closed readiness for PR-092 manifest assembly."""

    run_id: str
    state: PR105HarnessState
    ready_for_pr092_assembly: bool
    live_allowed: bool
    runtime_submission_enabled: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    elapsed_seconds: int
    events_recorded: int
    candidates_seen: int
    missing_artifact_paths: tuple[str, ...]
    schema_version: str = PR105_HARNESS_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def build_pr105_shadow_soak_harness(
    config: PR105ShadowSoakHarnessConfig,
) -> PR105ShadowSoakHarnessPlan:
    """Build a sender-free plan for a future 72h+ shadow/mainnet-read-only soak."""

    blockers: list[str] = []
    warnings: list[str] = []
    if config.sender_enabled:
        blockers.append("SENDER_ENABLED")
    if config.live_submission_enabled:
        blockers.append("LIVE_SUBMISSION_ENABLED")
    if config.submission_endpoints_enabled:
        blockers.append("SUBMISSION_ENDPOINTS_ENABLED")
    if config.environment is SoakEnvironment.RECORDED:
        blockers.append("RECORDED_FIXTURE_ENVIRONMENT")
    if config.minimum_sample_threshold <= 0:
        blockers.append("MINIMUM_SAMPLE_THRESHOLD_NOT_POSITIVE")

    artifact_prefix = f"{config.artifact_prefix}/{config.run_id}"
    artifacts = tuple(
        PR105HarnessArtifactTarget(
            kind=kind,
            path=f"{artifact_prefix}/{_ARTIFACT_FILENAMES[kind]}",
            produced_by=_producer_for_artifact(kind),
        )
        for kind in REQUIRED_PR092_ARTIFACTS
    )
    steps = _default_steps()
    if config.duration_seconds == MINIMUM_SOAK_SECONDS:
        warnings.append("minimum 72h soak configured; no time buffer above threshold")

    return PR105ShadowSoakHarnessPlan(
        run_id=config.run_id,
        state=(
            PR105HarnessState.BLOCKED if blockers else PR105HarnessState.READY_TO_START
        ),
        code_commit=config.code_commit,
        environment=config.environment,
        started_at=config.started_at,
        planned_end_at=config.started_at + timedelta(seconds=config.duration_seconds),
        artifact_prefix=artifact_prefix,
        artifacts=artifacts,
        steps=steps,
        required_pr092_prerequisites=REQUIRED_PR092_PREREQUISITES,
        live_allowed=False,
        sender_enabled=False,
        submission_endpoints_enabled=False,
        pr092_evidence_claimed=False,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def evaluate_pr105_harness_snapshot(
    plan: PR105ShadowSoakHarnessPlan,
    snapshot: PR105HarnessRunSnapshot,
) -> PR105HarnessReadiness:
    """Evaluate observed PR-105 progress without claiming PR-092 evidence."""

    blockers: list[str] = list(plan.blockers)
    warnings: list[str] = list(plan.warnings)
    if plan.run_id != snapshot.run_id:
        blockers.append("RUN_ID_MISMATCH")
    if plan.live_allowed or plan.sender_enabled or plan.submission_endpoints_enabled:
        blockers.append("PLAN_NOT_SENDER_FREE")
    if snapshot.sender_imports_observed:
        blockers.append("SENDER_IMPORT_OBSERVED")
    if snapshot.submission_endpoints_enabled:
        blockers.append("SUBMISSION_ENDPOINT_ENABLED")
    if snapshot.live_submissions_observed != 0:
        blockers.append("LIVE_SUBMISSIONS_OBSERVED")
    if snapshot.candidates_seen < 1:
        blockers.append("NO_REAL_CANDIDATES_OBSERVED")
    if snapshot.events_recorded < snapshot.candidates_seen:
        blockers.append("EVENT_COUNT_BELOW_CANDIDATES")
    if not snapshot.replay_verified:
        blockers.append("REPLAY_NOT_VERIFIED")
    if not snapshot.operator_review_recorded:
        blockers.append("OPERATOR_REVIEW_NOT_RECORDED")

    effective_end = snapshot.ended_at or snapshot.observed_at
    elapsed_seconds = int((effective_end - snapshot.started_at).total_seconds())
    if elapsed_seconds < MINIMUM_SOAK_SECONDS:
        blockers.append("PR105_DURATION_BELOW_72H")
    if snapshot.ended_at is None:
        blockers.append("PR105_RUN_NOT_FINALIZED")

    materialized = set(snapshot.materialized_artifact_paths)
    missing_paths = tuple(
        artifact.path
        for artifact in plan.artifacts
        if artifact.required_before_pr092 and artifact.path not in materialized
    )
    for path in missing_paths:
        blockers.append(f"ARTIFACT_NOT_MATERIALIZED:{path}")

    unique_blockers = tuple(dict.fromkeys(blockers))
    ready = not unique_blockers
    state = (
        PR105HarnessState.READY_FOR_PR092_ASSEMBLY
        if ready
        else (
            PR105HarnessState.RUNNING
            if snapshot.ended_at is None
            else PR105HarnessState.BLOCKED
        )
    )
    if ready:
        warnings.append(
            "PR-105 harness complete; PR-092 must still hash files and evaluate"
            " manifest"
        )
    return PR105HarnessReadiness(
        run_id=plan.run_id,
        state=state,
        ready_for_pr092_assembly=ready,
        live_allowed=False,
        runtime_submission_enabled=False,
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        elapsed_seconds=max(elapsed_seconds, 0),
        events_recorded=snapshot.events_recorded,
        candidates_seen=snapshot.candidates_seen,
        missing_artifact_paths=missing_paths,
    )


def _producer_for_artifact(
    kind: PR092ActualSoakArtifactKind,
) -> PR105HarnessCommand:
    if kind in {
        PR092ActualSoakArtifactKind.RAW_EVENTS,
        PR092ActualSoakArtifactKind.RUNTIME_READINESS,
    }:
        return PR105HarnessCommand.RECORD_TELEMETRY
    if kind is PR092ActualSoakArtifactKind.METRICS_REPORT:
        return PR105HarnessCommand.FINALIZE_METRICS
    if kind in {
        PR092ActualSoakArtifactKind.REPLAY_CORPUS,
        PR092ActualSoakArtifactKind.DETERMINISTIC_REPLAY_REPORT,
    }:
        return PR105HarnessCommand.VERIFY_REPLAY
    if kind is PR092ActualSoakArtifactKind.OPERATOR_REVIEW:
        return PR105HarnessCommand.FINALIZE_METRICS
    if kind in {
        PR092ActualSoakArtifactKind.SECURITY_PROVENANCE,
        PR092ActualSoakArtifactKind.IMMUTABLE_BUNDLE,
        PR092ActualSoakArtifactKind.BUNDLE_SIGNATURE,
    }:
        return PR105HarnessCommand.SEAL_BUNDLE
    raise AssertionError("unhandled PR-092 artifact kind")


def _default_steps() -> tuple[PR105HarnessStep, ...]:
    return (
        PR105HarnessStep(
            command=PR105HarnessCommand.RECORD_START,
            description="write start metadata with code commit and runtime truth hash",
            required_streams=("run-start",),
        ),
        PR105HarnessStep(
            command=PR105HarnessCommand.RUN_SHADOW_CYCLE,
            description="run sender-free discovery through paper simulation only",
            required_streams=_REQUIRED_STAGE_STREAMS,
        ),
        PR105HarnessStep(
            command=PR105HarnessCommand.RECORD_TELEMETRY,
            description="append metrics, rejection, latency and staleness telemetry",
            required_streams=_REQUIRED_TELEMETRY_STREAMS,
            produces=(
                PR092ActualSoakArtifactKind.RAW_EVENTS,
                PR092ActualSoakArtifactKind.RUNTIME_READINESS,
            ),
        ),
        PR105HarnessStep(
            command=PR105HarnessCommand.FINALIZE_METRICS,
            description="close run, summarize metrics and record operator review",
            required_streams=("run-end", "operator-review"),
            produces=(
                PR092ActualSoakArtifactKind.METRICS_REPORT,
                PR092ActualSoakArtifactKind.OPERATOR_REVIEW,
            ),
        ),
        PR105HarnessStep(
            command=PR105HarnessCommand.VERIFY_REPLAY,
            description="build replay corpus and verify deterministic replay",
            required_streams=("replay-corpus", "deterministic-replay"),
            produces=(
                PR092ActualSoakArtifactKind.REPLAY_CORPUS,
                PR092ActualSoakArtifactKind.DETERMINISTIC_REPLAY_REPORT,
            ),
        ),
        PR105HarnessStep(
            command=PR105HarnessCommand.SEAL_BUNDLE,
            description="create immutable bundle, signature and provenance pins",
            required_streams=("bundle", "signature", "security-provenance"),
            produces=(
                PR092ActualSoakArtifactKind.SECURITY_PROVENANCE,
                PR092ActualSoakArtifactKind.IMMUTABLE_BUNDLE,
                PR092ActualSoakArtifactKind.BUNDLE_SIGNATURE,
            ),
        ),
    )


__all__ = [
    "PR105_HARNESS_RESULT_SCHEMA_VERSION",
    "PR105_HARNESS_SCHEMA_VERSION",
    "PR105HarnessArtifactTarget",
    "PR105HarnessCommand",
    "PR105HarnessReadiness",
    "PR105HarnessRunSnapshot",
    "PR105HarnessState",
    "PR105HarnessStep",
    "PR105ShadowSoakHarnessConfig",
    "PR105ShadowSoakHarnessPlan",
    "build_pr105_shadow_soak_harness",
    "evaluate_pr105_harness_snapshot",
]
