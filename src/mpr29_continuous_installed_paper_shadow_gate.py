"""MPR-29 continuous installed paper/shadow workload gate.

This module is intentionally side-effect free. It validates evidence that the
installed sender-free artifact can run a continuous paper/shadow workload with
one lifecycle truth, bounded shutdown, replay-stable evidence, and workload
readiness that depends on real work rather than management liveness.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Mapping, Sequence

SCHEMA_VERSION = "mpr29.continuous-installed-paper-shadow-workload-gate.v1"
LIVE_EXECUTION_ALLOWED = False
SIGNER_ALLOWED = False
SENDER_ALLOWED = False

REQUIRED_UPSTREAM_GATES: tuple[str, ...] = (
    "mpr25",
    "mpr26",
    "mpr27",
    "mpr28",
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/=-]{0,159}$")


class MPR29State(str, Enum):
    READY_FOR_MPR30 = "ready_for_mpr30"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class RuntimeModeEvidence:
    mode_contract_sha256: str
    runtime_graph_sha256: str
    safe_idle_mode_present: bool
    paper_mode_present: bool
    shadow_mode_present: bool
    live_gate_mode_present: bool
    same_runtime_graph_for_all_modes: bool
    safe_idle_never_satisfies_paper_ready: bool
    safe_idle_never_satisfies_shadow_ready: bool
    live_gate_default_off: bool


@dataclass(frozen=True)
class LifecycleEvidence:
    lifecycle_trace_sha256: str
    candidate_event_hash_sha256: str
    exactly_one_terminal_state_per_candidate: bool
    expiry_releases_lifecycle_and_reservation: bool
    rejection_releases_lifecycle_and_reservation: bool
    cancellation_releases_lifecycle_and_reservation: bool
    deterministic_capture_replay: bool
    no_process_local_terminal_truth: bool
    no_unbounded_rejection_aggregation: bool
    no_heap_mutation_outside_async_lock: bool


@dataclass(frozen=True)
class ReadinessEvidence:
    readiness_contract_sha256: str
    worker_generation_sha256: str
    latest_terminal_cycle_sha256: str
    provider_freshness_sha256: str
    replay_state_sha256: str
    ready_requires_real_workload: bool
    unready_when_safe_idle: bool
    unready_when_dead_worker: bool
    unready_when_stale_provider_root: bool
    unready_when_blocked_outbox: bool
    unready_when_exact_simulator_missing: bool
    management_liveness_alone_never_green: bool


@dataclass(frozen=True)
class ShutdownChaosEvidence:
    chaos_matrix_sha256: str
    bounded_shutdown_seconds: int
    sigkill_boundaries_tested: bool
    full_disk_tested: bool
    locked_db_tested: bool
    provider_timeout_tested: bool
    malformed_payload_tested: bool
    shutdown_during_handler_tested: bool
    no_orphan_tasks_sockets_or_writes: bool
    structured_concurrency_enforced: bool


@dataclass(frozen=True)
class SoakEvidence:
    soak_report_sha256: str
    replay_hash_sha256: str
    pre_soak_hours: int
    soak_hours: int
    provider_faults_tested: bool
    db_contention_tested: bool
    backlog_pressure_tested: bool
    clock_and_slot_drift_tested: bool
    replay_hash_stable_across_restart: bool
    identical_replay_hash_across_clean_hosts: bool


@dataclass(frozen=True)
class InstalledArtifactEvidence:
    wheel_sha256: str
    image_sha256: str
    install_trace_sha256: str
    digest_pinned_runtime_image: bool
    runs_only_from_installed_artifact: bool
    source_checkout_imports_blocked: bool
    hidden_dependency_injection_blocked: bool
    sender_namespace_absent: bool
    signer_namespace_absent: bool
    live_submission_namespace_absent: bool


@dataclass(frozen=True)
class MPR29Evidence:
    upstream_gates: Mapping[str, bool]
    runtime_modes: RuntimeModeEvidence
    lifecycle: LifecycleEvidence
    readiness: ReadinessEvidence
    shutdown_chaos: ShutdownChaosEvidence
    soak: SoakEvidence
    artifact: InstalledArtifactEvidence


@dataclass(frozen=True)
class MPR29Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MPR29Report:
    schema_version: str
    state: MPR29State
    blockers: tuple[MPR29Violation, ...]
    evidence_hash: str
    mpr30_unblocked: bool
    live_execution_allowed: bool = LIVE_EXECUTION_ALLOWED
    signer_allowed: bool = SIGNER_ALLOWED
    sender_allowed: bool = SENDER_ALLOWED

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "blockers": [asdict(blocker) for blocker in self.blockers],
            "evidence_hash": self.evidence_hash,
            "mpr30_unblocked": self.mpr30_unblocked,
            "live_execution_allowed": self.live_execution_allowed,
            "signer_allowed": self.signer_allowed,
            "sender_allowed": self.sender_allowed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"


def evaluate_mpr29_evidence(evidence: MPR29Evidence) -> MPR29Report:
    blockers: list[MPR29Violation] = []
    _upstream(evidence.upstream_gates, blockers)
    _runtime_modes(evidence.runtime_modes, blockers)
    _lifecycle(evidence.lifecycle, blockers)
    _readiness(evidence.readiness, blockers)
    _shutdown_chaos(evidence.shutdown_chaos, blockers)
    _soak(evidence.soak, blockers)
    _artifact(evidence.artifact, blockers)

    unique = tuple(_dedupe(blockers))
    ready = not unique
    return MPR29Report(
        schema_version=SCHEMA_VERSION,
        state=MPR29State.READY_FOR_MPR30 if ready else MPR29State.BLOCKED,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        mpr30_unblocked=ready,
    )


def blockers_by_code(report: MPR29Report) -> Mapping[str, tuple[MPR29Violation, ...]]:
    grouped: dict[str, list[MPR29Violation]] = {}
    for blocker in report.blockers:
        grouped.setdefault(blocker.code, []).append(blocker)
    return {code: tuple(items) for code, items in grouped.items()}


def _upstream(items: Mapping[str, bool], blockers: list[MPR29Violation]) -> None:
    missing = [gate for gate in REQUIRED_UPSTREAM_GATES if gate not in items]
    extra = [gate for gate in items if gate not in REQUIRED_UPSTREAM_GATES]
    if missing:
        _add(blockers, "MPR29_MISSING_UPSTREAM_GATE", f"missing upstream gates: {missing}")
    if extra:
        _add(blockers, "MPR29_UNKNOWN_UPSTREAM_GATE", f"unknown upstream gates: {extra}")
    for gate in REQUIRED_UPSTREAM_GATES:
        if gate in items and not items[gate]:
            _add(blockers, "MPR29_UPSTREAM_NOT_READY", f"{gate} must be accepted before MPR-29 readiness")


def _runtime_modes(evidence: RuntimeModeEvidence, blockers: list[MPR29Violation]) -> None:
    _hash_fields(
        blockers,
        "MPR29_BAD_RUNTIME_HASH",
        mode_contract_sha256=evidence.mode_contract_sha256,
        runtime_graph_sha256=evidence.runtime_graph_sha256,
    )
    _require_flags(
        blockers,
        "MPR29_RUNTIME_MODE_INCOMPLETE",
        safe_idle_mode_present=evidence.safe_idle_mode_present,
        paper_mode_present=evidence.paper_mode_present,
        shadow_mode_present=evidence.shadow_mode_present,
        live_gate_mode_present=evidence.live_gate_mode_present,
        same_runtime_graph_for_all_modes=evidence.same_runtime_graph_for_all_modes,
        safe_idle_never_satisfies_paper_ready=evidence.safe_idle_never_satisfies_paper_ready,
        safe_idle_never_satisfies_shadow_ready=evidence.safe_idle_never_satisfies_shadow_ready,
        live_gate_default_off=evidence.live_gate_default_off,
    )


def _lifecycle(evidence: LifecycleEvidence, blockers: list[MPR29Violation]) -> None:
    _hash_fields(
        blockers,
        "MPR29_BAD_LIFECYCLE_HASH",
        lifecycle_trace_sha256=evidence.lifecycle_trace_sha256,
        candidate_event_hash_sha256=evidence.candidate_event_hash_sha256,
    )
    _require_flags(
        blockers,
        "MPR29_LIFECYCLE_INCOMPLETE",
        exactly_one_terminal_state_per_candidate=evidence.exactly_one_terminal_state_per_candidate,
        expiry_releases_lifecycle_and_reservation=evidence.expiry_releases_lifecycle_and_reservation,
        rejection_releases_lifecycle_and_reservation=evidence.rejection_releases_lifecycle_and_reservation,
        cancellation_releases_lifecycle_and_reservation=evidence.cancellation_releases_lifecycle_and_reservation,
        deterministic_capture_replay=evidence.deterministic_capture_replay,
        no_process_local_terminal_truth=evidence.no_process_local_terminal_truth,
        no_unbounded_rejection_aggregation=evidence.no_unbounded_rejection_aggregation,
        no_heap_mutation_outside_async_lock=evidence.no_heap_mutation_outside_async_lock,
    )


def _readiness(evidence: ReadinessEvidence, blockers: list[MPR29Violation]) -> None:
    _hash_fields(
        blockers,
        "MPR29_BAD_READINESS_HASH",
        readiness_contract_sha256=evidence.readiness_contract_sha256,
        worker_generation_sha256=evidence.worker_generation_sha256,
        latest_terminal_cycle_sha256=evidence.latest_terminal_cycle_sha256,
        provider_freshness_sha256=evidence.provider_freshness_sha256,
        replay_state_sha256=evidence.replay_state_sha256,
    )
    _require_flags(
        blockers,
        "MPR29_READINESS_INCOMPLETE",
        ready_requires_real_workload=evidence.ready_requires_real_workload,
        unready_when_safe_idle=evidence.unready_when_safe_idle,
        unready_when_dead_worker=evidence.unready_when_dead_worker,
        unready_when_stale_provider_root=evidence.unready_when_stale_provider_root,
        unready_when_blocked_outbox=evidence.unready_when_blocked_outbox,
        unready_when_exact_simulator_missing=evidence.unready_when_exact_simulator_missing,
        management_liveness_alone_never_green=evidence.management_liveness_alone_never_green,
    )


def _shutdown_chaos(evidence: ShutdownChaosEvidence, blockers: list[MPR29Violation]) -> None:
    _hash_fields(
        blockers,
        "MPR29_BAD_CHAOS_HASH",
        chaos_matrix_sha256=evidence.chaos_matrix_sha256,
    )
    if evidence.bounded_shutdown_seconds <= 0:
        _add(blockers, "MPR29_BAD_SHUTDOWN_BOUND", "shutdown bound must be positive")
    _require_flags(
        blockers,
        "MPR29_CHAOS_INCOMPLETE",
        sigkill_boundaries_tested=evidence.sigkill_boundaries_tested,
        full_disk_tested=evidence.full_disk_tested,
        locked_db_tested=evidence.locked_db_tested,
        provider_timeout_tested=evidence.provider_timeout_tested,
        malformed_payload_tested=evidence.malformed_payload_tested,
        shutdown_during_handler_tested=evidence.shutdown_during_handler_tested,
        no_orphan_tasks_sockets_or_writes=evidence.no_orphan_tasks_sockets_or_writes,
        structured_concurrency_enforced=evidence.structured_concurrency_enforced,
    )


def _soak(evidence: SoakEvidence, blockers: list[MPR29Violation]) -> None:
    _hash_fields(
        blockers,
        "MPR29_BAD_SOAK_HASH",
        soak_report_sha256=evidence.soak_report_sha256,
        replay_hash_sha256=evidence.replay_hash_sha256,
    )
    if evidence.pre_soak_hours < 24:
        _add(blockers, "MPR29_PRE_SOAK_TOO_SHORT", "pre-soak must cover at least 24 hours")
    if evidence.soak_hours < 72:
        _add(blockers, "MPR29_SOAK_TOO_SHORT", "soak must cover at least 72 hours")
    _require_flags(
        blockers,
        "MPR29_SOAK_INCOMPLETE",
        provider_faults_tested=evidence.provider_faults_tested,
        db_contention_tested=evidence.db_contention_tested,
        backlog_pressure_tested=evidence.backlog_pressure_tested,
        clock_and_slot_drift_tested=evidence.clock_and_slot_drift_tested,
        replay_hash_stable_across_restart=evidence.replay_hash_stable_across_restart,
        identical_replay_hash_across_clean_hosts=evidence.identical_replay_hash_across_clean_hosts,
    )


def _artifact(evidence: InstalledArtifactEvidence, blockers: list[MPR29Violation]) -> None:
    _hash_fields(
        blockers,
        "MPR29_BAD_ARTIFACT_HASH",
        wheel_sha256=evidence.wheel_sha256,
        image_sha256=evidence.image_sha256,
        install_trace_sha256=evidence.install_trace_sha256,
    )
    _require_flags(
        blockers,
        "MPR29_ARTIFACT_BOUNDARY_INCOMPLETE",
        digest_pinned_runtime_image=evidence.digest_pinned_runtime_image,
        runs_only_from_installed_artifact=evidence.runs_only_from_installed_artifact,
        source_checkout_imports_blocked=evidence.source_checkout_imports_blocked,
        hidden_dependency_injection_blocked=evidence.hidden_dependency_injection_blocked,
        sender_namespace_absent=evidence.sender_namespace_absent,
        signer_namespace_absent=evidence.signer_namespace_absent,
        live_submission_namespace_absent=evidence.live_submission_namespace_absent,
    )


def _hash_fields(blockers: list[MPR29Violation], code: str, **fields: str) -> None:
    for field_name, value in fields.items():
        if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
            _add(blockers, code, f"{field_name} must be a lowercase sha256 digest")


def _require_flags(blockers: list[MPR29Violation], code: str, **flags: bool) -> None:
    for name, flag in flags.items():
        if not flag:
            _add(blockers, code, f"{name} must be true")


def _stable_hash(evidence: MPR29Evidence) -> str:
    payload = json.dumps(asdict(evidence), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dedupe(blockers: Sequence[MPR29Violation]) -> Sequence[MPR29Violation]:
    seen: set[tuple[str, str]] = set()
    result: list[MPR29Violation] = []
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            result.append(blocker)
    return result


def _add(blockers: list[MPR29Violation], code: str, message: str) -> None:
    if not IDENTIFIER_RE.fullmatch(code):
        raise ValueError(f"invalid blocker code: {code}")
    blockers.append(MPR29Violation(code=code, message=message))