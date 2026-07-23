"""PR-198 V3 continuous sender-free paper/shadow qualification gate.

The V3 audit redefines PR-198 as the installed-artifact, continuous
sender-free paper/shadow qualification layer.  This module is intentionally
an offline evidence validator: it does not import signer, sender, RPC, Jito,
wallet or provider clients and it never enables live execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Mapping

SCHEMA_VERSION = "pr198.sender-free-qualification-v3.v1"
PRODUCT_ID = "studious-pancake.pr198.sender-free-qualification-v3"
LIVE_EXECUTION_ALLOWED = False
SIGNER_ALLOWED = False
SENDER_IMPORT_ALLOWED = False
MIN_SOAK_HOURS = 72.0
MIN_CONTINUOUS_CYCLES = 1_000
MIN_REAL_PROVIDER_CYCLES = 100
MIN_REPLAY_CASES = 10

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_CHAOS_SCENARIOS = (
    "queue_pressure",
    "provider_outage",
    "clock_jump",
    "db_lock",
    "restart_replay",
    "sigterm_drain",
)


class PR198V3Requirement(StrEnum):
    """Reviewable acceptance requirements for revised roadmap PR-198."""

    INSTALLED_ARTIFACT_CUTOVER = "installed_artifact_cutover"
    PR195_196_197_DEPENDENCY_CHAIN = "pr195_196_197_dependency_chain"
    CONTINUOUS_NOT_SAFE_IDLE = "continuous_not_safe_idle"
    DURABLE_INPUT_AND_TERMINAL_OUTCOME = "durable_input_and_terminal_outcome"
    DETERMINISTIC_REPLAY = "deterministic_replay"
    CHAOS_QUALIFICATION = "chaos_qualification"
    SLO_ENVELOPE = "slo_envelope"
    NO_SENDER_OR_LIVE_SURFACE = "no_sender_or_live_surface"


class PR198V3Failure(StrEnum):
    INVALID_EVIDENCE = "invalid_evidence"
    REQUIREMENT_BLOCKED = "requirement_blocked"


class PR198V3BoundaryError(RuntimeError):
    """Raised when malformed PR-198 V3 evidence cannot be evaluated."""

    def __init__(self, failure: PR198V3Failure, message: str) -> None:
        super().__init__(message)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Content-addressed artifact reference used by qualification evidence."""

    label: str
    sha256: str
    relative_path: str

    def __post_init__(self) -> None:
        identifier(self.label, "label")
        sha256(self.sha256, "sha256")
        path = self.relative_path
        if (
            not path
            or path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise PR198V3BoundaryError(
                PR198V3Failure.INVALID_EVIDENCE,
                "evidence artifact path must be a normalized relative path",
            )

    @property
    def ref_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr198-v3/evidence-ref",
                "label": self.label,
                "sha256": self.sha256,
                "relative_path": self.relative_path,
            }
        )


@dataclass(frozen=True, slots=True)
class PR198V3SLOLimits:
    """Default qualification SLO caps for sender-free soak evidence."""

    max_event_loop_lag_ms: int = 250
    max_p99_opportunity_age_ms: int = 5_000
    max_queue_age_ms: int = 10_000
    max_shutdown_ms: int = 30_000
    max_memory_growth_mb: int = 128
    max_fd_growth: int = 16
    max_reconciliation_p99_ms: int = 5_000

    def __post_init__(self) -> None:
        values = (
            self.max_event_loop_lag_ms,
            self.max_p99_opportunity_age_ms,
            self.max_queue_age_ms,
            self.max_shutdown_ms,
            self.max_memory_growth_mb,
            self.max_fd_growth,
            self.max_reconciliation_p99_ms,
        )
        if any(not isinstance(value, int) or value <= 0 for value in values):
            raise ValueError("PR-198 V3 SLO limits must be positive integers")


