"""AGG-01 lender-neutral repayment and finalized-evidence contracts.

This module is deliberately side-effect free. Protocol-specific decoders remain
separate adapters; this boundary only accepts a repayment proof when lender,
deployment generation, decoder identity, asset identity, and exact base-unit
amounts all agree. It lets later lender integrations connect to the existing
economic lifecycle without relabelling MarginFi evidence as another lender.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Protocol, Sequence

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FinancingEvidenceError(ValueError):
    """Fail-closed financing evidence error."""


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FinancingEvidenceError(f"{label} is required")
    return value


def _sha(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise FinancingEvidenceError(f"{label} must be lowercase sha256")
    return value


def _uint(value: int, label: str) -> int:
    if type(value) is not int or value < 0:
        raise FinancingEvidenceError(f"{label} must be non-negative integer")
    return value


def _digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class FinancingRepaymentEvidence:
    attempt_id: str
    attempt_generation: int
    message_hash: str
    lender_id: str
    program_id: str
    deployment_generation: int
    decoder_identity: str
    obligation_digest: str
    source_evidence_sha256: str
    asset_id: str
    debt_before_base_units: int
    debt_after_base_units: int
    required_repayment_base_units: int
    observed_repayment_base_units: int

    def __post_init__(self) -> None:
        _text(self.attempt_id, "attempt_id")
        if type(self.attempt_generation) is not int or self.attempt_generation < 1:
            raise FinancingEvidenceError("attempt_generation must be positive integer")
        _sha(self.message_hash, "message_hash")
        _text(self.lender_id, "lender_id")
        _text(self.program_id, "program_id")
        _text(self.decoder_identity, "decoder_identity")
        _text(self.asset_id, "asset_id")
        if (
            type(self.deployment_generation) is not int
            or self.deployment_generation < 1
        ):
            raise FinancingEvidenceError(
                "deployment_generation must be positive integer"
            )
        _sha(self.obligation_digest, "obligation_digest")
        _sha(self.source_evidence_sha256, "source_evidence_sha256")
        _uint(self.debt_before_base_units, "debt_before_base_units")
        _uint(self.debt_after_base_units, "debt_after_base_units")
        _uint(self.required_repayment_base_units, "required_repayment_base_units")
        _uint(self.observed_repayment_base_units, "observed_repayment_base_units")

    @property
    def digest(self) -> str:
        return _digest(
            {
                "attempt_id": self.attempt_id,
                "attempt_generation": self.attempt_generation,
                "message_hash": self.message_hash,
                "lender_id": self.lender_id,
                "program_id": self.program_id,
                "deployment_generation": self.deployment_generation,
                "decoder_identity": self.decoder_identity,
                "obligation_digest": self.obligation_digest,
                "source_evidence_sha256": self.source_evidence_sha256,
                "asset_id": self.asset_id,
                "debt_before_base_units": self.debt_before_base_units,
                "debt_after_base_units": self.debt_after_base_units,
                "required_repayment_base_units": self.required_repayment_base_units,
                "observed_repayment_base_units": self.observed_repayment_base_units,
            }
        )


@dataclass(frozen=True, slots=True)
class RepaymentDecision:
    proven: bool
    attempt_id: str
    attempt_generation: int
    message_hash: str
    lender_id: str
    program_id: str
    deployment_generation: int
    decoder_identity: str
    reason: str | None
    evidence_digest: str


class FinancingRepaymentValidator(Protocol):
    lender_id: str
    program_id: str
    deployment_generation: int
    decoder_identity: str

    def validate(self, evidence: FinancingRepaymentEvidence) -> bool: ...


def validate_financing_repayment(
    evidence: FinancingRepaymentEvidence,
    validators: Sequence[FinancingRepaymentValidator],
) -> RepaymentDecision:
    decoder_matches = [
        validator
        for validator in validators
        if validator.lender_id == evidence.lender_id
        and validator.deployment_generation == evidence.deployment_generation
        and validator.decoder_identity == evidence.decoder_identity
    ]
    if len(decoder_matches) != 1:
        return RepaymentDecision(
            False,
            evidence.attempt_id,
            evidence.attempt_generation,
            evidence.message_hash,
            evidence.lender_id,
            evidence.program_id,
            evidence.deployment_generation,
            evidence.decoder_identity,
            "FINANCING_DECODER_REQUIRED",
            evidence.digest,
        )
    validator = decoder_matches[0]
    if validator.program_id != evidence.program_id:
        return RepaymentDecision(
            False,
            evidence.attempt_id,
            evidence.attempt_generation,
            evidence.message_hash,
            evidence.lender_id,
            evidence.program_id,
            evidence.deployment_generation,
            evidence.decoder_identity,
            "FINANCING_PROGRAM_MISMATCH",
            evidence.digest,
        )
    if not validator.validate(evidence):
        return RepaymentDecision(
            False,
            evidence.attempt_id,
            evidence.attempt_generation,
            evidence.message_hash,
            evidence.lender_id,
            evidence.program_id,
            evidence.deployment_generation,
            evidence.decoder_identity,
            "FINANCING_REPAYMENT_NOT_PROVEN",
            evidence.digest,
        )
    return RepaymentDecision(
        True,
        evidence.attempt_id,
        evidence.attempt_generation,
        evidence.message_hash,
        evidence.lender_id,
        evidence.program_id,
        evidence.deployment_generation,
        evidence.decoder_identity,
        None,
        evidence.digest,
    )


@dataclass(frozen=True, slots=True)
class FinalizedFinancingEvidence:
    attempt_id: str
    attempt_generation: int
    message_hash: str
    finalized_slot: int
    repayment: RepaymentDecision

    def __post_init__(self) -> None:
        _text(self.attempt_id, "attempt_id")
        if type(self.attempt_generation) is not int or self.attempt_generation < 1:
            raise FinancingEvidenceError("attempt_generation must be positive integer")
        _sha(self.message_hash, "message_hash")
        _uint(self.finalized_slot, "finalized_slot")
        if not self.repayment.proven:
            raise FinancingEvidenceError("FINALIZED_FINANCING_REPAYMENT_NOT_PROVEN")
        if self.repayment.attempt_id != self.attempt_id:
            raise FinancingEvidenceError("FINALIZED_FINANCING_ATTEMPT_MISMATCH")
        if self.repayment.attempt_generation != self.attempt_generation:
            raise FinancingEvidenceError("FINALIZED_FINANCING_GENERATION_MISMATCH")
        if self.repayment.message_hash != self.message_hash:
            raise FinancingEvidenceError("FINALIZED_FINANCING_MESSAGE_MISMATCH")

    @property
    def digest(self) -> str:
        return _digest(
            {
                "attempt_id": self.attempt_id,
                "attempt_generation": self.attempt_generation,
                "message_hash": self.message_hash,
                "finalized_slot": self.finalized_slot,
                "repayment_evidence_digest": self.repayment.evidence_digest,
                "repayment_attempt_id": self.repayment.attempt_id,
                "repayment_attempt_generation": self.repayment.attempt_generation,
                "repayment_message_hash": self.repayment.message_hash,
                "lender_id": self.repayment.lender_id,
                "program_id": self.repayment.program_id,
                "deployment_generation": self.repayment.deployment_generation,
                "decoder_identity": self.repayment.decoder_identity,
            }
        )


__all__ = [
    "FinalizedFinancingEvidence",
    "FinancingEvidenceError",
    "FinancingRepaymentEvidence",
    "FinancingRepaymentValidator",
    "RepaymentDecision",
    "validate_financing_repayment",
]
