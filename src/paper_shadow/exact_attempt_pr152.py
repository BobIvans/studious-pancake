"""PR-152 exact sender-free paper-attempt orchestration.

The boundary joins durable capital reservation, the existing atomic
planner/simulation/reconciliation vertical, and exact final-message fee
revalidation. It never signs or submits a transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
import time
from typing import Awaitable, Callable, Protocol

from src.durability import AttemptKey
from src.durability.unified_authority_pr02 import (
    AuthorityFence,
    ReservationTerminalState,
    UnifiedAuthorityError,
    UnifiedLifecycleAuthority,
)
from src.economics.capital import CapitalCandidate, MessageFeeQuote
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    DurableCapitalReservationResult,
    WalletBalanceSnapshot,
)
from src.economics.exact_fee_workflow import (
    ExactFeeCapitalResult,
    ExactFeeCapitalWorkflow,
    candidate_with_exact_message_fee,
)
from src.paper_shadow.atomic_vertical import (
    AtomicVerticalCandidate,
    AtomicVerticalResult,
)
from src.execution.economic_reconciliation.mega_pr02_proof import (
    EconomicProofQualification,
    QualificationStatus,
)
from src.execution.economic_reconciliation.models import ReconciliationStatus
from src.execution.models import ExecutionState
from src.paper_shadow.mpr2602_runtime import (
    begin_prepared_attempt_intent,
    validate_prepared_plan_hash,
)
from src.planning.atomic_marginfi_jupiter import CapitalReservationEvidence

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ExactAttemptStatus(StrEnum):
    PROVIDER_BLOCKED = "provider_blocked"
    CAPITAL_BLOCKED = "capital_blocked"
    VERTICAL_BLOCKED = "vertical_blocked"
    FINAL_FEE_BLOCKED = "final_fee_blocked"
    READY_FOR_DURABLE_PAPER = "ready_for_durable_paper"


class AtomicVerticalPort(Protocol):
    def run(
        self, candidate: AtomicVerticalCandidate
    ) -> Awaitable[AtomicVerticalResult]: ...


class CandidateFactory(Protocol):
    def __call__(
        self, reservation: CapitalReservationEvidence
    ) -> AtomicVerticalCandidate: ...


@dataclass(frozen=True, slots=True)
class ProviderExecutionEvidence:
    jupiter_contract_pin: str
    marginfi_program_hash: str
    account_snapshot_hash: str
    rooted_slot: int
    captured_at_ns: int
    expires_at_ns: int
    jupiter_execution_allowed: bool
    marginfi_execution_allowed: bool

    def __post_init__(self) -> None:
        for name in (
            "jupiter_contract_pin",
            "marginfi_program_hash",
            "account_snapshot_hash",
        ):
            if not _SHA256.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be a lowercase sha256 digest")
        if min(self.rooted_slot, self.captured_at_ns, self.expires_at_ns) < 0:
            raise ValueError("slot and timestamps must be non-negative")
        if self.expires_at_ns <= self.captured_at_ns:
            raise ValueError("provider evidence expiry must follow capture")

    def blockers(self, *, now_ns: int, discovery_slot: int) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.jupiter_execution_allowed:
            blockers.append("PR152_JUPITER_EXECUTION_NOT_ALLOWED")
        if not self.marginfi_execution_allowed:
            blockers.append("PR152_MARGINFI_EXECUTION_NOT_ALLOWED")
        if now_ns > self.expires_at_ns:
            blockers.append("PR152_PROVIDER_EVIDENCE_EXPIRED")
        if self.rooted_slot < discovery_slot:
            blockers.append("PR152_ROOTED_SLOT_BEHIND_DISCOVERY")
        return tuple(blockers)

    @property
    def evidence_hash(self) -> str:
        return _hash_json(
            {
                "jupiter_contract_pin": self.jupiter_contract_pin,
                "marginfi_program_hash": self.marginfi_program_hash,
                "account_snapshot_hash": self.account_snapshot_hash,
                "rooted_slot": self.rooted_slot,
                "captured_at_ns": self.captured_at_ns,
                "expires_at_ns": self.expires_at_ns,
                "jupiter_execution_allowed": self.jupiter_execution_allowed,
                "marginfi_execution_allowed": self.marginfi_execution_allowed,
            }
        )


@dataclass(frozen=True, slots=True)
class ExactAttemptRequest:
    attempt_key: AttemptKey
    capital_candidate: CapitalCandidate
    wallet_snapshot: WalletBalanceSnapshot
    provider_evidence: ProviderExecutionEvidence
    discovery_slot: int
    candidate_factory: CandidateFactory
    reserve_idempotency_key: str
    release_idempotency_key: str
    final_fee_idempotency_key: str

    def __post_init__(self) -> None:
        if (
            self.attempt_key.logical_opportunity_id
            != self.capital_candidate.candidate_id
        ):
            raise ValueError("attempt and capital candidate identities differ")
        if not all(
            (
                self.reserve_idempotency_key,
                self.release_idempotency_key,
                self.final_fee_idempotency_key,
            )
        ):
            raise ValueError("all PR-152 idempotency keys are required")


@dataclass(frozen=True, slots=True)
class ExactAttemptResult:
    status: ExactAttemptStatus
    provider_evidence_hash: str
    blockers: tuple[str, ...] = ()
    attempt_id: str | None = None
    message_hash: str | None = None
    planner_digest: str | None = None
    reconciliation_hash: str | None = None
    reservation_released: bool = False
    capital: DurableCapitalReservationResult | None = None
    exact_fee: ExactFeeCapitalResult | None = None
    vertical: AtomicVerticalResult | None = None
    sender_imported: bool = False
    submission_allowed: bool = False
    prepared_plan_hash: str | None = None

    @property
    def ready(self) -> bool:
        return self.status is ExactAttemptStatus.READY_FOR_DURABLE_PAPER

    @property
    def result_hash(self) -> str:
        payload: dict[str, object] = {
            "status": self.status.value,
            "provider_evidence_hash": self.provider_evidence_hash,
            "blockers": self.blockers,
            "attempt_id": self.attempt_id,
            "message_hash": self.message_hash,
            "planner_digest": self.planner_digest,
            "reconciliation_hash": self.reconciliation_hash,
            "reservation_released": self.reservation_released,
            "sender_imported": self.sender_imported,
            "submission_allowed": self.submission_allowed,
        }
        # Keep historical blocked-result hashes stable, while binding every new
        # prepared handoff to its complete execution-semantic identity.
        if self.prepared_plan_hash is not None:
            payload["prepared_plan_hash"] = self.prepared_plan_hash
        return _hash_json(payload)


class _PreparedFeeRejected(Exception):
    """Roll back the legacy fee release before PR-02 terminalizes atomically."""

    def __init__(self, result: ExactFeeCapitalResult) -> None:
        super().__init__("MPR2602_PREPARED_FINAL_FEE_REJECTED")
        self.result = result


class ExactPaperAttemptOrchestrator:
    def __init__(
        self,
        *,
        coordinator: DurableCapitalCoordinator,
        vertical: AtomicVerticalPort,
        clock_ns: Callable[[], int] = time.time_ns,
        authority: UnifiedLifecycleAuthority | None = None,
    ) -> None:
        if authority is not None and (
            not isinstance(authority, UnifiedLifecycleAuthority)
            or coordinator.store is not authority.lifecycle
        ):
            raise ValueError("MPR2602_FOREIGN_ATTEMPT_AUTHORITY")
        self.coordinator = coordinator
        self.vertical = vertical
        self.fee_workflow = ExactFeeCapitalWorkflow(coordinator)
        self.clock_ns = clock_ns
        self.authority = authority

    async def run(self, request: ExactAttemptRequest) -> ExactAttemptResult:
        evidence_hash = request.provider_evidence.evidence_hash
        blockers = request.provider_evidence.blockers(
            now_ns=self.clock_ns(), discovery_slot=request.discovery_slot
        )
        if blockers:
            return ExactAttemptResult(
                ExactAttemptStatus.PROVIDER_BLOCKED,
                evidence_hash,
                blockers=blockers,
            )

        capital = self.coordinator.reserve(
            request.capital_candidate,
            wallet_snapshot=request.wallet_snapshot,
            attempt_key=request.attempt_key,
            idempotency_key=request.reserve_idempotency_key,
        )
        if not capital.decision.allowed or capital.attempt is None:
            return ExactAttemptResult(
                ExactAttemptStatus.CAPITAL_BLOCKED,
                evidence_hash,
                blockers=(f"PR152_{capital.decision.reason.value.upper()}",),
                capital=capital,
            )

        attempt_id = capital.attempt.attempt_id
        reservation = CapitalReservationEvidence(
            reservation_id=capital.decision.reservation_id or "",
            approved=True,
            approved_borrow_amount=(
                request.capital_candidate.requested_flash_loan_lamports
            ),
            policy_profile="durable-paper",
            decision_hash=_hash_json(capital.decision.to_json()),
        )
        fence: AuthorityFence | None = None
        plan_hash: str | None = None
        try:
            candidate = request.candidate_factory(reservation)
            self._validate_candidate(candidate, request)
            if candidate.request.capital != reservation:
                raise ValueError("MPR2602_PREPARED_RESERVATION_MISMATCH")
            if self.authority is None:
                raise ValueError("MPR2602_UNIFIED_AUTHORITY_REQUIRED")
            fence, plan_hash = begin_prepared_attempt_intent(
                self.authority,
                attempt_id=attempt_id,
                attempt_generation=request.attempt_key.generation,
                candidate=candidate,
            )
            if fence.replayed:
                # A matching intent is not permission to repeat effects. The
                # durable outcome consumer/recovery owner must resolve it.
                return ExactAttemptResult(
                    ExactAttemptStatus.VERTICAL_BLOCKED,
                    evidence_hash,
                    blockers=("MPR2602_PREPARED_REPLAY_REQUIRES_RECONCILIATION",),
                    attempt_id=attempt_id,
                    capital=capital,
                    prepared_plan_hash=plan_hash,
                )
            vertical = await self.vertical.run(candidate)
            validate_prepared_plan_hash(candidate, plan_hash)
            self._validate_vertical(vertical, request, candidate)
        except UnifiedAuthorityError:
            # Never release another in-flight attempt's reservation after a
            # replay conflict, stale lease, or changed owner/policy fence.
            return ExactAttemptResult(
                ExactAttemptStatus.VERTICAL_BLOCKED,
                evidence_hash,
                blockers=("MPR2602_PREPARED_AUTHORITY_CONFLICT",),
                attempt_id=attempt_id,
                capital=capital,
                prepared_plan_hash=plan_hash,
            )
        except Exception as exc:
            reason = f"PR152_VERTICAL_{type(exc).__name__.upper()}"
            if fence is not None and plan_hash is not None:
                return self._commit_prepared_rejection(
                    fence,
                    ExactAttemptResult(
                        ExactAttemptStatus.VERTICAL_BLOCKED,
                        evidence_hash,
                        blockers=(reason,),
                        attempt_id=attempt_id,
                        reservation_released=True,
                        capital=capital,
                        prepared_plan_hash=plan_hash,
                    ),
                )
            released = self._release(request, attempt_id, "PR152_VERTICAL_FAILED")
            return ExactAttemptResult(
                ExactAttemptStatus.VERTICAL_BLOCKED,
                evidence_hash,
                blockers=(reason,),
                attempt_id=attempt_id,
                reservation_released=released,
                capital=capital,
            )

        assert (
            self.authority is not None and fence is not None and plan_hash is not None
        )
        message_hash = vertical.trace.message_hash
        fee_quote = MessageFeeQuote(
            message_hash=message_hash,
            base_fee_lamports=vertical.trace.final_fee_lamports,
            context_slot=vertical.finalized.report.fee_context_slot,
        )
        finalized_candidate = candidate_with_exact_message_fee(
            request.capital_candidate,
            fee_quote,
            expected_message_hash=message_hash,
        )
        try:
            # Fee evaluation is synchronous and has no network effects. A
            # rejected legacy release is rolled back; PR-02 owns the complete
            # rejection, reservation transition, terminal and outbox instead.
            with self.authority.lifecycle.write_transaction():
                exact_fee = self.fee_workflow.finalize_reserved_attempt(
                    attempt_id=attempt_id,
                    finalized_candidate=finalized_candidate,
                    wallet_snapshot=request.wallet_snapshot,
                    idempotency_key=request.final_fee_idempotency_key,
                )
                if not exact_fee.accepted:
                    raise _PreparedFeeRejected(exact_fee)
        except _PreparedFeeRejected as exc:
            exact_fee = exc.result
            return self._commit_prepared_rejection(
                fence,
                ExactAttemptResult(
                    ExactAttemptStatus.FINAL_FEE_BLOCKED,
                    evidence_hash,
                    blockers=(f"PR152_{exact_fee.status.value.upper()}",),
                    attempt_id=attempt_id,
                    message_hash=message_hash,
                    reservation_released=True,
                    capital=capital,
                    exact_fee=exact_fee,
                    vertical=vertical,
                    prepared_plan_hash=plan_hash,
                ),
            )

        return ExactAttemptResult(
            ExactAttemptStatus.READY_FOR_DURABLE_PAPER,
            evidence_hash,
            attempt_id=attempt_id,
            message_hash=message_hash,
            planner_digest=vertical.trace.planner_digest,
            reconciliation_hash=vertical.trace.reconciliation_hash,
            capital=capital,
            exact_fee=exact_fee,
            vertical=vertical,
            prepared_plan_hash=plan_hash,
        )

    def _commit_prepared_rejection(
        self, fence: AuthorityFence, result: ExactAttemptResult
    ) -> ExactAttemptResult:
        if self.authority is None or result.prepared_plan_hash is None:
            raise ValueError("MPR2602_PREPARED_REJECTION_AUTHORITY_REQUIRED")
        self.authority.commit_attempt_terminal(
            fence,
            target_state=ExecutionState.REJECTED,
            reservation_terminal_state=ReservationTerminalState.RELEASED,
            outcome="BLOCKED",
            reason_code=result.blockers[0],
            report_hash=result.result_hash,
            report_payload={
                "schema": "mpr2602.prepared-attempt-rejection.v1",
                "status": result.status.value,
                "prepared_plan_hash": result.prepared_plan_hash,
                "provider_evidence_hash": result.provider_evidence_hash,
                "blockers": list(result.blockers),
                "sender_imported": False,
                "submission_allowed": False,
            },
        )
        return result

    def _validate_candidate(
        self, candidate: AtomicVerticalCandidate, request: ExactAttemptRequest
    ) -> None:
        planner = candidate.request
        evidence = request.provider_evidence
        if planner.opportunity_id != request.capital_candidate.candidate_id:
            raise ValueError("candidate identity mismatch")
        if planner.jupiter_contract_pin != evidence.jupiter_contract_pin:
            raise ValueError("Jupiter contract pin mismatch")
        if getattr(candidate, "pre_state_accounts", None) is None:
            # Historical observation candidates remain representable, but they
            # cannot be promoted into a qualified production paper handoff.
            raise ValueError("legacy observations are unqualified for durable handoff")
        if not candidate.pre_state_accounts:
            raise ValueError("raw candidate requires account evidence")
        if (
            candidate.decoded_account_hashes
            or candidate.native_observations
            or candidate.token_observations
            or candidate.marginfi_observation is not None
        ):
            raise ValueError("raw candidate cannot carry caller economics")
        snapshot = planner.marginfi_snapshot
        if evidence.account_snapshot_hash != snapshot.state_fingerprint:
            raise ValueError("provider snapshot fingerprint mismatch")
        if (
            type(candidate.pre_state_slot) is not int
            or candidate.pre_state_slot != snapshot.slot
            or candidate.pre_state_slot < request.discovery_slot
            or evidence.rooted_slot < candidate.pre_state_slot
        ):
            raise ValueError("raw snapshot context mismatch")
        policy = candidate.decode_policy
        if policy is None or policy.marginfi is None:
            raise ValueError("raw MarginFi decoding policy required")
        marginfi = policy.marginfi
        if (
            marginfi.margin_account != snapshot.margin_account.address
            or marginfi.group != snapshot.group
            or marginfi.authority != str(planner.payer)
            or marginfi.authority != snapshot.margin_account.authority
            or marginfi.bank != snapshot.bank.address
            or marginfi.vault != snapshot.bank.liquidity_vault
            or marginfi.principal != planner.borrow_amount
        ):
            raise ValueError("raw decoder policy differs from planner snapshot")
        if (
            snapshot.bank.mint != "So11111111111111111111111111111111111111112"
            or snapshot.bank.mint_decimals != 9
            or snapshot.bank.token_program
            != "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
            or planner.borrow_amount
            != request.capital_candidate.requested_flash_loan_lamports
            or str(planner.payer) != request.wallet_snapshot.wallet_pubkey
        ):
            raise ValueError("raw capital principal requires exact native WSOL units")

    @staticmethod
    def _validate_vertical(
        vertical: AtomicVerticalResult,
        request: ExactAttemptRequest,
        candidate: AtomicVerticalCandidate,
    ) -> None:
        provenance = vertical.planner_result.provenance
        evidence = request.provider_evidence
        if provenance.jupiter_contract_pin != evidence.jupiter_contract_pin:
            raise ValueError("final Jupiter provenance mismatch")
        if provenance.marginfi_pin_hash != evidence.marginfi_program_hash:
            raise ValueError("final MarginFi provenance mismatch")
        if vertical.trace.opportunity_id != request.capital_candidate.candidate_id:
            raise ValueError("vertical opportunity identity mismatch")
        qualification = vertical.qualification
        if (
            not isinstance(qualification, EconomicProofQualification)
            or qualification.qualified is not True
            or qualification.status is not QualificationStatus.QUALIFIED_PROFIT
            or qualification.report_status is not ReconciliationStatus.PROVEN_PROFIT
            or type(qualification.quote_net) is not int
            or qualification.quote_net <= 0
            or qualification.quote_net < qualification.min_profit_quote_units
        ):
            raise ValueError("raw conservative economic qualification not admitted")
        if (
            vertical.evidence_origin != "decoder_owned_offline"
            or not isinstance(vertical.raw_evidence_hash, str)
            or not _SHA256.fullmatch(vertical.raw_evidence_hash)
            or candidate.valuation is None
            or candidate.marginfi_registry is None
            or qualification.valuation_hash != candidate.valuation.valuation_hash
            or qualification.registry_hash != candidate.marginfi_registry.registry_hash
            or qualification.report_status != vertical.reconciliation.status
        ):
            raise ValueError("raw economic qualification provenance mismatch")

    def _release(
        self, request: ExactAttemptRequest, attempt_id: str, reason: str
    ) -> bool:
        return self.coordinator.release_pre_submission_reservation(
            attempt_id,
            idempotency_key=request.release_idempotency_key,
            reason=reason,
        )


def _hash_json(value: object) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
