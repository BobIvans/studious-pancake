"""PR-224 production platform, operations and verifiable cutover gate."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re

SCHEMA_VERSION = "pr224.production-platform-cutover-gate.v1"
PRODUCT_ID = "studious-pancake.pr224.production-platform-cutover-gate"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PR224CutoverState(StrEnum):
    READY_FOR_PRODUCTION_CUTOVER_REVIEW = "ready-for-production-cutover-review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class OciReleaseSet:
    runtime_image_digest: str
    signer_image_digest: str
    sbom_digest: str
    provenance_digest: str
    non_root_uid: int
    read_only_rootfs: bool

    def __post_init__(self) -> None:
        for field_name in (
            "runtime_image_digest",
            "signer_image_digest",
            "sbom_digest",
            "provenance_digest",
        ):
            _sha256(getattr(self, field_name), field_name)
        if self.non_root_uid <= 0:
            raise ValueError("non_root_uid must be positive")


@dataclass(frozen=True, slots=True)
class NetworkIsolationEvidence:
    runtime_direct_internet_allowed: bool
    signer_shares_runtime_network: bool
    signer_shares_runtime_mounts: bool
    signer_shares_runtime_user: bool
    allowlisted_egress_gateway_enforced: bool


@dataclass(frozen=True, slots=True)
class SecretFilesystemEvidence:
    example_secrets_present: bool
    plaintext_keys_present: bool
    shared_tmp_state_present: bool
    secret_rotation_requires_rebuild: bool


@dataclass(frozen=True, slots=True)
class SandboxPolicyEvidence:
    seccomp_validated_by_trace: bool
    apparmor_validated_by_trace: bool
    sqlite_wal_trace_passed: bool
    archive_trace_passed: bool
    deny_tests_passed: bool


@dataclass(frozen=True, slots=True)
class OperationsPlaneEvidence:
    unified_management_api: bool
    readiness_includes_freshness: bool
    readiness_blocks_empty_runtime: bool
    readiness_blocks_dead_worker: bool
    shutdown_budget_ms: int
    orphan_tasks_detected: bool

    def __post_init__(self) -> None:
        if self.shutdown_budget_ms <= 0:
            raise ValueError("shutdown_budget_ms must be positive")


@dataclass(frozen=True, slots=True)
class DrillEvidence:
    deployed_state_validator_materialized: bool
    slo_drills_materialized: bool
    backup_restore_rpo_seconds: int
    backup_restore_rto_seconds: int
    rollback_rehearsed: bool

    def __post_init__(self) -> None:
        if self.backup_restore_rpo_seconds < 0 or self.backup_restore_rto_seconds < 0:
            raise ValueError("RPO/RTO must be non-negative")


@dataclass(frozen=True, slots=True)
class CutoverEvidence:
    accepted_pr219_to_pr223: bool
    tiny_canary_autostops: bool
    unrestricted_live_enabled: bool


@dataclass(frozen=True, slots=True)
class PR224CutoverEvidence:
    release_id: str
    release_set: OciReleaseSet
    network: NetworkIsolationEvidence
    secrets: SecretFilesystemEvidence
    sandbox: SandboxPolicyEvidence
    operations: OperationsPlaneEvidence
    drills: DrillEvidence
    cutover: CutoverEvidence

    def __post_init__(self) -> None:
        _identifier(self.release_id, "release_id")


@dataclass(frozen=True, slots=True)
class CutoverViolation:
    code: str
    subject: str
    detail: str

    def __post_init__(self) -> None:
        _identifier(self.code, "code")
        if not self.subject:
            raise ValueError("subject must not be empty")
        if not self.detail:
            raise ValueError("detail must not be empty")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class PR224CutoverReport:
    schema_version: str
    product_id: str
    state: PR224CutoverState
    evidence_hash: str
    violations: tuple[CutoverViolation, ...]
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_allowed: bool = False

    @property
    def ready(self) -> bool:
        return self.state is PR224CutoverState.READY_FOR_PRODUCTION_CUTOVER_REVIEW

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_id": self.product_id,
            "state": self.state.value,
            "ready": self.ready,
            "evidence_hash": self.evidence_hash,
            "violation_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
            "safety_boundary": {
                "live_execution_allowed": self.live_execution_allowed,
                "signer_allowed": self.signer_allowed,
                "sender_allowed": self.sender_allowed,
            },
        }


def evaluate_pr224_cutover(evidence: PR224CutoverEvidence) -> PR224CutoverReport:
    violations: list[CutoverViolation] = []

    if evidence.network.runtime_direct_internet_allowed:
        violations.append(_violation(
            "runtime_direct_internet_allowed",
            "network",
            "runtime must not have direct internet egress outside the allowlisted gateway",
        ))
    if not evidence.network.allowlisted_egress_gateway_enforced:
        violations.append(_violation(
            "missing_allowlisted_egress_gateway",
            "network",
            "production cutover requires deny-by-default egress with an allowlisted gateway",
        ))
    if evidence.network.signer_shares_runtime_network:
        violations.append(_violation(
            "signer_shares_runtime_network",
            "network",
            "signer must not share the runtime network namespace",
        ))
    if evidence.network.signer_shares_runtime_mounts:
        violations.append(_violation(
            "signer_shares_runtime_mounts",
            "filesystem",
            "signer must not share runtime mounts or state paths",
        ))
    if evidence.network.signer_shares_runtime_user:
        violations.append(_violation(
            "signer_shares_runtime_user",
            "identity",
            "signer must not share the runtime user identity",
        ))

    if evidence.secrets.example_secrets_present:
        violations.append(_violation(
            "example_secrets_present",
            "secrets",
            "production deployment must not contain example or placeholder secrets",
        ))
    if evidence.secrets.plaintext_keys_present:
        violations.append(_violation(
            "plaintext_keys_present",
            "secrets",
            "plaintext keys must never be present in runtime state or deployment inputs",
        ))
    if evidence.secrets.shared_tmp_state_present:
        violations.append(_violation(
            "shared_tmp_state_present",
            "filesystem",
            "shared /tmp state between services is forbidden",
        ))
    if evidence.secrets.secret_rotation_requires_rebuild:
        violations.append(_violation(
            "rotation_requires_rebuild",
            "secrets",
            "secret rotation must not require rebuilding the production image",
        ))

    if not evidence.sandbox.seccomp_validated_by_trace:
        violations.append(_violation(
            "seccomp_not_trace_validated",
            "sandbox",
            "seccomp must be validated against measured workload traces",
        ))
    if not evidence.sandbox.apparmor_validated_by_trace:
        violations.append(_violation(
            "apparmor_not_trace_validated",
            "sandbox",
            "AppArmor must be validated against measured workload traces",
        ))
    if not evidence.sandbox.sqlite_wal_trace_passed:
        violations.append(_violation(
            "sqlite_wal_trace_missing",
            "sandbox",
            "sandbox must prove SQLite WAL durability under the real policy",
        ))
    if not evidence.sandbox.archive_trace_passed:
        violations.append(_violation(
            "archive_trace_missing",
            "sandbox",
            "sandbox must prove archive operations under the real policy",
        ))
    if not evidence.sandbox.deny_tests_passed:
        violations.append(_violation(
            "deny_tests_missing",
            "sandbox",
            "deny tests must prove blocked filesystem, secret and network-escape paths",
        ))

    if not evidence.operations.unified_management_api:
        violations.append(_violation(
            "multiple_management_apis",
            "operations",
            "production cutover requires one authenticated management API",
        ))
    if not evidence.operations.readiness_includes_freshness:
        violations.append(_violation(
            "readiness_missing_freshness",
            "readiness",
            "readiness must include freshness-sensitive dependencies",
        ))
    if not evidence.operations.readiness_blocks_empty_runtime:
        violations.append(_violation(
            "readiness_allows_empty_runtime",
            "readiness",
            "empty or blocked runtime must not report ready",
        ))
    if not evidence.operations.readiness_blocks_dead_worker:
        violations.append(_violation(
            "readiness_allows_dead_worker",
            "readiness",
            "dead worker or stuck strategy must not report ready",
        ))
    if evidence.operations.orphan_tasks_detected:
        violations.append(_violation(
            "orphan_tasks_detected",
            "shutdown",
            "shutdown must complete without orphan tasks or sockets",
        ))

    if not evidence.drills.deployed_state_validator_materialized:
        violations.append(_violation(
            "missing_deployed_state_validator",
            "drills",
            "operational evidence must come from a deployed-state validator",
        ))
    if not evidence.drills.slo_drills_materialized:
        violations.append(_violation(
            "missing_slo_drills",
            "drills",
            "cutover requires materialized SLO and fault drill outputs",
        ))
    if not evidence.drills.rollback_rehearsed:
        violations.append(_violation(
            "rollback_not_rehearsed",
            "drills",
            "cutover requires rehearsed rollback evidence",
        ))

    if not evidence.cutover.accepted_pr219_to_pr223:
        violations.append(_violation(
            "upstream_gates_unaccepted",
            "cutover",
            "PR-219 through PR-223 must be accepted before PR-224 cutover review",
        ))
    if not evidence.cutover.tiny_canary_autostops:
        violations.append(_violation(
            "tiny_canary_missing_autostop",
            "cutover",
            "tiny canary must auto-stop on budget, SLO or finality deviation",
        ))
    if evidence.cutover.unrestricted_live_enabled:
        violations.append(_violation(
            "unrestricted_live_enabled",
            "cutover",
            "PR-224 must not enable unrestricted live execution",
        ))

    ordered = tuple(sorted(violations, key=lambda v: (v.code, v.subject, v.detail)))
    state = (
        PR224CutoverState.BLOCKED
        if ordered
        else PR224CutoverState.READY_FOR_PRODUCTION_CUTOVER_REVIEW
    )
    return PR224CutoverReport(
        schema_version=SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        state=state,
        evidence_hash=_evidence_hash(evidence),
        violations=ordered,
    )


def _evidence_hash(evidence: PR224CutoverEvidence) -> str:
    payload = {
        "domain": "studious-pancake/pr224/production-platform-cutover-gate",
        "release_id": evidence.release_id,
        "release_set": asdict(evidence.release_set),
        "network": asdict(evidence.network),
        "secrets": asdict(evidence.secrets),
        "sandbox": asdict(evidence.sandbox),
        "operations": asdict(evidence.operations),
        "drills": asdict(evidence.drills),
        "cutover": asdict(evidence.cutover),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a stable identifier")
    return value


def _sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return value


def _violation(code: str, subject: str, detail: str) -> CutoverViolation:
    return CutoverViolation(code=code, subject=subject, detail=detail)
