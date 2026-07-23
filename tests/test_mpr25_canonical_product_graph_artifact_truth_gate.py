from __future__ import annotations

import json

from src.mpr25_canonical_product_graph_artifact_truth_gate import (
    REQUIRED_ARTIFACTS,
    REQUIRED_COMMANDS,
    REQUIRED_FINDINGS,
    REQUIRED_WORKFLOW_PURPOSES,
    SCHEMA_VERSION,
    evaluate_mpr25_evidence,
)

H2, H3, H4, H5, H6, H7 = ("2" * 64, "3" * 64, "4" * 64, "5" * 64, "6" * 64, "7" * 64)
H8 = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
H9 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
ACTION_SHA = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"


def evidence() -> dict[str, object]:
    surface_hash, reach_hash, dep_hash = H4, H5, H6
    commands = {
        command: {
            "entrypoint": f"src.cli:{command.replace('-', '_')}",
            "in_surface_manifest": True,
            "clean_install_invoked": True,
            "structured_json_errors": True,
            "exit_codes_stable": True,
            "stdout_stderr_contract_stable": True,
        }
        for command in REQUIRED_COMMANDS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "roadmap": "MPR-25",
        "findings_closed": sorted(REQUIRED_FINDINGS),
        "product_graph": {
            "source_tree_sha256": H2,
            "main_wheel_sha256": H3,
            "runtime_image_digest": f"sha256:{H4}",
            "release_set_sha256": H4,
            "surface_manifest_sha256": surface_hash,
            "reachability_manifest_sha256": reach_hash,
            "qualification_log_sha256": H7,
            "generated_from": "installed-wheel-console-scripts",
            "one_product_authority": True,
            "one_release_set_manifest": True,
            "one_composition_root": True,
            "single_mandatory_qualification_gate": True,
            "safe_idle_diagnostic_only": True,
            "safe_idle_cannot_satisfy_readiness": True,
            "source_launchers_retired": True,
            "pm2_paths_retired": True,
            "legacy_gates_demoted": True,
            "declaration_only_gates_blocked": True,
            "old_pr01_pr10_authority_map_replaced": True,
            "coequal_product_authorities": [],
            "signer_namespace_in_main_wheel": False,
            "sender_namespace_in_main_wheel": False,
            "submission_transport_in_main_wheel": False,
            "live_canary_in_main_wheel": False,
        },
        "surface_policy": {
            "policy_sha256": surface_hash,
            "commands": commands,
            "root_launcher_matches_console_scripts": True,
            "package_resources_only": True,
        },
        "reachability": {
            "graph_sha256": reach_hash,
            "generated_from_installed_wheel": True,
            "total_src_modules": 474,
            "reachable_src_modules": 430,
            "quarantined_src_modules": 24,
            "experimental_src_modules": 20,
            "accounted_src_modules": 474,
            "new_module_policy_enforced": True,
            "quarantine_has_expiry_and_owner": True,
            "production_callers": {name: 1 for name in (
                "product_authority", "release_set_authority", "composition_root",
                "surface_policy", "reachability_manifest", "qualification_gate",
                "dependency_graph", "workflow_policy", "quality_inventory",
            )},
            "forbidden_import_edges": [],
            "import_cycles": [],
        },
        "build": {
            "lock_sha256": H2,
            "wheelhouse_sha256": H3,
            "sbom_sha256": H8,
            "builder_provenance_sha256": H9,
            "dependency_graph_sha256": dep_hash,
            "network_disabled_build": True,
            "python_m_build_used": True,
            "docker_build_same_release_path": True,
            "signed_lockfile": True,
            "signed_wheelhouse": True,
            "offline_install_verified": True,
            "pip_check_disposable_release_env": True,
            "ambient_developer_pip_check_removed": True,
            "deterministic_rebuild_or_provenance_equivalence": True,
            "resolver_count": 1,
            "runtime_lock_has_tooling_packages": False,
        },
        "workflows": {
            "required_purposes": list(REQUIRED_WORKFLOW_PURPOSES),
            "workflow_file_count": 5,
            "required_workflow_count": 5,
            "external_action_refs": [ACTION_SHA],
            "least_privilege_permissions": True,
            "no_path_filter_gaps": True,
            "no_writable_diagnostics": True,
            "authoritative_branch_protection_check": "release-qualification",
        },
        "quality": {
            "formatter_manifest_sha256": H2,
            "type_manifest_sha256": H3,
            "test_inventory_sha256": H4,
            "verify_repo_dag_sha256": H5,
            "dependency_graph_sha256": dep_hash,
            "pytest_collection_errors": 0,
            "packaged_module_import_errors": 0,
            "reachable_production_assert_count": 0,
            "formatter_inventory_generated_from_tracked_python": True,
            "formatter_inventory_complete": True,
            "type_lint_coverage_from_inventory": True,
            "black_box_installed_cli_tests": True,
            "python_optimized_mode_equivalent": True,
            "verify_repo_artifact_based_dag": True,
            "no_historical_subset_baseline": True,
            "duplicate_tests_removed_or_retired": True,
            "tracked_python_files": 859,
            "formatter_manifest_entries": 859,
            "type_manifest_entries": 859,
            "test_inventory_entries": 859,
        },
        "artifacts": [
            {
                "kind": kind,
                "path": f"release/{kind}.json",
                "sha256": H2 if idx % 2 else H3,
                "size_bytes": 100 + idx,
                "materialized_from_bytes": True,
                "signature_verified": True,
                "fresh_for_release": True,
                "caller_declared_only": False,
            }
            for idx, kind in enumerate(REQUIRED_ARTIFACTS)
        ],
    }


