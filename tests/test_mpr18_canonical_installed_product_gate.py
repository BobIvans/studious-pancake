from __future__ import annotations

import json

from src.mpr18_canonical_installed_product_gate import (
    ArtifactTruthEvidence,
    AuthorityQualityEvidence,
    InstalledCompositionEvidence,
    MPR18Evidence,
    MPR18State,
    REQUIRED_FINDINGS,
    ReleaseBuildEvidence,
    blockers_by_code,
    evaluate_mpr18_evidence,
)

HASHES = {"a": "a" * 64, "b": "b" * 64, "c": "c" * 64}
DIGEST = "sha256:" + "1" * 64
COMMANDS = (
    "flashloan-bot container",
    "flashloan-bot paper",
    "flashloan-bot shadow",
    "flashloan-bot status",
    "flashloan-bot capabilities",
)


def installed(**overrides: object) -> InstalledCompositionEvidence:
    values = {
        "manifest_hashes": HASHES,
        "installed_commands": COMMANDS,
        "shared_state_machine": True,
        "shared_durable_schema": True,
        "safe_idle_diagnostic_only": True,
        "safe_idle_cannot_pass_readiness": True,
        "blocked_paper_default_removed": True,
        "legacy_parallel_roots_removed": True,
    }
    values.update(overrides)
    return InstalledCompositionEvidence(**values)  # type: ignore[arg-type]


def artifact(**overrides: object) -> ArtifactTruthEvidence:
    values = {
        "artifact_hashes": HASHES,
        "source_wheel_image_match": True,
        "packaged_modules_import_from_clean_wheel": True,
        "resources_loaded_from_package_resources": True,
        "installed_e2e_sender_free_trace": True,
        "clean_collection_zero_import_errors": True,
        "release_gate_network_and_ambient_free": True,
    }
    values.update(overrides)
    return ArtifactTruthEvidence(**values)  # type: ignore[arg-type]


def release(**overrides: object) -> ReleaseBuildEvidence:
    values = {
        "release_hashes": HASHES,
        "base_image_digest": DIGEST,
        "checked_in_build_removed": True,
        "egg_info_removed": True,
        "source_launchers_blocked": True,
        "pm2_and_setup_bypasses_blocked": True,
        "one_hash_locked_dependency_graph": True,
        "reproducible_or_equivalent_builds": True,
        "base_image_pinned_by_digest": True,
        "actions_pinned_by_full_sha": True,
    }
    values.update(overrides)
    return ReleaseBuildEvidence(**values)  # type: ignore[arg-type]


def authority(**overrides: object) -> AuthorityQualityEvidence:
    values = {
        "authority_hashes": HASHES,
        "one_versioned_authority_source": True,
        "all_five_cli_surfaces_clean_install_tested": True,
        "full_python_surface_tracked_by_quality": True,
        "documented_non_production_quarantine": True,
        "duplicate_readiness_workflows_retired": True,
        "one_authoritative_branch_protection_check": True,
        "authoritative_check_cannot_swallow_failures": True,
        "every_finding_has_test_and_artifact_link": True,
    }
    values.update(overrides)
    return AuthorityQualityEvidence(**values)  # type: ignore[arg-type]


def evidence(**overrides: object) -> MPR18Evidence:
    values = {
        "finding_coverage": REQUIRED_FINDINGS,
        "installed": installed(),
        "artifact": artifact(),
        "release": release(),
        "authority": authority(),
    }
    values.update(overrides)
    return MPR18Evidence(**values)  # type: ignore[arg-type]


def codes(item: MPR18Evidence) -> set[str]:
    return set(blockers_by_code(evaluate_mpr18_evidence(item)))


def test_valid_evidence_unblocks_only_mpr19_and_mpr20() -> None:
    report = evaluate_mpr18_evidence(evidence())

    assert report.state is MPR18State.READY_FOR_MPR19_MPR20
    assert report.mpr19_mpr20_unblocked is True
    assert report.live_execution_allowed is False
    assert report.sender_allowed is False
    assert report.signer_allowed is False
    assert json.loads(report.to_json())["required_findings"] == list(REQUIRED_FINDINGS)


def test_finding_coverage_is_exact_for_v9_mpr18() -> None:
    assert "MPR18_MISSING_FINDINGS" in codes(
        evidence(finding_coverage=REQUIRED_FINDINGS[:-1])
    )
    assert "MPR18_DUPLICATE_FINDINGS" in codes(
        evidence(finding_coverage=REQUIRED_FINDINGS + (REQUIRED_FINDINGS[0],))
    )
    assert "MPR18_UNKNOWN_FINDINGS" in codes(
        evidence(finding_coverage=REQUIRED_FINDINGS + ("F-999",))
    )


def test_container_paper_shadow_must_share_one_installed_root() -> None:
    item = evidence(
        installed=installed(
            shared_state_machine=False,
            safe_idle_cannot_pass_readiness=False,
        )
    )

    assert "MPR18_INSTALLED_COMPOSITION_INCOMPLETE" in codes(item)


def test_all_five_installed_cli_surfaces_are_required() -> None:
    item = evidence(installed=installed(installed_commands=COMMANDS[:3]))

    assert "MPR18_MISSING_COMMANDS" in codes(item)


def test_artifact_truth_requires_clean_wheel_image_and_e2e_trace() -> None:
    item = evidence(
        artifact=artifact(
            artifact_hashes={"source": "0" * 64},
            source_wheel_image_match=False,
            installed_e2e_sender_free_trace=False,
        )
    )

    assert "MPR18_BAD_ARTIFACT_HASH" in codes(item)
    assert "MPR18_ARTIFACT_TRUTH_INCOMPLETE" in codes(item)


def test_release_build_blocks_generated_trees_and_unpinned_actions() -> None:
    item = evidence(
        release=release(
            base_image_digest="python:3.13-slim",
            checked_in_build_removed=False,
            source_launchers_blocked=False,
            actions_pinned_by_full_sha=False,
        )
    )

    assert "MPR18_BAD_BASE_IMAGE_DIGEST" in codes(item)
    assert "MPR18_RELEASE_BUILD_INCOMPLETE" in codes(item)


def test_authority_quality_requires_single_truth_and_authoritative_ci() -> None:
    item = evidence(
        authority=authority(
            one_versioned_authority_source=False,
            one_authoritative_branch_protection_check=False,
            authoritative_check_cannot_swallow_failures=False,
        )
    )

    assert "MPR18_AUTHORITY_QUALITY_INCOMPLETE" in codes(item)


def test_live_signer_sender_and_source_launcher_paths_are_forbidden() -> None:
    item = evidence(
        live_reachable=True,
        sender_reachable=True,
        signer_reachable=True,
        source_launcher_reachable=True,
    )

    assert "MPR18_LIVE_REACHABLE" in codes(item)
    assert "MPR18_SENDER_REACHABLE" in codes(item)
    assert "MPR18_SIGNER_REACHABLE" in codes(item)
    assert "MPR18_SOURCE_LAUNCHER_REACHABLE" in codes(item)


def test_report_is_deterministic_for_same_evidence() -> None:
    assert evaluate_mpr18_evidence(evidence()).to_json() == evaluate_mpr18_evidence(
        evidence()
    ).to_json()
