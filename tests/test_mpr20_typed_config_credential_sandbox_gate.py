from __future__ import annotations

import json
from dataclasses import replace

from src.mpr20_typed_config_credential_sandbox_gate import (
    MPR20Blocker,
    MPR18DependencyEvidence,
    MPR20Evidence,
    ChainProgramIdentityEvidence,
    CredentialLifecycleEvidence,
    DiagnosticRedactionEvidence,
    REQUIRED_FINDINGS,
    SandboxAttestationEvidence,
    TypedConfigurationEvidence,
    blockers_by_code,
    evaluate_mpr20_evidence,
    report_to_json,
)


GOOD_HASH = "a" * 64


def complete_evidence() -> MPR20Evidence:
    return MPR20Evidence(
        covered_findings=REQUIRED_FINDINGS,
        mpr18_dependency=MPR18DependencyEvidence(
            mpr18_accepted=True,
            installed_artifact_manifest_sha256=GOOD_HASH,
            release_set_generation_sha256=GOOD_HASH,
            installed_surface_trace_sha256=GOOD_HASH,
            signer_split_manifest_sha256=GOOD_HASH,
        ),
        typed_configuration=TypedConfigurationEvidence(
            config_schema_sha256=GOOD_HASH,
            policy_bundle_sha256=GOOD_HASH,
            signed_activation_sha256=GOOD_HASH,
            cli_container_signer_contract_same=True,
            immutable_config_snapshot=True,
            unknown_flashloan_env_blocked=True,
            unknown_cluster_blocked=True,
            incompatible_secret_scheme_blocked=True,
            duplicate_keys_nan_yaml_bombs_blocked=True,
            secure_no_follow_open=True,
            bounded_read_before_parse=True,
            canonical_path_policy_enforced=True,
            weak_http_rpc_blocked=True,
            weak_ws_transport_blocked=True,
            weak_commitment_blocked=True,
            runtime_env_contract_matches_compose=True,
        ),
        credential_lifecycle=CredentialLifecycleEvidence(
            secret_policy_sha256=GOOD_HASH,
            rotation_revocation_report_sha256=GOOD_HASH,
            docker_secret_contract_sha256=GOOD_HASH,
            network_runtime_has_signer_secret_access=False,
            signer_secret_resolved_only_in_signer_process=True,
            narrow_authenticated_ipc_required=True,
            empty_approved_roots_rejected=True,
            supported_backends_end_to_end_only=True,
            parse_only_keychain_contract_removed_or_implemented=True,
            secret_generation_content_bound=True,
            monotonic_secret_lease=True,
            maximum_use_cas_enforced=True,
            docker_secret_file_consumed=True,
            obsolete_variable_names_removed=True,
            raw_query_secret_forbidden_in_urls=True,
            raw_query_secret_forbidden_in_config_identity=True,
            revealed_secret_zeroization_boundary_documented=True,
        ),
        chain_program_identity=ChainProgramIdentityEvidence(
            chain_registry_sha256=GOOD_HASH,
            cluster_genesis_sha256=GOOD_HASH,
            program_registry_sha256=GOOD_HASH,
            commitment_policy_sha256=GOOD_HASH,
            https_wss_only=True,
            approved_finalized_or_rooted_commitment_only=True,
            unknown_cluster_rejected=True,
            configured_program_cannot_self_authorize=True,
            marginfi_program_bound_to_registry=True,
            token_programs_bound_to_registry=True,
            rpc_doctor_uses_hardened_transport=True,
            rpc_doctor_total_deadline=True,
            rpc_doctor_bounded_response=True,
            rpc_doctor_redacts_provider_errors=True,
        ),
        sandbox_attestation=SandboxAttestationEvidence(
            target_host_attestation_sha256=GOOD_HASH,
            apparmor_profile_sha256=GOOD_HASH,
            seccomp_profile_sha256=GOOD_HASH,
            egress_policy_sha256=GOOD_HASH,
            volume_policy_sha256=GOOD_HASH,
            target_host_attested=True,
            runtime_uid=10001,
            volumes_writable_by_runtime_uid=True,
            canonical_db_log_archive_paths_volume_bound=True,
            apparmor_loaded_on_target_host=True,
            seccomp_loaded_on_target_host=True,
            sqlite_wal_fsync_syscalls_allowed=True,
            denied_syscall_tests_passed=True,
            internal_network_only=True,
            explicit_proxy_or_firewall_enforced=True,
            destination_allowlist_enforced=True,
            arbitrary_egress_denied=True,
            signer_network_separated_from_runtime=True,
            signer_mounts_separated_from_runtime=True,
            signer_user_separated_from_runtime=True,
        ),
        diagnostic_redaction=DiagnosticRedactionEvidence(
            diagnostic_corpus_sha256=GOOD_HASH,
            crash_log_corpus_sha256=GOOD_HASH,
            redaction_policy_sha256=GOOD_HASH,
            diagnostics_bounded_by_value_and_type=True,
            provider_payloads_removed=True,
            url_query_removed=True,
            filesystem_paths_minimized=True,
            secret_prefixes_removed=True,
            crash_logs_redacted=True,
        ),
    )


