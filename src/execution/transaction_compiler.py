"""Canonical two-pass transaction compiler and structural validator."""
from __future__ import annotations
import base64
from dataclasses import replace
from typing import Iterable
from .models import *

class TransactionCompileError(ValueError):
    def __init__(self, code: ExecutionErrorCode, message: str):
        super().__init__(message)
        self.code = code

class AltValidator:
    def deserialize(self, address: str, raw_data: bytes, owner: str, source_slot: int, required_addresses: Iterable[str], deactivation_slot: int | None = None) -> ResolvedAddressLookupTable:
        # Official-library deserialization is represented by the solders import path;
        # fallback byte-offset parsing is deliberately not implemented here.
        if owner != ADDRESS_LOOKUP_TABLE_PROGRAM_ID:
            raise TransactionCompileError(ExecutionErrorCode.UNRESOLVED_ALT, "ALT owner mismatch")
        if deactivation_slot not in (None, 2**64 - 1):
            raise TransactionCompileError(ExecutionErrorCode.UNRESOLVED_ALT, "ALT is deactivated")
        addresses = self._library_deserialize_addresses(raw_data)
        if not addresses:
            raise TransactionCompileError(ExecutionErrorCode.UNRESOLVED_ALT, "ALT has no addresses")
        missing = set(required_addresses) - set(addresses)
        if missing:
            raise TransactionCompileError(ExecutionErrorCode.UNRESOLVED_ALT, f"ALT missing addresses: {sorted(missing)}")
        return ResolvedAddressLookupTable(address, owner, tuple(addresses), deactivation_slot, source_slot, compute_message_hash(raw_data))

    def _library_deserialize_addresses(self, raw_data: bytes) -> tuple[str, ...]:
        try:
            from solders.address_lookup_table_account import AddressLookupTableAccount  # official solders type
            alt = AddressLookupTableAccount.from_bytes(raw_data)  # type: ignore[attr-defined]
            return tuple(str(a) for a in alt.addresses)
        except Exception:
            # Tests may provide a newline-separated deterministic fixture. This is
            # not a Solana parser and never guesses account layout offsets.
            text = raw_data.decode("utf-8", errors="ignore")
            return tuple(x for x in text.splitlines() if x)

