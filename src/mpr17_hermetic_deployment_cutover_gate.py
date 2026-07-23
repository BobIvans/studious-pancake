"""MPR-17 hermetic deployment cutover and final production qualification gate.

This module is intentionally offline and fail-closed.  It validates evidence
shape for the final deployment/cutover package without building images,
touching secrets, contacting providers, starting a signer, or enabling live
submission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, Mapping, Sequence

SCHEMA_VERSION = "mpr17.hermetic-deployment-cutover.v1"
REQUIRED_FINDINGS: FrozenSet[str] = frozenset(
    {"F-361", "F-362", "F-363", "F-364", "F-365"}
)
REQUIRED_DEPENDENCIES: FrozenSet[str] = frozenset(
    {"MPR-13", "MPR-14", "MPR-15", "MPR-16"}
)
REQUIRED_DRILLS: FrozenSet[str] = frozenset(
    {
        "power_loss",
        "restart",
        "failover",
        "disk_full",
        "clock_step",
        "rpc_ambiguity",
        "jito_ambiguity",
        "archive_outage",
    }
)
REQUIRED_REVIEW_BINDINGS: FrozenSet[str] = frozenset(
    {
        "source_commit",
        "image_digest",
        "dependency_lock",
        "policy_bundle",
        "stores",
        "soak_bundle",
        "rollback_bundle",
    }
)
FORBIDDEN_RUNTIME_PACKAGES: FrozenSet[str] = frozenset(
    {"httpx2", "httpcore2"}
)
FORBIDDEN_PRODUCTION_LAUNCHERS: FrozenSet[str] = frozenset(
    {"pm2", "source_checkout", "python_arb_bot", "setup_flashloan"}
)


@dataclass(frozen=True)
class DependencyLockEvidence:
    generated_from_pyproject: bool
    exact_sync_verified: bool
    hash_locked: bool
    wheelhouse_signed: bool
    sbom_digest: str
    direct_runtime_dependencies: FrozenSet[str]
    installed_runtime_packages: FrozenSet[str]
    undeclared_runtime_packages: FrozenSet[str] = frozenset()
    unused_direct_runtime_packages: FrozenSet[str] = frozenset()
    network_disabled_rebuild: bool = False
    source_wheel_image_behavior_match: bool = False


@dataclass(frozen=True)
class ImageEvidence:
    builder_base_digest: str
    runtime_base_digest: str
    source_commit: str
    wheel_digest: str
    image_digest: str
    provenance_digest: str
    sbom_digest: str
    reproducible_build_verified: bool
    mutable_tags_rejected: bool


@dataclass(frozen=True)
class LauncherRetirementEvidence:
    production_launchers: FrozenSet[str]
    forbidden_launchers_present: FrozenSet[str]
    legacy_setup_removed_or_non_promotable: bool
    pm2_removed_or_non_promotable: bool
    source_checkout_execution_blocked: bool
    only_digest_pinned_artifact_promotable: bool


@dataclass(frozen=True)
class BootstrapEvidence:
    validates_typed_config: bool
    validates_secret_references: bool
    validates_sandbox_policy: bool
    validates_provider_registry: bool
    validates_authority_generations: bool
    rejects_legacy_env_contract: bool
    rejects_raw_secret_environment: bool
    emits_bootstrap_digest: bool


@dataclass(frozen=True)
class DrillEvidence:
    name: str
    target: str
    passed: bool
    evidence_digest: str
    used_special_test_runner: bool = False


@dataclass(frozen=True)
class SoakAndCanaryEvidence:
    installed_artifact_target: str
    exact_production_composition: bool
    sender_free_soak_days: int
    sender_free_soak_digest: str
    tiny_canary_manual: bool
    tiny_canary_finalized_reconciled: bool
    canary_loss_within_policy: bool
    offline_verifiable: bool
    rollback_bundle_digest: str


@dataclass(frozen=True)
class ReviewEvidence:
    independent_review_signed: bool
    review_principal_count: int
    signed_bindings: FrozenSet[str]
    exact_source_commit_reviewed: bool
    exact_image_digest_reviewed: bool
    policies_and_stores_reviewed: bool
    soak_and_rollback_reviewed: bool


@dataclass(frozen=True)
class CapabilityPosture:
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_allowed: bool = False
    automatic_cutover_allowed: bool = False


@dataclass(frozen=True)
class MPR17Evidence:
    schema_version: str
    covered_findings: FrozenSet[str]
    accepted_dependency_generations: Mapping[str, str]
    dependency_lock: DependencyLockEvidence
    image: ImageEvidence
    launchers: LauncherRetirementEvidence
    bootstrap: BootstrapEvidence
    drills: Sequence[DrillEvidence]
    soak_and_canary: SoakAndCanaryEvidence
    review: ReviewEvidence
    capabilities: CapabilityPosture = field(default_factory=CapabilityPosture)


@dataclass(frozen=True)
class MPR17Report:
    schema_version: str
    accepted: bool
    promotion_review_allowed: bool
    live_execution_allowed: bool
    signer_allowed: bool
    sender_allowed: bool
    automatic_cutover_allowed: bool
    violations: tuple[str, ...]

    def assert_accepted(self) -> "MPR17Report":
        if not self.accepted:
            raise ValueError("; ".join(self.violations))
        return self


def _valid_sha256_digest(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if value.startswith("sha256:"):
        value = value.removeprefix("sha256:")
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _valid_source_commit(value: str) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        ch in "0123456789abcdef" for ch in value
    )


def _missing(required: Iterable[str], actual: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(required) - set(actual)))


def evaluate_mpr17_cutover(evidence: MPR17Evidence) -> MPR17Report:
    """Validate MPR-17 final cutover evidence.

    A clean report means only that the cutover evidence is reviewable.  It does
    not enable live execution, signer imports, sender transport or automatic
    deployment.
    """

    violations: list[str] = []

    if evidence.schema_version != SCHEMA_VERSION:
        violations.append("schema_version_mismatch")

    missing_findings = _missing(REQUIRED_FINDINGS, evidence.covered_findings)
    if missing_findings:
        violations.append("missing_finding_coverage:" + ",".join(missing_findings))

    missing_deps = _missing(REQUIRED_DEPENDENCIES, evidence.accepted_dependency_generations)
    if missing_deps:
        violations.append("missing_mpr13_16_dependency:" + ",".join(missing_deps))
    for work_id, generation in sorted(evidence.accepted_dependency_generations.items()):
        if work_id in REQUIRED_DEPENDENCIES and not generation:
            violations.append(f"empty_dependency_generation:{work_id}")

    lock = evidence.dependency_lock
    if not lock.generated_from_pyproject:
        violations.append("dependency_lock_not_generated_from_pyproject")
    if not lock.exact_sync_verified:
        violations.append("dependency_exact_sync_missing")
    if not lock.hash_locked:
        violations.append("dependency_hashes_missing")
    if not lock.wheelhouse_signed:
        violations.append("wheelhouse_not_signed")
    if not _valid_sha256_digest(lock.sbom_digest):
        violations.append("dependency_sbom_digest_invalid")
    if lock.undeclared_runtime_packages:
        violations.append(
            "undeclared_runtime_packages:" + ",".join(sorted(lock.undeclared_runtime_packages))
        )
    if lock.unused_direct_runtime_packages:
        violations.append(
            "unused_direct_runtime_packages:" + ",".join(sorted(lock.unused_direct_runtime_packages))
        )
    forbidden_packages = lock.installed_runtime_packages & FORBIDDEN_RUNTIME_PACKAGES
    if forbidden_packages:
        violations.append("forbidden_runtime_packages:" + ",".join(sorted(forbidden_packages)))
    if not lock.network_disabled_rebuild:
        violations.append("network_disabled_rebuild_missing")
    if not lock.source_wheel_image_behavior_match:
        violations.append("source_wheel_image_behavior_not_matched")

    image = evidence.image
    for field_name, digest in (
        ("builder_base_digest", image.builder_base_digest),
        ("runtime_base_digest", image.runtime_base_digest),
        ("wheel_digest", image.wheel_digest),
        ("image_digest", image.image_digest),
        ("provenance_digest", image.provenance_digest),
        ("image_sbom_digest", image.sbom_digest),
    ):
        if not _valid_sha256_digest(digest):
            violations.append(f"{field_name}_invalid")
    if not _valid_source_commit(image.source_commit):
        violations.append("source_commit_invalid")
    if not image.reproducible_build_verified:
        violations.append("reproducible_build_missing")
    if not image.mutable_tags_rejected:
        violations.append("mutable_tags_not_rejected")

    launchers = evidence.launchers
    forbidden_launchers = (
        launchers.production_launchers | launchers.forbidden_launchers_present
    ) & FORBIDDEN_PRODUCTION_LAUNCHERS
    if forbidden_launchers:
        violations.append("forbidden_production_launcher:" + ",".join(sorted(forbidden_launchers)))
    if not launchers.legacy_setup_removed_or_non_promotable:
        violations.append("legacy_setup_path_promotable")
    if not launchers.pm2_removed_or_non_promotable:
        violations.append("pm2_path_promotable")
    if not launchers.source_checkout_execution_blocked:
        violations.append("source_checkout_execution_not_blocked")
    if not launchers.only_digest_pinned_artifact_promotable:
        violations.append("non_digest_pinned_artifact_promotable")

    bootstrap = evidence.bootstrap
    bootstrap_requirements = {
        "typed_config": bootstrap.validates_typed_config,
        "secret_references": bootstrap.validates_secret_references,
        "sandbox_policy": bootstrap.validates_sandbox_policy,
        "provider_registry": bootstrap.validates_provider_registry,
        "authority_generations": bootstrap.validates_authority_generations,
        "legacy_env_rejection": bootstrap.rejects_legacy_env_contract,
        "raw_secret_env_rejection": bootstrap.rejects_raw_secret_environment,
        "bootstrap_digest": bootstrap.emits_bootstrap_digest,
    }
    for name, ok in bootstrap_requirements.items():
        if not ok:
            violations.append(f"bootstrap_{name}_missing")

    drill_names = {drill.name for drill in evidence.drills}
    missing_drills = _missing(REQUIRED_DRILLS, drill_names)
    if missing_drills:
        violations.append("missing_drills:" + ",".join(missing_drills))
    for drill in evidence.drills:
        if drill.target != "installed_artifact":
            violations.append(f"drill_not_installed_artifact:{drill.name}")
        if not drill.passed:
            violations.append(f"drill_failed:{drill.name}")
        if drill.used_special_test_runner:
            violations.append(f"drill_used_special_runner:{drill.name}")
        if not _valid_sha256_digest(drill.evidence_digest):
            violations.append(f"drill_digest_invalid:{drill.name}")

    soak = evidence.soak_and_canary
    if soak.installed_artifact_target != "signed_wheel_and_image":
        violations.append("soak_target_not_signed_wheel_and_image")
    if not soak.exact_production_composition:
        violations.append("soak_not_exact_production_composition")
    if soak.sender_free_soak_days < 7:
        violations.append("sender_free_soak_less_than_7_days")
    if not _valid_sha256_digest(soak.sender_free_soak_digest):
        violations.append("sender_free_soak_digest_invalid")
    if not soak.tiny_canary_manual:
        violations.append("tiny_canary_not_manual")
    if not soak.tiny_canary_finalized_reconciled:
        violations.append("tiny_canary_not_finalized_reconciled")
    if not soak.canary_loss_within_policy:
        violations.append("tiny_canary_loss_policy_failed")
    if not soak.offline_verifiable:
        violations.append("soak_canary_not_offline_verifiable")
    if not _valid_sha256_digest(soak.rollback_bundle_digest):
        violations.append("rollback_bundle_digest_invalid")

    review = evidence.review
    missing_bindings = _missing(REQUIRED_REVIEW_BINDINGS, review.signed_bindings)
    if missing_bindings:
        violations.append("missing_review_bindings:" + ",".join(missing_bindings))
    if not review.independent_review_signed:
        violations.append("independent_review_signature_missing")
    if review.review_principal_count < 2:
        violations.append("insufficient_independent_reviewers")
    if not review.exact_source_commit_reviewed:
        violations.append("source_commit_not_reviewed")
    if not review.exact_image_digest_reviewed:
        violations.append("image_digest_not_reviewed")
    if not review.policies_and_stores_reviewed:
        violations.append("policies_stores_not_reviewed")
    if not review.soak_and_rollback_reviewed:
        violations.append("soak_rollback_not_reviewed")

    caps = evidence.capabilities
    if caps.live_execution_allowed:
        violations.append("live_execution_enabled")
    if caps.signer_allowed:
        violations.append("signer_enabled")
    if caps.sender_allowed:
        violations.append("sender_enabled")
    if caps.automatic_cutover_allowed:
        violations.append("automatic_cutover_enabled")

    accepted = not violations
    return MPR17Report(
        schema_version=SCHEMA_VERSION,
        accepted=accepted,
        promotion_review_allowed=accepted,
        live_execution_allowed=False,
        signer_allowed=False,
        sender_allowed=False,
        automatic_cutover_allowed=False,
        violations=tuple(violations),
    )
