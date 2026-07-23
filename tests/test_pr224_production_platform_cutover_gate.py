from __future__ import annotations

import pytest

from src.pr224_production_platform_cutover_gate import (
    CutoverEvidence,
    DrillEvidence,
    NetworkIsolationEvidence,
    OciReleaseSet,
    OperationsPlaneEvidence,
    PR224CutoverEvidence,
    PR224CutoverState,
    SandboxPolicyEvidence,
    SecretFilesystemEvidence,
    evaluate_pr224_cutover,
)

D1 = "1" * 64
D2 = "2" * 64
D3 = "3" * 64
D4 = "4" * 64


def happy() -> PR224CutoverEvidence:
    return PR224CutoverEvidence(
        release_id="release/pr224/sandbox-qualified",
        release_set=OciReleaseSet(
            runtime_image_digest=D1,
            signer_image_digest=D2,
            sbom_digest=D3,
            provenance_digest=D4,
            non_root_uid=10001,
            read_only_rootfs=True,
        ),
        network=NetworkIsolationEvidence(
            runtime_direct_internet_allowed=False,
            signer_shares_runtime_network=False,
            signer_shares_runtime_mounts=False,
            signer_shares_runtime_user=False,
            allowlisted_egress_gateway_enforced=True,
        ),
        secrets=SecretFilesystemEvidence(
            example_secrets_present=False,
            plaintext_keys_present=False,
            shared_tmp_state_present=False,
            secret_rotation_requires_rebuild=False,
        ),
        sandbox=SandboxPolicyEvidence(
            seccomp_validated_by_trace=True,
            apparmor_validated_by_trace=True,
            sqlite_wal_trace_passed=True,
            archive_trace_passed=True,
            deny_tests_passed=True,
        ),
        operations=OperationsPlaneEvidence(
            unified_management_api=True,
            readiness_includes_freshness=True,
            readiness_blocks_empty_runtime=True,
            readiness_blocks_dead_worker=True,
            shutdown_budget_ms=30000,
            orphan_tasks_detected=False,
        ),
        drills=DrillEvidence(
            deployed_state_validator_materialized=True,
            slo_drills_materialized=True,
            backup_restore_rpo_seconds=60,
            backup_restore_rto_seconds=300,
            rollback_rehearsed=True,
        ),
        cutover=CutoverEvidence(
            accepted_pr219_to_pr223=True,
            tiny_canary_autostops=True,
            unrestricted_live_enabled=False,
        ),
    )


def test_pr224_accepts_reviewable_cutover_boundary() -> None:
    report = evaluate_pr224_cutover(happy())

    assert report.ready is True
    assert report.state is PR224CutoverState.READY_FOR_PRODUCTION_CUTOVER_REVIEW
    assert report.violations == ()
    assert report.to_dict()["safety_boundary"] == {
        "live_execution_allowed": False,
        "signer_allowed": False,
        "sender_allowed": False,
    }


def test_pr224_rejects_direct_runtime_internet_or_missing_gateway() -> None:
    evidence = happy()
    evidence = PR224CutoverEvidence(
        release_id=evidence.release_id,
        release_set=evidence.release_set,
        network=NetworkIsolationEvidence(
            runtime_direct_internet_allowed=True,
            signer_shares_runtime_network=False,
            signer_shares_runtime_mounts=False,
            signer_shares_runtime_user=False,
            allowlisted_egress_gateway_enforced=False,
        ),
        secrets=evidence.secrets,
        sandbox=evidence.sandbox,
        operations=evidence.operations,
        drills=evidence.drills,
        cutover=evidence.cutover,
    )

    report = evaluate_pr224_cutover(evidence)
    assert report.ready is False
    assert [v.code for v in report.violations] == [
        "missing_allowlisted_egress_gateway",
        "runtime_direct_internet_allowed",
    ]


def test_pr224_rejects_signer_namespace_sharing() -> None:
    evidence = happy()
    evidence = PR224CutoverEvidence(
        release_id=evidence.release_id,
        release_set=evidence.release_set,
        network=NetworkIsolationEvidence(
            runtime_direct_internet_allowed=False,
            signer_shares_runtime_network=True,
            signer_shares_runtime_mounts=True,
            signer_shares_runtime_user=True,
            allowlisted_egress_gateway_enforced=True,
        ),
        secrets=evidence.secrets,
        sandbox=evidence.sandbox,
        operations=evidence.operations,
        drills=evidence.drills,
        cutover=evidence.cutover,
    )

    report = evaluate_pr224_cutover(evidence)
    assert {v.code for v in report.violations} == {
        "signer_shares_runtime_mounts",
        "signer_shares_runtime_network",
        "signer_shares_runtime_user",
    }


