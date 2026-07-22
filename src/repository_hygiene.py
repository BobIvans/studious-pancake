"""PR-177 repository evolution hygiene and generated-artifact governance.

This module is deliberately side-effect free. It does not delete files, mutate the
package, run generators, read the working tree, alter runtime imports, or enable
paper/live behaviour. It provides one deterministic policy/evaluator layer that
can be wired into CI/release qualification later.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

PR177_SCHEMA_VERSION = "pr177.repository-hygiene-governance.v1"


class PR177HygieneError(ValueError):
    """Raised when a hygiene policy object is malformed."""


class ArtifactClass(str, Enum):
    """Repository artifact classes with explicit production semantics."""

    SOURCE = "source"
    GENERATED = "generated"
    FIXTURE = "fixture"
    EVIDENCE = "evidence"
    DOCUMENTATION = "documentation"
    TEMPORARY = "temporary"
    FORBIDDEN = "forbidden"


class ArtifactLifecycle(str, Enum):
    """Lifecycle states for source, docs, fixtures, and generated artifacts."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    QUARANTINED = "quarantined"
    SCHEDULED_FOR_REMOVAL = "scheduled-for-removal"
    REMOVED = "removed"


class ArtifactSeverity(str, Enum):
    """Finding severity used by the PR-177 evaluator."""

    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


class DomainOwnerState(str, Enum):
    """Whether a domain owner is production-active or only historical."""

    PRODUCTION_ACTIVE = "production-active"
    TEST_ONLY = "test-only"
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class SupersessionMetadata:
    """Machine-readable canonical/superseded relationship."""

    canonical_id: str
    owner: str
    status: ArtifactLifecycle
    supersedes: tuple[str, ...] = ()
    superseded_by: str | None = None
    removal_release: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "owner": self.owner,
            "status": self.status.value,
            "supersedes": list(self.supersedes),
            "superseded_by": self.superseded_by,
            "removal_release": self.removal_release,
        }


@dataclass(frozen=True, slots=True)
class GeneratedArtifactManifest:
    """Reproducibility contract for committed generated output."""

    generator_command: str
    generator_version: str
    source_input_hashes: tuple[str, ...]
    deterministic_hash: str
    freshness_expires_at: str | None
    verification_test: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "generator_command": self.generator_command,
            "generator_version": self.generator_version,
            "source_input_hashes": list(self.source_input_hashes),
            "deterministic_hash": self.deterministic_hash,
            "freshness_expires_at": self.freshness_expires_at,
            "verification_test": self.verification_test,
        }


@dataclass(frozen=True, slots=True)
class QuarantineMetadata:
    """Owner and removal metadata for quarantined code/artifacts."""

    owner: str
    reason: str
    removal_release: str
    removal_owner: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "reason": self.reason,
            "removal_release": self.removal_release,
            "removal_owner": self.removal_owner,
        }


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """One path-level repository artifact inventory record."""

    path: str
    artifact_class: ArtifactClass
    lifecycle: ArtifactLifecycle
    domain_id: str | None = None
    root_file: bool = False
    empty_file: bool = False
    included_in_production_wheel: bool = False
    generated: GeneratedArtifactManifest | None = None
    supersession: SupersessionMetadata | None = None
    quarantine: QuarantineMetadata | None = None
    evidence_expires_at: str | None = None
    stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "artifact_class": self.artifact_class.value,
            "lifecycle": self.lifecycle.value,
            "domain_id": self.domain_id,
            "root_file": self.root_file,
            "empty_file": self.empty_file,
            "included_in_production_wheel": self.included_in_production_wheel,
            "generated": _maybe_to_dict(self.generated),
            "supersession": _maybe_to_dict(self.supersession),
            "quarantine": _maybe_to_dict(self.quarantine),
            "evidence_expires_at": self.evidence_expires_at,
            "stale": self.stale,
        }


@dataclass(frozen=True, slots=True)
class DomainOwnerRecord:
    """Production-domain ownership declaration."""

    domain_id: str
    owner_path: str
    state: DomainOwnerState
    owner_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "owner_path": self.owner_path,
            "state": self.state.value,
            "owner_hash": self.owner_hash,
        }


