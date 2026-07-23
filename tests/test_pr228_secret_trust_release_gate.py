from __future__ import annotations

from dataclasses import asdict, replace

from src.pr228_secret_trust_release_gate import (
    AtomicSecretLifecycleEvidence,
    CrashSafePublicationEvidence,
    EvidenceRef,
    ManagementReadinessEvidence,
    PR228Evidence,
    PR228State,
    PR228_FINDINGS,
    RetentionReleaseEvidence,
    SCHEMA_VERSION,
    SafeFileAcquisitionEvidence,
    SecretHandlingEvidence,
    SecretRootPolicyEvidence,
    TrustAnchorEvidence,
    evaluate_pr228_secret_trust_release_gate,
)


def _sha(seed: str) -> str:
    return (seed * 64)[:64]


def valid_evidence() -> PR228Evidence:
    refs = tuple(
        EvidenceRef(
            label=f"artifact-{idx}",
            sha256=_sha(format(idx + 1, "x")),
            path=f"artifacts/pr228/workstream-{idx}.json",
        )
        for idx in range(8)
    )
    return PR228Evidence(
        schema_version=SCHEMA_VERSION,
        covered_findings=PR228_FINDINGS,
        evidence_refs=refs,
        secret_roots=SecretRootPolicyEvidence(
            empty_registry_denies_all_file_secrets=True,
            only_explicit_providers_and_roots_allowed=True,
            root_policy_binds_owner_mode_device_inode=True,
            owner_only_absolute_path_fallback_denied=True,
            provider_registry_generation_digest=_sha("a"),
            rollback_preserves_revocations=True,
        ),
        lifecycle=AtomicSecretLifecycleEvidence(
            reveal_revoke_max_uses_lease_audit_transactional=True,
            max_uses_one_concurrent_reveal_single_success=True,
            revoke_linearized_with_reveal=True,
            restart_preserves_revoke_and_use_count=True,
            lease_uses_trusted_time_not_wall_clock=True,
            audit_record_committed_with_reveal_decision=True,
            unknown_or_expired_lease_denied=True,
        ),
        safe_file=SafeFileAcquisitionEvidence(
            openat_or_single_open_no_follow=True,
            owner_and_mode_verified=True,
            stable_inode_size_mtime_digest_before_after_read=True,
            byte_limit_enforced=True,
            no_check_then_open_path_reuse=True,
            symlink_swap_detected=True,
            content_swap_detected=True,
            version_derived_from_exact_bytes=True,
        ),
        handling=SecretHandlingEvidence(
            no_immutable_string_reveal=True,
            scoped_handle_or_mutable_buffer_api=True,
            best_effort_zeroization=True,
            secret_bytes_absent_from_logs_status_evidence=True,
            caller_cannot_set_secret_version=True,
            persistent_credential_lifecycle_registry=True,
            credential_records_immutable_or_cas_guarded=True,
            registry_has_concurrency_discipline=True,
        ),
        trust_anchor=TrustAnchorEvidence(
            mac_or_signing_key_outside_runtime_state_dir=True,
            runtime_cannot_generate_own_state_trust_root=True,
            external_provenance_digest=_sha("b"),
            rotation_policy_materialized=True,
            revocation_policy_materialized=True,
            generation_continuity_independently_verifiable=True,
        ),
        management=ManagementReadinessEvidence(
            signed_state_one_strict_nested_schema=True,
            malformed_nested_state_blocked=True,
            future_generation_blocked=True,
            active_signed_state_readers_unified_type_semantics=True,
            authenticated_proxy_identity_verified_not_boolean=True,
            bearer_auth_rate_limit_lockout_audit=True,
            liveness_derived_from_supervisor_truth=True,
            readiness_hash_covers_nested_schema=True,
            public_liveness_cannot_hardcode_ok=True,
        ),
        publication=CrashSafePublicationEvidence(
            temp_write_fsync_file_atomic_rename_fsync_dir=True,
            fsync_file_failure_blocks_publication=True,
            fsync_directory_failure_blocks_publication=True,
            permission_failure_blocks_readiness=True,
            crash_matrix_proves_previous_or_new_generation_only=True,
            torn_state_never_visible=True,
        ),
        retention_release=RetentionReleaseEvidence(
            completed_outbox_purge_requires_worm_receipt=True,
            worm_receipt_binds_payload_digest=True,
            retention_cutoff_validated_against_trusted_time_and_policy=True,
            retention_ledger_immutable_and_identity_complete=True,
            lifecycle_integrity_checks_materialized_attempt_projection=True,
            release_identity_binds_installed_wheel_image_config_trust_bundle=True,
            source_tree_only_release_identity_rejected=True,
            rollback_switches_trust_config_state_generation_atomically=True,
        ),
    )


