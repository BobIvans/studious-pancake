from __future__ import annotations

from dataclasses import replace

from src.mpr17_hermetic_deployment_cutover_gate import (
    BootstrapEvidence,
    CapabilityPosture,
    DependencyLockEvidence,
    DrillEvidence,
    ImageEvidence,
    LauncherRetirementEvidence,
    MPR17Evidence,
    REQUIRED_DEPENDENCIES,
    REQUIRED_DRILLS,
    REQUIRED_FINDINGS,
    REQUIRED_REVIEW_BINDINGS,
    ReviewEvidence,
    SCHEMA_VERSION,
    SoakAndCanaryEvidence,
    evaluate_mpr17_cutover,
)


D = "a" * 64
SOURCE = "b" * 40


def _valid_evidence() -> MPR17Evidence:
    return MPR17Evidence(
        schema_version=SCHEMA_VERSION,
        covered_findings=frozenset(REQUIRED_FINDINGS),
        accepted_dependency_generations={
            work_id: f"{work_id.lower()}-accepted-generation" for work_id in REQUIRED_DEPENDENCIES
        },
        dependency_lock=DependencyLockEvidence(
            generated_from_pyproject=True,
            exact_sync_verified=True,
            hash_locked=True,
            wheelhouse_signed=True,
            sbom_digest=D,
            direct_runtime_dependencies=frozenset({"httpx", "certifi"}),
            installed_runtime_packages=frozenset({"httpx", "httpcore", "certifi"}),
            network_disabled_rebuild=True,
            source_wheel_image_behavior_match=True,
        ),
        image=ImageEvidence(
            builder_base_digest="sha256:" + D,
            runtime_base_digest="sha256:" + D,
            source_commit=SOURCE,
            wheel_digest=D,
            image_digest="sha256:" + D,
            provenance_digest=D,
            sbom_digest=D,
            reproducible_build_verified=True,
            mutable_tags_rejected=True,
        ),
        launchers=LauncherRetirementEvidence(
            production_launchers=frozenset({"digest_pinned_image"}),
            forbidden_launchers_present=frozenset(),
            legacy_setup_removed_or_non_promotable=True,
            pm2_removed_or_non_promotable=True,
            source_checkout_execution_blocked=True,
            only_digest_pinned_artifact_promotable=True,
        ),
        bootstrap=BootstrapEvidence(
            validates_typed_config=True,
            validates_secret_references=True,
            validates_sandbox_policy=True,
            validates_provider_registry=True,
            validates_authority_generations=True,
            rejects_legacy_env_contract=True,
            rejects_raw_secret_environment=True,
            emits_bootstrap_digest=True,
        ),
        drills=tuple(
            DrillEvidence(
                name=name,
                target="installed_artifact",
                passed=True,
                evidence_digest=D,
            )
            for name in REQUIRED_DRILLS
        ),
        soak_and_canary=SoakAndCanaryEvidence(
            installed_artifact_target="signed_wheel_and_image",
            exact_production_composition=True,
            sender_free_soak_days=7,
            sender_free_soak_digest=D,
            tiny_canary_manual=True,
            tiny_canary_finalized_reconciled=True,
            canary_loss_within_policy=True,
            offline_verifiable=True,
            rollback_bundle_digest=D,
        ),
        review=ReviewEvidence(
            independent_review_signed=True,
            review_principal_count=2,
            signed_bindings=frozenset(REQUIRED_REVIEW_BINDINGS),
            exact_source_commit_reviewed=True,
            exact_image_digest_reviewed=True,
            policies_and_stores_reviewed=True,
            soak_and_rollback_reviewed=True,
        ),
    )


def _violation(evidence: MPR17Evidence, expected: str) -> None:
    report = evaluate_mpr17_cutover(evidence)
    assert not report.accepted
    assert any(expected in item for item in report.violations), report.violations
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.automatic_cutover_allowed is False


def test_happy_path_allows_only_promotion_review() -> None:
    report = evaluate_mpr17_cutover(_valid_evidence())

    assert report.accepted is True
    assert report.promotion_review_allowed is True
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
    assert report.automatic_cutover_allowed is False
    assert report.violations == ()


def test_missing_mpr13_16_dependency_fails_closed() -> None:
    evidence = _valid_evidence()
    deps = dict(evidence.accepted_dependency_generations)
    deps.pop("MPR-15")
    _violation(replace(evidence, accepted_dependency_generations=deps), "missing_mpr13_16_dependency")


def test_httpx2_or_httpcore2_in_runtime_lock_fails_closed() -> None:
    evidence = _valid_evidence()
    lock = replace(
        evidence.dependency_lock,
        installed_runtime_packages=evidence.dependency_lock.installed_runtime_packages
        | {"httpx2"},
    )
    _violation(replace(evidence, dependency_lock=lock), "forbidden_runtime_packages")


def test_undeclared_or_unused_dependency_fails_closed() -> None:
    evidence = _valid_evidence()
    lock = replace(
        evidence.dependency_lock,
        undeclared_runtime_packages=frozenset({"httpcore2"}),
        unused_direct_runtime_packages=frozenset({"pytz"}),
    )
    report = evaluate_mpr17_cutover(replace(evidence, dependency_lock=lock))
    assert not report.accepted
    assert any("undeclared_runtime_packages" in item for item in report.violations)
    assert any("unused_direct_runtime_packages" in item for item in report.violations)


