from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from src.release_gate.production_paper_qualification import (
    REQUIRED_CHAOS_SCENARIOS,
    REQUIRED_PROTOCOLS,
    ExactMessageProof,
    HermeticReleaseEvidence,
    MaterializedArtifact,
    ProductionPaperQualificationEvidence,
    ProtocolConformance,
    QualificationBlocker,
    QualificationEvidenceError,
    SandboxEvidence,
    SoakQualificationEvidence,
    evaluate_production_paper_qualification,
)


def h(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def artifact(label: str) -> MaterializedArtifact:
    return MaterializedArtifact(
        path=f"evidence/{label}.json",
        sha256=h(label),
        size_bytes=128,
        producer_id=f"producer-{label}",
        media_type="application/json",
    )


def protocol(protocol_id: str) -> ProtocolConformance:
    return ProtocolConformance(
        protocol_id=protocol_id,
        contract_generation=f"{protocol_id}-2026-07",
        credentialed_probe=artifact(f"{protocol_id}-probe"),
        golden_fixtures=artifact(f"{protocol_id}-golden"),
        negative_fixtures=artifact(f"{protocol_id}-negative"),
        schema_pinned=True,
        program_and_account_identity_verified=True,
        drift_detection_materialized=True,
        supported_combinations_nonempty=True,
    )


def complete_evidence() -> ProductionPaperQualificationEvidence:
    message_hash = h("compiled-message")
    release_wheel = h("wheel")
    release_image = h("image")
    release_config = h("config")
    release_contracts = h("contracts")
    exact = ExactMessageProof(
        compiled_message_sha256=message_hash,
        simulated_message_sha256=message_hash,
        transaction_proof=artifact("transaction-proof"),
        simulation_result=artifact("simulation-result"),
        economics_result=artifact("economics-result"),
        instruction_order_verified=True,
        program_allowlist_verified=True,
        account_metas_verified=True,
        signer_writable_flags_verified=True,
        compute_budget_verified=True,
        blockhash_validity_verified=True,
        mutation_after_simulation_impossible=True,
        total_fees_rent_and_tips_reserved=True,
        slippage_bound_verified=True,
        flash_repayment_verified=True,
        minimum_profit_verified=True,
    )
    release = HermeticReleaseEvidence(
        source_commit="1" * 40,
        source_tree_sha256=h("tree"),
        wheel_sha256=release_wheel,
        image_sha256=release_image,
        config_sha256=release_config,
        provider_contracts_sha256=release_contracts,
        qualification_manifest=artifact("qualification-manifest"),
        sbom=artifact("sbom"),
        provenance=artifact("provenance"),
        artifact_signature=artifact("signature"),
        clean_source_tree=True,
        network_disabled_build=True,
        offline_hash_locked_wheelhouse=True,
        reproducible_build_verified=True,
        github_actions_refs=("2" * 40, "3" * 40),
        docker_base_image_digest=h("docker-base"),
        wheel_image_surface_equal=True,
    )
    sandbox = SandboxEvidence(
        runtime_test_report=artifact("sandbox-runtime"),
        apparmor_profile=artifact("apparmor"),
        seccomp_profile=artifact("seccomp"),
        egress_policy=artifact("egress"),
        non_root_runtime=True,
        read_only_root_filesystem=True,
        apparmor_loaded_and_hash_verified=True,
        seccomp_loaded_and_hash_verified=True,
        denied_write_capability_and_egress_tests_passed=True,
        egress_destination_port_dns_allowlist_enforced=True,
        secrets_from_files_or_manager_only=True,
        plaintext_secret_placeholders_absent=True,
        secret_rotation_drill_passed=True,
        operator_plane_authenticated=True,
        operator_rbac_enforced=True,
        audit_log_durable=True,
        pause_drain_kill_switch_tested=True,
        break_glass_procedure_tested=True,
    )
    soak = SoakQualificationEvidence(
        soak_report=artifact("soak"),
        slo_report=artifact("slo"),
        chaos_report=artifact("chaos"),
        operator_drill_report=artifact("operator-drill"),
        independent_review=artifact("independent-review"),
        duration_hours=72,
        release_wheel_sha256=release_wheel,
        release_image_sha256=release_image,
        release_config_sha256=release_config,
        release_provider_contracts_sha256=release_contracts,
        non_synthetic_streaming_data=True,
        real_provider_data_plane=True,
        synthetic_contamination_count=0,
        lost_intents=0,
        duplicate_intents=0,
        unexplained_terminal_states=0,
        accepted_cycles_have_complete_causal_economic_chain=True,
        required_chaos_scenarios_completed=REQUIRED_CHAOS_SCENARIOS,
        provider_availability_slo_met=True,
        rooted_freshness_slo_met=True,
        latency_slo_met=True,
        queue_and_cycle_slo_met=True,
        reconciliation_slo_met=True,
        resource_profiles_materialized=True,
        alert_routing_and_runbooks_drilled=True,
        evidence_signed_and_immutable=True,
        independently_reviewed=True,
    )
    return ProductionPaperQualificationEvidence(
        mega_pr_01_accepted=True,
        mega_pr_01_report_sha256=h("mega-pr-01"),
        protocols=tuple(protocol(item) for item in REQUIRED_PROTOCOLS),
        optional_provider_ids=("okx", "openocean", "odos"),
        optional_providers_admitted=(),
        jupiter_contract_generations=("swap-v1",),
        exact_message=exact,
        release=release,
        sandbox=sandbox,
        soak=soak,
    )


def blocker_values(report) -> set[str]:
    return set(report.blockers)


def test_complete_evidence_allows_paper_ready_but_never_live() -> None:
    report = evaluate_production_paper_qualification(complete_evidence())

    assert report.ready
    assert report.paper_ready_allowed
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.blockers == ()
    assert len(report.evidence_hash) == 64


def test_mega_pr_01_dependency_is_mandatory() -> None:
    evidence = replace(complete_evidence(), mega_pr_01_accepted=False)
    report = evaluate_production_paper_qualification(evidence)

    assert QualificationBlocker.MEGA_PR_01_NOT_ACCEPTED.value in blocker_values(
        report
    )


def test_required_protocol_set_must_be_exact() -> None:
    evidence = complete_evidence()
    report = evaluate_production_paper_qualification(
        replace(evidence, protocols=evidence.protocols[:-1])
    )

    assert QualificationBlocker.PROTOCOL_SET_INCOMPLETE.value in blocker_values(
        report
    )


def test_protocol_conformance_cannot_be_documentation_only() -> None:
    evidence = complete_evidence()
    first = replace(
        evidence.protocols[0],
        schema_pinned=False,
        drift_detection_materialized=False,
    )
    report = evaluate_production_paper_qualification(
        replace(evidence, protocols=(first, *evidence.protocols[1:]))
    )

    assert (
        QualificationBlocker.PROTOCOL_CONFORMANCE_INCOMPLETE.value
        in blocker_values(report)
    )


def test_jupiter_contract_generation_must_be_unambiguous() -> None:
    evidence = replace(
        complete_evidence(),
        jupiter_contract_generations=("swap-v1", "swap-v2-build"),
    )
    report = evaluate_production_paper_qualification(evidence)

    assert QualificationBlocker.JUPITER_CONTRACT_AMBIGUOUS.value in blocker_values(
        report
    )


def test_optional_provider_cannot_be_admitted_without_evidence() -> None:
    evidence = replace(
        complete_evidence(),
        optional_providers_admitted=("unknown-provider",),
    )
    report = evaluate_production_paper_qualification(evidence)

    assert (
        QualificationBlocker.OPTIONAL_PROVIDER_ADMITTED_WITHOUT_EVIDENCE.value
        in blocker_values(report)
    )


def test_exact_simulation_must_match_compiled_message() -> None:
    evidence = complete_evidence()
    exact = replace(
        evidence.exact_message,
        simulated_message_sha256=h("different-message"),
    )
    report = evaluate_production_paper_qualification(
        replace(evidence, exact_message=exact)
    )

    assert QualificationBlocker.MESSAGE_SIMULATION_MISMATCH.value in blocker_values(
        report
    )


def test_post_simulation_mutation_is_blocked() -> None:
    evidence = complete_evidence()
    exact = replace(
        evidence.exact_message,
        mutation_after_simulation_impossible=False,
    )
    report = evaluate_production_paper_qualification(
        replace(evidence, exact_message=exact)
    )

    assert (
        QualificationBlocker.MESSAGE_MUTABLE_AFTER_SIMULATION.value
        in blocker_values(report)
    )


def test_instruction_and_economics_proofs_are_mandatory() -> None:
    evidence = complete_evidence()
    exact = replace(
        evidence.exact_message,
        account_metas_verified=False,
        minimum_profit_verified=False,
    )
    report = evaluate_production_paper_qualification(
        replace(evidence, exact_message=exact)
    )

    assert (
        QualificationBlocker.INSTRUCTION_OR_ACCOUNT_PROOF_INCOMPLETE.value
        in blocker_values(report)
    )
    assert QualificationBlocker.ECONOMIC_PROOF_INCOMPLETE.value in blocker_values(
        report
    )


def test_release_build_must_be_hermetic_and_pinned() -> None:
    evidence = complete_evidence()
    release = replace(
        evidence.release,
        network_disabled_build=False,
        offline_hash_locked_wheelhouse=False,
        github_actions_refs=(),
    )
    report = evaluate_production_paper_qualification(
        replace(evidence, release=release)
    )

    assert QualificationBlocker.RELEASE_BUILD_NOT_HERMETIC.value in blocker_values(
        report
    )
    assert QualificationBlocker.SUPPLY_CHAIN_NOT_PINNED.value in blocker_values(
        report
    )


def test_soak_is_bound_to_exact_release_identity() -> None:
    evidence = complete_evidence()
    soak = replace(evidence.soak, release_image_sha256=h("other-image"))
    report = evaluate_production_paper_qualification(replace(evidence, soak=soak))

    assert QualificationBlocker.RELEASE_IDENTITY_MISMATCH.value in blocker_values(
        report
    )


def test_sandbox_must_be_measured_not_declared() -> None:
    evidence = complete_evidence()
    sandbox = replace(
        evidence.sandbox,
        apparmor_loaded_and_hash_verified=False,
        egress_destination_port_dns_allowlist_enforced=False,
        operator_rbac_enforced=False,
    )
    report = evaluate_production_paper_qualification(
        replace(evidence, sandbox=sandbox)
    )

    assert QualificationBlocker.SANDBOX_NOT_ENFORCED.value in blocker_values(report)
    assert (
        QualificationBlocker.SECRET_OR_OPERATOR_POLICY_INCOMPLETE.value
        in blocker_values(report)
    )


def test_soak_requires_72_hours_non_synthetic_and_complete_chaos() -> None:
    evidence = complete_evidence()
    soak = replace(
        evidence.soak,
        duration_hours=71,
        non_synthetic_streaming_data=False,
        synthetic_contamination_count=1,
        required_chaos_scenarios_completed=REQUIRED_CHAOS_SCENARIOS[:-1],
    )
    report = evaluate_production_paper_qualification(replace(evidence, soak=soak))

    assert QualificationBlocker.SOAK_TOO_SHORT.value in blocker_values(report)
    assert (
        QualificationBlocker.SOAK_SYNTHETIC_OR_NOT_RELEASE_BOUND.value
        in blocker_values(report)
    )
    assert QualificationBlocker.CHAOS_MATRIX_INCOMPLETE.value in blocker_values(
        report
    )


def test_soak_terminal_and_independent_review_invariants() -> None:
    evidence = complete_evidence()
    soak = replace(
        evidence.soak,
        duplicate_intents=1,
        unexplained_terminal_states=1,
        independently_reviewed=False,
    )
    report = evaluate_production_paper_qualification(replace(evidence, soak=soak))

    assert (
        QualificationBlocker.SLO_OR_TERMINAL_INVARIANTS_FAILED.value
        in blocker_values(report)
    )
    assert (
        QualificationBlocker.PROMOTION_EVIDENCE_NOT_INDEPENDENT.value
        in blocker_values(report)
    )


def test_live_signer_or_sender_surface_is_always_blocked() -> None:
    evidence = replace(
        complete_evidence(),
        live_execution_reachable=True,
        signer_reachable=True,
        sender_reachable=True,
    )
    report = evaluate_production_paper_qualification(evidence)

    assert (
        QualificationBlocker.LIVE_OR_SIGNER_SURFACE_REACHABLE.value
        in blocker_values(report)
    )
    assert report.paper_ready_allowed is False


def test_materialized_artifact_rejects_placeholder_digest_and_unsafe_path() -> None:
    with pytest.raises(QualificationEvidenceError, match="placeholder"):
        MaterializedArtifact(
            path="evidence/item.json",
            sha256="0" * 64,
            size_bytes=1,
            producer_id="producer",
            media_type="application/json",
        )
    with pytest.raises(QualificationEvidenceError, match="relative path"):
        MaterializedArtifact(
            path="../secret",
            sha256=h("safe"),
            size_bytes=1,
            producer_id="producer",
            media_type="application/json",
        )


def test_report_json_is_stable() -> None:
    report = evaluate_production_paper_qualification(complete_evidence())
    payload = json.loads(report.to_json())

    assert payload["schema_version"] == "release.production-paper-qualification.v1"
    assert payload["paper_ready_allowed"] is True
    assert payload["live_execution_allowed"] is False
