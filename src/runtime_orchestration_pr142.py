"""PR-142 structured runtime orchestration and bounded resource lifecycle gate.

This module is intentionally offline and side-effect free.  It does not start
the active paper runner, open sockets, call providers, write lifecycle state, or
enable live trading.  It models the evidence a later RuntimeSupervisor
integration must provide before the repository can claim that the long-running
paper/shadow runtime is continuous, bounded, cancellation-safe and recoverable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Mapping, Sequence


PR142_SCHEMA_VERSION = "pr142.structured-runtime-orchestration.v1"
PR142_RESULT_SCHEMA_VERSION = "pr142.structured-runtime-readiness.v1"
PR142_READY_STATE = "structured-runtime-review-ready"
PR142_BLOCKED_STATE = "blocked"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_STAGES = (
    "discovery",
    "exact_quote",
    "capital",
    "planning",
    "compile",
    "simulation",
    "reconciliation",
    "journal_export",
)
_REQUIRED_SUPERVISOR_COMPONENTS = (
    "discovery_loop",
    "candidate_processor",
    "provider_clients",
    "lifecycle_writer",
    "observability_exporter",
    "health_readiness_server",
)
_REQUIRED_SHUTDOWN_STEPS = (
    "stop_new_discovery",
    "stop_new_reservations",
    "preserve_ambiguous_submission",
    "drain_journal_outbox",
    "checkpoint",
    "close_clients",
    "readiness_false_before_exit",
)
_REQUIRED_FAULTS = (
    "stage_hang",
    "child_task_crash",
    "cancellation_during_db_commit",
    "cancellation_during_provider_request",
    "queue_full",
    "tracker_expiration",
    "sigterm_during_stage",
    "second_runtime_process",
    "db_busy_locked",
    "event_loop_lag",
    "provider_swallowed_cancelled_error",
)


class PR142RuntimeError(ValueError):
    """Raised for malformed PR-142 evidence."""


class ComponentCriticality(str, Enum):
    """Runtime component criticality for readiness propagation."""

    CRITICAL = "critical"
    SUPPORTING = "supporting"


class CandidateRejectionPolicy(str, Enum):
    """How the runtime reacts to candidate-local rejections."""

    CONTINUE = "continue_after_candidate_local_rejection"
    STOP_ON_DEPENDENCY_FAILURE = "stop_on_dependency_wide_failure"


@dataclass(frozen=True, slots=True)
class StageBudget:
    """Bounded execution contract for one paper/shadow stage."""

    stage_name: str
    timeout_ms: int
    cancellation_budget_ms: int
    max_attempts: int
    max_external_calls: int
    lease_refresh_ms: int | None
    terminal_reason: str

    def __post_init__(self) -> None:
        if self.stage_name not in _REQUIRED_STAGES:
            raise PR142RuntimeError(f"unknown stage: {self.stage_name}")
        _require_positive(self.timeout_ms, "timeout_ms")
        _require_non_negative(self.cancellation_budget_ms, "cancellation_budget_ms")
        _require_positive(self.max_attempts, "max_attempts")
        _require_non_negative(self.max_external_calls, "max_external_calls")
        if self.lease_refresh_ms is not None:
            _require_positive(self.lease_refresh_ms, "lease_refresh_ms")
            if self.lease_refresh_ms >= self.timeout_ms:
                raise PR142RuntimeError("lease_refresh_ms must be below timeout_ms")
        _require_nonempty(self.terminal_reason, "terminal_reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "stage_name": self.stage_name,
            "timeout_ms": self.timeout_ms,
            "cancellation_budget_ms": self.cancellation_budget_ms,
            "max_attempts": self.max_attempts,
            "max_external_calls": self.max_external_calls,
            "lease_refresh_ms": self.lease_refresh_ms,
            "terminal_reason": self.terminal_reason,
        }


@dataclass(frozen=True, slots=True)
class ComponentContract:
    """Ownership/readiness contract for one supervised runtime component."""

    component_name: str
    criticality: ComponentCriticality
    owned_by_supervisor: bool
    failure_changes_readiness: bool
    exception_history_limit: int
    restart_limit: int
    cancellation_propagates: bool

    def __post_init__(self) -> None:
        if self.component_name not in _REQUIRED_SUPERVISOR_COMPONENTS:
            raise PR142RuntimeError(f"unknown component: {self.component_name}")
        _require_non_negative(self.exception_history_limit, "exception_history_limit")
        _require_non_negative(self.restart_limit, "restart_limit")
        if (
            self.criticality is ComponentCriticality.CRITICAL
            and not self.failure_changes_readiness
        ):
            raise PR142RuntimeError(
                f"critical component does not affect readiness: {self.component_name}"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "component_name": self.component_name,
            "criticality": self.criticality.value,
            "owned_by_supervisor": self.owned_by_supervisor,
            "failure_changes_readiness": self.failure_changes_readiness,
            "exception_history_limit": self.exception_history_limit,
            "restart_limit": self.restart_limit,
            "cancellation_propagates": self.cancellation_propagates,
        }


@dataclass(frozen=True, slots=True)
class ResourceBounds:
    """Finite resource limits for a long-running runtime process."""

    active_tasks_max: int
    provider_requests_max: int
    candidate_queue_max: int
    evidence_blob_bytes_max: int
    exception_history_max: int
    log_records_max: int
    cache_entries_max: int
    pending_outbox_max: int
    db_connections_max: int
    file_descriptors_max: int

    def __post_init__(self) -> None:
        for name, value in self.to_dict().items():
            _require_positive(value, name)

    def to_dict(self) -> dict[str, int]:
        return {
            "active_tasks_max": self.active_tasks_max,
            "provider_requests_max": self.provider_requests_max,
            "candidate_queue_max": self.candidate_queue_max,
            "evidence_blob_bytes_max": self.evidence_blob_bytes_max,
            "exception_history_max": self.exception_history_max,
            "log_records_max": self.log_records_max,
            "cache_entries_max": self.cache_entries_max,
            "pending_outbox_max": self.pending_outbox_max,
            "db_connections_max": self.db_connections_max,
            "file_descriptors_max": self.file_descriptors_max,
        }


@dataclass(frozen=True, slots=True)
class QueueTrackerEvidence:
    """Bounded queue/tracker cleanup requirements."""

    queue_capacity: int
    pending_ttl_ms: int
    terminal_ttl_ms: int
    terminal_retention_max: int
    expired_items_release_pending: bool
    persistent_dedup_enabled: bool
    drop_reason_durable: bool
    backpressure_metrics: bool

    def __post_init__(self) -> None:
        _require_positive(self.queue_capacity, "queue_capacity")
        _require_positive(self.pending_ttl_ms, "pending_ttl_ms")
        _require_positive(self.terminal_ttl_ms, "terminal_ttl_ms")
        _require_positive(self.terminal_retention_max, "terminal_retention_max")

    def to_dict(self) -> dict[str, object]:
        return {
            "queue_capacity": self.queue_capacity,
            "pending_ttl_ms": self.pending_ttl_ms,
            "terminal_ttl_ms": self.terminal_ttl_ms,
            "terminal_retention_max": self.terminal_retention_max,
            "expired_items_release_pending": self.expired_items_release_pending,
            "persistent_dedup_enabled": self.persistent_dedup_enabled,
            "drop_reason_durable": self.drop_reason_durable,
            "backpressure_metrics": self.backpressure_metrics,
        }


@dataclass(frozen=True, slots=True)
class DatabaseActorEvidence:
    """SQLite/process leadership contract for PR-142."""

    dedicated_writer_actor: bool
    bounded_command_queue: bool
    command_queue_capacity: int
    no_blocking_db_in_event_loop: bool
    explicit_reader_connections: bool
    process_lock_or_leader_lease: bool
    rejects_second_writer_process: bool
    topology_in_readiness: bool
    evidence_hash: str

    def __post_init__(self) -> None:
        _require_positive(self.command_queue_capacity, "command_queue_capacity")
        _require_sha256(self.evidence_hash, "evidence_hash")

    def to_dict(self) -> dict[str, object]:
        return {
            "dedicated_writer_actor": self.dedicated_writer_actor,
            "bounded_command_queue": self.bounded_command_queue,
            "command_queue_capacity": self.command_queue_capacity,
            "no_blocking_db_in_event_loop": self.no_blocking_db_in_event_loop,
            "explicit_reader_connections": self.explicit_reader_connections,
            "process_lock_or_leader_lease": self.process_lock_or_leader_lease,
            "rejects_second_writer_process": self.rejects_second_writer_process,
            "topology_in_readiness": self.topology_in_readiness,
            "evidence_hash": self.evidence_hash,
        }


@dataclass(frozen=True, slots=True)
class ShutdownProtocolEvidence:
    """Ordered shutdown/drain evidence."""

    implemented_steps: tuple[str, ...]
    drain_timeout_ms: int
    checkpoint_hash: str
    cancellation_preserves_ambiguous_state: bool
    no_orphan_tasks_proven: bool
    cancelled_error_propagates: bool

    def __post_init__(self) -> None:
        _require_positive(self.drain_timeout_ms, "drain_timeout_ms")
        _require_sha256(self.checkpoint_hash, "checkpoint_hash")
        _require_unique(self.implemented_steps, "implemented_steps")
        unknown = set(self.implemented_steps) - set(_REQUIRED_SHUTDOWN_STEPS)
        if unknown:
            raise PR142RuntimeError(f"unknown shutdown steps: {sorted(unknown)}")

    def to_dict(self) -> dict[str, object]:
        return {
            "implemented_steps": list(self.implemented_steps),
            "drain_timeout_ms": self.drain_timeout_ms,
            "checkpoint_hash": self.checkpoint_hash,
            "cancellation_preserves_ambiguous_state": (
                self.cancellation_preserves_ambiguous_state
            ),
            "no_orphan_tasks_proven": self.no_orphan_tasks_proven,
            "cancelled_error_propagates": self.cancelled_error_propagates,
        }


@dataclass(frozen=True, slots=True)
class FaultInjectionEvidence:
    """Fault/chaos evidence that the structured runtime actually detects leaks."""

    covered_faults: tuple[str, ...]
    no_task_leak: bool
    no_queue_leak: bool
    no_file_descriptor_leak: bool
    readiness_changes_on_critical_task_death: bool
    evidence_hash: str

    def __post_init__(self) -> None:
        _require_unique(self.covered_faults, "covered_faults")
        unknown = set(self.covered_faults) - set(_REQUIRED_FAULTS)
        if unknown:
            raise PR142RuntimeError(f"unknown fault injection case: {sorted(unknown)}")
        _require_sha256(self.evidence_hash, "evidence_hash")

    def to_dict(self) -> dict[str, object]:
        return {
            "covered_faults": list(self.covered_faults),
            "no_task_leak": self.no_task_leak,
            "no_queue_leak": self.no_queue_leak,
            "no_file_descriptor_leak": self.no_file_descriptor_leak,
            "readiness_changes_on_critical_task_death": (
                self.readiness_changes_on_critical_task_death
            ),
            "evidence_hash": self.evidence_hash,
        }


@dataclass(frozen=True, slots=True)
class RuntimeOrchestrationEvidence:
    """Complete PR-142 runtime orchestration evidence envelope."""

    stage_budgets: tuple[StageBudget, ...]
    component_contracts: tuple[ComponentContract, ...]
    resource_bounds: ResourceBounds
    queue_tracker: QueueTrackerEvidence
    database_actor: DatabaseActorEvidence
    shutdown_protocol: ShutdownProtocolEvidence
    fault_injection: FaultInjectionEvidence
    continuous_run_until_stopped: bool
    structured_concurrency: bool
    candidate_rejection_policy: CandidateRejectionPolicy
    stop_on_first_blocked_candidate_contract_enforced: bool
    policy_snapshot_hash: str
    implementation_evidence_hash: str
    unresolved_blockers: tuple[str, ...] = field(default_factory=tuple)
    schema_version: str = PR142_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR142_SCHEMA_VERSION:
            raise PR142RuntimeError(f"unsupported schema: {self.schema_version}")
        _require_unique([stage.stage_name for stage in self.stage_budgets], "stages")
        _require_unique(
            [component.component_name for component in self.component_contracts],
            "components",
        )
        _require_sha256(self.policy_snapshot_hash, "policy_snapshot_hash")
        _require_sha256(self.implementation_evidence_hash, "implementation_evidence_hash")
        for blocker in self.unresolved_blockers:
            _require_nonempty(blocker, "unresolved_blocker")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stage_budgets": [stage.to_dict() for stage in self.stage_budgets],
            "component_contracts": [
                component.to_dict() for component in self.component_contracts
            ],
            "resource_bounds": self.resource_bounds.to_dict(),
            "queue_tracker": self.queue_tracker.to_dict(),
            "database_actor": self.database_actor.to_dict(),
            "shutdown_protocol": self.shutdown_protocol.to_dict(),
            "fault_injection": self.fault_injection.to_dict(),
            "continuous_run_until_stopped": self.continuous_run_until_stopped,
            "structured_concurrency": self.structured_concurrency,
            "candidate_rejection_policy": self.candidate_rejection_policy.value,
            "stop_on_first_blocked_candidate_contract_enforced": (
                self.stop_on_first_blocked_candidate_contract_enforced
            ),
            "policy_snapshot_hash": self.policy_snapshot_hash,
            "implementation_evidence_hash": self.implementation_evidence_hash,
            "unresolved_blockers": list(self.unresolved_blockers),
        }


@dataclass(frozen=True, slots=True)
class RuntimeOrchestrationDecision:
    """PR-142 fail-closed readiness result."""

    schema_version: str
    state: str
    review_ready: bool
    paper_runtime_claim_allowed: bool
    live_claim_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    evidence_hash: str
    metrics: Mapping[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "review_ready": self.review_ready,
            "paper_runtime_claim_allowed": self.paper_runtime_claim_allowed,
            "live_claim_allowed": self.live_claim_allowed,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "evidence_hash": self.evidence_hash,
            "metrics": dict(self.metrics),
        }


def evaluate_pr142_runtime_orchestration(
    evidence: RuntimeOrchestrationEvidence,
) -> RuntimeOrchestrationDecision:
    """Evaluate whether PR-142 evidence is review-ready.

    Even when review-ready, this slice never authorizes paper/live execution.
    It only proves that the runtime orchestration contract has complete evidence.
    """

    blockers: list[str] = []
    warnings: list[str] = []

    stage_names = {stage.stage_name for stage in evidence.stage_budgets}
    for required_stage in _REQUIRED_STAGES:
        if required_stage not in stage_names:
            blockers.append(f"MISSING_STAGE_BUDGET:{required_stage}")

    component_names = {
        component.component_name for component in evidence.component_contracts
    }
    for required_component in _REQUIRED_SUPERVISOR_COMPONENTS:
        if required_component not in component_names:
            blockers.append(f"MISSING_SUPERVISED_COMPONENT:{required_component}")

    if not evidence.structured_concurrency:
        blockers.append("STRUCTURED_CONCURRENCY_NOT_PROVEN")
    if not evidence.continuous_run_until_stopped:
        blockers.append("RUN_UNTIL_STOPPED_IS_NOT_CONTINUOUS")
    if not evidence.stop_on_first_blocked_candidate_contract_enforced:
        blockers.append("STOP_ON_FIRST_BLOCKED_CANDIDATE_CONTRACT_NOT_ENFORCED")
    if evidence.unresolved_blockers:
        blockers.extend(f"UNRESOLVED_BLOCKER:{item}" for item in evidence.unresolved_blockers)

    _evaluate_components(evidence.component_contracts, blockers)
    _evaluate_queue_tracker(evidence.queue_tracker, blockers)
    _evaluate_database_actor(evidence.database_actor, blockers)
    _evaluate_shutdown(evidence.shutdown_protocol, blockers)
    _evaluate_faults(evidence.fault_injection, blockers)

    for stage in evidence.stage_budgets:
        if stage.timeout_ms < stage.cancellation_budget_ms:
            blockers.append(f"STAGE_CANCELLATION_EXCEEDS_TIMEOUT:{stage.stage_name}")
        if stage.max_attempts > 1 and stage.max_external_calls == 0:
            warnings.append(f"STAGE_RETRIES_WITHOUT_EXTERNAL_CALL_BUDGET:{stage.stage_name}")

    evidence_hash = _hash_json(
        {
            "domain": "flashloan-bot/pr142-runtime-orchestration",
            "schema_version": PR142_RESULT_SCHEMA_VERSION,
            "payload": evidence.to_dict(),
        }
    )
    metrics = {
        "stage_count": len(evidence.stage_budgets),
        "component_count": len(evidence.component_contracts),
        "fault_count": len(evidence.fault_injection.covered_faults),
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
    }
    review_ready = not blockers
    return RuntimeOrchestrationDecision(
        schema_version=PR142_RESULT_SCHEMA_VERSION,
        state=PR142_READY_STATE if review_ready else PR142_BLOCKED_STATE,
        review_ready=review_ready,
        paper_runtime_claim_allowed=False,
        live_claim_allowed=False,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        evidence_hash=evidence_hash,
        metrics=metrics,
    )


def assert_pr142_runtime_orchestration_review_ready(
    evidence: RuntimeOrchestrationEvidence,
) -> RuntimeOrchestrationDecision:
    """Raise a typed error unless the PR-142 contract is review-ready."""

    decision = evaluate_pr142_runtime_orchestration(evidence)
    if not decision.review_ready:
        raise PR142RuntimeError("PR142_BLOCKED:" + ",".join(decision.blockers))
    return decision


def _evaluate_components(
    components: Sequence[ComponentContract], blockers: list[str]
) -> None:
    for component in components:
        if not component.owned_by_supervisor:
            blockers.append(f"COMPONENT_NOT_OWNED_BY_SUPERVISOR:{component.component_name}")
        if component.criticality is not ComponentCriticality.CRITICAL:
            blockers.append(f"REQUIRED_COMPONENT_NOT_CRITICAL:{component.component_name}")
        if component.criticality is ComponentCriticality.CRITICAL:
            if not component.failure_changes_readiness:
                blockers.append(
                    f"CRITICAL_COMPONENT_DOES_NOT_CHANGE_READINESS:"
                    f"{component.component_name}"
                )
            if not component.cancellation_propagates:
                blockers.append(
                    f"CRITICAL_COMPONENT_CANCELLATION_NOT_PROPAGATED:"
                    f"{component.component_name}"
                )
        if component.exception_history_limit <= 0:
            blockers.append(f"UNBOUNDED_EXCEPTION_HISTORY:{component.component_name}")


def _evaluate_queue_tracker(
    queue_tracker: QueueTrackerEvidence, blockers: list[str]
) -> None:
    if not queue_tracker.expired_items_release_pending:
        blockers.append("EXPIRED_QUEUE_ITEM_DOES_NOT_RELEASE_TRACKER_PENDING")
    if not queue_tracker.persistent_dedup_enabled:
        blockers.append("PERSISTENT_DEDUP_NOT_ENABLED")
    if not queue_tracker.drop_reason_durable:
        blockers.append("QUEUE_DROP_REASON_NOT_DURABLE")
    if not queue_tracker.backpressure_metrics:
        blockers.append("BACKPRESSURE_METRICS_MISSING")


def _evaluate_database_actor(
    database_actor: DatabaseActorEvidence, blockers: list[str]
) -> None:
    required = {
        "dedicated_writer_actor": database_actor.dedicated_writer_actor,
        "bounded_command_queue": database_actor.bounded_command_queue,
        "no_blocking_db_in_event_loop": database_actor.no_blocking_db_in_event_loop,
        "explicit_reader_connections": database_actor.explicit_reader_connections,
        "process_lock_or_leader_lease": database_actor.process_lock_or_leader_lease,
        "rejects_second_writer_process": database_actor.rejects_second_writer_process,
        "topology_in_readiness": database_actor.topology_in_readiness,
    }
    for name, passed in required.items():
        if not passed:
            blockers.append(f"DATABASE_ACTOR_REQUIREMENT_MISSING:{name}")


def _evaluate_shutdown(
    shutdown: ShutdownProtocolEvidence, blockers: list[str]
) -> None:
    for step in _REQUIRED_SHUTDOWN_STEPS:
        if step not in shutdown.implemented_steps:
            blockers.append(f"MISSING_SHUTDOWN_STEP:{step}")
    if not shutdown.cancellation_preserves_ambiguous_state:
        blockers.append("CANCELLATION_DOES_NOT_PRESERVE_AMBIGUOUS_STATE")
    if not shutdown.no_orphan_tasks_proven:
        blockers.append("NO_ORPHAN_TASKS_NOT_PROVEN")
    if not shutdown.cancelled_error_propagates:
        blockers.append("CANCELLED_ERROR_NOT_PROPAGATED")


def _evaluate_faults(faults: FaultInjectionEvidence, blockers: list[str]) -> None:
    for required_fault in _REQUIRED_FAULTS:
        if required_fault not in faults.covered_faults:
            blockers.append(f"MISSING_FAULT_INJECTION:{required_fault}")
    if not faults.no_task_leak:
        blockers.append("TASK_LEAK_NOT_EXCLUDED")
    if not faults.no_queue_leak:
        blockers.append("QUEUE_LEAK_NOT_EXCLUDED")
    if not faults.no_file_descriptor_leak:
        blockers.append("FILE_DESCRIPTOR_LEAK_NOT_EXCLUDED")
    if not faults.readiness_changes_on_critical_task_death:
        blockers.append("CRITICAL_TASK_DEATH_DOES_NOT_CHANGE_READINESS")


def _hash_json(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_positive(value: int, field_name: str) -> None:
    if value <= 0:
        raise PR142RuntimeError(f"{field_name} must be positive")


def _require_non_negative(value: int, field_name: str) -> None:
    if value < 0:
        raise PR142RuntimeError(f"{field_name} must be non-negative")


def _require_nonempty(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise PR142RuntimeError(f"{field_name} must be non-empty")


def _require_sha256(value: str, field_name: str) -> None:
    if not _SHA256_RE.fullmatch(value):
        raise PR142RuntimeError(f"{field_name} must be a lowercase sha256 hex digest")


def _require_unique(values: Sequence[str], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise PR142RuntimeError(f"{field_name} must not contain duplicates")
