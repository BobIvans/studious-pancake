"""Strict canonical execution boundary for production code.

PR-053 makes the public execution package fail closed unless all plans and
compiled artifacts use Solders primitives and canonical v0 bytes.  PR-071 adds
the explicit ownership registry for execution-domain reports, receipts and
sender protocols so later runtime composition cannot silently pick a duplicate
shadow/canary/sender boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from importlib import import_module
from typing import Any, Sequence

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
    TransactionCompiler as _CanonicalV0Compiler,
)

_SYNTHETIC_UNSIGNED_PREFIX = bytes.fromhex("756e7369676e65643a")


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


class DomainRole(StrEnum):
    """Execution-domain roles that must have exactly one production owner."""

    SIMULATION_REPORT = "simulation_report"
    RECONCILIATION_REPORT = "reconciliation_report"
    EXECUTION_RECEIPT = "execution_receipt"
    SENDER_PROTOCOL = "sender_protocol"


@dataclass(frozen=True, slots=True)
class CanonicalDomainSymbol:
    """A single importable production owner for one execution-domain role."""

    role: DomainRole
    module: str
    name: str
    rationale: str

    @property
    def qualified_name(self) -> str:
        return f"{self.module}.{self.name}"

    def resolve(self) -> Any:
        return getattr(import_module(self.module), self.name)


@dataclass(frozen=True, slots=True)
class QuarantinedDomainSymbol:
    """Known non-production compatibility symbol retained for migration only."""

    module: str
    name: str
    replacement_role: DomainRole
    reason: str

    @property
    def qualified_name(self) -> str:
        return f"{self.module}.{self.name}"


CANONICAL_EXECUTION_DOMAIN: tuple[CanonicalDomainSymbol, ...] = (
    CanonicalDomainSymbol(
        DomainRole.SIMULATION_REPORT,
        "src.execution.models",
        "SimulationReport",
        "Solders/exact simulator report shared by compiler, simulator and paper evidence.",
    ),
    CanonicalDomainSymbol(
        DomainRole.RECONCILIATION_REPORT,
        "src.execution.economic_reconciliation.models",
        "ReconciliationReport",
        "State-derived economic report with repayment, fee and account evidence.",
    ),
    CanonicalDomainSymbol(
        DomainRole.EXECUTION_RECEIPT,
        "src.execution.canonical_domain",
        "ExecutionReceipt",
        "Transport-neutral post-attempt receipt tied to exactly one message hash.",
    ),
    CanonicalDomainSymbol(
        DomainRole.SENDER_PROTOCOL,
        "src.submission.permit_bound",
        "Sender",
        "Permit-bound sender protocol; transport senders are implementations only.",
    ),
)


QUARANTINED_EXECUTION_DOMAIN_SYMBOLS: tuple[QuarantinedDomainSymbol, ...] = (
    QuarantinedDomainSymbol(
        "src.execution.shadow",
        "SimulationReport",
        DomainRole.SIMULATION_REPORT,
        "PR-013 replay fixture shape only; active exact simulation uses src.execution.models.",
    ),
    QuarantinedDomainSymbol(
        "src.execution.shadow",
        "ReconciliationResult",
        DomainRole.RECONCILIATION_REPORT,
        "Legacy shadow ledger result; production reconciliation uses economic_reconciliation.models.",
    ),
    QuarantinedDomainSymbol(
        "src.live_canary.models",
        "ReconciliationResult",
        DomainRole.RECONCILIATION_REPORT,
        "Canary status DTO only; it must not replace the canonical economic report.",
    ),
    QuarantinedDomainSymbol(
        "src.execution.live_control",
        "LiveSubmissionPermit",
        DomainRole.EXECUTION_RECEIPT,
        "Live-control permit DTO only; it is not the canonical post-attempt receipt.",
    ),
    QuarantinedDomainSymbol(
        "src.execution.live_control",
        "PermitBoundSender",
        DomainRole.SENDER_PROTOCOL,
        "Legacy live-control sender adapter; canonical protocol is src.submission.permit_bound.Sender.",
    ),
    QuarantinedDomainSymbol(
        "src.execution.senders.rpc_sender",
        "RpcTransactionSender",
        DomainRole.SENDER_PROTOCOL,
        "Legacy sender implementation kept outside the supported canonical sender stack.",
    ),
    QuarantinedDomainSymbol(
        "src.execution.senders.jito_single_sender",
        "JitoSingleTransactionSender",
        DomainRole.SENDER_PROTOCOL,
        "Legacy sender implementation kept outside the supported canonical sender stack.",
    ),
    QuarantinedDomainSymbol(
        "src.execution.senders.jito_bundle_sender",
        "JitoBundleSender",
        DomainRole.SENDER_PROTOCOL,
        "Legacy sender implementation kept outside the supported canonical sender stack.",
    ),
)


def canonical_symbol(role: DomainRole) -> CanonicalDomainSymbol:
    matches = tuple(item for item in CANONICAL_EXECUTION_DOMAIN if item.role is role)
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one canonical symbol for {role.value}")
    return matches[0]


def canonical_qualified_names() -> frozenset[str]:
    return frozenset(item.qualified_name for item in CANONICAL_EXECUTION_DOMAIN)


def quarantined_qualified_names() -> frozenset[str]:
    return frozenset(
        item.qualified_name for item in QUARANTINED_EXECUTION_DOMAIN_SYMBOLS
    )


def validate_canonical_execution_domain() -> None:
    """Fail closed if role ownership drifts or any canonical import is broken."""

    roles = [item.role for item in CANONICAL_EXECUTION_DOMAIN]
    if len(roles) != len(set(roles)):
        raise RuntimeError("duplicate canonical execution-domain role")
    for item in CANONICAL_EXECUTION_DOMAIN:
        if item.resolve() is None:
            raise RuntimeError(
                f"canonical symbol is not importable: {item.qualified_name}"
            )
    overlap = canonical_qualified_names() & quarantined_qualified_names()
    if overlap:
        names = ", ".join(sorted(overlap))
        raise RuntimeError(f"canonical symbols cannot be quarantined: {names}")


def validate_canonical_plan(plan: TransactionPlan) -> None:
    """Reject every string/compatibility plan before compilation."""

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
    if compiled.serialized_transaction.startswith(_SYNTHETIC_UNSIGNED_PREFIX):
        raise CanonicalExecutionContractError(
            "non-canonical unsigned transaction envelope is forbidden"
        )


class CanonicalTransactionCompiler:
    """Public compiler that has no legacy synthetic branch."""

    def __init__(self, *args, **kwargs) -> None:
        self._delegate = _CanonicalV0Compiler(*args, **kwargs)

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
        if signed.serialized_transaction.startswith(_SYNTHETIC_UNSIGNED_PREFIX):
            raise CanonicalExecutionContractError(
                "non-canonical signed payload is forbidden"
            )
        return signed


# Public package compatibility name. Callers importing TransactionCompiler from
# src.execution receive the strict canonical boundary.
TransactionCompiler = CanonicalTransactionCompiler


def sign_fully(
    compiled: CompiledTransaction,
    signers: Sequence[Keypair],
) -> SignedTransaction:
    """Sign through the strict canonical compiler boundary."""

    return CanonicalTransactionCompiler(
        max_size=max(1232, len(compiled.serialized_transaction))
    ).sign_fully(compiled, signers)
