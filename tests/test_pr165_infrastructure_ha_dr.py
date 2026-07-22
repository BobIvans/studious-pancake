from __future__ import annotations

import pytest

from src.infrastructure_ha_dr_pr165 import (
    BackupEvidence,
    EgressEvidence,
    EgressMechanism,
    EncryptionAtRestEvidence,
    FailoverEvidence,
    InfrastructureHaDrEvidence,
    Pr165BlockedError,
    ProviderFailoverEvidence,
    RpoRtoEvidence,
    SandboxEvidence,
    SignerRuntimeSeparationEvidence,
    DeploymentTruthEvidence,
    evaluate_pr165_infrastructure_ha_dr,
    assert_pr165_infrastructure_ha_dr_review_ready,
    REQUIRED_APPROVED_EGRESS_PURPOSES,
    REQUIRED_BACKUP_CAPABILITIES,
    REQUIRED_DEPLOYMENT_TRUTH_FIELDS,
    REQUIRED_DRILLS,
    REQUIRED_RPO_RTO_TARGETS,
)

H = "a" * 64


def evidence(**overrides):
    targets = {k: 60 for k in REQUIRED_RPO_RTO_TARGETS}
    measured = {k: 30 for k in REQUIRED_RPO_RTO_TARGETS}
    value = InfrastructureHaDrEvidence(
        environment="production",
        policy_hash=H,
        egress=EgressEvidence(True, EgressMechanism.EGRESS_PROXY, REQUIRED_APPROVED_EGRESS_PURPOSES, True, H, H),
        sandbox=SandboxEvidence(True, H, True, True, H, True, True, True, True),
        separation=SignerRuntimeSeparationEvidence(True, False, True, False, False, H),
        encryption=EncryptionAtRestEvidence(True, True, True, True, True, True, True, True, True, H),
        backup=BackupEvidence(REQUIRED_BACKUP_CAPABILITIES, "object://redacted/pr165", H, H, H, True),
        rpo_rto=RpoRtoEvidence(targets, measured, H),
        failover=FailoverEvidence(True, True, H, True, True, True, False, H),
        provider_failover=ProviderFailoverEvidence(True, True, True, True, True, True, H),
        completed_drills=REQUIRED_DRILLS,
        deployment_truth=DeploymentTruthEvidence({k: H for k in REQUIRED_DEPLOYMENT_TRUTH_FIELDS}, H, False),
    )
    if not overrides:
        return value
    data = {name: getattr(value, name) for name in value.__dataclass_fields__}
    data.update(overrides)
    return InfrastructureHaDrEvidence(**data)


def blockers_for(e):
    return evaluate_pr165_infrastructure_ha_dr(e).blockers


def test_complete_evidence_is_review_ready():
    decision = evaluate_pr165_infrastructure_ha_dr(evidence())
    assert decision.review_ready
    assert decision.live_claim_allowed is False
    assert decision.sender_submission_allowed is False
    assert len(decision.evidence_hash) == 64


def test_egress_must_be_enforced_default_deny_not_compose_declaration():
    e = evidence(egress=EgressEvidence(False, None, frozenset({"rpc"}), False, "bad", H, True))
    blockers = blockers_for(e)
    assert "EGRESS_NOT_DEFAULT_DENY" in blockers
    assert "EGRESS_MECHANISM_MISSING" in blockers
    assert "ARBITRARY_INTERNET_EGRESS_NOT_BLOCKED" in blockers
    assert "INTERNAL_FALSE_BRIDGE_WITHOUT_FIREWALL" in blockers
    assert "BAD_DNS_OR_HOSTNAME_ALLOWLIST_HASH" in blockers
    assert "MISSING_APPROVED_EGRESS_PURPOSE:backup_object_store" in blockers


def test_missing_apparmor_or_seccomp_blocks_deployment():
    e = evidence(sandbox=SandboxEvidence(False, "bad", False, False, "bad", False, False, False, False))
    blockers = blockers_for(e)
    assert "APPARMOR_PROFILE_MISSING" in blockers
    assert "MISSING_APPARMOR_DOES_NOT_FAIL_DEPLOYMENT" in blockers
    assert "SECCOMP_PROFILE_MISSING" in blockers
    assert "SECCOMP_NOT_VALIDATED_AGAINST_TRACE" in blockers
    assert "BAD_APPARMOR_PROFILE_HASH" in blockers
    assert "BAD_SECCOMP_PROFILE_HASH" in blockers


def test_signer_runtime_network_separation_is_mandatory():
    e = evidence(separation=SignerRuntimeSeparationEvidence(False, True, False, True, True, "bad"))
    blockers = blockers_for(e)
    assert "SIGNER_NOT_IN_SEPARATE_TRUST_ZONE" in blockers
    assert "SIGNER_HAS_GENERAL_INTERNET" in blockers
    assert "SIGNER_IPC_NOT_AUTHENTICATED_ONLY" in blockers
    assert "RUNTIME_CAN_MOUNT_SIGNER_KEY" in blockers
    assert "TELEMETRY_CAN_ACCESS_SIGNING_ENDPOINT" in blockers