def _codes(report) -> set[str]:
    return {blocker.code for blocker in report.blockers}


def test_valid_evidence_allows_only_review_not_reveal_or_release():
    report = evaluate_pr228_secret_trust_release_gate(valid_evidence())

    assert report.state is PR228State.READY_FOR_SECRET_TRUST_REVIEW
    assert report.secret_trust_review_allowed is True
    assert report.secret_reveal_allowed is False
    assert report.management_ready_allowed is False
    assert report.release_ready_allowed is False
    assert report.operational_paper_ready_allowed is False
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert len(report.evidence_hash) == 64


def test_missing_finding_blocks_review():
    evidence = replace(valid_evidence(), covered_findings=PR228_FINDINGS[:-1])

    report = evaluate_pr228_secret_trust_release_gate(evidence)

    assert "FINDING_COVERAGE_INCOMPLETE" in _codes(report)
    assert report.secret_trust_review_allowed is False


def test_bad_or_secret_locator_evidence_ref_blocks_review():
    refs = (
        EvidenceRef(
            label="artifact-0",
            sha256="0" * 64,
            path="artifacts/pr228/secret-token.json",
        ),
    )
    evidence = replace(valid_evidence(), evidence_refs=refs)

    report = evaluate_pr228_secret_trust_release_gate(evidence)

    codes = _codes(report)
    assert "MATERIALIZED_EVIDENCE_INCOMPLETE" in codes
    assert "INVALID_EVIDENCE_DIGEST" in codes
    assert "EVIDENCE_PATH_MAY_DISCLOSE_SECRET_LOCATOR" in codes


def test_empty_approved_roots_must_deny_all_file_secrets():
    root = replace(
        valid_evidence().secret_roots,
        empty_registry_denies_all_file_secrets=False,
    )

    report = evaluate_pr228_secret_trust_release_gate(
        replace(valid_evidence(), secret_roots=root)
    )

    assert "SECRET_ROOT_POLICY_INCOMPLETE" in _codes(report)


def test_concurrent_max_uses_and_revoke_must_be_linearized_and_restart_safe():
    lifecycle = replace(
        valid_evidence().lifecycle,
        max_uses_one_concurrent_reveal_single_success=False,
        revoke_linearized_with_reveal=False,
        restart_preserves_revoke_and_use_count=False,
    )

    report = evaluate_pr228_secret_trust_release_gate(
        replace(valid_evidence(), lifecycle=lifecycle)
    )

    assert "SECRET_LIFECYCLE_NOT_LINEARIZED" in _codes(report)


def test_safe_file_acquisition_rejects_check_then_open_and_swaps():
    safe_file = replace(
        valid_evidence().safe_file,
        openat_or_single_open_no_follow=False,
        no_check_then_open_path_reuse=False,
        symlink_swap_detected=False,
        content_swap_detected=False,
    )

    report = evaluate_pr228_secret_trust_release_gate(
        replace(valid_evidence(), safe_file=safe_file)
    )

    assert "SAFE_FILE_ACQUISITION_INCOMPLETE" in _codes(report)


