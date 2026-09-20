"""AGG-09 OPS-02: telemetry, operator control and measured scaling.

The mutable operating state remains owned by MPR-2613.  This module only
aggregates metrics and delegates pause/resume/stop transitions to that authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import re
import sqlite3

from src.operations.mpr2613_guarded_operations import (
    OperatingState,
    StateTransitionDenied,
    transition_state,
)

SCHEMA_VERSION = "agg09.ops02.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class Agg09Ops02Error(ValueError):
    """Malformed operational evidence."""


def _sha(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise Agg09Ops02Error(f"{name} must be a lowercase sha256 digest")


def _nonnegative(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise Agg09Ops02Error(f"{name} must be a non-negative integer")


def _positive(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise Agg09Ops02Error(f"{name} must be a positive integer")


def _percentile(values: tuple[int, ...], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered) / 100))
    return ordered[rank - 1]


@dataclass(frozen=True, slots=True)
class TelemetryWindow:
    campaign_id: str
    latency_ns: tuple[int, ...]
    data_gap_count: int
    dropped_work_count: int
    quota_used: int
    quota_limit: int
    provider_error_count: int
    stalled_state_count: int
    unresolved_reconciliation_count: int
    useful_episode_count: int
    process_liveness_healthy: bool
    market_readiness_qualified: bool
    evidence_age_seconds: int

    def __post_init__(self) -> None:
        if not self.campaign_id.strip():
            raise Agg09Ops02Error("campaign_id is required")
        for value in self.latency_ns:
            _nonnegative(value, "latency_ns")
        for name in (
            "data_gap_count",
            "dropped_work_count",
            "quota_used",
            "quota_limit",
            "provider_error_count",
            "stalled_state_count",
            "unresolved_reconciliation_count",
            "useful_episode_count",
            "evidence_age_seconds",
        ):
            _nonnegative(getattr(self, name), name)
        if self.quota_used > self.quota_limit:
            raise Agg09Ops02Error("quota_used cannot exceed quota_limit")


@dataclass(frozen=True, slots=True)
class ProductionTelemetry:
    campaign_id: str
    sample_count: int
    p50_latency_ns: int
    p95_latency_ns: int
    p99_latency_ns: int
    data_gap_count: int
    dropped_work_count: int
    quota_used: int
    quota_limit: int
    provider_error_count: int
    stalled_state_count: int
    unresolved_reconciliation_count: int
    useful_episode_count: int
    process_liveness_healthy: bool
    market_readiness_qualified: bool
    evidence_age_seconds: int
    reason_codes: tuple[str, ...]


def build_production_telemetry(window: TelemetryWindow) -> ProductionTelemetry:
    reasons: list[str] = []
    if not window.latency_ns:
        reasons.append("AGG09_TELEMETRY_LATENCY_EMPTY")
    if window.data_gap_count:
        reasons.append("AGG09_TELEMETRY_DATA_GAPS")
    if window.dropped_work_count:
        reasons.append("AGG09_TELEMETRY_DROPPED_WORK")
    if window.provider_error_count:
        reasons.append("AGG09_TELEMETRY_PROVIDER_ERRORS")
    if window.stalled_state_count:
        reasons.append("AGG09_TELEMETRY_STALLED_STATE")
    if window.unresolved_reconciliation_count:
        reasons.append("AGG09_TELEMETRY_UNRESOLVED_RECONCILIATION")
    if not window.market_readiness_qualified:
        reasons.append("AGG09_MARKET_READINESS_NOT_QUALIFIED")
    if not window.process_liveness_healthy:
        reasons.append("AGG09_PROCESS_LIVENESS_UNHEALTHY")
    return ProductionTelemetry(
        campaign_id=window.campaign_id,
        sample_count=len(window.latency_ns),
        p50_latency_ns=_percentile(window.latency_ns, 50),
        p95_latency_ns=_percentile(window.latency_ns, 95),
        p99_latency_ns=_percentile(window.latency_ns, 99),
        data_gap_count=window.data_gap_count,
        dropped_work_count=window.dropped_work_count,
        quota_used=window.quota_used,
        quota_limit=window.quota_limit,
        provider_error_count=window.provider_error_count,
        stalled_state_count=window.stalled_state_count,
        unresolved_reconciliation_count=window.unresolved_reconciliation_count,
        useful_episode_count=window.useful_episode_count,
        process_liveness_healthy=window.process_liveness_healthy,
        market_readiness_qualified=window.market_readiness_qualified,
        evidence_age_seconds=window.evidence_age_seconds,
        reason_codes=tuple(sorted(set(reasons))),
    )


class OperatorRole(StrEnum):
    READ_ONLY = "read-only"
    RISK_OPERATOR = "risk-operator"


class OperatorAction(StrEnum):
    INSPECT = "inspect"
    PAUSE = "pause"
    RESUME_SHADOW = "resume-shadow"
    STOP = "stop"


@dataclass(frozen=True, slots=True)
class OperatorAuthorization:
    operator_id: str
    role: OperatorRole
    authorization_hash: str

    def __post_init__(self) -> None:
        if not self.operator_id.strip():
            raise Agg09Ops02Error("operator_id is required")
        _sha(self.authorization_hash, "authorization_hash")


@dataclass(frozen=True, slots=True)
class OperatorCommandReceipt:
    scope_key: str
    action: OperatorAction
    from_state: OperatingState
    to_state: OperatingState
    writer_generation: int
    audit_owner: str
    mutated: bool
    live_enabled: bool = False


def execute_operator_command(
    db: sqlite3.Connection,
    *,
    scope_key: str,
    action: OperatorAction,
    authorization: OperatorAuthorization,
    writer_generation: int,
    current_utc: str,
) -> OperatorCommandReceipt:
    """Execute only scope-limited MPR-2613 transitions.

    Resume is intentionally limited to SHADOW_ONLY. AGG-09 does not provide a
    command that activates live execution.
    """

    _positive(writer_generation, "writer_generation")
    row = db.execute(
        "SELECT state,writer_generation FROM mpr2613_operating_state WHERE scope_key=?",
        (scope_key,),
    ).fetchone()
    if row is None:
        raise StateTransitionDenied("AGG09_SCOPE_NOT_INITIALIZED")
    current = OperatingState(int(row[0]))
    if int(row[1]) != writer_generation:
        raise StateTransitionDenied("AGG09_STALE_WRITER_GENERATION")

    if action is OperatorAction.INSPECT:
        return OperatorCommandReceipt(
            scope_key=scope_key,
            action=action,
            from_state=current,
            to_state=current,
            writer_generation=writer_generation,
            audit_owner="mpr2613_state_events",
            mutated=False,
        )
    if authorization.role is not OperatorRole.RISK_OPERATOR:
        raise StateTransitionDenied("AGG09_OPERATOR_ROLE_DENIED")

    target = {
        OperatorAction.PAUSE: OperatingState.DORMANT,
        OperatorAction.RESUME_SHADOW: OperatingState.SHADOW_ONLY,
        OperatorAction.STOP: OperatingState.LATCHED,
    }[action]
    upward_hash = authorization.authorization_hash if target > current else None
    transition_state(
        db,
        scope_key=scope_key,
        target_state=target,
        reason=f"agg09:{action.value}:{authorization.operator_id}",
        writer_generation=writer_generation,
        current_utc=current_utc,
        automated=False,
        upward_authorization_hash=upward_hash,
    )
    return OperatorCommandReceipt(
        scope_key=scope_key,
        action=action,
        from_state=current,
        to_state=target,
        writer_generation=writer_generation,
        audit_owner="mpr2613_state_events",
        mutated=target != current,
        live_enabled=False,
    )


@dataclass(frozen=True, slots=True)
class PerformanceEvidence:
    workload_hash: str
    baseline_semantics_hash: str
    candidate_semantics_hash: str
    baseline_p95_ns: int
    candidate_p95_ns: int
    baseline_p99_ns: int
    candidate_p99_ns: int
    baseline_cost_units: int
    candidate_cost_units: int

    def __post_init__(self) -> None:
        for name in (
            "workload_hash",
            "baseline_semantics_hash",
            "candidate_semantics_hash",
        ):
            _sha(getattr(self, name), name)
        for name in (
            "baseline_p95_ns",
            "candidate_p95_ns",
            "baseline_p99_ns",
            "candidate_p99_ns",
            "baseline_cost_units",
            "candidate_cost_units",
        ):
            _nonnegative(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class PerformancePatchDecision:
    accepted: bool
    reason_codes: tuple[str, ...]
    p95_delta_ns: int
    p99_delta_ns: int
    cost_delta_units: int


def evaluate_performance_patch(
    evidence: PerformanceEvidence,
) -> PerformancePatchDecision:
    reasons: list[str] = []
    if evidence.baseline_semantics_hash != evidence.candidate_semantics_hash:
        reasons.append("AGG09_PERFORMANCE_SEMANTICS_CHANGED")
    if evidence.candidate_p95_ns > evidence.baseline_p95_ns:
        reasons.append("AGG09_PERFORMANCE_P95_REGRESSED")
    if evidence.candidate_p99_ns > evidence.baseline_p99_ns:
        reasons.append("AGG09_PERFORMANCE_P99_REGRESSED")
    if (
        evidence.candidate_p95_ns == evidence.baseline_p95_ns
        and evidence.candidate_p99_ns == evidence.baseline_p99_ns
        and evidence.candidate_cost_units >= evidence.baseline_cost_units
    ):
        reasons.append("AGG09_PERFORMANCE_NO_MEASURED_UPLIFT")
    return PerformancePatchDecision(
        accepted=not reasons,
        reason_codes=tuple(sorted(set(reasons))),
        p95_delta_ns=evidence.candidate_p95_ns - evidence.baseline_p95_ns,
        p99_delta_ns=evidence.candidate_p99_ns - evidence.baseline_p99_ns,
        cost_delta_units=evidence.candidate_cost_units - evidence.baseline_cost_units,
    )


@dataclass(frozen=True, slots=True)
class DataScaleEvidence:
    before_replay_hash: str
    after_replay_hash: str
    identity_registry_hash_before: str
    identity_registry_hash_after: str
    cursor_semantics_hash_before: str
    cursor_semantics_hash_after: str
    quota_authority_hash_before: str
    quota_authority_hash_after: str
    economic_authority_hash_before: str
    economic_authority_hash_after: str
    within_budget: bool
    duplicate_episode_count: int

    def __post_init__(self) -> None:
        for name in (
            "before_replay_hash",
            "after_replay_hash",
            "identity_registry_hash_before",
            "identity_registry_hash_after",
            "cursor_semantics_hash_before",
            "cursor_semantics_hash_after",
            "quota_authority_hash_before",
            "quota_authority_hash_after",
            "economic_authority_hash_before",
            "economic_authority_hash_after",
        ):
            _sha(getattr(self, name), name)
        _nonnegative(self.duplicate_episode_count, "duplicate_episode_count")


@dataclass(frozen=True, slots=True)
class DataScalePlan:
    accepted: bool
    reason_codes: tuple[str, ...]
    authoritative_economic_owner_preserved: bool


def evaluate_data_scale(evidence: DataScaleEvidence) -> DataScalePlan:
    reasons: list[str] = []
    comparisons = (
        ("AGG09_SCALE_REPLAY_DRIFT", evidence.before_replay_hash, evidence.after_replay_hash),
        (
            "AGG09_SCALE_IDENTITY_DRIFT",
            evidence.identity_registry_hash_before,
            evidence.identity_registry_hash_after,
        ),
        (
            "AGG09_SCALE_CURSOR_DRIFT",
            evidence.cursor_semantics_hash_before,
            evidence.cursor_semantics_hash_after,
        ),
        (
            "AGG09_SCALE_QUOTA_AUTHORITY_DRIFT",
            evidence.quota_authority_hash_before,
            evidence.quota_authority_hash_after,
        ),
        (
            "AGG09_SCALE_ECONOMIC_AUTHORITY_DRIFT",
            evidence.economic_authority_hash_before,
            evidence.economic_authority_hash_after,
        ),
    )
    for reason, before, after in comparisons:
        if before != after:
            reasons.append(reason)
    if not evidence.within_budget:
        reasons.append("AGG09_SCALE_BUDGET_EXCEEDED")
    if evidence.duplicate_episode_count:
        reasons.append("AGG09_SCALE_DUPLICATE_EPISODES")
    return DataScalePlan(
        accepted=not reasons,
        reason_codes=tuple(sorted(set(reasons))),
        authoritative_economic_owner_preserved=(
            evidence.economic_authority_hash_before
            == evidence.economic_authority_hash_after
        ),
    )


__all__ = [
    "Agg09Ops02Error",
    "DataScaleEvidence",
    "DataScalePlan",
    "OperatorAction",
    "OperatorAuthorization",
    "OperatorCommandReceipt",
    "OperatorRole",
    "PerformanceEvidence",
    "PerformancePatchDecision",
    "ProductionTelemetry",
    "SCHEMA_VERSION",
    "TelemetryWindow",
    "build_production_telemetry",
    "evaluate_data_scale",
    "evaluate_performance_patch",
    "execute_operator_command",
]
