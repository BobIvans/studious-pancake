from __future__ import annotations

from src.mpr12_post_completion_qualification_lock import (
    REQUIRED_BUNDLE_MEMBERS,
    REQUIRED_INSTALLED_CLIS,
    REQUIRED_PROBES,
    evaluate_mpr12_qualification,
)

DIGEST_A = "1" * 63 + "2"
DIGEST_B = "2" * 63 + "3"
DIGEST_C = "3" * 63 + "4"
DIGEST_D = "4" * 63 + "5"
COMMIT = "a" * 40


def complete_evidence() -> dict[str, object]:
    return {
        "schema_version": "mpr12.post-completion-qualification.v1",
        "roadmap": "MPR-12",
        "capabilities": {
            "live_execution_allowed": False,
            "signer_allowed": False,
            "sender_allowed": False,
            "automatic_cutover_allowed": False,
        },
        "dependencies": [
            {
                "work_package": work_package,
                "status": "accepted_materialized",
                "source_commit": COMMIT,
                "installed_generation_digest": DIGEST_A,
            }
            for work_package in ("MPR-08", "MPR-09", "MPR-10", "MPR-11")
        ],
        "installed_artifacts": [
            {
                "role": "source_export",
                "sha256": DIGEST_A,
                "installed_boundary": True,
                "built_from_clean_source_export": True,
                "completion_ledger_digest": DIGEST_B,
            },
            {
                "role": "wheel",
                "sha256": DIGEST_B,
                "installed_boundary": True,
                "built_from_clean_source_export": True,
                "completion_ledger_digest": DIGEST_B,
            },
            {
                "role": "image",
                "sha256": DIGEST_C,
                "installed_boundary": True,
                "built_from_clean_source_export": True,
                "completion_ledger_digest": DIGEST_B,
            },
        ],
        "installed_cli_results": [
            {
                "name": cli,
                "artifact_role": "wheel",
                "no_network_smoke": "passed",
                "exit_contract": "consistent",
                "policy_digest": DIGEST_C,
            }
            for cli in sorted(REQUIRED_INSTALLED_CLIS)
        ],
        "adversarial_probes": [
            {
                "name": probe,
                "target": "installed_artifact",
                "result": "passed_fail_closed",
                "evidence_digest": DIGEST_D,
                "duration_ms": 1.5,
            }
            for probe in sorted(REQUIRED_PROBES)
        ],
        "regression_lock": {
            "source_only_evidence_allowed": False,
            "test_only_evidence_allowed": False,
            "old_schemas_can_reappear": False,
            "promotion_authority": "mpr12_offline_bundle_only",
            "observed_old_schema_ids": [],
        },
        "rollback_rehearsal": {
            "migration_preserves_previous_generation": True,
            "failed_deployment_blocks_promotion": True,
            "previous_generation_restored": True,
            "manual_recovery_required": False,
            "rehearsal_digest": DIGEST_A,
        },
        "offline_bundle": {
            "signed": True,
            "offline_verifiable": True,
            "immutable": True,
            "bundle_digest": DIGEST_B,
            "members": sorted(REQUIRED_BUNDLE_MEMBERS),
            "verifier_entrypoint": "flashloan-release-evidence verify-mpr12",
            "source_tree_acceptance": "clean_installed_artifact_only",
        },
    }


def assert_blocked(evidence: dict[str, object], reason: str) -> None:
    report = evaluate_mpr12_qualification(evidence)
    assert report.qualification_passed is False
    assert report.promotion_review_allowed is False
    assert reason in report.blockers
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False


def test_complete_installed_artifact_qualification_passes_review_only() -> None:
    report = evaluate_mpr12_qualification(complete_evidence())

    assert report.qualification_passed is True
    assert report.promotion_review_allowed is True
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.blockers == ()


def test_rejects_missing_materialized_mpr_dependency() -> None:
    evidence = complete_evidence()
    evidence["dependencies"] = [
        dep
        for dep in evidence["dependencies"]  # type: ignore[index]
        if dep["work_package"] != "MPR-11"
    ]

    assert_blocked(evidence, "MPR12_REQUIRED_DEPENDENCY_MISSING:MPR-11")


