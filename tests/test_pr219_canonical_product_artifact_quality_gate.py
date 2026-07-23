from __future__ import annotations

import json

import pytest

from src.pr219_canonical_product_artifact_quality_gate import (
    REQUIRED_FINDINGS,
    ArchitectureConfigEvidence,
    CLICompositionEvidence,
    InstalledWheelEvidence,
    PR219Evidence,
    ProductAuthorityEvidence,
    SupplyChainQualityEvidence,
    blockers_by_code,
    evaluate_pr219_evidence,
)

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64
H6 = "6" * 64
H7 = "7" * 64


def product(**overrides: object) -> ProductAuthorityEvidence:
    values = {
        "product_manifest_sha256": H1,
        "release_set_manifest_sha256": H2,
        "runtime_authority_manifest_sha256": H3,
        "sender_free_product_id": "studious-pancake/main-sender-free",
        "isolated_signer_product_id": "studious-pancake/isolated-signer",
        "active_product_count": 1,
        "backlog_decoupled_from_runtime_authority": True,
        "historical_modules_retired_or_quarantined": True,
        "source_only_modules_outside_production_graph": True,
    }
    values.update(overrides)
    return ProductAuthorityEvidence(**values)


def cli(**overrides: object) -> CLICompositionEvidence:
    values = {
        "root_launcher_contract_sha256": H1,
        "installed_console_contract_sha256": H2,
        "command_contract_manifest_sha256": H3,
        "public_commands": ("status", "capabilities", "doctor"),
        "root_and_console_stdout_stderr_exit_match": True,
        "structured_json_errors_for_all_commands": True,
        "stable_exit_codes_for_all_commands": True,
        "no_heavy_eager_imports_from_status_or_capabilities": True,
    }
    values.update(overrides)
    return CLICompositionEvidence(**values)


def wheel(**overrides: object) -> InstalledWheelEvidence:
    values = {
        "fresh_checkout_wheel_sha256": H1,
        "installed_reachability_trace_sha256": H2,
        "package_data_manifest_sha256": H3,
        "required_control_trace_sha256": H4,
        "source_wheel_parity_verified": True,
        "all_packaged_modules_imported_from_installed_wheel": True,
        "required_controls_reachable_from_composition_root": True,
        "sender_free_wheel_excludes_signer_sender_live_namespaces": True,
        "forbidden_namespace_scan_uses_real_package_contents": True,
    }
    values.update(overrides)
    return InstalledWheelEvidence(**values)


def arch(**overrides: object) -> ArchitectureConfigEvidence:
    values = {
        "schema_registry_sha256": H1,
        "enum_registry_sha256": H2,
        "typed_config_snapshot_sha256": H3,
        "activation_signature_policy_sha256": H4,
        "active_import_graph_sha256": H5,
        "active_import_time_monkeypatching_absent": True,
        "production_import_cycles_absent": True,
        "version_by_filename_not_used_for_selection": True,
        "duplicate_canonical_schemas_retired": True,
        "direct_env_reads_blocked_outside_bootstrap": True,
        "unknown_config_keys_rejected": True,
        "conflicting_defaults_absent": True,
        "signed_activation_required": True,
    }
    values.update(overrides)
    return ArchitectureConfigEvidence(**values)


def quality(**overrides: object) -> SupplyChainQualityEvidence:
    values = {
        "runtime_lock_sha256": H1,
        "signer_lock_sha256": H2,
        "dev_lock_sha256": H3,
        "offline_wheelhouse_manifest_sha256": H4,
        "sbom_sha256": H5,
        "provenance_sha256": H6,
        "quality_trace_sha256": H7,
        "actions_pinned_to_full_sha": True,
        "base_images_pinned_to_digest": True,
        "no_placeholder_hashes_or_caller_inventories": True,
        "ci_gates_execute_installed_graph": True,
        "dependency_profiles_resolved_by_one_owner": True,
        "coverage_threshold_enforced": True,
        "mypy_has_no_broad_quarantine_for_proof_modules": True,
        "lint_and_black_follow_production_graph": True,
        "production_assert_count_zero_under_optimized_python": True,
        "duplicate_tests_retired": True,
    }
    values.update(overrides)
    return SupplyChainQualityEvidence(**values)


def evidence(**overrides: object) -> PR219Evidence:
    values = {
        "finding_coverage": REQUIRED_FINDINGS,
        "product": product(),
        "cli": cli(),
        "wheel": wheel(),
        "architecture_config": arch(),
        "supply_chain_quality": quality(),
    }
    values.update(overrides)
    return PR219Evidence(**values)


def codes(report) -> set[str]:
    return set(blockers_by_code(report))


