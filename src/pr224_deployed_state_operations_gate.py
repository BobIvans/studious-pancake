"""PR-224 deployed-state operations and cutover evidence gate.

This module is a side-effect-free continuation of the PR-224 production platform
cutover contract. It does not inspect the host, open sockets, read secrets, call
providers, start containers, sign, submit or enable live execution. It validates
materialized evidence produced by an external deployed-state validator before a
production cutover review can be considered.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence

SCHEMA_VERSION = "pr224.deployed-state-operations-gate.v2"
PRODUCT_ID = "studious-pancake.pr224.deployed-state-operations-gate"

REQUIRED_FINDINGS: tuple[str, ...] = (
    "F-038", "F-039",
    "F-137", "F-138", "F-139", "F-140", "F-141", "F-142",
    "F-199", "F-200", "F-201", "F-202", "F-203",
    "F-204", "F-205", "F-206", "F-207", "F-208",
    "F-256", "F-257", "F-258", "F-259", "F-260",
    "F-303", "F-304", "F-305", "F-306", "F-308", "F-409",
)
REQUIRED_UPSTREAM_PRS: tuple[str, ...] = (
    "PR-219", "PR-220", "PR-221", "PR-222", "PR-223",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+=-]{0,159}$")
_PATH_RE = re.compile(r"^/(?:[A-Za-z0-9._-]+/?){1,12}$")


class PR224V2State(StrEnum):
    """High-level deployed-state review state."""

    READY_FOR_TARGET_HOST_CUTOVER_REVIEW = "ready-for-target-host-cutover-review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ReleaseIdentityEvidence:
    """Digest-bound release identity exercised by the target-host validator."""

    release_id: str
    runtime_image_digest: str
    signer_image_digest: str
    source_manifest_digest: str
    wheel_digest: str
    config_bundle_digest: str
    provider_policy_digest: str
    sbom_digest: str
    provenance_digest: str
    validator_binary_digest: str
    runtime_user_uid: int
    signer_user_uid: int

    def __post_init__(self) -> None:
        _identifier(self.release_id, "release_id")
        for field_name in (
            "runtime_image_digest",
            "signer_image_digest",
            "source_manifest_digest",
            "wheel_digest",
            "config_bundle_digest",
            "provider_policy_digest",
            "sbom_digest",
            "provenance_digest",
            "validator_binary_digest",
        ):
            _sha256(getattr(self, field_name), field_name)
        if self.runtime_user_uid <= 0 or self.signer_user_uid <= 0:
            raise ValueError("runtime_user_uid and signer_user_uid must be positive")
        if self.runtime_user_uid == self.signer_user_uid:
            raise ValueError("runtime and signer must not share the same UID")


@dataclass(frozen=True, slots=True)
class NetworkEgressEvidence:
    """Proof that runtime/signer networking is deny-by-default and bounded."""

    deny_by_default_policy_loaded: bool
    runtime_direct_internet_denied: bool
    signer_network_namespace_separate: bool
    signer_egress_denied: bool
    egress_gateway_only: bool
    destinations_exactly_allowlisted: bool
    dns_policy_bound_to_provider_generation: bool
    private_link_local_loopback_denied: bool
    redirect_escape_denied: bool
    denied_probe_digest: str

    def __post_init__(self) -> None:
        _sha256(self.denied_probe_digest, "denied_probe_digest")


@dataclass(frozen=True, slots=True)
class SandboxTraceEvidence:
    """Measured seccomp/AppArmor/filesystem trace evidence for the target host."""

    seccomp_profile_loaded: bool
    apparmor_profile_loaded: bool
    read_only_rootfs: bool
    no_new_privileges: bool
    minimal_capabilities: bool
    sqlite_wal_fsync_trace_passed: bool
    archive_fsync_trace_passed: bool
    forbidden_syscalls_denied: bool
    forbidden_filesystem_paths_denied: bool
    writable_runtime_paths: tuple[str, ...]
    trace_digest: str

    def __post_init__(self) -> None:
        _sha256(self.trace_digest, "trace_digest")
        if not self.writable_runtime_paths:
            raise ValueError("writable_runtime_paths must be non-empty")
        for path in self.writable_runtime_paths:
            _path(path, "writable_runtime_paths")


@dataclass(frozen=True, slots=True)
class ReadinessManagementEvidence:
    """Proof that readiness is authenticated and cannot be false-green."""

    authenticated_management_api: bool
    signed_readiness_snapshot: bool
    readiness_schema_digest: str
    snapshot_bound_to_release_and_boot_generation: bool
    empty_runtime_ready_false: bool
    blocked_runtime_ready_false: bool
    dead_worker_ready_false: bool
    stale_provider_ready_false: bool
    signer_unavailable_ready_false: bool
    recovery_blocked_ready_false: bool
    current_freshness_age_ms: int
    freshness_budget_ms: int

    def __post_init__(self) -> None:
        _sha256(self.readiness_schema_digest, "readiness_schema_digest")
        if self.current_freshness_age_ms < 0 or self.freshness_budget_ms <= 0:
            raise ValueError("freshness ages must be non-negative and bounded")


@dataclass(frozen=True, slots=True)
class DrillEvidence:
    """Materialized SLO, shutdown, backup/restore and rollback evidence."""

    deployed_state_validator_digest: str
    slo_drill_report_digest: str
    shutdown_drill_report_digest: str
    backup_restore_report_digest: str
    rollback_report_digest: str
    rpo_seconds_observed: int
    rpo_seconds_budget: int
    rto_seconds_observed: int
    rto_seconds_budget: int
    orphan_tasks_zero: bool
    orphan_sockets_zero: bool
    split_brain_prevented: bool
    materialized_outputs_not_booleans: bool

    def __post_init__(self) -> None:
        for field_name in (
            "deployed_state_validator_digest",
            "slo_drill_report_digest",
            "shutdown_drill_report_digest",
            "backup_restore_report_digest",
            "rollback_report_digest",
        ):
            _sha256(getattr(self, field_name), field_name)
        for value_name in (
            "rpo_seconds_observed",
            "rpo_seconds_budget",
            "rto_seconds_observed",
            "rto_seconds_budget",
        ):
            if getattr(self, value_name) < 0:
                raise ValueError(f"{value_name} must be non-negative")


@dataclass(frozen=True, slots=True)
class CutoverGovernanceEvidence:
    """Upstream acceptance and tiny-canary governance evidence."""

    accepted_upstream_prs: tuple[str, ...]
    signed_cutover_bundle_digest: str
    independent_approval_quorum_digest: str
    tiny_canary_cap_lamports: int
    tiny_canary_autostop_on_budget_slo_or_finality: bool
    canary_requires_finalized_settlement: bool
    rollback_keeps_dispatched_reconciliation: bool
    signer_sender_default_off_until_bundle: bool
    unrestricted_live_enabled: bool
    live_execution_requested: bool
    signer_requested: bool
    sender_requested: bool

    def __post_init__(self) -> None:
        _sha256(self.signed_cutover_bundle_digest, "signed_cutover_bundle_digest")
        _sha256(
            self.independent_approval_quorum_digest,
            "independent_approval_quorum_digest",
        )
        if self.tiny_canary_cap_lamports <= 0:
            raise ValueError("tiny_canary_cap_lamports must be positive")


@dataclass(frozen=True, slots=True)
class PR224DeployedStateEvidence:
    """Complete PR-224 deployed-state operations evidence envelope."""

    finding_coverage: tuple[str, ...]
    release: ReleaseIdentityEvidence
    network: NetworkEgressEvidence
    sandbox: SandboxTraceEvidence
    readiness: ReadinessManagementEvidence
    drills: DrillEvidence
    cutover: CutoverGovernanceEvidence


@dataclass(frozen=True, slots=True)
class PR224V2Violation:
    """One fail-closed deployed-state blocker."""

    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class PR224V2Report:
    """Deterministic report for PR-224 deployed-state evidence."""

    schema_version: str
    product_id: str
    state: PR224V2State
    evidence_hash: str
    violations: tuple[PR224V2Violation, ...]
    ready_for_target_host_cutover_review: bool
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_allowed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_id": self.product_id,
            "state": self.state.value,
            "ready_for_target_host_cutover_review": (
                self.ready_for_target_host_cutover_review
            ),
            "evidence_hash": self.evidence_hash,
            "violation_count": len(self.violations),
            "violations": [asdict(item) for item in self.violations],
            "live_execution_allowed": self.live_execution_allowed,
            "signer_allowed": self.signer_allowed,
            "sender_allowed": self.sender_allowed,
            "required_findings": list(REQUIRED_FINDINGS),
            "required_upstream_prs": list(REQUIRED_UPSTREAM_PRS),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def evaluate_pr224_deployed_state(
    evidence: PR224DeployedStateEvidence,
) -> PR224V2Report:
    """Validate target-host PR-224 deployed-state evidence."""

    violations: list[PR224V2Violation] = []
    _finding_coverage(evidence.finding_coverage, violations)
    _release(evidence.release, violations)
    _network(evidence.network, violations)
    _sandbox(evidence.sandbox, violations)
    _readiness(evidence.readiness, violations)
    _drills(evidence.drills, violations)
    _cutover(evidence.cutover, violations)

    ordered = tuple(sorted(_dedupe(violations), key=lambda item: (item.code, item.detail)))
    ready = not ordered
    return PR224V2Report(
        schema_version=SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        state=(
            PR224V2State.READY_FOR_TARGET_HOST_CUTOVER_REVIEW
            if ready
            else PR224V2State.BLOCKED
        ),
        evidence_hash=_stable_hash(evidence),
        violations=ordered,
        ready_for_target_host_cutover_review=ready,
    )


def blockers_by_code(report: PR224V2Report) -> Mapping[str, tuple[PR224V2Violation, ...]]:
    """Group violations by stable code for tests and release tooling."""

    grouped: dict[str, list[PR224V2Violation]] = {}
    for violation in report.violations:
        grouped.setdefault(violation.code, []).append(violation)
    return {code: tuple(items) for code, items in grouped.items()}


def _finding_coverage(items: Sequence[str], violations: list[PR224V2Violation]) -> None:
    if tuple(sorted(items)) != tuple(sorted(set(items))):
        _add(violations, "PR224_DUPLICATE_FINDING_COVERAGE", "finding coverage has duplicates")
    missing = [item for item in REQUIRED_FINDINGS if item not in items]
    extra = [item for item in items if item not in REQUIRED_FINDINGS]
    if missing:
        _add(violations, "PR224_MISSING_FINDING_COVERAGE", f"missing findings: {missing}")
    if extra:
        _add(violations, "PR224_UNKNOWN_FINDING_COVERAGE", f"unknown findings: {extra}")


def _release(evidence: ReleaseIdentityEvidence, violations: list[PR224V2Violation]) -> None:
    if evidence.runtime_image_digest == evidence.signer_image_digest:
        _add(violations, "PR224_RELEASE_COLLAPSES_RUNTIME_SIGNER", "runtime and signer images must be distinct")


def _network(evidence: NetworkEgressEvidence, violations: list[PR224V2Violation]) -> None:
    _require_flags(
        violations,
        "PR224_NETWORK_EGRESS_INCOMPLETE",
        deny_by_default_policy_loaded=evidence.deny_by_default_policy_loaded,
        runtime_direct_internet_denied=evidence.runtime_direct_internet_denied,
        signer_network_namespace_separate=evidence.signer_network_namespace_separate,
        signer_egress_denied=evidence.signer_egress_denied,
        egress_gateway_only=evidence.egress_gateway_only,
        destinations_exactly_allowlisted=evidence.destinations_exactly_allowlisted,
        dns_policy_bound_to_provider_generation=(
            evidence.dns_policy_bound_to_provider_generation
        ),
        private_link_local_loopback_denied=evidence.private_link_local_loopback_denied,
        redirect_escape_denied=evidence.redirect_escape_denied,
    )


def _sandbox(evidence: SandboxTraceEvidence, violations: list[PR224V2Violation]) -> None:
    _require_flags(
        violations,
        "PR224_SANDBOX_TRACE_INCOMPLETE",
        seccomp_profile_loaded=evidence.seccomp_profile_loaded,
        apparmor_profile_loaded=evidence.apparmor_profile_loaded,
        read_only_rootfs=evidence.read_only_rootfs,
        no_new_privileges=evidence.no_new_privileges,
        minimal_capabilities=evidence.minimal_capabilities,
        sqlite_wal_fsync_trace_passed=evidence.sqlite_wal_fsync_trace_passed,
        archive_fsync_trace_passed=evidence.archive_fsync_trace_passed,
        forbidden_syscalls_denied=evidence.forbidden_syscalls_denied,
        forbidden_filesystem_paths_denied=evidence.forbidden_filesystem_paths_denied,
    )
    if "/tmp" in evidence.writable_runtime_paths:
        _add(violations, "PR224_SHARED_TMP_WRITABLE", "shared /tmp must not be a runtime writable evidence path")


def _readiness(
    evidence: ReadinessManagementEvidence,
    violations: list[PR224V2Violation],
) -> None:
    _require_flags(
        violations,
        "PR224_READINESS_ANTI_FALSE_GREEN_INCOMPLETE",
        authenticated_management_api=evidence.authenticated_management_api,
        signed_readiness_snapshot=evidence.signed_readiness_snapshot,
        snapshot_bound_to_release_and_boot_generation=(
            evidence.snapshot_bound_to_release_and_boot_generation
        ),
        empty_runtime_ready_false=evidence.empty_runtime_ready_false,
        blocked_runtime_ready_false=evidence.blocked_runtime_ready_false,
        dead_worker_ready_false=evidence.dead_worker_ready_false,
        stale_provider_ready_false=evidence.stale_provider_ready_false,
        signer_unavailable_ready_false=evidence.signer_unavailable_ready_false,
        recovery_blocked_ready_false=evidence.recovery_blocked_ready_false,
    )
    if evidence.current_freshness_age_ms > evidence.freshness_budget_ms:
        _add(
            violations,
            "PR224_READINESS_STALE",
            "current readiness freshness age exceeds budget",
        )


def _drills(evidence: DrillEvidence, violations: list[PR224V2Violation]) -> None:
    if evidence.rpo_seconds_observed > evidence.rpo_seconds_budget:
        _add(violations, "PR224_RPO_BUDGET_EXCEEDED", "observed RPO exceeds budget")
    if evidence.rto_seconds_observed > evidence.rto_seconds_budget:
        _add(violations, "PR224_RTO_BUDGET_EXCEEDED", "observed RTO exceeds budget")
    _require_flags(
        violations,
        "PR224_DRILL_OUTPUT_INCOMPLETE",
        orphan_tasks_zero=evidence.orphan_tasks_zero,
        orphan_sockets_zero=evidence.orphan_sockets_zero,
        split_brain_prevented=evidence.split_brain_prevented,
        materialized_outputs_not_booleans=evidence.materialized_outputs_not_booleans,
    )


def _cutover(
    evidence: CutoverGovernanceEvidence,
    violations: list[PR224V2Violation],
) -> None:
    if tuple(evidence.accepted_upstream_prs) != REQUIRED_UPSTREAM_PRS:
        _add(
            violations,
            "PR224_UPSTREAM_GATES_INCOMPLETE",
            "accepted upstream PRs must be exactly PR-219 through PR-223 in order",
        )
    _require_flags(
        violations,
        "PR224_CUTOVER_GOVERNANCE_INCOMPLETE",
        tiny_canary_autostop_on_budget_slo_or_finality=(
            evidence.tiny_canary_autostop_on_budget_slo_or_finality
        ),
        canary_requires_finalized_settlement=evidence.canary_requires_finalized_settlement,
        rollback_keeps_dispatched_reconciliation=(
            evidence.rollback_keeps_dispatched_reconciliation
        ),
        signer_sender_default_off_until_bundle=evidence.signer_sender_default_off_until_bundle,
    )
    if evidence.unrestricted_live_enabled:
        _add(violations, "PR224_UNRESTRICTED_LIVE_ENABLED", "unrestricted live must remain disabled")
    if evidence.live_execution_requested:
        _add(violations, "PR224_LIVE_EXECUTION_REQUESTED", "this gate must not request live execution")
    if evidence.signer_requested:
        _add(violations, "PR224_SIGNER_REQUESTED", "this gate must not request signer access")
    if evidence.sender_requested:
        _add(violations, "PR224_SENDER_REQUESTED", "this gate must not request sender access")


def _require_flags(
    violations: list[PR224V2Violation],
    code: str,
    **flags: bool,
) -> None:
    missing = [name for name, value in flags.items() if value is not True]
    if missing:
        _add(violations, code, f"missing required flags: {missing}")


def _identifier(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a stable identifier")


def _path(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not _PATH_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be an absolute bounded path")


def _sha256(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not _SHA256_RE.fullmatch(value)
        or value in {"0" * 64, "f" * 64}
    ):
        raise ValueError(f"{field_name} must be a non-placeholder lowercase sha256")


def _stable_hash(value: object) -> str:
    payload = json.dumps(_json(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _json(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value


def _add(violations: list[PR224V2Violation], code: str, detail: str) -> None:
    violations.append(PR224V2Violation(code=code, detail=detail))


def _dedupe(items: Iterable[PR224V2Violation]) -> Iterable[PR224V2Violation]:
    seen: set[tuple[str, str]] = set()
    for item in items:
        key = (item.code, item.detail)
        if key not in seen:
            seen.add(key)
            yield item
