"""MPR-2619 fail-closed liquidation qualification boundary.

This module does not authorize live liquidation. It exists to prevent the
fixture-only liquidation package from being promoted by configuration alone and
to define the evidence that a future exact MarginFi classic implementation must
supply before it can become executable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Iterable

LEGACY_FINANCING_PROGRAM = "marginfi_flashloan_provider_pr009"
LEGACY_UNWIND_PROGRAM = "route"
LEGACY_END_INDEX_MARKER = "end_index:"


class LiquidationMode(str, Enum):
    MARGINFI_CLASSIC = "marginfi_classic"
    MARGINFI_RECEIVERSHIP = "marginfi_receivership"
    MARGINFI_DELEVERAGE = "marginfi_deleverage"
    KAMINO = "kamino_liquidation"


class QualificationVerdict(str, Enum):
    BLOCKED = "blocked"
    VERIFIED_OFFLINE = "verified_offline"


class Blocker(str, Enum):
    FIXTURE_ONLY_QUARANTINE = "fixture_only_quarantine"
    EXACT_ABI_UNPROVEN = "exact_abi_unproven"
    FINANCING_UNQUALIFIED = "financing_unqualified"
    UNWIND_UNQUALIFIED = "unwind_unqualified"
    FINAL_SIMULATION_DECODER_UNPROVEN = "final_simulation_decoder_unproven"
    ECONOMIC_LEDGER_UNPROVEN = "economic_ledger_unproven"
    CIRCUIT_BREAKER_STATE_UNPROVEN = "circuit_breaker_state_unproven"
    UNSUPPORTED_LIQUIDATION_MODE = "unsupported_liquidation_mode"
    LEGACY_PLACEHOLDER_INSTRUCTION = "legacy_placeholder_instruction"
    UNEXPECTED_PROGRAM = "unexpected_program"
    UNEXPECTED_INSTRUCTION = "unexpected_instruction"
    RAW_SIMULATION_EVIDENCE_REQUIRED = "raw_simulation_evidence_required"
    TARGET_STATE_CHANGE_UNPROVEN = "target_state_change_unproven"
    FLASH_REPAYMENT_UNPROVEN = "flash_repayment_unproven"
    ECONOMICS_INCOMPLETE = "economics_incomplete"
    NON_POSITIVE_REALIZED_PNL = "non_positive_realized_pnl"


@dataclass(frozen=True, slots=True)
class LiquidationCapabilityEvidence:
    mode: LiquidationMode
    fixture_only_quarantine: bool
    exact_abi_proven: bool
    financing_qualified: bool
    unwind_qualified: bool
    final_simulation_decoder_proven: bool
    economic_ledger_proven: bool
    circuit_breaker_state_proven: bool
    source_commit: str
    deployment_generation: str
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class QualificationDecision:
    verdict: QualificationVerdict
    blockers: tuple[Blocker, ...]
    decision_hash: str


@dataclass(frozen=True, slots=True)
class InstructionDescriptor:
    program_id: str
    name: str
    data_hex: str = ""
    writable_accounts: tuple[str, ...] = ()
    signer_accounts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FirewallPolicy:
    allowed_program_ids: frozenset[str]
    allowed_instruction_names: frozenset[str]


@dataclass(frozen=True, slots=True)
class SimulationRawProof:
    raw_simulation_hash: str
    returned_accounts_hash: str
    simulation_slot: int
    target_debt_delta: int | None
    target_collateral_delta: int | None
    flash_principal: int | None
    flash_fee: int | None
    flash_repayment_observed: int | None
    economics_complete: bool
    realized_pnl_atomic_units: int | None


@dataclass(frozen=True, slots=True)
class SimulationProofDecision:
    accepted: bool
    blockers: tuple[Blocker, ...]
    proof_hash: str


def qualify_liquidation_capability(
    evidence: LiquidationCapabilityEvidence,
) -> QualificationDecision:
    blockers: list[Blocker] = []

    if evidence.mode is not LiquidationMode.MARGINFI_CLASSIC:
        blockers.append(Blocker.UNSUPPORTED_LIQUIDATION_MODE)
    if evidence.fixture_only_quarantine:
        blockers.append(Blocker.FIXTURE_ONLY_QUARANTINE)
    if not evidence.exact_abi_proven:
        blockers.append(Blocker.EXACT_ABI_UNPROVEN)
    if not evidence.financing_qualified:
        blockers.append(Blocker.FINANCING_UNQUALIFIED)
    if not evidence.unwind_qualified:
        blockers.append(Blocker.UNWIND_UNQUALIFIED)
    if not evidence.final_simulation_decoder_proven:
        blockers.append(Blocker.FINAL_SIMULATION_DECODER_UNPROVEN)
    if not evidence.economic_ledger_proven:
        blockers.append(Blocker.ECONOMIC_LEDGER_UNPROVEN)
    if not evidence.circuit_breaker_state_proven:
        blockers.append(Blocker.CIRCUIT_BREAKER_STATE_UNPROVEN)

    blockers_tuple = tuple(dict.fromkeys(blockers))
    verdict = (
        QualificationVerdict.VERIFIED_OFFLINE
        if not blockers_tuple
        else QualificationVerdict.BLOCKED
    )
    return QualificationDecision(
        verdict=verdict,
        blockers=blockers_tuple,
        decision_hash=_hash_json(
            {
                "mode": evidence.mode.value,
                "source_commit": evidence.source_commit,
                "deployment_generation": evidence.deployment_generation,
                "evidence_hash": evidence.evidence_hash,
                "verdict": verdict.value,
                "blockers": [blocker.value for blocker in blockers_tuple],
            }
        ),
    )


def validate_instruction_firewall(
    instructions: Iterable[InstructionDescriptor],
    policy: FirewallPolicy,
) -> tuple[Blocker, ...]:
    blockers: list[Blocker] = []
    for instruction in instructions:
        if (
            instruction.program_id == LEGACY_FINANCING_PROGRAM
            or instruction.program_id == LEGACY_UNWIND_PROGRAM
            or LEGACY_END_INDEX_MARKER in instruction.data_hex
        ):
            blockers.append(Blocker.LEGACY_PLACEHOLDER_INSTRUCTION)
        if instruction.program_id not in policy.allowed_program_ids:
            blockers.append(Blocker.UNEXPECTED_PROGRAM)
        if instruction.name not in policy.allowed_instruction_names:
            blockers.append(Blocker.UNEXPECTED_INSTRUCTION)
    return tuple(dict.fromkeys(blockers))


def verify_raw_simulation_proof(
    proof: SimulationRawProof,
) -> SimulationProofDecision:
    blockers: list[Blocker] = []
    if not proof.raw_simulation_hash or not proof.returned_accounts_hash:
        blockers.append(Blocker.RAW_SIMULATION_EVIDENCE_REQUIRED)
    if (
        proof.target_debt_delta is None
        or proof.target_collateral_delta is None
        or proof.target_debt_delta >= 0
        or proof.target_collateral_delta >= 0
    ):
        blockers.append(Blocker.TARGET_STATE_CHANGE_UNPROVEN)

    if (
        proof.flash_principal is None
        or proof.flash_fee is None
        or proof.flash_repayment_observed is None
        or proof.flash_principal < 0
        or proof.flash_fee < 0
        or proof.flash_repayment_observed
        != proof.flash_principal + proof.flash_fee
    ):
        blockers.append(Blocker.FLASH_REPAYMENT_UNPROVEN)

    if not proof.economics_complete or proof.realized_pnl_atomic_units is None:
        blockers.append(Blocker.ECONOMICS_INCOMPLETE)
    elif proof.realized_pnl_atomic_units <= 0:
        blockers.append(Blocker.NON_POSITIVE_REALIZED_PNL)

    blockers_tuple = tuple(dict.fromkeys(blockers))
    return SimulationProofDecision(
        accepted=not blockers_tuple,
        blockers=blockers_tuple,
        proof_hash=_hash_json(
            {
                "raw_simulation_hash": proof.raw_simulation_hash,
                "returned_accounts_hash": proof.returned_accounts_hash,
                "simulation_slot": proof.simulation_slot,
                "target_debt_delta": proof.target_debt_delta,
                "target_collateral_delta": proof.target_collateral_delta,
                "flash_principal": proof.flash_principal,
                "flash_fee": proof.flash_fee,
                "flash_repayment_observed": proof.flash_repayment_observed,
                "economics_complete": proof.economics_complete,
                "realized_pnl_atomic_units": proof.realized_pnl_atomic_units,
                "blockers": [blocker.value for blocker in blockers_tuple],
            }
        ),
    )


def _hash_json(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "Blocker",
    "FirewallPolicy",
    "InstructionDescriptor",
    "LEGACY_END_INDEX_MARKER",
    "LEGACY_FINANCING_PROGRAM",
    "LEGACY_UNWIND_PROGRAM",
    "LiquidationCapabilityEvidence",
    "LiquidationMode",
    "QualificationDecision",
    "QualificationVerdict",
    "SimulationProofDecision",
    "SimulationRawProof",
    "qualify_liquidation_capability",
    "validate_instruction_firewall",
    "verify_raw_simulation_proof",
]