@dataclass(frozen=True, slots=True)
class RepositorySurfaceBudget:
    """Budget for repository growth and production surface area."""

    max_production_python_modules: int
    max_wheel_files: int
    max_test_modules: int
    max_docs_gate_files: int
    max_duplicate_domain_count: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "max_production_python_modules": self.max_production_python_modules,
            "max_wheel_files": self.max_wheel_files,
            "max_test_modules": self.max_test_modules,
            "max_docs_gate_files": self.max_docs_gate_files,
            "max_duplicate_domain_count": self.max_duplicate_domain_count,
        }


@dataclass(frozen=True, slots=True)
class RepositorySurfaceCounts:
    """Observed repository surface counts."""

    production_python_modules: int
    wheel_files: int
    test_modules: int
    docs_gate_files: int
    duplicate_domain_count: int

    def to_dict(self) -> dict[str, int]:
        return {
            "production_python_modules": self.production_python_modules,
            "wheel_files": self.wheel_files,
            "test_modules": self.test_modules,
            "docs_gate_files": self.docs_gate_files,
            "duplicate_domain_count": self.duplicate_domain_count,
        }


@dataclass(frozen=True, slots=True)
class HygieneFinding:
    """Machine-readable hygiene finding."""

    code: str
    severity: ArtifactSeverity
    path: str | None = None
    domain_id: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "path": self.path,
            "domain_id": self.domain_id,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class RepositoryHygieneResult:
    """PR-177 evaluation output."""

    schema_version: str
    release_branch_clean: bool
    production_wheel_clean: bool
    artifact_inventory_complete: bool
    generated_artifacts_reproducible: bool
    duplicate_domains_blocked: bool
    supersession_metadata_complete: bool
    quarantine_lifecycle_complete: bool
    surface_budget_ok: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    findings: tuple[HygieneFinding, ...]
    result_hash: str

    @property
    def hygiene_ok(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "release_branch_clean": self.release_branch_clean,
            "production_wheel_clean": self.production_wheel_clean,
            "artifact_inventory_complete": self.artifact_inventory_complete,
            "generated_artifacts_reproducible": self.generated_artifacts_reproducible,
            "duplicate_domains_blocked": self.duplicate_domains_blocked,
            "supersession_metadata_complete": self.supersession_metadata_complete,
            "quarantine_lifecycle_complete": self.quarantine_lifecycle_complete,
            "surface_budget_ok": self.surface_budget_ok,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "findings": [finding.to_dict() for finding in self.findings],
            "result_hash": self.result_hash,
            "hygiene_ok": self.hygiene_ok,
        }


def evaluate_repository_hygiene(
    *,
    artifacts: Sequence[ArtifactRecord],
    domain_owners: Sequence[DomainOwnerRecord],
    surface_counts: RepositorySurfaceCounts,
    surface_budget: RepositorySurfaceBudget,
    release_branch: bool = False,
) -> RepositoryHygieneResult:
    """Evaluate PR-177 repository hygiene without touching the filesystem."""

    findings: list[HygieneFinding] = []
    for artifact in artifacts:
        findings.extend(_artifact_findings(artifact, release_branch=release_branch))

    findings.extend(_duplicate_domain_findings(domain_owners))
    findings.extend(_surface_budget_findings(surface_counts, surface_budget))

    blockers = tuple(
        dict.fromkeys(
            finding.code for finding in findings if finding.severity == ArtifactSeverity.BLOCKER
        )
    )
    warnings = tuple(
        dict.fromkeys(
            finding.code for finding in findings if finding.severity == ArtifactSeverity.WARNING
        )
    )

    release_branch_clean = not any(
        finding.code.startswith("RELEASE_BRANCH_") for finding in findings
    )
    production_wheel_clean = not any(
        finding.code in {"TEMPORARY_IN_PRODUCTION_WHEEL", "FORBIDDEN_IN_PRODUCTION_WHEEL"}
        for finding in findings
    )
    artifact_inventory_complete = not any(
        finding.code in {"UNCLASSIFIED_ARTIFACT", "EMPTY_UNEXPLAINED_ROOT_FILE"}
        for finding in findings
    )
    generated_artifacts_reproducible = not any(
        finding.code.startswith("GENERATED_") for finding in findings
    )
    duplicate_domains_blocked = not any(
        finding.code == "DUPLICATE_PRODUCTION_DOMAIN_OWNER" for finding in findings
    )
    supersession_metadata_complete = not any(
        finding.code.startswith("SUPERSESSION_") for finding in findings
    )
    quarantine_lifecycle_complete = not any(
        finding.code.startswith("QUARANTINE_") for finding in findings
    )
    surface_budget_ok = not any(
        finding.code.startswith("SURFACE_BUDGET_") for finding in findings
    )

    result_payload = {
        "schema_version": PR177_SCHEMA_VERSION,
        "release_branch_clean": release_branch_clean,
        "production_wheel_clean": production_wheel_clean,
        "artifact_inventory_complete": artifact_inventory_complete,
        "generated_artifacts_reproducible": generated_artifacts_reproducible,
        "duplicate_domains_blocked": duplicate_domains_blocked,
        "supersession_metadata_complete": supersession_metadata_complete,
        "quarantine_lifecycle_complete": quarantine_lifecycle_complete,
        "surface_budget_ok": surface_budget_ok,
        "blockers": list(blockers),
        "warnings": list(warnings),
        "findings": [finding.to_dict() for finding in findings],
        "surface_counts": surface_counts.to_dict(),
        "surface_budget": surface_budget.to_dict(),
    }
    result_hash = _hash_json(result_payload)
    return RepositoryHygieneResult(
        schema_version=PR177_SCHEMA_VERSION,
        release_branch_clean=release_branch_clean,
        production_wheel_clean=production_wheel_clean,
        artifact_inventory_complete=artifact_inventory_complete,
        generated_artifacts_reproducible=generated_artifacts_reproducible,
        duplicate_domains_blocked=duplicate_domains_blocked,
        supersession_metadata_complete=supersession_metadata_complete,
        quarantine_lifecycle_complete=quarantine_lifecycle_complete,
        surface_budget_ok=surface_budget_ok,
        blockers=blockers,
        warnings=warnings,
        findings=tuple(findings),
        result_hash=result_hash,
    )


