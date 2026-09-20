"""Adapter from AGG-01 FinancingPort to the canonical atomic planner surface.

This module is compatibility glue only. It does not emulate MarginFi state and
it does not relabel lender evidence. The wrapped planner receives an explicit
FinancingPlannerSnapshot and branches on uses_flashloan_bookends=False.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from solders.instruction import Instruction

from src.lending.financing import (
    FinancingContractError,
    FinancingEvidence,
    FinancingPort,
    FinancingRole,
    PreparedFinancing,
    validate_financing_binding,
)


@dataclass(frozen=True, slots=True)
class FinancingPlannerSnapshot:
    protocol_snapshot: Any
    asset_mint: str
    asset_id: str
    payer: str
    slot: int
    available_liquidity_base_units: int
    monitored_accounts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (
            ("asset_mint", self.asset_mint),
            ("asset_id", self.asset_id),
            ("payer", self.payer),
        ):
            if not isinstance(value, str) or not value.strip():
                raise FinancingContractError(f"{label} is required")
        if type(self.slot) is not int or self.slot < 0:
            raise FinancingContractError("slot must be non-negative integer")
        if (
            type(self.available_liquidity_base_units) is not int
            or self.available_liquidity_base_units < 0
        ):
            raise FinancingContractError(
                "available_liquidity_base_units must be non-negative integer"
            )
        if len(set(self.monitored_accounts)) != len(self.monitored_accounts):
            raise FinancingContractError("duplicate monitored account")


@dataclass(frozen=True, slots=True)
class PreparedFinancingPlannerLoan:
    raw: PreparedFinancing
    borrow_instruction: Instruction
    repay_instruction: Instruction
    required_repayment: int
    min_context_slot: int
    pin_hash: str
    state_fingerprint: str


@dataclass(frozen=True, slots=True)
class FinalizedFinancingPlannerLoan:
    instructions: tuple[Instruction, ...]
    start_index: int
    end_index: int
    required_repayment: int
    sequence_fingerprint: str


class FinancingPlannerProviderAdapter:
    """Expose a verified FinancingPort through the existing planner protocol."""

    execution_conformance_verified = True
    uses_flashloan_bookends = False

    def __init__(
        self,
        port: FinancingPort,
        evidence: FinancingEvidence,
    ) -> None:
        if getattr(port, "execution_conformance_verified", False) is not True:
            raise FinancingContractError(
                "FINANCING_EXECUTION_CONFORMANCE_REQUIRED"
            )
        if port.lender_id != evidence.lender_id:
            raise FinancingContractError("FINANCING_LENDER_MISMATCH")
        if port.deployment_generation != evidence.deployment_generation:
            raise FinancingContractError("FINANCING_GENERATION_MISMATCH")
        self.port = port
        self.evidence = evidence
        self.lender_id = evidence.lender_id
        self.program_id = evidence.program_id
        self.deployment_generation = evidence.deployment_generation

    def prepare(
        self,
        *,
        snapshot: Any,
        amount: int,
        destination_token_account: str,
        repayment_source_token_account: str,
        min_final_balance: int,
        safety_surplus: int = 0,
    ) -> PreparedFinancingPlannerLoan:
        if type(snapshot) is not FinancingPlannerSnapshot:
            raise FinancingContractError("FINANCING_PLANNER_SNAPSHOT_REQUIRED")
        if amount > snapshot.available_liquidity_base_units:
            raise FinancingContractError("FINANCING_INSUFFICIENT_LIQUIDITY")
        minimum_terminal = min_final_balance
        if safety_surplus:
            minimum_terminal = max(minimum_terminal, amount + safety_surplus)
        prepared = self.port.prepare(
            snapshot=snapshot.protocol_snapshot,
            amount=amount,
            destination_account=destination_token_account,
            repayment_source_account=repayment_source_token_account,
            minimum_terminal_balance=minimum_terminal,
            role=FinancingRole.PRIMARY,
        )
        validate_financing_binding(
            lender_id=self.lender_id,
            deployment_generation=self.deployment_generation,
            evidence=self.evidence,
            obligations=(prepared.obligation,),
        )
        if prepared.obligation.asset_id != snapshot.asset_id:
            raise FinancingContractError("FINANCING_ASSET_MISMATCH")
        if prepared.obligation.principal_base_units != amount:
            raise FinancingContractError("FINANCING_PRINCIPAL_MISMATCH")
        if len(prepared.borrow_instructions) != 1 or len(prepared.repay_instructions) != 1:
            raise FinancingContractError(
                "PRIMARY_FINANCING_SINGLE_BORROW_REPAY_REQUIRED"
            )
        return PreparedFinancingPlannerLoan(
            raw=prepared,
            borrow_instruction=prepared.borrow_instructions[0],
            repay_instruction=prepared.repay_instructions[0],
            required_repayment=prepared.obligation.required_repayment_base_units,
            min_context_slot=prepared.min_context_slot,
            pin_hash=self.evidence.digest,
            state_fingerprint=prepared.state_fingerprint,
        )

    def finalize(
        self,
        prepared: PreparedFinancingPlannerLoan,
        immutable_sequence: Sequence[Instruction],
    ) -> FinalizedFinancingPlannerLoan:
        sequence = tuple(immutable_sequence)
        finalized = self.port.finalize(prepared.raw, sequence)
        if finalized.instructions != sequence:
            raise FinancingContractError("FINANCING_SEQUENCE_MUTATED")
        try:
            start = sequence.index(prepared.borrow_instruction)
            end = sequence.index(prepared.repay_instruction)
        except ValueError as exc:
            raise FinancingContractError("FINANCING_BOOKENDS_MISSING") from exc
        if start >= end:
            raise FinancingContractError("FINANCING_ORDER_INVALID")
        return FinalizedFinancingPlannerLoan(
            instructions=sequence,
            start_index=start,
            end_index=end,
            required_repayment=prepared.required_repayment,
            sequence_fingerprint=finalized.sequence_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class PreparedAuxiliaryFinancingLoan:
    raw: PreparedFinancing
    borrow_instruction: Instruction
    repay_instructions: tuple[Instruction, ...]
    required_repayment: int
    min_context_slot: int
    pin_hash: str
    state_fingerprint: str


@dataclass(frozen=True, slots=True)
class FinalizedAuxiliaryFinancingLoan:
    instructions: tuple[Instruction, ...]
    borrow_index: int
    repay_indices: tuple[int, ...]
    required_repayment: int
    sequence_fingerprint: str


class AuxiliaryFinancingPlannerAdapter:
    """Expose a RENT FinancingPort around the same immutable atomic sequence."""

    execution_conformance_verified = True

    def __init__(self, port: FinancingPort, evidence: FinancingEvidence) -> None:
        if getattr(port, "execution_conformance_verified", False) is not True:
            raise FinancingContractError(
                "FINANCING_EXECUTION_CONFORMANCE_REQUIRED"
            )
        if port.lender_id != evidence.lender_id:
            raise FinancingContractError("FINANCING_LENDER_MISMATCH")
        if port.deployment_generation != evidence.deployment_generation:
            raise FinancingContractError("FINANCING_GENERATION_MISMATCH")
        self.port = port
        self.evidence = evidence
        self.lender_id = evidence.lender_id
        self.program_id = evidence.program_id
        self.deployment_generation = evidence.deployment_generation

    def prepare(
        self,
        *,
        snapshot: FinancingPlannerSnapshot,
        amount: int,
        destination_account: str,
        repayment_source_account: str,
        min_final_balance: int,
    ) -> PreparedAuxiliaryFinancingLoan:
        if amount > snapshot.available_liquidity_base_units:
            raise FinancingContractError("FINANCING_INSUFFICIENT_LIQUIDITY")
        prepared = self.port.prepare(
            snapshot=snapshot.protocol_snapshot,
            amount=amount,
            destination_account=destination_account,
            repayment_source_account=repayment_source_account,
            minimum_terminal_balance=min_final_balance,
            role=FinancingRole.RENT,
        )
        validate_financing_binding(
            lender_id=self.lender_id,
            deployment_generation=self.deployment_generation,
            evidence=self.evidence,
            obligations=(prepared.obligation,),
        )
        if prepared.obligation.role is not FinancingRole.RENT:
            raise FinancingContractError("FINANCING_RENT_ROLE_REQUIRED")
        if prepared.obligation.principal_base_units != amount:
            raise FinancingContractError("FINANCING_PRINCIPAL_MISMATCH")
        if len(prepared.borrow_instructions) != 1 or not prepared.repay_instructions:
            raise FinancingContractError("RENT_FINANCING_BOOKENDS_REQUIRED")
        return PreparedAuxiliaryFinancingLoan(
            raw=prepared,
            borrow_instruction=prepared.borrow_instructions[0],
            repay_instructions=prepared.repay_instructions,
            required_repayment=prepared.obligation.required_repayment_base_units,
            min_context_slot=prepared.min_context_slot,
            pin_hash=self.evidence.digest,
            state_fingerprint=prepared.state_fingerprint,
        )

    def finalize(
        self,
        prepared: PreparedAuxiliaryFinancingLoan,
        immutable_sequence: Sequence[Instruction],
    ) -> FinalizedAuxiliaryFinancingLoan:
        sequence = tuple(immutable_sequence)
        finalized = self.port.finalize(prepared.raw, sequence)
        if finalized.instructions != sequence:
            raise FinancingContractError("FINANCING_SEQUENCE_MUTATED")
        try:
            borrow_index = sequence.index(prepared.borrow_instruction)
            repay_indices = tuple(
                sequence.index(item) for item in prepared.repay_instructions
            )
        except ValueError as exc:
            raise FinancingContractError("FINANCING_BOOKENDS_MISSING") from exc
        if not repay_indices or borrow_index >= min(repay_indices):
            raise FinancingContractError("FINANCING_ORDER_INVALID")
        return FinalizedAuxiliaryFinancingLoan(
            instructions=sequence,
            borrow_index=borrow_index,
            repay_indices=repay_indices,
            required_repayment=prepared.required_repayment,
            sequence_fingerprint=finalized.sequence_fingerprint,
        )


__all__ = [
    "AuxiliaryFinancingPlannerAdapter",
    "FinalizedAuxiliaryFinancingLoan",
    "FinalizedFinancingPlannerLoan",
    "FinancingPlannerProviderAdapter",
    "FinancingPlannerSnapshot",
    "PreparedAuxiliaryFinancingLoan",
    "PreparedFinancingPlannerLoan",
]