def test_encryption_at_rest_and_key_lifecycle_required():
    e = evidence(encryption=EncryptionAtRestEvidence(False, False, False, False, False, False, False, False, False, "bad"))
    blockers = blockers_for(e)
    assert "LIFECYCLE_DB_NOT_ENCRYPTED" in blockers
    assert "BACKUPS_NOT_ENCRYPTED" in blockers
    assert "KMS_OR_HSM_NOT_MANAGED" in blockers
    assert "KEY_ROTATION_NOT_TESTED" in blockers
    assert "BAD_ENCRYPTED_RESTORE_PROCEDURE_HASH" in blockers


def test_local_sibling_backup_is_not_disaster_recovery():
    e = evidence(backup=BackupEvidence(frozenset({"encrypted"}), "local://db.bak", "bad", H, H, False, True))
    blockers = blockers_for(e)
    assert "BACKUP_IS_LOCAL_SIBLING_ONLY" in blockers
    assert "REMOTE_OBJECT_STORE_REFERENCE_MISSING" in blockers
    assert "CROSS_REGION_BACKUP_COPY_MISSING" in blockers
    assert "BAD_BACKUP_MANIFEST_HASH" in blockers
    assert "MISSING_BACKUP_CAPABILITY:remote_object_store" in blockers


def test_rpo_rto_targets_must_be_measured_and_met():
    targets = {k: 10 for k in REQUIRED_RPO_RTO_TARGETS}
    measured = {k: 11 for k in REQUIRED_RPO_RTO_TARGETS}
    e = evidence(rpo_rto=RpoRtoEvidence(targets, measured, "bad"))
    blockers = blockers_for(e)
    assert "RPO_RTO_TARGET_EXCEEDED:lifecycle_db_rpo_seconds" in blockers
    assert "BAD_RPO_RTO_DRILL_REPORT_HASH" in blockers


def test_missing_rpo_rto_window_blocks():
    e = evidence(rpo_rto=RpoRtoEvidence({}, {}, H))
    blockers = blockers_for(e)
    assert "MISSING_RPO_RTO_TARGET:lifecycle_db_rpo_seconds" in blockers
    assert "MISSING_RPO_RTO_MEASUREMENT:rollback_rto_seconds" in blockers


def test_failover_requires_fencing_and_no_dual_senders():
    e = evidence(failover=FailoverEvidence(False, False, "bad", False, False, False, True, "bad"))
    blockers = blockers_for(e)
    assert "SINGLE_ACTIVE_RUNTIME_NOT_PROVEN" in blockers
    assert "DURABLE_LEADER_IDENTITY_MISSING" in blockers
    assert "OLD_LEADER_NOT_FENCED_BEFORE_PROMOTION" in blockers
    assert "DUAL_LIVE_SENDERS_POSSIBLE" in blockers
    assert "BAD_SPLIT_BRAIN_DRILL_HASH" in blockers


def test_provider_failover_cannot_bypass_attestation_or_policy():
    e = evidence(provider_failover=ProviderFailoverEvidence(False, False, False, False, False, False, "bad"))
    blockers = blockers_for(e)
    assert "FAILOVER_ENDPOINTS_NOT_INDEPENDENTLY_ATTESTED" in blockers
    assert "FAILOVER_CLUSTER_GENESIS_MISMATCH" in blockers
    assert "FAILOVER_BYPASSES_EVIDENCE_REQUIREMENTS" in blockers
    assert "BAD_PROVIDER_FAILOVER_EVIDENCE_HASH" in blockers


def test_all_regional_failure_drills_are_required():
    e = evidence(completed_drills=frozenset({"host_loss"}))
    blockers = blockers_for(e)
    assert "MISSING_REGIONAL_FAILURE_DRILL:split_brain" in blockers
    assert "MISSING_REGIONAL_FAILURE_DRILL:database_corruption" in blockers


def test_deployment_truth_must_be_observed_not_policy_only():
    e = evidence(deployment_truth=DeploymentTruthEvidence({}, "bad", True))
    blockers = blockers_for(e)
    assert "DEPLOYMENT_TRUTH_IS_POLICY_DECLARATION_ONLY" in blockers
    assert "MISSING_DEPLOYMENT_TRUTH_FIELD:image_digest" in blockers
    assert "BAD_DEPLOYMENT_RELEASE_IDENTITY_HASH" in blockers


def test_bad_deployment_truth_hash_blocks():
    fields = {k: H for k in REQUIRED_DEPLOYMENT_TRUTH_FIELDS}
    fields["image_digest"] = "sha256:mutable-looking"
    blockers = blockers_for(evidence(deployment_truth=DeploymentTruthEvidence(fields, H, False)))
    assert "BAD_DEPLOYMENT_TRUTH_HASH:image_digest" in blockers


def test_assert_helper_raises_typed_blocked_error():
    with pytest.raises(Pr165BlockedError) as err:
        assert_pr165_infrastructure_ha_dr_review_ready(evidence(environment="development"))
    assert "ENVIRONMENT_NOT_PRODUCTION" in err.value.blockers
