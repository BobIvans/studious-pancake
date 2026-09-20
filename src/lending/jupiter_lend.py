"""AGG-03 low-level Jupiter Lend flashloan instruction contract.

This module intentionally avoids an unverified npm/runtime dependency. It
implements unsigned instruction encoding from the official public Jupiter Lend
IDL pinned below. Account discovery, deployed-state admission, fee-state
qualification, signing and submission are separate responsibilities and are not
claimed here.

Pinned upstream:
- repository: https://github.com/jup-ag/jupiter-lend
- commit: 33a22cf7a5bfdd32ab1712dda4adfbeb9b348ad9
- target/idl/flashloan.json git blob:
  0d0ae6d624b33355315e98baaf0a5d00d317beb8
- IDL version: 0.1.4
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

JUPITER_LEND_UPSTREAM_REPOSITORY = "https://github.com/jup-ag/jupiter-lend"
JUPITER_LEND_UPSTREAM_COMMIT = "33a22cf7a5bfdd32ab1712dda4adfbeb9b348ad9"
JUPITER_LEND_FLASHLOAN_IDL_BLOB = "0d0ae6d624b33355315e98baaf0a5d00d317beb8"
JUPITER_LEND_FLASHLOAN_IDL_VERSION = "0.1.4"

JUPITER_LEND_FLASHLOAN_PROGRAM_ID = Pubkey.from_string(
    "jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS"
)
JUPITER_FLASHLOAN_ADMIN_SEED = b"flashloan_admin"
JUPITER_FLASHLOAN_ADMIN_PDA, JUPITER_FLASHLOAN_ADMIN_BUMP = (
    Pubkey.find_program_address(
        [JUPITER_FLASHLOAN_ADMIN_SEED],
        JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
    )
)
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string(
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
)
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
INSTRUCTIONS_SYSVAR_ID = Pubkey.from_string(
    "Sysvar1nstructions1111111111111111111111111"
)

FLASHLOAN_BORROW_DISCRIMINATOR = bytes((103, 19, 78, 24, 240, 9, 135, 63))
FLASHLOAN_PAYBACK_DISCRIMINATOR = bytes((213, 47, 153, 137, 84, 243, 94, 232))
_U64_MAX = (1 << 64) - 1
_EXPECTED_META_FLAGS = (
    (True, True),
    (False, True),
    (False, True),
    (False, False),
    (False, True),
    (False, True),
    (False, False),
    (False, True),
    (False, False),
    (False, False),
    (False, False),
    (False, False),
    (False, False),
    (False, False),
)


class JupiterLendRejectionCode(StrEnum):
    INVALID_AMOUNT = "AGG03_JUP_LEND_INVALID_AMOUNT"
    INVALID_FIXED_ACCOUNT = "AGG03_JUP_LEND_INVALID_FIXED_ACCOUNT"
    ORDER_INVARIANT = "AGG03_JUP_LEND_ORDER_INVARIANT"
    AMOUNT_MISMATCH = "AGG03_JUP_LEND_AMOUNT_MISMATCH"
    ACCOUNT_MISMATCH = "AGG03_JUP_LEND_ACCOUNT_MISMATCH"


class JupiterLendAdapterError(ValueError):
    def __init__(self, code: JupiterLendRejectionCode, message: str) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class JupiterLendFlashloanAccounts:
    """Ordered account contract from the pinned flashloan IDL."""

    signer: Pubkey
    flashloan_admin: Pubkey
    signer_borrow_token_account: Pubkey
    mint: Pubkey
    flashloan_token_reserves_liquidity: Pubkey
    flashloan_borrow_position_on_liquidity: Pubkey
    rate_model: Pubkey
    vault: Pubkey
    liquidity: Pubkey
    liquidity_program: Pubkey
    token_program: Pubkey
    associated_token_program: Pubkey = ASSOCIATED_TOKEN_PROGRAM_ID
    system_program: Pubkey = SYSTEM_PROGRAM_ID
    instruction_sysvar: Pubkey = INSTRUCTIONS_SYSVAR_ID

    def __post_init__(self) -> None:
        if self.flashloan_admin != JUPITER_FLASHLOAN_ADMIN_PDA:
            raise JupiterLendAdapterError(
                JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
                "flashloan_admin does not match the pinned PDA seed/program",
            )
        expected = (
            (
                self.associated_token_program,
                ASSOCIATED_TOKEN_PROGRAM_ID,
                "ATA program",
            ),
            (self.system_program, SYSTEM_PROGRAM_ID, "system program"),
            (
                self.instruction_sysvar,
                INSTRUCTIONS_SYSVAR_ID,
                "instructions sysvar",
            ),
        )
        for actual, required, label in expected:
            if actual != required:
                raise JupiterLendAdapterError(
                    JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
                    f"{label} differs from pinned IDL",
                )

    def metas(self) -> list[AccountMeta]:
        return [
            AccountMeta(self.signer, True, True),
            AccountMeta(self.flashloan_admin, False, True),
            AccountMeta(self.signer_borrow_token_account, False, True),
            AccountMeta(self.mint, False, False),
            AccountMeta(self.flashloan_token_reserves_liquidity, False, True),
            AccountMeta(self.flashloan_borrow_position_on_liquidity, False, True),
            AccountMeta(self.rate_model, False, False),
            AccountMeta(self.vault, False, True),
            AccountMeta(self.liquidity, False, False),
            AccountMeta(self.liquidity_program, False, False),
            AccountMeta(self.token_program, False, False),
            AccountMeta(self.associated_token_program, False, False),
            AccountMeta(self.system_program, False, False),
            AccountMeta(self.instruction_sysvar, False, False),
        ]


@dataclass(frozen=True, slots=True)
class JupiterLendOrderCertificate:
    borrow_index: int
    payback_index: int
    amount: int


def _encode_amount(amount: int) -> bytes:
    if type(amount) is not int or not 0 < amount <= _U64_MAX:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.INVALID_AMOUNT,
            "flashloan amount must be a positive u64",
        )
    return amount.to_bytes(8, "little", signed=False)


def build_flashloan_borrow_instruction(
    accounts: JupiterLendFlashloanAccounts,
    amount: int,
) -> Instruction:
    return Instruction(
        JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
        FLASHLOAN_BORROW_DISCRIMINATOR + _encode_amount(amount),
        accounts.metas(),
    )


def build_flashloan_payback_instruction(
    accounts: JupiterLendFlashloanAccounts,
    amount: int,
) -> Instruction:
    return Instruction(
        JUPITER_LEND_FLASHLOAN_PROGRAM_ID,
        FLASHLOAN_PAYBACK_DISCRIMINATOR + _encode_amount(amount),
        accounts.metas(),
    )


def _decode_amount(instruction: Instruction, discriminator: bytes) -> int:
    data = bytes(instruction.data)
    if len(data) != 16 or not data.startswith(discriminator):
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.ORDER_INVARIANT,
            "instruction data does not match pinned Jupiter Lend flashloan ABI",
        )
    amount = int.from_bytes(data[8:], "little", signed=False)
    if amount <= 0:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.INVALID_AMOUNT,
            "decoded flashloan amount must be positive",
        )
    return amount


def _account_fingerprint(
    instruction: Instruction,
) -> tuple[tuple[Pubkey, bool, bool], ...]:
    return tuple(
        (meta.pubkey, meta.is_signer, meta.is_writable)
        for meta in instruction.accounts
    )


def _validate_account_shape(instruction: Instruction) -> None:
    accounts = tuple(instruction.accounts)
    if len(accounts) != len(_EXPECTED_META_FLAGS):
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.ACCOUNT_MISMATCH,
            "flashloan instruction must contain exactly 14 ordered account metas",
        )

    actual_flags = tuple(
        (meta.is_signer, meta.is_writable) for meta in accounts
    )
    if actual_flags != _EXPECTED_META_FLAGS:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.ACCOUNT_MISMATCH,
            "flashloan account signer/writable flags differ from pinned IDL",
        )

    fixed = (
        (1, JUPITER_FLASHLOAN_ADMIN_PDA, "flashloan_admin"),
        (11, ASSOCIATED_TOKEN_PROGRAM_ID, "associated_token_program"),
        (12, SYSTEM_PROGRAM_ID, "system_program"),
        (13, INSTRUCTIONS_SYSVAR_ID, "instruction_sysvar"),
    )
    for index, expected, label in fixed:
        if accounts[index].pubkey != expected:
            raise JupiterLendAdapterError(
                JupiterLendRejectionCode.INVALID_FIXED_ACCOUNT,
                f"{label} differs from pinned IDL",
            )


def validate_jupiter_lend_order(
    instructions: Sequence[Instruction],
) -> JupiterLendOrderCertificate:
    """Require one ABI-valid, account-bound Borrow before matching Payback."""

    borrow: list[tuple[int, int, tuple[tuple[Pubkey, bool, bool], ...]]] = []
    payback: list[tuple[int, int, tuple[tuple[Pubkey, bool, bool], ...]]] = []
    for index, instruction in enumerate(instructions):
        if instruction.program_id != JUPITER_LEND_FLASHLOAN_PROGRAM_ID:
            continue
        data = bytes(instruction.data)
        if data.startswith(FLASHLOAN_BORROW_DISCRIMINATOR):
            _validate_account_shape(instruction)
            borrow.append(
                (
                    index,
                    _decode_amount(
                        instruction,
                        FLASHLOAN_BORROW_DISCRIMINATOR,
                    ),
                    _account_fingerprint(instruction),
                )
            )
        elif data.startswith(FLASHLOAN_PAYBACK_DISCRIMINATOR):
            _validate_account_shape(instruction)
            payback.append(
                (
                    index,
                    _decode_amount(
                        instruction,
                        FLASHLOAN_PAYBACK_DISCRIMINATOR,
                    ),
                    _account_fingerprint(instruction),
                )
            )

    if len(borrow) != 1 or len(payback) != 1:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.ORDER_INVARIANT,
            "exactly one Jupiter Lend Borrow and Payback are required",
        )
    if borrow[0][0] >= payback[0][0]:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.ORDER_INVARIANT,
            "Jupiter Lend Payback must succeed Borrow",
        )
    if borrow[0][1] != payback[0][1]:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.AMOUNT_MISMATCH,
            "Borrow and Payback amount arguments differ",
        )
    if borrow[0][2] != payback[0][2]:
        raise JupiterLendAdapterError(
            JupiterLendRejectionCode.ACCOUNT_MISMATCH,
            "Borrow and Payback must bind the same ordered account metas",
        )
    return JupiterLendOrderCertificate(
        borrow_index=borrow[0][0],
        payback_index=payback[0][0],
        amount=borrow[0][1],
    )


__all__ = [
    "ASSOCIATED_TOKEN_PROGRAM_ID",
    "FLASHLOAN_BORROW_DISCRIMINATOR",
    "FLASHLOAN_PAYBACK_DISCRIMINATOR",
    "INSTRUCTIONS_SYSVAR_ID",
    "JUPITER_FLASHLOAN_ADMIN_BUMP",
    "JUPITER_FLASHLOAN_ADMIN_PDA",
    "JUPITER_FLASHLOAN_ADMIN_SEED",
    "JUPITER_LEND_FLASHLOAN_IDL_BLOB",
    "JUPITER_LEND_FLASHLOAN_IDL_VERSION",
    "JUPITER_LEND_FLASHLOAN_PROGRAM_ID",
    "JUPITER_LEND_UPSTREAM_COMMIT",
    "JUPITER_LEND_UPSTREAM_REPOSITORY",
    "SYSTEM_PROGRAM_ID",
    "JupiterLendAdapterError",
    "JupiterLendFlashloanAccounts",
    "JupiterLendOrderCertificate",
    "JupiterLendRejectionCode",
    "build_flashloan_borrow_instruction",
    "build_flashloan_payback_instruction",
    "validate_jupiter_lend_order",
]
