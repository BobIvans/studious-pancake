"""Protocol-agnostic Solana v0 transaction compiler and signer."""

from __future__ import annotations

from collections import Counter
from typing import Iterable, Sequence

from solders.address_lookup_table_account import (
    LOOKUP_TABLE_MAX_ADDRESSES,
    AddressLookupTable,
    AddressLookupTableAccount,
)
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import MessageV0, from_bytes_versioned, to_bytes_versioned
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction

from .models import (
    ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
    COMPUTE_BUDGET_PROGRAM_ID,
    SOLANA_WIRE_TRANSACTION_LIMIT_BYTES,
    BlockhashContext,
    CompiledTransaction,
    ExecutionErrorCode,
    PlannedInstruction,
    ResolvedAddressLookupTable,
    SignedTransaction,
    TransactionDiagnostics,
    TransactionPlan,
    compute_message_hash,
)


class TransactionCompileError(ValueError):
    """Typed fail-closed compiler error with safe diagnostics."""

    def __init__(
        self,
        code: ExecutionErrorCode,
        message: str,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics or {}


class AltValidator:
    """Validate on-chain Address Lookup Table state before v0 compilation."""

    def deserialize(
        self,
        address: Pubkey,
        raw_data: bytes,
        owner: Pubkey,
        source_slot: int,
        required_addresses: Iterable[Pubkey] = (),
        deactivation_slot: int | None = None,
    ) -> ResolvedAddressLookupTable:
        if not isinstance(address, Pubkey) or not isinstance(owner, Pubkey):
            raise TransactionCompileError(
                ExecutionErrorCode.UNRESOLVED_ALT,
                "ALT address/owner must be Pubkey",
            )
        if owner != ADDRESS_LOOKUP_TABLE_PROGRAM_ID:
            raise TransactionCompileError(
                ExecutionErrorCode.UNRESOLVED_ALT,
                "ALT owner mismatch",
            )
        try:
            parsed = AddressLookupTable.deserialize(raw_data)
        except Exception:
            try:
                parsed = AddressLookupTable.from_bytes(raw_data)
            except Exception as exc:
                raise TransactionCompileError(
                    ExecutionErrorCode.UNRESOLVED_ALT,
                    "ALT official parser failed",
                ) from exc

        addresses = tuple(parsed.addresses)
        meta = parsed.meta
        if not addresses or len(addresses) > LOOKUP_TABLE_MAX_ADDRESSES:
            raise TransactionCompileError(
                ExecutionErrorCode.UNRESOLVED_ALT,
                "ALT address count invalid",
            )
        if len(set(addresses)) != len(addresses):
            raise TransactionCompileError(
                ExecutionErrorCode.UNRESOLVED_ALT,
                "ALT duplicate addresses",
            )

        parsed_deactivation = (
            deactivation_slot
            if deactivation_slot is not None
            else int(meta.deactivation_slot)
        )
        if parsed_deactivation != 2**64 - 1:
            raise TransactionCompileError(
                ExecutionErrorCode.UNRESOLVED_ALT,
                "ALT is deactivated or deactivating",
            )
        if int(meta.last_extended_slot) >= source_slot:
            raise TransactionCompileError(
                ExecutionErrorCode.UNRESOLVED_ALT,
                "ALT extension slot is not older than source slot",
            )

        required = set(required_addresses)
        missing = required - set(addresses)
        if missing:
            raise TransactionCompileError(
                ExecutionErrorCode.UNRESOLVED_ALT,
                "ALT missing required addresses",
                {"missing": [str(m) for m in sorted(missing, key=str)]},
            )

        return ResolvedAddressLookupTable(
            address=address,
            owner=owner,
            addresses=addresses,
            deactivation_slot=parsed_deactivation,
            last_extended_slot=int(meta.last_extended_slot),
            last_extended_slot_start_index=int(meta.last_extended_slot_start_index),
            source_slot=source_slot,
            data_hash=compute_message_hash(raw_data),
            account=AddressLookupTableAccount(address, addresses),
        )


class TransactionCompiler:
    """Compile generic Solana instructions into unsigned and signed v0 transactions."""

    def __init__(self, *, max_size: int = SOLANA_WIRE_TRANSACTION_LIMIT_BYTES) -> None:
        self.max_size = max_size

    def compile(
        self,
        plan: TransactionPlan,
        blockhash: BlockhashContext,
        lookup_tables: tuple[ResolvedAddressLookupTable, ...] = (),
    ) -> CompiledTransaction:
        try:
            blockhash.validate()
        except ValueError as exc:
            raise TransactionCompileError(
                ExecutionErrorCode.INVALID_BLOCKHASH,
                "invalid recent blockhash",
            ) from exc

        self._validate_plan(plan)
        self._validate_alts(plan, lookup_tables)
        instructions = self._compose_instructions(plan)
        alt_accounts = [alt.account for alt in lookup_tables]

        try:
            message = MessageV0.try_compile(
                plan.payer,
                list(instructions),
                alt_accounts,
                blockhash.blockhash,
            )
        except Exception as exc:
            raise TransactionCompileError(
                ExecutionErrorCode.INVALID_PLAN,
                "MessageV0.try_compile failed",
            ) from exc

        signer_count = message.header.num_required_signatures
        signer_keys = tuple(message.account_keys[:signer_count])
        if not signer_keys or signer_keys[0] != plan.payer:
            raise TransactionCompileError(
                ExecutionErrorCode.MISSING_SIGNER,
                "payer must be first signer",
            )
        if signer_keys != plan.required_signers:
            raise TransactionCompileError(
                ExecutionErrorCode.MISSING_SIGNER,
                "declared signers do not match compiled message order",
                {
                    "compiled": [str(signer) for signer in signer_keys],
                    "declared": [str(signer) for signer in plan.required_signers],
                },
            )

        serialized_message = bytes(to_bytes_versioned(message))
        unsigned = VersionedTransaction.populate(
            message,
            [Signature.default()] * signer_count,
        )
        self._round_trip(unsigned, serialized_message)
        diagnostics = self._diagnostics(unsigned, message, lookup_tables)
        if diagnostics.wire_size > self.max_size:
            raise TransactionCompileError(
                ExecutionErrorCode.TRANSACTION_TOO_LARGE,
                "serialized transaction exceeds 1232 bytes",
                {
                    "actual_size": diagnostics.wire_size,
                    "limit": self.max_size,
                    "required_signature_count": diagnostics.required_signature_count,
                    "static_account_count": diagnostics.static_account_count,
                    "lookup_writable_count": diagnostics.lookup_writable_count,
                    "lookup_readonly_count": diagnostics.lookup_readonly_count,
                },
            )

        return CompiledTransaction(
            opportunity_id=plan.opportunity_id,
            payer=plan.payer,
            instructions=instructions,
            message=message,
            blockhash_context=blockhash,
            lookup_tables=lookup_tables,
            serialized_message=serialized_message,
            serialized_transaction=bytes(unsigned),
            versioned_transaction=unsigned,
            message_hash=compute_message_hash(serialized_message),
            min_context_slot=plan.min_context_slot,
            required_signers=signer_keys,
            diagnostics=diagnostics,
        )

    def sign_fully(
        self,
        compiled: CompiledTransaction,
        signers: Sequence[Keypair],
    ) -> SignedTransaction:
        if compiled.is_fully_signed:
            raise TransactionCompileError(
                ExecutionErrorCode.SIGNATURE_FAILED,
                "compiled result is already marked signed",
            )

        signer_pubkeys = [signer.pubkey() for signer in signers]
        counts = Counter(signer_pubkeys)
        if any(count != 1 for count in counts.values()):
            raise TransactionCompileError(
                ExecutionErrorCode.SIGNATURE_FAILED,
                "duplicate signer",
            )
        if set(signer_pubkeys) != set(compiled.required_signers):
            raise TransactionCompileError(
                ExecutionErrorCode.SIGNATURE_FAILED,
                "missing or unexpected signer",
                {
                    "required": [str(signer) for signer in compiled.required_signers],
                    "provided": [str(signer) for signer in signer_pubkeys],
                },
            )

        ordered = [
            next(signer for signer in signers if signer.pubkey() == pubkey)
            for pubkey in compiled.required_signers
        ]
        tx = VersionedTransaction(compiled.message, ordered)
        signed_message = bytes(to_bytes_versioned(tx.message))
        if signed_message != compiled.serialized_message:
            raise TransactionCompileError(
                ExecutionErrorCode.SIGNATURE_FAILED,
                "message changed during signing",
            )
        if compute_message_hash(compiled.serialized_message) != compiled.message_hash:
            raise TransactionCompileError(
                ExecutionErrorCode.SIGNATURE_FAILED,
                "compiled message hash mismatch",
            )
        if not all(tx.verify_with_results()):
            raise TransactionCompileError(
                ExecutionErrorCode.SIGNATURE_FAILED,
                "signature verification failed",
            )
        tx.verify_and_hash_message()
        tx.sanitize()

        raw = bytes(tx)
        if len(raw) > self.max_size:
            raise TransactionCompileError(
                ExecutionErrorCode.TRANSACTION_TOO_LARGE,
                "signed transaction exceeds 1232 bytes",
                {"actual_size": len(raw), "limit": self.max_size},
            )
        return SignedTransaction(
            compiled=compiled,
            versioned_transaction=tx,
            serialized_transaction=raw,
            signatures=tuple(tx.signatures),
            message_hash=compiled.message_hash,
        )

    def _validate_plan(self, plan: TransactionPlan) -> None:
        if not isinstance(plan.payer, Pubkey):
            raise TransactionCompileError(
                ExecutionErrorCode.INVALID_PLAN,
                "payer must be Pubkey",
            )
        if len(set(plan.required_signers)) != len(plan.required_signers):
            raise TransactionCompileError(
                ExecutionErrorCode.MISSING_SIGNER,
                "duplicate required signer",
            )
        if plan.payer not in plan.required_signers:
            raise TransactionCompileError(
                ExecutionErrorCode.MISSING_SIGNER,
                "payer must be required signer",
            )

        cb = plan.compute_budget_policy
        if cb.unit_limit is not None and not (1 <= cb.unit_limit <= 1_400_000):
            raise TransactionCompileError(
                ExecutionErrorCode.INVALID_PLAN,
                "compute unit limit out of range",
            )
        if cb.micro_lamports_per_cu is not None and cb.micro_lamports_per_cu < 0:
            raise TransactionCompileError(
                ExecutionErrorCode.INVALID_PLAN,
                "compute unit price out of range",
            )
        if plan.tip_policy.lamports < 0:
            raise TransactionCompileError(
                ExecutionErrorCode.INVALID_PLAN,
                "negative tip",
            )
        if plan.tip_policy.lamports > 0:
            if not isinstance(plan.tip_policy.tip_account, Pubkey):
                raise TransactionCompileError(
                    ExecutionErrorCode.INVALID_PLAN,
                    "tip account required",
                )

        for planned in plan.instructions:
            if not isinstance(planned, PlannedInstruction) or not isinstance(
                planned.instruction,
                Instruction,
            ):
                raise TransactionCompileError(
                    ExecutionErrorCode.INVALID_PLAN,
                    "wire instruction must be solders Instruction",
                )
            if planned.instruction.program_id == COMPUTE_BUDGET_PROGRAM_ID:
                raise TransactionCompileError(
                    ExecutionErrorCode.INVALID_PLAN,
                    "caller compute budget instruction rejected",
                )
            if planned.role in {"compute_budget", "tip", "sender"}:
                raise TransactionCompileError(
                    ExecutionErrorCode.INVALID_PLAN,
                    "compiler-owned/provider-sender role rejected",
                )

    def _validate_alts(
        self,
        plan: TransactionPlan,
        lookup_tables: tuple[ResolvedAddressLookupTable, ...],
    ) -> None:
        by_address = {alt.address: alt for alt in lookup_tables}
        if len(by_address) != len(lookup_tables):
            raise TransactionCompileError(
                ExecutionErrorCode.UNRESOLVED_ALT,
                "duplicate ALT account",
            )
        requested = set(plan.lookup_table_addresses)
        provided = set(by_address)
        unexpected = provided - requested
        if unexpected:
            raise TransactionCompileError(
                ExecutionErrorCode.UNRESOLVED_ALT,
                "unexpected ALT account",
                {"unexpected": [str(alt) for alt in sorted(unexpected, key=str)]},
            )

        for address in plan.lookup_table_addresses:
            alt = by_address.get(address)
            if (
                alt is None
                or alt.owner != ADDRESS_LOOKUP_TABLE_PROGRAM_ID
                or not alt.library_deserialized
            ):
                raise TransactionCompileError(
                    ExecutionErrorCode.UNRESOLVED_ALT,
                    "unresolved ALT",
                )

        all_lookup_addresses: set[Pubkey] = set()
        for alt in lookup_tables:
            all_lookup_addresses.update(alt.addresses)
        missing = set(plan.required_lookup_addresses) - all_lookup_addresses
        if missing:
            raise TransactionCompileError(
                ExecutionErrorCode.UNRESOLVED_ALT,
                "required lookup addresses missing",
                {"missing": [str(address) for address in sorted(missing, key=str)]},
            )

    def _compose_instructions(self, plan: TransactionPlan) -> tuple[Instruction, ...]:
        out: list[Instruction] = []
        cb = plan.compute_budget_policy
        if cb.unit_limit is not None:
            out.append(set_compute_unit_limit(cb.unit_limit))
        if cb.micro_lamports_per_cu is not None:
            out.append(set_compute_unit_price(cb.micro_lamports_per_cu))
        out.extend(planned.instruction for planned in plan.instructions)
        if plan.tip_policy.lamports > 0:
            out.append(
                transfer(
                    TransferParams(
                        from_pubkey=plan.payer,
                        to_pubkey=plan.tip_policy.tip_account,
                        lamports=plan.tip_policy.lamports,
                    ),
                ),
            )
        return tuple(out)

    def _round_trip(
        self,
        tx: VersionedTransaction,
        serialized_message: bytes,
    ) -> None:
        try:
            parsed = VersionedTransaction.from_bytes(bytes(tx))
            parsed.sanitize()
            from_bytes_versioned(serialized_message)
        except Exception as exc:
            raise TransactionCompileError(
                ExecutionErrorCode.INVALID_PLAN,
                "transaction round-trip failed",
            ) from exc

    def _diagnostics(
        self,
        tx: VersionedTransaction,
        message: MessageV0,
        lookup_tables: tuple[ResolvedAddressLookupTable, ...],
    ) -> TransactionDiagnostics:
        lookups = message.address_table_lookups
        lookup_writable_count = sum(len(lookup.writable_indexes) for lookup in lookups)
        lookup_readonly_count = sum(len(lookup.readonly_indexes) for lookup in lookups)
        return TransactionDiagnostics(
            wire_size=len(bytes(tx)),
            required_signature_count=message.header.num_required_signatures,
            static_account_count=len(message.account_keys),
            lookup_writable_count=lookup_writable_count,
            lookup_readonly_count=lookup_readonly_count,
            total_resolved_account_count=(
                len(message.account_keys)
                + lookup_writable_count
                + lookup_readonly_count
            ),
            used_alt_pubkeys=tuple(alt.address for alt in lookup_tables),
        )
