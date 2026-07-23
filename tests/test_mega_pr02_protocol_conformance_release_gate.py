from __future__ import annotations

from dataclasses import replace

from src.mega_pr02_protocol_conformance_release_gate import (  # noqa: E402
    REQUIRED_IMPL_FINDINGS,
    REQUIRED_MONETARY_FUZZ_CASES,
    REQUIRED_PROTOCOLS,
    REQUIRED_PROVIDER_FAILURE_CASES,
    REQUIRED_SANDBOX_NEGATIVE_TESTS,
    REQUIRED_SECURITY_SCANNERS,
    EconomicsTruthEvidence,
    HermeticReleaseEvidence,
    MegaPR02Evidence,
    MegaPR02GateState,
    MessageSimulationEvidence,
    ProtocolConformanceEvidence,
    ProtocolContractEvidence,
    ProtocolDisposition,
    ProviderHttpTransportEvidence,
    SandboxReadinessEvidence,
    SecurityQualityEvidence,
    SoakQualificationEvidence,
    blockers_by_code,
    evaluate_mega_pr02_evidence,
)


HASH = "a" * 64


def _protocol(name: str) -> ProtocolContractEvidence:
    return ProtocolContractEvidence(
        protocol=name,
        disposition=ProtocolDisposition.ADMITTED,
        reviewed_contract_hash=HASH,
        contract_reviewed_at_unix=1_780_000_000,
        contract_expires_at_unix=1_790_000_000,
        credentialed_probe_passed=True,
        golden_fixture_hash=HASH,
        negative_fixture_hash=HASH,
        schema_hash=HASH,
        endpoint_or_program_identity_hash=HASH,
    )


def valid_evidence() -> MegaPR02Evidence:
    return MegaPR02Evidence(
        mega_pr01_accepted=True,
        mega_pr01_evidence_hash=HASH,
        findings_covered=REQUIRED_IMPL_FINDINGS,
        protocol_conformance=ProtocolConformanceEvidence(
            protocols=tuple(_protocol(protocol) for protocol in REQUIRED_PROTOCOLS),
            optional_aggregators_disabled_or_admitted=True,
            jupiter_v1_removed_or_quarantined=True,
            jupiter_v2_build_is_canonical=True,
            helius_enqueue_before_ack_proven=True,
            helius_replay_dedup_and_gap_repair_proven=True,
            solana_finalized_v0_read_proven=True,
            marginfi_fee_truth_bound_to_deployment=True,
            kamino_fee_truth_bound_to_registry_or_chain=True,
        ),
        message_simulation=MessageSimulationEvidence(
            compiled_v0_message_hash=HASH,
            simulation_input_message_hash=HASH,
            paper_acceptance_message_hash=HASH,
            instruction_firewall_hash=HASH,
            exact_simulation_passed=True,
            message_hash_immutable_through_acceptance=True,
            protocol_fee_rent_slippage_tip_retry_economics_complete=True,
            no_message_mutation_after_simulation=True,
            negative_instruction_fixture_hash=HASH,
        ),
        hermetic_release=HermeticReleaseEvidence(
            clean_source_export_hash=HASH,
            clean_tree_verified=True,
            generated_artifacts_excluded=True,
            top_level_build_shadowing_prevented=True,
            isolated_verifier_environment=True,
            wheelhouse_lock_hash=HASH,
            wheelhouse_requires_hashes=True,
            offline_network_disabled_build=True,
            dependency_attestations_verified=True,
            sbom_hash=HASH,
            provenance_hash=HASH,
            release_signature_hash=HASH,
            image_digest_pinned=True,
            full_sha_actions_pinned_count=119,
            workflow_actions_total=119,
            mutable_workflow_actions_found=0,
        ),
        security_quality=SecurityQualityEvidence(
            scanners=REQUIRED_SECURITY_SCANNERS,
            scanners_mandatory=True,
            path_aware_findings=True,
            category_aware_findings=True,
            secrets_baseline_reviewed=True,
            precommit_dependencies_pinned=True,
            lint_type_coverage_complete=True,
            optimized_mode_tests_passed=True,
            runtime_asserts_removed_from_safety_path=True,
        ),
        sandbox_readiness=SandboxReadinessEvidence(
            negative_runtime_tests=REQUIRED_SANDBOX_NEGATIVE_TESTS,
            apparmor_profile_loaded=True,
            seccomp_profile_loaded=True,
            egress_enforcement_runtime_proven=True,
            secret_isolation_runtime_proven=True,
            readiness_endpoint_used_for_admission=True,
            readiness_covers_worker_provider_db_queue_recovery=True,
            degraded_dependency_closes_readiness=True,
        ),
        soak_qualification=SoakQualificationEvidence(
            soak_hours=72,
            release_bound_source_hash=HASH,
            release_bound_wheel_hash=HASH,
            release_bound_image_hash=HASH,
            release_bound_config_hash=HASH,
            contract_digest_set_hash=HASH,
            non_synthetic=True,
            no_unexplained_terminal_state=True,
            no_duplicate_intent=True,
            no_synthetic_contamination=True,
            slo_baseline_hash=HASH,
            chaos_dr_secret_rotation_drills_hash=HASH,
            independent_review_hash=HASH,
        ),
        economics_truth=EconomicsTruthEvidence(
            immutable_economics_object_hash=HASH,
            opportunity_profit_lamports=1000,
            admission_profit_lamports=1000,
            terminal_profit_lamports=1000,
            integer_denominated_only=True,
            float_inputs_rejected=True,
            metadata_profit_truth_absent=True,
            expected_profit_bound_to_economics_object=True,
            min_out_bound_to_economics_object=True,
            repayment_bound_to_protocol_evidence=True,
            protocol_fee_bound_to_protocol_evidence=True,
            silent_principal_default_forbidden=True,
            monetary_fuzz_cases=REQUIRED_MONETARY_FUZZ_CASES,
        ),
        provider_http_transport=ProviderHttpTransportEvidence(
            canonical_transport_hash=HASH,
            host_allowlist_hash=HASH,
            retry_policy_hash=HASH,
            all_provider_clients_use_canonical_transport=True,
            streamed_response_size_limit_bytes=1_048_576,
            content_type_limits_enforced=True,
            schema_limits_enforced_before_business_logic=True,
            method_aware_idempotent_retry_policy=True,
            retry_after_and_jitter_proven=True,
            non_idempotent_requests_not_retried=True,
            deadline_budget_enforced=True,
            oversized_response_fails_closed_before_decode=True,
            malformed_response_fails_closed=True,
            slow_response_fails_closed=True,
            no_oom_or_duplicate_side_effects=True,
            provider_failure_cases=REQUIRED_PROVIDER_FAILURE_CASES,
        ),
    )


