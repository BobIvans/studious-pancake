"""PR-144 shadow soak evidence gate.

This module is an additive, side-effect-free contract for proving that a
shadow/paper candidate stream has survived a bounded soak period before any
live-canary discussion. It does not call providers, RPC, Jito, signers,
senders, wallets, or runtime execution paths.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum


class SoakDecision(StrEnum):
    REVIEW_READY = "review_ready"
    BLOCKED = "blocked"


class SoakReason(StrEnum):
    TOO_SHORT = "too_short"
    MISSING_STREAM = "missing_stream"
    PLACEHOLDER_HASH = "placeholder_hash"
    UNREVIEWED_EVIDENCE = "unreviewed_evidence"
    LIVE_ENABLED = "live_enabled"
    SENDER_TOUCHED = "sender_touched"
    SUBMISSION_ATTEMPTED = "submission_attempted"
    SIGNATURE_OBSERVED = "signature_observed"
    UNRECONCILED_TERMINAL = "unreconciled_terminal"
    GAP_DETECTED = "gap_detected"
    DUPLICATE_IDENTITY = "duplicate_identity"
    EVENT_VOLUME_TOO_LOW = "event_volume_too_low"
    ERROR_BUDGET_EXCEEDED = "error_budget_exceeded"


REQUIRED_SHADOW_STREAMS: tuple[str, ...] = (
    "candidate_identity",
    "exact_simulation",
    "cpi_call_graph",
    "observability_events",
    "data_lineage",
    "finalized_settlement_simulated",
    "readiness_report",
)

_PLACEHOLDER_HASHES = frozenset(
    {
        "",
        "0",
        "0" * 64,
        "1" * 64,
        "deadbeef",
        "placeholder",
        "todo",
        "pending",
        "not_applicable",
    }
)


@dataclass(frozen=True, slots=True)
class ShadowSoakWindow:
    start_unix_ms: int
    end_unix_ms: int

    def __post_init__(self) -> None:
        if self.start_unix_ms < 0:
            raise ValueError("start_unix_ms must be non-negative")
        if self.end_unix_ms < self.start_unix_ms:
            raise ValueError("end_unix_ms must be >= start_unix_ms")

    @property
    def duration_hours(self) -> float:
        return (self.end_unix_ms - self.start_unix_ms) / 3_600_000


@dataclass(frozen=True, slots=True)
class ShadowSoakEvidence:
    run_id: str
    window: ShadowSoakWindow
    streams: tuple[str, ...]
    evidence_hash: str
    reviewed_by_human: bool
    total_events: int
    reconciled_terminal_events: int
    live_enabled: bool = False
    sender_invocations: int = 0
    submission_attempts: int = 0
    observed_transaction_signatures: int = 0
    gap_count: int = 0
    duplicate_identity_count: int = 0
    error_count: int = 0
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must be non-empty")
        if any(not stream for stream in self.streams):
            raise ValueError("stream names must be non-empty")
        counters = (
            self.total_events,
            self.reconciled_terminal_events,
            self.sender_invocations,
            self.submission_attempts,
            self.observed_transaction_signatures,
            self.gap_count,
            self.duplicate_identity_count,
            self.error_count,
        )
        if any(value < 0 for value in counters):
            raise ValueError("soak counters must be non-negative")
        if self.reconciled_terminal_events > self.total_events:
            raise ValueError("reconciled_terminal_events cannot exceed total_events")


@dataclass(frozen=True, slots=True)
class ShadowSoakPolicy:
    min_duration_hours: int = 72
    min_total_events: int = 1
    max_error_rate_bps: int = 50
    required_streams: tuple[str, ...] = field(default_factory=lambda: REQUIRED_SHADOW_STREAMS)
    allow_placeholder_hashes: bool = False

    def __post_init__(self) -> None:
        if self.min_duration_hours <= 0:
            raise ValueError("min_duration_hours must be positive")
        if self.min_total_events < 0:
            raise ValueError("min_total_events must be non-negative")
        if self.max_error_rate_bps < 0:
            raise ValueError("max_error_rate_bps must be non-negative")


@dataclass(frozen=True, slots=True)
class ShadowSoakFailure:
    reason: SoakReason
    detail: str
    stream: str | None = None


@dataclass(frozen=True, slots=True)
class ShadowSoakReport:
    decision: SoakDecision
    failures: tuple[ShadowSoakFailure, ...]
    report_hash: str
    duration_hours: float
    observed_streams: tuple[str, ...]
    required_streams: tuple[str, ...]
    live_canary_allowed: bool = False

    @property
    def review_ready(self) -> bool:
        return self.decision is SoakDecision.REVIEW_READY

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "review_ready": self.review_ready,
            "live_canary_allowed": self.live_canary_allowed,
            "report_hash": self.report_hash,
            "duration_hours": self.duration_hours,
            "observed_streams": list(self.observed_streams),
            "required_streams": list(self.required_streams),
            "failures": [
                {
                    "reason": failure.reason.value,
                    "detail": failure.detail,
                    "stream": failure.stream,
                }
                for failure in self.failures
            ],
        }


def evaluate_shadow_soak(
    evidence: ShadowSoakEvidence,
    policy: ShadowSoakPolicy | None = None,
) -> ShadowSoakReport:
    """Evaluate whether shadow soak evidence is ready for human review."""

    resolved_policy = policy or ShadowSoakPolicy()
    failures: list[ShadowSoakFailure] = []

    if evidence.window.duration_hours < resolved_policy.min_duration_hours:
        failures.append(
            ShadowSoakFailure(
                SoakReason.TOO_SHORT,
                "shadow soak duration is below required minimum",
            )
        )

    observed_streams = tuple(sorted(set(evidence.streams)))
    observed_set = set(observed_streams)
    for stream in resolved_policy.required_streams:
        if stream not in observed_set:
            failures.append(
                ShadowSoakFailure(
                    SoakReason.MISSING_STREAM,
                    "required shadow evidence stream is missing",
                    stream=stream,
                )
            )

    if evidence.total_events < resolved_policy.min_total_events:
        failures.append(
            ShadowSoakFailure(
                SoakReason.EVENT_VOLUME_TOO_LOW,
                "shadow soak did not record enough events",
            )
        )
    if evidence.reconciled_terminal_events < evidence.total_events:
        failures.append(
            ShadowSoakFailure(
                SoakReason.UNRECONCILED_TERMINAL,
                "not every terminal shadow event has reconciliation evidence",
            )
        )
    if not evidence.reviewed_by_human:
        failures.append(
            ShadowSoakFailure(
                SoakReason.UNREVIEWED_EVIDENCE,
                "human review is required before promotion decisions",
            )
        )
    if not resolved_policy.allow_placeholder_hashes and _looks_placeholder_hash(
        evidence.evidence_hash
    ):
        failures.append(
            ShadowSoakFailure(
                SoakReason.PLACEHOLDER_HASH,
                "evidence hash is missing or placeholder-shaped",
            )
        )
    if evidence.live_enabled:
        failures.append(
            ShadowSoakFailure(
                SoakReason.LIVE_ENABLED,
                "shadow soak evidence must not enable live behavior",
            )
        )
    if evidence.sender_invocations:
        failures.append(
            ShadowSoakFailure(
                SoakReason.SENDER_TOUCHED,
                "shadow soak must not instantiate or invoke senders",
            )
        )
    if evidence.submission_attempts:
        failures.append(
            ShadowSoakFailure(
                SoakReason.SUBMISSION_ATTEMPTED,
                "shadow soak must not submit transactions",
            )
        )
    if evidence.observed_transaction_signatures:
        failures.append(
            ShadowSoakFailure(
                SoakReason.SIGNATURE_OBSERVED,
                "shadow soak must not produce on-chain transaction signatures",
            )
        )
    if evidence.gap_count:
        failures.append(
            ShadowSoakFailure(
                SoakReason.GAP_DETECTED,
                "shadow soak evidence contains data gaps",
            )
        )
    if evidence.duplicate_identity_count:
        failures.append(
            ShadowSoakFailure(
                SoakReason.DUPLICATE_IDENTITY,
                "shadow soak evidence contains duplicate logical identities",
            )
        )
    if _error_rate_bps(evidence) > resolved_policy.max_error_rate_bps:
        failures.append(
            ShadowSoakFailure(
                SoakReason.ERROR_BUDGET_EXCEEDED,
                "shadow soak error rate exceeds policy budget",
            )
        )

    decision = SoakDecision.REVIEW_READY if not failures else SoakDecision.BLOCKED
    return ShadowSoakReport(
        decision=decision,
        failures=tuple(failures),
        report_hash=_report_hash(evidence, resolved_policy),
        duration_hours=evidence.window.duration_hours,
        observed_streams=observed_streams,
        required_streams=resolved_policy.required_streams,
        live_canary_allowed=False,
    )


def release_gate_payload(report: ShadowSoakReport) -> dict[str, object]:
    """Produce a conservative release-gate payload."""

    return {
        "shadow_soak_review_ready": report.review_ready,
        "live_canary_allowed": False,
        "decision": report.decision.value,
        "report_hash": report.report_hash,
        "blockers": [failure.reason.value for failure in report.failures],
    }


def _error_rate_bps(evidence: ShadowSoakEvidence) -> int:
    if evidence.total_events == 0:
        return 0 if evidence.error_count == 0 else 10_000
    return (evidence.error_count * 10_000) // evidence.total_events


def _looks_placeholder_hash(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in _PLACEHOLDER_HASHES:
        return True
    if len(normalized) < 32:
        return True
    try:
        int(normalized, 16)
    except ValueError:
        return False
    return len(set(normalized)) == 1


def _report_hash(evidence: ShadowSoakEvidence, policy: ShadowSoakPolicy) -> str:
    payload = {
        "run_id": evidence.run_id,
        "window": {
            "start_unix_ms": evidence.window.start_unix_ms,
            "end_unix_ms": evidence.window.end_unix_ms,
        },
        "streams": sorted(evidence.streams),
        "evidence_hash": evidence.evidence_hash,
        "reviewed_by_human": evidence.reviewed_by_human,
        "total_events": evidence.total_events,
        "reconciled_terminal_events": evidence.reconciled_terminal_events,
        "live_enabled": evidence.live_enabled,
        "sender_invocations": evidence.sender_invocations,
        "submission_attempts": evidence.submission_attempts,
        "observed_transaction_signatures": evidence.observed_transaction_signatures,
        "gap_count": evidence.gap_count,
        "duplicate_identity_count": evidence.duplicate_identity_count,
        "error_count": evidence.error_count,
        "notes": list(evidence.notes),
        "policy": {
            "min_duration_hours": policy.min_duration_hours,
            "min_total_events": policy.min_total_events,
            "max_error_rate_bps": policy.max_error_rate_bps,
            "required_streams": list(policy.required_streams),
            "allow_placeholder_hashes": policy.allow_placeholder_hashes,
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "REQUIRED_SHADOW_STREAMS",
    "ShadowSoakEvidence",
    "ShadowSoakFailure",
    "ShadowSoakPolicy",
    "ShadowSoakReport",
    "ShadowSoakWindow",
    "SoakDecision",
    "SoakReason",
    "evaluate_shadow_soak",
    "release_gate_payload",
]
