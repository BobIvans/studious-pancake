from src.pr217_installed_behavioral_quality_gate import (
    CoverageEvidence,
    DuplicateTestEvidence,
    DuplicateTestGroup,
    LintTypeEvidence,
    PR217GateState,
    PR217QualityEvidence,
    WheelSubprocessEvidence,
    evaluate_pr217_quality_evidence,
)


def h(seed: str) -> str:
    return (seed * 64)[:64]


def complete_evidence(**overrides) -> PR217QualityEvidence:
    duplicate_group = DuplicateTestGroup(
        group_hash=h("1"),
        files=(
            "tests/test_orderbook_ray.py",
            "tests/test_orderbook_phoenix.py",
        ),
        behavioral_case_id="orderbook-adapter-parameterized-depth",
        parameterized_fixture_count=2,
    )
    values = {
        "release_artifact_hash": h("a"),
        "quality_manifest_hash": h("b"),
        "installed_graph_manifest_hash": h("c"),
        "pyproject_script_manifest_hash": h("d"),
        "findings_covered": (
            "F-296",
            "F-297",
            "F-298",
            "F-299",
            "F-300",
            "F-301",
            "F-302",
        ),
        "duplicate_tests": DuplicateTestEvidence(
            total_test_files=278,
            total_test_functions=1880,
            unique_behavioral_case_count=1740,
            duplicate_hash_groups=(duplicate_group,),
            duplicate_hashes_counted_as_independent_evidence=False,
            duplicate_groups_removed_or_parameterized=True,
            unique_case_count_published=True,
        ),
        "coverage": CoverageEvidence(
            line_coverage_enabled=True,
            branch_coverage_enabled=True,
            diff_coverage_enabled=True,
            measured_line_percent=88.0,
            measured_branch_percent=82.0,
            measured_diff_percent=91.0,
            minimum_line_percent=80.0,
            minimum_branch_percent=80.0,
            minimum_diff_percent=85.0,
            required_controls_map_hash=h("e"),
            installed_wheel_hash=h("6"),
            coverage_bound_to_installed_wheel=True,
            composition_trace_hash=h("2"),
        ),
        "lint_type": LintTypeEvidence(
            complexity_signal_enabled=True,
            unused_import_signal_enabled=True,
            redefined_name_signal_enabled=True,
            wildcard_import_signal_enabled=True,
            wildcard_imports_forbidden=True,
            format_targets_from_installed_graph=True,
            quarantine_manifest_hash=h("3"),
            quarantine_entries_have_owner_issue_expiry=True,
            active_graph_mypy_ignore_errors_count=0,
            active_graph_wildcard_import_count=0,
        ),
        "subprocess_matrix": WheelSubprocessEvidence(
            installed_console_targets=(
                "flashloan-bot",
                "flashloan-bot-healthcheck",
                "flashloan-contracts",
                "flashloan-checks",
                "flashloan-release-evidence",
            ),
            production_surface_console_targets=(
                "flashloan-bot",
                "flashloan-bot-healthcheck",
                "flashloan-contracts",
                "flashloan-checks",
                "flashloan-release-evidence",
            ),
            exercised_cases=(
                "clean_env",
                "missing_dependency",
                "corrupt_config",
                "unknown_command",
                "interrupted_output",
            ),
            exact_exit_schema_assertions=True,
            no_traceback_without_debug=True,
            dependency_failure_structured=True,
            config_failure_structured=True,
            root_wrapper_parity_checked=True,
            installed_artifact_hash=h("4"),
        ),
    }
    values.update(overrides)
    return PR217QualityEvidence(**values)


def codes(report):
    return {blocker.code for blocker in report.blockers}


def test_accepts_complete_installed_quality_baseline():
    report = evaluate_pr217_quality_evidence(complete_evidence())

    assert report.state == PR217GateState.READY_FOR_INSTALLED_QUALITY_BASELINE
    assert report.blockers == ()
    assert report.live_execution_allowed is False
    assert report.sender_allowed is False
    assert report.transaction_signer_allowed is False


def test_rejects_duplicate_hashes_counted_as_independent_evidence():
    base = complete_evidence().duplicate_tests
    report = evaluate_pr217_quality_evidence(
        complete_evidence(
            duplicate_tests=DuplicateTestEvidence(
                total_test_files=base.total_test_files,
                total_test_functions=base.total_test_functions,
                unique_behavioral_case_count=base.unique_behavioral_case_count,
                duplicate_hash_groups=base.duplicate_hash_groups,
                duplicate_hashes_counted_as_independent_evidence=True,
                duplicate_groups_removed_or_parameterized=True,
                unique_case_count_published=True,
            )
        )
    )

    assert "PR217_DUPLICATE_HASH_COUNTED" in codes(report)


def test_rejects_missing_branch_and_diff_coverage_gates():
    base = complete_evidence().coverage
    report = evaluate_pr217_quality_evidence(
        complete_evidence(
            coverage=CoverageEvidence(
                line_coverage_enabled=True,
                branch_coverage_enabled=False,
                diff_coverage_enabled=False,
                measured_line_percent=90.0,
                measured_branch_percent=0.0,
                measured_diff_percent=0.0,
                minimum_line_percent=80.0,
                minimum_branch_percent=80.0,
                minimum_diff_percent=85.0,
                required_controls_map_hash=base.required_controls_map_hash,
                installed_wheel_hash=base.installed_wheel_hash,
                coverage_bound_to_installed_wheel=True,
                composition_trace_hash=base.composition_trace_hash,
            )
        )
    )

    assert "PR217_BRANCH_COVERAGE_DISABLED" in codes(report)
    assert "PR217_DIFF_COVERAGE_DISABLED" in codes(report)