def codes(evidence: MPR20Evidence) -> set[MPR20Blocker]:
    return set(blockers_by_code(evaluate_mpr20_evidence(evidence)))


def test_complete_evidence_ready_but_live_sender_signer_disabled() -> None:
    report = evaluate_mpr20_evidence(complete_evidence())

    assert report.blockers == ()
    assert report.startup_trust_boundary_ready is True
    assert report.target_host_sandbox_evidence_ready is True
    assert report.mpr21_mpr22_dependency_ready is True
    assert report.live_execution_allowed is False
    assert report.sender_allowed is False
    assert report.signer_allowed is False


def test_all_mpr20_findings_are_required_exactly_once() -> None:
    assert len(REQUIRED_FINDINGS) == 35
    assert REQUIRED_FINDINGS[0] == "F-281"
    assert REQUIRED_FINDINGS[-1] == "F-434"

    evidence = complete_evidence()
    mutated = replace(
        evidence,
        covered_findings=REQUIRED_FINDINGS[:-1] + ("F-999",),
    )

    assert MPR20Blocker.MISSING_FINDING_COVERAGE in codes(mutated)


def test_duplicate_finding_coverage_blocked() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        covered_findings=REQUIRED_FINDINGS + (REQUIRED_FINDINGS[0],),
    )

    assert MPR20Blocker.DUPLICATE_FINDING_COVERAGE in codes(mutated)


def test_mpr18_dependency_is_hard_gate() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        mpr18_dependency=replace(
            evidence.mpr18_dependency,
            mpr18_accepted=False,
        ),
    )

    assert MPR20Blocker.MPR18_NOT_ACCEPTED in codes(mutated)


def test_unknown_config_inputs_fail_closed() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        typed_configuration=replace(
            evidence.typed_configuration,
            unknown_flashloan_env_blocked=False,
            unknown_cluster_blocked=False,
        ),
    )

    assert MPR20Blocker.UNKNOWN_INPUT_NOT_BLOCKED in codes(mutated)


def test_unsafe_config_file_loading_blocked() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        typed_configuration=replace(
            evidence.typed_configuration,
            secure_no_follow_open=False,
            bounded_read_before_parse=False,
        ),
    )

    assert MPR20Blocker.CONFIG_PARSE_NOT_SAFE in codes(mutated)


def test_weak_rpc_transport_and_commitment_blocked() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        typed_configuration=replace(
            evidence.typed_configuration,
            weak_http_rpc_blocked=False,
            weak_commitment_blocked=False,
        ),
    )

    assert MPR20Blocker.LIVE_TRANSPORT_OR_COMMITMENT_PERMISSIVE in codes(mutated)


def test_network_runtime_signer_secret_access_blocked() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        credential_lifecycle=replace(
            evidence.credential_lifecycle,
            network_runtime_has_signer_secret_access=True,
        ),
    )

    assert MPR20Blocker.RUNTIME_CAN_ACCESS_SIGNER_SECRET in codes(mutated)


