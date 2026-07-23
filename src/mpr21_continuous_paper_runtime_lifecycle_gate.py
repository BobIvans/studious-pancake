"""MPR-21 continuous paper/shadow runtime lifecycle qualification gate.

This module is intentionally side-effect free. It does not start workers, open
network connections, touch SQLite, import provider SDKs, load keys, sign, submit
or execute trades. It defines the deterministic evidence contract that a real
MPR-21 cutover must satisfy before the repository may claim continuous bounded
sender-free paper/shadow readiness.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import math
import re
from typing import Mapping, Sequence


SCHEMA_VERSION = "mpr21.continuous-paper-runtime-lifecycle.v1"

REQUIRED_NEW_FINDINGS: tuple[str, ...] = (
    "F-369",
    "F-388",
    *tuple(f"F-{n}" for n in range(404, 414)),
    *tuple(f"F-{n}" for n in range(416, 420)),
)

REQUIRED_CARRY_FORWARD_FINDINGS: tuple[str, ...] = tuple(
    f"F-{n}" for n in range(297, 304)
)

REQUIRED_FAULT_SCENARIOS: tuple[str, ...] = (
    "queue_expiry_reinsertion",
    "mandatory_worker_exception",
    "callback_exception",
    "result_sink_failure",
    "database_writer_stall",
    "hanging_shutdown_handler",
    "full_queue_shutdown",
    "slow_durable_writer_shutdown",
    "nan_timestamp_rejection",
    "wall_clock_rollback",
    "container_management_alive_worker_dead",
)

HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")


class MPR21GateState(str, Enum):
    """MPR-21 evidence gate state."""

    CONTINUOUS_SENDER_FREE_RUNTIME_QUALIFIED = (
        "continuous_sender_free_runtime_qualified"
    )
    BLOCKED = "blocked"


class MPR21RuntimeMode(str, Enum):
    """Runtime mode covered by the evidence."""

    PAPER = "paper"
    SHADOW = "shadow"


@dataclass(frozen=True)
class QueueLifecycleEvidence:
    """Evidence that queue, lifecycle and result truth have one owner."""

    durable_attempt_authority: bool
    enqueue_claim_expire_complete_reject_single_fsm: bool
    queue_identity_bound_to_attempt: bool
    idempotency_key_bound_to_attempt_and_payload: bool
    atomic_expiry_terminalizes_or_releases: bool
    expiry_uses_async_lock: bool
    expired_item_reinsertion_proven: bool
    no_pending_leak_after_expiry: bool
    exactly_one_durable_outcome_per_item: bool
    result_committed_before_terminal_tracker: bool
    result_sink_failure_keeps_recoverable_nonterminal: bool
    independent_tracker_truth_removed: bool


@dataclass(frozen=True)
class BoundedRetentionEvidence:
    """Evidence that long-running state has hard retention and cursor bounds."""

    terminal_tracker_durable_bounded: bool
    result_sink_durable_bounded: bool
    supervisor_reports_durable_bounded: bool
    rejection_aggregation_bounded: bool
    cursor_pagination_deterministic: bool
    retention_policy_hash: str
    max_terminal_records: int
    max_result_records: int
    max_supervisor_reports: int
    measured_peak_memory_bytes: int
    memory_budget_bytes: int


@dataclass(frozen=True)
class StructuredConcurrencyEvidence:
    """Evidence for mandatory worker supervision and generation-aware restart."""

    mandatory_workers: tuple[str, ...]
    worker_generation_id: str
    worker_crash_sets_unready: bool
    fatal_evidence_persisted: bool
    bounded_restart_backoff: bool
    restart_creates_new_generation: bool
    worker_death_not_masked_as_success: bool
    cleanup_errors_not_suppressed: bool
    incomplete_work_ids_persisted: bool
    durable_recovery_plan_persisted: bool


@dataclass(frozen=True)
class ShutdownEvidence:
    """Evidence that shutdown has one absolute deadline and one owner."""

    admission_closed_first: bool
    bounded_critical_commits: bool
    no_second_unbounded_drain: bool
    absolute_deadline_ms: int
    measured_worst_case_shutdown_ms: int
    hanging_handler_test_passed: bool
    full_queue_test_passed: bool
    slow_writer_test_passed: bool
    terminal_shutdown_outcome_persisted: bool


@dataclass(frozen=True)
class TimingReadinessEvidence:
    """Evidence for finite timing, boot-domain clocks and real workload readiness."""

    timing_fields_finite_positive: bool
    nan_infinity_rejected: bool
    future_causal_timestamp_rejected: bool
    ttl_uses_monotonic_clock_in_boot_domain: bool
    persisted_deadlines_use_utc_and_generation: bool
    wall_clock_rollback_cannot_make_ready: bool
    readiness_has_distinct_live_ready_paper_live_gate: bool
    readiness_requires_worker_generation: bool
    readiness_requires_queue_backlog_slo: bool
    readiness_requires_provider_root_freshness: bool
    readiness_requires_recent_durable_terminal_cycle: bool
    management_listener_not_sufficient: bool
    container_health_fails_when_worker_dead: bool
    latest_terminal_cycle_age_ms: int
    max_terminal_cycle_age_ms: int


@dataclass(frozen=True)
class MPR21Evidence:
    """Complete MPR-21 acceptance evidence."""

    mpr18_accepted: bool
    mpr18_evidence_hash: str
    mpr19_accepted: bool
    mpr19_evidence_hash: str
    findings_covered: tuple[str, ...]
    carry_forward_findings_covered: tuple[str, ...]
    runtime_modes: tuple[MPR21RuntimeMode, ...]
    installed_mpr18_composition_used: bool
    mpr19_authority_used: bool
    queue_lifecycle: QueueLifecycleEvidence
    bounded_retention: BoundedRetentionEvidence
    structured_concurrency: StructuredConcurrencyEvidence
    shutdown: ShutdownEvidence
    timing_readiness: TimingReadinessEvidence
    fault_scenarios_passed: tuple[str, ...]
    workload_readiness_timeline_hash: str
    transition_model_hash: str
    memory_backpressure_profile_hash: str
    live_execution_requested: bool = False
    signer_requested: bool = False
    sender_requested: bool = False
    private_key_material_present: bool = False


@dataclass(frozen=True)
class MPR21Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MPR21Report:
    schema_version: str
    state: MPR21GateState
    violations: tuple[MPR21Violation, ...]
    covered_new_findings: tuple[str, ...]
    covered_carry_forward_findings: tuple[str, ...]
    missing_new_findings: tuple[str, ...]
    missing_carry_forward_findings: tuple[str, ...]
    transaction_signer_allowed: bool
    sender_allowed: bool
    live_execution_allowed: bool
    private_key_material_allowed: bool

    @property
    def ready(self) -> bool:
        return self.state is MPR21GateState.CONTINUOUS_SENDER_FREE_RUNTIME_QUALIFIED

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["state"] = self.state.value
        return payload


def evaluate_mpr21_evidence(evidence: MPR21Evidence) -> MPR21Report:
    """Evaluate MPR-21 evidence and fail closed on any missing invariant."""

    violations: list[MPR21Violation] = []

    def add(code: str, message: str) -> None:
        violations.append(MPR21Violation(code, message))

    if not evidence.mpr18_accepted:
        add("MPR18_REQUIRED", "MPR-21 requires accepted MPR-18 installed composition.")
    if not evidence.mpr19_accepted:
        add("MPR19_REQUIRED", "MPR-21 requires accepted MPR-19 durable authority.")

    for name, value in (
        ("mpr18_evidence_hash", evidence.mpr18_evidence_hash),
        ("mpr19_evidence_hash", evidence.mpr19_evidence_hash),
        ("workload_readiness_timeline_hash", evidence.workload_readiness_timeline_hash),
        ("transition_model_hash", evidence.transition_model_hash),
        ("memory_backpressure_profile_hash", evidence.memory_backpressure_profile_hash),
        ("retention_policy_hash", evidence.bounded_retention.retention_policy_hash),
    ):
        if not HEX_64_RE.fullmatch(value):
            add("BAD_HASH", f"{name} must be a lowercase SHA-256 digest.")

    missing_new = tuple(
        finding for finding in REQUIRED_NEW_FINDINGS
        if finding not in set(evidence.findings_covered)
    )
    missing_carry = tuple(
        finding for finding in REQUIRED_CARRY_FORWARD_FINDINGS
        if finding not in set(evidence.carry_forward_findings_covered)
    )
    if missing_new:
        add("MISSING_NEW_FINDINGS", f"Missing V9 findings: {', '.join(missing_new)}.")
    if missing_carry:
        add(
            "MISSING_CARRY_FORWARD_FINDINGS",
            f"Missing carry-forward findings: {', '.join(missing_carry)}.",
        )

    if set(evidence.runtime_modes) != {MPR21RuntimeMode.PAPER, MPR21RuntimeMode.SHADOW}:
        add("MODE_COVERAGE", "Both paper and shadow continuous runtime modes are required.")

    if not evidence.installed_mpr18_composition_used:
        add("SOURCE_CHECKOUT_RUNTIME", "Runtime must use installed MPR-18 composition.")
    if not evidence.mpr19_authority_used:
        add("MISSING_DURABLE_AUTHORITY", "Runtime must use MPR-19 durable authority.")

    _validate_queue_lifecycle(evidence.queue_lifecycle, add)
    _validate_bounded_retention(evidence.bounded_retention, add)
    _validate_structured_concurrency(evidence.structured_concurrency, add)
    _validate_shutdown(evidence.shutdown, add)
    _validate_timing_readiness(evidence.timing_readiness, add)

    missing_faults = tuple(
        scenario for scenario in REQUIRED_FAULT_SCENARIOS
        if scenario not in set(evidence.fault_scenarios_passed)
    )
    if missing_faults:
        add("MISSING_FAULT_SCENARIOS", f"Missing fault scenarios: {', '.join(missing_faults)}.")

    if (
        evidence.live_execution_requested
        or evidence.signer_requested
        or evidence.sender_requested
        or evidence.private_key_material_present
    ):
        add(
            "LIVE_SURFACE_FORBIDDEN",
            "MPR-21 is sender-free; live/signer/sender/private-key surfaces must remain absent.",
        )

    state = (
        MPR21GateState.BLOCKED
        if violations
        else MPR21GateState.CONTINUOUS_SENDER_FREE_RUNTIME_QUALIFIED
    )
    return MPR21Report(
        schema_version=SCHEMA_VERSION,
        state=state,
        violations=tuple(violations),
        covered_new_findings=tuple(evidence.findings_covered),
        covered_carry_forward_findings=tuple(evidence.carry_forward_findings_covered),
        missing_new_findings=missing_new,
        missing_carry_forward_findings=missing_carry,
        transaction_signer_allowed=False,
        sender_allowed=False,
        live_execution_allowed=False,
        private_key_material_allowed=False,
    )


def _validate_queue_lifecycle(
    evidence: QueueLifecycleEvidence,
    add: callable,
) -> None:
    required = {
        "durable_attempt_authority": evidence.durable_attempt_authority,
        "enqueue_claim_expire_complete_reject_single_fsm": (
            evidence.enqueue_claim_expire_complete_reject_single_fsm
        ),
        "queue_identity_bound_to_attempt": evidence.queue_identity_bound_to_attempt,
        "idempotency_key_bound_to_attempt_and_payload": (
            evidence.idempotency_key_bound_to_attempt_and_payload
        ),
        "atomic_expiry_terminalizes_or_releases": (
            evidence.atomic_expiry_terminalizes_or_releases
        ),
        "expiry_uses_async_lock": evidence.expiry_uses_async_lock,
        "expired_item_reinsertion_proven": evidence.expired_item_reinsertion_proven,
        "no_pending_leak_after_expiry": evidence.no_pending_leak_after_expiry,
        "exactly_one_durable_outcome_per_item": evidence.exactly_one_durable_outcome_per_item,
        "result_committed_before_terminal_tracker": (
            evidence.result_committed_before_terminal_tracker
        ),
        "result_sink_failure_keeps_recoverable_nonterminal": (
            evidence.result_sink_failure_keeps_recoverable_nonterminal
        ),
        "independent_tracker_truth_removed": evidence.independent_tracker_truth_removed,
    }
    _require_all(required, "QUEUE_LIFECYCLE", add)


def _validate_bounded_retention(
    evidence: BoundedRetentionEvidence,
    add: callable,
) -> None:
    required = {
        "terminal_tracker_durable_bounded": evidence.terminal_tracker_durable_bounded,
        "result_sink_durable_bounded": evidence.result_sink_durable_bounded,
        "supervisor_reports_durable_bounded": evidence.supervisor_reports_durable_bounded,
        "rejection_aggregation_bounded": evidence.rejection_aggregation_bounded,
        "cursor_pagination_deterministic": evidence.cursor_pagination_deterministic,
    }
    _require_all(required, "BOUNDED_RETENTION", add)
    for name in ("max_terminal_records", "max_result_records", "max_supervisor_reports"):
        value = getattr(evidence, name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            add("INVALID_RETENTION_BOUND", f"{name} must be a positive integer.")
    for name in ("measured_peak_memory_bytes", "memory_budget_bytes"):
        value = getattr(evidence, name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            add("INVALID_MEMORY_BOUND", f"{name} must be a positive integer.")
    if (
        isinstance(evidence.measured_peak_memory_bytes, int)
        and isinstance(evidence.memory_budget_bytes, int)
        and evidence.measured_peak_memory_bytes > evidence.memory_budget_bytes
    ):
        add("MEMORY_BUDGET_EXCEEDED", "Measured memory exceeds the declared bound.")


def _validate_structured_concurrency(
    evidence: StructuredConcurrencyEvidence,
    add: callable,
) -> None:
    if len(evidence.mandatory_workers) < 2:
        add("MISSING_MANDATORY_WORKERS", "Detector and consumer/workload workers are required.")
    if not evidence.worker_generation_id.strip():
        add("MISSING_WORKER_GENERATION", "Worker generation identity is required.")
    required = {
        "worker_crash_sets_unready": evidence.worker_crash_sets_unready,
        "fatal_evidence_persisted": evidence.fatal_evidence_persisted,
        "bounded_restart_backoff": evidence.bounded_restart_backoff,
        "restart_creates_new_generation": evidence.restart_creates_new_generation,
        "worker_death_not_masked_as_success": evidence.worker_death_not_masked_as_success,
        "cleanup_errors_not_suppressed": evidence.cleanup_errors_not_suppressed,
        "incomplete_work_ids_persisted": evidence.incomplete_work_ids_persisted,
        "durable_recovery_plan_persisted": evidence.durable_recovery_plan_persisted,
    }
    _require_all(required, "STRUCTURED_CONCURRENCY", add)


def _validate_shutdown(evidence: ShutdownEvidence, add: callable) -> None:
    required = {
        "admission_closed_first": evidence.admission_closed_first,
        "bounded_critical_commits": evidence.bounded_critical_commits,
        "no_second_unbounded_drain": evidence.no_second_unbounded_drain,
        "hanging_handler_test_passed": evidence.hanging_handler_test_passed,
        "full_queue_test_passed": evidence.full_queue_test_passed,
        "slow_writer_test_passed": evidence.slow_writer_test_passed,
        "terminal_shutdown_outcome_persisted": evidence.terminal_shutdown_outcome_persisted,
    }
    _require_all(required, "SHUTDOWN", add)
    for name in ("absolute_deadline_ms", "measured_worst_case_shutdown_ms"):
        value = getattr(evidence, name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            add("INVALID_SHUTDOWN_DEADLINE", f"{name} must be a positive integer.")
    if (
        isinstance(evidence.absolute_deadline_ms, int)
        and isinstance(evidence.measured_worst_case_shutdown_ms, int)
        and evidence.measured_worst_case_shutdown_ms > evidence.absolute_deadline_ms
    ):
        add("SHUTDOWN_DEADLINE_EXCEEDED", "Worst-case shutdown exceeded absolute deadline.")


def _validate_timing_readiness(
    evidence: TimingReadinessEvidence,
    add: callable,
) -> None:
    required = {
        "timing_fields_finite_positive": evidence.timing_fields_finite_positive,
        "nan_infinity_rejected": evidence.nan_infinity_rejected,
        "future_causal_timestamp_rejected": evidence.future_causal_timestamp_rejected,
        "ttl_uses_monotonic_clock_in_boot_domain": (
            evidence.ttl_uses_monotonic_clock_in_boot_domain
        ),
        "persisted_deadlines_use_utc_and_generation": (
            evidence.persisted_deadlines_use_utc_and_generation
        ),
        "wall_clock_rollback_cannot_make_ready": evidence.wall_clock_rollback_cannot_make_ready,
        "readiness_has_distinct_live_ready_paper_live_gate": (
            evidence.readiness_has_distinct_live_ready_paper_live_gate
        ),
        "readiness_requires_worker_generation": evidence.readiness_requires_worker_generation,
        "readiness_requires_queue_backlog_slo": evidence.readiness_requires_queue_backlog_slo,
        "readiness_requires_provider_root_freshness": (
            evidence.readiness_requires_provider_root_freshness
        ),
        "readiness_requires_recent_durable_terminal_cycle": (
            evidence.readiness_requires_recent_durable_terminal_cycle
        ),
        "management_listener_not_sufficient": evidence.management_listener_not_sufficient,
        "container_health_fails_when_worker_dead": (
            evidence.container_health_fails_when_worker_dead
        ),
    }
    _require_all(required, "TIMING_READINESS", add)
    for name in ("latest_terminal_cycle_age_ms", "max_terminal_cycle_age_ms"):
        value = getattr(evidence, name)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or not math.isfinite(float(value))
        ):
            add("INVALID_READY_AGE", f"{name} must be a finite non-negative integer.")
    if (
        isinstance(evidence.latest_terminal_cycle_age_ms, int)
        and isinstance(evidence.max_terminal_cycle_age_ms, int)
        and evidence.latest_terminal_cycle_age_ms > evidence.max_terminal_cycle_age_ms
    ):
        add("STALE_TERMINAL_CYCLE", "Latest durable terminal cycle is too old for readiness.")


def _require_all(values: Mapping[str, bool], category: str, add: callable) -> None:
    missing = tuple(name for name, value in values.items() if value is not True)
    if missing:
        add(category, f"Required booleans are false: {', '.join(missing)}.")