@dataclass(frozen=True, slots=True)
class PR198V3SLOEvidence:
    """Measured SLO envelope from the continuous sender-free run."""

    max_event_loop_lag_ms: int
    p99_opportunity_age_ms: int
    max_queue_age_ms: int
    max_shutdown_ms: int
    memory_growth_mb: int
    fd_growth: int
    reconciliation_p99_ms: int

    def __post_init__(self) -> None:
        values = (
            ("max_event_loop_lag_ms", self.max_event_loop_lag_ms),
            ("p99_opportunity_age_ms", self.p99_opportunity_age_ms),
            ("max_queue_age_ms", self.max_queue_age_ms),
            ("max_shutdown_ms", self.max_shutdown_ms),
            ("memory_growth_mb", self.memory_growth_mb),
            ("fd_growth", self.fd_growth),
            ("reconciliation_p99_ms", self.reconciliation_p99_ms),
        )
        for name, value in values:
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    def within(self, limits: PR198V3SLOLimits) -> bool:
        return all(
            (
                self.max_event_loop_lag_ms <= limits.max_event_loop_lag_ms,
                self.p99_opportunity_age_ms <= limits.max_p99_opportunity_age_ms,
                self.max_queue_age_ms <= limits.max_queue_age_ms,
                self.max_shutdown_ms <= limits.max_shutdown_ms,
                self.memory_growth_mb <= limits.max_memory_growth_mb,
                self.fd_growth <= limits.max_fd_growth,
                self.reconciliation_p99_ms <= limits.max_reconciliation_p99_ms,
            )
        )

    @property
    def evidence_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr198-v3/slo-evidence",
                "max_event_loop_lag_ms": self.max_event_loop_lag_ms,
                "p99_opportunity_age_ms": self.p99_opportunity_age_ms,
                "max_queue_age_ms": self.max_queue_age_ms,
                "max_shutdown_ms": self.max_shutdown_ms,
                "memory_growth_mb": self.memory_growth_mb,
                "fd_growth": self.fd_growth,
                "reconciliation_p99_ms": self.reconciliation_p99_ms,
            }
        )


