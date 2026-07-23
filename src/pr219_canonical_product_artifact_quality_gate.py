from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Sequence

SCHEMA_VERSION = "pr219.canonical-product-artifact-quality-gate.v1"
PRODUCT_ID = "studious-pancake.pr219.canonical-product-artifact-quality-gate"

REQUIRED_CLI_NAMES: tuple[str, ...] = (
    "flashloan-bot",
    "flashloan-paper",
    "flashloan-shadow",
    "flashloan-status",
    "flashloan-checks",
)

FORBIDDEN_NAMESPACE_PREFIXES: tuple[str, ...] = (
    "src.submission",
    "src.live_canary",
    "src.signer",
    "src.isolated_signer_service",
    "src.sender",
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class PR219GateState(StrEnum):
    READY = "ready-for-pr219-review"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class CLIContract:
    name: str
    entry_module: str
    stable_exit_codes: bool
    structured_json_errors: bool
    root_launcher_equivalent: bool
    installed_entrypoint_present: bool

    def __post_init__(self) -> None:
        _identifier(self.name, "cli.name")
        _module_name(self.entry_module, "cli.entry_module")


@dataclass(frozen=True, slots=True)
class ArtifactGateViolation:
    code: str
    subject: str
    detail: str

    def __post_init__(self) -> None:
        _identifier(self.code, "violation.code")
        if not self.subject:
            raise ValueError("violation subject must not be empty")
        if not self.detail:
            raise ValueError("violation detail must not be empty")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class PR219ArtifactEvidence:
    canonical_product_id: str
    composition_root_module: str
    main_wheel_sha256: str
    signer_wheel_sha256: str
    image_digest: str
    sbom_sha256: str
    provenance_sha256: str
    installed_modules: Sequence[str]
    reachable_modules: Sequence[str]
    required_controls: Sequence[str]
    observed_required_controls: Sequence[str]
    cli_contracts: Sequence[CLIContract]
    detected_forbidden_modules: Sequence[str]
    checked_in_build_artifacts: Sequence[str]
    legacy_bypass_paths: Sequence[str]
    mutable_action_refs: int
    mutable_base_images: int
    production_assert_count: int
    import_cycles_present: bool
    source_wheel_surface_match: bool
    offline_build_verified: bool
    release_wheelhouse_signed: bool
    duplicate_tests_present: bool
    broad_quality_quarantine_count: int
    safe_idle_satisfies_workload_readiness: bool
    ambient_dependency_leak: bool

    def __post_init__(self) -> None:
        _identifier(self.canonical_product_id, "canonical_product_id")
        _module_name(self.composition_root_module, "composition_root_module")
        _sha256(self.main_wheel_sha256, "main_wheel_sha256")
        _sha256(self.signer_wheel_sha256, "signer_wheel_sha256")
        _image_digest(self.image_digest, "image_digest")
        _sha256(self.sbom_sha256, "sbom_sha256")
        _sha256(self.provenance_sha256, "provenance_sha256")
        _module_sequence(self.installed_modules, "installed_modules")
        _module_sequence(self.reachable_modules, "reachable_modules")
        _module_sequence(self.required_controls, "required_controls")
        _module_sequence(self.observed_required_controls, "observed_required_controls")
        if not self.cli_contracts:
            raise ValueError("cli_contracts must not be empty")
        if self.mutable_action_refs < 0:
            raise ValueError("mutable_action_refs must be non-negative")
        if self.mutable_base_images < 0:
            raise ValueError("mutable_base_images must be non-negative")
        if self.production_assert_count < 0:
            raise ValueError("production_assert_count must be non-negative")
        if self.broad_quality_quarantine_count < 0:
            raise ValueError("broad_quality_quarantine_count must be non-negative")


@dataclass(frozen=True, slots=True)
class PR219ArtifactGateReport:
    schema_version: str
    product_id: str
    state: PR219GateState
    evidence_hash: str
    violations: tuple[ArtifactGateViolation, ...]
    live_execution_allowed: bool = False
    signer_allowed: bool = False
    sender_allowed: bool = False

    @property
    def ready(self) -> bool:
        return self.state is PR219GateState.READY

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "product_id": self.product_id,
            "state": self.state.value,
            "ready": self.ready,
            "evidence_hash": self.evidence_hash,
            "violation_count": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
            "safety_boundary": {
                "live_execution_allowed": self.live_execution_allowed,
                "signer_allowed": self.signer_allowed,
                "sender_allowed": self.sender_allowed,
            },
        }