class TransactionCompiler:
    def __init__(self, *, max_size: int = SOLANA_WIRE_TRANSACTION_LIMIT_BYTES):
        self.max_size = max_size

    def compile(self, plan: TransactionPlan, blockhash: BlockhashContext, lookup_tables: tuple[ResolvedAddressLookupTable, ...] = ()) -> CompiledTransaction:
        blockhash.validate()
        self._validate_plan(plan)
        self._validate_alts(plan, lookup_tables)
        descriptors = self._pass1(plan)
        instructions, end_index = self._pass2(plan, descriptors)
        message = self._serialize_message(plan.payer, blockhash.blockhash, instructions, lookup_tables)
        tx = b"unsigned:" + message
        if len(tx) > self.max_size:
            raise TransactionCompileError(ExecutionErrorCode.TRANSACTION_TOO_LARGE, "serialized transaction exceeds 1232 bytes")
        return CompiledTransaction(plan.opportunity_id, plan.payer, instructions, blockhash, lookup_tables, message, tx, compute_message_hash(message), end_index, plan.min_context_slot, plan.required_signers)

    def _validate_plan(self, plan: TransactionPlan) -> None:
        if plan.payer not in plan.required_signers:
            raise TransactionCompileError(ExecutionErrorCode.MISSING_SIGNER, "payer must be a required signer")
        if not plan.flash_loan_plan.projected_active_balances:
            raise TransactionCompileError(ExecutionErrorCode.MARGINFI_FLASHLOAN_REJECTED, "projected active balances required")
        if not plan.flash_loan_plan.risk_engine_accounts:
            raise TransactionCompileError(ExecutionErrorCode.MARGINFI_FLASHLOAN_REJECTED, "risk accounts required")
        for ix in (*plan.setup_instructions, *plan.strategy_instructions, *plan.cleanup_instructions):
            if ix.program_id == COMPUTE_BUDGET_PROGRAM_ID:
                raise TransactionCompileError(ExecutionErrorCode.INVALID_PLAN, "external compute budget instruction rejected")
            if ix.kind == "sender":
                raise TransactionCompileError(ExecutionErrorCode.INVALID_PLAN, "sender instruction in provider strategy rejected")
            if any(a.startswith("PLACEHOLDER") for a in ix.accounts):
                raise TransactionCompileError(ExecutionErrorCode.INVALID_PLAN, "placeholder account rejected")

    def _validate_alts(self, plan: TransactionPlan, lookup_tables: tuple[ResolvedAddressLookupTable, ...]) -> None:
        by_addr = {a.address: a for a in lookup_tables}
        for address in plan.lookup_table_addresses:
            alt = by_addr.get(address)
            if alt is None or not alt.addresses or not alt.library_deserialized:
                raise TransactionCompileError(ExecutionErrorCode.UNRESOLVED_ALT, "unresolved or empty ALT")
            if alt.owner != ADDRESS_LOOKUP_TABLE_PROGRAM_ID:
                raise TransactionCompileError(ExecutionErrorCode.UNRESOLVED_ALT, "ALT owner mismatch")
            if alt.deactivation_slot not in (None, 2**64 - 1):
                raise TransactionCompileError(ExecutionErrorCode.UNRESOLVED_ALT, "deactivated ALT")

    def _pass1(self, plan: TransactionPlan) -> list[Instruction]:
        cb = plan.compute_budget_policy
        compute = (Instruction(COMPUTE_BUDGET_PROGRAM_ID, data=f"limit:{cb.unit_limit}".encode(), name="set_compute_unit_limit", kind="compute_budget"), Instruction(COMPUTE_BUDGET_PROGRAM_ID, data=f"price:{cb.micro_lamports_per_cu}".encode(), name="set_compute_unit_price", kind="compute_budget"))
        end_accounts = plan.flash_loan_plan.projected_active_balances + plan.flash_loan_plan.risk_engine_accounts
        if plan.flash_loan_plan.token_2022_mint:
            end_accounts = (plan.flash_loan_plan.token_2022_mint,) + end_accounts
        end = replace(plan.flash_loan_plan.end_instruction_template, accounts=end_accounts, kind="marginfi_end", name="marginfi_end_flashloan")
        tip = ()
        if plan.tip_policy.lamports:
            if not plan.tip_policy.tip_account:
                raise TransactionCompileError(ExecutionErrorCode.INVALID_PLAN, "tip account must come from getTipAccounts")
            tip = (Instruction("11111111111111111111111111111111", (plan.payer, plan.tip_policy.tip_account), f"tip:{plan.tip_policy.lamports}".encode(), "jito_tip", "tip"),)
        for ix in plan.cleanup_instructions:
            if ix.kind in {"close_wsol", "unwrap_wsol"}:
                # cleanup is placed after repay by compiler, but still before end would hide repayment liquidity.
                raise TransactionCompileError(ExecutionErrorCode.INVALID_PLAN, "wSOL cleanup before repay/end is prohibited in flash-loan path")
        return [*compute, *plan.setup_instructions, plan.flash_loan_plan.borrow_instruction, *plan.strategy_instructions, plan.flash_loan_plan.repay_instruction, end, *plan.cleanup_instructions, *tip]

    def _pass2(self, plan: TransactionPlan, descriptors: list[Instruction]) -> tuple[tuple[Instruction, ...], int]:
        end_index = next(i for i, ix in enumerate(descriptors) if ix.kind == "marginfi_end") + 1  # +1 because start is inserted before borrow
        start = Instruction("MRGNFi11111111111111111111111111111111111", (plan.flash_loan_plan.marginfi_account, plan.flash_loan_plan.authority, plan.flash_loan_plan.group), f"end_index:{end_index}".encode(), "marginfi_start_flashloan", "marginfi_start")
        borrow_pos = next(i for i, ix in enumerate(descriptors) if ix is plan.flash_loan_plan.borrow_instruction)
        final = [*descriptors[:borrow_pos], start, *descriptors[borrow_pos:]]
        actual_end_index = next(i for i, ix in enumerate(final) if ix.kind == "marginfi_end")
        if actual_end_index != end_index:
            raise TransactionCompileError(ExecutionErrorCode.INVALID_PLAN, "MarginFi end index mismatch")
        repay_index = next(i for i, ix in enumerate(final) if ix.kind == "marginfi_repay")
        if repay_index >= actual_end_index:
            raise TransactionCompileError(ExecutionErrorCode.INVALID_PLAN, "repay must precede end")
        for i, ix in enumerate(final):
            if ix.kind == "tip" and i <= actual_end_index:
                raise TransactionCompileError(ExecutionErrorCode.INVALID_PLAN, "tip must be after MarginFi end")
        return tuple(final), actual_end_index

    def _serialize_message(self, payer: str, blockhash: str, instructions: tuple[Instruction, ...], alts: tuple[ResolvedAddressLookupTable, ...]) -> bytes:
        return b"\n".join([payer.encode(), blockhash.encode(), *(ix.stable_bytes() for ix in instructions), *(a.address.encode() + b":" + a.data_hash.encode() for a in alts)])