@dataclass(frozen=True, slots=True)
class PR198V3QualificationEvidence:
    """Immutable evidence envelope for revised V3 PR-198 qualification."""

    release_id: str
    source_commit_sha256: str
    wheel_sha256: str
    image_sha256: str
    config_sha256: str
    policy_bundle_sha256: str
    run_started_ns: int
    run_ended_ns: int
    cycles_completed: int
    safe_idle_cycles: int
    real_provider_cycles: int
    installed_wheel_exercised: bool
    container_image_exercised: bool
    single_sender_free_service: bool
    uses_pr195_lifecycle: bool
    uses_pr196_provider_contracts: bool
    uses_pr197_economic_proof: bool
    durable_input_before_ack: bool
    durable_terminal_outcome: bool
    bounded_queue_policy: bool
    deterministic_drop_policy: bool
    deterministic_replay_cases: int
    replay_mismatches: int
    acknowledged_event_loss_count: int
    pending_without_terminal_count: int
    unknown_outcome_count: int
    restart_replay_verified: bool
    sigterm_drain_verified: bool
    chaos_scenarios_passed: tuple[str, ...]
    provider_outage_cycles: int
    db_lock_cycles: int
    clock_jump_cycles: int
    sender_imports_detected: int
    live_capability_enabled: bool
    signer_capability_enabled: bool
    shadow_artifact: EvidenceRef
    replay_artifact: EvidenceRef
    chaos_artifact: EvidenceRef
    slo: PR198V3SLOEvidence

    def __post_init__(self) -> None:
        identifier(self.release_id, "release_id")
        for value, field in (
            (self.source_commit_sha256, "source_commit_sha256"),
            (self.wheel_sha256, "wheel_sha256"),
            (self.image_sha256, "image_sha256"),
            (self.config_sha256, "config_sha256"),
            (self.policy_bundle_sha256, "policy_bundle_sha256"),
        ):
            sha256(value, field)
        integer_fields = (
            "run_started_ns",
            "run_ended_ns",
            "cycles_completed",
            "safe_idle_cycles",
            "real_provider_cycles",
            "deterministic_replay_cases",
            "replay_mismatches",
            "acknowledged_event_loss_count",
            "pending_without_terminal_count",
            "unknown_outcome_count",
            "provider_outage_cycles",
            "db_lock_cycles",
            "clock_jump_cycles",
            "sender_imports_detected",
        )
        for field in integer_fields:
            value = getattr(self, field)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if self.run_ended_ns <= self.run_started_ns:
            raise PR198V3BoundaryError(
                PR198V3Failure.INVALID_EVIDENCE,
                "sender-free run must have positive duration",
            )
        for scenario in self.chaos_scenarios_passed:
            identifier(scenario, "chaos_scenario")
        if len(set(self.chaos_scenarios_passed)) != len(self.chaos_scenarios_passed):
            raise PR198V3BoundaryError(
                PR198V3Failure.INVALID_EVIDENCE,
                "chaos scenarios must be unique",
            )

    @property
    def duration_hours(self) -> float:
        return (self.run_ended_ns - self.run_started_ns) / 3_600_000_000_000

    @property
    def evidence_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr198-v3/qualification-evidence",
                "release_id": self.release_id,
                "source_commit_sha256": self.source_commit_sha256,
                "wheel_sha256": self.wheel_sha256,
                "image_sha256": self.image_sha256,
                "config_sha256": self.config_sha256,
                "policy_bundle_sha256": self.policy_bundle_sha256,
                "run_started_ns": self.run_started_ns,
                "run_ended_ns": self.run_ended_ns,
                "cycles_completed": self.cycles_completed,
                "safe_idle_cycles": self.safe_idle_cycles,
                "real_provider_cycles": self.real_provider_cycles,
                "installed_wheel_exercised": self.installed_wheel_exercised,
                "container_image_exercised": self.container_image_exercised,
                "single_sender_free_service": self.single_sender_free_service,
                "uses_pr195_lifecycle": self.uses_pr195_lifecycle,
                "uses_pr196_provider_contracts": self.uses_pr196_provider_contracts,
                "uses_pr197_economic_proof": self.uses_pr197_economic_proof,
                "durable_input_before_ack": self.durable_input_before_ack,
                "durable_terminal_outcome": self.durable_terminal_outcome,
                "bounded_queue_policy": self.bounded_queue_policy,
                "deterministic_drop_policy": self.deterministic_drop_policy,
                "deterministic_replay_cases": self.deterministic_replay_cases,
                "replay_mismatches": self.replay_mismatches,
                "acknowledged_event_loss_count": self.acknowledged_event_loss_count,
                "pending_without_terminal_count": self.pending_without_terminal_count,
                "unknown_outcome_count": self.unknown_outcome_count,
                "restart_replay_verified": self.restart_replay_verified,
                "sigterm_drain_verified": self.sigterm_drain_verified,
                "chaos_scenarios_passed": list(self.chaos_scenarios_passed),
                "provider_outage_cycles": self.provider_outage_cycles,
                "db_lock_cycles": self.db_lock_cycles,
                "clock_jump_cycles": self.clock_jump_cycles,
                "sender_imports_detected": self.sender_imports_detected,
                "live_capability_enabled": self.live_capability_enabled,
                "signer_capability_enabled": self.signer_capability_enabled,
                "shadow_artifact": self.shadow_artifact.ref_hash,
                "replay_artifact": self.replay_artifact.ref_hash,
                "chaos_artifact": self.chaos_artifact.ref_hash,
                "slo": self.slo.evidence_hash,
            }
        )


@dataclass(frozen=True, slots=True)
class PR198V3QualificationReport:
    """Deterministic qualification result for merge/promotion evidence."""

    schema_version: str
    product_id: str
    evidence_hash: str
    passed: bool
    requirement_results: Mapping[str, bool]
    blockers: tuple[str, ...]
    live_execution_allowed: bool = LIVE_EXECUTION_ALLOWED
    signer_allowed: bool = SIGNER_ALLOWED
    sender_import_allowed: bool = SENDER_IMPORT_ALLOWED

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_id": self.product_id,
            "evidence_hash": self.evidence_hash,
            "passed": self.passed,
            "requirement_results": dict(sorted(self.requirement_results.items())),
            "blockers": list(self.blockers),
            "live_execution_allowed": self.live_execution_allowed,
            "signer_allowed": self.signer_allowed,
            "sender_import_allowed": self.sender_import_allowed,
        }

    @property
    def report_hash(self) -> str:
        return hash_json(
            {
                "domain": "studious-pancake/pr198-v3/qualification-report",
                **self.to_json_dict(),
            }
        )