def test_rejects_coverage_not_bound_to_installed_wheel():
    base = complete_evidence().coverage
    report = evaluate_pr217_quality_evidence(
        complete_evidence(
            coverage=CoverageEvidence(
                line_coverage_enabled=True,
                branch_coverage_enabled=True,
                diff_coverage_enabled=True,
                measured_line_percent=88.0,
                measured_branch_percent=82.0,
                measured_diff_percent=91.0,
                minimum_line_percent=80.0,
                minimum_branch_percent=80.0,
                minimum_diff_percent=85.0,
                required_controls_map_hash=base.required_controls_map_hash,
                installed_wheel_hash=base.installed_wheel_hash,
                coverage_bound_to_installed_wheel=False,
                composition_trace_hash=base.composition_trace_hash,
            )
        )
    )

    assert "PR217_COVERAGE_NOT_WHEEL_BOUND" in codes(report)


def test_rejects_disabled_flake8_debt_signals():
    base = complete_evidence().lint_type
    report = evaluate_pr217_quality_evidence(
        complete_evidence(
            lint_type=LintTypeEvidence(
                complexity_signal_enabled=False,
                unused_import_signal_enabled=False,
                redefined_name_signal_enabled=False,
                wildcard_import_signal_enabled=False,
                wildcard_imports_forbidden=True,
                format_targets_from_installed_graph=True,
                quarantine_manifest_hash=base.quarantine_manifest_hash,
                quarantine_entries_have_owner_issue_expiry=True,
                active_graph_mypy_ignore_errors_count=0,
                active_graph_wildcard_import_count=0,
            )
        )
    )

    assert "PR217_COMPLEXITY_SIGNAL_DISABLED" in codes(report)
    assert "PR217_UNUSED_IMPORT_SIGNAL_DISABLED" in codes(report)
    assert "PR217_REDEFINED_NAME_SIGNAL_DISABLED" in codes(report)
    assert "PR217_WILDCARD_SIGNAL_DISABLED" in codes(report)


def test_rejects_manual_format_targets():
    base = complete_evidence().lint_type
    report = evaluate_pr217_quality_evidence(
        complete_evidence(
            lint_type=LintTypeEvidence(
                complexity_signal_enabled=True,
                unused_import_signal_enabled=True,
                redefined_name_signal_enabled=True,
                wildcard_import_signal_enabled=True,
                wildcard_imports_forbidden=True,
                format_targets_from_installed_graph=False,
                quarantine_manifest_hash=base.quarantine_manifest_hash,
                quarantine_entries_have_owner_issue_expiry=True,
                active_graph_mypy_ignore_errors_count=0,
                active_graph_wildcard_import_count=0,
            )
        )
    )

    assert "PR217_FORMAT_TARGETS_NOT_GRAPH_DERIVED" in codes(report)


def test_rejects_active_graph_mypy_ignore_errors():
    base = complete_evidence().lint_type
    report = evaluate_pr217_quality_evidence(
        complete_evidence(
            lint_type=LintTypeEvidence(
                complexity_signal_enabled=True,
                unused_import_signal_enabled=True,
                redefined_name_signal_enabled=True,
                wildcard_import_signal_enabled=True,
                wildcard_imports_forbidden=True,
                format_targets_from_installed_graph=True,
                quarantine_manifest_hash=base.quarantine_manifest_hash,
                quarantine_entries_have_owner_issue_expiry=True,
                active_graph_mypy_ignore_errors_count=1,
                active_graph_wildcard_import_count=0,
            )
        )
    )

    assert "PR217_ACTIVE_GRAPH_MYPY_IGNORE_ERRORS" in codes(report)


def test_rejects_active_graph_wildcard_imports():
    base = complete_evidence().lint_type
    report = evaluate_pr217_quality_evidence(
        complete_evidence(
            lint_type=LintTypeEvidence(
                complexity_signal_enabled=True,
                unused_import_signal_enabled=True,
                redefined_name_signal_enabled=True,
                wildcard_import_signal_enabled=True,
                wildcard_imports_forbidden=True,
                format_targets_from_installed_graph=True,
                quarantine_manifest_hash=base.quarantine_manifest_hash,
                quarantine_entries_have_owner_issue_expiry=True,
                active_graph_mypy_ignore_errors_count=0,
                active_graph_wildcard_import_count=1,
            )
        )
    )

    assert "PR217_ACTIVE_GRAPH_WILDCARD_IMPORTS" in codes(report)


def test_rejects_missing_wheel_subprocess_failure_matrix_case():
    base = complete_evidence().subprocess_matrix
    report = evaluate_pr217_quality_evidence(
        complete_evidence(
            subprocess_matrix=WheelSubprocessEvidence(
                installed_console_targets=base.installed_console_targets,
                production_surface_console_targets=base.production_surface_console_targets,
                exercised_cases=("clean_env", "unknown_command"),
                exact_exit_schema_assertions=True,
                no_traceback_without_debug=True,
                dependency_failure_structured=True,
                config_failure_structured=True,
                root_wrapper_parity_checked=True,
                installed_artifact_hash=base.installed_artifact_hash,
            )
        )
    )

    assert "PR217_SUBPROCESS_MATRIX_INCOMPLETE" in codes(report)


def test_rejects_live_signer_or_sender_enablement():
    report = evaluate_pr217_quality_evidence(
        complete_evidence(
            live_execution_requested=True,
            signer_requested=True,
            sender_requested=True,
        )
    )

    assert "PR217_LIVE_REQUESTED" in codes(report)
    assert "PR217_SIGNER_REQUESTED" in codes(report)
    assert "PR217_SENDER_REQUESTED" in codes(report)
