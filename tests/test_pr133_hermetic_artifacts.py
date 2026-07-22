from __future__ import annotations

import pytest

from src.hermetic_artifacts_pr133 import (
    ActionPinEvidence,
    DependencyArtifactEvidence,
    DockerImageEvidence,
    PR133HermeticArtifactError,
    PR133HermeticArtifactPackage,
    assert_pr133_hermetic_artifact_package,
    evaluate_pr133_hermetic_artifact_package,
)

GIT_SHA = "a" * 40
OTHER_GIT_SHA = "b" * 40
HASH = "c" * 64
OTHER_HASH = "d" * 64
DOCKER_DIGEST = "sha256:" + HASH
OTHER_DOCKER_DIGEST = "sha256:" + OTHER_HASH


def _controls(**overrides: bool) -> dict[str, bool]:
    controls = {
        "pip_require_hashes": True,
        "offline_wheelhouse": True,
        "network_denied_reproducible_build": True,
        "no_unreviewed_sdist": True,
        "signatures_verified": True,
        "trusted_oidc_workload_identity": True,
        "cache_keys_include_lock_hashes": True,
        "cache_not_source_of_truth": True,
        "pr091_real_evidence_required": True,
        "build_twice_compared": True,
        "release_trust_root_documented": True,
        "key_rotation_runbook_documented": True,
    }
    controls.update(overrides)
    return controls


def _action(**overrides: object) -> ActionPinEvidence:
    values: dict[str, object] = {
        "workflow_path": ".github/workflows/ci.yml",
        "action": "actions/checkout",
        "ref": GIT_SHA,
        "reviewed_commit_sha": GIT_SHA,
    }
    values.update(overrides)
    return ActionPinEvidence(**values)  # type: ignore[arg-type]


def _docker(**overrides: object) -> DockerImageEvidence:
    values: dict[str, object] = {
        "image": "python",
        "reference": "python@" + DOCKER_DIGEST,
        "reviewed_digest": DOCKER_DIGEST,
    }
    values.update(overrides)
    return DockerImageEvidence(**values)  # type: ignore[arg-type]


def _dependency(**overrides: object) -> DependencyArtifactEvidence:
    values: dict[str, object] = {
        "name": "pytest",
        "version": "8.4.1",
        "filename": "pytest-8.4.1-py3-none-any.whl",
        "sha256": HASH,
        "artifact_type": "wheel",
        "platform_tag": "py3-none-any",
    }
    values.update(overrides)
    return DependencyArtifactEvidence(**values)  # type: ignore[arg-type]


def _package(**overrides: object) -> PR133HermeticArtifactPackage:
    values: dict[str, object] = {
        "actions": (_action(),),
        "docker_images": (_docker(),),
        "dependency_artifacts": (_dependency(),),
        "controls": _controls(),
        "wheel_sha256": HASH,
        "container_digest": DOCKER_DIGEST,
        "sbom_sha256": HASH,
        "dependency_graph_sha256": HASH,
        "provenance_attestation_sha256": HASH,
        "reproducible_outputs": True,
        "allowed_nondeterminism_documented": False,
        "evidence_sha256": HASH,
    }
    values.update(overrides)
    return PR133HermeticArtifactPackage(**values)  # type: ignore[arg-type]


def test_pr133_complete_package_is_review_ready() -> None:
    result = assert_pr133_hermetic_artifact_package(_package())

    assert result.release_ready is True
    assert result.live_release_allowed is False
    assert result.blockers == ()
    assert result.state.value == "hermetic-artifact-provenance-review-ready"


def test_pr133_mutable_action_tag_blocks_release() -> None:
    result = evaluate_pr133_hermetic_artifact_package(
        _package(actions=(_action(ref="v4"),))
    )

    assert result.release_ready is False
    assert any(
        blocker.startswith("ACTION_REF_NOT_FULL_SHA")
        for blocker in result.blockers
    )


def test_pr133_unreviewed_action_sha_blocks_release() -> None:
    result = evaluate_pr133_hermetic_artifact_package(
        _package(actions=(_action(ref=OTHER_GIT_SHA),))
    )

    assert result.release_ready is False
    assert "ACTION_SHA_NOT_REVIEWED:.github/workflows/ci.yml:actions/checkout" in (
        result.blockers
    )


def test_pr133_docker_tag_without_digest_blocks_release() -> None:
    result = evaluate_pr133_hermetic_artifact_package(
        _package(docker_images=(_docker(reference="python:3.13-slim"),))
    )

    assert result.release_ready is False
    assert "DOCKER_IMAGE_NOT_PINNED_BY_DIGEST:python" in result.blockers


def test_pr133_docker_digest_must_match_reviewed_digest() -> None:
    result = evaluate_pr133_hermetic_artifact_package(
        _package(
            docker_images=(
                _docker(reference="python@" + OTHER_DOCKER_DIGEST),
            )
        )
    )

    assert result.release_ready is False
    assert "DOCKER_IMAGE_DIGEST_NOT_REVIEWED:python" in result.blockers


def test_pr133_dependency_requires_reviewed_wheel_hash() -> None:
    result = evaluate_pr133_hermetic_artifact_package(
        _package(
            dependency_artifacts=(
                _dependency(artifact_type="sdist", reviewed=False),
            )
        )
    )

    assert result.release_ready is False
    assert "DEPENDENCY_ARTIFACT_NOT_REVIEWED:pytest==8.4.1" in result.blockers


def test_pr133_missing_release_controls_block() -> None:
    result = evaluate_pr133_hermetic_artifact_package(
        _package(
            controls=_controls(
                pip_require_hashes=False,
                offline_wheelhouse=False,
                network_denied_reproducible_build=False,
            )
        )
    )

    assert result.release_ready is False
    assert "CONTROL_MISSING:pip_require_hashes" in result.blockers
    assert "CONTROL_MISSING:offline_wheelhouse" in result.blockers
    assert "CONTROL_MISSING:network_denied_reproducible_build" in result.blockers


def test_pr133_reproducibility_must_be_proven_or_documented() -> None:
    result = evaluate_pr133_hermetic_artifact_package(
        _package(
            reproducible_outputs=False,
            allowed_nondeterminism_documented=False,
        )
    )

    assert result.release_ready is False
    assert "REPRODUCIBILITY_NOT_PROVEN_OR_DOCUMENTED" in result.blockers


def test_pr133_malformed_hashes_fail_fast() -> None:
    with pytest.raises(PR133HermeticArtifactError):
        _package(evidence_sha256="not-a-hash")
