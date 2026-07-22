"""PR-165 enforced infrastructure isolation / HA / DR evidence gate.

This module is deliberately side-effect free.  It does not configure Docker,
Kubernetes, firewalls, object storage, KMS, RPC clients, signers, senders, or
runtime processes.  It defines a deterministic, fail-closed evidence contract
for proving that deployment-time infrastructure policy is actually enforced
rather than merely declared.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Iterable

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_APPROVED_EGRESS_PURPOSES: frozenset[str] = frozenset(
    {
        "rpc",
        "providers",
        "jito",
        "telemetry_alerting",
        "backup_object_store",
    }
)

REQUIRED_BACKUP_CAPABILITIES: frozenset[str] = frozenset(
    {
        "remote_object_store",
        "encrypted",
        "versioned",
        "immutable_or_worm",
        "checksum_verified",
        "restore_tested",
        "independent_failure_domain",
    }
)

REQUIRED_DRILLS: frozenset[str] = frozenset(
    {
        "host_loss",
        "disk_loss",
        "database_corruption",
        "object_store_unavailable",
        "rpc_region_loss",
        "provider_outage",
        "alertmanager_loss",
        "signer_kms_unavailable",
        "network_partition",
        "stale_standby",
        "split_brain",
    }
)

REQUIRED_DEPLOYMENT_TRUTH_FIELDS: frozenset[str] = frozenset(
    {
        "image_digest",
        "apparmor_hash",
        "seccomp_hash",
        "effective_capabilities",
        "egress_rules_hash",
        "mounts_hash",
        "runtime_user",
        "resource_limits_hash",
        "secret_mounts_hash",
        "network_topology_hash",
    }
)

REQUIRED_RPO_RTO_TARGETS: frozenset[str] = frozenset(
    {
        "lifecycle_db_rpo_seconds",
        "evidence_rpo_seconds",
        "alert_state_rpo_seconds",
        "config_policy_rpo_seconds",
        "runtime_recovery_rto_seconds",
        "signer_recovery_rto_seconds",
        "rollback_rto_seconds",
    }
)


class Pr165State(StrEnum):
    REVIEW_READY = "review_ready"
    BLOCKED = "blocked"


class EgressMechanism(StrEnum):
    KUBERNETES_NETWORK_POLICY = "kubernetes_network_policy"
    EGRESS_PROXY = "egress_proxy"
    HOST_FIREWALL = "host_firewall"
    AUDITED_EQUIVALENT = "audited_equivalent"


@dataclass(frozen=True, slots=True)
class EgressEvidence:
    default_deny: bool
    mechanism: EgressMechanism | None
    approved_purposes: frozenset[str]
    arbitrary_internet_blocked: bool
    dns_or_hostname_allowlist_hash: str
    enforcement_artifact_hash: str
    bridge_internal_false_without_firewall: bool = False


@dataclass(frozen=True, slots=True)
class SandboxEvidence:
    apparmor_profile_present: bool
    apparmor_profile_hash: str
    missing_profile_fails_deployment: bool
    seccomp_profile_present: bool
    seccomp_profile_hash: str
    seccomp_validated_against_trace: bool
    production_image_denies_shell_package_debug: bool
    no_new_privileges: bool
    capability_drop_enforced: bool


@dataclass(frozen=True, slots=True)
class SignerRuntimeSeparationEvidence:
    signer_separate_trust_zone: bool
    signer_has_general_internet: bool
    authenticated_ipc_only: bool
    runtime_can_mount_signer_key: bool
    telemetry_can_access_signing_endpoint: bool
    separation_policy_hash: str


@dataclass(frozen=True, slots=True)
class EncryptionAtRestEvidence:
    lifecycle_db_encrypted: bool
    evidence_artifacts_encrypted: bool
    backups_encrypted: bool
    operator_approval_records_encrypted: bool
    alert_state_encrypted_when_sensitive: bool
    kms_or_hsm_managed: bool
    key_rotation_tested: bool
    key_revocation_tested: bool
    keys_separate_from_data: bool
    restore_procedure_hash: str


@dataclass(frozen=True, slots=True)
class BackupEvidence:
    capabilities: frozenset[str]
    object_store_uri_redacted: str
    backup_manifest_hash: str
    restore_manifest_hash: str
    retention_policy_hash: str
    cross_region_copy: bool
    local_sibling_only: bool = False


@dataclass(frozen=True, slots=True)
class RpoRtoEvidence:
    targets_seconds: dict[str, int]
    measured_seconds: dict[str, int]
    drill_report_hash: str


@dataclass(frozen=True, slots=True)
class FailoverEvidence:
    single_active_runtime: bool
    durable_leader_identity: bool
    fencing_token_hash: str
    standby_restore_readiness: bool
    explicit_promotion_required: bool
    old_leader_fenced_before_promotion: bool
    dual_live_senders_possible: bool
    split_brain_drill_hash: str


@dataclass(frozen=True, slots=True)
class ProviderFailoverEvidence:
    independently_attested_endpoints: bool
    same_cluster_genesis: bool
    acceptable_rooted_state: bool
    current_credentials_and_quota: bool
    same_effective_policy: bool
    failover_preserves_evidence_requirements: bool
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class DeploymentTruthEvidence:
    fields: dict[str, str]
    release_identity_hash: str
    policy_declaration_only: bool


@dataclass(frozen=True, slots=True)
class InfrastructureHaDrEvidence:
    environment: str
    policy_hash: str
    egress: EgressEvidence
    sandbox: SandboxEvidence
    separation: SignerRuntimeSeparationEvidence
    encryption: EncryptionAtRestEvidence
    backup: BackupEvidence
    rpo_rto: RpoRtoEvidence
    failover: FailoverEvidence
    provider_failover: ProviderFailoverEvidence
    completed_drills: frozenset[str]
    deployment_truth: DeploymentTruthEvidence


@dataclass(frozen=True, slots=True)
class InfrastructureHaDrDecision:
    state: Pr165State
    blockers: tuple[str, ...]
    evidence_hash: str
    live_claim_allowed: bool = False
    sender_submission_allowed: bool = False

    @property
    def review_ready(self) -> bool:
        return self.state is Pr165State.REVIEW_READY


class Pr165BlockedError(AssertionError):
    """Raised when PR-165 evidence is not review-ready."""

    def __init__(self, blockers: Iterable[str]) -> None:
        self.blockers = tuple(blockers)
        super().__init__("PR-165 infrastructure HA/DR evidence blocked: " + ", ".join(self.blockers))


def evaluate_pr165_infrastructure_ha_dr(
    evidence: InfrastructureHaDrEvidence,
) -> InfrastructureHaDrDecision:
    blockers: list[str] = []
    _collect_identity_blockers(evidence, blockers)
    _collect_egress_blockers(evidence.egress, blockers)
    _collect_sandbox_blockers(evidence.sandbox, blockers)
    _collect_separation_blockers(evidence.separation, blockers)
    _collect_encryption_blockers(evidence.encryption, blockers)
    _collect_backup_blockers(evidence.backup, blockers)
    _collect_rpo_rto_blockers(evidence.rpo_rto, blockers)
    _collect_failover_blockers(evidence.failover, blockers)
    _collect_provider_failover_blockers(evidence.provider_failover, blockers)
    _collect_drill_blockers(evidence.completed_drills, blockers)
    _collect_deployment_truth_blockers(evidence.deployment_truth, blockers)
    canonical_blockers = tuple(sorted(set(blockers)))
    return InfrastructureHaDrDecision(
        state=Pr165State.BLOCKED if canonical_blockers else Pr165State.REVIEW_READY,
        blockers=canonical_blockers,
        evidence_hash=_evidence_hash(evidence),
    )


def assert_pr165_infrastructure_ha_dr_review_ready(
    evidence: InfrastructureHaDrEvidence,
) -> InfrastructureHaDrDecision:
    decision = evaluate_pr165_infrastructure_ha_dr(evidence)
    if not decision.review_ready:
        raise Pr165BlockedError(decision.blockers)
    return decision


def _collect_identity_blockers(
    evidence: InfrastructureHaDrEvidence,
    blockers: list[str],
) -> None:
    if evidence.environment != "production":
        blockers.append("ENVIRONMENT_NOT_PRODUCTION")
    if not _is_sha256(evidence.policy_hash):
        blockers.append("BAD_POLICY_HASH")


def _collect_egress_blockers(evidence: EgressEvidence, blockers: list[str]) -> None:
    if not evidence.default_deny:
        blockers.append("EGRESS_NOT_DEFAULT_DENY")
    if evidence.mechanism is None:
        blockers.append("EGRESS_MECHANISM_MISSING")
    if not evidence.arbitrary_internet_blocked:
        blockers.append("ARBITRARY_INTERNET_EGRESS_NOT_BLOCKED")
    if evidence.bridge_internal_false_without_firewall:
        blockers.append("INTERNAL_FALSE_BRIDGE_WITHOUT_FIREWALL")
    missing = REQUIRED_APPROVED_EGRESS_PURPOSES - evidence.approved_purposes
    for purpose in sorted(missing):
        blockers.append(f"MISSING_APPROVED_EGRESS_PURPOSE:{purpose}")
    if not _is_sha256(evidence.dns_or_hostname_allowlist_hash):
        blockers.append("BAD_DNS_OR_HOSTNAME_ALLOWLIST_HASH")
    if not _is_sha256(evidence.enforcement_artifact_hash):
        blockers.append("BAD_EGRESS_ENFORCEMENT_ARTIFACT_HASH")


def _collect_sandbox_blockers(evidence: SandboxEvidence, blockers: list[str]) -> None:
    required_flags = {
        "APPARMOR_PROFILE_MISSING": evidence.apparmor_profile_present,
        "MISSING_APPARMOR_DOES_NOT_FAIL_DEPLOYMENT": evidence.missing_profile_fails_deployment,
        "SECCOMP_PROFILE_MISSING": evidence.seccomp_profile_present,
        "SECCOMP_NOT_VALIDATED_AGAINST_TRACE": evidence.seccomp_validated_against_trace,
        "PRODUCTION_IMAGE_ALLOWS_SHELL_PACKAGE_OR_DEBUG_TOOLING": evidence.production_image_denies_shell_package_debug,
        "NO_NEW_PRIVILEGES_NOT_ENFORCED": evidence.no_new_privileges,
        "CAPABILITY_DROP_NOT_ENFORCED": evidence.capability_drop_enforced,
    }
    for blocker, ok in required_flags.items():
        if not ok:
            blockers.append(blocker)
    if not _is_sha256(evidence.apparmor_profile_hash):
        blockers.append("BAD_APPARMOR_PROFILE_HASH")
    if not _is_sha256(evidence.seccomp_profile_hash):
        blockers.append("BAD_SECCOMP_PROFILE_HASH")


def _collect_separation_blockers(
    evidence: SignerRuntimeSeparationEvidence,
    blockers: list[str],
) -> None:
    if not evidence.signer_separate_trust_zone:
        blockers.append("SIGNER_NOT_IN_SEPARATE_TRUST_ZONE")
    if evidence.signer_has_general_internet:
        blockers.append("SIGNER_HAS_GENERAL_INTERNET")
    if not evidence.authenticated_ipc_only:
        blockers.append("SIGNER_IPC_NOT_AUTHENTICATED_ONLY")
    if evidence.runtime_can_mount_signer_key:
        blockers.append("RUNTIME_CAN_MOUNT_SIGNER_KEY")
    if evidence.telemetry_can_access_signing_endpoint:
        blockers.append("TELEMETRY_CAN_ACCESS_SIGNING_ENDPOINT")
    if not _is_sha256(evidence.separation_policy_hash):
        blockers.append("BAD_SIGNER_RUNTIME_SEPARATION_HASH")


def _collect_encryption_blockers(
    evidence: EncryptionAtRestEvidence,
    blockers: list[str],
) -> None:
    for name, ok in {
        "LIFECYCLE_DB_NOT_ENCRYPTED": evidence.lifecycle_db_encrypted,
        "EVIDENCE_ARTIFACTS_NOT_ENCRYPTED": evidence.evidence_artifacts_encrypted,
        "BACKUPS_NOT_ENCRYPTED": evidence.backups_encrypted,
        "OPERATOR_APPROVAL_RECORDS_NOT_ENCRYPTED": evidence.operator_approval_records_encrypted,
        "ALERT_STATE_NOT_ENCRYPTED_WHEN_SENSITIVE": evidence.alert_state_encrypted_when_sensitive,
        "KMS_OR_HSM_NOT_MANAGED": evidence.kms_or_hsm_managed,
        "KEY_ROTATION_NOT_TESTED": evidence.key_rotation_tested,
        "KEY_REVOCATION_NOT_TESTED": evidence.key_revocation_tested,
        "KEYS_NOT_SEPARATE_FROM_DATA": evidence.keys_separate_from_data,
    }.items():
        if not ok:
            blockers.append(name)
    if not _is_sha256(evidence.restore_procedure_hash):
        blockers.append("BAD_ENCRYPTED_RESTORE_PROCEDURE_HASH")


def _collect_backup_blockers(evidence: BackupEvidence, blockers: list[str]) -> None:
    if evidence.local_sibling_only:
        blockers.append("BACKUP_IS_LOCAL_SIBLING_ONLY")
    missing = REQUIRED_BACKUP_CAPABILITIES - evidence.capabilities
    for capability in sorted(missing):
        blockers.append(f"MISSING_BACKUP_CAPABILITY:{capability}")
    if not evidence.cross_region_copy:
        blockers.append("CROSS_REGION_BACKUP_COPY_MISSING")
    if not evidence.object_store_uri_redacted.startswith("object://"):
        blockers.append("REMOTE_OBJECT_STORE_REFERENCE_MISSING")
    for name, value in {
        "BAD_BACKUP_MANIFEST_HASH": evidence.backup_manifest_hash,
        "BAD_RESTORE_MANIFEST_HASH": evidence.restore_manifest_hash,
        "BAD_BACKUP_RETENTION_POLICY_HASH": evidence.retention_policy_hash,
    }.items():
        if not _is_sha256(value):
            blockers.append(name)


def _collect_rpo_rto_blockers(evidence: RpoRtoEvidence, blockers: list[str]) -> None:
    missing_targets = REQUIRED_RPO_RTO_TARGETS - set(evidence.targets_seconds)
    missing_measures = REQUIRED_RPO_RTO_TARGETS - set(evidence.measured_seconds)
    for target in sorted(missing_targets):
        blockers.append(f"MISSING_RPO_RTO_TARGET:{target}")
    for measure in sorted(missing_measures):
        blockers.append(f"MISSING_RPO_RTO_MEASUREMENT:{measure}")
    for name in sorted(REQUIRED_RPO_RTO_TARGETS & set(evidence.targets_seconds) & set(evidence.measured_seconds)):
        target = evidence.targets_seconds[name]
        measured = evidence.measured_seconds[name]
        if target < 0 or measured < 0:
            blockers.append(f"NEGATIVE_RPO_RTO_VALUE:{name}")
        elif measured > target:
            blockers.append(f"RPO_RTO_TARGET_EXCEEDED:{name}")
    if not _is_sha256(evidence.drill_report_hash):
        blockers.append("BAD_RPO_RTO_DRILL_REPORT_HASH")


def _collect_failover_blockers(evidence: FailoverEvidence, blockers: list[str]) -> None:
    for name, ok in {
        "SINGLE_ACTIVE_RUNTIME_NOT_PROVEN": evidence.single_active_runtime,
        "DURABLE_LEADER_IDENTITY_MISSING": evidence.durable_leader_identity,
        "STANDBY_RESTORE_READINESS_MISSING": evidence.standby_restore_readiness,
        "EXPLICIT_PROMOTION_NOT_REQUIRED": evidence.explicit_promotion_required,
        "OLD_LEADER_NOT_FENCED_BEFORE_PROMOTION": evidence.old_leader_fenced_before_promotion,
    }.items():
        if not ok:
            blockers.append(name)
    if evidence.dual_live_senders_possible:
        blockers.append("DUAL_LIVE_SENDERS_POSSIBLE")
    if not _is_sha256(evidence.fencing_token_hash):
        blockers.append("BAD_FENCING_TOKEN_HASH")
    if not _is_sha256(evidence.split_brain_drill_hash):
        blockers.append("BAD_SPLIT_BRAIN_DRILL_HASH")


def _collect_provider_failover_blockers(
    evidence: ProviderFailoverEvidence,
    blockers: list[str],
) -> None:
    for name, ok in {
        "FAILOVER_ENDPOINTS_NOT_INDEPENDENTLY_ATTESTED": evidence.independently_attested_endpoints,
        "FAILOVER_CLUSTER_GENESIS_MISMATCH": evidence.same_cluster_genesis,
        "FAILOVER_ROOTED_STATE_NOT_ACCEPTABLE": evidence.acceptable_rooted_state,
        "FAILOVER_CREDENTIALS_OR_QUOTA_NOT_CURRENT": evidence.current_credentials_and_quota,
        "FAILOVER_EFFECTIVE_POLICY_MISMATCH": evidence.same_effective_policy,
        "FAILOVER_BYPASSES_EVIDENCE_REQUIREMENTS": evidence.failover_preserves_evidence_requirements,
    }.items():
        if not ok:
            blockers.append(name)
    if not _is_sha256(evidence.evidence_hash):
        blockers.append("BAD_PROVIDER_FAILOVER_EVIDENCE_HASH")


def _collect_drill_blockers(completed_drills: frozenset[str], blockers: list[str]) -> None:
    missing = REQUIRED_DRILLS - completed_drills
    for drill in sorted(missing):
        blockers.append(f"MISSING_REGIONAL_FAILURE_DRILL:{drill}")


def _collect_deployment_truth_blockers(
    evidence: DeploymentTruthEvidence,
    blockers: list[str],
) -> None:
    if evidence.policy_declaration_only:
        blockers.append("DEPLOYMENT_TRUTH_IS_POLICY_DECLARATION_ONLY")
    missing = REQUIRED_DEPLOYMENT_TRUTH_FIELDS - set(evidence.fields)
    for field in sorted(missing):
        blockers.append(f"MISSING_DEPLOYMENT_TRUTH_FIELD:{field}")
    for field in sorted(REQUIRED_DEPLOYMENT_TRUTH_FIELDS & set(evidence.fields)):
        if not _is_sha256(evidence.fields[field]):
            blockers.append(f"BAD_DEPLOYMENT_TRUTH_HASH:{field}")
    if not _is_sha256(evidence.release_identity_hash):
        blockers.append("BAD_DEPLOYMENT_RELEASE_IDENTITY_HASH")


def _evidence_hash(evidence: InfrastructureHaDrEvidence) -> str:
    return hashlib.sha256(_canonical_json(_to_jsonable(evidence)).encode("utf-8")).hexdigest()


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _to_jsonable(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: _to_jsonable(getattr(value, name))
            for name in sorted(value.__dataclass_fields__)  # type: ignore[attr-defined]
        }
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, frozenset):
        return sorted(_to_jsonable(v) for v in value)
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in sorted(value.items())}
    if isinstance(value, tuple):
        return [_to_jsonable(v) for v in value]
    return value


def _is_sha256(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value))