def assert_repository_hygiene(result: RepositoryHygieneResult) -> None:
    """Raise if repository hygiene has blocking findings."""

    if result.blockers:
        raise PR177HygieneError(
            "repository hygiene has blockers: " + ", ".join(result.blockers)
        )


def _artifact_findings(
    artifact: ArtifactRecord,
    *,
    release_branch: bool,
) -> tuple[HygieneFinding, ...]:
    _validate_artifact(artifact)
    findings: list[HygieneFinding] = []
    path = artifact.path

    if _is_tmp_or_marker(path):
        findings.append(
            _blocker("TEMPORARY_OR_ACCIDENTAL_MARKER", path=path)
        )
    if _is_cache_or_local_state(path):
        findings.append(_blocker("CACHE_OR_LOCAL_STATE_ARTIFACT", path=path))
    if artifact.root_file and artifact.empty_file and artifact.artifact_class not in {
        ArtifactClass.SOURCE,
        ArtifactClass.DOCUMENTATION,
    }:
        findings.append(_blocker("EMPTY_UNEXPLAINED_ROOT_FILE", path=path))
    if artifact.artifact_class == ArtifactClass.FORBIDDEN:
        findings.append(_blocker("FORBIDDEN_ARTIFACT", path=path))
    if artifact.artifact_class == ArtifactClass.GENERATED:
        findings.extend(_generated_findings(artifact))
    if artifact.artifact_class in {ArtifactClass.DOCUMENTATION, ArtifactClass.EVIDENCE}:
        findings.extend(_supersession_findings(artifact))
    if artifact.lifecycle == ArtifactLifecycle.QUARANTINED:
        findings.extend(_quarantine_findings(artifact))
    if artifact.lifecycle == ArtifactLifecycle.SCHEDULED_FOR_REMOVAL:
        if artifact.supersession is None or not artifact.supersession.removal_release:
            findings.append(_blocker("SUPERSESSION_REMOVAL_RELEASE_MISSING", path=path))
    if artifact.included_in_production_wheel:
        if artifact.artifact_class == ArtifactClass.TEMPORARY:
            findings.append(_blocker("TEMPORARY_IN_PRODUCTION_WHEEL", path=path))
        if artifact.artifact_class == ArtifactClass.FORBIDDEN:
            findings.append(_blocker("FORBIDDEN_IN_PRODUCTION_WHEEL", path=path))
        if artifact.lifecycle in {
            ArtifactLifecycle.QUARANTINED,
            ArtifactLifecycle.SCHEDULED_FOR_REMOVAL,
            ArtifactLifecycle.REMOVED,
        }:
            findings.append(_blocker("NON_ACTIVE_ARTIFACT_IN_PRODUCTION_WHEEL", path=path))
    if artifact.artifact_class == ArtifactClass.EVIDENCE:
        if artifact.evidence_expires_at is None:
            findings.append(_blocker("EVIDENCE_EXPIRY_MISSING", path=path))
        if artifact.stale:
            findings.append(_blocker("STALE_EVIDENCE_ARTIFACT", path=path))
    if release_branch:
        findings.extend(_release_branch_findings(artifact))
    return tuple(findings)