def codes(report):
    return {b.code for b in report.blockers}


def test_complete_materialized_bundle_allows_sender_free_qualification_review():
    report = evaluate_mpr25_evidence(evidence())
    assert report.decision.value == "ready_for_cutover_review"
    assert report.paper_readiness_allowed is True
    assert report.shadow_readiness_allowed is True
    assert report.mandatory_release_qualification_allowed is True
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.blockers == ()


def test_schema_and_roadmap_must_match():
    item = evidence()
    item["schema_version"] = "wrong"
    item["roadmap"] = "MPR-24"
    assert {"MPR25_SCHEMA_VERSION", "MPR25_ROADMAP_ID"} <= codes(evaluate_mpr25_evidence(item))


def test_findings_must_be_complete_known_and_unique():
    item = evidence()
    item["findings_closed"] = list(item["findings_closed"]) + ["V10-F-438", "UNKNOWN-FINDING"]
    item["findings_closed"].remove("V11-PYTEST-COLLECTION-104")
    result = codes(evaluate_mpr25_evidence(item))
    assert {"MPR25_FINDING_COVERAGE", "MPR25_UNKNOWN_FINDING", "MPR25_DUPLICATE_FINDING"} <= result


def test_product_graph_must_be_installed_and_cut_over():
    item = evidence(); graph = item["product_graph"]
    graph["generated_from"] = "source-checkout"
    graph["one_composition_root"] = False
    graph["source_launchers_retired"] = False
    graph["coequal_product_authorities"] = ["legacy", "new"]
    result = codes(evaluate_mpr25_evidence(item))
    assert {"MPR25_GRAPH_NOT_INSTALLED", "MPR25_PRODUCT_CUTOVER", "MPR25_COEQUAL_AUTHORITIES"} <= result


def test_signer_sender_live_surfaces_remain_forbidden():
    item = evidence(); item["live_execution_requested"] = True
    item["product_graph"]["signer_namespace_in_main_wheel"] = True
    item["product_graph"]["submission_transport_in_main_wheel"] = True
    report = evaluate_mpr25_evidence(item)
    assert {"MPR25_FORBIDDEN_REQUEST", "MPR25_FORBIDDEN_NAMESPACE"} <= codes(report)
    assert report.live_execution_allowed is False


def test_all_public_commands_are_clean_install_contracts():
    item = evidence(); commands = item["surface_policy"]["commands"]
    del commands["flashloan-release-evidence"]
    commands["flashloan-bot"]["structured_json_errors"] = False
    result = codes(evaluate_mpr25_evidence(item))
    assert {"MPR25_MISSING_COMMAND", "MPR25_COMMAND_ERRORS"} <= result