def evaluate_pr219_artifact_quality(
    evidence: PR219ArtifactEvidence,
) -> PR219ArtifactGateReport:
    violations: list[ArtifactGateViolation] = []

    cli_by_name = {cli.name: cli for cli in evidence.cli_contracts}
    for required_name in REQUIRED_CLI_NAMES:
        cli = cli_by_name.get(required_name)
        if cli is None:
            violations.append(
                ArtifactGateViolation(
                    code="missing_required_cli",
                    subject=required_name,
                    detail="required installed CLI contract is absent",
                )
            )
            continue
        if not cli.installed_entrypoint_present:
            violations.append(
                ArtifactGateViolation(
                    code="missing_installed_entrypoint",
                    subject=required_name,
                    detail="required CLI is missing from the installed artifact",
                )
            )
        if not cli.root_launcher_equivalent:
            violations.append(
                ArtifactGateViolation(
                    code="root_launcher_contract_drift",
                    subject=required_name,
                    detail="root launcher and installed entrypoint do not share one contract",
                )
            )
        if not cli.stable_exit_codes:
            violations.append(
                ArtifactGateViolation(
                    code="unstable_exit_codes",
                    subject=required_name,
                    detail="CLI does not provide a stable exit-code contract",
                )
            )
        if not cli.structured_json_errors:
            violations.append(
                ArtifactGateViolation(
                    code="missing_structured_errors",
                    subject=required_name,
                    detail="CLI does not expose structured JSON error output",
                )
            )

    reachable = set(evidence.reachable_modules)
    observed_controls = set(evidence.observed_required_controls)

    for control in evidence.required_controls:
        if control not in observed_controls:
            violations.append(
                ArtifactGateViolation(
                    code="missing_required_control_trace",
                    subject=control,
                    detail="required control is not observed in installed behavioral trace",
                )
            )
        if control not in reachable:
            violations.append(
                ArtifactGateViolation(
                    code="unreachable_required_control",
                    subject=control,
                    detail="required control is not reachable from the canonical composition root",
                )
            )

    installed = set(evidence.installed_modules)
    for module_name in sorted(installed):
        if _is_forbidden_namespace(module_name):
            violations.append(
                ArtifactGateViolation(
                    code="forbidden_namespace_packaged",
                    subject=module_name,
                    detail="sender/live/signer namespace is present in sender-free runtime package",
                )
            )

    for module_name in sorted(set(evidence.detected_forbidden_modules)):
        violations.append(
            ArtifactGateViolation(
                code="forbidden_namespace_observed",
                subject=module_name,
                detail="artifact scan observed forbidden sender/live/signer namespace",
            )
        )

    if evidence.checked_in_build_artifacts:
        for path in sorted(set(evidence.checked_in_build_artifacts)):
            violations.append(
                ArtifactGateViolation(
                    code="checked_in_build_artifact",
                    subject=path,
                    detail="checked-in build or cache artifact contaminates release input",
                )
            )

    if evidence.legacy_bypass_paths:
        for path in sorted(set(evidence.legacy_bypass_paths)):
            violations.append(
                ArtifactGateViolation(
                    code="legacy_source_bypass",
                    subject=path,
                    detail="legacy launcher or source bypass remains production-reachable",
                )
            )

    if evidence.mutable_action_refs:
        violations.append(
            ArtifactGateViolation(
                code="mutable_action_refs",
                subject="github-actions",
                detail="workflow actions are not immutable-pinned by full commit SHA",
            )
        )
    if evidence.mutable_base_images:
        violations.append(
            ArtifactGateViolation(
                code="mutable_base_images",
                subject="base-images",
                detail="base images are not digest-pinned",
            )
        )
    if evidence.production_assert_count:
        violations.append(
            ArtifactGateViolation(
                code="production_asserts_present",
                subject="reachable-graph",
                detail="production validation still depends on assert in the reachable graph",
            )
        )
    if evidence.import_cycles_present:
        violations.append(
            ArtifactGateViolation(
                code="import_cycles_present",
                subject="production-graph",
                detail="production import graph still contains cycles",
            )
        )
    if not evidence.source_wheel_surface_match:
        violations.append(
            ArtifactGateViolation(
                code="source_wheel_surface_mismatch",
                subject="artifact-surface",
                detail="source, wheel and image surfaces do not match one canonical product",
            )
        )
    if not evidence.offline_build_verified:
        violations.append(
            ArtifactGateViolation(
                code="offline_build_unverified",
                subject="release-build",
                detail="release build is not verified from a clean offline environment",
            )
        )
    if not evidence.release_wheelhouse_signed:
        violations.append(
            ArtifactGateViolation(
                code="unsigned_release_wheelhouse",
                subject="wheelhouse",
                detail="release wheelhouse or dependency graph is not signed/hash-locked",
            )
        )
    if evidence.duplicate_tests_present:
        violations.append(
            ArtifactGateViolation(
                code="duplicate_tests_present",
                subject="quality-baseline",
                detail="duplicate tests inflate readiness signals",
            )
        )
    if evidence.broad_quality_quarantine_count:
        violations.append(
            ArtifactGateViolation(
                code="broad_quality_quarantine",
                subject="quality-baseline",
                detail="proof-critical modules remain behind broad quarantine/ignore rules",
            )
        )
    if evidence.safe_idle_satisfies_workload_readiness:
        violations.append(
            ArtifactGateViolation(
                code="safe_idle_claims_workload_ready",
                subject="paper-runtime",
                detail="safe-idle or blocked composition can satisfy workload readiness",
            )
        )
    if evidence.ambient_dependency_leak:
        violations.append(
            ArtifactGateViolation(
                code="ambient_dependency_leak",
                subject="qualification-environment",
                detail="qualification depends on ambient packages outside the signed artifact",
            )
        )

    ordered = tuple(sorted(violations, key=lambda v: (v.code, v.subject, v.detail)))
    return PR219ArtifactGateReport(
        schema_version=SCHEMA_VERSION,
        product_id=PRODUCT_ID,
        state=PR219GateState.BLOCKED if ordered else PR219GateState.READY,
        evidence_hash=_evidence_hash(evidence),
        violations=ordered,
    )


