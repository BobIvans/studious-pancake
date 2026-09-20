"""AGG-03 concrete unsigned FinancingPort adapters.

These adapters bridge the source-pinned Jupiter Lend and Slumlord contracts into
AGG-01's lender-neutral FinancingPort without adding a signer, sender, network
client, lifecycle store, or capital authority.  Construction requires immutable
FinancingEvidence; protocol state is supplied explicitly by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Sequence

from solders.instruction import Instruction
from solders.pubkey import Pubkey

from src.lending.financing import (
    FinalizedFinancing,
    FinancingContractError,
    FinancingEvidence,
    FinancingObligation,
    FinancingRole,
    PreparedFinancing,
)
from src.lending.jupiter_lend import (
    JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
    JupiterLendFlashloanAccounts,
    JupiterLendFlashloanAdminState,
    build_flashloan_borrow_instruction,
    build_flashloan_payback_instruction,
    validate_jupiter_lend_order,
)
from src.lending.slumlord import (
    SLUMLORD_PDA,
    SLUMLORD_PROGRAM_ID,
    SlumlordReserveState,
    prepare_rent_loan,
    validate_slumlord_order,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise FinancingContractError(f"{label} must be lowercase sha256")
    return value


def _positive(value: int, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise FinancingContractError(f"{label} must be positive integer")
    return value


def _nonnegative(value: int, label: str) -> int:
    if type(value) is not int or value < 0:
        raise FinancingContractError(f"{label} must be non-negative integer")
    return value


def _sequence_hash(instructions: Sequence[Instruction]) -> str:
    digest = hashlib.sha256()
    for instruction in instructions:
        digest.update(bytes(instruction.program_id))
        digest.update(len(instruction.data).to_bytes(4, "little"))
        digest.update(bytes(instruction.data))
        for account in instruction.accounts:
            digest.update(bytes(account.pubkey))
            digest.update(bytes((int(account.is_signer), int(account.is_writable))))
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class JupiterLendFinancingSnapshot:
    accounts: JupiterLendFlashloanAccounts
    admin_state: JupiterLendFlashloanAdminState
    asset_id: str
    available_liquidity_base_units: int
    required_repayment_base_units: int
    slot: int
    evidence_sha256: str
    state_fingerprint: str
    monitored_accounts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise FinancingContractError("asset_id is required")
        _nonnegative(self.available_liquidity_base_units, "available_liquidity")
        _positive(self.required_repayment_base_units, "required_repayment")
        _nonnegative(self.slot, "slot")
        _sha(self.evidence_sha256, "evidence_sha256")
        _sha(self.state_fingerprint, "state_fingerprint")
        if not self.admin_state.status:
            raise FinancingContractError("JUPITER_LEND_PROTOCOL_PAUSED")
        if self.admin_state.is_flashloan_active:
            raise FinancingContractError("JUPITER_LEND_FLASHLOAN_ALREADY_ACTIVE")
        if self.admin_state.active_flashloan_amount != 0:
            raise FinancingContractError("JUPITER_LEND_ACTIVE_AMOUNT_NOT_ZERO")
        if self.admin_state.flashloan_fee != 0:
            raise FinancingContractError("JUPITER_LEND_NONZERO_FEE_UNQUALIFIED")
        if self.admin_state.liquidity_program != self.accounts.liquidity_program:
            raise FinancingContractError("JUPITER_LEND_LIQUIDITY_PROGRAM_MISMATCH")
        required = (
            str(self.accounts.flashloan_admin),
            str(self.accounts.signer_borrow_token_account),
            str(self.accounts.flashloan_token_reserves_liquidity),
        )
        normalized = tuple(dict.fromkeys((*self.monitored_accounts, *required)))
        object.__setattr__(self, "monitored_accounts", normalized)


    @property
    def required_monitored_accounts(self) -> tuple[str, ...]:
        return (
            str(self.accounts.flashloan_admin),
            str(self.accounts.signer_borrow_token_account),
            str(self.accounts.flashloan_token_reserves_liquidity),
        )


@dataclass(frozen=True, slots=True)
class SlumlordFinancingSnapshot:
    reserve: SlumlordReserveState
    evidence_sha256: str
    state_fingerprint: str

    def __post_init__(self) -> None:
        _sha(self.evidence_sha256, "evidence_sha256")
        _sha(self.state_fingerprint, "state_fingerprint")


    @property
    def required_monitored_accounts(self) -> tuple[str, ...]:
        return (str(SLUMLORD_PDA),)


class JupiterLendFinancingPort:
    """Qualified, unsigned bridge for the pinned Jupiter Lend flashloan ABI."""

    lender_id = "jupiter-lend"
    execution_conformance_verified = True

    def __init__(self, evidence: FinancingEvidence) -> None:
        if evidence.lender_id != self.lender_id:
            raise FinancingContractError("FINANCING_LENDER_MISMATCH")
        if evidence.program_id != str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID):
            raise FinancingContractError("FINANCING_PROGRAM_MISMATCH")
        self.evidence = evidence
        self.deployment_generation = evidence.deployment_generation

    def prepare(
        self,
        *,
        snapshot: object,
        amount: int,
        destination_account: str,
        repayment_source_account: str,
        minimum_terminal_balance: int,
        role: FinancingRole = FinancingRole.PRIMARY,
    ) -> PreparedFinancing:
        if type(snapshot) is not JupiterLendFinancingSnapshot:
            raise FinancingContractError("JUPITER_LEND_SNAPSHOT_REQUIRED")
        if role is not FinancingRole.PRIMARY:
            raise FinancingContractError("JUPITER_LEND_PRIMARY_ROLE_REQUIRED")
        _positive(amount, "amount")
        _nonnegative(minimum_terminal_balance, "minimum_terminal_balance")
        if snapshot.evidence_sha256 != self.evidence.evidence_sha256:
            raise FinancingContractError("FINANCING_EVIDENCE_MISMATCH")
        if amount > snapshot.available_liquidity_base_units:
            raise FinancingContractError("JUPITER_LEND_INSUFFICIENT_LIQUIDITY")
        account = str(snapshot.accounts.signer_borrow_token_account)
        if destination_account != account or repayment_source_account != account:
            raise FinancingContractError("JUPITER_LEND_TOKEN_ACCOUNT_MISMATCH")
        repayment = snapshot.required_repayment_base_units
        if repayment != amount:
            raise FinancingContractError(
                "JUPITER_LEND_DYNAMIC_REPAYMENT_UNSUPPORTED_BY_PINNED_ABI"
            )
        if minimum_terminal_balance < repayment:
            raise FinancingContractError("JUPITER_LEND_REPAYMENT_NOT_COVERED")
        borrow = build_flashloan_borrow_instruction(snapshot.accounts, amount)
        payback = build_flashloan_payback_instruction(snapshot.accounts, repayment)
        constraints = _sequence_hash((borrow, payback))
        obligation = FinancingObligation(
            obligation_id=f"jupiter-lend:{self.deployment_generation}:{constraints[:16]}",
            role=FinancingRole.PRIMARY,
            lender_id=self.lender_id,
            program_id=str(JUPITER_LEND_FLASHLOAN_PROGRAM_ID),
            deployment_generation=self.deployment_generation,
            asset_id=snapshot.asset_id,
            principal_base_units=amount,
            required_repayment_base_units=repayment,
            evidence_sha256=self.evidence.evidence_sha256,
            repayment_destination=str(
                snapshot.accounts.flashloan_token_reserves_liquidity
            ),
            instruction_constraints_sha256=constraints,
        )
        return PreparedFinancing(
            obligation=obligation,
            borrow_instructions=(borrow,),
            repay_instructions=(payback,),
            min_context_slot=snapshot.slot,
            state_fingerprint=snapshot.state_fingerprint,
        )

    def finalize(
        self,
        prepared: PreparedFinancing,
        immutable_sequence: Sequence[Instruction],
    ) -> FinalizedFinancing:
        sequence = tuple(immutable_sequence)
        certificate = validate_jupiter_lend_order(sequence)
        if certificate.amount != prepared.obligation.principal_base_units:
            raise FinancingContractError("JUPITER_LEND_SEQUENCE_AMOUNT_MISMATCH")
        if prepared.borrow_instructions[0] != sequence[certificate.borrow_index]:
            raise FinancingContractError("JUPITER_LEND_BORROW_SEQUENCE_MISMATCH")
        if prepared.repay_instructions[0] != sequence[certificate.payback_index]:
            raise FinancingContractError("JUPITER_LEND_REPAY_SEQUENCE_MISMATCH")
        return FinalizedFinancing(
            obligation=prepared.obligation,
            instructions=sequence,
            sequence_fingerprint=_sequence_hash(sequence),
        )


class SlumlordFinancingPort:
    """Unsigned rent-financing bridge preserving reserve-balance-minus-one semantics."""

    lender_id = "slumlord"
    execution_conformance_verified = True

    def __init__(self, evidence: FinancingEvidence) -> None:
        if evidence.lender_id != self.lender_id:
            raise FinancingContractError("FINANCING_LENDER_MISMATCH")
        if evidence.program_id != str(SLUMLORD_PROGRAM_ID):
            raise FinancingContractError("FINANCING_PROGRAM_MISMATCH")
        self.evidence = evidence
        self.deployment_generation = evidence.deployment_generation

    def prepare(
        self,
        *,
        snapshot: object,
        amount: int,
        destination_account: str,
        repayment_source_account: str,
        minimum_terminal_balance: int,
        role: FinancingRole = FinancingRole.RENT,
    ) -> PreparedFinancing:
        if type(snapshot) is not SlumlordFinancingSnapshot:
            raise FinancingContractError("SLUMLORD_SNAPSHOT_REQUIRED")
        if role is not FinancingRole.RENT:
            raise FinancingContractError("SLUMLORD_RENT_ROLE_REQUIRED")
        if snapshot.evidence_sha256 != self.evidence.evidence_sha256:
            raise FinancingContractError("FINANCING_EVIDENCE_MISMATCH")
        _positive(amount, "amount")
        _nonnegative(minimum_terminal_balance, "minimum_terminal_balance")
        try:
            destination = Pubkey.from_string(destination_account)
            source = Pubkey.from_string(repayment_source_account)
        except Exception as exc:
            raise FinancingContractError("SLUMLORD_ACCOUNT_IDENTITY_INVALID") from exc
        prepared = prepare_rent_loan(
            snapshot.reserve,
            destination=destination,
            repayment_source=source,
            requested_lamports=amount,
        )
        if minimum_terminal_balance < prepared.required_repayment_lamports:
            raise FinancingContractError("SLUMLORD_REPAYMENT_NOT_COVERED")
        instructions = (
            prepared.borrow_instruction,
            prepared.repay_instruction,
            prepared.check_repaid_instruction,
        )
        constraints = _sequence_hash(instructions)
        obligation = FinancingObligation(
            obligation_id=f"slumlord:{self.deployment_generation}:{constraints[:16]}",
            role=FinancingRole.RENT,
            lender_id=self.lender_id,
            program_id=str(SLUMLORD_PROGRAM_ID),
            deployment_generation=self.deployment_generation,
            asset_id="sol:lamports",
            principal_base_units=prepared.borrow_lamports,
            required_repayment_base_units=prepared.required_repayment_lamports,
            evidence_sha256=self.evidence.evidence_sha256,
            repayment_destination=str(SLUMLORD_PDA),
            instruction_constraints_sha256=constraints,
        )
        return PreparedFinancing(
            obligation=obligation,
            borrow_instructions=(prepared.borrow_instruction,),
            repay_instructions=(
                prepared.repay_instruction,
                prepared.check_repaid_instruction,
            ),
            min_context_slot=snapshot.reserve.slot,
            state_fingerprint=snapshot.state_fingerprint,
        )

    def finalize(
        self,
        prepared: PreparedFinancing,
        immutable_sequence: Sequence[Instruction],
    ) -> FinalizedFinancing:
        sequence = tuple(immutable_sequence)
        certificate = validate_slumlord_order(sequence)
        if prepared.borrow_instructions[0] != sequence[certificate.borrow_index]:
            raise FinancingContractError("SLUMLORD_BORROW_SEQUENCE_MISMATCH")
        if prepared.repay_instructions[0] != sequence[certificate.repay_index]:
            raise FinancingContractError("SLUMLORD_REPAY_SEQUENCE_MISMATCH")
        if prepared.repay_instructions[1] != sequence[certificate.check_repaid_index]:
            raise FinancingContractError("SLUMLORD_CHECK_SEQUENCE_MISMATCH")
        return FinalizedFinancing(
            obligation=prepared.obligation,
            instructions=sequence,
            sequence_fingerprint=_sequence_hash(sequence),
        )


__all__ = [
    "JupiterLendFinancingPort",
    "JupiterLendFinancingSnapshot",
    "SlumlordFinancingPort",
    "SlumlordFinancingSnapshot",
]
