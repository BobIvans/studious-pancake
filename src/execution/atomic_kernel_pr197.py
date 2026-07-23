"""Roadmap PR-197 sender-free atomic execution and economic kernel.

This module binds rooted state, provider build evidence, instruction order,
blockhash freshness, ALT identities, final message identity, simulation evidence
and integer-only economics into one immutable sender-free report.  It never
imports signer, sender, Jito submit or RPC transport code.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "pr197.atomic-execution-kernel.v1"
RESULT_SCHEMA_VERSION = "pr197.atomic-execution-kernel-result.v1"
SOLANA_WIRE_TRANSACTION_LIMIT_BYTES = 1232
_U128_MAX = 2**128 - 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")


class AtomicKernelError(ValueError):
    """Raised when PR-197 sender-free kernel evidence is malformed."""


class AtomicKernelStatus(StrEnum):
    """Stable PR-197 admission states; none imply sending or signing."""

    READY_SENDER_FREE = "ready_sender_free"
    STRUCTURE_REJECTED = "structure_rejected"
    FRESHNESS_REJECTED = "freshness_rejected"
    SIMULATION_REJECTED = "simulation_rejected"
    ECONOMICS_REJECTED = "economics_rejected"
    IDENTITY_REJECTED = "identity_rejected"


@dataclass(frozen=True, slots=True)
class KernelDiagnostic:
    code: str
    message: str
    status: AtomicKernelStatus

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "status": self.status.value,
        }


def _require_safe_id(value: object, field: str) -> str:
    text = str(value)
    if not _SAFE_ID_RE.fullmatch(text):
        raise AtomicKernelError(f"{field} must be a bounded stable identifier")
    return text


def _require_sha256(value: object, field: str) -> str:
    digest = str(value).lower()
    if not _SHA256_RE.fullmatch(digest) or digest == "0" * 64:
        raise AtomicKernelError(f"{field} must be a non-placeholder sha256")
    return digest


def _require_int(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AtomicKernelError(f"{field} must be an integer")
    if value < minimum or value > _U128_MAX:
        raise AtomicKernelError(f"{field} outside allowed integer range")
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise AtomicKernelError("canonical object keys must be strings")
            converted[key] = _jsonable(item)
        return converted
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, float):
        raise AtomicKernelError("floating point values are forbidden in PR-197")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise AtomicKernelError(f"unsupported canonical value: {type(value).__name__}")


def stable_json(payload: Any) -> str:
    return json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_payload(payload: Any) -> str:
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExternalStateBinding:
    """Rooted/provider evidence that must stay bound to the final message."""

    state_snapshot_hash: str
    provider_response_hash: str
    route_plan_hash: str
    marginfi_identity_hash: str
    quote_slot: int
    market_state_slot: int
    oracle_slot: int
    provider_received_at_unix_ns: int

    def __post_init__(self) -> None:
        for field in (
            "state_snapshot_hash",
            "provider_response_hash",
            "route_plan_hash",
            "marginfi_identity_hash",
        ):
            object.__setattr__(
                self,
                field,
                _require_sha256(getattr(self, field), field),
            )
        for field in (
            "quote_slot",
            "market_state_slot",
            "oracle_slot",
            "provider_received_at_unix_ns",
        ):
            _require_int(getattr(self, field), field=field)

    @property
    def min_context_slot(self) -> int:
        return max(self.quote_slot, self.market_state_slot, self.oracle_slot)


@dataclass(frozen=True, slots=True)
class InstructionSequenceBinding:
    """Semantic instruction roles without exposing signer or sender authority."""

    instruction_roles: tuple[str, ...]
    instruction_programs_hash: str
    instruction_accounts_hash: str
    instruction_data_hash: str

    def __post_init__(self) -> None:
        if not self.instruction_roles:
            raise AtomicKernelError("instruction_roles must not be empty")
        object.__setattr__(
            self,
            "instruction_roles",
            tuple(_require_safe_id(role, "instruction_role") for role in self.instruction_roles),
        )
        for field in (
            "instruction_programs_hash",
            "instruction_accounts_hash",
            "instruction_data_hash",
        ):
            object.__setattr__(
                self,
                field,
                _require_sha256(getattr(self, field), field),
            )

    def diagnostics(self) -> tuple[KernelDiagnostic, ...]:
        diagnostics: list[KernelDiagnostic] = []
        roles = self.instruction_roles
        forbidden = {
            "provider.compute_budget",
            "provider.tip",
            "provider.jito_tip",
            "sender.submit",
            "signer.sign",
        }
        for role in sorted(forbidden & set(roles)):
            diagnostics.append(
                KernelDiagnostic(
                    "FORBIDDEN_INSTRUCTION_ROLE",
                    f"provider/sender-owned role {role!r} is forbidden",
                    AtomicKernelStatus.STRUCTURE_REJECTED,
                )
            )
        ordered_roles = (
            "marginfi.begin",
            "marginfi.borrow",
            "jupiter.leg_a",
            "jupiter.leg_b",
            "marginfi.repay",
            "marginfi.end",
        )
        indexes: dict[str, int] = {}
        for required in ordered_roles:
            if required not in roles:
                diagnostics.append(
                    KernelDiagnostic(
                        "MISSING_INSTRUCTION_ROLE",
                        f"missing required role {required!r}",
                        AtomicKernelStatus.STRUCTURE_REJECTED,
                    )
                )
            else:
                indexes[required] = roles.index(required)
        if len(indexes) == len(ordered_roles):
            values = [indexes[role] for role in ordered_roles]
            if values != sorted(values):
                diagnostics.append(
                    KernelDiagnostic(
                        "INSTRUCTION_ORDER_REJECTED",
                        "MarginFi bracket and Jupiter legs are not in canonical order",
                        AtomicKernelStatus.STRUCTURE_REJECTED,
                    )
                )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class BlockhashBinding:
    blockhash: str
    source_slot: int
    last_valid_block_height: int
    fetched_at_unix_ns: int
    commitment: str = "confirmed"

    def __post_init__(self) -> None:
        _require_safe_id(self.blockhash, "blockhash")
        _require_safe_id(self.commitment, "commitment")
        _require_int(self.source_slot, field="source_slot")
        _require_int(
            self.last_valid_block_height,
            field="last_valid_block_height",
        )
        _require_int(self.fetched_at_unix_ns, field="fetched_at_unix_ns")


@dataclass(frozen=True, slots=True)
class AddressLookupTableBinding:
    address: str
    account_hash: str
    addresses_hash: str
    source_slot: int
    deactivation_slot: int | None = None

    def __post_init__(self) -> None:
        _require_safe_id(self.address, "address")
        object.__setattr__(
            self,
            "account_hash",
            _require_sha256(self.account_hash, "account_hash"),
        )
        object.__setattr__(
            self,
            "addresses_hash",
            _require_sha256(self.addresses_hash, "addresses_hash"),
        )
        _require_int(self.source_slot, field="source_slot")
        if self.deactivation_slot is not None:
            _require_int(self.deactivation_slot, field="deactivation_slot")


@dataclass(frozen=True, slots=True)
class FinalMessageBinding:
    message_hash: str
    wire_size_bytes: int
    required_signers_hash: str
    static_account_count: int
    lookup_account_count: int
    compiled_at_unix_ns: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "message_hash",
            _require_sha256(self.message_hash, "message_hash"),
        )
        object.__setattr__(
            self,
            "required_signers_hash",
            _require_sha256(self.required_signers_hash, "required_signers_hash"),
        )
        _require_int(self.wire_size_bytes, field="wire_size_bytes", minimum=1)
        _require_int(self.static_account_count, field="static_account_count")
        _require_int(self.lookup_account_count, field="lookup_account_count")
        _require_int(self.compiled_at_unix_ns, field="compiled_at_unix_ns")


@dataclass(frozen=True, slots=True)
class SimulationBinding:
    transaction_message_hash: str
    simulation_slot: int
    min_context_slot: int
    success: bool
    logs_hash: str
    units_consumed: int | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "transaction_message_hash",
            _require_sha256(
                self.transaction_message_hash,
                "transaction_message_hash",
            ),
        )
        object.__setattr__(
            self,
            "logs_hash",
            _require_sha256(self.logs_hash, "logs_hash"),
        )
        _require_int(self.simulation_slot, field="simulation_slot")
        _require_int(self.min_context_slot, field="min_context_slot")
        if not isinstance(self.success, bool):
            raise AtomicKernelError("success must be boolean")
        if self.units_consumed is not None:
            _require_int(self.units_consumed, field="units_consumed")
        if self.error_code is not None:
            _require_safe_id(self.error_code, "error_code")


@dataclass(frozen=True, slots=True)
class IntegerEconomics:
    """Integer-only conservative economics for the exact final message."""

    principal_lamports: int
    repayment_lamports: int
    flash_fee_lamports: int
    expected_output_lamports: int
    base_network_fee_lamports: int
    priority_fee_lamports: int
    jito_tip_lamports: int
    ata_rent_peak_lamports: int
    token2022_transfer_fee_lamports: int
    contingency_lamports: int
    protected_reserve_lamports: int
    wallet_lamports: int
    minimum_profit_lamports: int

    def __post_init__(self) -> None:
        for field in fields(self):
            minimum = 1 if field.name in {"principal_lamports"} else 0
            _require_int(getattr(self, field.name), field=field.name, minimum=minimum)
        if self.repayment_lamports < self.principal_lamports:
            raise AtomicKernelError("repayment must cover principal")
        if self.flash_fee_lamports > self.repayment_lamports:
            raise AtomicKernelError("flash fee cannot exceed repayment")

    @property
    def native_cost_lamports(self) -> int:
        return (
            self.base_network_fee_lamports
            + self.priority_fee_lamports
            + self.jito_tip_lamports
            + self.ata_rent_peak_lamports
            + self.contingency_lamports
        )

    @property
    def total_required_output_lamports(self) -> int:
        return (
            self.repayment_lamports
            + self.base_network_fee_lamports
            + self.priority_fee_lamports
            + self.jito_tip_lamports
            + self.token2022_transfer_fee_lamports
            + self.minimum_profit_lamports
        )

    @property
    def conservative_profit_lamports(self) -> int:
        return self.expected_output_lamports - (
            self.repayment_lamports
            + self.base_network_fee_lamports
            + self.priority_fee_lamports
            + self.jito_tip_lamports
            + self.token2022_transfer_fee_lamports
        )

    def diagnostics(self) -> tuple[KernelDiagnostic, ...]:
        diagnostics: list[KernelDiagnostic] = []
        if self.expected_output_lamports < self.total_required_output_lamports:
            diagnostics.append(
                KernelDiagnostic(
                    "INSUFFICIENT_CONSERVATIVE_OUTPUT",
                    "final output does not cover repayment, costs and profit",
                    AtomicKernelStatus.ECONOMICS_REJECTED,
                )
            )
        if self.wallet_lamports < (
            self.native_cost_lamports + self.protected_reserve_lamports
        ):
            diagnostics.append(
                KernelDiagnostic(
                    "INSUFFICIENT_WALLET_RESERVE",
                    "wallet cannot pay native costs while preserving reserve",
                    AtomicKernelStatus.ECONOMICS_REJECTED,
                )
            )
        return tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class ExecutionBinding:
    attempt_id: str
    plan_hash: str
    compiler_version: str
    config_generation_hash: str
    policy_bundle_hash: str
    external_state: ExternalStateBinding
    instruction_sequence: InstructionSequenceBinding
    blockhash: BlockhashBinding
    final_message: FinalMessageBinding
    economics: IntegerEconomics
    alt_bindings: tuple[AddressLookupTableBinding, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_safe_id(self.attempt_id, "attempt_id")
        _require_safe_id(self.compiler_version, "compiler_version")
        for field in (
            "plan_hash",
            "config_generation_hash",
            "policy_bundle_hash",
        ):
            object.__setattr__(
                self,
                field,
                _require_sha256(getattr(self, field), field),
            )
        if self.schema_version != SCHEMA_VERSION:
            raise AtomicKernelError("unsupported PR-197 schema version")
        object.__setattr__(self, "alt_bindings", tuple(self.alt_bindings))

    @property
    def min_context_slot(self) -> int:
        return self.external_state.min_context_slot

    @property
    def binding_hash(self) -> str:
        return sha256_payload(self)


@dataclass(frozen=True, slots=True)
class AtomicKernelReport:
    schema_version: str
    status: AtomicKernelStatus
    binding_hash: str
    final_message_hash: str
    min_context_slot: int
    diagnostics: tuple[KernelDiagnostic, ...]
    signed: bool = False
    submitted: bool = False
    live_enabled: bool = False

    @property
    def ok(self) -> bool:
        return self.status is AtomicKernelStatus.READY_SENDER_FREE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "status": self.status.value,
            "binding_hash": self.binding_hash,
            "final_message_hash": self.final_message_hash,
            "min_context_slot": self.min_context_slot,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "signed": self.signed,
            "submitted": self.submitted,
            "live_enabled": self.live_enabled,
        }


def evaluate_atomic_sender_free_kernel(
    binding: ExecutionBinding,
    simulation: SimulationBinding,
) -> AtomicKernelReport:
    diagnostics: list[KernelDiagnostic] = []
    diagnostics.extend(binding.instruction_sequence.diagnostics())
    diagnostics.extend(binding.economics.diagnostics())

    if binding.final_message.wire_size_bytes > SOLANA_WIRE_TRANSACTION_LIMIT_BYTES:
        diagnostics.append(
            KernelDiagnostic(
                "WIRE_SIZE_LIMIT_EXCEEDED",
                "final v0 transaction wire size exceeds Solana packet limit",
                AtomicKernelStatus.STRUCTURE_REJECTED,
            )
        )
    if binding.blockhash.source_slot < binding.min_context_slot:
        diagnostics.append(
            KernelDiagnostic(
                "BLOCKHASH_BEFORE_EXECUTION_CONTEXT",
                "blockhash source slot is older than execution minContextSlot",
                AtomicKernelStatus.FRESHNESS_REJECTED,
            )
        )
    for alt in binding.alt_bindings:
        if alt.source_slot < binding.min_context_slot:
            diagnostics.append(
                KernelDiagnostic(
                    "ALT_BEFORE_EXECUTION_CONTEXT",
                    f"ALT {alt.address} is older than execution minContextSlot",
                    AtomicKernelStatus.FRESHNESS_REJECTED,
                )
            )
        if alt.deactivation_slot is not None and alt.deactivation_slot <= binding.min_context_slot:
            diagnostics.append(
                KernelDiagnostic(
                    "ALT_DEACTIVATED_AT_CONTEXT",
                    f"ALT {alt.address} is deactivated at execution context",
                    AtomicKernelStatus.FRESHNESS_REJECTED,
                )
            )
    if simulation.transaction_message_hash != binding.final_message.message_hash:
        diagnostics.append(
            KernelDiagnostic(
                "SIMULATION_MESSAGE_MISMATCH",
                "simulation evidence is not for the final compiled message",
                AtomicKernelStatus.IDENTITY_REJECTED,
            )
        )
    if simulation.min_context_slot != binding.min_context_slot:
        diagnostics.append(
            KernelDiagnostic(
                "SIMULATION_MIN_CONTEXT_MISMATCH",
                "simulation minContextSlot differs from execution binding",
                AtomicKernelStatus.IDENTITY_REJECTED,
            )
        )
    if simulation.simulation_slot < binding.min_context_slot:
        diagnostics.append(
            KernelDiagnostic(
                "SIMULATION_BEFORE_EXECUTION_CONTEXT",
                "simulation slot does not cover execution minContextSlot",
                AtomicKernelStatus.FRESHNESS_REJECTED,
            )
        )
    if not simulation.success:
        reason = simulation.error_code or "unknown"
        diagnostics.append(
            KernelDiagnostic(
                "FINAL_MESSAGE_SIMULATION_FAILED",
                f"final message simulation failed: {reason}",
                AtomicKernelStatus.SIMULATION_REJECTED,
            )
        )

    status = AtomicKernelStatus.READY_SENDER_FREE
    if diagnostics:
        status = diagnostics[0].status
    return AtomicKernelReport(
        schema_version=RESULT_SCHEMA_VERSION,
        status=status,
        binding_hash=binding.binding_hash,
        final_message_hash=binding.final_message.message_hash,
        min_context_slot=binding.min_context_slot,
        diagnostics=tuple(diagnostics),
        signed=False,
        submitted=False,
        live_enabled=False,
    )


__all__ = [
    "AddressLookupTableBinding",
    "AtomicKernelError",
    "AtomicKernelReport",
    "AtomicKernelStatus",
    "BlockhashBinding",
    "ExecutionBinding",
    "ExternalStateBinding",
    "FinalMessageBinding",
    "InstructionSequenceBinding",
    "IntegerEconomics",
    "KernelDiagnostic",
    "RESULT_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "SimulationBinding",
    "evaluate_atomic_sender_free_kernel",
    "sha256_payload",
    "stable_json",
]