def test_valid_evidence_qualifies_paper_only() -> None:
    report = evaluate_mega_pr02_evidence(valid_evidence())

    assert report.state is MegaPR02GateState.PRODUCTION_PAPER_QUALIFIED
    assert report.blockers == ()
    assert report.transaction_signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False
    assert report.private_key_material_allowed is False


def test_mega_pr01_dependency_is_hard_blocker() -> None:
    evidence = replace(valid_evidence(), mega_pr01_accepted=False)

    report = evaluate_mega_pr02_evidence(evidence)

    assert blockers_by_code(report)["MEGA_PR02_MPR01_NOT_ACCEPTED"]


def test_v3_findings_impl40_and_impl41_are_required() -> None:
    evidence = replace(
        valid_evidence(),
        findings_covered=tuple(
            finding
            for finding in REQUIRED_IMPL_FINDINGS
            if finding not in {"IMPL-40", "IMPL-41"}
        ),
    )

    report = evaluate_mega_pr02_evidence(evidence)

    blocker = blockers_by_code(report)["MEGA_PR02_FINDINGS_INCOMPLETE"]
    assert "IMPL-40" in blocker.message
    assert "IMPL-41" in blocker.message


def test_float_monetary_inputs_fail_closed() -> None:
    economics = replace(valid_evidence().economics_truth, float_inputs_rejected=False)
    evidence = replace(valid_evidence(), economics_truth=economics)

    report = evaluate_mega_pr02_evidence(evidence)

    assert blockers_by_code(report)["MEGA_PR02_FLOAT_INPUTS_ACCEPTED"]


def test_duplicate_profit_truth_fails_closed() -> None:
    economics = replace(valid_evidence().economics_truth, admission_profit_lamports=999)
    evidence = replace(valid_evidence(), economics_truth=economics)

    report = evaluate_mega_pr02_evidence(evidence)

    assert blockers_by_code(report)["MEGA_PR02_ECONOMICS_DUPLICATE_PROFIT_TRUTH"]


def test_silent_repayment_default_fails_closed() -> None:
    economics = replace(
        valid_evidence().economics_truth,
        repayment_bound_to_protocol_evidence=False,
        silent_principal_default_forbidden=False,
    )
    evidence = replace(valid_evidence(), economics_truth=economics)

    report = evaluate_mega_pr02_evidence(evidence)

    codes = blockers_by_code(report)
    assert codes["MEGA_PR02_REPAYMENT_UNBOUND"]
    assert codes["MEGA_PR02_SILENT_PRINCIPAL_DEFAULT"]


def test_fragmented_provider_http_transport_fails_closed() -> None:
    transport = replace(
        valid_evidence().provider_http_transport,
        all_provider_clients_use_canonical_transport=False,
    )
    evidence = replace(valid_evidence(), provider_http_transport=transport)

    report = evaluate_mega_pr02_evidence(evidence)

    assert blockers_by_code(report)["MEGA_PR02_PROVIDER_TRANSPORT_FRAGMENTED"]


def test_unbounded_or_malformed_provider_response_fails_closed() -> None:
    transport = replace(
        valid_evidence().provider_http_transport,
        streamed_response_size_limit_bytes=0,
        oversized_response_fails_closed_before_decode=False,
        malformed_response_fails_closed=False,
        provider_failure_cases=("oversized_response",),
    )
    evidence = replace(valid_evidence(), provider_http_transport=transport)

    report = evaluate_mega_pr02_evidence(evidence)

    codes = blockers_by_code(report)
    assert codes["MEGA_PR02_PROVIDER_RESPONSE_LIMIT_INVALID"]
    assert codes["MEGA_PR02_OVERSIZED_RESPONSE_NOT_FAIL_CLOSED"]
    assert codes["MEGA_PR02_MALFORMED_RESPONSE_NOT_FAIL_CLOSED"]
    assert codes["MEGA_PR02_PROVIDER_FAILURE_CASES_INCOMPLETE"]


def test_live_or_key_material_still_forbidden() -> None:
    evidence = replace(
        valid_evidence(),
        live_execution_requested=True,
        signer_requested=True,
        sender_requested=True,
        private_key_material_present=True,
    )

    report = evaluate_mega_pr02_evidence(evidence)

    codes = blockers_by_code(report)
    assert codes["MEGA_PR02_LIVE_REQUESTED"]
    assert codes["MEGA_PR02_SIGNER_REQUESTED"]
    assert codes["MEGA_PR02_SENDER_REQUESTED"]
    assert codes["MEGA_PR02_PRIVATE_KEY_PRESENT"]
