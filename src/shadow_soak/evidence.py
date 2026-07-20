"""PR-060 real shadow-soak evidence and promotion gate.

The module is deliberately runtime-neutral: it does not start discovery,
simulation, signing, submission, or live trading. It validates a durable
paper/shadow evidence package before it can become PR-047 release evidence.
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

from src.release_gate.models import (
    EvidenceKind,
    EvidenceReference,
    FilePin,
    PinKind,
)

SCHEMA_VERSION = "pr060.shadow-soak-evidence.v1"
RESULT_SCHEMA_VERSION = "pr060.shadow-soak-evaluation.v1"
MINIMUM_SOAK_SECONDS = 72 * 60 * 60
_BPS_DENOMINATOR = 10_000
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ShadowSoakError(ValueError):
    """Raised when a PR-060 evidence object is malformed."""


class SoakEnvironment(StrEnum):
    RECORDED = "recorded"
    SHADOW = "shadow"
    MAINNET_READ_ONLY = "mainnet-read-only"


class SoakArtifactKind(StrEnum):
    RAW_EVENTS = "raw-events"
    REPLAY_CORPUS = "replay-corpus"
    METRICS_REPORT = "metrics-report"
    OPERATOR_REVIEW = "operator-review"


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ShadowSoakError(f"{field} must be timezone-aware")


def _non_negative(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ShadowSoakError(f"{field} must be a non-negative integer")


def _integer(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ShadowSoakError(f"{field} must be an integer")


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


def _relative_path(value: str, field: str) -> str:
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if (
        not value
        or normalized.startswith(("/", "~"))
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ShadowSoakError(f"{field} must be a normalized relative path")
    return normalized


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        result: dict[str, Any] = {}
        for item in fields(value):
            result[item.name] = _jsonable(getattr(value, item.name))
        return result
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def stable_json(payload: Any) -> str:
    return json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"))


def sha256_payload(payload: Any) -> str:
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SoakArtifactReference:
    path: str
    sha256: str
    kind: SoakArtifactKind
    event_count: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _relative_path(self.path, "artifact.path"))
        object.__setattr__(self, "sha256", _sha256(self.sha256, "artifact.sha256"))
        if self.event_count is not None:
            _non_negative(self.event_count, "artifact.event_count")


@dataclass(frozen=True, slots=True)
class ShadowSoakMetrics:
    candidates_seen: int
    candidates_simulated: int
    candidates_rejected: int
    paper_outcomes_written: int
    outcomes_reconciled: int
    reconciliation_mismatches: int
    message_hash_mismatches: int
    repayment_mismatches: int
    ambiguous_outcomes: int
    quota_exhaustions: int
    provider_5xx_errors: int
    rpc_errors: int
    stale_data_rejections: int
    stale_data_accepted: int
    p50_latency_ms: int
    p95_latency_ms: int
    max_latency_ms: int
    net_pnl_lamports: int

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name == "net_pnl_lamports":
                _integer(value, item.name)
            else:
                _non_negative(value, item.name)
        if not self.max_latency_ms >= self.p95_latency_ms >= self.p50_latency_ms:
            raise ShadowSoakError("latencies must satisfy max >= p95 >= p50")
        if self.candidates_simulated > self.candidates_seen:
            raise ShadowSoakError("simulated candidates cannot exceed seen candidates")
        if self.paper_outcomes_written > self.candidates_simulated:
            raise ShadowSoakError("paper outcomes cannot exceed simulated candidates")
        if self.outcomes_reconciled > self.paper_outcomes_written:
            raise ShadowSoakError("reconciled outcomes cannot exceed paper outcomes")


@dataclass(frozen=True, slots=True)
class ReplayEvidence:
    corpus_events: int
    replayed_events: int
    deterministic_passed_events: int
    deterministic_failed_events: int
    corpus_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "corpus_events",
            "replayed_events",
            "deterministic_passed_events",
            "deterministic_failed_events",
        ):
            _non_negative(getattr(self, name), name)
        object.__setattr__(
            self,
            "corpus_sha256",
            _sha256(self.corpus_sha256, "corpus_sha256"),
        )
        if self.replayed_events > self.corpus_events:
            raise ShadowSoakError("replayed events cannot exceed corpus events")
        if (
            self.deterministic_passed_events + self.deterministic_failed_events
            != self.replayed_events
        ):
            raise ShadowSoakError("replay counts must sum to replayed events")

    @property
    def pass_rate_bps(self) -> int:
        if self.replayed_events == 0:
            return 0
        return (
            self.deterministic_passed_events
            * _BPS_DENOMINATOR
            // self.replayed_events
        )


@dataclass(frozen=True, slots=True)
class ShadowSoakThresholds:
    min_duration_seconds: int = MINIMUM_SOAK_SECONDS
    min_candidates_seen: int = 1
    min_reconciled_outcomes: int = 1
    min_replay_pass_rate_bps: int = _BPS_DENOMINATOR
    max_reconciliation_mismatches: int = 0
    max_message_hash_mismatches: int = 0
    max_repayment_mismatches: int = 0
    max_ambiguous_outcomes: int = 0
    max_quota_exhaustions: int = 0
    max_rpc_errors: int = 0
    max_stale_data_accepted: int = 0
    require_human_review: bool = True
    require_signed_bundle: bool = True
    required_vertical_stages: tuple[str, ...] = (
        "discovery",
        "capital",
        "planner",
        "compiler",
        "simulation",
        "reconciliation",
        "lifecycle",
    )

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name == "required_vertical_stages":
                if not value or any(not stage.strip() for stage in value):
                    raise ShadowSoakError("required stages cannot be empty")
            elif item.name in {"require_human_review", "require_signed_bundle"}:
                if not isinstance(value, bool):
                    raise ShadowSoakError(f"{item.name} must be boolean")
            else:
                _non_negative(value, item.name)
        if self.min_replay_pass_rate_bps > _BPS_DENOMINATOR:
            raise ShadowSoakError("pass-rate threshold cannot exceed 10000 bps")


@dataclass(frozen=True, slots=True)
class ShadowSoakEvidence:
    run_id: str
    code_commit: str
    started_at: datetime
    ended_at: datetime
    environment: SoakEnvironment
    vertical_stages: tuple[str, ...]
    metrics: ShadowSoakMetrics
    replay: ReplayEvidence
    artifacts: tuple[SoakArtifactReference, ...]
    operator: str
    human_reviewed: bool
    reviewer: str
    reviewed_at: datetime
    signed_by: str
    signature_reference: str
    schema_version: str = SCHEMA_VERSION
    notes: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ShadowSoakError("unsupported PR-060 evidence schema")
        if not self.run_id.strip():
            raise ShadowSoakError("run_id is required")
        object.__setattr__(
            self, "code_commit", _git_sha(self.code_commit, "code_commit")
        )
        _aware(self.started_at, "started_at")
        _aware(self.ended_at, "ended_at")
        _aware(self.reviewed_at, "reviewed_at")
        if self.ended_at <= self.started_at:
            raise ShadowSoakError("ended_at must be after started_at")
        if self.reviewed_at < self.ended_at:
            raise ShadowSoakError("reviewed_at cannot be before soak ended")
        if not self.vertical_stages or any(
            not stage.strip() for stage in self.vertical_stages
        ):
            raise ShadowSoakError("vertical stages are required")
        if len(self.vertical_stages) != len(set(self.vertical_stages)):
            raise ShadowSoakError("vertical stages must be unique")
        if not self.artifacts:
            raise ShadowSoakError("at least one evidence artifact is required")
        artifact_kinds = [artifact.kind for artifact in self.artifacts]
        if len(artifact_kinds) != len(set(artifact_kinds)):
            raise ShadowSoakError("artifact kinds must be unique")
        if not self.operator.strip():
            raise ShadowSoakError("operator is required")
        if not isinstance(self.human_reviewed, bool):
            raise ShadowSoakError("human_reviewed must be boolean")

    @property
    def duration_seconds(self) -> int:
        return int((self.ended_at - self.started_at).total_seconds())

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)

    @property
    def evidence_sha256(self) -> str:
        return sha256_payload(self.to_dict())


@dataclass(frozen=True, slots=True)
class ShadowSoakEvaluation:
    run_id: str
    promotion_ready: bool
    state: str
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    duration_seconds: int
    evidence_sha256: str
    checks_evaluated: int
    metrics_summary: Mapping[str, int]
    schema_version: str = RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)


def evaluate_shadow_soak(
    evidence: ShadowSoakEvidence,
    thresholds: ShadowSoakThresholds | None = None,
) -> ShadowSoakEvaluation:
    """Evaluate a PR-060 package without enabling any execution path."""

    policy = thresholds or ShadowSoakThresholds()
    blockers: list[str] = []
    warnings: list[str] = []
    checks = 0

    def check(condition: bool, reason: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(reason)

    metrics = evidence.metrics
    replay = evidence.replay
    stages = set(evidence.vertical_stages)
    artifacts = {artifact.kind for artifact in evidence.artifacts}

    check(
        evidence.duration_seconds >= policy.min_duration_seconds,
        "SHADOW_SOAK_DURATION_BELOW_THRESHOLD",
    )
    for stage in policy.required_vertical_stages:
        check(stage in stages, f"REQUIRED_STAGE_MISSING:{stage}")
    check(
        metrics.candidates_seen >= policy.min_candidates_seen,
        "CANDIDATES_SEEN_BELOW_THRESHOLD",
    )
    check(
        metrics.outcomes_reconciled >= policy.min_reconciled_outcomes,
        "RECONCILED_OUTCOMES_BELOW_THRESHOLD",
    )
    check(
        metrics.reconciliation_mismatches <= policy.max_reconciliation_mismatches,
        "RECONCILIATION_MISMATCHES_PRESENT",
    )
    check(
        metrics.message_hash_mismatches <= policy.max_message_hash_mismatches,
        "MESSAGE_HASH_MISMATCHES_PRESENT",
    )
    check(
        metrics.repayment_mismatches <= policy.max_repayment_mismatches,
        "REPAYMENT_MISMATCHES_PRESENT",
    )
    check(
        metrics.ambiguous_outcomes <= policy.max_ambiguous_outcomes,
        "AMBIGUOUS_OUTCOMES_PRESENT",
    )
    check(
        metrics.quota_exhaustions <= policy.max_quota_exhaustions,
        "QUOTA_EXHAUSTIONS_PRESENT",
    )
    check(metrics.rpc_errors <= policy.max_rpc_errors, "RPC_ERRORS_PRESENT")
    check(
        metrics.stale_data_accepted <= policy.max_stale_data_accepted,
        "STALE_DATA_ACCEPTED",
    )
    check(replay.replayed_events > 0, "REPLAY_CORPUS_EMPTY")
    check(
        replay.pass_rate_bps >= policy.min_replay_pass_rate_bps,
        "DETERMINISTIC_REPLAY_PASS_RATE_TOO_LOW",
    )
    check(
        replay.deterministic_failed_events == 0,
        "DETERMINISTIC_REPLAY_FAILURES_PRESENT",
    )
    check(SoakArtifactKind.RAW_EVENTS in artifacts, "RAW_EVENT_ARTIFACT_MISSING")
    check(
        SoakArtifactKind.REPLAY_CORPUS in artifacts,
        "REPLAY_CORPUS_ARTIFACT_MISSING",
    )
    check(
        SoakArtifactKind.METRICS_REPORT in artifacts,
        "METRICS_REPORT_ARTIFACT_MISSING",
    )
    if policy.require_human_review:
        check(evidence.human_reviewed, "HUMAN_REVIEW_MISSING")
        check(bool(evidence.reviewer.strip()), "REVIEWER_MISSING")
        check(
            SoakArtifactKind.OPERATOR_REVIEW in artifacts,
            "OPERATOR_REVIEW_ARTIFACT_MISSING",
        )
    if policy.require_signed_bundle:
        check(bool(evidence.signed_by.strip()), "SIGNED_EVIDENCE_MISSING")
        check(bool(evidence.signature_reference.strip()), "SIGNATURE_REFERENCE_MISSING")

    if metrics.provider_5xx_errors:
        warnings.append(f"PROVIDER_5XX_ERRORS:{metrics.provider_5xx_errors}")
    if metrics.stale_data_rejections:
        warnings.append(f"STALE_DATA_REJECTIONS:{metrics.stale_data_rejections}")
    if metrics.net_pnl_lamports < 0:
        warnings.append("NEGATIVE_SHADOW_NET_PNL_REQUIRES_REVIEW")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return ShadowSoakEvaluation(
        run_id=evidence.run_id,
        promotion_ready=not unique_blockers,
        state="shadow-soak-passed" if not unique_blockers else "blocked",
        blockers=unique_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        duration_seconds=evidence.duration_seconds,
        evidence_sha256=evidence.evidence_sha256,
        checks_evaluated=checks,
        metrics_summary={
            "candidates_seen": metrics.candidates_seen,
            "candidates_simulated": metrics.candidates_simulated,
            "paper_outcomes_written": metrics.paper_outcomes_written,
            "outcomes_reconciled": metrics.outcomes_reconciled,
            "replay_pass_rate_bps": replay.pass_rate_bps,
            "net_pnl_lamports": metrics.net_pnl_lamports,
        },
    )


def to_pr047_shadow_soak_reference(
    evidence: ShadowSoakEvidence,
    evaluation: ShadowSoakEvaluation,
    *,
    pin_path: str,
    pin_sha256: str,
) -> EvidenceReference:
    """Adapt PR-060 output into PR-047's existing PR039 evidence slot."""

    return EvidenceReference(
        kind=EvidenceKind.PR039_SHADOW_SOAK,
        schema_version=evidence.schema_version,
        pin=FilePin(path=pin_path, sha256=pin_sha256, kind=PinKind.EVIDENCE),
        passed=evaluation.promotion_ready,
        human_reviewed=evidence.human_reviewed,
        reviewer=evidence.reviewer,
        reviewed_at=evidence.reviewed_at,
    )
