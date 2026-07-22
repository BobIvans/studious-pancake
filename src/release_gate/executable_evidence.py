"""PR-175 executable evidence production and provenance pipeline.

The existing release gates intentionally evaluate side-effect-free descriptors.  This
module adds the next fail-closed layer: a readiness requirement can be satisfied
only by a raw artifact produced by an executable producer and independently
verified into a signed provenance reference.  It remains offline and does not call
RPC, providers, signers, or live submission paths.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import json
import re
from typing import Iterable

PR175_SCHEMA_VERSION = "pr175.executable-evidence-provenance.v1"
PR175_VERIFIED_SCHEMA_VERSION = "pr175.verified-evidence.v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIREMENT_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")
_RELEASE_DIGEST_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_ALLOWED_SIGNATURE_PREFIXES = ("sigstore:", "gitsign:", "kms:", "file:")
_ALLOWED_RAW_URI_PREFIXES = ("sha256:", "file:", "s3://", "gs://")
_FORBIDDEN_TEXT = (
    "private_key",
    "secret_key",
    "authorization:",
    "api_key",
    "bearer ",
    "x-api-key",
)


class EvidenceSource(StrEnum):
    """Executable producer source class."""

    LOCAL_DETERMINISTIC_TEST = "local-deterministic-test"
    INSTALLED_WHEEL_TEST = "installed-wheel-test"
    CREDENTIALED_PROVIDER_PROBE = "credentialed-provider-probe"
    READONLY_MAINNET_RPC_ATTESTATION = "readonly-mainnet-rpc-attestation"
    SIMULATION_TRACE = "simulation-trace"
    FINALIZED_SETTLEMENT_TRACE = "finalized-settlement-trace"
    CHAOS_FAULT_INJECTION = "chaos-fault-injection"
    DEPLOYMENT_OBSERVATION = "deployment-observation"
    OPERATOR_APPROVAL = "operator-approval"
    EXTERNAL_AUDIT_REPORT = "external-audit-report"


class EvidenceOutcome(StrEnum):
    VERIFIED = "verified"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class RawEvidenceArtifact:
    """Raw executable evidence emitted by a producer before independent review."""

    requirement_id: str
    source: EvidenceSource
    producer_id: str
    command: tuple[str, ...]
    source_commit: str
    release_digest: str
    policy_bundle_digest: str
    component_owner: str
    environment: str
    started_at: datetime
    finished_at: datetime
    exit_code: int
    raw_output_sha256: str
    stdout_sha256: str
    stderr_sha256: str
    input_artifact_sha256: str
    raw_artifact_uri: str
    schema_version: str = PR175_SCHEMA_VERSION
    cluster_genesis_hash: str | None = None
    sanitized_summary: str = ""
    secrets_redacted: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != PR175_SCHEMA_VERSION:
            raise ValueError("unsupported raw evidence schema")
        _require_requirement_id(self.requirement_id)
        _require_identity("producer_id", self.producer_id)
        _require_identity("component_owner", self.component_owner)
        _require_identity("environment", self.environment)
        _require_commit(self.source_commit)
        _require_release_digest("release_digest", self.release_digest)
        _require_sha256("policy_bundle_digest", self.policy_bundle_digest)
        _require_sha256("raw_output_sha256", self.raw_output_sha256)
        _require_sha256("stdout_sha256", self.stdout_sha256)
        _require_sha256("stderr_sha256", self.stderr_sha256)
        _require_sha256("input_artifact_sha256", self.input_artifact_sha256)
        if self.cluster_genesis_hash is not None:
            _require_sha256("cluster_genesis_hash", self.cluster_genesis_hash)
        if not self.command or any(not part.strip() for part in self.command):
            raise ValueError("producer command must be explicit and non-empty")
        _require_time("started_at", self.started_at)
        _require_time("finished_at", self.finished_at)
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot be before started_at")
        if self.exit_code < 0:
            raise ValueError("exit_code cannot be negative")
        if not self.raw_artifact_uri.startswith(_ALLOWED_RAW_URI_PREFIXES):
            raise ValueError("raw_artifact_uri must be content-addressed or file backed")
        _reject_secret_text(self.raw_artifact_uri)
        _reject_secret_text(self.sanitized_summary)
        if not self.secrets_redacted:
            raise ValueError("raw evidence must provide a redacted safe view")

    @property
    def artifact_digest(self) -> str:
        """Stable digest of the raw evidence descriptor."""

        return _sha256_json(asdict(self))


@dataclass(frozen=True, slots=True)
class EvidenceVerificationPolicy:
    """Policy used by an independent verifier for one readiness requirement."""

    requirement_id: str
    accepted_sources: tuple[EvidenceSource, ...]
    release_digest: str
    policy_bundle_digest: str
    max_age_seconds: int
    required_component_owner: str | None = None
    cluster_genesis_hash: str | None = None
    allow_same_producer_verifier: bool = False

    def __post_init__(self) -> None:
        _require_requirement_id(self.requirement_id)
        if not self.accepted_sources:
            raise ValueError("at least one accepted evidence source is required")
        _require_release_digest("release_digest", self.release_digest)
        _require_sha256("policy_bundle_digest", self.policy_bundle_digest)
        if self.cluster_genesis_hash is not None:
            _require_sha256("cluster_genesis_hash", self.cluster_genesis_hash)
        if self.required_component_owner is not None:
            _require_identity("required_component_owner", self.required_component_owner)
        if self.max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")


@dataclass(frozen=True, slots=True)
class VerifiedEvidence:
    """Independent verifier result with signed provenance reference."""

    requirement_id: str
    source: EvidenceSource
    producer_id: str
    verifier_id: str
    release_digest: str
    policy_bundle_digest: str
    raw_artifact_digest: str
    result_digest: str
    provenance_signature_ref: str
    verifier_tool: str
    verified_at: datetime
    expires_at: datetime
    outcome: EvidenceOutcome
    blockers: tuple[str, ...]
    schema_version: str = PR175_VERIFIED_SCHEMA_VERSION
    cluster_genesis_hash: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != PR175_VERIFIED_SCHEMA_VERSION:
            raise ValueError("unsupported verified evidence schema")
        _require_requirement_id(self.requirement_id)
        _require_identity("producer_id", self.producer_id)
        _require_identity("verifier_id", self.verifier_id)
        _require_identity("verifier_tool", self.verifier_tool)
        _require_release_digest("release_digest", self.release_digest)
        _require_sha256("policy_bundle_digest", self.policy_bundle_digest)
        _require_sha256("raw_artifact_digest", self.raw_artifact_digest)
        _require_sha256("result_digest", self.result_digest)
        if self.cluster_genesis_hash is not None:
            _require_sha256("cluster_genesis_hash", self.cluster_genesis_hash)
        if not self.provenance_signature_ref.startswith(_ALLOWED_SIGNATURE_PREFIXES):
            raise ValueError("verified evidence requires a signed provenance reference")
        _reject_secret_text(self.provenance_signature_ref)
        _require_time("verified_at", self.verified_at)
        _require_time("expires_at", self.expires_at)
        if self.expires_at <= self.verified_at:
            raise ValueError("expires_at must be after verified_at")
        if self.outcome is EvidenceOutcome.VERIFIED and self.blockers:
            raise ValueError("verified evidence cannot carry blockers")
        if self.outcome is EvidenceOutcome.BLOCKED and not self.blockers:
            raise ValueError("blocked evidence must explain blockers")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["source"] = self.source.value
        payload["outcome"] = self.outcome.value
        payload["verified_at"] = self.verified_at.isoformat()
        payload["expires_at"] = self.expires_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class EvidenceVerificationReport:
    accepted: bool
    evidence: VerifiedEvidence
    checks_evaluated: int


class IndependentEvidenceVerifier:
    """Convert raw producer artifacts into signed verified evidence."""

    def __init__(self, *, verifier_id: str, verifier_tool: str) -> None:
        _require_identity("verifier_id", verifier_id)
        _require_identity("verifier_tool", verifier_tool)
        self.verifier_id = verifier_id
        self.verifier_tool = verifier_tool

    def verify(
        self,
        artifact: RawEvidenceArtifact,
        policy: EvidenceVerificationPolicy,
        *,
        verified_at: datetime,
        provenance_signature_ref: str,
    ) -> EvidenceVerificationReport:
        _require_time("verified_at", verified_at)
        blockers: list[str] = []
        checks = 0

        def check(condition: bool, blocker: str) -> None:
            nonlocal checks
            checks += 1
            if not condition:
                blockers.append(blocker)

        check(artifact.requirement_id == policy.requirement_id, "REQUIREMENT_MISMATCH")
        check(artifact.source in policy.accepted_sources, "SOURCE_NOT_ACCEPTED")
        check(artifact.release_digest == policy.release_digest, "RELEASE_DIGEST_MISMATCH")
        check(
            artifact.policy_bundle_digest == policy.policy_bundle_digest,
            "POLICY_BUNDLE_DIGEST_MISMATCH",
        )
        check(artifact.exit_code == 0, "PRODUCER_EXIT_NONZERO")
        check(artifact.secrets_redacted, "RAW_EVIDENCE_NOT_REDACTED")
        check(
            artifact.producer_id != self.verifier_id or policy.allow_same_producer_verifier,
            "PRODUCER_VERIFIER_NOT_INDEPENDENT",
        )
        check(
            (verified_at - artifact.finished_at).total_seconds() <= policy.max_age_seconds,
            "EVIDENCE_STALE",
        )
        if policy.required_component_owner is not None:
            check(
                artifact.component_owner == policy.required_component_owner,
                "COMPONENT_OWNER_MISMATCH",
            )
        if policy.cluster_genesis_hash is not None:
            check(
                artifact.cluster_genesis_hash == policy.cluster_genesis_hash,
                "CLUSTER_GENESIS_MISMATCH",
            )
        check(
            provenance_signature_ref.startswith(_ALLOWED_SIGNATURE_PREFIXES),
            "SIGNED_PROVENANCE_REFERENCE_MISSING",
        )

        unique_blockers = tuple(dict.fromkeys(blockers))
        outcome = EvidenceOutcome.BLOCKED if unique_blockers else EvidenceOutcome.VERIFIED
        expires_at = datetime.fromtimestamp(
            verified_at.timestamp() + policy.max_age_seconds,
            timezone.utc,
        )
        raw_digest = artifact.artifact_digest
        result_payload = {
            "artifact_digest": raw_digest,
            "blockers": unique_blockers,
            "outcome": outcome.value,
            "policy": asdict(policy),
            "verified_at": verified_at.isoformat(),
            "verifier_id": self.verifier_id,
            "verifier_tool": self.verifier_tool,
        }
        evidence = VerifiedEvidence(
            requirement_id=artifact.requirement_id,
            source=artifact.source,
            producer_id=artifact.producer_id,
            verifier_id=self.verifier_id,
            release_digest=artifact.release_digest,
            policy_bundle_digest=artifact.policy_bundle_digest,
            raw_artifact_digest=raw_digest,
            result_digest=_sha256_json(result_payload),
            provenance_signature_ref=provenance_signature_ref,
            verifier_tool=self.verifier_tool,
            verified_at=verified_at,
            expires_at=expires_at,
            outcome=outcome,
            blockers=unique_blockers,
            cluster_genesis_hash=artifact.cluster_genesis_hash,
        )
        return EvidenceVerificationReport(
            accepted=evidence.outcome is EvidenceOutcome.VERIFIED,
            evidence=evidence,
            checks_evaluated=checks,
        )


@dataclass(frozen=True, slots=True)
class VerifiedEvidencePackage:
    """Bundle consumed by readiness/release gates after PR-175."""

    package_id: str
    release_digest: str
    policy_bundle_digest: str
    evidences: tuple[VerifiedEvidence, ...]
    generated_at: datetime
    required_requirement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_identity("package_id", self.package_id)
        _require_release_digest("release_digest", self.release_digest)
        _require_sha256("policy_bundle_digest", self.policy_bundle_digest)
        _require_time("generated_at", self.generated_at)
        if not self.required_requirement_ids:
            raise ValueError("verified evidence package must declare requirements")
        for requirement_id in self.required_requirement_ids:
            _require_requirement_id(requirement_id)


@dataclass(frozen=True, slots=True)
class VerifiedEvidencePackageResult:
    ready: bool
    blockers: tuple[str, ...]
    checks_evaluated: int


def evaluate_verified_evidence_package(
    package: VerifiedEvidencePackage,
    *,
    evaluated_at: datetime,
) -> VerifiedEvidencePackageResult:
    """Fail closed unless all required requirements have current verified evidence."""

    _require_time("evaluated_at", evaluated_at)
    blockers: list[str] = []
    checks = 0
    by_requirement: dict[str, VerifiedEvidence] = {}
    duplicates: set[str] = set()
    for evidence in package.evidences:
        if evidence.requirement_id in by_requirement:
            duplicates.add(evidence.requirement_id)
        by_requirement[evidence.requirement_id] = evidence

    for requirement_id in package.required_requirement_ids:
        checks += 1
        if requirement_id not in by_requirement:
            blockers.append(f"VERIFIED_EVIDENCE_MISSING:{requirement_id}")

    for requirement_id in sorted(duplicates):
        checks += 1
        blockers.append(f"DUPLICATE_VERIFIED_EVIDENCE:{requirement_id}")

    for evidence in package.evidences:
        prefix = evidence.requirement_id
        checks += 1
        if evidence.outcome is not EvidenceOutcome.VERIFIED:
            blockers.append(f"VERIFIED_EVIDENCE_BLOCKED:{prefix}")
        checks += 1
        if evidence.release_digest != package.release_digest:
            blockers.append(f"PACKAGE_RELEASE_MISMATCH:{prefix}")
        checks += 1
        if evidence.policy_bundle_digest != package.policy_bundle_digest:
            blockers.append(f"PACKAGE_POLICY_MISMATCH:{prefix}")
        checks += 1
        if evaluated_at >= evidence.expires_at:
            blockers.append(f"VERIFIED_EVIDENCE_EXPIRED:{prefix}")

    return VerifiedEvidencePackageResult(
        ready=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        checks_evaluated=checks,
    )


def _require_requirement_id(value: str) -> None:
    if not _REQUIREMENT_RE.fullmatch(value):
        raise ValueError("requirement_id must be a stable domain id")


def _require_identity(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} is required")
    _reject_secret_text(value)


def _require_commit(value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("source_commit must be a full lowercase git SHA")
    if value == "0" * 40:
        raise ValueError("source_commit cannot be a placeholder")


def _require_release_digest(field_name: str, value: str) -> None:
    if not _RELEASE_DIGEST_RE.fullmatch(value) or value.endswith("0" * 64):
        raise ValueError(f"{field_name} must be sha256-bound")


def _require_sha256(field_name: str, value: str) -> None:
    if not _SHA256_RE.fullmatch(value) or value == "0" * 64:
        raise ValueError(f"{field_name} must be a real lowercase sha256")


def _require_time(field_name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _reject_secret_text(value: str) -> None:
    lowered = value.lower()
    if any(marker in lowered for marker in _FORBIDDEN_TEXT):
        raise ValueError("evidence metadata must not contain secret-bearing text")


def _sha256_json(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "EvidenceOutcome",
    "EvidenceSource",
    "EvidenceVerificationPolicy",
    "EvidenceVerificationReport",
    "IndependentEvidenceVerifier",
    "PR175_SCHEMA_VERSION",
    "PR175_VERIFIED_SCHEMA_VERSION",
    "RawEvidenceArtifact",
    "VerifiedEvidence",
    "VerifiedEvidencePackage",
    "VerifiedEvidencePackageResult",
    "evaluate_verified_evidence_package",
]
