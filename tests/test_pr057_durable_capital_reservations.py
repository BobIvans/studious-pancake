from __future__ import annotations

from pathlib import Path

from src.durability import AttemptKey, DurableLifecycleStore, ReservationState
from src.economics.capital import (
    CapitalCandidate,
    CapitalPolicy,
    NativeCostBreakdown,
    NoTradeReason,
    lamports_from_sol_string,
)
from src.economics.durable_reservations import (
    DurableCapitalCoordinator,
    WalletBalanceSnapshot,
)


def _policy() -> CapitalPolicy:
    return CapitalPolicy(
        protected_reserve_lamports=10_000_000,
        minimum_net_profit_lamports=100_000,
        maximum_priority_fee_lamports=1_000_000,
        maximum_jito_tip_lamports=1_000_000,
        maximum_peak_rent_lamports=8_000_000,
        contingency_lamports=500_000,
        maximum_flash_loan_lamports=2_000_000_000,
    )


def _snapshot(native_lamports: int = 20_000_000) -> WalletBalanceSnapshot:
    return WalletBalanceSnapshot(
        wallet_pubkey="wallet111111111111111111111111111111111111",
        native_lamports=native_lamports,
        context_slot=123_456,
        captured_at_ns=1_000_000_000,
    )


def _key(candidate_id: str, generation: int = 1) -> AttemptKey:
    return AttemptKey(
        logical_opportunity_id=candidate_id,
        plan_hash="a" * 64,
        generation=generation,
    )


def _candidate(
    candidate_id: str = "candidate-a",
    *,
    requested_flash_loan_lamports: int = 1_000_000_000,
    guaranteed_min_out_lamports: int = 1_020_000_000,
    flash_repayment_lamports: int = 1_000_000_000,
    base_network_fee_lamports: int = 5_000,
    priority_fee_lamports: int = 50_000,
    peak_rent_lamports: int = 2_000_000,
) -> CapitalCandidate:
    return CapitalCandidate(
        candidate_id=candidate_id,
        guaranteed_min_out_lamports=guaranteed_min_out_lamports,
        flash_repayment_lamports=flash_repayment_lamports,
        requested_flash_loan_lamports=requested_flash_loan_lamports,
        native_costs=NativeCostBreakdown(
            base_network_fee_lamports=base_network_fee_lamports,
            priority_fee_lamports=priority_fee_lamports,
            peak_rent_lamports=peak_rent_lamports,
        ),
        slippage_buffer_lamports=100_000,
        uncertainty_buffer_lamports=100_000,
        message_hash=f"message-{candidate_id}",
    )


def _store(path: Path) -> DurableLifecycleStore:
    return DurableLifecycleStore(path)


def test_0015_sol_wallet_snapshot_keeps_protected_reserve_unspendable(
    tmp_path: Path,
) -> None:
    with _store(tmp_path / "journal.db") as store:
        coordinator = DurableCapitalCoordinator(store=store, policy=_policy())

        result = coordinator.reserve(
            _candidate(
                peak_rent_lamports=4_600_000,
                base_network_fee_lamports=5_000,
            ),
            wallet_snapshot=_snapshot(lamports_from_sol_string("0.015")),
            attempt_key=_key("too-small"),
            idempotency_key="reserve:too-small",
        )

        assert result.decision.allowed is False
        assert result.decision.reason is NoTradeReason.INSUFFICIENT_NATIVE_BALANCE
        assert result.decision.available_native_lamports == 5_000_000
        assert result.decision.required_native_lamports == 5_155_000
        assert result.attempt is None
        assert store.count_rows("durable_attempts") == 0
        assert store.count_rows("durable_reservations") == 0


