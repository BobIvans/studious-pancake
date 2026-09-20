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

from dataclasses import dataclass, replace
import json
from enum import Enum
from typing import Mapping, Any
from src.kernel import canonical_json_bytes
from src.execution.state_evidence_pr115 import PR115DecodePolicy
from src.execution.economic_reconciliation.exact_adapter import (
    evidence_from_raw_simulation,
)
from src.execution.economic_reconciliation.mega_pr02_proof import (
    ConservativeValuationSnapshot,
    MarginfiRegistrySnapshot,
    RawStateEconomicProofAuthority,
    EconomicProofQualification,
)

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
    pre_state_accounts: tuple[Mapping[str, Any] | None, ...] | None = None
    pre_state_slot: int | None = None
    decode_policy: PR115DecodePolicy | None = None
    approved_assets: tuple[AssetKey, ...] = ()
    valuation: ConservativeValuationSnapshot | None = None
    marginfi_registry: MarginfiRegistrySnapshot | None = None


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
    qualification: EconomicProofQualification | None = None
    raw_evidence_hash: str | None = None
    evidence_origin: str = "legacy_observations_unqualified"


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
        if candidate.pre_state_accounts is not None:
            self._validate_raw_context(candidate)
            raw = canonical_json_bytes(candidate.pre_state_accounts)
            if len(raw) > self.simulator.policy.max_raw_account_evidence_bytes:
                raise ValueError("pre-state evidence exceeds bound")
            candidate = replace(candidate, pre_state_accounts=tuple(json.loads(raw)))
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
            raw_state = None
            raw_hash = None
            if candidate.pre_state_accounts is not None:
                if (
                    candidate.native_observations
                    or candidate.token_observations
                    or candidate.marginfi_observation is not None
                    or candidate.decoded_account_hashes
                    or candidate.protocol_fees
                    or candidate.tip_lamports
                ):
                    raise ValueError(
                        "caller observations cannot override decoder-owned economics"
                    )
                if candidate.decode_policy is None or candidate.pre_state_slot is None:
                    raise ValueError("raw decoder context missing")
                evidence, raw_state, raw_hash = evidence_from_raw_simulation(
                    finalized,
                    pre_state_accounts=candidate.pre_state_accounts,
                    pre_state_slot=candidate.pre_state_slot,
                    policy=candidate.decode_policy,
                    settlement_asset=candidate.settlement_asset,
                    assets=candidate.approved_assets,
                    payer=str(candidate.request.payer),
                    principal=candidate.request.borrow_amount,
                )
            else:
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
        qualification = None
        if raw_state is not None:
            if candidate.valuation is None or candidate.marginfi_registry is None:
                raise AtomicVerticalError(
                    AtomicVerticalRejectionCode.RECONCILIATION_INCOMPLETE,
                    "approved valuation and registry required for raw economic qualification",
                )
            qualification = RawStateEconomicProofAuthority().qualify(
                evidence=evidence,
                report=reconciliation,
                raw_state=raw_state,
                registry=candidate.marginfi_registry,
                valuation=candidate.valuation,
            )
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
            qualification=qualification,
            raw_evidence_hash=raw_hash,
            evidence_origin=(
                "decoder_owned_offline"
                if raw_state is not None
                else "legacy_observations_unqualified"
            ),
        )

    @staticmethod
    def _validate_raw_context(candidate: AtomicVerticalCandidate) -> None:
        """Bind the raw decoder's scope to the same snapshot used by the planner."""
        policy = candidate.decode_policy
        if policy is None or policy.marginfi is None:
            raise ValueError("raw MarginFi decoder context required")
        context = policy.marginfi
        request = candidate.request
        snapshot = request.marginfi_snapshot
        if (
            context.margin_account != str(snapshot.margin_account.address)
            or context.group != str(snapshot.group)
            or context.group != str(snapshot.margin_account.group)
            or context.group != str(snapshot.bank.group)
            or context.authority != str(snapshot.margin_account.authority)
            or context.authority != str(request.payer)
            or context.bank != str(snapshot.bank.address)
            or context.vault != str(snapshot.bank.liquidity_vault)
            or context.principal != request.borrow_amount
            or candidate.pre_state_slot != snapshot.slot
        ):
            raise ValueError("raw decoder and planner snapshot differ")
        vectors = request.marginfi_source_vectors
        if vectors is not None and (
            context.source_commit != vectors.source_commit
            or context.layout_sha256 != vectors.layout_sha256
        ):
            raise ValueError("raw decoder and planner source vectors differ")

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
