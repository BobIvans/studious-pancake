"""Canonical shadow-only MarginFi flash-loan instruction builder."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import struct
from typing import Sequence

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from .accounts import BankSnapshot, MarginfiSnapshot
from .errors import MarginfiRejection, MarginfiRejectionCode
from .layouts import ceil_i80f48_product
from .pin import MarginfiContractPin
from .risk import MarginfiRiskAccountResolver


@dataclass(frozen=True, slots=True)
class PreparedMarginfiFlashLoan:
    # Preserve the pre-PR-028 field order; append fee evidence.
    borrow_instruction: Instruction
    repay_instruction: Instruction
    end_template: Instruction
    required_repayment: int
    destination_token_account: str
    repayment_source_token_account: str
    projected_active_balances: tuple[str, ...]
    risk_accounts: tuple[str, ...]
    min_context_slot: int
    pin_hash: str
    state_fingerprint: str
    _fingerprint: str
    borrow_amount: int = 0
    origination_fee: int = 0


@dataclass(frozen=True, slots=True)
class FinalizedMarginfiFlashLoanPlan:
    # Preserve the pre-PR-028 field order; append fee evidence.
    instructions: tuple[Instruction, ...]
    start_index: int
    end_index: int
    required_repayment: int
    destination_token_account: str
    repayment_source_token_account: str
    projected_active_balances: tuple[str, ...]
    risk_accounts: tuple[str, ...]
    min_context_slot: int
    pin_hash: str
    state_fingerprint: str
    sequence_fingerprint: str
    borrow_amount: int = 0
    origination_fee: int = 0


class MarginfiFlashLoanProvider:
    """Build a pinned MarginFi bracket without signing or submitting it."""

    def __init__(self, pin: MarginfiContractPin):
        self.pin = pin
        self.risk = MarginfiRiskAccountResolver()

    def prepare(
        self,
        *,
        snapshot: MarginfiSnapshot,
        amount: int,
        destination_token_account: str,
        repayment_source_token_account: str,
        min_final_balance: int,
        safety_surplus: int = 0,
    ) -> PreparedMarginfiFlashLoan:
        if amount <= 0:
            raise MarginfiRejection(
                MarginfiRejectionCode.INSUFFICIENT_LIQUIDITY,
                "borrow amount must be positive",
            )
        if safety_surplus < 0 or min_final_balance < 0:
            raise MarginfiRejection(
                MarginfiRejectionCode.MIN_FINAL_BALANCE,
                "balance and surplus inputs must be non-negative integers",
            )
        if snapshot.margin_account.target_bank_was_active:
            raise MarginfiRejection(
                MarginfiRejectionCode.EXISTING_POSITION,
                "flash-loan target bank already has an active balance; repay_all would alter it",
            )
        if snapshot.bank.available_liquidity is None:
            raise MarginfiRejection(
                MarginfiRejectionCode.INSUFFICIENT_LIQUIDITY,
                "target bank liquidity was not observed",
            )
        if snapshot.bank.available_liquidity < amount:
            raise MarginfiRejection(
                MarginfiRejectionCode.INSUFFICIENT_LIQUIDITY,
                "target bank liquidity cannot satisfy the borrow",
            )

        fee = ceil_i80f48_product(
            amount,
            snapshot.bank.origination_fee_raw_i80f48,
            fractional_bits=int(
                self.pin.raw["constants"]["i80f48_fractional_bits"]
            ),
        )
        required = amount + fee
        if min_final_balance < required + safety_surplus:
            raise MarginfiRejection(
                MarginfiRejectionCode.MIN_FINAL_BALANCE,
                "ExactIn min_final_balance is below conservative repayment plus safety surplus",
            )

        bank_map = {item.address: item for item in snapshot.banks}
        risk_accounts = self.risk.resolve(snapshot.margin_account, bank_map)
        borrow = self._borrow_ix(
            snapshot,
            amount,
            destination_token_account,
            risk_accounts,
        )
        repay = self._repay_ix(
            snapshot,
            required,
            repayment_source_token_account,
        )
        end = self._end_ix(snapshot, risk_accounts)
        fingerprint = hashlib.sha256(
            b"".join(
                bytes(ix.program_id)
                + b"".join(bytes(meta.pubkey) for meta in ix.accounts)
                + bytes(ix.data)
                for ix in (borrow, repay, end)
            )
        ).hexdigest()
        return PreparedMarginfiFlashLoan(
            borrow_instruction=borrow,
            repay_instruction=repay,
            end_template=end,
            required_repayment=required,
            destination_token_account=destination_token_account,
            repayment_source_token_account=repayment_source_token_account,
            projected_active_balances=snapshot.margin_account.active_balances,
            risk_accounts=risk_accounts,
            min_context_slot=snapshot.slot,
            pin_hash=self.pin.pin_hash,
            state_fingerprint=snapshot.state_fingerprint,
            _fingerprint=fingerprint,
            borrow_amount=amount,
            origination_fee=fee,
        )

    def finalize(
        self,
        prepared: PreparedMarginfiFlashLoan,
        immutable_sequence: Sequence[Instruction],
    ) -> FinalizedMarginfiFlashLoanPlan:
        sequence = tuple(immutable_sequence)
        if (
            prepared.borrow_instruction not in sequence
            or prepared.repay_instruction not in sequence
        ):
            raise MarginfiRejection(
                MarginfiRejectionCode.SEQUENCE_MUTATED,
                "borrow/repay missing from immutable sequence",
            )
        if prepared.end_template in sequence:
            raise MarginfiRejection(
                MarginfiRejectionCode.SEQUENCE_MUTATED,
                "end template must be appended only after final index calculation",
            )
        borrow_index = sequence.index(prepared.borrow_instruction)
        repay_index = sequence.index(prepared.repay_instruction)
        if borrow_index >= repay_index:
            raise MarginfiRejection(
                MarginfiRejectionCode.SEQUENCE_MUTATED,
                "borrow must precede repay",
            )

        end_index = len(sequence) + 1
        start = self._start_ix(prepared.borrow_instruction, end_index)
        final = (
            *sequence[:borrow_index],
            start,
            *sequence[borrow_index:],
            prepared.end_template,
        )
        if final[end_index] != prepared.end_template:
            raise MarginfiRejection(
                MarginfiRejectionCode.SEQUENCE_MUTATED,
                "computed end_index does not point to end_flashloan",
            )
        if final[borrow_index] != start:
            raise MarginfiRejection(
                MarginfiRejectionCode.SEQUENCE_MUTATED,
                "computed start_index does not point to start_flashloan",
            )
        sequence_fingerprint = hashlib.sha256(
            b"".join(
                bytes(ix.program_id)
                + b"".join(
                    bytes(meta.pubkey)
                    + bytes((meta.is_signer, meta.is_writable))
                    for meta in ix.accounts
                )
                + bytes(ix.data)
                for ix in final
            )
        ).hexdigest()
        return FinalizedMarginfiFlashLoanPlan(
            instructions=final,
            start_index=borrow_index,
            end_index=end_index,
            required_repayment=prepared.required_repayment,
            destination_token_account=prepared.destination_token_account,
            repayment_source_token_account=prepared.repayment_source_token_account,
            projected_active_balances=prepared.projected_active_balances,
            risk_accounts=prepared.risk_accounts,
            min_context_slot=prepared.min_context_slot,
            pin_hash=prepared.pin_hash,
            state_fingerprint=prepared.state_fingerprint,
            sequence_fingerprint=sequence_fingerprint,
            borrow_amount=prepared.borrow_amount,
            origination_fee=prepared.origination_fee,
        )

    def _start_ix(self, borrow_ix: Instruction, end_index: int) -> Instruction:
        if len(borrow_ix.accounts) < 3:
            raise MarginfiRejection(
                MarginfiRejectionCode.SEQUENCE_MUTATED,
                "borrow instruction does not expose canonical margin-account accounts",
            )
        sysvar = str(self.pin.raw["programs"]["instructions_sysvar"])
        accounts = [
            AccountMeta(borrow_ix.accounts[1].pubkey, False, True),
            AccountMeta(borrow_ix.accounts[2].pubkey, True, False),
            AccountMeta(Pubkey.from_string(sysvar), False, False),
        ]
        return Instruction(
            Pubkey.from_string(self.pin.program_id),
            self.pin.ix_discriminator("lending_account_start_flashloan")
            + struct.pack("<Q", end_index),
            accounts,
        )

    def _borrow_ix(
        self,
        snapshot: MarginfiSnapshot,
        amount: int,
        destination: str,
        risk_accounts: tuple[str, ...],
    ) -> Instruction:
        bank = snapshot.bank
        accounts = self._borrow_accounts(
            bank,
            snapshot.margin_account.address,
            snapshot.margin_account.authority,
            destination,
        )
        if bank.requires_mint_account:
            accounts.append(AccountMeta(Pubkey.from_string(bank.mint), False, False))
        accounts.extend(
            AccountMeta(Pubkey.from_string(key), False, False)
            for key in risk_accounts
        )
        return Instruction(
            Pubkey.from_string(self.pin.program_id),
            self.pin.ix_discriminator("lending_account_borrow")
            + struct.pack("<Q", amount),
            accounts,
        )

    def _repay_ix(
        self,
        snapshot: MarginfiSnapshot,
        amount: int,
        source: str,
    ) -> Instruction:
        bank = snapshot.bank
        accounts = self._repay_accounts(
            bank,
            snapshot.margin_account.address,
            snapshot.margin_account.authority,
            source,
        )
        if bank.requires_mint_account:
            accounts.append(AccountMeta(Pubkey.from_string(bank.mint), False, False))
        # Upstream takes Option<bool>; Borsh Some(true) is tag=1, value=1.
        data = (
            self.pin.ix_discriminator("lending_account_repay")
            + struct.pack("<QBB", amount, 1, 1)
        )
        return Instruction(Pubkey.from_string(self.pin.program_id), data, accounts)

    def _end_ix(
        self,
        snapshot: MarginfiSnapshot,
        risk_accounts: tuple[str, ...],
    ) -> Instruction:
        accounts = [
            AccountMeta(
                Pubkey.from_string(snapshot.margin_account.address),
                False,
                True,
            ),
            AccountMeta(
                Pubkey.from_string(snapshot.margin_account.authority),
                True,
                False,
            ),
        ]
        accounts.extend(
            AccountMeta(Pubkey.from_string(key), False, False)
            for key in risk_accounts
        )
        return Instruction(
            Pubkey.from_string(self.pin.program_id),
            self.pin.ix_discriminator("lending_account_end_flashloan"),
            accounts,
        )

    @staticmethod
    def _borrow_accounts(
        bank: BankSnapshot,
        margin_account: str,
        authority: str,
        token_account: str,
    ) -> list[AccountMeta]:
        return [
            AccountMeta(Pubkey.from_string(bank.group), False, False),
            AccountMeta(Pubkey.from_string(margin_account), False, True),
            AccountMeta(Pubkey.from_string(authority), True, False),
            AccountMeta(Pubkey.from_string(bank.address), False, True),
            AccountMeta(Pubkey.from_string(token_account), False, True),
            AccountMeta(
                Pubkey.from_string(bank.liquidity_vault_authority),
                False,
                False,
            ),
            AccountMeta(Pubkey.from_string(bank.liquidity_vault), False, True),
            AccountMeta(Pubkey.from_string(bank.token_program), False, False),
        ]

    @staticmethod
    def _repay_accounts(
        bank: BankSnapshot,
        margin_account: str,
        authority: str,
        token_account: str,
    ) -> list[AccountMeta]:
        return [
            AccountMeta(Pubkey.from_string(bank.group), False, False),
            AccountMeta(Pubkey.from_string(margin_account), False, True),
            AccountMeta(Pubkey.from_string(authority), True, False),
            AccountMeta(Pubkey.from_string(bank.address), False, True),
            AccountMeta(Pubkey.from_string(token_account), False, True),
            AccountMeta(Pubkey.from_string(bank.liquidity_vault), False, True),
            AccountMeta(Pubkey.from_string(bank.token_program), False, False),
        ]