def test_secret_handling_blocks_immutable_string_and_manual_version_escape():
    handling = replace(
        valid_evidence().handling,
        no_immutable_string_reveal=False,
        caller_cannot_set_secret_version=False,
        secret_bytes_absent_from_logs_status_evidence=False,
    )

    report = evaluate_pr228_secret_trust_release_gate(
        replace(valid_evidence(), handling=handling)
    )

    assert "SECRET_HANDLING_ESCAPES_CONTROL" in _codes(report)


def test_runtime_self_generated_trust_root_is_blocked():
    trust = replace(
        valid_evidence().trust_anchor,
        runtime_cannot_generate_own_state_trust_root=False,
        mac_or_signing_key_outside_runtime_state_dir=False,
    )

    report = evaluate_pr228_secret_trust_release_gate(
        replace(valid_evidence(), trust_anchor=trust)
    )

    assert "STATE_TRUST_ANCHOR_NOT_INDEPENDENT" in _codes(report)


def test_management_readiness_rejects_boolean_proxy_and_hardcoded_liveness():
    management = replace(
        valid_evidence().management,
        authenticated_proxy_identity_verified_not_boolean=False,
        liveness_derived_from_supervisor_truth=False,
        public_liveness_cannot_hardcode_ok=False,
    )

    report = evaluate_pr228_secret_trust_release_gate(
        replace(valid_evidence(), management=management)
    )

    assert "MANAGEMENT_READINESS_CONTRACT_INCOMPLETE" in _codes(report)


def test_publication_fsync_failures_and_torn_state_must_fail_closed():
    publication = replace(
        valid_evidence().publication,
        fsync_file_failure_blocks_publication=False,
        fsync_directory_failure_blocks_publication=False,
        torn_state_never_visible=False,
    )

    report = evaluate_pr228_secret_trust_release_gate(
        replace(valid_evidence(), publication=publication)
    )

    assert "CRASH_SAFE_PUBLICATION_INCOMPLETE" in _codes(report)


def test_retention_requires_worm_receipt_and_exact_release_identity():
    retention = replace(
        valid_evidence().retention_release,
        completed_outbox_purge_requires_worm_receipt=False,
        release_identity_binds_installed_wheel_image_config_trust_bundle=False,
        source_tree_only_release_identity_rejected=False,
    )

    report = evaluate_pr228_secret_trust_release_gate(
        replace(valid_evidence(), retention_release=retention)
    )

    assert "RETENTION_RELEASE_IDENTITY_INCOMPLETE" in _codes(report)


def test_runtime_capability_requests_are_denied():
    evidence = replace(
        valid_evidence(),
        secret_reveal_requested=True,
        management_ready_requested=True,
        release_ready_requested=True,
        live_execution_requested=True,
        signer_requested=True,
        sender_requested=True,
    )

    report = evaluate_pr228_secret_trust_release_gate(evidence)

    assert "UNSAFE_CAPABILITY_REQUESTED" in _codes(report)
    assert report.secret_trust_review_allowed is False


def test_mapping_input_is_supported_for_artifact_replay():
    evidence = valid_evidence()
    mapping = {
        "schema_version": evidence.schema_version,
        "covered_findings": list(evidence.covered_findings),
        "evidence_refs": [ref.to_dict() for ref in evidence.evidence_refs],
        "secret_roots": asdict(evidence.secret_roots),
        "lifecycle": asdict(evidence.lifecycle),
        "safe_file": asdict(evidence.safe_file),
        "handling": asdict(evidence.handling),
        "trust_anchor": asdict(evidence.trust_anchor),
        "management": asdict(evidence.management),
        "publication": asdict(evidence.publication),
        "retention_release": asdict(evidence.retention_release),
    }

    report = evaluate_pr228_secret_trust_release_gate(mapping)

    assert report.state is PR228State.READY_FOR_SECRET_TRUST_REVIEW
