"""PR-035 hardening for canonical Solana v0 compilation.

This layer adds lifecycle/context checks that do not belong to the protocol
planner: recent-blockhash viability, exact ALT provenance/order, immutable plan
fingerprints, account-lock ceilings, and structured retry reasons.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import time
from typing import Iterable

from solders.address_lookup_table_account import ID as ADDRESS_LOOKUP_TABLE_ID
from solders.instruction import Instruction
from solders.message import MessageV0
from solders.pubkey import Pubkey

from .canonical_domain import (
    CanonicalTransactionCompiler,
    validate_canonical_plan,
    validate_compiled_identity,
)
from .models import (
    SOLANA_WIRE_TRANSACTION_LIMIT_BYTES,
    BlockhashContext,
    CompiledTransaction,
    ExecutionErrorCode,
    ResolvedAddressLookupTable,
    TransactionPlan,
)
from .transaction_compiler import TransactionCompileError

_U64_MAX = 2**64 - 1


class V0CompileFailureReason(str, Enum):
    """Stable reasons that a route scheduler may classify without parsing text."""

    INVALID_CONTEXT = "invalid_context"
    BLOCKHASH_STALE = "blockhash_stale"
    BLOCKHASH_NEAR_EXPIRY = "blockhash_near_expiry"
    BLOCKHASH_SLOT_AHEAD = "blockhash_slot_ahead"
    ALT_ORDER_MISMATCH = "alt_order_mismatch"
    ALT_OWNER_MISMATCH = "alt_owner_mismatch"
    ALT_DEACTIVATED = "alt_deactivated"
    ALT_CONTEXT_STALE = "alt_context_stale"
    ALT_EXTENSION_UNSAFE = "alt_extension_unsafe"
    ALT_CONTENT_MISMATCH = "alt_content_mismatch"
    REQUIRED_LOOKUP_MISSING = "required_lookup_missing"
    ACCOUNT_LOCK_LIMIT = "account_lock_limit"
    TRANSACTION_TOO_LARGE = "transaction_too_large"
    PLAN_MUTATED = "plan_mutated"
    COMPILED_IDENTITY_MISMATCH = "compiled_identity_mismatch"


_REASON_CODES: dict[V0CompileFailureReason, ExecutionErrorCode] = {
    V0CompileFailureReason.BLOCKHASH_STALE: ExecutionErrorCode.BLOCKHASH_EXPIRED,
    V0CompileFailureReason.BLOCKHASH_NEAR_EXPIRY: ExecutionErrorCode.BLOCKHASH_EXPIRED,
    V0CompileFailureReason.BLOCKHASH_SLOT_AHEAD: ExecutionErrorCode.INVALID_BLOCKHASH,
    V0CompileFailureReason.ALT_ORDER_MISMATCH: ExecutionErrorCode.UNRESOLVED_ALT,
    V0CompileFailureReason.ALT_OWNER_MISMATCH: ExecutionErrorCode.UNRESOLVED_ALT,
    V0CompileFailureReason.ALT_DEACTIVATED: ExecutionErrorCode.UNRESOLVED_ALT,
    V0CompileFailureReason.ALT_CONTEXT_STALE: ExecutionErrorCode.UNRESOLVED_ALT,
    V0CompileFailureReason.ALT_EXTENSION_UNSAFE: ExecutionErrorCode.UNRESOLVED_ALT,
    V0CompileFailureReason.ALT_CONTENT_MISMATCH: ExecutionErrorCode.UNRESOLVED_ALT,
    V0CompileFailureReason.REQUIRED_LOOKUP_MISSING: ExecutionErrorCode.UNRESOLVED_ALT,
    V0CompileFailureReason.ACCOUNT_LOCK_LIMIT: ExecutionErrorCode.INVALID_PLAN,
    V0CompileFailureReason.TRANSACTION_TOO_LARGE: ExecutionErrorCode.TRANSACTION_TOO_LARGE,
    V0CompileFailureReason.PLAN_MUTATED: ExecutionErrorCode.INVALID_PLAN,
    V0CompileFailureReason.COMPILED_IDENTITY_MISMATCH: ExecutionErrorCode.INVALID_PLAN,
    V0CompileFailureReason.INVALID_CONTEXT: ExecutionErrorCode.INVALID_PLAN,
}


class V0HardeningError(TransactionCompileError):
    """Structured fail-closed error for bounded route retry decisions."""

    def __init__(
        self,
        reason: V0CompileFailureReason,
        message: str,
        *,
        retryable: bool,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        safe_diagnostics = dict(diagnostics or {})
        safe_diagnostics["reason"] = reason.value
        safe_diagnostics["retryable"] = retryable
        super().__init__(_REASON_CODES[reason], message, safe_diagnostics)
        self.reason = reason
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class V0CompilePolicy:
    """Bounded compiler policy; callers may tighten but not silently relax it."""

    max_wire_bytes: int = SOLANA_WIRE_TRANSACTION_LIMIT_BYTES
    max_account_locks: int = 64
    min_remaining_block_heights: int = 20
    max_blockhash_age_seconds: float = 45.0
    allowed_commitments: tuple[str, ...] = ("processed", "confirmed", "finalized")

    def __post_init__(self) -> None:
        if not (1 <= self.max_wire_bytes <= SOLANA_WIRE_TRANSACTION_LIMIT_BYTES):
            raise ValueError("max_wire_bytes must be within the Solana wire limit")
        if self.max_account_locks < 1:
            raise ValueError("max_account_locks must be positive")
        if self.min_remaining_block_heights < 0:
            raise ValueError("min_remaining_block_heights cannot be negative")
        if self.max_blockhash_age_seconds <= 0:
            raise ValueError("max_blockhash_age_seconds must be positive")
        if not self.allowed_commitments:
            raise ValueError("allowed_commitments cannot be empty")


@dataclass(frozen=True, slots=True)
class CompileRuntimeContext:
    current_block_height: int
    current_slot: int
    observed_at: float

    @classmethod
    def now(
        cls, *, current_block_height: int, current_slot: int
    ) -> "CompileRuntimeContext":
        return cls(
            current_block_height=current_block_height,
            current_slot=current_slot,
            observed_at=time.time(),
        )

    def validate(self) -> None:
        if self.current_block_height < 0 or self.current_slot < 0:
            raise V0HardeningError(
                V0CompileFailureReason.INVALID_CONTEXT,
                "runtime height and slot must be non-negative",
                retryable=False,
            )
        if self.observed_at < 0:
            raise V0HardeningError(
                V0CompileFailureReason.INVALID_CONTEXT,
                "observed_at must be non-negative",
                retryable=False,
            )


@dataclass(frozen=True, slots=True)
class CompilationFingerprints:
    plan_sha256: str
    instruction_sha256: str
    lookup_tables_sha256: str
    blockhash_sha256: str
    message_sha256: str


@dataclass(frozen=True, slots=True)
class HardenedCompilation:
    compiled: CompiledTransaction
    policy: V0CompilePolicy
    runtime_context: CompileRuntimeContext
    fingerprints: CompilationFingerprints


def _put(buffer: bytearray, value: object) -> None:
    raw = str(value).encode("utf-8")
    buffer.extend(len(raw).to_bytes(4, "little"))
    buffer.extend(raw)


def _instruction_bytes(instruction: Instruction) -> bytes:
    payload = bytearray()
    _put(payload, instruction.program_id)
    payload.extend(len(instruction.accounts).to_bytes(4, "little"))
    for meta in instruction.accounts:
        _put(payload, meta.pubkey)
        payload.extend(b"\x01" if meta.is_signer else b"\x00")
        payload.extend(b"\x01" if meta.is_writable else b"\x00")
    payload.extend(len(instruction.data).to_bytes(8, "little"))
    payload.extend(bytes(instruction.data))
    return bytes(payload)


def instruction_fingerprint(plan: TransactionPlan) -> str:
    payload = bytearray()
    for planned in plan.instructions:
        _put(payload, planned.role)
        _put(payload, planned.name or "")
        payload.extend(_instruction_bytes(planned.instruction))
    return hashlib.sha256(payload).hexdigest()


def plan_fingerprint(plan: TransactionPlan) -> str:
    """Hash every field that may influence compilation."""

    validate_canonical_plan(plan)
    payload = bytearray()
    for value in (
        plan.opportunity_id,
        plan.payer,
        plan.compute_budget_policy.unit_limit,
        plan.compute_budget_policy.micro_lamports_per_cu,
        plan.compute_budget_policy.simulation_unit_limit,
        plan.compute_budget_policy.safety_margin_bps,
        plan.tip_policy.lamports,
        plan.tip_policy.tip_account or "",
        plan.quote_slot,
        plan.market_state_slot,
        plan.oracle_slot,
    ):
        _put(payload, value)
    for collection in (
        plan.required_signers,
        plan.lookup_table_addresses,
        plan.required_lookup_addresses,
        plan.monitored_accounts,
    ):
        payload.extend(len(collection).to_bytes(4, "little"))
        for value in collection:
            _put(payload, value)
    payload.extend(bytes.fromhex(instruction_fingerprint(plan)))
    return hashlib.sha256(payload).hexdigest()


def lookup_tables_fingerprint(
    lookup_tables: Iterable[ResolvedAddressLookupTable],
) -> str:
    payload = bytearray()
    for alt in lookup_tables:
        for value in (
            alt.address,
            alt.owner,
            alt.deactivation_slot,
            alt.last_extended_slot,
            alt.last_extended_slot_start_index,
            alt.source_slot,
            alt.data_hash,
        ):
            _put(payload, value)
        payload.extend(len(alt.addresses).to_bytes(4, "little"))
        for address in alt.addresses:
            _put(payload, address)
    return hashlib.sha256(payload).hexdigest()


def blockhash_fingerprint(blockhash: BlockhashContext) -> str:
    payload = bytearray()
    for value in (
        blockhash.blockhash,
        blockhash.last_valid_block_height,
        blockhash.source_slot,
        blockhash.fetched_at,
        blockhash.commitment,
    ):
        _put(payload, value)
    return hashlib.sha256(payload).hexdigest()


def _validate_blockhash(
    blockhash: BlockhashContext,
    context: CompileRuntimeContext,
    policy: V0CompilePolicy,
) -> None:
    context.validate()
    try:
        blockhash.validate()
    except ValueError as exc:
        raise V0HardeningError(
            V0CompileFailureReason.BLOCKHASH_STALE,
            "blockhash is missing or invalid",
            retryable=True,
        ) from exc
    if blockhash.commitment not in policy.allowed_commitments:
        raise V0HardeningError(
            V0CompileFailureReason.INVALID_CONTEXT,
            "blockhash commitment is not allowed",
            retryable=False,
            diagnostics={"commitment": blockhash.commitment},
        )
    if blockhash.source_slot > context.current_slot:
        raise V0HardeningError(
            V0CompileFailureReason.BLOCKHASH_SLOT_AHEAD,
            "blockhash source slot is ahead of runtime context",
            retryable=True,
            diagnostics={
                "source_slot": blockhash.source_slot,
                "current_slot": context.current_slot,
            },
        )
    age = context.observed_at - blockhash.fetched_at
    if age < 0 or age > policy.max_blockhash_age_seconds:
        raise V0HardeningError(
            V0CompileFailureReason.BLOCKHASH_STALE,
            "blockhash age is outside policy",
            retryable=True,
            diagnostics={"age_seconds": age},
        )
    remaining = blockhash.last_valid_block_height - context.current_block_height
    if remaining < policy.min_remaining_block_heights:
        raise V0HardeningError(
            V0CompileFailureReason.BLOCKHASH_NEAR_EXPIRY,
            "blockhash is too close to expiry",
            retryable=True,
            diagnostics={
                "remaining_block_heights": remaining,
                "minimum": policy.min_remaining_block_heights,
            },
        )


def _validate_lookup_tables(
    plan: TransactionPlan,
    lookup_tables: tuple[ResolvedAddressLookupTable, ...],
    context: CompileRuntimeContext,
) -> None:
    expected_order = tuple(plan.lookup_table_addresses)
    actual_order = tuple(alt.address for alt in lookup_tables)
    if actual_order != expected_order:
        raise V0HardeningError(
            V0CompileFailureReason.ALT_ORDER_MISMATCH,
            "lookup tables must be supplied in plan order",
            retryable=True,
            diagnostics={
                "expected_count": len(expected_order),
                "actual_count": len(actual_order),
            },
        )

    all_addresses: set[Pubkey] = set()
    for alt in lookup_tables:
        if alt.owner != ADDRESS_LOOKUP_TABLE_ID:
            raise V0HardeningError(
                V0CompileFailureReason.ALT_OWNER_MISMATCH,
                "lookup table owner mismatch",
                retryable=False,
                diagnostics={"lookup_table": str(alt.address)},
            )
        if alt.deactivation_slot != _U64_MAX:
            raise V0HardeningError(
                V0CompileFailureReason.ALT_DEACTIVATED,
                "lookup table is deactivated or deactivating",
                retryable=True,
                diagnostics={"lookup_table": str(alt.address)},
            )
        if (
            alt.source_slot < plan.min_context_slot
            or alt.source_slot > context.current_slot
        ):
            raise V0HardeningError(
                V0CompileFailureReason.ALT_CONTEXT_STALE,
                "lookup table context does not satisfy plan/runtime slots",
                retryable=True,
                diagnostics={
                    "lookup_table": str(alt.address),
                    "source_slot": alt.source_slot,
                    "plan_min_context_slot": plan.min_context_slot,
                    "current_slot": context.current_slot,
                },
            )
        if alt.last_extended_slot is None or alt.last_extended_slot >= alt.source_slot:
            raise V0HardeningError(
                V0CompileFailureReason.ALT_EXTENSION_UNSAFE,
                "lookup table extension is not rooted before its source slot",
                retryable=True,
                diagnostics={"lookup_table": str(alt.address)},
            )
        if (
            not alt.library_deserialized
            or alt.account.key != alt.address
            or tuple(alt.account.addresses) != tuple(alt.addresses)
            or len(set(alt.addresses)) != len(alt.addresses)
        ):
            raise V0HardeningError(
                V0CompileFailureReason.ALT_CONTENT_MISMATCH,
                "lookup table canonical content/order mismatch",
                retryable=False,
                diagnostics={"lookup_table": str(alt.address)},
            )
        all_addresses.update(alt.addresses)

    missing = set(plan.required_lookup_addresses) - all_addresses
    if missing:
        raise V0HardeningError(
            V0CompileFailureReason.REQUIRED_LOOKUP_MISSING,
            "required lookup address is missing",
            retryable=True,
            diagnostics={"missing_count": len(missing)},
        )


class HardenedV0Compiler:
    """Compile one immutable plan with explicit slot/height context."""

    def __init__(self, policy: V0CompilePolicy = V0CompilePolicy()) -> None:
        self.policy = policy
        self._delegate = CanonicalTransactionCompiler(max_size=policy.max_wire_bytes)

    def compile(
        self,
        plan: TransactionPlan,
        blockhash: BlockhashContext,
        lookup_tables: tuple[ResolvedAddressLookupTable, ...] = (),
        *,
        runtime_context: CompileRuntimeContext,
    ) -> HardenedCompilation:
        validate_canonical_plan(plan)
        before = plan_fingerprint(plan)
        _validate_blockhash(blockhash, runtime_context, self.policy)
        _validate_lookup_tables(plan, lookup_tables, runtime_context)

        compiled = self._delegate.compile(plan, blockhash, lookup_tables)
        after = plan_fingerprint(plan)
        if before != after:
            raise V0HardeningError(
                V0CompileFailureReason.PLAN_MUTATED,
                "transaction plan changed during compilation",
                retryable=False,
            )

        self._validate_compiled(compiled, plan, blockhash, lookup_tables)
        fingerprints = CompilationFingerprints(
            plan_sha256=before,
            instruction_sha256=instruction_fingerprint(plan),
            lookup_tables_sha256=lookup_tables_fingerprint(lookup_tables),
            blockhash_sha256=blockhash_fingerprint(blockhash),
            message_sha256=compiled.message_hash,
        )
        return HardenedCompilation(
            compiled=compiled,
            policy=self.policy,
            runtime_context=runtime_context,
            fingerprints=fingerprints,
        )

    def revalidate(
        self,
        hardened: HardenedCompilation,
        plan: TransactionPlan,
        *,
        runtime_context: CompileRuntimeContext,
    ) -> None:
        _validate_blockhash(
            hardened.compiled.blockhash_context,
            runtime_context,
            hardened.policy,
        )
        _validate_lookup_tables(plan, hardened.compiled.lookup_tables, runtime_context)
        if plan_fingerprint(plan) != hardened.fingerprints.plan_sha256:
            raise V0HardeningError(
                V0CompileFailureReason.PLAN_MUTATED,
                "plan fingerprint changed after compile",
                retryable=False,
            )
        self._validate_compiled(
            hardened.compiled,
            plan,
            hardened.compiled.blockhash_context,
            hardened.compiled.lookup_tables,
        )
        if hardened.compiled.message_hash != hardened.fingerprints.message_sha256:
            raise V0HardeningError(
                V0CompileFailureReason.COMPILED_IDENTITY_MISMATCH,
                "compiled message fingerprint changed",
                retryable=False,
            )

    def _validate_compiled(
        self,
        compiled: CompiledTransaction,
        plan: TransactionPlan,
        blockhash: BlockhashContext,
        lookup_tables: tuple[ResolvedAddressLookupTable, ...],
    ) -> None:
        try:
            validate_compiled_identity(compiled)
        except TransactionCompileError as exc:
            raise V0HardeningError(
                V0CompileFailureReason.COMPILED_IDENTITY_MISMATCH,
                "compiled v0 identity validation failed",
                retryable=False,
            ) from exc
        if not isinstance(compiled.message, MessageV0):
            raise V0HardeningError(
                V0CompileFailureReason.COMPILED_IDENTITY_MISMATCH,
                "compiler did not produce MessageV0",
                retryable=False,
            )
        if compiled.blockhash_context != blockhash:
            raise V0HardeningError(
                V0CompileFailureReason.COMPILED_IDENTITY_MISMATCH,
                "compiled blockhash context changed",
                retryable=False,
            )
        if tuple(alt.address for alt in compiled.lookup_tables) != tuple(
            plan.lookup_table_addresses
        ):
            raise V0HardeningError(
                V0CompileFailureReason.ALT_ORDER_MISMATCH,
                "compiled lookup table order changed",
                retryable=False,
            )
        if tuple(compiled.required_signers) != tuple(plan.required_signers):
            raise V0HardeningError(
                V0CompileFailureReason.COMPILED_IDENTITY_MISMATCH,
                "compiled signer order changed",
                retryable=False,
            )
        if compiled.diagnostics.wire_size > self.policy.max_wire_bytes:
            raise V0HardeningError(
                V0CompileFailureReason.TRANSACTION_TOO_LARGE,
                "compiled transaction exceeds policy wire size",
                retryable=True,
                diagnostics={
                    "actual_size": compiled.diagnostics.wire_size,
                    "limit": self.policy.max_wire_bytes,
                },
            )
        if (
            compiled.diagnostics.total_resolved_account_count
            > self.policy.max_account_locks
        ):
            raise V0HardeningError(
                V0CompileFailureReason.ACCOUNT_LOCK_LIMIT,
                "compiled transaction exceeds account-lock policy",
                retryable=True,
                diagnostics={
                    "actual_count": compiled.diagnostics.total_resolved_account_count,
                    "limit": self.policy.max_account_locks,
                },
            )
