from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from src.mpr09_live_deployment_policy_gate import (
    CredentialLifecycleEvidence,
    DeploymentSandboxEvidence,
    LiveRuntimeConfigEvidence,
    MPR09Blocker,
    MPR09EvidenceError,
    MPR09LiveDeploymentEvidence,
    SCHEMA_VERSION,
    evaluate_mpr09_live_deployment,
)


def h(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def complete_evidence() -> MPR09LiveDeploymentEvidence:
    config = LiveRuntimeConfigEvidence(
        runtime_mode="live",
        authoritative_commitment="finalized",
        discovery_commitment="processed",
        rpc_http_url="https://rpc.example.invalid",
        rpc_ws_url="wss://rpc.example.invalid",
        cluster_name="mainnet-beta",
        cluster_genesis_sha256=h("mainnet genesis"),
        cluster_registry_sha256=h("cluster registry"),
        protocol_registry_sha256=h("protocol registry"),
        marginfi_program_id="marginfi-mainnet-v1",
        marginfi_program_from_signed_registry=True,
    )
    lifecycle = CredentialLifecycleEvidence(
        credential_registry_sha256=h("credential registry"),
        credential_generation_sha256=h("credential generation"),
        secret_mount_schema_sha256=h("secret mount schema"),
        secret_values_redacted=True,
        generation_changes_on_rotation=True,
        revocation_durable_cross_process=True,
        restart_cannot_resurrect_revoked_generation=True,
        leases_use_monotonic_and_trusted_utc=True,
        boot_generation_bound_to_lease=True,
        max_use_consumption_serialized=True,
        raw_secret_strings_exposed_to_runtime=False,
        approved_file_roots_required=True,
        arbitrary_owner_file_read_allowed=False,
        content_bound_generation_ids=True,
    )
    sandbox = DeploymentSandboxEvidence(
        deployment_policy_sha256=h("deployment policy"),
        typed_runtime_mode_configured=True,
        legacy_flags_only=False,
        runtime_env_secret_mounted=True,
        application_reads_secret_mount=True,
        raw_secret_env_vars_present=False,
        egress_policy_enforced_by_runtime_topology=True,
        denied_destination_probe_passed=True,
        approved_destination_probe_passed=True,
        arbitrary_bridge_network_available=False,
        canonical_state_paths_on_persistent_volumes=True,
        non_root_volume_write_restart_probe_passed=True,
        apparmor_profile_hash_sha256=h("apparmor profile"),
        apparmor_profile_loaded=True,
        readiness_uses_workload_state=True,
        orchestrator_uses_ready_not_health=True,
        liveness_and_readiness_separated=True,
    )
    return MPR09LiveDeploymentEvidence(
        mpr08_completion_ledger_accepted=True,
        mpr08_completion_ledger_sha256=h("mpr08 ledger"),
        live_config=config,
        credential_lifecycle=lifecycle,
        deployment_sandbox=sandbox,
    )


def blockers(report) -> set[str]:
    return set(report.blockers)


def test_complete_evidence_is_ready_but_does_not_enable_live_or_network() -> None:
    report = evaluate_mpr09_live_deployment(complete_evidence())

    assert report.schema_version == SCHEMA_VERSION
    assert report.ready
    assert report.blockers == ()
    assert report.live_execution_allowed is False
    assert report.signer_access_allowed is False
    assert report.provider_network_allowed is False
    assert len(report.evidence_hash) == 64


def test_mpr08_completion_ledger_is_required() -> None:
    evidence = replace(complete_evidence(), mpr08_completion_ledger_accepted=False)

    report = evaluate_mpr09_live_deployment(evidence)

    assert not report.ready
    assert MPR09Blocker.MPR08_LEDGER_NOT_ACCEPTED.value in blockers(report)


def test_processed_or_confirmed_live_authority_is_blocked() -> None:
    evidence = complete_evidence()
    config = replace(evidence.live_config, authoritative_commitment="processed")

    report = evaluate_mpr09_live_deployment(replace(evidence, live_config=config))

    assert not report.ready
    assert MPR09Blocker.LIVE_AUTHORITY_NOT_FINALIZED.value in blockers(report)


def test_plaintext_rpc_transports_are_blocked() -> None:
    evidence = complete_evidence()
    config = replace(
        evidence.live_config,
        rpc_http_url="http://rpc.example.invalid",
        rpc_ws_url="ws://rpc.example.invalid",
    )

    report = evaluate_mpr09_live_deployment(replace(evidence, live_config=config))

    assert not report.ready
    assert MPR09Blocker.PLAINTEXT_RPC_TRANSPORT.value in blockers(report)


def test_unknown_cluster_and_self_authorized_program_are_blocked() -> None:
    evidence = complete_evidence()
    config = replace(
        evidence.live_config,
        cluster_name="mainnet-btea",
        marginfi_program_from_signed_registry=False,
        config_can_extend_program_allowlist=True,
    )

    report = evaluate_mpr09_live_deployment(replace(evidence, live_config=config))

    assert not report.ready
    assert MPR09Blocker.UNKNOWN_CLUSTER_OR_GENESIS.value in blockers(report)
    assert MPR09Blocker.SELF_AUTHORIZED_PROTOCOL_PROGRAM.value in blockers(report)


def test_secret_rotation_revocation_and_fail_open_roots_are_blocked() -> None:
    evidence = complete_evidence()
    lifecycle = replace(
        evidence.credential_lifecycle,
        generation_changes_on_rotation=False,
        content_bound_generation_ids=False,
        revocation_durable_cross_process=False,
        approved_file_roots_required=False,
        arbitrary_owner_file_read_allowed=True,
    )

    report = evaluate_mpr09_live_deployment(
        replace(evidence, credential_lifecycle=lifecycle)
    )

    assert not report.ready
    assert MPR09Blocker.SECRET_GENERATION_NOT_CONTENT_BOUND.value in blockers(report)
    assert MPR09Blocker.SECRET_ROOT_POLICY_FAIL_OPEN.value in blockers(report)
    assert MPR09Blocker.CREDENTIAL_AUTHORITY_NOT_DURABLE.value in blockers(report)


def test_secret_leases_and_consumption_must_be_safe() -> None:
    evidence = complete_evidence()
    lifecycle = replace(
        evidence.credential_lifecycle,
        leases_use_monotonic_and_trusted_utc=False,
        boot_generation_bound_to_lease=False,
        max_use_consumption_serialized=False,
        raw_secret_strings_exposed_to_runtime=True,
    )

    report = evaluate_mpr09_live_deployment(
        replace(evidence, credential_lifecycle=lifecycle)
    )

    assert not report.ready
    assert MPR09Blocker.LEASE_TIME_NOT_DUAL_DOMAIN.value in blockers(report)
    assert MPR09Blocker.SECRET_CONSUMPTION_NOT_SERIALIZED.value in blockers(report)
    assert MPR09Blocker.SECRET_STRINGS_EXPOSED.value in blockers(report)


def test_secret_mount_and_typed_runtime_mode_are_required() -> None:
    evidence = complete_evidence()
    sandbox = replace(
        evidence.deployment_sandbox,
        application_reads_secret_mount=False,
        raw_secret_env_vars_present=True,
        typed_runtime_mode_configured=False,
        legacy_flags_only=True,
    )

    report = evaluate_mpr09_live_deployment(
        replace(evidence, deployment_sandbox=sandbox)
    )

    assert not report.ready
    assert MPR09Blocker.SECRET_MOUNT_NOT_CONSUMED.value in blockers(report)
    assert MPR09Blocker.LEGACY_FLAGS_WITHOUT_TYPED_MODE.value in blockers(report)


def test_enforceable_egress_and_durable_volumes_are_required() -> None:
    evidence = complete_evidence()
    sandbox = replace(
        evidence.deployment_sandbox,
        egress_policy_enforced_by_runtime_topology=False,
        arbitrary_bridge_network_available=True,
        canonical_state_paths_on_persistent_volumes=False,
        non_root_volume_write_restart_probe_passed=False,
    )

    report = evaluate_mpr09_live_deployment(
        replace(evidence, deployment_sandbox=sandbox)
    )

    assert not report.ready
    assert MPR09Blocker.EGRESS_NOT_ENFORCED.value in blockers(report)
    assert MPR09Blocker.DURABLE_VOLUME_NOT_PROVEN.value in blockers(report)


def test_apparmor_and_readiness_healthcheck_are_required() -> None:
    evidence = complete_evidence()
    sandbox = replace(
        evidence.deployment_sandbox,
        apparmor_profile_loaded=False,
        readiness_uses_workload_state=False,
        orchestrator_uses_ready_not_health=False,
    )

    report = evaluate_mpr09_live_deployment(
        replace(evidence, deployment_sandbox=sandbox)
    )

    assert not report.ready
    assert MPR09Blocker.SANDBOX_PROFILE_NOT_ATTESTED.value in blockers(report)
    assert MPR09Blocker.HEALTHCHECK_NOT_READINESS.value in blockers(report)


def test_reachable_live_signer_or_network_surface_is_blocked() -> None:
    evidence = replace(
        complete_evidence(),
        live_execution_reachable=True,
        signer_access_reachable=True,
        provider_network_calls_performed=True,
    )

    report = evaluate_mpr09_live_deployment(evidence)

    assert not report.ready
    assert MPR09Blocker.LIVE_OR_SIGNER_REACHABLE.value in blockers(report)


def test_placeholder_digests_and_bad_urls_are_rejected() -> None:
    with pytest.raises(MPR09EvidenceError, match="placeholder"):
        CredentialLifecycleEvidence(
            credential_registry_sha256="0" * 64,
            credential_generation_sha256=h("credential generation"),
            secret_mount_schema_sha256=h("secret mount schema"),
            secret_values_redacted=True,
            generation_changes_on_rotation=True,
            revocation_durable_cross_process=True,
            restart_cannot_resurrect_revoked_generation=True,
            leases_use_monotonic_and_trusted_utc=True,
            boot_generation_bound_to_lease=True,
            max_use_consumption_serialized=True,
            raw_secret_strings_exposed_to_runtime=False,
            approved_file_roots_required=True,
            arbitrary_owner_file_read_allowed=False,
            content_bound_generation_ids=True,
        )

    with pytest.raises(MPR09EvidenceError, match="absolute URL"):
        LiveRuntimeConfigEvidence(
            runtime_mode="live",
            authoritative_commitment="finalized",
            discovery_commitment="processed",
            rpc_http_url="not-a-url",
            rpc_ws_url="wss://rpc.example.invalid",
            cluster_name="mainnet-beta",
            cluster_genesis_sha256=h("genesis"),
            cluster_registry_sha256=h("registry"),
            protocol_registry_sha256=h("protocol"),
            marginfi_program_id="marginfi-mainnet-v1",
            marginfi_program_from_signed_registry=True,
        )


def test_report_json_is_stable() -> None:
    report = evaluate_mpr09_live_deployment(complete_evidence())
    payload = json.loads(report.to_json())

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["ready"] is True
    assert payload["blockers"] == []