def _generated_findings(artifact: ArtifactRecord) -> tuple[HygieneFinding, ...]:
    findings: list[HygieneFinding] = []
    generated = artifact.generated
    if generated is None:
        return (_blocker("GENERATED_MANIFEST_MISSING", path=artifact.path),)
    if not generated.generator_command.strip():
        findings.append(_blocker("GENERATED_COMMAND_MISSING", path=artifact.path))
    if not generated.generator_version.strip():
        findings.append(_blocker("GENERATED_VERSION_MISSING", path=artifact.path))
    if not generated.source_input_hashes:
        findings.append(_blocker("GENERATED_INPUT_HASHES_MISSING", path=artifact.path))
    for source_hash in generated.source_input_hashes:
        if not _looks_like_sha256(source_hash):
            findings.append(_blocker("GENERATED_INPUT_HASH_INVALID", path=artifact.path))
            break
    if not _looks_like_sha256(generated.deterministic_hash):
        findings.append(_blocker("GENERATED_DETERMINISTIC_HASH_INVALID", path=artifact.path))
    if not generated.verification_test.strip():
        findings.append(_blocker("GENERATED_VERIFICATION_TEST_MISSING", path=artifact.path))
    return tuple(findings)


def _supersession_findings(artifact: ArtifactRecord) -> tuple[HygieneFinding, ...]:
    if artifact.supersession is None:
        return (_blocker("SUPERSESSION_METADATA_MISSING", path=artifact.path),)
    findings: list[HygieneFinding] = []
    supersession = artifact.supersession
    if not supersession.canonical_id.strip():
        findings.append(_blocker("SUPERSESSION_CANONICAL_ID_MISSING", path=artifact.path))
    if not supersession.owner.strip():
        findings.append(_blocker("SUPERSESSION_OWNER_MISSING", path=artifact.path))
    if supersession.status in {
        ArtifactLifecycle.DEPRECATED,
        ArtifactLifecycle.SCHEDULED_FOR_REMOVAL,
        ArtifactLifecycle.REMOVED,
    } and not supersession.superseded_by:
        findings.append(_blocker("SUPERSESSION_TARGET_MISSING", path=artifact.path))
    return tuple(findings)


def _quarantine_findings(artifact: ArtifactRecord) -> tuple[HygieneFinding, ...]:
    quarantine = artifact.quarantine
    if quarantine is None:
        return (_blocker("QUARANTINE_METADATA_MISSING", path=artifact.path),)
    findings: list[HygieneFinding] = []
    if not quarantine.owner.strip():
        findings.append(_blocker("QUARANTINE_OWNER_MISSING", path=artifact.path))
    if not quarantine.removal_owner.strip():
        findings.append(_blocker("QUARANTINE_REMOVAL_OWNER_MISSING", path=artifact.path))
    if not quarantine.removal_release.strip():
        findings.append(_blocker("QUARANTINE_REMOVAL_RELEASE_MISSING", path=artifact.path))
    if not quarantine.reason.strip():
        findings.append(_blocker("QUARANTINE_REASON_MISSING", path=artifact.path))
    return tuple(findings)


def _duplicate_domain_findings(
    owners: Sequence[DomainOwnerRecord],
) -> tuple[HygieneFinding, ...]:
    by_domain: dict[str, list[DomainOwnerRecord]] = {}
    for owner in owners:
        _validate_domain_owner(owner)
        if owner.state == DomainOwnerState.PRODUCTION_ACTIVE:
            by_domain.setdefault(owner.domain_id, []).append(owner)
    findings: list[HygieneFinding] = []
    for domain_id, active_owners in sorted(by_domain.items()):
        if len(active_owners) > 1:
            paths = ", ".join(owner.owner_path for owner in active_owners)
            findings.append(
                _blocker(
                    "DUPLICATE_PRODUCTION_DOMAIN_OWNER",
                    domain_id=domain_id,
                    message=paths,
                )
            )
    return tuple(findings)