def test_mutable_or_unreproducible_image_fails_closed() -> None:
    evidence = _valid_evidence()
    image = replace(
        evidence.image,
        builder_base_digest="python:3.13-slim-bookworm",
        reproducible_build_verified=False,
        mutable_tags_rejected=False,
    )
    report = evaluate_mpr17_cutover(replace(evidence, image=image))
    assert not report.accepted
    assert "builder_base_digest_invalid" in report.violations
    assert "reproducible_build_missing" in report.violations
    assert "mutable_tags_not_rejected" in report.violations


def test_pm2_or_source_checkout_launcher_fails_closed() -> None:
    evidence = _valid_evidence()
    launchers = replace(
        evidence.launchers,
        production_launchers=frozenset({"pm2", "source_checkout"}),
        pm2_removed_or_non_promotable=False,
    )
    report = evaluate_mpr17_cutover(replace(evidence, launchers=launchers))
    assert not report.accepted
    assert any("forbidden_production_launcher" in item for item in report.violations)
    assert "pm2_path_promotable" in report.violations


def test_legacy_setup_or_python_arb_bot_path_fails_closed() -> None:
    evidence = _valid_evidence()
    launchers = replace(
        evidence.launchers,
        forbidden_launchers_present=frozenset({"setup_flashloan", "python_arb_bot"}),
        legacy_setup_removed_or_non_promotable=False,
        source_checkout_execution_blocked=False,
    )
    report = evaluate_mpr17_cutover(replace(evidence, launchers=launchers))
    assert not report.accepted
    assert any("forbidden_production_launcher" in item for item in report.violations)
    assert "legacy_setup_path_promotable" in report.violations
    assert "source_checkout_execution_not_blocked" in report.violations


def test_bootstrap_raw_env_or_legacy_contract_fails_closed() -> None:
    evidence = _valid_evidence()
    bootstrap = replace(
        evidence.bootstrap,
        validates_typed_config=False,
        rejects_legacy_env_contract=False,
        rejects_raw_secret_environment=False,
    )
    report = evaluate_mpr17_cutover(replace(evidence, bootstrap=bootstrap))
    assert not report.accepted
    assert "bootstrap_typed_config_missing" in report.violations
    assert "bootstrap_legacy_env_rejection_missing" in report.violations
    assert "bootstrap_raw_secret_env_rejection_missing" in report.violations


def test_missing_required_drill_fails_closed() -> None:
    evidence = _valid_evidence()
    drills = tuple(drill for drill in evidence.drills if drill.name != "archive_outage")
    _violation(replace(evidence, drills=drills), "missing_drills:archive_outage")


def test_drill_against_special_runner_or_failed_drill_fails_closed() -> None:
    evidence = _valid_evidence()
    drills = list(evidence.drills)
    drills[0] = replace(
        drills[0],
        target="source_checkout",
        passed=False,
        used_special_test_runner=True,
    )
    report = evaluate_mpr17_cutover(replace(evidence, drills=tuple(drills)))
    assert not report.accepted
    assert any("drill_not_installed_artifact" in item for item in report.violations)
    assert any("drill_failed" in item for item in report.violations)
    assert any("drill_used_special_runner" in item for item in report.violations)


def test_sender_free_soak_and_tiny_canary_require_exact_artifact_and_finality() -> None:
    evidence = _valid_evidence()
    soak = replace(
        evidence.soak_and_canary,
        installed_artifact_target="source_tree",
        exact_production_composition=False,
        sender_free_soak_days=6,
        tiny_canary_manual=False,
        tiny_canary_finalized_reconciled=False,
        canary_loss_within_policy=False,
        offline_verifiable=False,
    )
    report = evaluate_mpr17_cutover(replace(evidence, soak_and_canary=soak))
    assert not report.accepted
    assert "soak_target_not_signed_wheel_and_image" in report.violations
    assert "soak_not_exact_production_composition" in report.violations
    assert "sender_free_soak_less_than_7_days" in report.violations
    assert "tiny_canary_not_manual" in report.violations
    assert "tiny_canary_not_finalized_reconciled" in report.violations
    assert "tiny_canary_loss_policy_failed" in report.violations
    assert "soak_canary_not_offline_verifiable" in report.violations


def test_independent_review_must_bind_exact_release_bundle() -> None:
    evidence = _valid_evidence()
    review = replace(
        evidence.review,
        independent_review_signed=False,
        review_principal_count=1,
        signed_bindings=frozenset({"source_commit"}),
        exact_image_digest_reviewed=False,
        policies_and_stores_reviewed=False,
        soak_and_rollback_reviewed=False,
    )
    report = evaluate_mpr17_cutover(replace(evidence, review=review))
    assert not report.accepted
    assert any("missing_review_bindings" in item for item in report.violations)
    assert "independent_review_signature_missing" in report.violations
    assert "insufficient_independent_reviewers" in report.violations
    assert "image_digest_not_reviewed" in report.violations
    assert "policies_stores_not_reviewed" in report.violations
    assert "soak_rollback_not_reviewed" in report.violations


def test_live_signer_sender_or_automatic_cutover_capability_fails_closed() -> None:
    evidence = _valid_evidence()
    caps = CapabilityPosture(
        live_execution_allowed=True,
        signer_allowed=True,
        sender_allowed=True,
        automatic_cutover_allowed=True,
    )
    report = evaluate_mpr17_cutover(replace(evidence, capabilities=caps))
    assert not report.accepted
    assert "live_execution_enabled" in report.violations
    assert "signer_enabled" in report.violations
    assert "sender_enabled" in report.violations
    assert "automatic_cutover_enabled" in report.violations
    assert report.live_execution_allowed is False
    assert report.signer_allowed is False
    assert report.sender_allowed is False
