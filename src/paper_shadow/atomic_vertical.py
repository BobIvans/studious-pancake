"""PR-058 sender-free atomic execution vertical.

This module composes the already isolated PR-034, PR-036, and PR-037
boundaries into one reviewable paper/shadow vertical:

    atomic MarginFi + Jupiter plan
    -> canonical v0 exact simulation
    -> state-derived economic reconciliation

It deliberately never signs, submits, polls Jito/RPC send status, or imports a
sender.  The result is evidence that a candidate can move through all canonical
pre-send stages without mutating the final simulated message.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.execution.economic_reconciliation import (
    AssetKey,
    AssetQuantity,
    EconomicReconciler,
    MarginfiRepaymentObservation,
    NativeObservation,
    ReconciliationReport,
    TokenObservation,
    evidence_from_exact_simulation,
)
from src.execution.exact_simulation import (
    ExactSimulationFinalizer,
    FinalizedSimulation,
    validate_exact_submission_binding,
)
from src.execution.models import BlockhashContext, ResolvedAddressLookupTable
from src.planning.atomic_marginfi_jupiter import (
    AtomicMarginfiJupiterPlanner,
    AtomicPlannerRequest,
    AtomicPlannerResult,
)


class AtomicVerticalRejectionCode(str, Enum):
    """Fail-closed PR-058 vertical rejection reasons."""

    ACCOUNT_EVIDENCE_MISMATCH = "PR058_ACCOUNT_EVIDENCE_MISMATCH"
    MESSAGE_MUTATED_AFTER_SIMULATION = "PR058_MESSAGE_MUTATED_AFTER_SIMULATION"
    RECONCILIATION_INCOMPLETE = "PR058_RECONCILIATION_INCOMPLETE"


class AtomicVerticalError(RuntimeError):
    """Typed sender-free vertical error with safe diagnostics."""

    def __init__(
        self,
        code: AtomicVerticalRejectionCode,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(f"{code.value}: {message}")
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class AtomicVerticalCandidate:
    """All non-live inputs needed for a single PR-058 pre-send vertical run."""

    request: AtomicPlannerRequest
    blockhash: BlockhashContext
    settlement_asset: AssetKey
    lookup_tables: tuple[ResolvedAddressLookupTable, ...] = ()
    native_observations: tuple[NativeObservation, ...] = ()
    token_observations: tuple[TokenObservation, ...] = ()
    marginfi_observation: MarginfiRepaymentObservation | None = None
    decoded_account_hashes: tuple[str, ...] = ()
    required_accounts: tuple[str, ...] = ()
    tip_lamports: int = 0
    protocol_fees: tuple[AssetQuantity, ...] = ()


@dataclass(frozen=True, slots=True)
class AtomicVerticalTrace:
    """Stable review evidence for planner -> simulation -> reconciliation."""

    opportunity_id: str
    planner_digest: str
    sequence_fingerprint: str
    message_hash: str
    provisional_response_hash: str
    final_response_hash: str
    logs_hash: str
    reconciliation_hash: str
    min_context_slot: int
    final_compute_unit_limit: int
    final_fee_lamports: int
    settlement_net: int | None
    reconciliation_status: str
    reconciliation_reason: str
    monitored_accounts: tuple[str, ...]
    required_accounts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AtomicVerticalResult:
    """Sender-free PR-058 vertical result."""

    planner_result: AtomicPlannerResult
    finalized: FinalizedSimulation
    reconciliation: ReconciliationReport
    trace: AtomicVerticalTrace


class AtomicPlannerSimulationReconciliationVertical:
    """Run one atomic candidate through canonical stages without a sender."""

    def __init__(
        self,
        planner: AtomicMarginfiJupiterPlanner,
        simulator: ExactSimulationFinalizer,
        *,
        reconciler: EconomicReconciler | None = None,
    ) -> None:
        self.planner = planner
        self.simulator = simulator
        self.reconciler = reconciler or EconomicReconciler()

    async def run(self, candidate: AtomicVerticalCandidate) -> AtomicVerticalResult:
        planner_result = self.planner.plan(candidate.request)
        finalized = await self.simulator.finalize(
            planner_result.transaction_plan,
            candidate.blockhash,
            candidate.lookup_tables,
        )

        message_hash = finalized.compiled.message_hash
        serialized_message = bytes(finalized.compiled.serialized_message)
        validate_exact_submission_binding(
            finalized,
            permit_message_hash=message_hash,
            submission_message_hash=message_hash,
            serialized_submission_message=serialized_message,
        )

        try:
            evidence = evidence_from_exact_simulation(
                finalized,
                settlement_asset=candidate.settlement_asset,
                native=candidate.native_observations,
                tokens=candidate.token_observations,
                marginfi=candidate.marginfi_observation,
                decoded_account_hashes=candidate.decoded_account_hashes,
                required_accounts=candidate.required_accounts,
                tip_lamports=candidate.tip_lamports,
                protocol_fees=candidate.protocol_fees,
            )
        except ValueError as exc:
            raise AtomicVerticalError(
                AtomicVerticalRejectionCode.ACCOUNT_EVIDENCE_MISMATCH,
                "decoded account evidence is not bound to exact simulation",
                details={"exception_type": type(exc).__name__},
            ) from exc

        reconciliation = self.reconciler.reconcile(evidence)
        self._ensure_message_immutable(
            finalized=finalized,
            reconciliation=reconciliation,
            message_hash=message_hash,
            serialized_message=serialized_message,
        )

        if not reconciliation.complete:
            raise AtomicVerticalError(
                AtomicVerticalRejectionCode.RECONCILIATION_INCOMPLETE,
                "state-derived economic reconciliation did not prove an outcome",
                details={
                    "status": reconciliation.status.value,
                    "reason": reconciliation.reason.value,
                    "message_hash": reconciliation.message_hash,
                },
            )

        report = finalized.report
        trace = AtomicVerticalTrace(
            opportunity_id=planner_result.provenance.opportunity_id,
            planner_digest=planner_result.provenance.digest,
            sequence_fingerprint=planner_result.provenance.sequence_fingerprint,
            message_hash=message_hash,
            provisional_response_hash=report.provisional.response_hash,
            final_response_hash=report.final.response_hash,
            logs_hash=report.final.logs_hash,
            reconciliation_hash=reconciliation.reconciliation_hash,
            min_context_slot=report.min_context_slot,
            final_compute_unit_limit=report.final_compute_unit_limit,
            final_fee_lamports=report.final_fee_lamports,
            settlement_net=reconciliation.settlement_net,
            reconciliation_status=reconciliation.status.value,
            reconciliation_reason=reconciliation.reason.value,
            monitored_accounts=report.monitored_accounts,
            required_accounts=candidate.required_accounts,
        )
        return AtomicVerticalResult(
            planner_result=planner_result,
            finalized=finalized,
            reconciliation=reconciliation,
            trace=trace,
        )

    def _ensure_message_immutable(
        self,
        *,
        finalized: FinalizedSimulation,
        reconciliation: ReconciliationReport,
        message_hash: str,
        serialized_message: bytes,
    ) -> None:
        if finalized.compiled.message_hash != message_hash:
            raise AtomicVerticalError(
                AtomicVerticalRejectionCode.MESSAGE_MUTATED_AFTER_SIMULATION,
                "compiled message hash changed after final simulation",
            )
        if bytes(finalized.compiled.serialized_message) != serialized_message:
            raise AtomicVerticalError(
                AtomicVerticalRejectionCode.MESSAGE_MUTATED_AFTER_SIMULATION,
                "serialized message changed after final simulation",
            )
        finalized.report.validate_message_bytes(serialized_message)
        if reconciliation.message_hash != message_hash:
            raise AtomicVerticalError(
                AtomicVerticalRejectionCode.MESSAGE_MUTATED_AFTER_SIMULATION,
                "reconciliation evidence points at a different message",
            )


__all__ = [
    "AtomicPlannerSimulationReconciliationVertical",
    "AtomicVerticalCandidate",
    "AtomicVerticalError",
    "AtomicVerticalRejectionCode",
    "AtomicVerticalResult",
    "AtomicVerticalTrace",
]