def test_complete_evidence_unblocks_pr220_and_pr221_but_never_live() -> None:
    report = evaluate_pr219_evidence(evidence())

    assert report.blockers == ()
    assert report.pr220_pr221_unblocked is True
    assert report.live_execution_allowed is False
    assert report.sender_allowed is False
    assert report.signer_allowed is False
    assert len(report.required_findings) == 82


def test_missing_or_extra_finding_coverage_blocks() -> None:
    coverage = REQUIRED_FINDINGS[:-1] + ("F-999",)

    report = evaluate_pr219_evidence(evidence(finding_coverage=coverage))

    assert "PR219_MISSING_FINDING_COVERAGE" in codes(report)
    assert "PR219_UNKNOWN_FINDING_COVERAGE" in codes(report)


def test_duplicate_finding_coverage_blocks() -> None:
    report = evaluate_pr219_evidence(evidence(finding_coverage=REQUIRED_FINDINGS + ("F-001",)))

    assert "PR219_DUPLICATE_FINDING_COVERAGE" in codes(report)


def test_multiple_products_or_shared_signer_identity_blocks() -> None:
    report = evaluate_pr219_evidence(
        evidence(
            product=product(
                active_product_count=2,
                isolated_signer_product_id="studious-pancake/main-sender-free",
            )
        )
    )

    assert "PR219_MULTIPLE_ACTIVE_PRODUCTS" in codes(report)
    assert "PR219_PRODUCT_ISOLATION_MISSING" in codes(report)


def test_cli_contract_mismatch_blocks() -> None:
    report = evaluate_pr219_evidence(
        evidence(
            cli=cli(
                root_and_console_stdout_stderr_exit_match=False,
                public_commands=("status", "status"),
            )
        )
    )

    assert "PR219_CLI_CONTRACT_INCOMPLETE" in codes(report)
    assert "PR219_DUPLICATE_PUBLIC_COMMANDS" in codes(report)


def test_installed_wheel_must_prove_reachability_and_forbidden_namespace_scan() -> None:
    report = evaluate_pr219_evidence(
        evidence(
            wheel=wheel(
                required_controls_reachable_from_composition_root=False,
                sender_free_wheel_excludes_signer_sender_live_namespaces=False,
            )
        )
    )

    assert "PR219_INSTALLED_WHEEL_CLOSURE_INCOMPLETE" in codes(report)


def test_architecture_and_typed_config_truth_are_required() -> None:
    report = evaluate_pr219_evidence(
        evidence(
            architecture_config=arch(
                active_import_time_monkeypatching_absent=False,
                direct_env_reads_blocked_outside_bootstrap=False,
                conflicting_defaults_absent=False,
            )
        )
    )

    assert "PR219_ARCHITECTURE_CONFIG_INCOMPLETE" in codes(report)


def test_supply_chain_and_quality_are_installed_graph_claims() -> None:
    report = evaluate_pr219_evidence(
        evidence(
            supply_chain_quality=quality(
                actions_pinned_to_full_sha=False,
                ci_gates_execute_installed_graph=False,
                production_assert_count_zero_under_optimized_python=False,
            )
        )
    )

    assert "PR219_SUPPLY_CHAIN_QUALITY_INCOMPLETE" in codes(report)


def test_placeholder_hashes_and_bad_identifiers_block() -> None:
    report = evaluate_pr219_evidence(
        evidence(
            product=product(
                product_manifest_sha256="0" * 64,
                sender_free_product_id=" bad id",
            )
        )
    )

    assert "PR219_BAD_PRODUCT_HASH" in codes(report)
    assert "PR219_BAD_IDENTIFIER" in codes(report)


def test_live_sender_or_signer_reachability_blocks_even_when_evidence_otherwise_ready() -> None:
    report = evaluate_pr219_evidence(
        evidence(
            live_namespace_reachable=True,
            sender_namespace_reachable=True,
            signer_namespace_in_main_wheel_reachable=True,
        )
    )

    assert "PR219_LIVE_NAMESPACE_REACHABLE" in codes(report)
    assert "PR219_SENDER_NAMESPACE_REACHABLE" in codes(report)
    assert "PR219_SIGNER_IN_MAIN_WHEEL_REACHABLE" in codes(report)
    assert report.pr220_pr221_unblocked is False


def test_report_json_is_stable_and_sorted() -> None:
    first = evaluate_pr219_evidence(evidence()).to_json()
    second = evaluate_pr219_evidence(evidence()).to_json()

    assert first == second
    payload = json.loads(first)
    assert payload["schema_version"] == "pr219.canonical-product-artifact-quality-truth.v1"


@pytest.mark.parametrize(
    "command",
    ["status", "capabilities", "doctor", "release:qualify"],
)
def test_public_command_identifiers_accept_expected_forms(command: str) -> None:
    report = evaluate_pr219_evidence(evidence(cli=cli(public_commands=(command,))))

    assert "PR219_BAD_IDENTIFIER" not in codes(report)
