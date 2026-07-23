from __future__ import annotations

from dataclasses import replace
from src.mega_pr02_protocol_conformance_release_gate import (  # noqa: E402
    REQUIRED_IMPL_FINDINGS,
    REQUIRED_PROTOCOLS,
    REQUIRED_SANDBOX_NEGATIVE_TESTS,
    REQUIRED_SECURITY_SCANNERS,
    HermeticReleaseEvidence,
    MegaPR02Evidence,
    MegaPR02GateState,
    MessageSimulationEvidence,
    ProtocolConformanceEvidence,
    ProtocolContractEvidence,
    ProtocolDisposition,
    SandboxReadinessEvidence,
    SecurityQualityEvidence,
    SoakQualificationEvidence,
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
            instruction_firewall_manifest_hash=HASH,
            exact_simulation_report_hash=HASH,
            protocol_economics_report_hash=HASH,
            fees_rent_slippage_tip_retry_complete=True,
            mutation_after_simulation_detected=False,
            protocol_fee_sources_chain_or_contract_bound=True,
            paper_outcome_bound_to_message_hash=True,
        ),
        hermetic_release=HermeticReleaseEvidence(
            source_export_manifest_hash=HASH,
            clean_tree_verified=True,
            generated_artifacts_excluded=True,
            top_level_build_shadowing_prevented=True,
            aggregate_verifier_uses_isolated_environment=True,
            hash_locked_wheelhouse_manifest_hash=HASH,
            offline_build_network_disabled=True,
            package_attestations_verified=True,
            sbom_hash=HASH,
            provenance_hash=HASH,
            release_signature_hash=HASH,
            docker_base_image_pinned_by_digest=True,
            github_actions_total_uses=119,
            github_actions_full_sha_pins=119,
            mutable_action_refs=(),
        ),
        security_quality=SecurityQualityEvidence(
            mandatory_scanners=REQUIRED_SECURITY_SCANNERS,
            scanner_policy_hash=HASH,
            path_aware_findings=True,
            category_aware_findings=True,
            secrets_baseline_reviewed_or_removed=True,
            pre_commit_dependencies_pinned=True,
            security_gate_runs_in_clean_aggregate=True,
            runtime_asserts_replaced_on_critical_path=True,
            optimized_mode_tests_passed=True,
            lint_type_coverage_hash=HASH,
            no_python_o_validation_loss=True,
        ),
        sandbox_readiness=SandboxReadinessEvidence(
            apparmor_profile_hash=HASH,
            seccomp_profile_hash=HASH,
            egress_policy_hash=HASH,
            apparmor_loaded=True,
            seccomp_loaded=True,
            destination_port_dns_egress_enforced=True,
            secret_isolation_proven=True,
            negative_runtime_tests=REQUIRED_SANDBOX_NEGATIVE_TESTS,
            health_is_liveness_only=True,
            readiness_endpoint_configured_for_admission=True,
            readiness_checks_worker_provider_db_queue_recovery=True,
            readiness_false_on_critical_degradation=True,
        ),
        soak=SoakQualificationEvidence(
            duration_hours=72,
            non_synthetic=True,
            source_commit_hash=HASH,
            wheel_hash=HASH,
            image_digest_hash=HASH,
            config_digest_hash=HASH,
            contract_digest_hash=HASH,
            evidence_bundle_hash=HASH,
            slo_baseline_hash=HASH,
            chaos_dr_secret_rotation_report_hash=HASH,
            no_unexplained_terminal_state=True,
            no_duplicate_intent=True,
            no_synthetic_contamination=True,
            independent_review_signed=True,
            product_state_changes_to_paper_ready_only=True,
        ),
    )


def assert_codes(evidence: MegaPR02Evidence, *codes: str) -> None:
    report = evaluate_mega_pr02_evidence(evidence)
    actual = {blocker.code for blocker in report.blockers}
    for code in codes:
        assert code in actual


def test_valid_evidence_qualifies_paper_but_never_live() -> None:
    report = evaluate_mega_pr02_evidence(valid_evidence())

    assert report.state == MegaPR02GateState.PRODUCTION_PAPER_QUALIFIED
    assert report.paper_ready_allowed is True
    assert report.transaction_signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False
    assert report.blockers == ()


