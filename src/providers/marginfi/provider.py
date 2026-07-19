from __future__ import annotations
from dataclasses import dataclass
import hashlib, struct
from typing import Sequence
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey
from .accounts import MarginfiSnapshot, BankSnapshot
from .errors import MarginfiRejection, MarginfiRejectionCode
from .pin import MarginfiContractPin
from .risk import MarginfiRiskAccountResolver

SYSVAR_INSTRUCTIONS = "Sysvar1nstructions1111111111111111111111111"

@dataclass(frozen=True, slots=True)
class PreparedMarginfiFlashLoan:
    borrow_instruction: Instruction; repay_instruction: Instruction; end_template: Instruction
    required_repayment: int; destination_token_account: str; repayment_source_token_account: str
    projected_active_balances: tuple[str, ...]; risk_accounts: tuple[str, ...]
    min_context_slot: int; pin_hash: str; state_fingerprint: str
    _fingerprint: str

@dataclass(frozen=True, slots=True)
class FinalizedMarginfiFlashLoanPlan:
    instructions: tuple[Instruction, ...]; start_index: int; end_index: int; required_repayment: int
    destination_token_account: str; repayment_source_token_account: str; projected_active_balances: tuple[str, ...]
    risk_accounts: tuple[str, ...]; min_context_slot: int; pin_hash: str; state_fingerprint: str; sequence_fingerprint: str

class MarginfiFlashLoanProvider:
    """Single canonical provider entry point for MarginFi flash-loan brackets."""
    def __init__(self, pin: MarginfiContractPin): self.pin = pin; self.risk = MarginfiRiskAccountResolver()
    def prepare(self, *, snapshot: MarginfiSnapshot, amount: int, destination_token_account: str, repayment_source_token_account: str, min_final_balance: int, safety_surplus: int = 0) -> PreparedMarginfiFlashLoan:
        if amount <= 0: raise MarginfiRejection(MarginfiRejectionCode.INSUFFICIENT_LIQUIDITY, "borrow amount must be positive")
        required = amount  # Pinned source/SDK fixture proves no additional encoded flash-loan fee in this instruction set.
        if min_final_balance < required + safety_surplus: raise MarginfiRejection(MarginfiRejectionCode.MIN_FINAL_BALANCE, "ExactIn min_final_balance is below repayment plus safety surplus")
        risk_accounts = self.risk.resolve(snapshot.margin_account, {snapshot.bank.address: snapshot.bank})
        borrow = self._borrow_ix(snapshot, amount, destination_token_account)
        repay = self._repay_ix(snapshot, required, repayment_source_token_account)
        end = self._end_ix(snapshot, risk_accounts)
        fp = hashlib.sha256(b"".join(ix.data for ix in (borrow, repay, end))).hexdigest()
        return PreparedMarginfiFlashLoan(borrow, repay, end, required, destination_token_account, repayment_source_token_account, snapshot.margin_account.active_balances, risk_accounts, snapshot.slot, self.pin.pin_hash, snapshot.state_fingerprint, fp)
    def finalize(self, prepared: PreparedMarginfiFlashLoan, immutable_sequence: Sequence[Instruction]) -> FinalizedMarginfiFlashLoanPlan:
        seq = tuple(immutable_sequence)
        if prepared.borrow_instruction not in seq or prepared.repay_instruction not in seq: raise MarginfiRejection(MarginfiRejectionCode.SEQUENCE_MUTATED, "borrow/repay missing from immutable sequence")
        if prepared.end_template in seq: raise MarginfiRejection(MarginfiRejectionCode.SEQUENCE_MUTATED, "end template must be supplied after final index calculation")
        repay_i = seq.index(prepared.repay_instruction); borrow_i = seq.index(prepared.borrow_instruction)
        if borrow_i >= repay_i: raise MarginfiRejection(MarginfiRejectionCode.SEQUENCE_MUTATED, "borrow must precede repay")
        end_index = len(seq) + 1
        start = self._start_ix(seq[borrow_i], end_index)
        final = (*seq[:borrow_i], start, *seq[borrow_i:], prepared.end_template)
        if final[end_index] != prepared.end_template: raise MarginfiRejection(MarginfiRejectionCode.SEQUENCE_MUTATED, "computed end_index mismatch")
        sfp = hashlib.sha256(b"".join(bytes(ix.program_id) + ix.data for ix in final)).hexdigest()
        return FinalizedMarginfiFlashLoanPlan(final, borrow_i, end_index, prepared.required_repayment, prepared.destination_token_account, prepared.repayment_source_token_account, prepared.projected_active_balances, prepared.risk_accounts, prepared.min_context_slot, prepared.pin_hash, prepared.state_fingerprint, sfp)
    def _start_ix(self, borrow_ix: Instruction, end_index: int) -> Instruction:
        # start accounts are marginfi_account and authority; derive from borrow account ordering below.
        return Instruction(Pubkey.from_string(self.pin.program_id), bytes(self.pin.ix_discriminator("lending_account_start_flashloan") + struct.pack("<Q", end_index)), [borrow_ix.accounts[1], borrow_ix.accounts[2]])
    def _borrow_ix(self, s: MarginfiSnapshot, amount: int, dest: str) -> Instruction:
        accts = self._bank_accounts(s.bank, s.margin_account.address, s.margin_account.authority, dest, writable_dest=True)
        return Instruction(Pubkey.from_string(self.pin.program_id), self.pin.ix_discriminator("lending_account_borrow") + struct.pack("<Q", amount), accts)
    def _repay_ix(self, s: MarginfiSnapshot, amount: int, src: str) -> Instruction:
        accts = self._bank_accounts(s.bank, s.margin_account.address, s.margin_account.authority, src, writable_dest=True)
        return Instruction(Pubkey.from_string(self.pin.program_id), self.pin.ix_discriminator("lending_account_repay") + struct.pack("<Q?", amount, False), accts)
    def _end_ix(self, s: MarginfiSnapshot, risk_accounts: tuple[str, ...]) -> Instruction:
        accts = [AccountMeta(Pubkey.from_string(s.margin_account.address), False, True), AccountMeta(Pubkey.from_string(s.margin_account.authority), True, False), AccountMeta(Pubkey.from_string(SYSVAR_INSTRUCTIONS), False, False)]
        accts.extend(AccountMeta(Pubkey.from_string(k), False, k in s.margin_account.active_balances) for k in risk_accounts)
        return Instruction(Pubkey.from_string(self.pin.program_id), self.pin.ix_discriminator("lending_account_end_flashloan"), accts)
    def _bank_accounts(self, b: BankSnapshot, ma: str, auth: str, token_account: str, *, writable_dest: bool) -> list[AccountMeta]:
        return [AccountMeta(Pubkey.from_string(b.group), False, False), AccountMeta(Pubkey.from_string(ma), False, True), AccountMeta(Pubkey.from_string(auth), True, False), AccountMeta(Pubkey.from_string(b.address), False, True), AccountMeta(Pubkey.from_string(token_account), False, writable_dest), AccountMeta(Pubkey.from_string(b.liquidity_vault_authority), False, False), AccountMeta(Pubkey.from_string(b.liquidity_vault), False, True), AccountMeta(Pubkey.from_string(b.token_program), False, False)]
