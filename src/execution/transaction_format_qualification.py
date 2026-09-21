"""SUPER-04 / W2-12 transaction-format qualification evidence.

The repository canonical compiler is currently Solana v0-only.  This module
does not invent a v1 serializer.  It records pinned capability evidence and
fails closed until an actual canonical v1 adapter, decoder and finalized
conformance path are present.  It never signs or submits transactions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re

SUPER04_FORMAT_SCHEMA = "super04.transaction-format-qualification.v1"
CANONICAL_V0_OWNER = "src.execution.transaction_compiler.TransactionCompiler"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_OID_RE = re.compile(r"^[0-9a-f]{40,64}$")


class TransactionDialect(StrEnum):
    V0 = "v0"
    V1 = "v1"


class FormatQualificationStatus(StrEnum):
    QUALIFIED_OFFLINE = "qualified_offline"
    BLOCKED = "blocked"


class TransactionFormatQualificationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TransactionFormatQualificationError(
            f"SUPER04_FORMAT_INVALID_{label.upper()}"
        )


def _sha(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise TransactionFormatQualificationError(
            f"SUPER04_FORMAT_INVALID_{label.upper()}"
        )


def _git_oid(value: str, label: str) -> None:
    if not isinstance(value, str) or not _GIT_OID_RE.fullmatch(value):
        raise TransactionFormatQualificationError(
            f"SUPER04_FORMAT_INVALID_{label.upper()}"
        )


def _nonnegative(value: int, label: str) -> None:
    if type(value) is not int or value < 0:
        raise TransactionFormatQualificationError(
            f"SUPER04_FORMAT_INVALID_{label.upper()}"
        )


def _hash_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class TransactionFormatCapabilityEvidence:
    dialect: TransactionDialect
    sdk_name: str
    sdk_version: str
    sdk_artifact_hash: str
    source_repository: str
    source_commit: str
    codec_symbol: str
    license_decision: str
    evidence_hash: str
    observed_at_ms: int
    expires_at_ms: int
    compile_supported: bool
    decode_supported: bool
    simulation_supported: bool
    finalized_decode_supported: bool

    def __post_init__(self) -> None:
        for value, label in (
            (self.sdk_name, "sdk_name"),
            (self.sdk_version, "sdk_version"),
            (self.source_repository, "source_repository"),
            (self.codec_symbol, "codec_symbol"),
            (self.license_decision, "license_decision"),
        ):
            _text(value, label)
        _sha(self.sdk_artifact_hash, "sdk_artifact_hash")
        _git_oid(self.source_commit, "source_commit")
        _sha(self.evidence_hash, "evidence_hash")
        _nonnegative(self.observed_at_ms, "observed_at_ms")
        _nonnegative(self.expires_at_ms, "expires_at_ms")
        if self.expires_at_ms <= self.observed_at_ms:
            raise TransactionFormatQualificationError(
                "SUPER04_FORMAT_INVALID_EXPIRY"
            )


@dataclass(frozen=True, slots=True)
class TransactionFormatAssessment:
    dialect: TransactionDialect
    status: FormatQualificationStatus
    reason_code: str
    evidence_hash: str | None
    canonical_owner: str
    assessment_hash: str
    live_enabled: bool = False
    signing_enabled: bool = False
    submission_enabled: bool = False


def assess_transaction_format(
    *,
    dialect: TransactionDialect,
    evidence: TransactionFormatCapabilityEvidence | None,
    now_ms: int,
) -> TransactionFormatAssessment:
    """NF-349 evidence gate without creating a second compiler owner."""

    _nonnegative(now_ms, "now_ms")
    reason = "FORMAT_NOT_QUALIFIED"
    status = FormatQualificationStatus.BLOCKED
    evidence_hash: str | None = None

    if dialect is TransactionDialect.V0:
        # Current repository authority is the existing MessageV0 compiler.
        reason = "CANONICAL_V0_OWNER"
        status = FormatQualificationStatus.QUALIFIED_OFFLINE
    elif evidence is None:
        reason = "V1_CAPABILITY_EVIDENCE_MISSING"
    elif evidence.dialect is not TransactionDialect.V1:
        reason = "V1_CAPABILITY_DIALECT_MISMATCH"
    elif now_ms >= evidence.expires_at_ms:
        reason = "CAPABILITY_EXPIRED"
        evidence_hash = evidence.evidence_hash
    elif evidence.license_decision.strip().upper() in {
        "UNKNOWN",
        "UNSPECIFIED",
        "BLOCKED",
    }:
        reason = "V1_LICENSE_UNRESOLVED"
        evidence_hash = evidence.evidence_hash
    elif not (
        evidence.compile_supported
        and evidence.decode_supported
        and evidence.simulation_supported
        and evidence.finalized_decode_supported
    ):
        reason = "V1_CAPABILITY_INCOMPLETE"
        evidence_hash = evidence.evidence_hash
    else:
        # Important: external capability evidence is not a local compiler.
        # src.execution.transaction_compiler still compiles MessageV0 only.
        reason = "V1_CANONICAL_COMPILER_NOT_IMPLEMENTED"
        evidence_hash = evidence.evidence_hash

    payload = {
        "schema": SUPER04_FORMAT_SCHEMA,
        "dialect": dialect.value,
        "status": status.value,
        "reason_code": reason,
        "evidence_hash": evidence_hash,
        "canonical_owner": CANONICAL_V0_OWNER,
    }
    return TransactionFormatAssessment(
        dialect=dialect,
        status=status,
        reason_code=reason,
        evidence_hash=evidence_hash,
        canonical_owner=CANONICAL_V0_OWNER,
        assessment_hash=_hash_json(payload),
        live_enabled=False,
        signing_enabled=False,
        submission_enabled=False,
    )


@dataclass(frozen=True, slots=True)
class V1ExecutionEvidenceRequest:
    plan_hash: str
    message_hash: str
    simulation_hash: str
    permit_hash: str
    decoder_evidence_hash: str
    finalized_evidence_hash: str

    def __post_init__(self) -> None:
        for label, value in asdict(self).items():
            _sha(value, label)


@dataclass(frozen=True, slots=True)
class V1ConformanceVerdict:
    accepted: bool
    reason_code: str
    verdict_hash: str
    live_enabled: bool = False


def bind_v1_exact_execution_evidence(
    *,
    assessment: TransactionFormatAssessment,
    request: V1ExecutionEvidenceRequest,
) -> V1ConformanceVerdict:
    """NF-350..352 stay blocked until the canonical v1 adapter exists."""

    if assessment.dialect is not TransactionDialect.V1:
        raise TransactionFormatQualificationError("FORMAT_HASH_MISMATCH")

    reason = (
        "V1_CANONICAL_COMPILER_NOT_IMPLEMENTED"
        if assessment.status is FormatQualificationStatus.BLOCKED
        else "V1_LOCAL_ADAPTER_REQUIRED"
    )
    payload = {
        "schema": SUPER04_FORMAT_SCHEMA,
        "assessment_hash": assessment.assessment_hash,
        "request": asdict(request),
        "accepted": False,
        "reason_code": reason,
    }
    return V1ConformanceVerdict(
        accepted=False,
        reason_code=reason,
        verdict_hash=_hash_json(payload),
        live_enabled=False,
    )


__all__ = [
    "CANONICAL_V0_OWNER",
    "FormatQualificationStatus",
    "SUPER04_FORMAT_SCHEMA",
    "TransactionDialect",
    "TransactionFormatAssessment",
    "TransactionFormatCapabilityEvidence",
    "TransactionFormatQualificationError",
    "V1ConformanceVerdict",
    "V1ExecutionEvidenceRequest",
    "assess_transaction_format",
    "bind_v1_exact_execution_evidence",
]