def test_missing_mega_pr01_blocks_even_with_good_evidence() -> None:
    evidence = replace(valid_evidence(), mega_pr01_accepted=False)

    assert_codes(evidence, "MEGA_PR02_MISSING_MEGA_PR01")


def test_missing_protocol_and_active_v1_blocks_contract_admission() -> None:
    conformance = valid_evidence().protocol_conformance
    evidence = replace(
        valid_evidence(),
        protocol_conformance=replace(
            conformance,
            protocols=conformance.protocols[:-1],
            jupiter_v1_removed_or_quarantined=False,
        ),
    )

    assert_codes(
        evidence,
        "MEGA_PR02_PROTOCOL_MISSING",
        "MEGA_PR02_JUPITER_V1_ACTIVE",
    )


def test_message_hash_mutation_after_simulation_blocks_paper_acceptance() -> None:
    message = valid_evidence().message_simulation
    evidence = replace(
        valid_evidence(),
        message_simulation=replace(
            message,
            paper_acceptance_message_hash="b" * 64,
            mutation_after_simulation_detected=True,
        ),
    )

    assert_codes(
        evidence,
        "MEGA_PR02_MESSAGE_HASH_MUTATED",
        "MEGA_PR02_MUTATION_AFTER_SIMULATION",
    )


def test_online_dirty_unpinned_release_blocks_hermetic_claim() -> None:
    release = valid_evidence().hermetic_release
    evidence = replace(
        valid_evidence(),
        hermetic_release=replace(
            release,
            clean_tree_verified=False,
            offline_build_network_disabled=False,
            github_actions_full_sha_pins=0,
            mutable_action_refs=("actions/checkout@v4",),
        ),
    )

    assert_codes(
        evidence,
        "MEGA_PR02_DIRTY_SOURCE",
        "MEGA_PR02_ONLINE_BUILD",
        "MEGA_PR02_ACTIONS_NOT_PINNED",
        "MEGA_PR02_MUTABLE_ACTION_REFS",
    )


def test_python_o_assertion_loss_blocks_quality_gate() -> None:
    quality = valid_evidence().security_quality
    evidence = replace(
        valid_evidence(),
        security_quality=replace(
            quality,
            runtime_asserts_replaced_on_critical_path=False,
            optimized_mode_tests_passed=False,
            no_python_o_validation_loss=False,
        ),
    )

    assert_codes(
        evidence,
        "MEGA_PR02_RUNTIME_ASSERTS_REMAIN",
        "MEGA_PR02_OPTIMIZED_TESTS_MISSING",
        "MEGA_PR02_PYTHON_O_VALIDATION_LOSS",
    )


def test_declarative_sandbox_or_short_synthetic_soak_blocks_release() -> None:
    sandbox = valid_evidence().sandbox_readiness
    soak = valid_evidence().soak
    evidence = replace(
        valid_evidence(),
        sandbox_readiness=replace(
            sandbox,
            seccomp_loaded=False,
            negative_runtime_tests=REQUIRED_SANDBOX_NEGATIVE_TESTS[:-1],
            readiness_false_on_critical_degradation=False,
        ),
        soak=replace(
            soak,
            duration_hours=48,
            non_synthetic=False,
            independent_review_signed=False,
        ),
    )

    assert_codes(
        evidence,
        "MEGA_PR02_SECCOMP_NOT_LOADED",
        "MEGA_PR02_SANDBOX_NEGATIVE_TESTS_MISSING",
        "MEGA_PR02_READY_FAIL_OPEN",
        "MEGA_PR02_SOAK_TOO_SHORT",
        "MEGA_PR02_SYNTHETIC_SOAK",
        "MEGA_PR02_REVIEW_UNSIGNED",
    )


def test_live_surface_is_always_forbidden() -> None:
    evidence = replace(
        valid_evidence(),
        signer_present=True,
        sender_present=True,
        live_execution_present=True,
        private_key_material_present=True,
    )

    report = evaluate_mega_pr02_evidence(evidence)
    assert report.transaction_signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False
    assert_codes(
        evidence,
        "MEGA_PR02_SIGNER_PRESENT",
        "MEGA_PR02_SENDER_PRESENT",
        "MEGA_PR02_LIVE_PRESENT",
        "MEGA_PR02_PRIVATE_KEY_PRESENT",
    )
