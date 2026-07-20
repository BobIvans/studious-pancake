"""PR-075 atomic vertical runtime stage adapter.

This module connects the PR-058 sender-free atomic vertical to the durable
``PaperShadowRunner`` stage contract without enabling a sender.  It is a narrow
composition layer: callers must supply a verified candidate adapter and an
already-constructed atomic vertical.  Missing provider/capital/account evidence
therefore remains fail-closed instead of being fabricated from discovery data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Protocol, cast

from src.paper_shadow.atomic_vertical import (
    AtomicPlannerSimulationReconciliationVertical,
    AtomicVerticalCandidate,
    AtomicVerticalResult,
)
from src.paper_shadow.runner import (
    PaperShadowStage,
    PaperShadowStageContext,
    PaperShadowStageName,
)


class AtomicRuntimeStageErrorCode(StrEnum):
    """Fail-closed PR-075 runtime stage errors."""

    MISSING_RUNTIME_INPUTS = "pr075_missing_runtime_inputs"
    INVALID_PROVIDER_PIN = "pr075_invalid_provider_pin"
    WRONG_STAGE_ORDER = "pr075_wrong_stage_order"
    MESSAGE_HASH_DRIFT = "pr075_message_hash_drift"


class AtomicRuntimeStageError(RuntimeError):
    """Typed paper/shadow stage error with safe diagnostics only."""

    def __init__(
        self,
        code: AtomicRuntimeStageErrorCode,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class AtomicVerticalRuntimeInputs:
    """Evidence bundle required before PR-075 may run the atomic vertical.

    The adapter intentionally carries provenance pins separately from the
    ``AtomicVerticalCandidate``.  That makes it impossible for a plain detected
    opportunity to be silently treated as a verified MarginFi/Jupiter/capital
    lifecycle candidate.
    """

    candidate: AtomicVerticalCandidate
    marginfi_provider_pin: str
    jupiter_contract_pin: str
    capital_reservation_id: str
    account_evidence_hash: str
    durable_trace_id: str
    provider_pins: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.candidate is None:
            raise AtomicRuntimeStageError(
                AtomicRuntimeStageErrorCode.MISSING_RUNTIME_INPUTS,
                "atomic vertical candidate is required",
            )
        required_hashes = {
            "marginfi_provider_pin": self.marginfi_provider_pin,
            "jupiter_contract_pin": self.jupiter_contract_pin,
            "account_evidence_hash": self.account_evidence_hash,
        }
        for name, value in required_hashes.items():
            if not _is_sha256_hex(value):
                raise AtomicRuntimeStageError(
                    AtomicRuntimeStageErrorCode.INVALID_PROVIDER_PIN,
                    f"{name} must be a sha256 hex digest",
                    details={"field": name},
                )
        for name, value in self.provider_pins.items():
            if not _is_sha256_hex(value):
                raise AtomicRuntimeStageError(
                    AtomicRuntimeStageErrorCode.INVALID_PROVIDER_PIN,
                    "provider_pins values must be sha256 hex digests",
                    details={"field": f"provider_pins.{name}"},
                )
        object.__setattr__(self, "provider_pins", MappingProxyType(dict(self.provider_pins)))


class AtomicVerticalCandidateAdapter(Protocol):
    """Build one verified atomic vertical candidate for a runner opportunity."""

    def build(self, context: PaperShadowStageContext) -> AtomicVerticalRuntimeInputs: ...


@dataclass(frozen=True, slots=True)
class AtomicVerticalStageRecord:
    """Cached one-opportunity PR-075 result shared by stage handlers."""

    inputs: AtomicVerticalRuntimeInputs
    result: AtomicVerticalResult


class AtomicVerticalRuntimeStageSuite:
    """Expose PR-058 vertical output as runner planner/compiler/sim/reconcile stages.

    ``PaperShadowRunner`` keeps the durable journal and stage ordering.  This
    suite supplies the concrete handlers for the stages spanned by the atomic
    vertical.  It never imports or calls a sender and never returns truthy live
    submission fields.
    """

    def __init__(
        self,
        *,
        adapter: AtomicVerticalCandidateAdapter,
        vertical: AtomicPlannerSimulationReconciliationVertical,
    ) -> None:
        self.adapter = adapter
        self.vertical = vertical
        self._records: dict[str, AtomicVerticalStageRecord] = {}

    def stage_handlers(self) -> dict[PaperShadowStageName, PaperShadowStage]:
        """Return handlers that can be passed to ``PaperShadowRunner``."""

        return {
            PaperShadowStageName.CAPITAL_SIZING: self.capital_sizing_stage,
            PaperShadowStageName.PLANNER: self.planner_stage,
            PaperShadowStageName.COMPILER: self.compiler_stage,
            PaperShadowStageName.FINAL_SIMULATION: self.final_simulation_stage,
            PaperShadowStageName.RECONCILIATION: self.reconciliation_stage,
        }

    async def capital_sizing_stage(
        self, context: PaperShadowStageContext
    ) -> Mapping[str, Any]:
        record = await self._ensure_record(context)
        return {
            "schema_version": "pr075.atomic-runtime-stage.capital-sizing.v1",
            "capital_reservation_id": record.inputs.capital_reservation_id,
            "durable_trace_id": record.inputs.durable_trace_id,
            "account_evidence_hash": record.inputs.account_evidence_hash,
            "reservation_bound_to_atomic_candidate": True,
            "sender_imported": False,
            "live_mutation_allowed": False,
        }

    async def planner_stage(self, context: PaperShadowStageContext) -> Mapping[str, Any]:
        self._require_previous(context, PaperShadowStageName.CAPITAL_SIZING)
        record = await self._ensure_record(context)
        trace = record.result.trace
        return {
            "schema_version": "pr075.atomic-runtime-stage.planner.v1",
            "opportunity_id": trace.opportunity_id,
            "planner_digest": trace.planner_digest,
            "sequence_fingerprint": trace.sequence_fingerprint,
            "marginfi_provider_pin": record.inputs.marginfi_provider_pin,
            "jupiter_contract_pin": record.inputs.jupiter_contract_pin,
            "capital_reservation_id": record.inputs.capital_reservation_id,
            "durable_trace_id": record.inputs.durable_trace_id,
            "sender_imported": False,
            "live_mutation_allowed": False,
        }

    async def compiler_stage(self, context: PaperShadowStageContext) -> Mapping[str, Any]:
        self._require_previous(
            context,
            PaperShadowStageName.PLANNER,
        )
        record = await self._ensure_record(context)
        trace = record.result.trace
        compiled = record.result.finalized.compiled
        diagnostics = compiled.diagnostics
        return {
            "schema_version": "pr075.atomic-runtime-stage.compiler.v1",
            "message_hash": trace.message_hash,
            "compiled_message_hash": compiled.message_hash,
            "wire_size": diagnostics.wire_size,
            "static_account_count": diagnostics.static_account_count,
            "total_resolved_account_count": diagnostics.total_resolved_account_count,
            "lookup_table_count": len(compiled.lookup_tables),
            "sender_imported": False,
            "live_mutation_allowed": False,
        }

    async def final_simulation_stage(
        self, context: PaperShadowStageContext
    ) -> Mapping[str, Any]:
        planner_output = self._require_previous(context, PaperShadowStageName.PLANNER)
        compiler_output = self._require_previous(context, PaperShadowStageName.COMPILER)
        record = await self._ensure_record(context)
        trace = record.result.trace
        self._assert_same_hash(
            trace.message_hash,
            cast(str, compiler_output.get("message_hash")),
            "compiler",
        )
        self._assert_same_hash(
            trace.planner_digest,
            cast(str, planner_output.get("planner_digest")),
            "planner",
        )
        return {
            "schema_version": "pr075.atomic-runtime-stage.final-simulation.v1",
            "message_hash": trace.message_hash,
            "provisional_response_hash": trace.provisional_response_hash,
            "final_response_hash": trace.final_response_hash,
            "logs_hash": trace.logs_hash,
            "min_context_slot": trace.min_context_slot,
            "final_compute_unit_limit": trace.final_compute_unit_limit,
            "final_fee_lamports": trace.final_fee_lamports,
            "monitored_accounts": trace.monitored_accounts,
            "account_evidence_hash": record.inputs.account_evidence_hash,
            "sender_imported": False,
            "live_mutation_allowed": False,
        }

    async def reconciliation_stage(
        self, context: PaperShadowStageContext
    ) -> Mapping[str, Any]:
        self._require_previous(context, PaperShadowStageName.PLANNER)
        self._require_previous(context, PaperShadowStageName.COMPILER)
        final_output = self._require_previous(
            context,
            PaperShadowStageName.FINAL_SIMULATION,
        )
        record = await self._ensure_record(context)
        trace = record.result.trace
        self._assert_same_hash(
            trace.message_hash,
            cast(str, final_output.get("message_hash")),
            "final_simulation",
        )
        return {
            "schema_version": "pr075.atomic-runtime-stage.reconciliation.v1",
            "message_hash": trace.message_hash,
            "reconciliation_hash": trace.reconciliation_hash,
            "reconciliation_status": trace.reconciliation_status,
            "reconciliation_reason": trace.reconciliation_reason,
            "settlement_net": trace.settlement_net,
            "required_accounts": trace.required_accounts,
            "provider_pins": dict(record.inputs.provider_pins),
            "sender_imported": False,
            "live_mutation_allowed": False,
        }

    async def _ensure_record(
        self, context: PaperShadowStageContext
    ) -> AtomicVerticalStageRecord:
        key = context.opportunity.opportunity_id
        if key not in self._records:
            inputs = self.adapter.build(context)
            result = await self.vertical.run(inputs.candidate)
            self._validate_result(inputs, result)
            self._records[key] = AtomicVerticalStageRecord(inputs=inputs, result=result)
        return self._records[key]

    def _validate_result(
        self,
        inputs: AtomicVerticalRuntimeInputs,
        result: AtomicVerticalResult,
    ) -> None:
        trace = result.trace
        compiled_hash = result.finalized.compiled.message_hash
        reconciliation_hash = result.reconciliation.message_hash
        self._assert_same_hash(trace.message_hash, compiled_hash, "compiled")
        self._assert_same_hash(trace.message_hash, reconciliation_hash, "reconciliation")
        if not trace.required_accounts:
            raise AtomicRuntimeStageError(
                AtomicRuntimeStageErrorCode.MISSING_RUNTIME_INPUTS,
                "state-derived reconciliation must name required accounts",
            )
        if not inputs.capital_reservation_id or not inputs.durable_trace_id:
            raise AtomicRuntimeStageError(
                AtomicRuntimeStageErrorCode.MISSING_RUNTIME_INPUTS,
                "capital reservation and durable trace evidence are required",
            )

    def _require_previous(
        self,
        context: PaperShadowStageContext,
        stage: PaperShadowStageName,
    ) -> Mapping[str, Any]:
        output = context.previous_outputs.get(stage.value)
        if output is None:
            raise AtomicRuntimeStageError(
                AtomicRuntimeStageErrorCode.WRONG_STAGE_ORDER,
                f"{context.stage.value} requires prior {stage.value} output",
                details={"required_stage": stage.value, "current_stage": context.stage.value},
            )
        return output

    def _assert_same_hash(self, left: str, right: str, label: str) -> None:
        if left != right:
            raise AtomicRuntimeStageError(
                AtomicRuntimeStageErrorCode.MESSAGE_HASH_DRIFT,
                f"{label} evidence points at a different message hash",
                details={"source": label},
            )


def _is_sha256_hex(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


__all__ = [
    "AtomicRuntimeStageError",
    "AtomicRuntimeStageErrorCode",
    "AtomicVerticalCandidateAdapter",
    "AtomicVerticalRuntimeInputs",
    "AtomicVerticalRuntimeStageSuite",
    "AtomicVerticalStageRecord",
]
