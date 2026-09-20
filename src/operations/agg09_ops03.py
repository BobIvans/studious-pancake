"""AGG-09 OPS-03: release conformance, soak and scoped readiness verdict.

This is a fail-closed evidence composition layer.  It cannot promote live
execution and never widens an operating envelope.  A positive result is limited
to the exact profile and release identity supplied by the accepted authorities.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re

from src.operations.mpr2614_continuous_conformance import ConformanceDecision

SCHEMA_VERSION = "agg09.ops03.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_OID_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_REQUIRED_CI_STAGES = frozenset(
    {
        "unit",
        "contract",
        "vm",
        "installed",
        "integration",
        "security",
        "disaster-replay",
    }
)


class Agg09Ops03Error(ValueError):
    """Malformed release/soak evidence."""


def _sha(value: str, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise Agg09Ops03Error(f"{name} must be a lowercase sha256 digest")


def _git_oid(value: str, name: str) -> None:
    if not isinstance(value, str) or not _GIT_OID_RE.fullmatch(value):
        raise Agg09Ops03Error(f"{name} must be a 40- or 64-hex git object id")


def _nonnegative(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise Agg09Ops03Error(f"{name} must be a non-negative integer")


def _positive(value: int, name: str) -> None:
    if type(value) is not int or value <= 0:
        raise Agg09Ops03Error(f"{name} must be a positive integer")


def _digest(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class CIStageEvidence:
    stage: str
    status: str
    log_sha256: str

    def __post_init__(self) -> None:
        if not self.stage.strip():
            raise Agg09Ops03Error("stage is required")
        if self.status not in {"PASS", "FAIL", "BLOCKED", "NOT_AUTHORIZED"}:
            raise Agg09Ops03Error("invalid CI stage status")
        _sha(self.log_sha256, "log_sha256")


@dataclass(frozen=True, slots=True)
class CIPipelineEvidence:
    source_commit: str
    stages: tuple[CIStageEvidence, ...]
    network_suite_status: str
    live_suite_status: str

    def __post_init__(self) -> None:
        _git_oid(self.source_commit, "source_commit")
        if self.network_suite_status not in {"PASS", "BLOCKED", "NOT_AUTHORIZED"}:
            raise Agg09Ops03Error("invalid network_suite_status")
        if self.live_suite_status not in {"PASS", "BLOCKED", "NOT_AUTHORIZED"}:
            raise Agg09Ops03Error("invalid live_suite_status")

    @property
    def reason_codes(self) -> tuple[str, ...]:
        reasons: list[str] = []
        seen = {stage.stage for stage in self.stages}
        if len(seen) != len(self.stages):
            reasons.append("AGG09_CI_DUPLICATE_STAGE")
        if not _REQUIRED_CI_STAGES <= seen:
            reasons.append("AGG09_CI_REQUIRED_STAGE_MISSING")
        for stage in self.stages:
            if stage.stage in _REQUIRED_CI_STAGES and stage.status != "PASS":
                reasons.append(f"AGG09_CI_STAGE_NOT_PASS:{stage.stage}")
        if self.network_suite_status == "BLOCKED":
            reasons.append("AGG09_CI_NETWORK_BLOCKED")
        if self.live_suite_status == "BLOCKED":
            reasons.append("AGG09_CI_LIVE_BLOCKED")
        return tuple(sorted(set(reasons)))

    @property
    def passed(self) -> bool:
        return not self.reason_codes


@dataclass(frozen=True, slots=True)
class ReleaseArtifactEvidence:
    source_commit: str
    tree_sha256: str
    wheel_sha256: str
    image_sha256: str
    lock_sha256: str
    sbom_sha256: str
    notice_sha256: str
    config_sha256: str
    policy_sha256: str
    installed_smoke_passed: bool
    licenses_complete: bool
    quarantined_sender_in_supported_wheel: bool
    live_enabled_by_environment: bool

    def __post_init__(self) -> None:
        _git_oid(self.source_commit, "source_commit")
        for name in (
            "tree_sha256",
            "wheel_sha256",
            "image_sha256",
            "lock_sha256",
            "sbom_sha256",
            "notice_sha256",
            "config_sha256",
            "policy_sha256",
        ):
            _sha(getattr(self, name), name)

    @property
    def reason_codes(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.installed_smoke_passed:
            reasons.append("AGG09_RELEASE_INSTALLED_SMOKE_FAILED")
        if not self.licenses_complete:
            reasons.append("AGG09_RELEASE_LICENSE_INCOMPLETE")
        if self.quarantined_sender_in_supported_wheel:
            reasons.append("AGG09_RELEASE_QUARANTINED_SENDER_REACHABLE")
        if self.live_enabled_by_environment:
            reasons.append("AGG09_RELEASE_LIVE_BY_ENV_FORBIDDEN")
        return tuple(sorted(set(reasons)))

    @property
    def passed(self) -> bool:
        return not self.reason_codes

    @property
    def semantic_digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True, slots=True)
class OperationalSoakEvidence:
    policy_sha256: str
    declared_min_duration_seconds: int
    actual_duration_seconds: int
    busy_window_count: int
    quiet_window_count: int
    restart_drill_count: int
    failover_drill_count: int
    incident_count: int
    resolved_incident_count: int
    data_gap_count: int
    dropped_work_count: int
    ledger_accurate_after_recovery: bool
    stable_state_restored: bool

    def __post_init__(self) -> None:
        _sha(self.policy_sha256, "policy_sha256")
        _positive(self.declared_min_duration_seconds, "declared_min_duration_seconds")
        for name in (
            "actual_duration_seconds",
            "busy_window_count",
            "quiet_window_count",
            "restart_drill_count",
            "failover_drill_count",
            "incident_count",
            "resolved_incident_count",
            "data_gap_count",
            "dropped_work_count",
        ):
            _nonnegative(getattr(self, name), name)
        if self.resolved_incident_count > self.incident_count:
            raise Agg09Ops03Error("resolved incidents exceed incidents")

    @property
    def reason_codes(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.actual_duration_seconds < self.declared_min_duration_seconds:
            reasons.append("AGG09_SOAK_DURATION_SHORT")
        if self.busy_window_count < 1:
            reasons.append("AGG09_SOAK_BUSY_WINDOW_MISSING")
        if self.quiet_window_count < 1:
            reasons.append("AGG09_SOAK_QUIET_WINDOW_MISSING")
        if self.restart_drill_count < 1:
            reasons.append("AGG09_SOAK_RESTART_DRILL_MISSING")
        if self.failover_drill_count < 1:
            reasons.append("AGG09_SOAK_FAILOVER_DRILL_MISSING")
        if self.resolved_incident_count != self.incident_count:
            reasons.append("AGG09_SOAK_INCIDENT_UNRESOLVED")
        if self.data_gap_count:
            reasons.append("AGG09_SOAK_DATA_GAPS")
        if self.dropped_work_count:
            reasons.append("AGG09_SOAK_DROPPED_WORK")
        if not self.ledger_accurate_after_recovery:
            reasons.append("AGG09_SOAK_LEDGER_INACCURATE")
        if not self.stable_state_restored:
            reasons.append("AGG09_SOAK_STABLE_STATE_NOT_RESTORED")
        return tuple(sorted(set(reasons)))

    @property
    def passed(self) -> bool:
        return not self.reason_codes


@dataclass(frozen=True, slots=True)
class CapitalProgressionEvidence:
    current_owned_atoms: int
    protected_fee_reserve_atoms: int
    minimum_fee_reserve_atoms: int
    requested_additional_spend_atoms: int
    measured_bottleneck: str | None
    independent_canary_passed: bool
    explicit_user_approval: bool

    def __post_init__(self) -> None:
        for name in (
            "current_owned_atoms",
            "protected_fee_reserve_atoms",
            "minimum_fee_reserve_atoms",
            "requested_additional_spend_atoms",
        ):
            _nonnegative(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class CapitalProgressionDecision:
    allowed: bool
    reason_codes: tuple[str, ...]
    automatic: bool = False


def evaluate_capital_progression(
    evidence: CapitalProgressionEvidence,
) -> CapitalProgressionDecision:
    reasons: list[str] = []
    if evidence.requested_additional_spend_atoms <= 0:
        reasons.append("AGG09_CAPITAL_PROGRESS_REQUEST_EMPTY")
    if not evidence.measured_bottleneck:
        reasons.append("AGG09_CAPITAL_PROGRESS_NO_MEASURED_BOTTLENECK")
    if evidence.protected_fee_reserve_atoms < evidence.minimum_fee_reserve_atoms:
        reasons.append("AGG09_CAPITAL_PROGRESS_FEE_RESERVE_LOW")
    if not evidence.independent_canary_passed:
        reasons.append("AGG09_CAPITAL_PROGRESS_CANARY_MISSING")
    if not evidence.explicit_user_approval:
        reasons.append("AGG09_CAPITAL_PROGRESS_APPROVAL_MISSING")
    return CapitalProgressionDecision(
        allowed=not reasons,
        reason_codes=tuple(sorted(set(reasons))),
        automatic=False,
    )


class ReadinessVerdict(StrEnum):
    BLOCKED = "blocked"
    QUALIFIED_DEFAULT_OFF = "qualified-default-off"


@dataclass(frozen=True, slots=True)
class ProductionReadinessInput:
    release_profile: str
    source_commit: str
    agg04_qualified: bool
    agg05_runtime_ready: bool
    agg08_execution_evidence_ready: bool
    live03_landing_evidence_ready: bool
    ops01_ready: bool
    ops02_ready: bool
    ci: CIPipelineEvidence
    release: ReleaseArtifactEvidence
    conformance: ConformanceDecision
    soak: OperationalSoakEvidence
    external_rights_and_reserves_known: bool
    research_scope_traceable: bool

    def __post_init__(self) -> None:
        if not self.release_profile.strip():
            raise Agg09Ops03Error("release_profile is required")
        _git_oid(self.source_commit, "source_commit")


@dataclass(frozen=True, slots=True)
class ProductionReadinessVerdict:
    verdict: ReadinessVerdict
    release_profile: str
    source_commit: str
    reason_codes: tuple[str, ...]
    implementation_status: str
    operational_status: str
    live_enabled: bool = False
    automatic_scale_up_allowed: bool = False

    @property
    def semantic_digest(self) -> str:
        payload = asdict(self)
        payload["verdict"] = self.verdict.value
        return _digest(payload)


def evaluate_production_readiness(
    evidence: ProductionReadinessInput,
) -> ProductionReadinessVerdict:
    reasons: list[str] = []
    prerequisite_checks = {
        "AGG09_PREREQUISITE_AGG04_MISSING": evidence.agg04_qualified,
        "AGG09_PREREQUISITE_AGG05_MISSING": evidence.agg05_runtime_ready,
        "AGG09_PREREQUISITE_AGG08_MISSING": evidence.agg08_execution_evidence_ready,
        "AGG09_LIVE03_EVIDENCE_MISSING": evidence.live03_landing_evidence_ready,
        "AGG09_OPS01_NOT_READY": evidence.ops01_ready,
        "AGG09_OPS02_NOT_READY": evidence.ops02_ready,
        "AGG09_EXTERNAL_RIGHTS_OR_RESERVES_UNKNOWN": (
            evidence.external_rights_and_reserves_known
        ),
        "AGG09_RESEARCH_SCOPE_NOT_TRACEABLE": evidence.research_scope_traceable,
    }
    for reason, ok in prerequisite_checks.items():
        if not ok:
            reasons.append(reason)
    reasons.extend(evidence.ci.reason_codes)
    reasons.extend(evidence.release.reason_codes)
    if evidence.ci.source_commit != evidence.source_commit:
        reasons.append("AGG09_CI_HEAD_MISMATCH")
    if evidence.release.source_commit != evidence.source_commit:
        reasons.append("AGG09_RELEASE_HEAD_MISMATCH")
    if not evidence.conformance.healthy or evidence.conformance.lease is None:
        reasons.extend(evidence.conformance.reason_codes)
        reasons.append("AGG09_CONTINUOUS_CONFORMANCE_NOT_HEALTHY")
    if evidence.conformance.live_enabled:
        reasons.append("AGG09_CONFORMANCE_LIVE_AUTHORITY_FORBIDDEN")
    reasons.extend(evidence.soak.reason_codes)
    if evidence.release_profile != "production-ready-default-off":
        reasons.append("AGG09_RELEASE_PROFILE_NOT_DEFAULT_OFF")

    unique = tuple(sorted(set(reasons)))
    verdict = (
        ReadinessVerdict.QUALIFIED_DEFAULT_OFF
        if not unique
        else ReadinessVerdict.BLOCKED
    )
    return ProductionReadinessVerdict(
        verdict=verdict,
        release_profile=evidence.release_profile,
        source_commit=evidence.source_commit,
        reason_codes=unique,
        implementation_status="IMPLEMENTED_OFFLINE",
        operational_status=(
            "EXTERNALLY_QUALIFIED_FOR_PROFILE" if not unique else "BLOCKED"
        ),
        live_enabled=False,
        automatic_scale_up_allowed=False,
    )


AGG09_NF_IDS = (
    "NF-240",
    "NF-243",
    "NF-244",
    "NF-245",
    "NF-246",
    "NF-247",
    "NF-248",
    "NF-249",
    "NF-250",
    "NF-251",
    "NF-252",
    "NF-253",
    "NF-254",
    "NF-255",
    "NF-256",
)


__all__ = [
    "AGG09_NF_IDS",
    "Agg09Ops03Error",
    "CIPipelineEvidence",
    "CIStageEvidence",
    "CapitalProgressionDecision",
    "CapitalProgressionEvidence",
    "OperationalSoakEvidence",
    "ProductionReadinessInput",
    "ProductionReadinessVerdict",
    "ReadinessVerdict",
    "ReleaseArtifactEvidence",
    "SCHEMA_VERSION",
    "evaluate_capital_progression",
    "evaluate_production_readiness",
]
