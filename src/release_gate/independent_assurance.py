"""PR-169 independent security assurance and launch certification gate.

This module is intentionally offline and side-effect free. It models the
independent evidence that must exist before a production launch can be certified;
it does not enable a sender, deploy a release, or evaluate live trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Final


PR169_SCHEMA_VERSION: Final = "pr169.independent-launch-certification.v1"

_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_SIGNATURE_PREFIXES: Final = ("sigstore:", "cosign:", "gpg:", "file:/")


class LaunchEvidenceKind(StrEnum):
    THREAT_MODEL = "threat-model"
    SECURITY_INVARIANTS = "security-invariants"
    PROPERTY_STATE_MACHINE = "property-state-machine"
    COVERAGE_GUIDED_FUZZING = "coverage-guided-fuzzing"
    MUTATION_TESTING = "mutation-testing"
    DIFFERENTIAL_TESTING = "differential-testing"
    STATIC_DATAFLOW = "static-dataflow"
    EXTERNAL_PENTEST = "external-pentest"


class LaunchRiskSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class LaunchRiskState(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    CLOSED = "closed"


class AssuranceSignoffRole(StrEnum):
    SECURITY = "security"
    PROTOCOL_FINANCIAL = "protocol-financial"
    OPERATIONS = "operations"
    TREASURY_RISK = "treasury-risk"
    INDEPENDENT_REVIEWER = "independent-reviewer"


class AssuranceDecision(StrEnum):
    APPROVE = "approve"
    BLOCK = "block"


REQUIRED_EVIDENCE_KINDS: Final[frozenset[LaunchEvidenceKind]] = frozenset(
    {
        LaunchEvidenceKind.THREAT_MODEL,
        LaunchEvidenceKind.SECURITY_INVARIANTS,
        LaunchEvidenceKind.PROPERTY_STATE_MACHINE,
        LaunchEvidenceKind.COVERAGE_GUIDED_FUZZING,
        LaunchEvidenceKind.MUTATION_TESTING,
        LaunchEvidenceKind.DIFFERENTIAL_TESTING,
        LaunchEvidenceKind.STATIC_DATAFLOW,
        LaunchEvidenceKind.EXTERNAL_PENTEST,
    }
)

REQUIRED_SIGNOFF_ROLES: Final[frozenset[AssuranceSignoffRole]] = frozenset(
    {
        AssuranceSignoffRole.SECURITY,
        AssuranceSignoffRole.PROTOCOL_FINANCIAL,
        AssuranceSignoffRole.OPERATIONS,
        AssuranceSignoffRole.TREASURY_RISK,
        AssuranceSignoffRole.INDEPENDENT_REVIEWER,
    }
)

REQUIRED_SECURITY_INVARIANTS: Final[frozenset[str]] = frozenset(
    {
        "network-runtime-never-accesses-private-key",
        "unknown-instruction-or-cpi-never-authorized",
        "one-exact-message-per-authorization",
        "no-duplicate-unresolved-submission",
        "repayment-proven-before-success",
        "restart-cannot-reset-financial-latches",
        "one-active-sender-generation",
        "evidence-cannot-be-silently-rewritten",
        "operator-cannot-self-approve-critical-release",
    }
)


@dataclass(frozen=True, slots=True)
class IndependentEvidenceArtifact:
    evidence_kind: LaunchEvidenceKind
    tool_name: str
    tool_version: str
    command: str
    source_commit: str
    image_digest: str
    produced_at: datetime
    producer_identity: str
    runner_identity: str
    verifier_identity: str
    raw_report_sha256: str
    signature_reference: str
    passed: bool

    def __post_init__(self) -> None:
        for field_name, value in (
            ("tool_name", self.tool_name),
            ("tool_version", self.tool_version),
            ("command", self.command),
            ("producer_identity", self.producer_identity),
            ("runner_identity", self.runner_identity),
            ("verifier_identity", self.verifier_identity),
        ):
            _require_text(field_name, value)
        _require_git_sha("source_commit", self.source_commit)
        _require_image_digest(self.image_digest)
        _require_sha256("raw_report_sha256", self.raw_report_sha256)
        _require_aware_datetime("produced_at", self.produced_at)
        if self.producer_identity == self.verifier_identity:
            raise ValueError("independent verifier must differ from producer")
        if not self.signature_reference.startswith(_SIGNATURE_PREFIXES):
            raise ValueError("signature_reference must use signed evidence storage")


@dataclass(frozen=True, slots=True)
class LaunchRiskRegisterItem:
    finding_id: str
    severity: LaunchRiskSeverity
    state: LaunchRiskState
    owner: str
    mitigation: str
    blast_radius: str
    acceptance_authority: str | None = None
    accepted_until: datetime | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("finding_id", self.finding_id),
            ("owner", self.owner),
            ("mitigation", self.mitigation),
            ("blast_radius", self.blast_radius),
        ):
            _require_text(field_name, value)
        if self.state is LaunchRiskState.ACCEPTED:
            if not self.acceptance_authority:
                raise ValueError("accepted risk requires acceptance_authority")
            _require_text("acceptance_authority", self.acceptance_authority)
            if self.accepted_until is None:
                raise ValueError("accepted risk requires accepted_until")
            _require_aware_datetime("accepted_until", self.accepted_until)
            if self.accepted_until <= datetime.now(timezone.utc):
                raise ValueError("accepted risk exception must be unexpired")
        if self.state is not LaunchRiskState.ACCEPTED and (
            self.acceptance_authority is not None or self.accepted_until is not None
        ):
            raise ValueError("only accepted risks may carry exception metadata")


@dataclass(frozen=True, slots=True)
class IndependentLaunchSignoff:
    role: AssuranceSignoffRole
    identity: str
    decision: AssuranceDecision
    signed_at: datetime
    exact_release_digest: str
    raw_evidence_sha256: str
    authored_release_changes: bool = False
    comment: str = ""

    def __post_init__(self) -> None:
        _require_text("identity", self.identity)
        _require_sha256("exact_release_digest", self.exact_release_digest)
        _require_sha256("raw_evidence_sha256", self.raw_evidence_sha256)
        _require_aware_datetime("signed_at", self.signed_at)
        if self.role is AssuranceSignoffRole.INDEPENDENT_REVIEWER:
            if self.authored_release_changes:
                raise ValueError("independent reviewer cannot author release changes")


@dataclass(frozen=True, slots=True)
class IndependentLaunchCertificationPackage:
    release_digest: str
    threat_model_path: str
    threat_model_reviewed_at: datetime
    assets: tuple[str, ...]
    trust_boundaries: tuple[str, ...]
    security_invariants: tuple[str, ...]
    evidence: tuple[IndependentEvidenceArtifact, ...]
    risk_register: tuple[LaunchRiskRegisterItem, ...]
    signoffs: tuple[IndependentLaunchSignoff, ...]
    schema_version: str = PR169_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PR169_SCHEMA_VERSION:
            raise ValueError("unsupported PR-169 schema")
        _require_sha256("release_digest", self.release_digest)
        _require_repo_path("threat_model_path", self.threat_model_path)
        _require_aware_datetime(
            "threat_model_reviewed_at",
            self.threat_model_reviewed_at,
        )
        _require_non_empty_unique("assets", self.assets)
        _require_non_empty_unique("trust_boundaries", self.trust_boundaries)
        _require_non_empty_unique("security_invariants", self.security_invariants)
        _require_unique_enum_values(
            "evidence kinds",
            tuple(item.evidence_kind for item in self.evidence),
        )
        _require_unique_text(
            "risk findings",
            tuple(item.finding_id for item in self.risk_register),
        )
        _require_unique_enum_values(
            "signoff roles",
            tuple(item.role for item in self.signoffs),
        )


@dataclass(frozen=True, slots=True)
class LaunchCertificationResult:
    approved: bool
    blockers: tuple[str, ...]
    required_evidence: tuple[str, ...]
    observed_evidence: tuple[str, ...]
    required_signoffs: tuple[str, ...]
    observed_signoffs: tuple[str, ...]


def evaluate_independent_launch_certification(
    package: IndependentLaunchCertificationPackage,
) -> LaunchCertificationResult:
    blockers: list[str] = []

    observed_evidence = frozenset(item.evidence_kind for item in package.evidence)
    missing_evidence = REQUIRED_EVIDENCE_KINDS - observed_evidence
    for kind in sorted(missing_evidence, key=lambda item: item.value):
        blockers.append(f"missing independent evidence: {kind.value}")

    for item in package.evidence:
        if not item.passed:
            blockers.append(f"independent evidence failed: {item.evidence_kind.value}")

    observed_signoffs = frozenset(item.role for item in package.signoffs)
    missing_signoffs = REQUIRED_SIGNOFF_ROLES - observed_signoffs
    for role in sorted(missing_signoffs, key=lambda item: item.value):
        blockers.append(f"missing independent signoff: {role.value}")

    for signoff in package.signoffs:
        if signoff.exact_release_digest != package.release_digest:
            blockers.append(f"signoff release mismatch: {signoff.role.value}")
        if signoff.decision is AssuranceDecision.BLOCK:
            blockers.append(f"blocking signoff: {signoff.role.value}")

    observed_invariants = frozenset(package.security_invariants)
    missing_invariants = REQUIRED_SECURITY_INVARIANTS - observed_invariants
    for invariant in sorted(missing_invariants):
        blockers.append(f"missing security invariant: {invariant}")

    for risk in package.risk_register:
        if risk.severity in {LaunchRiskSeverity.CRITICAL, LaunchRiskSeverity.HIGH}:
            if risk.state is not LaunchRiskState.CLOSED:
                blockers.append(f"unresolved high-severity risk: {risk.finding_id}")

    return LaunchCertificationResult(
        approved=not blockers,
        blockers=tuple(blockers),
        required_evidence=tuple(
            sorted(kind.value for kind in REQUIRED_EVIDENCE_KINDS)
        ),
        observed_evidence=tuple(sorted(kind.value for kind in observed_evidence)),
        required_signoffs=tuple(
            sorted(role.value for role in REQUIRED_SIGNOFF_ROLES)
        ),
        observed_signoffs=tuple(sorted(role.value for role in observed_signoffs)),
    )


def _require_text(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} is required")


def _require_sha256(field_name: str, value: str) -> None:
    lowered = value.lower()
    if not _SHA256_RE.fullmatch(lowered) or lowered == "0" * 64:
        raise ValueError(f"{field_name} must be a non-placeholder sha256")


def _require_git_sha(field_name: str, value: str) -> None:
    lowered = value.lower()
    if not _GIT_SHA_RE.fullmatch(lowered) or lowered == "0" * 40:
        raise ValueError(f"{field_name} must be a full non-placeholder git SHA")


def _require_image_digest(value: str) -> None:
    prefix = "sha256:"
    if not value.startswith(prefix):
        raise ValueError("image_digest must use sha256:<digest>")
    _require_sha256("image_digest", value[len(prefix) :])


def _require_aware_datetime(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_repo_path(field_name: str, value: str) -> None:
    _require_text(field_name, value)
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    if value.startswith(("/", "~")) or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{field_name} must be a normalized repository path")


def _require_non_empty_unique(field_name: str, values: tuple[str, ...]) -> None:
    if not values:
        raise ValueError(f"{field_name} cannot be empty")
    _require_unique_text(field_name, values)


def _require_unique_text(field_name: str, values: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for value in values:
        _require_text(field_name, value)
        if value in seen:
            raise ValueError(f"{field_name} must be unique")
        seen.add(value)


def _require_unique_enum_values(
    field_name: str,
    values: tuple[StrEnum, ...],
) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must be unique")


__all__ = [
    "AssuranceDecision",
    "AssuranceSignoffRole",
    "IndependentEvidenceArtifact",
    "IndependentLaunchCertificationPackage",
    "IndependentLaunchSignoff",
    "LaunchCertificationResult",
    "LaunchEvidenceKind",
    "LaunchRiskRegisterItem",
    "LaunchRiskSeverity",
    "LaunchRiskState",
    "PR169_SCHEMA_VERSION",
    "REQUIRED_EVIDENCE_KINDS",
    "REQUIRED_SECURITY_INVARIANTS",
    "REQUIRED_SIGNOFF_ROLES",
    "evaluate_independent_launch_certification",
]
