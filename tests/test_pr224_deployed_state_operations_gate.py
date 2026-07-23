from __future__ import annotations

import dataclasses

import pytest

from src.pr224_deployed_state_operations_gate import (
    CutoverGovernanceEvidence,
    DrillEvidence,
    NetworkEgressEvidence,
    PR224DeployedStateEvidence,
    PR224V2State,
    ReadinessManagementEvidence,
    ReleaseIdentityEvidence,
    REQUIRED_FINDINGS,
    REQUIRED_UPSTREAM_PRS,
    SandboxTraceEvidence,
    blockers_by_code,
    evaluate_pr224_deployed_state,
)


def digest(seed: str) -> str:
    return (seed.encode().hex() * 64)[:64]


def valid_evidence() -> PR224DeployedStateEvidence:
    return PR224DeployedStateEvidence(
        finding_coverage=REQUIRED_FINDINGS,
        release=ReleaseIdentityEvidence(
            release_id="release/pr224-target-host-v2",
            runtime_image_digest=digest("a"),
            signer_image_digest=digest("b"),
            source_manifest_digest=digest("c"),
            wheel_digest=digest("d"),
            config_bundle_digest=digest("e"),
            provider_policy_digest=digest("1"),
            sbom_digest=digest("2"),
            provenance_digest=digest("3"),
            validator_binary_digest=digest("4"),
            runtime_user_uid=10001,
            signer_user_uid=10002,
        ),
        network=NetworkEgressEvidence(
            deny_by_default_policy_loaded=True,
            runtime_direct_internet_denied=True,
            signer_network_namespace_separate=True,
            signer_egress_denied=True,
            egress_gateway_only=True,
            destinations_exactly_allowlisted=True,
            dns_policy_bound_to_provider_generation=True,
            private_link_local_loopback_denied=True,
            redirect_escape_denied=True,
            denied_probe_digest=digest("5"),
        ),
        sandbox=SandboxTraceEvidence(
            seccomp_profile_loaded=True,
            apparmor_profile_loaded=True,
            read_only_rootfs=True,
            no_new_privileges=True,
            minimal_capabilities=True,
            sqlite_wal_fsync_trace_passed=True,
            archive_fsync_trace_passed=True,
            forbidden_syscalls_denied=True,
            forbidden_filesystem_paths_denied=True,
            writable_runtime_paths=("/var/lib/flashloan", "/var/log/flashloan"),
            trace_digest=digest("6"),
        ),
        readiness=ReadinessManagementEvidence(
            authenticated_management_api=True,
            signed_readiness_snapshot=True,
            readiness_schema_digest=digest("7"),
            snapshot_bound_to_release_and_boot_generation=True,
            empty_runtime_ready_false=True,
            blocked_runtime_ready_false=True,
            dead_worker_ready_false=True,
            stale_provider_ready_false=True,
            signer_unavailable_ready_false=True,
            recovery_blocked_ready_false=True,
            current_freshness_age_ms=100,
            freshness_budget_ms=1_000,
        ),
        drills=DrillEvidence(
            deployed_state_validator_digest=digest("8"),
            slo_drill_report_digest=digest("9"),
            shutdown_drill_report_digest=digest("a1"),
            backup_restore_report_digest=digest("b1"),
            rollback_report_digest=digest("c1"),
            rpo_seconds_observed=2,
            rpo_seconds_budget=10,
            rto_seconds_observed=10,
            rto_seconds_budget=60,
            orphan_tasks_zero=True,
            orphan_sockets_zero=True,
            split_brain_prevented=True,
            materialized_outputs_not_booleans=True,
        ),
        cutover=CutoverGovernanceEvidence(
            accepted_upstream_prs=REQUIRED_UPSTREAM_PRS,
            signed_cutover_bundle_digest=digest("d1"),
            independent_approval_quorum_digest=digest("e1"),
            tiny_canary_cap_lamports=5_000,
            tiny_canary_autostop_on_budget_slo_or_finality=True,
            canary_requires_finalized_settlement=True,
            rollback_keeps_dispatched_reconciliation=True,
            signer_sender_default_off_until_bundle=True,
            unrestricted_live_enabled=False,
            live_execution_requested=False,
            signer_requested=False,
            sender_requested=False,
        ),
    )


def report_codes(evidence: PR224DeployedStateEvidence) -> set[str]:
    return set(blockers_by_code(evaluate_pr224_deployed_state(evidence)))


