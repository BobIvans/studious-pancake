"""MPR-2607 residual shadow-soak evidence qualification.

This module is deliberately consumer-only. It does not start a campaign, poll
providers, sign, submit, mutate lifecycle state, or create a second readiness
authority. It independently derives campaign coverage and outcome uniqueness
from already-produced evidence and composes with the existing PR-079 evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
from typing import Iterable, Mapping, Sequence

from src.shadow_soak.evidence import ShadowSoakThresholds
from src.shadow_soak.real_soak import (
    RealShadowSoakPackage,
    RealShadowSoakReadiness,
    evaluate_real_shadow_soak,
)

CAMPAIGN_EVIDENCE_SCHEMA_VERSION = "mpr2607.campaign-evidence.v1"
CAMPAIGN_QUALIFICATION_SCHEMA_VERSION = "mpr2607.campaign-qualification.v1"


class CampaignEvidenceError(ValueError):
    """Raised when residual campaign evidence is malformed."""


class EvidenceClass(StrEnum):
    SYNTHETIC_OFFLINE = "synthetic-offline"
    RECORDED_REPLAY = "recorded-replay"
    REAL_SHADOW_READ_ONLY = "real-shadow-read-only"


class IntervalKind(StrEnum):
    ELIGIBLE = "eligible"
    BLOCKED = "blocked"
    DOWNTIME = "downtime"
    FAULT = "fault"


@dataclass(frozen=True, slots=True)
class CampaignPolicy:
    minimum_eligible_seconds: int
    maximum_gap_seconds: int
    minimum_terminal_samples: int = 1

    def __post_init__(self) -> None:
        for name in (
            "minimum_eligible_seconds",
            "maximum_gap_seconds",
            "minimum_terminal_samples",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CampaignEvidenceError(f"{name} must be a non-negative integer")
        if self.minimum_terminal_samples == 0:
            raise CampaignEvidenceError("minimum_terminal_samples must be positive")


@dataclass(frozen=True, slots=True)
class CoverageInterval:
    segment_id: str
    started_at: datetime
    ended_at: datetime
    evidence_class: EvidenceClass
    kind: IntervalKind = IntervalKind.ELIGIBLE
    source_cursor: str = ""

    def __post_init__(self) -> None:
        if not self.segment_id.strip():
            raise CampaignEvidenceError("segment_id is required")
        _aware(self.started_at, "started_at")
        _aware(self.ended_at, "ended_at")
        if self.ended_at <= self.started_at:
            raise CampaignEvidenceError("coverage interval must have positive duration")
        if not self.source_cursor.strip():
            raise CampaignEvidenceError("source_cursor is required")


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    outcome_id: str
    semantic_sha256: str
    source_observation_id: str
    logical_cycle_id: str
    provider_attempt_id: str
    terminal: bool

    def __post_init__(self) -> None:
        for name in (
            "outcome_id",
            "source_observation_id",
            "logical_cycle_id",
            "provider_attempt_id",
        ):
            if not getattr(self, name).strip():
                raise CampaignEvidenceError(f"{name} is required")
        _sha256(self.semantic_sha256, "semantic_sha256")
        if not isinstance(self.terminal, bool):
            raise CampaignEvidenceError("terminal must be boolean")


@dataclass(frozen=True, slots=True)
class CampaignEvidence:
    campaign_id: str
    source_commit: str
    installed_artifact_sha256: str
    policy_sha256: str
    evidence_class: EvidenceClass
    intervals: tuple[CoverageInterval, ...]
    outcomes: tuple[OutcomeRecord, ...]
    claimed_eligible_seconds: int
    claimed_unique_terminal_outcomes: int
    replay_executions: int = 0
    schema_version: str = CAMPAIGN_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CAMPAIGN_EVIDENCE_SCHEMA_VERSION:
            raise CampaignEvidenceError("unsupported campaign evidence schema")
        if not self.campaign_id.strip():
            raise CampaignEvidenceError("campaign_id is required")
        _git_sha(self.source_commit, "source_commit")
        _sha256(self.installed_artifact_sha256, "installed_artifact_sha256")
        _sha256(self.policy_sha256, "policy_sha256")
        for name in (
            "claimed_eligible_seconds",
            "claimed_unique_terminal_outcomes",
            "replay_executions",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CampaignEvidenceError(f"{name} must be a non-negative integer")

    @property
    def evidence_sha256(self) -> str:
        return hashlib.sha256(_stable_json(self.to_dict()).encode("utf-8")).hexdigest()

    def to_dict(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "source_commit": self.source_commit,
            "installed_artifact_sha256": self.installed_artifact_sha256,
            "policy_sha256": self.policy_sha256,
            "evidence_class": self.evidence_class.value,
            "intervals": [
                {
                    "segment_id": item.segment_id,
                    "started_at": _utc(item.started_at),
                    "ended_at": _utc(item.ended_at),
                    "evidence_class": item.evidence_class.value,
                    "kind": item.kind.value,
                    "source_cursor": item.source_cursor,
                }
                for item in self.intervals
            ],
            "outcomes": [
                {
                    "outcome_id": item.outcome_id,
                    "semantic_sha256": item.semantic_sha256,
                    "source_observation_id": item.source_observation_id,
                    "logical_cycle_id": item.logical_cycle_id,
                    "provider_attempt_id": item.provider_attempt_id,
                    "terminal": item.terminal,
                }
                for item in self.outcomes
            ],
            "claimed_eligible_seconds": self.claimed_eligible_seconds,
            "claimed_unique_terminal_outcomes": self.claimed_unique_terminal_outcomes,
            "replay_executions": self.replay_executions,
        }


@dataclass(frozen=True, slots=True)
class CampaignQualification:
    campaign_id: str
    qualified: bool
    eligible_seconds: int
    longest_continuous_seconds: int
    calendar_span_seconds: int
    gap_seconds: int
    unique_terminal_outcomes: int
    duplicate_terminal_deliveries: int
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_sha256: str
    schema_version: str = CAMPAIGN_QUALIFICATION_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class ResidualRealSoakQualification:
    existing_readiness: RealShadowSoakReadiness
    residual: CampaignQualification
    qualified: bool
    live_allowed: bool
    blockers: tuple[str, ...]


def evaluate_campaign_evidence(
    evidence: CampaignEvidence,
    policy: CampaignPolicy,
) -> CampaignQualification:
    """Recompute coverage/count claims without trusting summary timestamps/counts."""

    blockers: list[str] = []
    warnings: list[str] = []

    if evidence.evidence_class is not EvidenceClass.REAL_SHADOW_READ_ONLY:
        blockers.append("REAL_SHADOW_LINEAGE_REQUIRED")

    real_intervals = [
        interval
        for interval in evidence.intervals
        if interval.evidence_class is EvidenceClass.REAL_SHADOW_READ_ONLY
        and interval.kind is IntervalKind.ELIGIBLE
    ]
    union = _merge_overlaps(real_intervals)
    eligible_seconds = sum(_seconds(start, end) for start, end in union)
    longest = _longest_continuous_window(union, policy.maximum_gap_seconds)

    if evidence.intervals:
        first = min(item.started_at for item in evidence.intervals)
        last = max(item.ended_at for item in evidence.intervals)
        calendar_span = _seconds(first, last)
    else:
        calendar_span = 0
    gap_seconds = max(0, calendar_span - eligible_seconds)

    unique_terminal, duplicate_terminal, conflicts = _outcome_counts(evidence.outcomes)
    blockers.extend(f"OUTCOME_ID_SEMANTIC_CONFLICT:{value}" for value in conflicts)

    if eligible_seconds < policy.minimum_eligible_seconds:
        blockers.append("ELIGIBLE_DURATION_BELOW_POLICY")
    if longest < policy.minimum_eligible_seconds:
        blockers.append("CONTINUOUS_WINDOW_BELOW_POLICY")
    if unique_terminal < policy.minimum_terminal_samples:
        blockers.append("TERMINAL_SAMPLES_BELOW_POLICY")
    if evidence.claimed_eligible_seconds != eligible_seconds:
        blockers.append("CLAIMED_DURATION_MISMATCH")
    if evidence.claimed_unique_terminal_outcomes != unique_terminal:
        blockers.append("CLAIMED_TERMINAL_COUNT_MISMATCH")
    if evidence.replay_executions:
        warnings.append(
            f"REPLAY_EXECUTIONS_EXCLUDED_FROM_REAL_DURATION:{evidence.replay_executions}"
        )
    if duplicate_terminal:
        warnings.append(f"DUPLICATE_TERMINAL_DELIVERIES:{duplicate_terminal}")

    deduped_blockers = tuple(dict.fromkeys(blockers))
    return CampaignQualification(
        campaign_id=evidence.campaign_id,
        qualified=not deduped_blockers,
        eligible_seconds=eligible_seconds,
        longest_continuous_seconds=longest,
        calendar_span_seconds=calendar_span,
        gap_seconds=gap_seconds,
        unique_terminal_outcomes=unique_terminal,
        duplicate_terminal_deliveries=duplicate_terminal,
        blockers=deduped_blockers,
        warnings=tuple(dict.fromkeys(warnings)),
        evidence_sha256=evidence.evidence_sha256,
    )


def evaluate_real_shadow_soak_residual(
    package: RealShadowSoakPackage,
    campaign_evidence: CampaignEvidence,
    campaign_policy: CampaignPolicy,
    thresholds: ShadowSoakThresholds | None = None,
) -> ResidualRealSoakQualification:
    """Compose residual checks with PR-079 without creating another live gate."""

    existing = evaluate_real_shadow_soak(package, thresholds)
    residual = evaluate_campaign_evidence(campaign_evidence, campaign_policy)
    blockers = list(existing.blockers)
    blockers.extend(f"MPR2607:{reason}" for reason in residual.blockers)

    if package.soak.run_id != campaign_evidence.campaign_id:
        blockers.append("MPR2607:CAMPAIGN_RUN_ID_MISMATCH")
    if package.soak.code_commit != campaign_evidence.source_commit.lower():
        blockers.append("MPR2607:SOURCE_COMMIT_MISMATCH")

    unique_blockers = tuple(dict.fromkeys(blockers))
    return ResidualRealSoakQualification(
        existing_readiness=existing,
        residual=residual,
        qualified=not unique_blockers,
        live_allowed=False,
        blockers=unique_blockers,
    )


def _merge_overlaps(
    intervals: Iterable[CoverageInterval],
) -> tuple[tuple[datetime, datetime], ...]:
    ordered = sorted(
        ((item.started_at, item.ended_at) for item in intervals),
        key=lambda item: item[0],
    )
    if not ordered:
        return ()
    merged: list[tuple[datetime, datetime]] = [ordered[0]]
    for start, end in ordered[1:]:
        prior_start, prior_end = merged[-1]
        if start <= prior_end:
            merged[-1] = (prior_start, max(prior_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _longest_continuous_window(
    union: Sequence[tuple[datetime, datetime]],
    maximum_gap_seconds: int,
) -> int:
    if not union:
        return 0
    window_start, window_end = union[0]
    longest = _seconds(window_start, window_end)
    for start, end in union[1:]:
        gap = _seconds(window_end, start)
        if gap <= maximum_gap_seconds:
            window_end = end
        else:
            longest = max(longest, _seconds(window_start, window_end))
            window_start, window_end = start, end
    return max(longest, _seconds(window_start, window_end))


def _outcome_counts(
    outcomes: Sequence[OutcomeRecord],
) -> tuple[int, int, tuple[str, ...]]:
    terminal_by_id: dict[str, str] = {}
    duplicate = 0
    conflicts: list[str] = []
    for outcome in outcomes:
        if not outcome.terminal:
            continue
        existing = terminal_by_id.get(outcome.outcome_id)
        if existing is None:
            terminal_by_id[outcome.outcome_id] = outcome.semantic_sha256
        elif existing == outcome.semantic_sha256:
            duplicate += 1
        else:
            conflicts.append(outcome.outcome_id)
    return len(terminal_by_id), duplicate, tuple(dict.fromkeys(conflicts))


def _seconds(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds()))


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CampaignEvidenceError(f"{field} must be timezone-aware")


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(value: str, field: str) -> None:
    lowered = value.lower()
    if len(lowered) != 64 or any(ch not in "0123456789abcdef" for ch in lowered):
        raise CampaignEvidenceError(f"{field} must be sha256")
    if lowered == "0" * 64:
        raise CampaignEvidenceError(f"{field} cannot be a placeholder")


def _git_sha(value: str, field: str) -> None:
    lowered = value.lower()
    if len(lowered) != 40 or any(ch not in "0123456789abcdef" for ch in lowered):
        raise CampaignEvidenceError(f"{field} must be a git SHA")
    if lowered == "0" * 40:
        raise CampaignEvidenceError(f"{field} cannot be a placeholder")


def _stable_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


__all__ = [
    "CAMPAIGN_EVIDENCE_SCHEMA_VERSION",
    "CAMPAIGN_QUALIFICATION_SCHEMA_VERSION",
    "CampaignEvidence",
    "CampaignEvidenceError",
    "CampaignPolicy",
    "CampaignQualification",
    "CoverageInterval",
    "EvidenceClass",
    "IntervalKind",
    "OutcomeRecord",
    "ResidualRealSoakQualification",
    "evaluate_campaign_evidence",
    "evaluate_real_shadow_soak_residual",
]
