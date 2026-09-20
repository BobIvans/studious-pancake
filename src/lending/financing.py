"""AGG-01 lender-neutral financing contracts.

The contracts in this module are deliberately sender-free.  They bind a lending
obligation to an exact lender/deployment generation and to immutable evidence,
but they do not fetch state, sign, submit, or create a second lifecycle/capital
owner.  Protocol adapters added by later AGG packages must satisfy this boundary
and remain responsible for their protocol-specific instruction/state decoding.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Protocol, Sequence

from solders.instruction import Instruction

FINANCING_CONTRACT_VERSION = "agg01.financing-obligation.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FinancingRole(StrEnum):
    PRIMARY = "primary"
    RENT = "rent"


class FinancingContractError(ValueError):
    """Fail-closed financing-contract error."""


def _require_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FinancingContractError(f"{label} is required")
    return value


def _require_sha256(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise FinancingContractError(f"{label} must be lowercase sha256")
    return value


def _positive_int(value: int, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise FinancingContractError(f"{label} must be a positive non-bool integer")
    return value


def _canonical_hash(payload: object) -> str:
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
class FinancingEvidence:
    """Immutable lender/deployment/decoder evidence identity."""

    lender_id: str
    program_id: str
    deployment_generation: int
    evidence_sha256: str
    decoder_identity: str
    decoder_generation: int
    contract_version: str = FINANCING_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.lender_id, "lender_id")
        _require_text(self.program_id, "program_id")
        _positive_int(self.deployment_generation, "deployment_generation")
        _require_sha256(self.evidence_sha256, "evidence_sha256")
        _require_text(self.decoder_identity, "decoder_identity")
        _positive_int(self.decoder_generation, "decoder_generation")
        if self.contract_version != FINANCING_CONTRACT_VERSION:
            raise FinancingContractError("unsupported financing contract version")

    @property
    def digest(self) -> str:
        return _canonical_hash(
            {
                "contract_version": self.contract_version,
                "lender_id": self.lender_id,
                "program_id": self.program_id,
                "deployment_generation": self.deployment_generation,
                "evidence_sha256": self.evidence_sha256,
                "decoder_identity": self.decoder_identity,
                "decoder_generation": self.decoder_generation,
            }
        )


@dataclass(frozen=True, slots=True)
class FinancingObligation:
    """Exact debt obligation carried through planning/evidence boundaries."""

    obligation_id: str
    role: FinancingRole
    lender_id: str
    program_id: str
    deployment_generation: int
    asset_id: str
    principal_base_units: int
    required_repayment_base_units: int
    evidence_sha256: str
    repayment_destination: str
    instruction_constraints_sha256: str
    contract_version: str = FINANCING_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_text(self.obligation_id, "obligation_id")
        if not isinstance(self.role, FinancingRole):
            raise FinancingContractError("role must be FinancingRole")
        _require_text(self.lender_id, "lender_id")
        _require_text(self.program_id, "program_id")
        _positive_int(self.deployment_generation, "deployment_generation")
        _require_text(self.asset_id, "asset_id")
        _positive_int(self.principal_base_units, "principal_base_units")
        _positive_int(
            self.required_repayment_base_units, "required_repayment_base_units"
        )
        if self.required_repayment_base_units < self.principal_base_units:
            raise FinancingContractError("repayment cannot be below principal")
        _require_sha256(self.evidence_sha256, "evidence_sha256")
        _require_text(self.repayment_destination, "repayment_destination")
        _require_sha256(
            self.instruction_constraints_sha256,
            "instruction_constraints_sha256",
        )
        if self.contract_version != FINANCING_CONTRACT_VERSION:
            raise FinancingContractError("unsupported financing contract version")

    @property
    def digest(self) -> str:
        return _canonical_hash(
            {
                "contract_version": self.contract_version,
                "obligation_id": self.obligation_id,
                "role": self.role.value,
                "lender_id": self.lender_id,
                "program_id": self.program_id,
                "deployment_generation": self.deployment_generation,
                "asset_id": self.asset_id,
                "principal_base_units": self.principal_base_units,
                "required_repayment_base_units": self.required_repayment_base_units,
                "evidence_sha256": self.evidence_sha256,
                "repayment_destination": self.repayment_destination,
                "instruction_constraints_sha256": self.instruction_constraints_sha256,
            }
        )


@dataclass(frozen=True, slots=True)
class PreparedFinancing:
    """Protocol adapter output before final instruction ordering."""

    obligation: FinancingObligation
    borrow_instructions: tuple[Instruction, ...]
    repay_instructions: tuple[Instruction, ...]
    min_context_slot: int
    state_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "borrow_instructions", tuple(self.borrow_instructions))
        object.__setattr__(self, "repay_instructions", tuple(self.repay_instructions))
        if not self.borrow_instructions or not self.repay_instructions:
            raise FinancingContractError("borrow and repay instructions are required")
        if type(self.min_context_slot) is not int or self.min_context_slot < 0:
            raise FinancingContractError(
                "min_context_slot must be non-negative integer"
            )
        _require_sha256(self.state_fingerprint, "state_fingerprint")


@dataclass(frozen=True, slots=True)
class FinalizedFinancing:
    """Final protocol-specific bookends after immutable sequence resolution."""

    obligation: FinancingObligation
    instructions: tuple[Instruction, ...]
    sequence_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "instructions", tuple(self.instructions))
        if not self.instructions:
            raise FinancingContractError("finalized instructions are required")
        _require_sha256(self.sequence_fingerprint, "sequence_fingerprint")


class FinancingPort(Protocol):
    """Unsigned adapter boundary implemented by a qualified lender integration."""

    lender_id: str
    deployment_generation: int
    execution_conformance_verified: bool

    def prepare(
        self,
        *,
        snapshot: Any,
        amount: int,
        destination_account: str,
        repayment_source_account: str,
        minimum_terminal_balance: int,
        role: FinancingRole = FinancingRole.PRIMARY,
    ) -> PreparedFinancing: ...

    def finalize(
        self,
        prepared: PreparedFinancing,
        immutable_sequence: Sequence[Instruction],
    ) -> FinalizedFinancing: ...


def validate_financing_binding(
    *,
    lender_id: str,
    deployment_generation: int,
    evidence: FinancingEvidence,
    obligations: Sequence[FinancingObligation] = (),
) -> tuple[FinancingObligation, ...]:
    """Validate one profile/evidence/obligation generation without side effects."""

    _require_text(lender_id, "lender_id")
    _positive_int(deployment_generation, "deployment_generation")
    if evidence.lender_id != lender_id:
        raise FinancingContractError("FINANCING_LENDER_MISMATCH")
    if evidence.deployment_generation != deployment_generation:
        raise FinancingContractError("FINANCING_GENERATION_MISMATCH")
    normalized = tuple(obligations)
    seen: set[str] = set()
    for obligation in normalized:
        if obligation.obligation_id in seen:
            raise FinancingContractError("DUPLICATE_FINANCING_OBLIGATION")
        seen.add(obligation.obligation_id)
        if obligation.lender_id != lender_id:
            raise FinancingContractError("FINANCING_OBLIGATION_LENDER_MISMATCH")
        if obligation.deployment_generation != deployment_generation:
            raise FinancingContractError("FINANCING_OBLIGATION_GENERATION_MISMATCH")
        if obligation.program_id != evidence.program_id:
            raise FinancingContractError("FINANCING_PROGRAM_MISMATCH")
        if obligation.evidence_sha256 != evidence.evidence_sha256:
            raise FinancingContractError("FINANCING_EVIDENCE_MISMATCH")
    return normalized


__all__ = [
    "FINANCING_CONTRACT_VERSION",
    "FinalizedFinancing",
    "FinancingContractError",
    "FinancingEvidence",
    "FinancingObligation",
    "FinancingPort",
    "FinancingRole",
    "PreparedFinancing",
    "validate_financing_binding",
]
