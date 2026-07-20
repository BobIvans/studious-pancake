"""Exact-message simulation and compute-budget finalization.

PR-036 makes one compiled Solana v0 message the authority for simulation,
fee quoting, permit binding, and eventual submission.  RPC ambiguity never
becomes success: a caller receives either a fully bound result or a typed,
fail-closed error.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json
from typing import Any, Sequence

from .canonical_domain import (
    CanonicalExecutionContractError,
    CanonicalTransactionCompiler,
    validate_compiled_identity,
)
from .models import (
    SOLANA_WIRE_TRANSACTION_LIMIT_BYTES,
    BlockhashContext,
    CompiledTransaction,
    ComputeBudgetPolicy,
    ResolvedAddressLookupTable,
    RpcClient,
    TransactionPlan,
    compute_message_hash,
)


class FailureDisposition(str, Enum):
    """Whether rebuilding/retrying may recover from a finalization failure."""

    RETRYABLE = "retryable"
    FATAL = "fatal"


class ExactSimulationErrorCode(str, Enum):
    INVALID_CONTEXT = "invalid_context"
    COMPILATION_FAILED = "compilation_failed"
    BLOCKHASH_EXPIRED = "blockhash_expired"
    RPC_TIMEOUT = "rpc_timeout"
    RPC_ERROR = "rpc_error"
    MALFORMED_RPC_RESPONSE = "malformed_rpc_response"
    CONTEXT_SLOT_VIOLATION = "context_slot_violation"
    SIMULATION_FAILED = "simulation_failed"
    COMPUTE_LIMIT_EXCEEDED = "compute_limit_exceeded"
    LOADED_ACCOUNT_BYTES_EXCEEDED = "loaded_account_bytes_exceeded"
    ACCOUNT_LIMIT_EXCEEDED = "account_limit_exceeded"
    WIRE_SIZE_EXCEEDED = "wire_size_exceeded"
    FEE_UNAVAILABLE = "fee_unavailable"
    MESSAGE_IDENTITY_MISMATCH = "message_identity_mismatch"


SafeDetail = int | str | bool | None


class ExactSimulationError(RuntimeError):
    """Typed error whose diagnostics intentionally exclude raw provider data."""

    def __init__(
        self,
        code: ExactSimulationErrorCode,
        disposition: FailureDisposition,
        message: str,
        details: dict[str, SafeDetail] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.disposition = disposition
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class ExactSimulationPolicy:
    """Bounded policy for the provisional and final simulation passes."""

    commitment: str = "confirmed"
    provisional_compute_unit_limit: int = 1_400_000
    compute_margin_bps: int = 12_000
    min_final_compute_unit_limit: int = 1
    max_final_compute_unit_limit: int = 1_400_000
    max_wire_bytes: int = SOLANA_WIRE_TRANSACTION_LIMIT_BYTES
    max_transaction_accounts: int = 64
    max_return_accounts: int = 20
    max_loaded_accounts_data_size: int = 64 * 1024 * 1024
    max_log_bytes: int = 256 * 1024
    rpc_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.commitment not in {"processed", "confirmed", "finalized"}:
            raise ValueError("unsupported commitment")
        if not 1 <= self.provisional_compute_unit_limit <= 1_400_000:
            raise ValueError("provisional compute unit limit out of range")
        if not 10_000 <= self.compute_margin_bps <= 20_000:
            raise ValueError("compute margin must be between 1.0x and 2.0x")
        if not 1 <= self.min_final_compute_unit_limit:
            raise ValueError("minimum final compute unit limit must be positive")
        if not (
            self.min_final_compute_unit_limit
            <= self.max_final_compute_unit_limit
            <= 1_400_000
        ):
            raise ValueError("final compute unit bounds are invalid")
        if not 1 <= self.max_wire_bytes <= SOLANA_WIRE_TRANSACTION_LIMIT_BYTES:
            raise ValueError("wire byte limit is invalid")
        if not 1 <= self.max_transaction_accounts <= 256:
            raise ValueError("transaction account limit is invalid")
        if not 1 <= self.max_return_accounts <= 20:
            raise ValueError("returned account limit is invalid")
        if self.max_loaded_accounts_data_size <= 0:
            raise ValueError("loaded account byte limit must be positive")
        if self.max_log_bytes <= 0:
            raise ValueError("log byte limit must be positive")
        if self.rpc_timeout_seconds <= 0:
            raise ValueError("RPC timeout must be positive")


@dataclass(frozen=True, slots=True)
class RpcSimulationEvidence:
    """Deterministic evidence from one exact-message RPC simulation."""

    message_hash: str
    response_hash: str
    logs_hash: str
    slot: int
    units_consumed: int
    loaded_accounts_data_size: int | None
    returned_account_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExactSimulationReport:
    """Evidence binding both simulation passes and the final fee quote."""

    provisional: RpcSimulationEvidence
    final: RpcSimulationEvidence
    final_compute_unit_limit: int
    final_compute_unit_price: int | None
    final_fee_lamports: int
    fee_context_slot: int
    commitment: str
    min_context_slot: int
    last_valid_block_height: int
    monitored_accounts: tuple[str, ...]

    @property
    def message_hash(self) -> str:
        return self.final.message_hash

    def validate_message_bytes(self, serialized_message: bytes) -> None:
        candidate = compute_message_hash(serialized_message)
        if candidate != self.message_hash:
            raise ExactSimulationError(
                ExactSimulationErrorCode.MESSAGE_IDENTITY_MISMATCH,
                FailureDisposition.FATAL,
                "serialized message no longer matches final simulation",
            )

    def validate_binding(
        self,
        *,
        permit_message_hash: str,
        submission_message_hash: str,
    ) -> None:
        for label, candidate in (
            ("permit", permit_message_hash),
            ("submission", submission_message_hash),
        ):
            if candidate != self.message_hash:
                raise ExactSimulationError(
                    ExactSimulationErrorCode.MESSAGE_IDENTITY_MISMATCH,
                    FailureDisposition.FATAL,
                    f"{label} hash does not match final simulation",
                )


@dataclass(frozen=True, slots=True)
class FinalizedSimulation:
    """The only compiled transaction eligible for a later permit/submission."""

    compiled: CompiledTransaction
    report: ExactSimulationReport

    def validate_submission(
        self,
        *,
        permit_message_hash: str,
        submission_message_hash: str,
        serialized_submission_message: bytes | None = None,
    ) -> None:
        validate_compiled_identity(self.compiled)
        self.report.validate_message_bytes(self.compiled.serialized_message)
        self.report.validate_binding(
            permit_message_hash=permit_message_hash,
            submission_message_hash=submission_message_hash,
        )
        if serialized_submission_message is not None:
            self.report.validate_message_bytes(serialized_submission_message)


class ExactSimulationFinalizer:
    """Compile, simulate, resize CU, rebuild, re-simulate, and quote fee."""

    def __init__(
        self,
        rpc: RpcClient,
        *,
        compiler: CanonicalTransactionCompiler | None = None,
        policy: ExactSimulationPolicy | None = None,
    ) -> None:
        self.rpc = rpc
        self.compiler = compiler or CanonicalTransactionCompiler()
        self.policy = policy or ExactSimulationPolicy()

    async def finalize(
        self,
        plan: TransactionPlan,
        blockhash: BlockhashContext,
        lookup_tables: tuple[ResolvedAddressLookupTable, ...] = (),
    ) -> FinalizedSimulation:
        self._validate_context(plan, blockhash)
        monitored = self._targeted_accounts(plan)

        await self._ensure_blockhash_live(blockhash, plan.min_context_slot)
        provisional_plan = self._with_unit_limit(
            plan,
            self.policy.provisional_compute_unit_limit,
        )
        provisional_compiled = self._compile(
            provisional_plan,
            blockhash,
            lookup_tables,
        )
        provisional = await self._simulate(
            provisional_compiled,
            monitored,
            compute_limit=self.policy.provisional_compute_unit_limit,
        )

        final_limit = self._final_compute_limit(provisional.units_consumed)
        final_plan = self._with_unit_limit(plan, final_limit)

        await self._ensure_blockhash_live(blockhash, plan.min_context_slot)
        final_compiled = self._compile(final_plan, blockhash, lookup_tables)
        final = await self._simulate(
            final_compiled,
            monitored,
            compute_limit=final_limit,
        )
        fee_lamports, fee_slot = await self._get_fee(final_compiled)

        report = ExactSimulationReport(
            provisional=provisional,
            final=final,
            final_compute_unit_limit=final_limit,
            final_compute_unit_price=(
                final_plan.compute_budget_policy.micro_lamports_per_cu
            ),
            final_fee_lamports=fee_lamports,
            fee_context_slot=fee_slot,
            commitment=self.policy.commitment,
            min_context_slot=final_compiled.min_context_slot,
            last_valid_block_height=blockhash.last_valid_block_height,
            monitored_accounts=monitored,
        )
        result = FinalizedSimulation(final_compiled, report)
        result.validate_submission(
            permit_message_hash=final_compiled.message_hash,
            submission_message_hash=final_compiled.message_hash,
        )
        return result

    def _validate_context(
        self,
        plan: TransactionPlan,
        blockhash: BlockhashContext,
    ) -> None:
        if blockhash.commitment != self.policy.commitment:
            raise ExactSimulationError(
                ExactSimulationErrorCode.INVALID_CONTEXT,
                FailureDisposition.FATAL,
                "blockhash and simulation commitments must match",
                {
                    "blockhash_commitment": blockhash.commitment,
                    "simulation_commitment": self.policy.commitment,
                },
            )
        if plan.min_context_slot < 0:
            raise ExactSimulationError(
                ExactSimulationErrorCode.INVALID_CONTEXT,
                FailureDisposition.FATAL,
                "minContextSlot must be non-negative",
            )
        try:
            blockhash.validate()
        except ValueError as exc:
            raise ExactSimulationError(
                ExactSimulationErrorCode.INVALID_CONTEXT,
                FailureDisposition.FATAL,
                "invalid blockhash context",
            ) from exc

    def _targeted_accounts(self, plan: TransactionPlan) -> tuple[str, ...]:
        monitored = tuple(
            dict.fromkeys(
                (
                    str(plan.payer),
                    *(str(address) for address in plan.monitored_accounts),
                )
            )
        )
        if len(monitored) > self.policy.max_return_accounts:
            raise ExactSimulationError(
                ExactSimulationErrorCode.ACCOUNT_LIMIT_EXCEEDED,
                FailureDisposition.FATAL,
                "targeted simulation account limit exceeded",
                {
                    "actual": len(monitored),
                    "limit": self.policy.max_return_accounts,
                },
            )
        return monitored

    def _with_unit_limit(
        self,
        plan: TransactionPlan,
        unit_limit: int,
    ) -> TransactionPlan:
        compute = replace(plan.compute_budget_policy, unit_limit=unit_limit)
        return replace(plan, compute_budget_policy=compute)

    def _compile(
        self,
        plan: TransactionPlan,
        blockhash: BlockhashContext,
        lookup_tables: tuple[ResolvedAddressLookupTable, ...],
    ) -> CompiledTransaction:
        try:
            compiled = self.compiler.compile(plan, blockhash, lookup_tables)
            validate_compiled_identity(compiled)
        except (CanonicalExecutionContractError, TypeError, ValueError) as exc:
            raise ExactSimulationError(
                ExactSimulationErrorCode.COMPILATION_FAILED,
                FailureDisposition.FATAL,
                "canonical transaction compilation failed",
                {"exception_type": type(exc).__name__},
            ) from exc
        if compiled.diagnostics.wire_size > self.policy.max_wire_bytes:
            raise ExactSimulationError(
                ExactSimulationErrorCode.WIRE_SIZE_EXCEEDED,
                FailureDisposition.FATAL,
                "compiled transaction exceeds configured wire limit",
                {
                    "actual": compiled.diagnostics.wire_size,
                    "limit": self.policy.max_wire_bytes,
                },
            )
        if (
            compiled.diagnostics.total_resolved_account_count
            > self.policy.max_transaction_accounts
        ):
            raise ExactSimulationError(
                ExactSimulationErrorCode.ACCOUNT_LIMIT_EXCEEDED,
                FailureDisposition.FATAL,
                "compiled transaction account limit exceeded",
                {
                    "actual": compiled.diagnostics.total_resolved_account_count,
                    "limit": self.policy.max_transaction_accounts,
                },
            )
        return compiled

    async def _ensure_blockhash_live(
        self,
        blockhash: BlockhashContext,
        min_context_slot: int,
    ) -> None:
        raw = await self._rpc_call(
            "getBlockHeight",
            [
                {
                    "commitment": self.policy.commitment,
                    "minContextSlot": min_context_slot,
                }
            ],
        )
        value = self._unwrap_rpc_result(raw)
        if isinstance(value, dict) and "value" in value:
            value = value["value"]
        if not _is_int(value) or value < 0:
            raise ExactSimulationError(
                ExactSimulationErrorCode.MALFORMED_RPC_RESPONSE,
                FailureDisposition.RETRYABLE,
                "getBlockHeight returned an invalid value",
            )
        if value > blockhash.last_valid_block_height:
            raise ExactSimulationError(
                ExactSimulationErrorCode.BLOCKHASH_EXPIRED,
                FailureDisposition.RETRYABLE,
                "recent blockhash is expired",
                {
                    "current_block_height": value,
                    "last_valid_block_height": blockhash.last_valid_block_height,
                },
            )

    async def _simulate(
        self,
        compiled: CompiledTransaction,
        monitored: tuple[str, ...],
        *,
        compute_limit: int,
    ) -> RpcSimulationEvidence:
        config: dict[str, Any] = {
            "encoding": "base64",
            "commitment": self.policy.commitment,
            "sigVerify": False,
            "replaceRecentBlockhash": False,
            "innerInstructions": True,
            "minContextSlot": compiled.min_context_slot,
            "accounts": {
                "encoding": "base64",
                "addresses": list(monitored),
            },
        }
        encoded = base64.b64encode(compiled.serialized_transaction).decode("ascii")
        raw = await self._rpc_call("simulateTransaction", [encoded, config])
        result = self._unwrap_rpc_result(raw)
        result_dict = self._require_dict(result, "simulateTransaction result")
        context = self._require_dict(
            result_dict.get("context"),
            "simulateTransaction context",
        )
        value = self._require_dict(
            result_dict.get("value"),
            "simulateTransaction value",
        )
        slot = context.get("slot")
        if not _is_int(slot) or slot < compiled.min_context_slot:
            raise ExactSimulationError(
                ExactSimulationErrorCode.CONTEXT_SLOT_VIOLATION,
                FailureDisposition.RETRYABLE,
                "simulation context slot is below minContextSlot",
                {
                    "slot": slot if _is_int(slot) else None,
                    "min_context_slot": compiled.min_context_slot,
                },
            )
        if value.get("replacementBlockhash") is not None:
            raise ExactSimulationError(
                ExactSimulationErrorCode.MESSAGE_IDENTITY_MISMATCH,
                FailureDisposition.FATAL,
                "RPC replaced the blockhash for an exact-message simulation",
            )

        error = value.get("err")
        if error is not None:
            code, disposition = _classify_provider_error(error)
            raise ExactSimulationError(
                code,
                disposition,
                "simulation rejected the exact message",
            )

        units = value.get("unitsConsumed")
        if not _is_int(units) or units <= 0:
            raise ExactSimulationError(
                ExactSimulationErrorCode.MALFORMED_RPC_RESPONSE,
                FailureDisposition.RETRYABLE,
                "successful simulation omitted unitsConsumed",
            )
        if units > compute_limit:
            raise ExactSimulationError(
                ExactSimulationErrorCode.COMPUTE_LIMIT_EXCEEDED,
                FailureDisposition.FATAL,
                "simulation consumed more units than the compiled limit",
                {"consumed": units, "limit": compute_limit},
            )

        loaded_size = value.get("loadedAccountsDataSize")
        if loaded_size is not None and (not _is_int(loaded_size) or loaded_size < 0):
            raise ExactSimulationError(
                ExactSimulationErrorCode.MALFORMED_RPC_RESPONSE,
                FailureDisposition.RETRYABLE,
                "loadedAccountsDataSize is invalid",
            )
        if (
            _is_int(loaded_size)
            and loaded_size > self.policy.max_loaded_accounts_data_size
        ):
            raise ExactSimulationError(
                ExactSimulationErrorCode.LOADED_ACCOUNT_BYTES_EXCEEDED,
                FailureDisposition.FATAL,
                "loaded account data byte limit exceeded",
                {
                    "actual": loaded_size,
                    "limit": self.policy.max_loaded_accounts_data_size,
                },
            )

        logs_value = value.get("logs")
        if logs_value is None:
            logs: tuple[str, ...] = ()
        elif isinstance(logs_value, list) and all(
            isinstance(line, str) for line in logs_value
        ):
            logs = tuple(logs_value)
        else:
            raise ExactSimulationError(
                ExactSimulationErrorCode.MALFORMED_RPC_RESPONSE,
                FailureDisposition.RETRYABLE,
                "simulation logs are malformed",
            )
        if sum(len(line.encode("utf-8")) for line in logs) > self.policy.max_log_bytes:
            raise ExactSimulationError(
                ExactSimulationErrorCode.LOADED_ACCOUNT_BYTES_EXCEEDED,
                FailureDisposition.FATAL,
                "simulation log byte limit exceeded",
            )

        accounts_value = value.get("accounts")
        if not isinstance(accounts_value, list) or len(accounts_value) != len(
            monitored
        ):
            raise ExactSimulationError(
                ExactSimulationErrorCode.ACCOUNT_LIMIT_EXCEEDED,
                FailureDisposition.RETRYABLE,
                "RPC did not return exactly the targeted account snapshots",
                {
                    "actual": (
                        len(accounts_value) if isinstance(accounts_value, list) else -1
                    ),
                    "expected": len(monitored),
                },
            )

        return RpcSimulationEvidence(
            message_hash=compiled.message_hash,
            response_hash=_hash_json(result_dict),
            logs_hash=_hash_json(logs),
            slot=slot,
            units_consumed=units,
            loaded_accounts_data_size=(loaded_size if _is_int(loaded_size) else None),
            returned_account_hashes=tuple(
                _hash_json(account) for account in accounts_value
            ),
        )

    async def _get_fee(self, compiled: CompiledTransaction) -> tuple[int, int]:
        encoded = base64.b64encode(compiled.serialized_message).decode("ascii")
        raw = await self._rpc_call(
            "getFeeForMessage",
            [
                encoded,
                {
                    "commitment": self.policy.commitment,
                    "minContextSlot": compiled.min_context_slot,
                },
            ],
        )
        result = self._unwrap_rpc_result(raw)
        result_dict = self._require_dict(result, "getFeeForMessage result")
        context = self._require_dict(
            result_dict.get("context"),
            "getFeeForMessage context",
        )
        slot = context.get("slot")
        if not _is_int(slot) or slot < compiled.min_context_slot:
            raise ExactSimulationError(
                ExactSimulationErrorCode.CONTEXT_SLOT_VIOLATION,
                FailureDisposition.RETRYABLE,
                "fee context slot is below minContextSlot",
            )
        value = result_dict.get("value")
        if value is None:
            raise ExactSimulationError(
                ExactSimulationErrorCode.FEE_UNAVAILABLE,
                FailureDisposition.RETRYABLE,
                "fee is unavailable for the final message blockhash",
            )
        if not _is_int(value) or value < 0:
            raise ExactSimulationError(
                ExactSimulationErrorCode.MALFORMED_RPC_RESPONSE,
                FailureDisposition.RETRYABLE,
                "getFeeForMessage returned an invalid fee",
            )
        return value, slot

    async def _rpc_call(self, method: str, params: list[Any]) -> Any:
        try:
            return await asyncio.wait_for(
                self.rpc.call(method, params),
                timeout=self.policy.rpc_timeout_seconds,
            )
        except TimeoutError as exc:
            raise ExactSimulationError(
                ExactSimulationErrorCode.RPC_TIMEOUT,
                FailureDisposition.RETRYABLE,
                f"{method} timed out",
            ) from exc
        except ExactSimulationError:
            raise
        except Exception as exc:
            raise ExactSimulationError(
                ExactSimulationErrorCode.RPC_ERROR,
                FailureDisposition.RETRYABLE,
                f"{method} failed",
                {"exception_type": type(exc).__name__},
            ) from exc

    def _unwrap_rpc_result(self, raw: Any) -> Any:
        if isinstance(raw, dict) and raw.get("error") is not None:
            code, disposition = _classify_provider_error(raw["error"])
            raise ExactSimulationError(code, disposition, "RPC returned an error")
        if isinstance(raw, dict) and "result" in raw:
            return raw["result"]
        return raw

    def _require_dict(self, value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ExactSimulationError(
                ExactSimulationErrorCode.MALFORMED_RPC_RESPONSE,
                FailureDisposition.RETRYABLE,
                f"{label} must be an object",
            )
        return value

    def _final_compute_limit(self, units_consumed: int) -> int:
        if units_consumed > self.policy.max_final_compute_unit_limit:
            raise ExactSimulationError(
                ExactSimulationErrorCode.COMPUTE_LIMIT_EXCEEDED,
                FailureDisposition.FATAL,
                "provisional simulation exceeds the final CU cap",
                {
                    "consumed": units_consumed,
                    "limit": self.policy.max_final_compute_unit_limit,
                },
            )
        scaled = (units_consumed * self.policy.compute_margin_bps + 9_999) // 10_000
        bounded = max(self.policy.min_final_compute_unit_limit, scaled)
        return min(bounded, self.policy.max_final_compute_unit_limit)


def validate_exact_submission_binding(
    finalized: FinalizedSimulation,
    *,
    permit_message_hash: str,
    submission_message_hash: str,
    serialized_submission_message: bytes | None = None,
) -> None:
    """Public integration hook for PR-035 permit and sender boundaries."""

    finalized.validate_submission(
        permit_message_hash=permit_message_hash,
        submission_message_hash=submission_message_hash,
        serialized_submission_message=serialized_submission_message,
    )


def _classify_provider_error(
    error: Any,
) -> tuple[ExactSimulationErrorCode, FailureDisposition]:
    text = _error_text(error)
    retryable_tokens = (
        "blockhashnotfound",
        "blockhash not found",
        "block height exceeded",
        "min context slot",
        "node is behind",
        "account in use",
        "too many requests",
        "temporarily unavailable",
        "timeout",
        "429",
    )
    if any(token in text for token in retryable_tokens):
        code = (
            ExactSimulationErrorCode.BLOCKHASH_EXPIRED
            if "blockhash" in text or "block height" in text
            else ExactSimulationErrorCode.RPC_ERROR
        )
        return code, FailureDisposition.RETRYABLE
    return ExactSimulationErrorCode.SIMULATION_FAILED, FailureDisposition.FATAL


def _error_text(error: Any) -> str:
    try:
        return json.dumps(
            error,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).lower()
    except (TypeError, ValueError):
        return type(error).__name__.lower()


def _hash_json(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExactSimulationError(
            ExactSimulationErrorCode.MALFORMED_RPC_RESPONSE,
            FailureDisposition.RETRYABLE,
            "RPC evidence is not canonical JSON",
        ) from exc
    return hashlib.sha256(payload).hexdigest()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = [
    "ExactSimulationError",
    "ExactSimulationErrorCode",
    "ExactSimulationFinalizer",
    "ExactSimulationPolicy",
    "ExactSimulationReport",
    "FailureDisposition",
    "FinalizedSimulation",
    "RpcSimulationEvidence",
    "validate_exact_submission_binding",
]