def evaluate_pr198_v3_qualification(
    evidence: PR198V3QualificationEvidence,
    *,
    limits: PR198V3SLOLimits | None = None,
) -> PR198V3QualificationReport:
    """Evaluate sender-free qualification evidence without side effects."""

    limits = limits or PR198V3SLOLimits()
    blockers: list[str] = []
    results: dict[str, bool] = {}

    def record(requirement: PR198V3Requirement, condition: bool, message: str) -> None:
        current = results.get(requirement.value, True)
        results[requirement.value] = current and condition
        if not condition:
            blockers.append(f"{requirement.value}: {message}")

    record(
        PR198V3Requirement.INSTALLED_ARTIFACT_CUTOVER,
        evidence.installed_wheel_exercised
        and evidence.container_image_exercised
        and evidence.single_sender_free_service,
        "qualification must exercise one installed wheel/container service",
    )
    record(
        PR198V3Requirement.PR195_196_197_DEPENDENCY_CHAIN,
        evidence.uses_pr195_lifecycle
        and evidence.uses_pr196_provider_contracts
        and evidence.uses_pr197_economic_proof,
        "continuous service must use accepted PR-195/196/197 contracts",
    )
    record(
        PR198V3Requirement.CONTINUOUS_NOT_SAFE_IDLE,
        evidence.duration_hours >= MIN_SOAK_HOURS
        and evidence.cycles_completed >= MIN_CONTINUOUS_CYCLES
        and evidence.real_provider_cycles >= MIN_REAL_PROVIDER_CYCLES
        and evidence.safe_idle_cycles < evidence.cycles_completed,
        "one-cycle or safe-idle evidence cannot qualify paper readiness",
    )
    record(
        PR198V3Requirement.DURABLE_INPUT_AND_TERMINAL_OUTCOME,
        evidence.durable_input_before_ack
        and evidence.durable_terminal_outcome
        and evidence.bounded_queue_policy
        and evidence.deterministic_drop_policy
        and evidence.acknowledged_event_loss_count == 0
        and evidence.pending_without_terminal_count == 0
        and evidence.unknown_outcome_count == 0,
        "acknowledged input, queue pressure and terminal outcomes must be durable",
    )
    record(
        PR198V3Requirement.DETERMINISTIC_REPLAY,
        evidence.deterministic_replay_cases >= MIN_REPLAY_CASES
        and evidence.replay_mismatches == 0
        and evidence.restart_replay_verified,
        "replay must reproduce attempt ids, decisions and reconciliation hashes",
    )
    record(
        PR198V3Requirement.CHAOS_QUALIFICATION,
        set(REQUIRED_CHAOS_SCENARIOS).issubset(evidence.chaos_scenarios_passed)
        and evidence.provider_outage_cycles > 0
        and evidence.db_lock_cycles > 0
        and evidence.clock_jump_cycles > 0
        and evidence.sigterm_drain_verified,
        "queue pressure, provider outage, clock jump, DB lock, restart and SIGTERM must pass",
    )
    record(
        PR198V3Requirement.SLO_ENVELOPE,
        evidence.slo.within(limits),
        "sender-free soak SLO envelope exceeds accepted limits",
    )
    record(
        PR198V3Requirement.NO_SENDER_OR_LIVE_SURFACE,
        evidence.sender_imports_detected == 0
        and not evidence.live_capability_enabled
        and not evidence.signer_capability_enabled,
        "PR-198 qualification cannot expose sender, signer or live capability",
    )

    return PR198V3QualificationReport(
        schema_version=SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        evidence_hash=evidence.evidence_hash,
        passed=not blockers,
        requirement_results=results,
        blockers=tuple(blockers),
    )


def pr198_v3_status_payload() -> dict[str, object]:
    """Expose a stable fail-closed status for package smoke checks."""

    return {
        "schema_version": SCHEMA_VERSION,
        "roadmap_pr": "PR-198",
        "v3_scope": "continuous_sender_free_paper_shadow_replay_chaos",
        "live_execution_allowed": LIVE_EXECUTION_ALLOWED,
        "signer_allowed": SIGNER_ALLOWED,
        "sender_import_allowed": SENDER_IMPORT_ALLOWED,
        "minimum_soak_hours": MIN_SOAK_HOURS,
        "required_chaos_scenarios": list(REQUIRED_CHAOS_SCENARIOS),
    }


def identifier(value: str, field: str) -> str:
    if not _ID_RE.fullmatch(value):
        raise ValueError(f"{field} must be a bounded structured identifier")
    return value


def sha256(value: str, field: str) -> str:
    if not _SHA256_RE.fullmatch(value) or len(set(value)) == 1:
        raise ValueError(f"{field} must be a non-placeholder lowercase sha256")
    return value


def hash_json(payload: object) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()
