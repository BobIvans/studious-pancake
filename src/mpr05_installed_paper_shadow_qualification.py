"""MPR-05 continuous installed paper/shadow qualification gate.

This module is intentionally offline, deterministic and sender-free.  It models
what evidence a real installed-artifact soak must provide before a paper/shadow
release can be promoted.  It does not import signer, sender, RPC or provider
clients and it never enables live execution.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "mpr05.installed-paper-shadow-qualification.v1"
PRODUCT_ID = "studious-pancake.mpr05.installed-paper-shadow-qualification"
MIN_SOAK_HOURS = 72
MIN_REPLAY_CASES = 10

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$")

REQUIRED_MPR_DEPENDENCIES = ("MPR-01", "MPR-02", "MPR-03", "MPR-04")
REQUIRED_FAULT_INJECTIONS = (
    "provider_outage",
    "db_contention",
    "cancellation",
    "restart_recovery",
    "clock_slot_drift",
    "backlog_pressure",
    "forced_restart",
)


class MPR05Decision(str, Enum):
    """Final qualification decision for the installed paper/shadow artifact."""

    READY_SENDER_FREE = "ready_sender_free"
    BLOCKED = "blocked"


class MPR05Failure(str, Enum):
    """Stable reason categories for malformed or insufficient evidence."""

    INVALID_EVIDENCE = "invalid_evidence"
    REQUIREMENT_BLOCKED = "requirement_blocked"


class MPR05EvidenceError(ValueError):
    """Raised when an MPR-05 evidence bundle is malformed."""


@dataclass(frozen=True, slots=True)
class DependencyEvidence:
    """Accepted prerequisite MPR generation bound into this soak evidence."""

    mpr_id: str
    accepted: bool
    generation_hash: str

    def __post_init__(self) -> None:
        if self.mpr_id not in REQUIRED_MPR_DEPENDENCIES:
            raise MPR05EvidenceError(f"unexpected dependency {self.mpr_id!r}")
        if not isinstance(self.accepted, bool):
            raise MPR05EvidenceError("dependency accepted flag must be boolean")
        _require_sha256(self.generation_hash, "generation_hash")

    def to_dict(self) -> dict[str, object]:
        return {
            "mpr_id": self.mpr_id,
            "accepted": self.accepted,
            "generation_hash": self.generation_hash,
        }


@dataclass(frozen=True, slots=True)
class SLOEnvelope:
    """Maximum values allowed during the installed sender-free soak."""

    terminal_slo_ms: int = 5_000
    max_queue_age_ms: int = 10_000
    max_event_loop_lag_ms: int = 250
    max_worker_heartbeat_age_ms: int = 10_000
    max_shutdown_drain_ms: int = 30_000

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, int) or value <= 0:
                raise MPR05EvidenceError(f"{field.name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class SoakMetrics:
    """Measured values from the installed release artifact."""

    admitted_candidates: int
    durable_terminal_candidates: int
    terminal_within_slo_candidates: int
    replay_case_count: int
    replay_mismatch_count: int
    unexplained_balance_loss_count: int
    evidence_loss_count: int
    leaked_reservation_count: int
    leaked_outbox_claim_count: int
    max_queue_age_ms: int
    max_event_loop_lag_ms: int
    max_worker_heartbeat_age_ms: int
    max_shutdown_drain_ms: int
    forced_restart_count: int
    backlog_pressure_cycles: int
    stale_worker_count: int

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, int) or value < 0:
                raise MPR05EvidenceError(f"{field.name} must be a non-negative integer")

    def to_dict(self) -> dict[str, int]:
        return {field.name: int(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class MPR05QualificationEvidence:
    """Immutable evidence envelope for MPR-05 installed paper/shadow qualification."""

    release_id: str
    source_commit_sha256: str
    wheel_sha256: str
    image_sha256: str
    config_sha256: str
    provider_registry_sha256: str
    protocol_registry_sha256: str
    durable_authority_schema_sha256: str
    composition_root_sha256: str
    soak_started_ns: int
    soak_ended_ns: int
    dependencies: tuple[DependencyEvidence, ...]
    metrics: SoakMetrics
    fault_injections: tuple[str, ...]
    deterministic_replay_hash: str
    signed_soak_artifact_sha256: str
    signature_sha256: str
    installed_wheel_exercised: bool
    installed_container_exercised: bool
    production_composition_root_used: bool
    parallel_runner_used: bool
    management_listener_alive: bool
    workload_workers_alive: bool
    artifact_immutable: bool
    offline_reverification_passed: bool
    signature_verified: bool
    live_execution_allowed: bool = False
    signer_or_sender_reachable: bool = False

    def __post_init__(self) -> None:
        _require_identifier(self.release_id, "release_id")
        for name in (
            "source_commit_sha256",
            "wheel_sha256",
            "image_sha256",
            "config_sha256",
            "provider_registry_sha256",
            "protocol_registry_sha256",
            "durable_authority_schema_sha256",
            "composition_root_sha256",
            "deterministic_replay_hash",
            "signed_soak_artifact_sha256",
            "signature_sha256",
        ):
            _require_sha256(getattr(self, name), name)

        if not isinstance(self.soak_started_ns, int) or not isinstance(
            self.soak_ended_ns, int
        ):
            raise MPR05EvidenceError("soak timestamps must be integers")
        if self.soak_started_ns < 0 or self.soak_ended_ns <= self.soak_started_ns:
            raise MPR05EvidenceError("soak duration must be positive")

        dependency_ids = tuple(item.mpr_id for item in self.dependencies)
        if set(dependency_ids) != set(REQUIRED_MPR_DEPENDENCIES):
            raise MPR05EvidenceError("dependencies must contain exactly MPR-01..MPR-04")
        if len(dependency_ids) != len(set(dependency_ids)):
            raise MPR05EvidenceError("dependencies must not contain duplicates")

        for field_name in (
            "installed_wheel_exercised",
            "installed_container_exercised",
            "production_composition_root_used",
            "parallel_runner_used",
            "management_listener_alive",
            "workload_workers_alive",
            "artifact_immutable",
            "offline_reverification_passed",
            "signature_verified",
            "live_execution_allowed",
            "signer_or_sender_reachable",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise MPR05EvidenceError(f"{field_name} must be boolean")

        for scenario in self.fault_injections:
            _require_identifier(scenario, "fault_injection")
        if len(set(self.fault_injections)) != len(self.fault_injections):
            raise MPR05EvidenceError("fault injections must be unique")

    @property
    def soak_hours(self) -> int:
        return (self.soak_ended_ns - self.soak_started_ns) // 3_600_000_000_000

    def to_dict(self) -> dict[str, object]:
        return {
            "release_id": self.release_id,
            "source_commit_sha256": self.source_commit_sha256,
            "wheel_sha256": self.wheel_sha256,
            "image_sha256": self.image_sha256,
            "config_sha256": self.config_sha256,
            "provider_registry_sha256": self.provider_registry_sha256,
            "protocol_registry_sha256": self.protocol_registry_sha256,
            "durable_authority_schema_sha256": self.durable_authority_schema_sha256,
            "composition_root_sha256": self.composition_root_sha256,
            "soak_started_ns": self.soak_started_ns,
            "soak_ended_ns": self.soak_ended_ns,
            "soak_hours": self.soak_hours,
            "dependencies": [item.to_dict() for item in self.dependencies],
            "metrics": self.metrics.to_dict(),
            "fault_injections": list(self.fault_injections),
            "deterministic_replay_hash": self.deterministic_replay_hash,
            "signed_soak_artifact_sha256": self.signed_soak_artifact_sha256,
            "signature_sha256": self.signature_sha256,
            "installed_wheel_exercised": self.installed_wheel_exercised,
            "installed_container_exercised": self.installed_container_exercised,
            "production_composition_root_used": self.production_composition_root_used,
            "parallel_runner_used": self.parallel_runner_used,
            "management_listener_alive": self.management_listener_alive,
            "workload_workers_alive": self.workload_workers_alive,
            "artifact_immutable": self.artifact_immutable,
            "offline_reverification_passed": self.offline_reverification_passed,
            "signature_verified": self.signature_verified,
            "live_execution_allowed": self.live_execution_allowed,
            "signer_or_sender_reachable": self.signer_or_sender_reachable,
        }


@dataclass(frozen=True, slots=True)
class RequirementResult:
    """One MPR-05 requirement evaluation result."""

    requirement_id: str
    satisfied: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "satisfied": self.satisfied,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class MPR05QualificationReport:
    """Deterministic report for installed paper/shadow qualification."""

    schema_version: str
    product_id: str
    decision: MPR05Decision
    ready: bool
    reason_codes: tuple[str, ...]
    evidence_hash: str
    requirement_results: tuple[RequirementResult, ...]
    soak_hours: int
    live_execution_allowed: bool
    signer_or_sender_reachable: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_id": self.product_id,
            "decision": self.decision.value,
            "ready": self.ready,
            "reason_codes": list(self.reason_codes),
            "evidence_hash": self.evidence_hash,
            "soak_hours": self.soak_hours,
            "live_execution_allowed": self.live_execution_allowed,
            "signer_or_sender_reachable": self.signer_or_sender_reachable,
            "requirement_results": [item.to_dict() for item in self.requirement_results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n"


def evaluate_mpr05_qualification(
    evidence: MPR05QualificationEvidence,
    *,
    slo: SLOEnvelope | None = None,
) -> MPR05QualificationReport:
    """Evaluate an installed-artifact sender-free paper/shadow qualification bundle."""

    limits = slo or SLOEnvelope()
    requirement_results = (
        _installed_artifact_result(evidence),
        _dependency_chain_result(evidence),
        _continuous_soak_result(evidence),
        _durable_terminal_result(evidence, limits),
        _lossless_evidence_result(evidence),
        _deterministic_replay_result(evidence),
        _fault_injection_result(evidence),
        _signed_artifact_result(evidence),
        _no_live_surface_result(evidence),
    )
    reason_codes = tuple(
        f"{result.requirement_id}:{blocker}"
        for result in requirement_results
        for blocker in result.blockers
    )
    ready = not reason_codes
    return MPR05QualificationReport(
        schema_version=SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        decision=MPR05Decision.READY_SENDER_FREE if ready else MPR05Decision.BLOCKED,
        ready=ready,
        reason_codes=reason_codes,
        evidence_hash=_hash_json(evidence.to_dict()),
        requirement_results=requirement_results,
        soak_hours=evidence.soak_hours,
        live_execution_allowed=evidence.live_execution_allowed,
        signer_or_sender_reachable=evidence.signer_or_sender_reachable,
    )


def complete_sender_free_evidence() -> MPR05QualificationEvidence:
    """Return a complete deterministic fixture bundle for tests and examples."""

    return MPR05QualificationEvidence(
        release_id="mpr05-release-001",
        source_commit_sha256="a" * 64,
        wheel_sha256="b" * 64,
        image_sha256="c" * 64,
        config_sha256="d" * 64,
        provider_registry_sha256="e" * 64,
        protocol_registry_sha256="f" * 64,
        durable_authority_schema_sha256="1" * 64,
        composition_root_sha256="2" * 64,
        soak_started_ns=0,
        soak_ended_ns=MIN_SOAK_HOURS * 3_600_000_000_000,
        dependencies=tuple(
            DependencyEvidence(mpr_id=mpr, accepted=True, generation_hash=str(index) * 64)
            for index, mpr in enumerate(REQUIRED_MPR_DEPENDENCIES, start=3)
        ),
        metrics=SoakMetrics(
            admitted_candidates=25,
            durable_terminal_candidates=25,
            terminal_within_slo_candidates=25,
            replay_case_count=MIN_REPLAY_CASES,
            replay_mismatch_count=0,
            unexplained_balance_loss_count=0,
            evidence_loss_count=0,
            leaked_reservation_count=0,
            leaked_outbox_claim_count=0,
            max_queue_age_ms=100,
            max_event_loop_lag_ms=10,
            max_worker_heartbeat_age_ms=100,
            max_shutdown_drain_ms=1000,
            forced_restart_count=2,
            backlog_pressure_cycles=3,
            stale_worker_count=0,
        ),
        fault_injections=REQUIRED_FAULT_INJECTIONS,
        deterministic_replay_hash="9" * 64,
        signed_soak_artifact_sha256="8" * 64,
        signature_sha256="7" * 64,
        installed_wheel_exercised=True,
        installed_container_exercised=True,
        production_composition_root_used=True,
        parallel_runner_used=False,
        management_listener_alive=True,
        workload_workers_alive=True,
        artifact_immutable=True,
        offline_reverification_passed=True,
        signature_verified=True,
    )


def report_json(evidence: MPR05QualificationEvidence) -> str:
    return evaluate_mpr05_qualification(evidence).to_json()


def _installed_artifact_result(evidence: MPR05QualificationEvidence) -> RequirementResult:
    blockers: list[str] = []
    required_flags = (
        ("installed_wheel_exercised", evidence.installed_wheel_exercised),
        ("installed_container_exercised", evidence.installed_container_exercised),
        ("production_composition_root_used", evidence.production_composition_root_used),
    )
    for name, value in required_flags:
        if not value:
            blockers.append(f"{name}_missing")
    if evidence.parallel_runner_used:
        blockers.append("parallel_runner_used")
    return _result("INSTALLED_PRODUCTION_COMPOSITION", blockers)


def _dependency_chain_result(evidence: MPR05QualificationEvidence) -> RequirementResult:
    blockers = [
        f"{dependency.mpr_id.lower()}_not_accepted"
        for dependency in sorted(evidence.dependencies, key=lambda item: item.mpr_id)
        if not dependency.accepted
    ]
    return _result("MPR01_TO_MPR04_DEPENDENCY_CHAIN", blockers)


def _continuous_soak_result(evidence: MPR05QualificationEvidence) -> RequirementResult:
    blockers: list[str] = []
    if evidence.soak_hours < MIN_SOAK_HOURS:
        blockers.append("soak_duration_below_72h")
    if evidence.metrics.admitted_candidates <= 0:
        blockers.append("no_admitted_candidates")
    if evidence.metrics.forced_restart_count <= 0:
        blockers.append("no_forced_restart")
    if evidence.metrics.backlog_pressure_cycles <= 0:
        blockers.append("no_backlog_pressure")
    return _result("CONTINUOUS_72H_SOAK", blockers)


def _durable_terminal_result(
    evidence: MPR05QualificationEvidence,
    limits: SLOEnvelope,
) -> RequirementResult:
    metrics = evidence.metrics
    blockers: list[str] = []
    if metrics.durable_terminal_candidates != metrics.admitted_candidates:
        blockers.append("not_every_candidate_terminal")
    if metrics.terminal_within_slo_candidates != metrics.admitted_candidates:
        blockers.append("not_every_candidate_within_slo")
    if metrics.max_queue_age_ms > limits.max_queue_age_ms:
        blockers.append("queue_age_slo_exceeded")
    if metrics.max_event_loop_lag_ms > limits.max_event_loop_lag_ms:
        blockers.append("event_loop_lag_slo_exceeded")
    if metrics.max_worker_heartbeat_age_ms > limits.max_worker_heartbeat_age_ms:
        blockers.append("worker_heartbeat_slo_exceeded")
    if metrics.max_shutdown_drain_ms > limits.max_shutdown_drain_ms:
        blockers.append("shutdown_drain_slo_exceeded")
    if not evidence.workload_workers_alive:
        blockers.append("workload_workers_dead")
    if metrics.stale_worker_count:
        blockers.append("stale_workers_present")
    if evidence.management_listener_alive and (
        not evidence.workload_workers_alive or metrics.stale_worker_count
    ):
        blockers.append("management_alive_but_workload_unready")
    return _result("DURABLE_TERMINAL_OUTCOME_WITHIN_SLO", blockers)


def _lossless_evidence_result(evidence: MPR05QualificationEvidence) -> RequirementResult:
    metrics = evidence.metrics
    blockers: list[str] = []
    for name in (
        "unexplained_balance_loss_count",
        "evidence_loss_count",
        "leaked_reservation_count",
        "leaked_outbox_claim_count",
    ):
        if getattr(metrics, name):
            blockers.append(name)
    return _result("ZERO_LOSS_AND_NO_LEAKED_CLAIMS", blockers)


def _deterministic_replay_result(evidence: MPR05QualificationEvidence) -> RequirementResult:
    metrics = evidence.metrics
    blockers: list[str] = []
    if metrics.replay_case_count < MIN_REPLAY_CASES:
        blockers.append("too_few_replay_cases")
    if metrics.replay_mismatch_count:
        blockers.append("replay_mismatch")
    return _result("DETERMINISTIC_CAPTURE_REPLAY", blockers)


def _fault_injection_result(evidence: MPR05QualificationEvidence) -> RequirementResult:
    present = set(evidence.fault_injections)
    blockers = [
        f"missing_fault_{scenario}"
        for scenario in REQUIRED_FAULT_INJECTIONS
        if scenario not in present
    ]
    return _result("FAULT_INJECTION_COVERAGE", blockers)


def _signed_artifact_result(evidence: MPR05QualificationEvidence) -> RequirementResult:
    blockers: list[str] = []
    if not evidence.artifact_immutable:
        blockers.append("artifact_not_immutable")
    if not evidence.offline_reverification_passed:
        blockers.append("offline_reverification_failed")
    if not evidence.signature_verified:
        blockers.append("signature_not_verified")
    return _result("SIGNED_IMMUTABLE_OFFLINE_REVERIFIABLE_SOAK_ARTIFACT", blockers)


def _no_live_surface_result(evidence: MPR05QualificationEvidence) -> RequirementResult:
    blockers: list[str] = []
    if evidence.live_execution_allowed:
        blockers.append("live_execution_allowed")
    if evidence.signer_or_sender_reachable:
        blockers.append("signer_or_sender_reachable")
    return _result("NO_LIVE_SIGNER_OR_SENDER_SURFACE", blockers)


def _result(requirement_id: str, blockers: Sequence[str]) -> RequirementResult:
    return RequirementResult(
        requirement_id=requirement_id,
        satisfied=not blockers,
        blockers=tuple(blockers),
    )


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise MPR05EvidenceError(f"{field_name} must be a bounded identifier")


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise MPR05EvidenceError(f"{field_name} must be a lowercase sha256 hex digest")


def _hash_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DependencyEvidence",
    "MPR05Decision",
    "MPR05EvidenceError",
    "MPR05Failure",
    "MPR05QualificationEvidence",
    "MPR05QualificationReport",
    "MIN_SOAK_HOURS",
    "PRODUCT_ID",
    "REQUIRED_FAULT_INJECTIONS",
    "REQUIRED_MPR_DEPENDENCIES",
    "SCHEMA_VERSION",
    "SLOEnvelope",
    "SoakMetrics",
    "complete_sender_free_evidence",
    "evaluate_mpr05_qualification",
    "report_json",
]