def test_reachability_requires_module_accounting_and_one_caller_per_authority():
    item = evidence(); reach = item["reachability"]
    reach["accounted_src_modules"] = 80
    reach["production_callers"]["qualification_gate"] = 2
    reach["forbidden_import_edges"] = ["src.legacy->src.runtime"]
    result = codes(evaluate_mpr25_evidence(item))
    assert {"MPR25_MODULE_ACCOUNTING", "MPR25_AUTHORITY_CALLER_COUNT", "MPR25_FORBIDDEN_IMPORT_EDGE"} <= result


def test_unaccounted_modules_block_product_graph_truth():
    item = evidence(); reach = item["reachability"]
    reach["reachable_src_modules"] = 80
    assert "MPR25_MODULE_CLOSURE" in codes(evaluate_mpr25_evidence(item))


def test_build_truth_rejects_ambient_and_polluted_dependency_state():
    item = evidence(); build = item["build"]
    build["network_disabled_build"] = False
    build["ambient_developer_pip_check_removed"] = False
    build["resolver_count"] = 3
    build["runtime_lock_has_tooling_packages"] = True
    result = codes(evaluate_mpr25_evidence(item))
    assert {"MPR25_BUILD_TRUTH", "MPR25_MULTIPLE_RESOLVERS", "MPR25_RUNTIME_LOCK_POLLUTED"} <= result


def test_workflows_must_be_small_pinned_and_authoritative():
    item = evidence(); wf = item["workflows"]
    wf["workflow_file_count"] = 68
    wf["external_action_refs"] = ["actions/checkout@v4"]
    wf["authoritative_branch_protection_check"] = "diagnostics"
    result = codes(evaluate_mpr25_evidence(item))
    assert {"MPR25_WORKFLOW_COUNT", "MPR25_MUTABLE_ACTION_REF", "MPR25_BRANCH_CHECK"} <= result


def test_quality_gate_blocks_collection_errors_partial_formatter_and_asserts():
    item = evidence(); quality = item["quality"]
    quality["pytest_collection_errors"] = 104
    quality["formatter_manifest_entries"] = 192
    quality["reachable_production_assert_count"] = 31
    quality["verify_repo_artifact_based_dag"] = False
    result = codes(evaluate_mpr25_evidence(item))
    assert {"MPR25_PYTEST_COLLECTION_ERRORS", "MPR25_INVENTORY_COVERAGE", "MPR25_PRODUCTION_ASSERT", "MPR25_QUALITY_GATE"} <= result


def test_artifacts_must_be_materialized_signed_fresh_and_non_placeholder():
    item = evidence(); artifact = item["artifacts"][0]
    artifact["sha256"] = "0" * 64
    artifact["materialized_from_bytes"] = False
    artifact["signature_verified"] = False
    artifact["fresh_for_release"] = False
    artifact["caller_declared_only"] = True
    result = codes(evaluate_mpr25_evidence(item))
    assert {"MPR25_BAD_ARTIFACT_HASH", "MPR25_ARTIFACT_NOT_MATERIALIZED", "MPR25_ARTIFACT_UNSIGNED", "MPR25_ARTIFACT_STALE", "MPR25_CALLER_DECLARED_ARTIFACT"} <= result


def test_missing_required_artifact_blocks_release_qualification():
    item = evidence(); item["artifacts"] = item["artifacts"][:-1]
    report = evaluate_mpr25_evidence(item)
    assert "MPR25_MISSING_ARTIFACT" in codes(report)
    assert report.mandatory_release_qualification_allowed is False


def test_cross_linked_hashes_prevent_competing_truths():
    item = evidence()
    item["product_graph"]["surface_manifest_sha256"] = H2
    item["product_graph"]["reachability_manifest_sha256"] = H3
    item["quality"]["dependency_graph_sha256"] = H4
    result = codes(evaluate_mpr25_evidence(item))
    assert {"MPR25_SURFACE_HASH_DRIFT", "MPR25_REACHABILITY_HASH_DRIFT", "MPR25_DEPENDENCY_HASH_DRIFT"} <= result


def test_report_json_is_deterministic_and_no_live_capability():
    report = evaluate_mpr25_evidence(evidence())
    parsed = json.loads(report.to_json())
    assert parsed["decision"] == "ready_for_cutover_review"
    assert parsed["live_execution_allowed"] is False
    assert parsed["signer_allowed"] is False
    assert parsed["sender_allowed"] is False
    assert report.to_json() == evaluate_mpr25_evidence(evidence()).to_json()
