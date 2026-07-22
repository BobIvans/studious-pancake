"""PR-133 hermetic build and artifact provenance review gate.

This module is offline and side-effect free. It models the PR-133 acceptance
contract without modifying workflows, Dockerfiles, dependency locks, caches,
publishers, senders, wallets, RPC, Jito or live/paper runtime paths.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any

PR133_SCHEMA_VERSION = "pr133.hermetic-artifacts.v1"
PR133_RESULT_SCHEMA_VERSION = "pr133.hermetic-artifacts-result.v1"
PR133_READY_STATE = "hermetic-artifact-provenance-review-ready"
PR133_BLOCKED_STATE = "blocked"

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DOCKER_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

REQUIRED_CONTROLS = (
    "pip_require_hashes",
    "offline_wheelhouse",
    "network_denied_reproducible_build",
    "no_unreviewed_sdist",
    "signatures_verified",
    "trusted_oidc_workload_identity",
    "cache_keys_include_lock_hashes",
    "cache_not_source_of_truth",
    "pr091_real_evidence_required",
    "build_twice_compared",
    "release_trust_root_documented",
    "key_rotation_runbook_documented",
)


class PR133HermeticState(StrEnum):
    BLOCKED = PR133_BLOCKED_STATE
    REVIEW_READY = PR133_READY_STATE


class PR133HermeticArtifactError(ValueError):
    """Raised when PR-133 evidence is malformed or blocked."""


@dataclass(frozen=True, slots=True)
class ActionPinEvidence:
    workflow_path: str
    action: str
    ref: str
    reviewed_commit_sha: str
    require_full_sha_pin: bool = True

    def __post_init__(self) -> None:
        _safe_path(self.workflow_path, "workflow_path")
        _required(self.action, "action")
        _required(self.ref, "ref")
        if not _git_sha(self.reviewed_commit_sha):
            raise PR133HermeticArtifactError(
                "reviewed_commit_sha must be a 40-character git SHA"
            )
        if type(self.require_full_sha_pin) is not bool:
            raise PR133HermeticArtifactError("require_full_sha_pin must be boolean")

    def blocker(self) -> str | None:
        if not self.require_full_sha_pin:
            return f"ACTION_SHA_POLICY_DISABLED:{self.workflow_path}:{self.action}"
        if not _git_sha(self.ref):
            return f"ACTION_REF_NOT_FULL_SHA:{self.workflow_path}:{self.action}"
        if self.ref != self.reviewed_commit_sha:
            return f"ACTION_SHA_NOT_REVIEWED:{self.workflow_path}:{self.action}"
        return None


@dataclass(frozen=True, slots=True)
class DockerImageEvidence:
    image: str
    reference: str
    reviewed_digest: str

    def __post_init__(self) -> None:
        _required(self.image, "image")
        _required(self.reference, "reference")
        if not _docker_digest(self.reviewed_digest):
            raise PR133HermeticArtifactError(
                "reviewed_digest must be a sha256 Docker digest"
            )

    def blocker(self) -> str | None:
        if "@" not in self.reference:
            return f"DOCKER_IMAGE_NOT_PINNED_BY_DIGEST:{self.image}"
        digest = self.reference.rsplit("@", maxsplit=1)[-1]
        if not _docker_digest(digest):
            return f"DOCKER_IMAGE_DIGEST_INVALID:{self.image}"
        if digest != self.reviewed_digest:
            return f"DOCKER_IMAGE_DIGEST_NOT_REVIEWED:{self.image}"
        return None


@dataclass(frozen=True, slots=True)
class DependencyArtifactEvidence:
    name: str
    version: str
    filename: str
    sha256: str
    artifact_type: str
    platform_tag: str
    reviewed: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "name",
            "version",
            "filename",
            "artifact_type",
            "platform_tag",
        ):
            _required(getattr(self, field_name), field_name)
        if not _sha256(self.sha256):
            raise PR133HermeticArtifactError("dependency sha256 must be 64 hex")
        if type(self.reviewed) is not bool:
            raise PR133HermeticArtifactError("reviewed must be boolean")

    def blocker(self) -> str | None:
        package = f"{self.name}=={self.version}"
        if not self.reviewed:
            return f"DEPENDENCY_ARTIFACT_NOT_REVIEWED:{package}"
        if self.artifact_type != "wheel":
            return f"DEPENDENCY_ARTIFACT_NOT_WHEEL:{package}"
        return None


@dataclass(frozen=True, slots=True)
class PR133HermeticArtifactPackage:
    actions: tuple[ActionPinEvidence, ...]
    docker_images: tuple[DockerImageEvidence, ...]
    dependency_artifacts: tuple[DependencyArtifactEvidence, ...]
    controls: dict[str, bool]
    wheel_sha256: str
    container_digest: str
    sbom_sha256: str
    dependency_graph_sha256: str
    provenance_attestation_sha256: str
    reproducible_outputs: bool
    allowed_nondeterminism_documented: bool
    evidence_sha256: str
    schema_version: str = PR133_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR133_SCHEMA_VERSION:
            raise PR133HermeticArtifactError("unsupported PR-133 schema")
        if not self.actions:
            raise PR133HermeticArtifactError("at least one action pin is required")
        if not self.docker_images:
            raise PR133HermeticArtifactError("at least one Docker image is required")
        if not self.dependency_artifacts:
            raise PR133HermeticArtifactError("at least one dependency is required")
        for name in REQUIRED_CONTROLS:
            if type(self.controls.get(name)) is not bool:
                raise PR133HermeticArtifactError(f"missing boolean control:{name}")
        for name in (
            "wheel_sha256",
            "sbom_sha256",
            "dependency_graph_sha256",
            "provenance_attestation_sha256",
            "evidence_sha256",
        ):
            if not _sha256(getattr(self, name)):
                raise PR133HermeticArtifactError(f"{name} must be SHA-256")
        if not _docker_digest(self.container_digest):
            raise PR133HermeticArtifactError("container_digest must be sha256")


@dataclass(frozen=True, slots=True)
class PR133HermeticArtifactReadiness:
    schema_version: str
    state: PR133HermeticState
    release_ready: bool
    live_release_allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    package_sha256: str
    checks_evaluated: int
    metrics_summary: dict[str, int | str | bool]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_pr133_hermetic_artifact_package(
    package: PR133HermeticArtifactPackage,
) -> PR133HermeticArtifactReadiness:
    """Evaluate PR-133 release hermeticity evidence."""

    blockers: list[str] = []
    checks = 0

    def check(condition: bool, reason: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            blockers.append(reason)

    for action in package.actions:
        reason = action.blocker()
        check(reason is None, reason or "ACTION_PIN_OK")
    for image in package.docker_images:
        reason = image.blocker()
        check(reason is None, reason or "DOCKER_DIGEST_OK")
    for artifact in package.dependency_artifacts:
        reason = artifact.blocker()
        check(reason is None, reason or "DEPENDENCY_ARTIFACT_OK")

    for name in REQUIRED_CONTROLS:
        check(package.controls[name], f"CONTROL_MISSING:{name}")

    check(
        package.reproducible_outputs or package.allowed_nondeterminism_documented,
        "REPRODUCIBILITY_NOT_PROVEN_OR_DOCUMENTED",
    )

    unique = tuple(dict.fromkeys(blockers))
    ready = not unique
    return PR133HermeticArtifactReadiness(
        schema_version=PR133_RESULT_SCHEMA_VERSION,
        state=(
            PR133HermeticState.REVIEW_READY
            if ready
            else PR133HermeticState.BLOCKED
        ),
        release_ready=ready,
        live_release_allowed=False,
        blockers=unique,
        warnings=("PR133_REVIEW_ONLY_RELEASE_PATH_UNCHANGED",),
        package_sha256=_digest(package),
        checks_evaluated=checks,
        metrics_summary={
            "actions": len(package.actions),
            "docker_images": len(package.docker_images),
            "dependency_artifacts": len(package.dependency_artifacts),
            "required_controls": len(REQUIRED_CONTROLS),
            "network_denied_build": package.controls[
                "network_denied_reproducible_build"
            ],
        },
    )


def assert_pr133_hermetic_artifact_package(
    package: PR133HermeticArtifactPackage,
) -> PR133HermeticArtifactReadiness:
    result = evaluate_pr133_hermetic_artifact_package(package)
    if not result.release_ready:
        raise PR133HermeticArtifactError(
            f"PR133_BLOCKED:{','.join(result.blockers)}"
        )
    return result


def _digest(package: PR133HermeticArtifactPackage) -> str:
    payload = asdict(package)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _required(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PR133HermeticArtifactError(f"{name} is required")


def _safe_path(value: str, name: str) -> None:
    _required(value, name)
    if value.startswith("/") or ".." in value.split("/"):
        raise PR133HermeticArtifactError(f"{name} must be repo-relative")


def _git_sha(value: str) -> bool:
    return bool(_GIT_SHA_RE.fullmatch(value))


def _sha256(value: str) -> bool:
    return bool(_SHA256_RE.fullmatch(value))


def _docker_digest(value: str) -> bool:
    return bool(_DOCKER_DIGEST_RE.fullmatch(value))