def test_valid_deployed_state_is_ready_but_live_sender_signer_disabled() -> None:
    report = evaluate_pr224_deployed_state(valid_evidence())

    assert report.state is PR224V2State.READY_FOR_TARGET_HOST_CUTOVER_REVIEW
    assert report.ready_for_target_host_cutover_review is True
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.to_dict()["violation_count"] == 0


def test_missing_finding_blocks_review() -> None:
    evidence = dataclasses.replace(valid_evidence(), finding_coverage=REQUIRED_FINDINGS[:-1])

    assert "PR224_MISSING_FINDING_COVERAGE" in report_codes(evidence)


def test_runtime_and_signer_must_be_distinct_release_units() -> None:
    evidence = valid_evidence()
    release = dataclasses.replace(
        evidence.release,
        signer_image_digest=evidence.release.runtime_image_digest,
    )

    assert "PR224_RELEASE_COLLAPSES_RUNTIME_SIGNER" in report_codes(
        dataclasses.replace(evidence, release=release)
    )


def test_network_policy_must_deny_direct_egress_and_signer_egress() -> None:
    evidence = valid_evidence()
    network = dataclasses.replace(
        evidence.network,
        runtime_direct_internet_denied=False,
        signer_egress_denied=False,
        redirect_escape_denied=False,
    )

    codes = report_codes(dataclasses.replace(evidence, network=network))
    assert "PR224_NETWORK_EGRESS_INCOMPLETE" in codes


def test_sandbox_requires_measured_seccomp_apparmor_wal_and_deny_traces() -> None:
    evidence = valid_evidence()
    sandbox = dataclasses.replace(
        evidence.sandbox,
        seccomp_profile_loaded=False,
        apparmor_profile_loaded=False,
        sqlite_wal_fsync_trace_passed=False,
        writable_runtime_paths=("/tmp",),
    )

    codes = report_codes(dataclasses.replace(evidence, sandbox=sandbox))
    assert "PR224_SANDBOX_TRACE_INCOMPLETE" in codes
    assert "PR224_SHARED_TMP_WRITABLE" in codes


def test_readiness_cannot_be_green_for_empty_dead_or_stale_runtime() -> None:
    evidence = valid_evidence()
    readiness = dataclasses.replace(
        evidence.readiness,
        empty_runtime_ready_false=False,
        dead_worker_ready_false=False,
        current_freshness_age_ms=2_000,
    )

    codes = report_codes(dataclasses.replace(evidence, readiness=readiness))
    assert "PR224_READINESS_ANTI_FALSE_GREEN_INCOMPLETE" in codes
    assert "PR224_READINESS_STALE" in codes


def test_drills_must_meet_rpo_rto_and_materialized_output_requirements() -> None:
    evidence = valid_evidence()
    drills = dataclasses.replace(
        evidence.drills,
        rpo_seconds_observed=99,
        rto_seconds_observed=99,
        orphan_tasks_zero=False,
        materialized_outputs_not_booleans=False,
    )

    codes = report_codes(dataclasses.replace(evidence, drills=drills))
    assert "PR224_RPO_BUDGET_EXCEEDED" in codes
    assert "PR224_RTO_BUDGET_EXCEEDED" in codes
    assert "PR224_DRILL_OUTPUT_INCOMPLETE" in codes


def test_upstream_gates_must_be_exact_pr219_through_pr223() -> None:
    evidence = valid_evidence()
    cutover = dataclasses.replace(evidence.cutover, accepted_upstream_prs=("PR-219", "PR-220"))

    assert "PR224_UPSTREAM_GATES_INCOMPLETE" in report_codes(
        dataclasses.replace(evidence, cutover=cutover)
    )


def test_unrestricted_live_or_requested_surfaces_fail_closed() -> None:
    evidence = valid_evidence()
    cutover = dataclasses.replace(
        evidence.cutover,
        unrestricted_live_enabled=True,
        live_execution_requested=True,
        signer_requested=True,
        sender_requested=True,
    )

    codes = report_codes(dataclasses.replace(evidence, cutover=cutover))
    assert "PR224_UNRESTRICTED_LIVE_ENABLED" in codes
    assert "PR224_LIVE_EXECUTION_REQUESTED" in codes
    assert "PR224_SIGNER_REQUESTED" in codes
    assert "PR224_SENDER_REQUESTED" in codes


def test_placeholder_digest_is_rejected_at_construction() -> None:
    evidence = valid_evidence()

    with pytest.raises(ValueError, match="non-placeholder lowercase sha256"):
        dataclasses.replace(evidence.release, sbom_digest="0" * 64)
