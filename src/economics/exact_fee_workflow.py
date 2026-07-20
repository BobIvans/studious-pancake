"""PR-074 exact-fee capital reservation workflow.

This module is the narrow bridge between PR-057 durable capital reservations
and the later PR-075 atomic vertical.  It never signs or submits a transaction:
it only applies the final Solana `getFeeForMessage` quote to a candidate,
revalidates the already-durable reservation, and releases pre-submission
capital when the exact finalized message makes the candidate unsafe.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from src.durability import DurableAttempt
from src.economics.capital import (
    CapitalCandidate,
    CapitalDecision,
    CapitalEngineError,
    MessageFeeQuote,
    NativeCostBreakdown,
)
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    DurableCapitalReservationResult,
    WalletBalanceSnapshot,
)


class ExactFeeCapitalStatus(StrEnum):
    """Machine-readable PR-074 final fee admission states."""

    READY_FOR_ATOMIC_VERTICAL = "ready_for_atomic_vertical"
    BLOCKED_BY_CAPITAL_DECISION = "blocked_by_capital_decision"
    FINAL_FEE_EXCEEDS_DURABLE_RESERVATION = "final_fee_exceeds_durable_reservation"
    MISSING_ATTEMPT = "missing_attempt"
    MISSING_ACTIVE_RESERVATION = "missing_active_reservation"
    MISSING_FINAL_MESSAGE_HASH = "missing_final_message_hash"


@dataclass(frozen=True, slots=True)
class ExactFeeCapitalResult:
    """Final exact-fee revalidation outcome for a reserved candidate."""

    status: ExactFeeCapitalStatus
    wallet_snapshot: WalletBalanceSnapshot
    revalidation: DurableCapitalReservationResult | None
    attempt: DurableAttempt | None
    final_message_hash: str | None
    reserved_lamports: int
    required_lamports: int
    released: bool = False
    release_reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status is ExactFeeCapitalStatus.READY_FOR_ATOMIC_VERTICAL

    @property
    def decision(self) -> CapitalDecision | None:
        if self.revalidation is None:
            return None
        return self.revalidation.decision

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "accepted": self.accepted,
            "wallet_snapshot": self.wallet_snapshot.to_json(),
            "decision": None if self.decision is None else self.decision.to_json(),
            "attempt_id": None if self.attempt is None else self.attempt.attempt_id,
            "final_message_hash": self.final_message_hash,
            "reserved_lamports": str(self.reserved_lamports),
            "required_lamports": str(self.required_lamports),
            "released": self.released,
            "release_reason": self.release_reason,
        }


def candidate_with_exact_message_fee(
    candidate: CapitalCandidate,
    fee_quote: MessageFeeQuote,
    *,
    priority_fee_lamports: int | None = None,
    jito_tip_lamports: int | None = None,
    peak_rent_lamports: int | None = None,
    rent_loss_lamports: int | None = None,
    expected_message_hash: str | None = None,
) -> CapitalCandidate:
    """Return a candidate whose native costs come from the final message fee.

    `MessageFeeQuote.from_rpc_payload(...)` already fail-closes on Solana RPC
    `getFeeForMessage` returning `null`.  This helper keeps the final base fee
    tied to the exact finalized message hash and preserves all non-native
    profitability buffers from the upstream candidate.
    """

    if expected_message_hash is not None and fee_quote.message_hash != expected_message_hash:
        raise CapitalEngineError("final fee quote does not match expected message hash")

    current_costs = candidate.native_costs
    final_costs = NativeCostBreakdown.from_message_fee(
        fee_quote,
        priority_fee_lamports=(
            current_costs.priority_fee_lamports
            if priority_fee_lamports is None
            else priority_fee_lamports
        ),
        jito_tip_lamports=(
            current_costs.jito_tip_lamports
            if jito_tip_lamports is None
            else jito_tip_lamports
        ),
        peak_rent_lamports=(
            current_costs.peak_rent_lamports
            if peak_rent_lamports is None
            else peak_rent_lamports
        ),
        rent_loss_lamports=(
            current_costs.rent_loss_lamports
            if rent_loss_lamports is None
            else rent_loss_lamports
        ),
    )
    return replace(
        candidate,
        native_costs=final_costs,
        message_hash=fee_quote.message_hash,
    )


class ExactFeeCapitalWorkflow:
    """Revalidate a durable reservation after exact message finalization."""

    def __init__(self, coordinator: DurableCapitalCoordinator) -> None:
        self.coordinator = coordinator

    def finalize_reserved_attempt(
        self,
        *,
        attempt_id: str,
        finalized_candidate: CapitalCandidate,
        wallet_snapshot: WalletBalanceSnapshot,
        idempotency_key: str,
        release_on_rejection: bool = True,
    ) -> ExactFeeCapitalResult:
        """Check exact final fee and release unsafe pre-submission reservations."""

        attempt = self.coordinator.store.get_attempt(attempt_id)
        if attempt is None:
            return ExactFeeCapitalResult(
                status=ExactFeeCapitalStatus.MISSING_ATTEMPT,
                wallet_snapshot=wallet_snapshot,
                revalidation=None,
                attempt=None,
                final_message_hash=finalized_candidate.message_hash,
                reserved_lamports=0,
                required_lamports=0,
            )

        if finalized_candidate.message_hash is None:
            released = self._release_if_requested(
                attempt_id=attempt_id,
                idempotency_key=idempotency_key,
                release_on_rejection=release_on_rejection,
                reason="PR074_MISSING_FINAL_MESSAGE_HASH",
            )
            return ExactFeeCapitalResult(
                status=ExactFeeCapitalStatus.MISSING_FINAL_MESSAGE_HASH,
                wallet_snapshot=wallet_snapshot,
                revalidation=None,
                attempt=attempt,
                final_message_hash=None,
                reserved_lamports=attempt.reserved_lamports,
                required_lamports=0,
                released=released,
                release_reason=("PR074_MISSING_FINAL_MESSAGE_HASH" if released else None),
            )

        try:
            revalidation = self.coordinator.evaluate_for_attempt(
                finalized_candidate,
                wallet_snapshot=wallet_snapshot,
                attempt_id=attempt_id,
            )
        except CapitalEngineError:
            return ExactFeeCapitalResult(
                status=ExactFeeCapitalStatus.MISSING_ACTIVE_RESERVATION,
                wallet_snapshot=wallet_snapshot,
                revalidation=None,
                attempt=attempt,
                final_message_hash=finalized_candidate.message_hash,
                reserved_lamports=attempt.reserved_lamports,
                required_lamports=0,
            )

        required = revalidation.decision.required_native_lamports
        if not revalidation.decision.allowed:
            released = self._release_if_requested(
                attempt_id=attempt_id,
                idempotency_key=idempotency_key,
                release_on_rejection=release_on_rejection,
                reason="PR074_FINAL_FEE_CAPITAL_REJECTED",
            )
            return ExactFeeCapitalResult(
                status=ExactFeeCapitalStatus.BLOCKED_BY_CAPITAL_DECISION,
                wallet_snapshot=wallet_snapshot,
                revalidation=revalidation,
                attempt=attempt,
                final_message_hash=finalized_candidate.message_hash,
                reserved_lamports=attempt.reserved_lamports,
                required_lamports=required,
                released=released,
                release_reason=("PR074_FINAL_FEE_CAPITAL_REJECTED" if released else None),
            )

        if required > attempt.reserved_lamports:
            released = self._release_if_requested(
                attempt_id=attempt_id,
                idempotency_key=idempotency_key,
                release_on_rejection=release_on_rejection,
                reason="PR074_FINAL_FEE_EXCEEDS_RESERVATION",
            )
            return ExactFeeCapitalResult(
                status=ExactFeeCapitalStatus.FINAL_FEE_EXCEEDS_DURABLE_RESERVATION,
                wallet_snapshot=wallet_snapshot,
                revalidation=revalidation,
                attempt=attempt,
                final_message_hash=finalized_candidate.message_hash,
                reserved_lamports=attempt.reserved_lamports,
                required_lamports=required,
                released=released,
                release_reason=(
                    "PR074_FINAL_FEE_EXCEEDS_RESERVATION" if released else None
                ),
            )

        return ExactFeeCapitalResult(
            status=ExactFeeCapitalStatus.READY_FOR_ATOMIC_VERTICAL,
            wallet_snapshot=wallet_snapshot,
            revalidation=revalidation,
            attempt=attempt,
            final_message_hash=finalized_candidate.message_hash,
            reserved_lamports=attempt.reserved_lamports,
            required_lamports=required,
        )

    def _release_if_requested(
        self,
        *,
        attempt_id: str,
        idempotency_key: str,
        release_on_rejection: bool,
        reason: str,
    ) -> bool:
        if not release_on_rejection:
            return False
        return self.coordinator.release_pre_submission_reservation(
            attempt_id,
            idempotency_key=idempotency_key,
            reason=reason,
        )