def test_rejects_unaccepted_dependency_generation() -> None:
    evidence = complete_evidence()
    evidence["dependencies"][0]["status"] = "merged_source_only"  # type: ignore[index]

    assert_blocked(evidence, "MPR12_DEPENDENCY_NOT_ACCEPTED:MPR-08")


def test_rejects_source_only_or_test_only_regression_claims() -> None:
    evidence = complete_evidence()
    evidence["regression_lock"]["source_only_evidence_allowed"] = True  # type: ignore[index]

    assert_blocked(evidence, "MPR12_SOURCE_ONLY_EVIDENCE_ALLOWED")

    evidence = complete_evidence()
    evidence["regression_lock"]["test_only_evidence_allowed"] = True  # type: ignore[index]

    assert_blocked(evidence, "MPR12_TEST_ONLY_EVIDENCE_ALLOWED")


def test_rejects_old_schema_reappearance() -> None:
    evidence = complete_evidence()
    evidence["regression_lock"]["observed_old_schema_ids"] = [  # type: ignore[index]
        "pr01.authority-map.v1"
    ]

    assert_blocked(evidence, "MPR12_OLD_SCHEMA_REAPPEARED:pr01.authority-map.v1")


def test_rejects_missing_installed_cli_smoke() -> None:
    evidence = complete_evidence()
    evidence["installed_cli_results"] = [
        cli
        for cli in evidence["installed_cli_results"]  # type: ignore[index]
        if cli["name"] != "flashloan-checks"
    ]

    assert_blocked(evidence, "MPR12_REQUIRED_CLI_MISSING:flashloan-checks")


def test_rejects_probe_not_executed_against_installed_artifact() -> None:
    evidence = complete_evidence()
    evidence["adversarial_probes"][0]["target"] = "source_tree"  # type: ignore[index]

    first_probe = evidence["adversarial_probes"][0]["name"]  # type: ignore[index]
    assert_blocked(evidence, f"MPR12_PROBE_NOT_INSTALLED_ARTIFACT:{first_probe}")


def test_rejects_probe_that_did_not_fail_closed() -> None:
    evidence = complete_evidence()
    evidence["adversarial_probes"][0]["result"] = "green_boolean_claim"  # type: ignore[index]

    first_probe = evidence["adversarial_probes"][0]["name"]  # type: ignore[index]
    assert_blocked(evidence, f"MPR12_PROBE_NOT_FAIL_CLOSED:{first_probe}")


def test_rejects_unsafe_migration_or_deployment_rollback() -> None:
    evidence = complete_evidence()
    evidence["rollback_rehearsal"]["previous_generation_restored"] = False  # type: ignore[index]

    assert_blocked(evidence, "MPR12_PREVIOUS_GENERATION_NOT_RESTORED")


def test_rejects_unsigned_or_source_tree_offline_bundle() -> None:
    evidence = complete_evidence()
    evidence["offline_bundle"]["signed"] = False  # type: ignore[index]

    assert_blocked(evidence, "MPR12_OFFLINE_BUNDLE_NOT_SIGNED")

    evidence = complete_evidence()
    evidence["offline_bundle"]["source_tree_acceptance"] = "source_tree_ok"  # type: ignore[index]

    assert_blocked(evidence, "MPR12_SOURCE_TREE_ACCEPTANCE_NOT_FORBIDDEN")


def test_rejects_live_or_automatic_cutover_capability() -> None:
    evidence = complete_evidence()
    evidence["capabilities"]["live_execution_allowed"] = True  # type: ignore[index]

    assert_blocked(evidence, "MPR12_LIVE_EXECUTION_CAPABILITY_ENABLED")

    evidence = complete_evidence()
    evidence["capabilities"]["automatic_cutover_allowed"] = True  # type: ignore[index]

    assert_blocked(evidence, "MPR12_AUTOMATIC_CUTOVER_ALLOWED")
