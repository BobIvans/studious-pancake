from src.mpr08_completion_release_truth_gate import (
    ArtifactEvidence,
    BuildProvenanceEvidence,
    COMPLETED_FOUNDATION_WORK,
    InstalledCommandEvidence,
    MPR08CompletionReleaseEvidence,
    MPR08GateState,
    POST_COMPLETION_WORK,
    REQUIRED_INSTALLED_COMMANDS,
    REQUIRED_MIRRORS,
    ReleaseMirrorEvidence,
    SignerTrustEvidence,
    WorkPackageEvidence,
    evaluate_mpr08_completion_release_truth,
)


def h(seed: str) -> str:
    return (seed * 64)[:64]


def commit(seed: str) -> str:
    return (seed * 40)[:40]


def complete_evidence(**overrides) -> MPR08CompletionReleaseEvidence:
    source_commit = commit("a")
    tree_hash = h("b")
    ledger_digest = h("c")
    release_model_digest = h("d")

    work_packages = tuple(
        WorkPackageEvidence(work_id, "completed", source_commit, index + 1)
        for index, work_id in enumerate(COMPLETED_FOUNDATION_WORK)
    ) + tuple(
        WorkPackageEvidence(
            work_id,
            "active" if work_id == "MPR-08" else "planned",
            source_commit,
            index + 8,
        )
        for index, work_id in enumerate(POST_COMPLETION_WORK)
    )
    work_ids = tuple(item.work_id for item in work_packages)

    values = {
        "ledger_schema_version": "mpr.completion-ledger.v2",
        "ledger_digest": ledger_digest,
        "release_model_digest": release_model_digest,
        "work_packages": work_packages,
        "mirrors": tuple(
            ReleaseMirrorEvidence(
                name,
                "mpr08.release-mirror.v1",
                1,
                ledger_digest,
                release_model_digest,
                work_ids,
            )
            for name in REQUIRED_MIRRORS
        ),
        "installed_commands": tuple(
            InstalledCommandEvidence(
                command,
                f"src.cli:{command.replace('-', '_')}",
                True,
                True,
                True,
            )
            for command in REQUIRED_INSTALLED_COMMANDS
        ),
        "artifacts": (
            ArtifactEvidence("source", h("e"), source_commit, tree_hash, 10_000, True),
            ArtifactEvidence("wheel", h("1"), source_commit, tree_hash, 20_000, True),
            ArtifactEvidence("image", h("2"), source_commit, tree_hash, 30_000, True),
            ArtifactEvidence("policy", h("3"), source_commit, tree_hash, 4_000, True),
        ),
        "signer_trust": (
            SignerTrustEvidence("release-key-2026q3", h("4"), 1_000, 20_000, False),
        ),
        "selected_release_signer_key_id": "release-key-2026q3",
        "produced_at_unix_ns": 10_000,
        "verified_at_unix_ns": 11_000,
        "max_attestation_age_ns": 5_000,
        "deployment_nonce": "deploy-2026-07-23-001",
        "consumed_deployment_nonces": (),
        "build": BuildProvenanceEvidence(
            source_commit=source_commit,
            git_head_commit=source_commit,
            source_tree_hash=tree_hash,
            clean_tree=True,
            wheel_source_commit=source_commit,
            image_source_commit=source_commit,
            builder_base_image_digest=f"sha256:{h('5')}",
            dependency_lock_hash=h("6"),
            dependencies_hash_locked=True,
            offline_wheelhouse_used=True,
            reproducible_build_verified=True,
        ),
    }
    values.update(overrides)
    return MPR08CompletionReleaseEvidence(**values)


def codes(report):
    return {blocker.code for blocker in report.blockers}


def test_accepts_current_completion_release_truth_contract():
    report = evaluate_mpr08_completion_release_truth(complete_evidence())

    assert report.state == MPR08GateState.READY_FOR_COMPLETION_RELEASE_TRUTH
    assert report.blockers == ()
    assert report.transaction_signer_allowed is False
    assert report.sender_allowed is False
    assert report.live_execution_allowed is False


def test_rejects_ledger_that_cannot_represent_mpr08_generation():
    evidence = complete_evidence(
        ledger_schema_version="pr01.authority-map.v1",
        work_packages=tuple(
            WorkPackageEvidence(work_id, "completed", commit("a"), index + 1)
            for index, work_id in enumerate(COMPLETED_FOUNDATION_WORK)
        ),
    )

    report = evaluate_mpr08_completion_release_truth(evidence)

    assert report.state == MPR08GateState.BLOCKED
    assert "MPR08_BAD_LEDGER_SCHEMA" in codes(report)
    assert "MPR08_ACTIVE_WORK_MISSING" in codes(report)


