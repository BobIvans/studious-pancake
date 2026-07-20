from __future__ import annotations

from pathlib import Path

import pytest

from src.durability import AttemptKey, DurableLifecycleStore, ReservationState
from src.economics.capital import (
    CapitalCandidate,
    CapitalEngineError,
    CapitalPolicy,
    MessageFeeQuote,
    NativeCostBreakdown,
    NoTradeReason,
    lamports_from_sol_string,
)
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)
from src.economics.exact_fee_workflow import (
    ExactFeeCapitalStatus,
    ExactFeeCapitalWorkflow,
    candidate_with_exact_message_fee,
)


FINAL_HASH = "a" * 64


def _policy(*, protected: int = 10_000_000) -> CapitalPolicy:
    return CapitalPolicy(
        protected_reserve_lamports=protected,
        minimum_net_profit_lamports=100_000,
        maximum_priority_fee_lamports=1_000_000,
        maximum_jito_tip_lamports=1_000_000,
        maximum_peak_rent_lamports=8_000_000,
        contingency_lamports=0,
        maximum_flash_loan_lamports=2_000_000_000,
    )


def _snapshot(native_lamports: int = 15_000_000) -> WalletBalanceSnapshot:
    return WalletBalanceSnapshot(
        wallet_pubkey="wallet111111111111111111111111111111111111",
        native_lamports=native_lamports,
        context_slot=222_222,
        captured_at_ns=2_000_000_000,
    )


def _key(candidate_id: str, generation: int = 1) -> AttemptKey:
    return AttemptKey(
        logical_opportunity_id=candidate_id,
        plan_hash="b" * 64,
        generation=generation,
    )


def _candidate(
    candidate_id: str = "candidate-a",
    *,
    base_network_fee_lamports: int = 4_000_000,
    guaranteed_min_out_lamports: int = 30_000_000,
    flash_repayment_lamports: int = 20_000_000,
    requested_flash_loan_lamports: int = 20_000_000,
) -> CapitalCandidate:
    return CapitalCandidate(
        candidate_id=candidate_id,
        guaranteed_min_out_lamports=guaranteed_min_out_lamports,
        flash_repayment_lamports=flash_repayment_lamports,
        requested_flash_loan_lamports=requested_flash_loan_lamports,
        native_costs=NativeCostBreakdown(
            base_network_fee_lamports=base_network_fee_lamports,
        ),
        slippage_buffer_lamports=0,
        uncertainty_buffer_lamports=0,
        message_hash=None,
    )


def _store(path: Path) -> DurableLifecycleStore:
    return DurableLifecycleStore(path)


def test_revalidates_final_fee_without_double_counting_current_reservation(
    tmp_path: Path,
) -> None:
    with _store(tmp_path / "journal.db") as store:
        coordinator = DurableCapitalCoordinator(store=store, policy=_policy())
        workflow = ExactFeeCapitalWorkflow(coordinator)

        reserved = coordinator.reserve(
            _candidate("same-fee", base_network_fee_lamports=4_000_000),
            wallet_snapshot=_snapshot(15_000_000),
            attempt_key=_key("same-fee"),
            idempotency_key="reserve:same-fee",
        )
        assert reserved.attempt is not None
        assert reserved.decision.required_native_lamports == 4_000_000

        finalized = candidate_with_exact_message_fee(
            _candidate("same-fee", base_network_fee_lamports=1),
            MessageFeeQuote(message_hash=FINAL_HASH, base_fee_lamports=4_000_000),
        )
        result = workflow.finalize_reserved_attempt(
            attempt_id=reserved.attempt.attempt_id,
            finalized_candidate=finalized,
            wallet_snapshot=_snapshot(15_000_000),
            idempotency_key="final-fee:same-fee",
        )

        assert result.accepted is True
        assert result.status is ExactFeeCapitalStatus.READY_FOR_ATOMIC_VERTICAL
        assert result.released is False
        assert result.required_lamports == 4_000_000
        assert result.revalidation is not None
        assert result.revalidation.active_durable_reserved_lamports == 0
        stored = store.get_attempt(reserved.attempt.attempt_id)
        assert stored is not None
        assert stored.reservation_state is ReservationState.ACTIVE