def _surface_budget_findings(
    counts: RepositorySurfaceCounts,
    budget: RepositorySurfaceBudget,
) -> tuple[HygieneFinding, ...]:
    findings: list[HygieneFinding] = []
    if counts.production_python_modules > budget.max_production_python_modules:
        findings.append(_blocker("SURFACE_BUDGET_PRODUCTION_MODULES_EXCEEDED"))
    if counts.wheel_files > budget.max_wheel_files:
        findings.append(_blocker("SURFACE_BUDGET_WHEEL_FILES_EXCEEDED"))
    if counts.test_modules > budget.max_test_modules:
        findings.append(_blocker("SURFACE_BUDGET_TEST_MODULES_EXCEEDED"))
    if counts.docs_gate_files > budget.max_docs_gate_files:
        findings.append(_blocker("SURFACE_BUDGET_DOCS_GATE_FILES_EXCEEDED"))
    if counts.duplicate_domain_count > budget.max_duplicate_domain_count:
        findings.append(_blocker("SURFACE_BUDGET_DUPLICATE_DOMAINS_EXCEEDED"))
    return tuple(findings)


def _release_branch_findings(artifact: ArtifactRecord) -> tuple[HygieneFinding, ...]:
    findings: list[HygieneFinding] = []
    if artifact.artifact_class in {ArtifactClass.TEMPORARY, ArtifactClass.FORBIDDEN}:
        findings.append(_blocker("RELEASE_BRANCH_TEMPORARY_OR_FORBIDDEN", path=artifact.path))
    if _is_cache_or_local_state(artifact.path):
        findings.append(_blocker("RELEASE_BRANCH_CACHE_OR_LOCAL_STATE", path=artifact.path))
    if artifact.artifact_class == ArtifactClass.EVIDENCE and artifact.stale:
        findings.append(_blocker("RELEASE_BRANCH_STALE_EVIDENCE", path=artifact.path))
    if artifact.lifecycle in {
        ArtifactLifecycle.QUARANTINED,
        ArtifactLifecycle.SCHEDULED_FOR_REMOVAL,
        ArtifactLifecycle.REMOVED,
    } and artifact.included_in_production_wheel:
        findings.append(_blocker("RELEASE_BRANCH_NON_ACTIVE_WHEEL_ARTIFACT", path=artifact.path))
    return tuple(findings)


def _validate_artifact(artifact: ArtifactRecord) -> None:
    _require_nonempty(artifact.path, "artifact.path")
    if artifact.path.startswith("/") or ".." in artifact.path.split("/"):
        raise PR177HygieneError("artifact path must be repository-relative")
    if artifact.domain_id is not None:
        _validate_stable_domain_id(artifact.domain_id)


def _validate_domain_owner(owner: DomainOwnerRecord) -> None:
    _validate_stable_domain_id(owner.domain_id)
    _require_nonempty(owner.owner_path, "owner_path")
    _require_hash(owner.owner_hash, "owner_hash")


def _validate_stable_domain_id(domain_id: str) -> None:
    _require_nonempty(domain_id, "domain_id")
    lowered = domain_id.lower()
    if lowered.startswith("pr-") or lowered.startswith("pr_"):
        raise PR177HygieneError("domain_id must not use PR-number identity")
    if not all(ch.islower() or ch.isdigit() or ch in {".", "-"} for ch in domain_id):
        raise PR177HygieneError("domain_id must be lowercase dotted/kebab identity")


def _is_tmp_or_marker(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    return name.startswith("tmp_") or "accidental_pr_marker" in name


def _is_cache_or_local_state(path: str) -> bool:
    parts = set(path.split("/"))
    name = path.split("/")[-1]
    return bool(
        {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"} & parts
        or name.endswith(".pyc")
        or name.endswith(".db")
        or name.endswith(".sqlite")
        or name.endswith(".sqlite3")
    )


def _blocker(
    code: str,
    *,
    path: str | None = None,
    domain_id: str | None = None,
    message: str | None = None,
) -> HygieneFinding:
    return HygieneFinding(
        code=code,
        severity=ArtifactSeverity.BLOCKER,
        path=path,
        domain_id=domain_id,
        message=message,
    )


def _maybe_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return value.to_dict()


def _hash_json(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _looks_like_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _require_hash(value: str, field: str) -> None:
    _require_nonempty(value, field)
    if not _looks_like_sha256(value):
        raise PR177HygieneError(f"{field} must be a lowercase sha256 digest")


def _require_nonempty(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PR177HygieneError(f"{field} is required")