def test_rejects_stale_or_hand_maintained_release_mirror():
    base = complete_evidence()
    mirrors = base.mirrors[:-1] + (
        ReleaseMirrorEvidence(
            "production-surface",
            "mpr08.release-mirror.v1",
            1,
            h("9"),
            base.release_model_digest,
            tuple(item.work_id for item in base.work_packages),
        ),
    )

    report = evaluate_mpr08_completion_release_truth(complete_evidence(mirrors=mirrors))

    assert "MPR08_MIRROR_LEDGER_DIGEST_MISMATCH" in codes(report)


def test_rejects_unmanifested_or_missing_installed_command():
    commands = tuple(
        command
        for command in complete_evidence().installed_commands
        if command.name != "flashloan-release-evidence"
    )

    report = evaluate_mpr08_completion_release_truth(complete_evidence(installed_commands=commands))

    assert "MPR08_INSTALLED_COMMAND_SET_MISMATCH" in codes(report)


def test_rejects_source_commit_not_grounded_in_built_tree():
    base = complete_evidence().build
    build = BuildProvenanceEvidence(
        source_commit=commit("a"),
        git_head_commit=commit("b"),
        source_tree_hash=base.source_tree_hash,
        clean_tree=True,
        wheel_source_commit=commit("a"),
        image_source_commit=commit("a"),
        builder_base_image_digest=base.builder_base_image_digest,
        dependency_lock_hash=base.dependency_lock_hash,
        dependencies_hash_locked=True,
        offline_wheelhouse_used=True,
        reproducible_build_verified=True,
    )

    report = evaluate_mpr08_completion_release_truth(complete_evidence(build=build))

    assert "MPR08_SOURCE_COMMIT_NOT_GIT_HEAD" in codes(report)


def test_rejects_caller_supplied_unregistered_trust_anchor():
    report = evaluate_mpr08_completion_release_truth(
        complete_evidence(selected_release_signer_key_id="caller-owned-key")
    )

    assert "MPR08_UNREGISTERED_RELEASE_SIGNER" in codes(report)


def test_rejects_future_stale_and_replayed_attestation():
    future = evaluate_mpr08_completion_release_truth(
        complete_evidence(produced_at_unix_ns=12_000, verified_at_unix_ns=11_000)
    )
    stale = evaluate_mpr08_completion_release_truth(
        complete_evidence(
            produced_at_unix_ns=1_000,
            verified_at_unix_ns=11_000,
            max_attestation_age_ns=5_000,
        )
    )
    replay = evaluate_mpr08_completion_release_truth(
        complete_evidence(
            deployment_nonce="deploy-2026-07-23-001",
            consumed_deployment_nonces=("deploy-2026-07-23-001",),
        )
    )

    assert "MPR08_FUTURE_ATTESTATION" in codes(future)
    assert "MPR08_STALE_ATTESTATION" in codes(stale)
    assert "MPR08_REPLAYED_DEPLOYMENT_NONCE" in codes(replay)


def test_rejects_placeholder_hashes_and_unbounded_artifact_hashing():
    artifacts = (
        ArtifactEvidence("wheel", "0" * 64, commit("a"), h("b"), 20_000, False),
    )

    report = evaluate_mpr08_completion_release_truth(complete_evidence(artifacts=artifacts))

    assert "MPR08_BAD_ARTIFACT_DIGEST" in codes(report)
    assert "MPR08_UNBOUNDED_HASHING" in codes(report)


def test_rejects_mutable_builder_and_unhashed_dependency_resolution():
    base = complete_evidence().build
    build = BuildProvenanceEvidence(
        source_commit=base.source_commit,
        git_head_commit=base.git_head_commit,
        source_tree_hash=base.source_tree_hash,
        clean_tree=True,
        wheel_source_commit=base.wheel_source_commit,
        image_source_commit=base.image_source_commit,
        builder_base_image_digest="python:3.13-slim",
        dependency_lock_hash=base.dependency_lock_hash,
        dependencies_hash_locked=False,
        offline_wheelhouse_used=False,
        reproducible_build_verified=False,
    )

    report = evaluate_mpr08_completion_release_truth(complete_evidence(build=build))

    assert "MPR08_BUILDER_BASE_NOT_DIGEST_PINNED" in codes(report)
    assert "MPR08_DEPENDENCIES_NOT_HASH_LOCKED" in codes(report)
    assert "MPR08_OFFLINE_WHEELHOUSE_MISSING" in codes(report)
    assert "MPR08_REPRODUCIBLE_BUILD_NOT_VERIFIED" in codes(report)


def test_rejects_runtime_enablement_in_completion_truth_gate():
    report = evaluate_mpr08_completion_release_truth(
        complete_evidence(
            transaction_signer_requested=True,
            sender_requested=True,
            live_execution_requested=True,
        )
    )

    assert "MPR08_TRANSACTION_SIGNER_REQUESTED" in codes(report)
    assert "MPR08_SENDER_REQUESTED" in codes(report)
    assert "MPR08_LIVE_REQUESTED" in codes(report)
