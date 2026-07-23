"""Side-effect-free MPR-18 installed product and artifact truth gate."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "mpr18.canonical-installed-product-artifact-truth.v1"
LIVE_EXECUTION_ALLOWED = False
SENDER_ALLOWED = False
SIGNER_ALLOWED = False
REQUIRED_NEW_FINDINGS = (
    "F-366",
    "F-367",
    "F-368",
    "F-371",
    "F-372",
    "F-373",
    "F-435",
    "F-436",
    "F-437",
)
REQUIRED_CARRY_FORWARD = tuple(
    [f"F-{number}" for number in range(270, 281)]
    + [f"F-{number}" for number in range(361, 365)]
)
REQUIRED_FINDINGS = REQUIRED_NEW_FINDINGS + REQUIRED_CARRY_FORWARD
REQUIRED_COMMANDS = (
    "flashloan-bot container",
    "flashloan-bot paper",
    "flashloan-bot shadow",
    "flashloan-bot status",
    "flashloan-bot capabilities",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MPR18State(str, Enum):
    """Top-level MPR-18 state."""

    READY_FOR_MPR19_MPR20 = "ready_for_mpr19_mpr20"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class InstalledCompositionEvidence:
    """One installed root for container, paper and shadow."""

    manifest_hashes: Mapping[str, str]
    installed_commands: tuple[str, ...]
    shared_state_machine: bool
    shared_durable_schema: bool
    safe_idle_diagnostic_only: bool
    safe_idle_cannot_pass_readiness: bool
    blocked_paper_default_removed: bool
    legacy_parallel_roots_removed: bool


@dataclass(frozen=True)
class ArtifactTruthEvidence:
    """Clean source/wheel/image and installed replay evidence."""

    artifact_hashes: Mapping[str, str]
    source_wheel_image_match: bool
    packaged_modules_import_from_clean_wheel: bool
    resources_loaded_from_package_resources: bool
    installed_e2e_sender_free_trace: bool
    clean_collection_zero_import_errors: bool
    release_gate_network_and_ambient_free: bool


@dataclass(frozen=True)
class ReleaseBuildEvidence:
    """Build and release paths that cannot bypass the signed artifact."""

    release_hashes: Mapping[str, str]
    base_image_digest: str
    checked_in_build_removed: bool
    egg_info_removed: bool
    source_launchers_blocked: bool
    pm2_and_setup_bypasses_blocked: bool
    one_hash_locked_dependency_graph: bool
    reproducible_or_equivalent_builds: bool
    base_image_pinned_by_digest: bool
    actions_pinned_by_full_sha: bool


@dataclass(frozen=True)
class AuthorityQualityEvidence:
    """Authority, capability, contract and quality truth."""

    authority_hashes: Mapping[str, str]
    one_versioned_authority_source: bool
    all_five_cli_surfaces_clean_install_tested: bool
    full_python_surface_tracked_by_quality: bool
    documented_non_production_quarantine: bool
    duplicate_readiness_workflows_retired: bool
    one_authoritative_branch_protection_check: bool
    authoritative_check_cannot_swallow_failures: bool
    every_finding_has_test_and_artifact_link: bool


@dataclass(frozen=True)
class MPR18Evidence:
    """Complete MPR-18 evidence envelope."""

    finding_coverage: tuple[str, ...]
    installed: InstalledCompositionEvidence
    artifact: ArtifactTruthEvidence
    release: ReleaseBuildEvidence
    authority: AuthorityQualityEvidence
    live_reachable: bool = False
    sender_reachable: bool = False
    signer_reachable: bool = False
    source_launcher_reachable: bool = False


@dataclass(frozen=True)
class MPR18Violation:
    code: str
    message: str


@dataclass(frozen=True)
class MPR18Report:
    schema_version: str
    state: MPR18State
    blockers: tuple[MPR18Violation, ...]
    evidence_hash: str
    mpr19_mpr20_unblocked: bool
    live_execution_allowed: bool = LIVE_EXECUTION_ALLOWED
    sender_allowed: bool = SENDER_ALLOWED
    signer_allowed: bool = SIGNER_ALLOWED
    required_findings: tuple[str, ...] = REQUIRED_FINDINGS

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "blockers": [asdict(blocker) for blocker in self.blockers],
            "evidence_hash": self.evidence_hash,
            "mpr19_mpr20_unblocked": self.mpr19_mpr20_unblocked,
            "live_execution_allowed": self.live_execution_allowed,
            "sender_allowed": self.sender_allowed,
            "signer_allowed": self.signer_allowed,
            "required_findings": list(self.required_findings),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"


def evaluate_mpr18_evidence(evidence: MPR18Evidence) -> MPR18Report:
    """Evaluate the V9 MPR-18 artifact/composition cutover contract."""

    blockers: list[MPR18Violation] = []
    _coverage(evidence.finding_coverage, blockers)
    _installed(evidence.installed, blockers)
    _artifact(evidence.artifact, blockers)
    _release(evidence.release, blockers)
    _authority(evidence.authority, blockers)
    if evidence.live_reachable:
        _add(blockers, "MPR18_LIVE_REACHABLE", "live execution must remain unreachable")
    if evidence.sender_reachable:
        _add(blockers, "MPR18_SENDER_REACHABLE", "sender must remain unreachable")
    if evidence.signer_reachable:
        _add(blockers, "MPR18_SIGNER_REACHABLE", "signer must remain unreachable")
    if evidence.source_launcher_reachable:
        _add(
            blockers,
            "MPR18_SOURCE_LAUNCHER_REACHABLE",
            "source launchers bypass the release",
        )
    unique = tuple(_dedupe(blockers))
    ready = not unique
    return MPR18Report(
        schema_version=SCHEMA_VERSION,
        state=MPR18State.READY_FOR_MPR19_MPR20 if ready else MPR18State.BLOCKED,
        blockers=unique,
        evidence_hash=_stable_hash(evidence),
        mpr19_mpr20_unblocked=ready,
    )


def blockers_by_code(report: MPR18Report) -> Mapping[str, tuple[MPR18Violation, ...]]:
    grouped: dict[str, list[MPR18Violation]] = {}
    for blocker in report.blockers:
        grouped.setdefault(blocker.code, []).append(blocker)
    return {code: tuple(items) for code, items in grouped.items()}


def _coverage(items: Sequence[str], blockers: list[MPR18Violation]) -> None:
    if len(set(items)) != len(items):
        _add(blockers, "MPR18_DUPLICATE_FINDINGS", "finding coverage has duplicates")
    missing = [item for item in REQUIRED_FINDINGS if item not in items]
    extra = [item for item in items if item not in REQUIRED_FINDINGS]
    if missing:
        _add(blockers, "MPR18_MISSING_FINDINGS", f"missing findings: {missing}")
    if extra:
        _add(blockers, "MPR18_UNKNOWN_FINDINGS", f"unknown findings: {extra}")


def _installed(
    evidence: InstalledCompositionEvidence,
    blockers: list[MPR18Violation],
) -> None:
    _hash_map(blockers, "MPR18_BAD_INSTALLED_HASH", evidence.manifest_hashes)
    missing = [
        command
        for command in REQUIRED_COMMANDS
        if command not in evidence.installed_commands
    ]
    if missing:
        _add(blockers, "MPR18_MISSING_COMMANDS", f"missing commands: {missing}")
    if len(set(evidence.installed_commands)) != len(evidence.installed_commands):
        _add(blockers, "MPR18_DUPLICATE_COMMANDS", "installed commands must be unique")
    _require(
        blockers,
        "MPR18_INSTALLED_COMPOSITION_INCOMPLETE",
        shared_state_machine=evidence.shared_state_machine,
        shared_durable_schema=evidence.shared_durable_schema,
        safe_idle_diagnostic_only=evidence.safe_idle_diagnostic_only,
        safe_idle_cannot_pass_readiness=evidence.safe_idle_cannot_pass_readiness,
        blocked_paper_default_removed=evidence.blocked_paper_default_removed,
        legacy_parallel_roots_removed=evidence.legacy_parallel_roots_removed,
    )


def _artifact(evidence: ArtifactTruthEvidence, blockers: list[MPR18Violation]) -> None:
    _hash_map(blockers, "MPR18_BAD_ARTIFACT_HASH", evidence.artifact_hashes)
    _require(
        blockers,
        "MPR18_ARTIFACT_TRUTH_INCOMPLETE",
        source_wheel_image_match=evidence.source_wheel_image_match,
        packaged_modules_import_from_clean_wheel=(
            evidence.packaged_modules_import_from_clean_wheel
        ),
        resources_loaded_from_package_resources=(
            evidence.resources_loaded_from_package_resources
        ),
        installed_e2e_sender_free_trace=evidence.installed_e2e_sender_free_trace,
        clean_collection_zero_import_errors=(
            evidence.clean_collection_zero_import_errors
        ),
        release_gate_network_and_ambient_free=(
            evidence.release_gate_network_and_ambient_free
        ),
    )


def _release(evidence: ReleaseBuildEvidence, blockers: list[MPR18Violation]) -> None:
    _hash_map(blockers, "MPR18_BAD_RELEASE_HASH", evidence.release_hashes)
    if not evidence.base_image_digest.startswith("sha256:") or not _sha(
        evidence.base_image_digest.removeprefix("sha256:")
    ):
        _add(
            blockers,
            "MPR18_BAD_BASE_IMAGE_DIGEST",
            "base image must be digest pinned",
        )
    _require(
        blockers,
        "MPR18_RELEASE_BUILD_INCOMPLETE",
        checked_in_build_removed=evidence.checked_in_build_removed,
        egg_info_removed=evidence.egg_info_removed,
        source_launchers_blocked=evidence.source_launchers_blocked,
        pm2_and_setup_bypasses_blocked=evidence.pm2_and_setup_bypasses_blocked,
        one_hash_locked_dependency_graph=evidence.one_hash_locked_dependency_graph,
        reproducible_or_equivalent_builds=evidence.reproducible_or_equivalent_builds,
        base_image_pinned_by_digest=evidence.base_image_pinned_by_digest,
        actions_pinned_by_full_sha=evidence.actions_pinned_by_full_sha,
    )


def _authority(
    evidence: AuthorityQualityEvidence,
    blockers: list[MPR18Violation],
) -> None:
    _hash_map(blockers, "MPR18_BAD_AUTHORITY_HASH", evidence.authority_hashes)
    _require(
        blockers,
        "MPR18_AUTHORITY_QUALITY_INCOMPLETE",
        one_versioned_authority_source=evidence.one_versioned_authority_source,
        all_five_cli_surfaces_clean_install_tested=(
            evidence.all_five_cli_surfaces_clean_install_tested
        ),
        full_python_surface_tracked_by_quality=(
            evidence.full_python_surface_tracked_by_quality
        ),
        documented_non_production_quarantine=(
            evidence.documented_non_production_quarantine
        ),
        duplicate_readiness_workflows_retired=(
            evidence.duplicate_readiness_workflows_retired
        ),
        one_authoritative_branch_protection_check=(
            evidence.one_authoritative_branch_protection_check
        ),
        authoritative_check_cannot_swallow_failures=(
            evidence.authoritative_check_cannot_swallow_failures
        ),
        every_finding_has_test_and_artifact_link=(
            evidence.every_finding_has_test_and_artifact_link
        ),
    )


def _require(blockers: list[MPR18Violation], code: str, **flags: bool) -> None:
    missing = [name for name, value in flags.items() if value is not True]
    if missing:
        _add(blockers, code, f"missing required flags: {missing}")


def _hash_map(
    blockers: list[MPR18Violation],
    code: str,
    values: Mapping[str, str],
) -> None:
    if not values:
        _add(blockers, code, "hash manifest must be non-empty")
        return
    bad = [name for name, value in values.items() if not _sha(value)]
    if bad:
        _add(blockers, code, f"invalid or placeholder sha256 fields: {bad}")


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.match(value)) and value not in {
        "0" * 64,
        "f" * 64,
    }


def _stable_hash(value: object) -> str:
    encoded = json.dumps(_json(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _json(value: object) -> object:
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json(item) for item in value]
    return value


def _add(blockers: list[MPR18Violation], code: str, message: str) -> None:
    blockers.append(MPR18Violation(code, message))


def _dedupe(blockers: Iterable[MPR18Violation]) -> Iterable[MPR18Violation]:
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker.code, blocker.message)
        if key not in seen:
            seen.add(key)
            yield blocker