def test_pr224_rejects_secret_and_tmp_smells() -> None:
    evidence = happy()
    evidence = PR224CutoverEvidence(
        release_id=evidence.release_id,
        release_set=evidence.release_set,
        network=evidence.network,
        secrets=SecretFilesystemEvidence(
            example_secrets_present=True,
            plaintext_keys_present=True,
            shared_tmp_state_present=True,
            secret_rotation_requires_rebuild=True,
        ),
        sandbox=evidence.sandbox,
        operations=evidence.operations,
        drills=evidence.drills,
        cutover=evidence.cutover,
    )

    report = evaluate_pr224_cutover(evidence)
    assert {v.code for v in report.violations} == {
        "example_secrets_present",
        "plaintext_keys_present",
        "rotation_requires_rebuild",
        "shared_tmp_state_present",
    }


def test_pr224_rejects_unproven_sandbox() -> None:
    evidence = happy()
    evidence = PR224CutoverEvidence(
        release_id=evidence.release_id,
        release_set=evidence.release_set,
        network=evidence.network,
        secrets=evidence.secrets,
        sandbox=SandboxPolicyEvidence(
            seccomp_validated_by_trace=False,
            apparmor_validated_by_trace=False,
            sqlite_wal_trace_passed=False,
            archive_trace_passed=False,
            deny_tests_passed=False,
        ),
        operations=evidence.operations,
        drills=evidence.drills,
        cutover=evidence.cutover,
    )

    report = evaluate_pr224_cutover(evidence)
    assert {v.code for v in report.violations} == {
        "apparmor_not_trace_validated",
        "archive_trace_missing",
        "deny_tests_missing",
        "seccomp_not_trace_validated",
        "sqlite_wal_trace_missing",
    }


def test_pr224_rejects_readiness_and_shutdown_gaps() -> None:
    evidence = happy()
    evidence = PR224CutoverEvidence(
        release_id=evidence.release_id,
        release_set=evidence.release_set,
        network=evidence.network,
        secrets=evidence.secrets,
        sandbox=evidence.sandbox,
        operations=OperationsPlaneEvidence(
            unified_management_api=False,
            readiness_includes_freshness=False,
            readiness_blocks_empty_runtime=False,
            readiness_blocks_dead_worker=False,
            shutdown_budget_ms=1000,
            orphan_tasks_detected=True,
        ),
        drills=evidence.drills,
        cutover=evidence.cutover,
    )

    report = evaluate_pr224_cutover(evidence)
    assert {v.code for v in report.violations} == {
        "multiple_management_apis",
        "orphan_tasks_detected",
        "readiness_allows_dead_worker",
        "readiness_allows_empty_runtime",
        "readiness_missing_freshness",
    }


def test_pr224_rejects_missing_drills_and_validator() -> None:
    evidence = happy()
    evidence = PR224CutoverEvidence(
        release_id=evidence.release_id,
        release_set=evidence.release_set,
        network=evidence.network,
        secrets=evidence.secrets,
        sandbox=evidence.sandbox,
        operations=evidence.operations,
        drills=DrillEvidence(
            deployed_state_validator_materialized=False,
            slo_drills_materialized=False,
            backup_restore_rpo_seconds=0,
            backup_restore_rto_seconds=0,
            rollback_rehearsed=False,
        ),
        cutover=evidence.cutover,
    )

    report = evaluate_pr224_cutover(evidence)
    assert {v.code for v in report.violations} == {
        "missing_deployed_state_validator",
        "missing_slo_drills",
        "rollback_not_rehearsed",
    }


def test_pr224_rejects_unaccepted_upstream_or_unbounded_live() -> None:
    evidence = happy()
    evidence = PR224CutoverEvidence(
        release_id=evidence.release_id,
        release_set=evidence.release_set,
        network=evidence.network,
        secrets=evidence.secrets,
        sandbox=evidence.sandbox,
        operations=evidence.operations,
        drills=evidence.drills,
        cutover=CutoverEvidence(
            accepted_pr219_to_pr223=False,
            tiny_canary_autostops=False,
            unrestricted_live_enabled=True,
        ),
    )

    report = evaluate_pr224_cutover(evidence)
    assert {v.code for v in report.violations} == {
        "tiny_canary_missing_autostop",
        "unrestricted_live_enabled",
        "upstream_gates_unaccepted",
    }


def test_pr224_hash_is_deterministic() -> None:
    left = evaluate_pr224_cutover(happy())
    right = evaluate_pr224_cutover(happy())
    assert left.evidence_hash == right.evidence_hash


def test_pr224_validates_release_and_shutdown_inputs() -> None:
    with pytest.raises(ValueError):
        OciReleaseSet(
            runtime_image_digest="bad",
            signer_image_digest=D2,
            sbom_digest=D3,
            provenance_digest=D4,
            non_root_uid=10001,
            read_only_rootfs=True,
        )
    with pytest.raises(ValueError):
        OperationsPlaneEvidence(
            unified_management_api=True,
            readiness_includes_freshness=True,
            readiness_blocks_empty_runtime=True,
            readiness_blocks_dead_worker=True,
            shutdown_budget_ms=0,
            orphan_tasks_detected=False,
        )