def test_exact_final_fee_can_invalidate_candidate_and_release_reservation(
    tmp_path: Path,
) -> None:
    with _store(tmp_path / "journal.db") as store:
        coordinator = DurableCapitalCoordinator(store=store, policy=_policy())
        workflow = ExactFeeCapitalWorkflow(coordinator)

        reserved = coordinator.reserve(
            _candidate("too-expensive", base_network_fee_lamports=4_000_000),
            wallet_snapshot=_snapshot(15_000_000),
            attempt_key=_key("too-expensive"),
            idempotency_key="reserve:too-expensive",
        )
        assert reserved.attempt is not None

        finalized = candidate_with_exact_message_fee(
            _candidate("too-expensive", base_network_fee_lamports=1),
            MessageFeeQuote(message_hash=FINAL_HASH, base_fee_lamports=6_000_000),
        )
        result = workflow.finalize_reserved_attempt(
            attempt_id=reserved.attempt.attempt_id,
            finalized_candidate=finalized,
            wallet_snapshot=_snapshot(15_000_000),
            idempotency_key="final-fee:too-expensive",
        )

        assert result.accepted is False
        assert result.status is ExactFeeCapitalStatus.BLOCKED_BY_CAPITAL_DECISION
        assert result.decision is not None
        assert result.decision.reason is NoTradeReason.INSUFFICIENT_NATIVE_BALANCE
        assert result.released is True
        assert coordinator.active_durable_reserved_lamports() == 0
        stored = store.get_attempt(reserved.attempt.attempt_id)
        assert stored is not None
        assert stored.reservation_state is ReservationState.RELEASED


def test_final_fee_growth_above_existing_reservation_fails_closed(
    tmp_path: Path,
) -> None:
    with _store(tmp_path / "journal.db") as store:
        coordinator = DurableCapitalCoordinator(store=store, policy=_policy())
        workflow = ExactFeeCapitalWorkflow(coordinator)

        reserved = coordinator.reserve(
            _candidate("under-reserved", base_network_fee_lamports=4_000_000),
            wallet_snapshot=_snapshot(30_000_000),
            attempt_key=_key("under-reserved"),
            idempotency_key="reserve:under-reserved",
        )
        assert reserved.attempt is not None

        finalized = candidate_with_exact_message_fee(
            _candidate("under-reserved", base_network_fee_lamports=1),
            MessageFeeQuote(message_hash=FINAL_HASH, base_fee_lamports=5_000_000),
        )
        result = workflow.finalize_reserved_attempt(
            attempt_id=reserved.attempt.attempt_id,
            finalized_candidate=finalized,
            wallet_snapshot=_snapshot(30_000_000),
            idempotency_key="final-fee:under-reserved",
        )

        assert result.accepted is False
        assert (
            result.status
            is ExactFeeCapitalStatus.FINAL_FEE_EXCEEDS_DURABLE_RESERVATION
        )
        assert result.decision is not None
        assert result.decision.allowed is True
        assert result.reserved_lamports == 4_000_000
        assert result.required_lamports == 5_000_000
        assert result.released is True
        assert coordinator.active_durable_reserved_lamports() == 0


def test_0015_sol_policy_reserve_is_unspendable_for_pr074_candidates(
    tmp_path: Path,
) -> None:
    with _store(tmp_path / "journal.db") as store:
        protected = lamports_from_sol_string("0.015")
        coordinator = DurableCapitalCoordinator(
            store=store,
            policy=_policy(protected=protected),
        )

        result = coordinator.reserve(
            _candidate("protected-reserve", base_network_fee_lamports=1),
            wallet_snapshot=_snapshot(protected),
            attempt_key=_key("protected-reserve"),
            idempotency_key="reserve:protected-reserve",
        )

        assert result.decision.allowed is False
        assert result.decision.reason is NoTradeReason.INSUFFICIENT_NATIVE_BALANCE
        assert result.decision.available_native_lamports == 0
        assert result.attempt is None
        assert store.count_rows("durable_attempts") == 0


def test_null_get_fee_for_message_response_is_not_convertible() -> None:
    with pytest.raises(CapitalEngineError, match="null fee"):
        MessageFeeQuote.from_rpc_payload(
            message_hash=FINAL_HASH,
            payload={"result": {"context": {"slot": 1}, "value": None}},
        )