def test_parse_only_secret_backend_and_missing_docker_secret_blocked() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        credential_lifecycle=replace(
            evidence.credential_lifecycle,
            parse_only_keychain_contract_removed_or_implemented=False,
            docker_secret_file_consumed=False,
        ),
    )

    assert MPR20Blocker.SECRET_BACKEND_NOT_REAL in codes(mutated)


def test_secret_roots_generation_and_lease_are_fail_closed() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        credential_lifecycle=replace(
            evidence.credential_lifecycle,
            empty_approved_roots_rejected=False,
            secret_generation_content_bound=False,
            maximum_use_cas_enforced=False,
        ),
    )

    assert MPR20Blocker.SECRET_ROOT_OR_ROTATION_NOT_FAIL_CLOSED in codes(mutated)


def test_program_self_authorization_and_untrusted_chain_identity_blocked() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        chain_program_identity=replace(
            evidence.chain_program_identity,
            configured_program_cannot_self_authorize=False,
            marginfi_program_bound_to_registry=False,
        ),
    )

    result = codes(mutated)
    assert MPR20Blocker.PROGRAM_SELF_AUTHORIZATION in result
    assert MPR20Blocker.CHAIN_OR_PROGRAM_IDENTITY_UNTRUSTED in result


def test_startup_rpc_doctor_must_use_hardened_transport() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        chain_program_identity=replace(
            evidence.chain_program_identity,
            rpc_doctor_uses_hardened_transport=False,
            rpc_doctor_bounded_response=False,
        ),
    )

    assert MPR20Blocker.DOCTOR_BYPASSES_HARDENED_TRANSPORT in codes(mutated)


def test_target_host_sandbox_requires_uid_volumes_apparmor_seccomp_and_egress() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        sandbox_attestation=replace(
            evidence.sandbox_attestation,
            target_host_attested=False,
            runtime_uid=0,
            apparmor_loaded_on_target_host=False,
            arbitrary_egress_denied=False,
        ),
    )

    result = codes(mutated)
    assert MPR20Blocker.DEPLOYMENT_SANDBOX_NOT_ATTESTED in result
    assert MPR20Blocker.UID_OR_VOLUME_NOT_ENFORCED in result
    assert MPR20Blocker.APPARMOR_SECCOMP_NOT_ENFORCED in result
    assert MPR20Blocker.EGRESS_NOT_ENFORCED in result


def test_diagnostics_must_remove_provider_payload_url_query_paths_and_secret_prefixes() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        diagnostic_redaction=replace(
            evidence.diagnostic_redaction,
            provider_payloads_removed=False,
            url_query_removed=False,
            filesystem_paths_minimized=False,
            secret_prefixes_removed=False,
        ),
    )

    assert MPR20Blocker.DIAGNOSTICS_NOT_REDACTED in codes(mutated)


def test_placeholder_hashes_are_rejected() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        typed_configuration=replace(
            evidence.typed_configuration,
            config_schema_sha256="0" * 64,
            policy_bundle_sha256="f" * 64,
        ),
    )

    assert MPR20Blocker.BAD_CONFIG_HASH in codes(mutated)


def test_live_sender_or_signer_request_is_always_blocked() -> None:
    evidence = complete_evidence()
    mutated = replace(
        evidence,
        live_execution_requested=True,
        sender_requested=True,
        signer_requested=True,
    )

    report = evaluate_mpr20_evidence(mutated)

    assert MPR20Blocker.LIVE_OR_SENDER_OR_SIGNER_REACHABLE in blockers_by_code(report)
    assert report.live_execution_allowed is False
    assert report.sender_allowed is False
    assert report.signer_allowed is False


def test_report_json_is_stable_and_machine_readable() -> None:
    first = report_to_json(evaluate_mpr20_evidence(complete_evidence()))
    second = report_to_json(evaluate_mpr20_evidence(complete_evidence()))

    assert first == second
    payload = json.loads(first)
    assert payload["schema_version"] == "mpr20.typed-config-credential-sandbox-gate.v1"
    assert payload["state"] == "ready_for_target_host_evidence"
