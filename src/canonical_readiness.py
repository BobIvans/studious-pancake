"""PR-174 canonical readiness and debt-authority consolidation.

This module defines one stable-domain readiness/debt authority for production
readiness decisions. It is side-effect free: it does not mutate existing
production_debt inventories, import runtime entrypoints, open files, query
providers, start SQLite, sign, submit, or enable live mode.

The purpose is to make duplicate truth planes visible and fail-closed until the
active CLI -> composition root -> implementation owner path and the installed
wheel identity prove the same canonical requirement owner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

PR174_SCHEMA_VERSION = "pr174.canonical-readiness-state.v1"
_DOMAIN_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")


class PR174ReadinessError(ValueError):
    """Raised when a canonical readiness record is malformed."""


class ProductState(str, Enum):
    """Top-level product state exposed by the canonical authority."""

    NOT_PRODUCTION_READY = "not-production-ready"
    PAPER_REVIEW_READY = "paper-review-ready"
    LIVE_CANARY_REVIEW_READY = "live-canary-review-ready"
    PRODUCTION_READY = "production-ready"
    REVOKED = "revoked"


class CapabilityState(str, Enum):
    """Machine-readable capability admission state."""

    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    REVIEW_READY = "review-ready"
    APPROVED = "approved"
    REVOKED = "revoked"


class BlockingMode(str, Enum):
    """How a requirement affects readiness."""

    P0_BLOCKS_PAPER_AND_LIVE = "p0-blocks-paper-and-live"
    P0_BLOCKS_LIVE = "p0-blocks-live"
    P1_BLOCKS_PRODUCTION = "p1-blocks-production"
    NON_BLOCKING_TRACKED = "non-blocking-tracked"


class ImplementationState(str, Enum):
    """Lifecycle for implementation ownership, independent of PR numbers."""

    DECLARED = "declared"
    IMPLEMENTATION_PENDING = "implementation-pending"
    IMPLEMENTED_ISOLATED = "implemented-isolated"
    INTEGRATED_DISABLED = "integrated-disabled"
    INTEGRATED_PAPER = "integrated-paper"
    EVIDENCE_PENDING = "evidence-pending"
    REVIEW_READY = "review-ready"
    LIVE_APPROVED = "live-approved"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"


class EvidenceState(str, Enum):
    """Whether evidence is executable, verified, fresh and bound."""

    MISSING = "missing"
    DESCRIPTOR_ONLY = "descriptor-only"
    PRODUCED_UNVERIFIED = "produced-unverified"
    VERIFIED_CURRENT = "verified-current"
    STALE = "stale"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class ArchitectureBindingProof:
    """Proof that a requirement owner is used by the active runtime path."""

    cli_entrypoint: str
    composition_root: str
    owner_module: str
    owner_symbol: str
    cli_imports_composition: bool
    composition_imports_owner: bool
    runtime_uses_owner: bool
    isolated_gate_only: bool = False
    proof_hash: str | None = None

    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        _require_nonempty(self.cli_entrypoint, "cli_entrypoint")
        _require_nonempty(self.composition_root, "composition_root")
        _require_nonempty(self.owner_module, "owner_module")
        _require_nonempty(self.owner_symbol, "owner_symbol")
        if self.proof_hash is not None:
            _require_hash(self.proof_hash, "proof_hash")
        if not self.cli_imports_composition:
            blockers.append("CLI_DOES_NOT_IMPORT_COMPOSITION_ROOT")
        if not self.composition_imports_owner:
            blockers.append("COMPOSITION_DOES_NOT_IMPORT_OWNER")
        if not self.runtime_uses_owner:
            blockers.append("RUNTIME_DOES_NOT_USE_OWNER")
        if self.isolated_gate_only:
            blockers.append("ISOLATED_GATE_ONLY_CANNOT_CLOSE_INTEGRATION")
        return tuple(blockers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cli_entrypoint": self.cli_entrypoint,
            "composition_root": self.composition_root,
            "owner_module": self.owner_module,
            "owner_symbol": self.owner_symbol,
            "cli_imports_composition": self.cli_imports_composition,
            "composition_imports_owner": self.composition_imports_owner,
            "runtime_uses_owner": self.runtime_uses_owner,
            "isolated_gate_only": self.isolated_gate_only,
            "proof_hash": self.proof_hash,
        }


@dataclass(frozen=True, slots=True)
class PackageBindingProof:
    """Proof that source checkout and installed wheel expose the same owner."""

    distribution_name: str
    distribution_version: str
    owner_module: str
    source_digest: str
    wheel_digest: str
    active_import_owner: str
    source_wheel_parity: bool

    def blockers(self) -> tuple[str, ...]:
        _require_nonempty(self.distribution_name, "distribution_name")
        _require_nonempty(self.distribution_version, "distribution_version")
        _require_nonempty(self.owner_module, "owner_module")
        _require_hash(self.source_digest, "source_digest")
        _require_hash(self.wheel_digest, "wheel_digest")
        _require_nonempty(self.active_import_owner, "active_import_owner")
        blockers: list[str] = []
        if self.active_import_owner != self.owner_module:
            blockers.append("ACTIVE_IMPORT_OWNER_MISMATCH")
        if not self.source_wheel_parity:
            blockers.append("SOURCE_WHEEL_PARITY_NOT_PROVEN")
        return tuple(blockers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
            "owner_module": self.owner_module,
            "source_digest": self.source_digest,
            "wheel_digest": self.wheel_digest,
            "active_import_owner": self.active_import_owner,
            "source_wheel_parity": self.source_wheel_parity,
        }


@dataclass(frozen=True, slots=True)
class RequirementRecord:
    """Canonical stable-domain requirement, not a PR-number truth plane."""

    domain_id: str
    title: str
    owner_module: str
    blocking_mode: BlockingMode
    implementation_state: ImplementationState
    evidence_state: EvidenceState
    evidence_producer: str
    evidence_verifier: str
    architecture: ArchitectureBindingProof | None
    package: PackageBindingProof | None
    blockers: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    superseded_by: str | None = None
    removal_criteria: str | None = None
    evidence_expires_at_ns: int | None = None
    component_version: str | None = None

    @property
    def is_active_owner(self) -> bool:
        return self.implementation_state not in {
            ImplementationState.SUPERSEDED,
            ImplementationState.REVOKED,
        } and self.superseded_by is None

    @property
    def blocks_paper(self) -> bool:
        return self.blocking_mode == BlockingMode.P0_BLOCKS_PAPER_AND_LIVE

    @property
    def blocks_live(self) -> bool:
        return self.blocking_mode in {
            BlockingMode.P0_BLOCKS_PAPER_AND_LIVE,
            BlockingMode.P0_BLOCKS_LIVE,
        }

    @property
    def blocks_production(self) -> bool:
        return self.blocking_mode != BlockingMode.NON_BLOCKING_TRACKED

    def evaluate_blockers(self) -> tuple[str, ...]:
        _validate_requirement(self)
        blockers = list(dict.fromkeys(self.blockers))

        if self.implementation_state == ImplementationState.REVOKED:
            blockers.append("REQUIREMENT_OWNER_REVOKED")
        if self.evidence_state in {EvidenceState.MISSING, EvidenceState.STALE, EvidenceState.REVOKED}:
            blockers.append(f"EVIDENCE_{self.evidence_state.value.upper().replace('-', '_')}")
        if self.evidence_state == EvidenceState.DESCRIPTOR_ONLY and self.blocks_production:
            blockers.append("DESCRIPTOR_ONLY_CANNOT_CLOSE_READINESS")

        if self.implementation_state in {
            ImplementationState.IMPLEMENTED_ISOLATED,
            ImplementationState.INTEGRATED_DISABLED,
            ImplementationState.INTEGRATED_PAPER,
            ImplementationState.EVIDENCE_PENDING,
            ImplementationState.REVIEW_READY,
            ImplementationState.LIVE_APPROVED,
        }:
            if self.architecture is None:
                blockers.append("ACTIVE_RUNTIME_BINDING_PROOF_MISSING")
            else:
                blockers.extend(self.architecture.blockers())
            if self.package is None:
                blockers.append("PACKAGE_BINDING_PROOF_MISSING")
            else:
                blockers.extend(self.package.blockers())

        if self.implementation_state == ImplementationState.LIVE_APPROVED:
            if self.evidence_state != EvidenceState.VERIFIED_CURRENT:
                blockers.append("LIVE_APPROVAL_REQUIRES_CURRENT_VERIFIED_EVIDENCE")
            if self.blocks_live and blockers:
                blockers.append("LIVE_APPROVAL_HAS_OPEN_BLOCKERS")

        if self.superseded_by and not self.removal_criteria:
            blockers.append("SUPERSEDED_REQUIREMENT_NEEDS_REMOVAL_CRITERIA")

        return tuple(dict.fromkeys(blockers))

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "title": self.title,
            "owner_module": self.owner_module,
            "blocking_mode": self.blocking_mode.value,
            "implementation_state": self.implementation_state.value,
            "evidence_state": self.evidence_state.value,
            "evidence_producer": self.evidence_producer,
            "evidence_verifier": self.evidence_verifier,
            "architecture": self.architecture.to_dict() if self.architecture else None,
            "package": self.package.to_dict() if self.package else None,
            "blockers": list(self.blockers),
            "supersedes": list(self.supersedes),
            "superseded_by": self.superseded_by,
            "removal_criteria": self.removal_criteria,
            "evidence_expires_at_ns": self.evidence_expires_at_ns,
            "component_version": self.component_version,
        }


@dataclass(frozen=True, slots=True)
class LegacyTruthReport:
    """Adapter for old production_debt truth planes during PR-174 migration."""

    system_id: str
    paper_ready: bool
    live_ready: bool
    production_ready: bool
    report_hash: str
    schema_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "system_id": self.system_id,
            "paper_ready": self.paper_ready,
            "live_ready": self.live_ready,
            "production_ready": self.production_ready,
            "report_hash": self.report_hash,
            "schema_id": self.schema_id,
        }


@dataclass(frozen=True, slots=True)
class ProductionReadinessState:
    """Canonical PR-174 machine-readable readiness result."""

    schema_version: str
    product_state: ProductState
    paper_capability: CapabilityState
    live_capability: CapabilityState
    production_ready: bool
    paper_ready: bool
    live_ready: bool
    requirements: tuple[RequirementRecord, ...]
    requirement_blockers: dict[str, tuple[str, ...]]
    global_blockers: tuple[str, ...]
    legacy_reports: tuple[LegacyTruthReport, ...]
    evaluated_release: str
    state_hash: str = field(init=False)

    def __post_init__(self) -> None:
        data = self.to_dict(include_hash=False)
        object.__setattr__(self, "state_hash", _hash_json(data))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "product_state": self.product_state.value,
            "paper_capability": self.paper_capability.value,
            "live_capability": self.live_capability.value,
            "production_ready": self.production_ready,
            "paper_ready": self.paper_ready,
            "live_ready": self.live_ready,
            "requirements": [requirement.to_dict() for requirement in self.requirements],
            "requirement_blockers": {
                key: list(value) for key, value in sorted(self.requirement_blockers.items())
            },
            "global_blockers": list(self.global_blockers),
            "legacy_reports": [report.to_dict() for report in self.legacy_reports],
            "evaluated_release": self.evaluated_release,
        }
        if include_hash:
            data["state_hash"] = self.state_hash
        return data


CANONICAL_PR174_DOMAIN_OWNERS: tuple[tuple[str, str], ...] = (
    ("policy.admission", "src.pr153_policy_admission"),
    ("market.economics", "src.market_economic_kernel_pr154"),
    ("transaction.proof", "src.transaction_proof_pr155"),
    ("runtime.paper", "src.durable_paper_runtime_pr156"),
    ("release.path", "src.release_path_pr157"),
    ("production.debt", "src.canonical_readiness"),
)


def evaluate_canonical_readiness(
    requirements: Iterable[RequirementRecord],
    *,
    legacy_reports: Iterable[LegacyTruthReport] = (),
    evaluated_release: str = "unknown",
) -> ProductionReadinessState:
    """Evaluate one canonical readiness state and fail on duplicate truth planes."""

    reqs = tuple(requirements)
    legacy = tuple(legacy_reports)
    if not reqs:
        raise PR174ReadinessError("at least one requirement is required")
    _require_nonempty(evaluated_release, "evaluated_release")

    requirement_blockers: dict[str, tuple[str, ...]] = {}
    global_blockers: list[str] = []

    seen_domains: dict[str, RequirementRecord] = {}
    active_owners_by_domain: dict[str, set[str]] = {}
    for requirement in reqs:
        _validate_requirement(requirement)
        blockers = requirement.evaluate_blockers()
        if blockers:
            requirement_blockers[requirement.domain_id] = blockers

        if requirement.domain_id in seen_domains:
            other = seen_domains[requirement.domain_id]
            if requirement.is_active_owner and other.is_active_owner:
                global_blockers.append(
                    f"DUPLICATE_ACTIVE_REQUIREMENT:{requirement.domain_id}"
                )
        else:
            seen_domains[requirement.domain_id] = requirement

        if requirement.is_active_owner:
            active_owners_by_domain.setdefault(requirement.domain_id, set()).add(
                requirement.owner_module
            )

    for domain_id, owners in active_owners_by_domain.items():
        if len(owners) > 1:
            global_blockers.append(f"DUPLICATE_ACTIVE_OWNER:{domain_id}")

    global_blockers.extend(_legacy_truth_blockers(legacy))
    global_blockers.extend(_supersession_blockers(reqs))

    paper_blockers = [
        domain_id
        for domain_id, blockers in requirement_blockers.items()
        if blockers and seen_domains[domain_id].blocks_paper
    ]
    live_blockers = [
        domain_id
        for domain_id, blockers in requirement_blockers.items()
        if blockers and seen_domains[domain_id].blocks_live
    ]
    production_blockers = [
        domain_id
        for domain_id, blockers in requirement_blockers.items()
        if blockers and seen_domains[domain_id].blocks_production
    ]

    has_global = bool(global_blockers)
    paper_ready = not has_global and not paper_blockers
    live_ready = not has_global and not live_blockers and paper_ready
    production_ready = not has_global and not production_blockers and live_ready

    product_state = ProductState.NOT_PRODUCTION_READY
    if production_ready:
        product_state = ProductState.PRODUCTION_READY
    elif live_ready:
        product_state = ProductState.LIVE_CANARY_REVIEW_READY
    elif paper_ready:
        product_state = ProductState.PAPER_REVIEW_READY

    return ProductionReadinessState(
        schema_version=PR174_SCHEMA_VERSION,
        product_state=product_state,
        paper_capability=CapabilityState.REVIEW_READY if paper_ready else CapabilityState.BLOCKED,
        live_capability=CapabilityState.REVIEW_READY if live_ready else CapabilityState.BLOCKED,
        production_ready=production_ready,
        paper_ready=paper_ready,
        live_ready=live_ready,
        requirements=reqs,
        requirement_blockers=requirement_blockers,
        global_blockers=tuple(dict.fromkeys(global_blockers)),
        legacy_reports=legacy,
        evaluated_release=evaluated_release,
    )


def assert_single_authoritative_readiness(state: ProductionReadinessState) -> None:
    """Raise when any duplicate or divergent truth plane remains."""

    blockers = list(state.global_blockers)
    blockers.extend(
        f"{domain_id}:{','.join(domain_blockers)}"
        for domain_id, domain_blockers in state.requirement_blockers.items()
    )
    if blockers:
        raise PR174ReadinessError(
            "canonical readiness has open blockers: " + "; ".join(blockers)
        )


def owner_map_as_requirements(
    *,
    source_digest: str,
    wheel_digest: str,
    proof_hash: str,
) -> tuple[RequirementRecord, ...]:
    """Return initial PR-174 owner mapping for duplicated PR-152..157 domains.

    This helper is intentionally conservative: all entries are integrated-disabled
    with descriptor-only evidence until an active architecture test proves
    CLI/runtime/wheel ownership.
    """

    _require_hash(source_digest, "source_digest")
    _require_hash(wheel_digest, "wheel_digest")
    _require_hash(proof_hash, "proof_hash")
    requirements: list[RequirementRecord] = []
    for domain_id, owner in CANONICAL_PR174_DOMAIN_OWNERS:
        architecture = ArchitectureBindingProof(
            cli_entrypoint="flashloan-bot readiness evaluate",
            composition_root="src.cli",
            owner_module=owner,
            owner_symbol="canonical_owner",
            cli_imports_composition=False,
            composition_imports_owner=False,
            runtime_uses_owner=False,
            isolated_gate_only=True,
            proof_hash=proof_hash,
        )
        package = PackageBindingProof(
            distribution_name="flashloan-bot",
            distribution_version="unknown",
            owner_module=owner,
            source_digest=source_digest,
            wheel_digest=wheel_digest,
            active_import_owner=owner,
            source_wheel_parity=False,
        )
        requirements.append(
            RequirementRecord(
                domain_id=domain_id,
                title=f"Canonical owner for {domain_id}",
                owner_module=owner,
                blocking_mode=BlockingMode.P0_BLOCKS_PAPER_AND_LIVE,
                implementation_state=ImplementationState.INTEGRATED_DISABLED,
                evidence_state=EvidenceState.DESCRIPTOR_ONLY,
                evidence_producer="pending-active-architecture-test",
                evidence_verifier="pending-independent-verifier",
                architecture=architecture,
                package=package,
                blockers=("CANONICAL_OWNER_DECLARED_NOT_YET_BOUND",),
                component_version=None,
            )
        )
    return tuple(requirements)


def _legacy_truth_blockers(reports: Sequence[LegacyTruthReport]) -> tuple[str, ...]:
    for report in reports:
        _require_nonempty(report.system_id, "legacy.system_id")
        _require_hash(report.report_hash, f"{report.system_id}.report_hash")

    blockers: list[str] = []
    by_answers: set[tuple[bool, bool, bool]] = {
        (report.paper_ready, report.live_ready, report.production_ready)
        for report in reports
    }
    if len(by_answers) > 1:
        blockers.append("LEGACY_READINESS_REPORTS_DIVERGE")
    if len(reports) > 1:
        blockers.append("MULTIPLE_LEGACY_TRUTH_PLANES_PRESENT")
    return tuple(blockers)


def _supersession_blockers(requirements: Sequence[RequirementRecord]) -> tuple[str, ...]:
    by_domain = {requirement.domain_id: requirement for requirement in requirements}
    blockers: list[str] = []
    for requirement in requirements:
        for superseded in requirement.supersedes:
            if superseded in by_domain:
                old = by_domain[superseded]
                if old.is_active_owner:
                    blockers.append(f"SUPERSEDED_REQUIREMENT_STILL_ACTIVE:{superseded}")
        if requirement.superseded_by and requirement.superseded_by not in by_domain:
            blockers.append(f"SUPERSEDING_REQUIREMENT_MISSING:{requirement.domain_id}")
    return tuple(dict.fromkeys(blockers))


def _validate_requirement(requirement: RequirementRecord) -> None:
    if not _DOMAIN_ID_RE.fullmatch(requirement.domain_id):
        raise PR174ReadinessError(
            f"domain_id must be a stable semantic id, got {requirement.domain_id!r}"
        )
    if requirement.domain_id.lower().startswith("pr-") or re.search(
        r"\bpr\d+\b", requirement.domain_id.lower()
    ):
        raise PR174ReadinessError("domain_id must not be a PR number")
    _require_nonempty(requirement.title, "title")
    _require_nonempty(requirement.owner_module, "owner_module")
    _require_nonempty(requirement.evidence_producer, "evidence_producer")
    _require_nonempty(requirement.evidence_verifier, "evidence_verifier")
    if requirement.evidence_producer == requirement.evidence_verifier:
        raise PR174ReadinessError("producer and verifier must be distinct")
    if requirement.evidence_expires_at_ns is not None:
        _require_nonnegative_int(requirement.evidence_expires_at_ns, "evidence_expires_at_ns")
    if requirement.superseded_by and requirement.superseded_by == requirement.domain_id:
        raise PR174ReadinessError("requirement cannot supersede itself")


def _require_nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PR174ReadinessError(f"{field_name} must be a non-empty string")


def _require_hash(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise PR174ReadinessError(f"{field_name} must be a lowercase sha256 hex digest")


def _require_nonnegative_int(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise PR174ReadinessError(f"{field_name} must be a non-negative integer")


def _hash_json(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