def _evidence_hash(evidence: PR219ArtifactEvidence) -> str:
    payload = {
        "domain": "studious-pancake/pr219/artifact-quality-gate",
        "canonical_product_id": evidence.canonical_product_id,
        "composition_root_module": evidence.composition_root_module,
        "main_wheel_sha256": evidence.main_wheel_sha256,
        "signer_wheel_sha256": evidence.signer_wheel_sha256,
        "image_digest": evidence.image_digest,
        "sbom_sha256": evidence.sbom_sha256,
        "provenance_sha256": evidence.provenance_sha256,
        "installed_modules": sorted(set(evidence.installed_modules)),
        "reachable_modules": sorted(set(evidence.reachable_modules)),
        "required_controls": sorted(set(evidence.required_controls)),
        "observed_required_controls": sorted(set(evidence.observed_required_controls)),
        "cli_contracts": [
            {
                "name": cli.name,
                "entry_module": cli.entry_module,
                "stable_exit_codes": cli.stable_exit_codes,
                "structured_json_errors": cli.structured_json_errors,
                "root_launcher_equivalent": cli.root_launcher_equivalent,
                "installed_entrypoint_present": cli.installed_entrypoint_present,
            }
            for cli in sorted(evidence.cli_contracts, key=lambda c: c.name)
        ],
        "detected_forbidden_modules": sorted(set(evidence.detected_forbidden_modules)),
        "checked_in_build_artifacts": sorted(set(evidence.checked_in_build_artifacts)),
        "legacy_bypass_paths": sorted(set(evidence.legacy_bypass_paths)),
        "mutable_action_refs": evidence.mutable_action_refs,
        "mutable_base_images": evidence.mutable_base_images,
        "production_assert_count": evidence.production_assert_count,
        "import_cycles_present": evidence.import_cycles_present,
        "source_wheel_surface_match": evidence.source_wheel_surface_match,
        "offline_build_verified": evidence.offline_build_verified,
        "release_wheelhouse_signed": evidence.release_wheelhouse_signed,
        "duplicate_tests_present": evidence.duplicate_tests_present,
        "broad_quality_quarantine_count": evidence.broad_quality_quarantine_count,
        "safe_idle_satisfies_workload_readiness": evidence.safe_idle_satisfies_workload_readiness,
        "ambient_dependency_leak": evidence.ambient_dependency_leak,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _is_forbidden_namespace(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(prefix + ".")
        for prefix in FORBIDDEN_NAMESPACE_PREFIXES
    )


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a stable identifier")
    return value


def _module_name(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _MODULE_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a Python module name")
    return value


def _module_sequence(values: Sequence[str], field_name: str) -> None:
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    for value in values:
        _module_name(value, field_name)


def _sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")
    return value


def _image_digest(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a sha256 image digest")
    return value
