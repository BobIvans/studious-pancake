"""AGG-03 sender-free Slumlord financing adapter.

This module is a clean Python compatibility port of the public Slumlord
instruction/state contract pinned by AGG-03. It builds unsigned Solders
instructions only; it never signs, submits, fetches network state, or grants
operational admission.

Pinned upstream:
- repository: https://github.com/igneous-labs/slumlord
- commit: 5c5565cb106f5316a66df8ba616034a7810fa850
- slumlord_interface/src/instructions.rs blob:
  9755520565f83dd2ee9f02bcc2651e193e669dcc
- slumlord-lib/src/lib.rs blob:
  03b41179d6e50b745ee9b9e6273753f0b9fb39b1
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

SLUMLORD_UPSTREAM_REPOSITORY = "https://github.com/igneous-labs/slumlord"
SLUMLORD_UPSTREAM_COMMIT = "5c5565cb106f5316a66df8ba616034a7810fa850"
SLUMLORD_INSTRUCTIONS_BLOB = "9755520565f83dd2ee9f02bcc2651e193e669dcc"
SLUMLORD_LIBRARY_BLOB = "03b41179d6e50b745ee9b9e6273753f0b9fb39b1"

SLUMLORD_PROGRAM_ID = Pubkey.from_string(
    "s1umBj7CEUA6djs6V1c6o2Nym3QrqF4ryKDr1Nm1FKt"
)
SLUMLORD_SEED = b"slumlord"
SLUMLORD_PDA, SLUMLORD_BUMP = Pubkey.find_program_address(
    [SLUMLORD_SEED], SLUMLORD_PROGRAM_ID
)
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
INSTRUCTIONS_SYSVAR_ID = Pubkey.from_string(
    "Sysvar1nstructions1111111111111111111111111"
)

SLUMLORD_ACCOUNT_LEN = 8
BORROW_DISCRIMINATOR = 1
REPAY_DISCRIMINATOR = 2
CHECK_REPAID_DISCRIMINATOR = 3
_U64_MAX = (1 << 64) - 1


class SlumlordRejectionCode(StrEnum):
    INVALID_STATE = "AGG03_SLUM_INVALID_STATE"
    WRONG_IDENTITY = "AGG03_SLUM_WRONG_IDENTITY"
    BORROW_ALREADY_ACTIVE = "AGG03_SLUM_BORROW_ALREADY_ACTIVE"
    INSUFFICIENT_RESERVE = "AGG03_SLUM_INSUFFICIENT_RESERVE"
    BORROW_AMOUNT_MISMATCH = "AGG03_SLUM_BORROW_AMOUNT_MISMATCH"
    ORDER_INVARIANT = "AGG03_SLUM_ORDER_INVARIANT"


class SlumlordAdapterError(ValueError):
    """Typed source-level Slumlord rejection."""

    def __init__(self, code: SlumlordRejectionCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class SlumlordReserveState:
    """Strict public-account observation used by the unsigned adapter.

    Empty data means no active Slumlord loan. Active state is exactly the
    upstream repr(C) Slumlord structure containing old_lamports as u64.
    """

    address: Pubkey
    owner: Pubkey
    lamports: int
    data: bytes
    slot: int

    def __post_init__(self) -> None:
        if type(self.lamports) is not int or not 0 <= self.lamports <= _U64_MAX:
            raise SlumlordAdapterError(
                SlumlordRejectionCode.INVALID_STATE, "lamports must be u64"
            )
        if type(self.slot) is not int or self.slot < 0:
            raise SlumlordAdapterError(
                SlumlordRejectionCode.INVALID_STATE, "slot must be non-negative"
            )
        if self.address != SLUMLORD_PDA or self.owner != SLUMLORD_PROGRAM_ID:
            raise SlumlordAdapterError(
                SlumlordRejectionCode.WRONG_IDENTITY,
                "Slumlord PDA or owner does not match pinned source",
            )
        if len(self.data) not in {0, SLUMLORD_ACCOUNT_LEN}:
            raise SlumlordAdapterError(
                SlumlordRejectionCode.INVALID_STATE,
                "Slumlord account data must be empty or exactly 8 bytes",
            )

    @property
    def loan_active(self) -> bool:
        return bool(self.data)

    @property
    def old_lamports(self) -> int | None:
        if not self.data:
            return None
        return int.from_bytes(self.data, "little", signed=False)

    @property
    def outstanding_lamports(self) -> int:
        old = self.old_lamports
        if old is None:
            return 0
        return max(old - self.lamports, 0)

    @property
    def available_borrow_lamports(self) -> int:
        if self.loan_active or self.lamports <= 1:
            return 0
        return self.lamports - 1


@dataclass(frozen=True, slots=True)
class SlumlordPreparedRentLoan:
    reserve: SlumlordReserveState
    destination: Pubkey
    repayment_source: Pubkey
    borrow_lamports: int
    required_repayment_lamports: int
    borrow_instruction: Instruction
    repay_instruction: Instruction
    check_repaid_instruction: Instruction


@dataclass(frozen=True, slots=True)
class SlumlordOrderCertificate:
    borrow_index: int
    repay_index: int
    check_repaid_index: int


def build_borrow_instruction(destination: Pubkey) -> Instruction:
    """Build the exact upstream Borrow instruction; it has no amount argument."""

    return Instruction(
        SLUMLORD_PROGRAM_ID,
        bytes((BORROW_DISCRIMINATOR,)),
        [
            AccountMeta(SLUMLORD_PDA, False, True),
            AccountMeta(destination, False, True),
            AccountMeta(INSTRUCTIONS_SYSVAR_ID, False, False),
        ],
    )


def build_repay_instruction(source: Pubkey) -> Instruction:
    return Instruction(
        SLUMLORD_PROGRAM_ID,
        bytes((REPAY_DISCRIMINATOR,)),
        [
            AccountMeta(SLUMLORD_PDA, False, True),
            AccountMeta(source, True, True),
            AccountMeta(SYSTEM_PROGRAM_ID, False, False),
        ],
    )


def build_check_repaid_instruction() -> Instruction:
    return Instruction(
        SLUMLORD_PROGRAM_ID,
        bytes((CHECK_REPAID_DISCRIMINATOR,)),
        [AccountMeta(SLUMLORD_PDA, False, True)],
    )


def prepare_rent_loan(
    reserve: SlumlordReserveState,
    *,
    destination: Pubkey,
    repayment_source: Pubkey,
    requested_lamports: int | None = None,
) -> SlumlordPreparedRentLoan:
    """Prepare the source-level Slumlord borrow/repay/check contract.

    requested_lamports is only a planner assertion. It never changes the
    on-chain Borrow instruction, whose amount is reserve_balance - 1.
    """

    if reserve.loan_active:
        raise SlumlordAdapterError(
            SlumlordRejectionCode.BORROW_ALREADY_ACTIVE,
            "Slumlord account already contains an active loan",
        )
    amount = reserve.available_borrow_lamports
    if amount <= 0:
        raise SlumlordAdapterError(
            SlumlordRejectionCode.INSUFFICIENT_RESERVE,
            "Slumlord reserve cannot lend a positive amount",
        )
    if requested_lamports is not None and requested_lamports != amount:
        raise SlumlordAdapterError(
            SlumlordRejectionCode.BORROW_AMOUNT_MISMATCH,
            "requested amount cannot alter Slumlord reserve_balance - 1 semantics",
        )
    return SlumlordPreparedRentLoan(
        reserve=reserve,
        destination=destination,
        repayment_source=repayment_source,
        borrow_lamports=amount,
        required_repayment_lamports=amount,
        borrow_instruction=build_borrow_instruction(destination),
        repay_instruction=build_repay_instruction(repayment_source),
        check_repaid_instruction=build_check_repaid_instruction(),
    )


def validate_slumlord_order(
    instructions: Sequence[Instruction],
) -> SlumlordOrderCertificate:
    """Require one Borrow -> Repay -> later top-level CheckRepaid sequence."""

    borrow: list[int] = []
    repay: list[int] = []
    check: list[int] = []
    for index, instruction in enumerate(instructions):
        if instruction.program_id != SLUMLORD_PROGRAM_ID:
            continue
        data = bytes(instruction.data)
        if data == bytes((BORROW_DISCRIMINATOR,)):
            borrow.append(index)
        elif data == bytes((REPAY_DISCRIMINATOR,)):
            repay.append(index)
        elif data == bytes((CHECK_REPAID_DISCRIMINATOR,)):
            check.append(index)

    if len(borrow) != 1 or len(repay) != 1 or len(check) != 1:
        raise SlumlordAdapterError(
            SlumlordRejectionCode.ORDER_INVARIANT,
            "exactly one Borrow, Repay and CheckRepaid are required",
        )
    if not borrow[0] < repay[0] < check[0]:
        raise SlumlordAdapterError(
            SlumlordRejectionCode.ORDER_INVARIANT,
            "Slumlord order must be Borrow -> Repay -> succeeding CheckRepaid",
        )
    return SlumlordOrderCertificate(borrow[0], repay[0], check[0])


__all__ = [
    "BORROW_DISCRIMINATOR",
    "CHECK_REPAID_DISCRIMINATOR",
    "INSTRUCTIONS_SYSVAR_ID",
    "REPAY_DISCRIMINATOR",
    "SLUMLORD_ACCOUNT_LEN",
    "SLUMLORD_BUMP",
    "SLUMLORD_INSTRUCTIONS_BLOB",
    "SLUMLORD_LIBRARY_BLOB",
    "SLUMLORD_PDA",
    "SLUMLORD_PROGRAM_ID",
    "SLUMLORD_SEED",
    "SLUMLORD_UPSTREAM_COMMIT",
    "SLUMLORD_UPSTREAM_REPOSITORY",
    "SYSTEM_PROGRAM_ID",
    "SlumlordAdapterError",
    "SlumlordOrderCertificate",
    "SlumlordPreparedRentLoan",
    "SlumlordRejectionCode",
    "SlumlordReserveState",
    "build_borrow_instruction",
    "build_check_repaid_instruction",
    "build_repay_instruction",
    "prepare_rent_loan",
    "validate_slumlord_order",
]
