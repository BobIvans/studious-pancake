from __future__ import annotations

from dataclasses import replace
import pytest

from src.pr219_canonical_product_artifact_quality_gate import (
    CLIContract,
    PR219ArtifactEvidence,
    PR219GateState,
    evaluate_pr219_artifact_quality,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
DIGEST = "sha256:" + "e" * 64


def clean_evidence() -> PR219ArtifactEvidence:
    return PR219ArtifactEvidence(
        canonical_product_id="flashloan-bot.sender-free",
        composition_root_module="src.cli_pr189",
        main_wheel_sha256=SHA_A,
        signer_wheel_sha256=SHA_B,
        image_digest=DIGEST,
        sbom_sha256=SHA_C,
        provenance_sha256=SHA_D,
        installed_modules=(
            "src.cli_pr189",
            "src.automation_cli_pr189",
            "src.paper_shadow.runtime",
            "src.release.manifest",
            "src.security.qualification",
            "src.observability.readiness",
        ),
        reachable_modules=(
            "src.cli_pr189",
            "src.automation_cli_pr189",
            "src.paper_shadow.runtime",
            "src.release.manifest",
            "src.security.qualification",
            "src.observability.readiness",
        ),
        required_controls=(
            "src.release.manifest",
            "src.security.qualification",
            "src.observability.readiness",
        ),
        observed_required_controls=(
            "src.release.manifest",
            "src.security.qualification",
            "src.observability.readiness",
        ),
        cli_contracts=(
            CLIContract("flashloan-bot", "src.cli_pr189", True, True, True, True),
            CLIContract("flashloan-paper", "src.cli_pr189", True, True, True, True),
            CLIContract("flashloan-shadow", "src.cli_pr189", True, True, True, True),
            CLIContract("flashloan-status", "src.automation_cli_pr189", True, True, True, True),
            CLIContract("flashloan-checks", "src.automation_cli_pr189", True, True, True, True),
        ),
        detected_forbidden_modules=(),
        checked_in_build_artifacts=(),
        legacy_bypass_paths=(),
        mutable_action_refs=0,
        mutable_base_images=0,
        production_assert_count=0,
        import_cycles_present=False,
        source_wheel_surface_match=True,
        offline_build_verified=True,
        release_wheelhouse_signed=True,
        duplicate_tests_present=False,
        broad_quality_quarantine_count=0,
        safe_idle_satisfies_workload_readiness=False,
        ambient_dependency_leak=False,
    )


def test_pr219_gate_accepts_clean_canonical_release_surface() -> None:
    report = evaluate_pr219_artifact_quality(clean_evidence())

    assert report.ready is True
    assert report.state is PR219GateState.READY
    assert report.violations == ()
    assert report.to_dict()["safety_boundary"] == {
        "live_execution_allowed": False,
        "signer_allowed": False,
        "sender_allowed": False,
    }


def test_pr219_gate_requires_all_five_public_cli_contracts() -> None:
    evidence = clean_evidence()
    report = evaluate_pr219_artifact_quality(
        replace(evidence, cli_contracts=evidence.cli_contracts[:-1])
    )
    assert report.ready is False
    assert report.violations[0].code == "missing_required_cli"
    assert report.violations[0].subject == "flashloan-checks"


def test_pr219_gate_blocks_safe_idle_workload_claims() -> None:
    report = evaluate_pr219_artifact_quality(
        replace(clean_evidence(), safe_idle_satisfies_workload_readiness=True)
    )
    assert report.ready is False
    assert report.violations[0].code == "safe_idle_claims_workload_ready"


def test_pr219_gate_blocks_forbidden_sender_namespace_presence() -> None:
    evidence = clean_evidence()
    report = evaluate_pr219_artifact_quality(
        replace(
            evidence,
            installed_modules=(*evidence.installed_modules, "src.submission.dispatch"),
        )
    )
    assert report.ready is False
    assert report.violations[0].code == "forbidden_namespace_packaged"
    assert report.violations[0].subject == "src.submission.dispatch"


def test_pr219_gate_blocks_mutable_ci_and_build_artifact_contamination() -> None:
    report = evaluate_pr219_artifact_quality(
        replace(
            clean_evidence(),
            mutable_action_refs=7,
            mutable_base_images=1,
            checked_in_build_artifacts=("build/", ".pytest_cache/"),
        )
    )
    assert report.ready is False
    assert {v.code for v in report.violations} == {
        "checked_in_build_artifact",
        "mutable_action_refs",
        "mutable_base_images",
    }


def test_pr219_gate_blocks_legacy_source_bypass_paths() -> None:
    report = evaluate_pr219_artifact_quality(
        replace(
            clean_evidence(),
            legacy_bypass_paths=("setup_flashloan.sh", "ecosystem.config.js"),
        )
    )
    assert report.ready is False
    assert {v.code for v in report.violations} == {"legacy_source_bypass"}


def test_pr219_gate_blocks_missing_or_unreachable_controls() -> None:
    evidence = clean_evidence()
    report = evaluate_pr219_artifact_quality(
        replace(
            evidence,
            observed_required_controls=("src.release.manifest",),
            reachable_modules=(
                "src.cli_pr189",
                "src.automation_cli_pr189",
                "src.paper_shadow.runtime",
                "src.release.manifest",
            ),
        )
    )
    assert report.ready is False
    assert {v.code for v in report.violations} == {
        "missing_required_control_trace",
        "unreachable_required_control",
    }


def test_pr219_gate_blocks_assert_cycles_quarantine_and_ambient_leaks() -> None:
    report = evaluate_pr219_artifact_quality(
        replace(
            clean_evidence(),
            production_assert_count=2,
            import_cycles_present=True,
            broad_quality_quarantine_count=3,
            ambient_dependency_leak=True,
        )
    )
    assert report.ready is False
    assert {
        "production_asserts_present",
        "import_cycles_present",
        "broad_quality_quarantine",
        "ambient_dependency_leak",
    } == {v.code for v in report.violations}


def test_pr219_gate_blocks_surface_mismatch_and_unsigned_release_inputs() -> None:
    report = evaluate_pr219_artifact_quality(
        replace(
            clean_evidence(),
            source_wheel_surface_match=False,
            offline_build_verified=False,
            release_wheelhouse_signed=False,
            duplicate_tests_present=True,
        )
    )
    assert report.ready is False
    assert {
        "source_wheel_surface_mismatch",
        "offline_build_unverified",
        "unsigned_release_wheelhouse",
        "duplicate_tests_present",
    } == {v.code for v in report.violations}


def test_pr219_gate_evidence_hash_is_deterministic_under_reordering() -> None:
    left = evaluate_pr219_artifact_quality(clean_evidence())
    evidence = clean_evidence()
    right = evaluate_pr219_artifact_quality(
        replace(
            evidence,
            installed_modules=tuple(reversed(evidence.installed_modules)),
            reachable_modules=tuple(reversed(evidence.reachable_modules)),
            required_controls=tuple(reversed(evidence.required_controls)),
            observed_required_controls=tuple(reversed(evidence.observed_required_controls)),
            cli_contracts=tuple(reversed(evidence.cli_contracts)),
        )
    )
    assert left.evidence_hash == right.evidence_hash


def test_pr219_cli_contract_validates_python_module_names() -> None:
    with pytest.raises(ValueError, match="Python module name"):
        CLIContract(
            name="flashloan-bot",
            entry_module="not/a/module",
            stable_exit_codes=True,
            structured_json_errors=True,
            root_launcher_equivalent=True,
            installed_entrypoint_present=True,
        )


def test_pr219_gate_validates_digest_shapes() -> None:
    with pytest.raises(ValueError, match="sha256 image digest"):
        replace(clean_evidence(), image_digest="bad-digest")
