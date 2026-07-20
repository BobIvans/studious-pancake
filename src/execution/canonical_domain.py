"""Strict canonical execution boundary for production code.

PR-029 deliberately keeps legacy compatibility objects quarantined in their
original modules while making the public execution package fail closed unless
all plans and compiled artifacts use Solders primitives and canonical v0 bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import MessageV0, to_bytes_versioned
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from .models import (
    BlockhashContext,
    CompiledTransaction,
    ExecutionErrorCode,
    PlannedInstruction,
    ResolvedAddressLookupTable,
    SignedTransaction,
    TransactionPlan,
    compute_message_hash,
)
from .transaction_compiler import (
    TransactionCompileError,
    TransactionCompiler as _LegacyAwareCompiler,
)


class CanonicalExecutionContractError(TransactionCompileError, TypeError):
    """Fail-closed canonical boundary error compatible with compiler callers."""

    def __init__(self, message: str) -> None:
        super().__init__(ExecutionErrorCode.INVALID_PLAN, message)


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    """Transport-neutral receipt tied to exactly one canonical message hash."""

    message_hash: str
    transport: str
    accepted: bool
    landed: bool = False
    signature: str | None = None
    bundle_id: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if len(self.message_hash) != 64:
            raise CanonicalExecutionContractError("message_hash must be sha256 hex")
        try:
            int(self.message_hash, 16)
        except ValueError as exc:
            raise CanonicalExecutionContractError(
                "message_hash must be sha256 hex"
            ) from exc
        if not self.transport:
            raise CanonicalExecutionContractError("transport is required")
        if self.landed and not self.accepted:
            raise CanonicalExecutionContractError("landed receipt must be accepted")


def validate_canonical_plan(plan: TransactionPlan) -> None:
    """Reject every legacy positional/string plan before compilation."""

    if not isinstance(plan, TransactionPlan):
        raise CanonicalExecutionContractError("plan must be TransactionPlan")
    if not isinstance(plan.payer, Pubkey):
        raise CanonicalExecutionContractError("payer must be solders Pubkey")
    if not isinstance(plan.instructions, tuple):
        raise CanonicalExecutionContractError("instructions must be an immutable tuple")
    for planned in plan.instructions:
        if not isinstance(planned, PlannedInstruction):
            raise CanonicalExecutionContractError(
                "instructions must contain PlannedInstruction values"
            )
        if not isinstance(planned.instruction, Instruction):
            raise CanonicalExecutionContractError(
                "planned instruction must wrap solders Instruction"
            )
    if any(not isinstance(signer, Pubkey) for signer in plan.required_signers):
        raise CanonicalExecutionContractError("required_signers must be Pubkey values")
    if any(
        not isinstance(address, Pubkey)
        for address in (
            *plan.lookup_table_addresses,
            *plan.required_lookup_addresses,
            *plan.monitored_accounts,
        )
    ):
        raise CanonicalExecutionContractError(
            "all account identities must be Pubkey values"
        )


def validate_compiled_identity(compiled: CompiledTransaction) -> None:
    """Prove that all canonical representations describe the same v0 message."""

    if not isinstance(compiled.message, MessageV0):
        raise CanonicalExecutionContractError("compiled message must be MessageV0")
    if not isinstance(compiled.versioned_transaction, VersionedTransaction):
        raise CanonicalExecutionContractError(
            "compiled transaction must be VersionedTransaction"
        )
    message_bytes = bytes(to_bytes_versioned(compiled.message))
    if message_bytes != compiled.serialized_message:
        raise CanonicalExecutionContractError("serialized message identity mismatch")
    if bytes(compiled.versioned_transaction) != compiled.serialized_transaction:
        raise CanonicalExecutionContractError(
            "serialized transaction identity mismatch"
        )
    if compute_message_hash(message_bytes) != compiled.message_hash:
        raise CanonicalExecutionContractError("canonical message hash mismatch")
    if compiled.serialized_transaction.startswith(b"unsigned:"):
        raise CanonicalExecutionContractError(
            "synthetic unsigned transaction is forbidden"
        )


class CanonicalTransactionCompiler:
    """Public compiler that cannot enter the legacy synthetic branch."""

    def __init__(self, *args, **kwargs) -> None:
        self._delegate = _LegacyAwareCompiler(*args, **kwargs)

    @property
    def max_size(self) -> int:
        return self._delegate.max_size

    def compile(
        self,
        plan: TransactionPlan,
        blockhash: BlockhashContext,
        lookup_tables: tuple[ResolvedAddressLookupTable, ...] = (),
    ) -> CompiledTransaction:
        validate_canonical_plan(plan)
        compiled = self._delegate.compile(plan, blockhash, lookup_tables)
        validate_compiled_identity(compiled)
        return compiled

    def sign_fully(
        self,
        compiled: CompiledTransaction,
        signers: Sequence[Keypair],
    ) -> SignedTransaction:
        validate_compiled_identity(compiled)
        signed = self._delegate.sign_fully(compiled, signers)
        if signed.message_hash != compiled.message_hash:
            raise CanonicalExecutionContractError("signed message hash mismatch")
        if signed.serialized_transaction.startswith(b"unsigned:"):
            raise CanonicalExecutionContractError(
                "synthetic signed payload is forbidden"
            )
        return signed


# Public package compatibility name. Callers importing TransactionCompiler from
# src.execution receive the strict boundary, not the legacy-aware implementation.
TransactionCompiler = CanonicalTransactionCompiler


def sign_fully(
    compiled: CompiledTransaction,
    signers: Sequence[Keypair],
) -> SignedTransaction:
    """Sign through the strict canonical compiler boundary."""

    return CanonicalTransactionCompiler(
        max_size=max(1232, len(compiled.serialized_transaction))
    ).sign_fully(compiled, signers)