def test_allowed_candidate_creates_lifecycle_bound_active_reservation(
    tmp_path: Path,
) -> None:
    with _store(tmp_path / "journal.db") as store:
        coordinator = DurableCapitalCoordinator(store=store, policy=_policy())

        result = coordinator.reserve(
            _candidate("candidate-a"),
            wallet_snapshot=_snapshot(20_000_000),
            attempt_key=_key("candidate-a"),
            idempotency_key="reserve:candidate-a",
        )

        assert result.decision.allowed is True
        assert result.decision.reservation_id is not None
        assert result.attempt is not None
        assert result.attempt.reservation_id == result.decision.reservation_id
        assert result.attempt.reserved_lamports == 2_555_000
        assert result.attempt.reservation_state is ReservationState.ACTIVE
        assert store.count_rows("durable_attempts") == 1
        assert store.count_rows("durable_reservations") == 1


def test_active_durable_reservation_reduces_available_balance_after_restart(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "journal.db"

    with _store(db_path) as store:
        coordinator = DurableCapitalCoordinator(store=store, policy=_policy())
        first = coordinator.reserve(
            _candidate("first", peak_rent_lamports=4_000_000),
            wallet_snapshot=_snapshot(16_000_000),
            attempt_key=_key("first"),
            idempotency_key="reserve:first",
        )
        assert first.decision.allowed is True

    with _store(db_path) as store:
        coordinator = DurableCapitalCoordinator(store=store, policy=_policy())
        second = coordinator.reserve(
            _candidate("second", peak_rent_lamports=4_000_000),
            wallet_snapshot=_snapshot(16_000_000),
            attempt_key=_key("second"),
            idempotency_key="reserve:second",
        )

        assert second.decision.allowed is False
        assert second.decision.reason is NoTradeReason.INSUFFICIENT_NATIVE_BALANCE
        assert second.active_durable_reserved_lamports == 4_555_000
        assert len(second.recovery_attempt_ids) == 1
        assert store.count_rows("durable_attempts") == 1


def test_release_abandoned_pre_submission_reservation_unlocks_capital(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "journal.db"

    with _store(db_path) as store:
        coordinator = DurableCapitalCoordinator(store=store, policy=_policy())
        first = coordinator.reserve(
            _candidate("first", peak_rent_lamports=4_000_000),
            wallet_snapshot=_snapshot(16_000_000),
            attempt_key=_key("first"),
            idempotency_key="reserve:first",
        )
        assert first.attempt is not None
        released = coordinator.release_pre_submission_reservation(
            first.attempt.attempt_id,
            idempotency_key="release:first",
        )
        assert released is True

    with _store(db_path) as store:
        coordinator = DurableCapitalCoordinator(store=store, policy=_policy())
        second = coordinator.reserve(
            _candidate("second", peak_rent_lamports=4_000_000),
            wallet_snapshot=_snapshot(16_000_000),
            attempt_key=_key("second"),
            idempotency_key="reserve:second",
        )

        assert second.active_durable_reserved_lamports == 0
        assert second.decision.allowed is True
        assert store.count_rows("durable_attempts") == 2


def test_bounded_amount_search_returns_highest_policy_allowed_amount(
    tmp_path: Path,
) -> None:
    policy = CapitalPolicy(
        protected_reserve_lamports=10_000_000,
        minimum_net_profit_lamports=100_000,
        maximum_priority_fee_lamports=1_000_000,
        maximum_jito_tip_lamports=1_000_000,
        maximum_peak_rent_lamports=8_000_000,
        contingency_lamports=500_000,
        maximum_flash_loan_lamports=150,
    )
    with _store(tmp_path / "journal.db") as store:
        coordinator = DurableCapitalCoordinator(store=store, policy=policy)

        search = coordinator.bounded_amount_search(
            lower_lamports=1,
            upper_lamports=200,
            wallet_snapshot=_snapshot(100_000_000),
            candidate_factory=lambda amount: _candidate(
                f"amount-{amount}",
                requested_flash_loan_lamports=amount,
                guaranteed_min_out_lamports=1_020_000_000 + amount,
            ),
        )

        assert search.allowed is True
        assert search.selected_amount_lamports == 150
        assert search.decision.reason is NoTradeReason.TRADE_PERMITTED
        assert search.evaluations <= 8
