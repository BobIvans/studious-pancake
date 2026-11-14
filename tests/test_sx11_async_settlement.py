"""SX-11 async settlement state machine tests (deterministic, offline)."""

from __future__ import annotations

import pytest

from src.strategy_evolution.async_settlement import (
    EXECUTION_CLASS,
    AsyncSettlementMachine,
    AtomicityClassificationError,
    CapitalLockLedger,
    DoubleReleaseError,
    InvalidTransitionError,
    SettlementAction,
    SettlementDomain,
    SettlementError,
    SettlementPath,
    SettlementState,
    classify_execution_class,
    execute_settlement_plan,
    inject_reorg_at,
    inject_timeout_at,
)


def _domains() -> tuple[SettlementDomain, SettlementDomain]:
    source = SettlementDomain(
        chain_id="chain:l1",
        finality_rule="POS_EPOCH_FINALITY",
        reorg_depth=12,
        message_latency_bounds=(12, 60),
    )
    target = SettlementDomain(
        chain_id="chain:rollup-x",
        finality_rule="SOFT_CONFIRM_DEPTH",
    )
    return source, target


def _machine(
    position_id: str = "pos-1", amount_atoms: int = 100
) -> AsyncSettlementMachine:
    source, target = _domains()
    return AsyncSettlementMachine(
        position_id=position_id,
        source_domain=source,
        target_domain=target,
        amount_atoms=amount_atoms,
    )


def _happy_plan() -> tuple[SettlementAction, ...]:
    return (
        SettlementAction(
            target=SettlementState.CONFIRMED_LOCAL, reason="local_confirm_observed"
        ),
        SettlementAction(
            target=SettlementState.RELAYED, reason="message_relay_observed"
        ),
        SettlementAction(
            target=SettlementState.FINALIZED, reason="target_finality_observed"
        ),
    )


def test_happy_path_settlement_releases_lock_exactly_once() -> None:
    machine = _machine()
    with pytest.raises(InvalidTransitionError, match="INVALID_TRANSITION"):
        machine.transition(SettlementState.RELAYED, reason="skip_confirm")
    with pytest.raises(InvalidTransitionError, match="INVALID_TRANSITION"):
        machine.transition(SettlementState.FINALIZED, reason="skip_everything")
    assert machine.state is SettlementState.INITIATED

    trace = execute_settlement_plan(machine, _happy_plan())
    assert trace.stopped_reason == "PLAN_COMPLETE"
    assert trace.final_state is SettlementState.FINALIZED
    assert trace.visited_states == (
        SettlementState.INITIATED,
        SettlementState.CONFIRMED_LOCAL,
        SettlementState.RELAYED,
        SettlementState.FINALIZED,
    )
    assert trace.lock_released is True
    assert trace.lock_release_step == 3
    lock = machine.lock_snapshot()
    assert lock.status == "RELEASED"
    assert lock.release_count == 1
    assert lock.released_at_step == 3
    assert lock.release_reason == "target_finality_observed"
    assert lock.amount_atoms == 100
    with pytest.raises(DoubleReleaseError, match="LOCK_DOUBLE_RELEASE"):
        machine.release_lock(reason="duplicate_release")


def test_reorg_fault_leaves_reorged_and_lock_held() -> None:
    machine = _machine()
    injected = inject_reorg_at(_happy_plan(), step=1)
    assert [action.target for action in injected] == [
        SettlementState.CONFIRMED_LOCAL,
        SettlementState.REORGED,
        SettlementState.RELAYED,
        SettlementState.FINALIZED,
    ]
    trace = execute_settlement_plan(machine, injected)
    assert trace.stopped_reason == "INVALID_TRANSITION"
    assert trace.final_state is SettlementState.REORGED
    assert machine.lock_snapshot().status == "LOCKED"
    assert machine.lock_snapshot().release_count == 0
    # remaining starts at the first not-applied action; the REORGED fault applied
    assert [action.target for action in trace.remaining_actions] == [
        SettlementState.RELAYED,
        SettlementState.FINALIZED,
    ]
    with pytest.raises(InvalidTransitionError):
        machine.transition(SettlementState.FINALIZED, reason="finalize_after_reorg")

    machine.transition(SettlementState.STRANDED_INVENTORY, reason="stranded_by_reorg")
    machine.transition(SettlementState.RECOVERED, reason="recovered_after_reorg")
    lock = machine.lock_snapshot()
    assert lock.status == "RELEASED"
    assert lock.release_count == 1
    assert lock.release_reason == "recovered_after_reorg"
    assert machine.recovery_transitions[-1].to_state is SettlementState.RECOVERED


def test_timeout_fault_stops_plan_and_holds_lock() -> None:
    machine = _machine()
    injected = inject_timeout_at(_happy_plan(), step=0)
    assert [action.target for action in injected] == [
        SettlementState.TIMEOUT,
        SettlementState.CONFIRMED_LOCAL,
        SettlementState.RELAYED,
        SettlementState.FINALIZED,
    ]
    trace = execute_settlement_plan(machine, injected)
    assert trace.stopped_reason == "INVALID_TRANSITION"
    assert trace.final_state is SettlementState.TIMEOUT
    assert trace.lock_released is False
    # remaining starts at the first not-applied action; the TIMEOUT fault applied
    assert [action.target for action in trace.remaining_actions] == [
        SettlementState.CONFIRMED_LOCAL,
        SettlementState.RELAYED,
        SettlementState.FINALIZED,
    ]
    with pytest.raises(InvalidTransitionError):
        machine.transition(
            SettlementState.CONFIRMED_LOCAL, reason="confirm_after_timeout"
        )


def test_stranded_recovery_releases_lock_once_and_double_release_raises() -> None:
    machine = _machine(amount_atoms=250)
    trace = execute_settlement_plan(machine, inject_timeout_at(_happy_plan(), step=0))
    assert trace.final_state is SettlementState.TIMEOUT

    machine.transition(SettlementState.STRANDED_INVENTORY, reason="stranded_by_timeout")
    machine.transition(SettlementState.RECOVERED, reason="recovered_after_timeout")
    lock = machine.lock_snapshot()
    assert lock.status == "RELEASED"
    assert lock.release_count == 1
    assert lock.released_at_step == 3
    assert [transition.to_state for transition in machine.recovery_transitions] == [
        SettlementState.STRANDED_INVENTORY,
        SettlementState.RECOVERED,
    ]
    with pytest.raises(DoubleReleaseError, match="LOCK_DOUBLE_RELEASE"):
        machine.release_lock(reason="second_release")
    assert machine.lock_snapshot().release_count == 1

    fresh = _machine()
    with pytest.raises(SettlementError, match="LOCK_NOT_TERMINAL"):
        fresh.release_lock(reason="premature_release")


def test_locked_capital_conservation_and_duplicate_registration() -> None:
    ledger = CapitalLockLedger()
    finalized = _machine("pos-finalized", 100)
    recovered = _machine("pos-recovered", 200)
    outstanding = _machine("pos-outstanding", 300)
    ledger.register(finalized)
    ledger.register(recovered)
    ledger.register(outstanding)

    execute_settlement_plan(finalized, _happy_plan())
    execute_settlement_plan(recovered, inject_reorg_at(_happy_plan(), step=1))
    recovered.transition(SettlementState.STRANDED_INVENTORY, reason="stranded")
    recovered.transition(SettlementState.RECOVERED, reason="recovered")

    report = ledger.conservation_report()
    assert report["lock_count"] == 3
    assert report["released_lock_count"] == 2
    assert report["total_registered_atoms"] == 600
    assert report["total_released_atoms"] == 300
    assert report["total_outstanding_atoms"] == 300

    with pytest.raises(SettlementError, match="LOCK_DUPLICATE_REGISTRATION"):
        ledger.register(_machine("pos-finalized", 100))

    assert finalized.lock_snapshot().amount_atoms == 100
    assert outstanding.lock_snapshot().amount_atoms == 300


def test_atomic_mislabel_guard_raises_without_proof() -> None:
    assert EXECUTION_CLASS == "SIGNAL_ONLY_ASYNC"
    source, target = _domains()
    path = SettlementPath(
        path_id="path-bridge",
        source_domain=source,
        target_domain=target,
        settlement_mechanism="BRIDGE",
    )
    assert classify_execution_class(path) == "SIGNAL_ONLY_ASYNC"
    with pytest.raises(AtomicityClassificationError, match="ATOMIC_MISLABEL_UNPROVEN"):
        classify_execution_class(path, claimed_class="LOCAL_ATOMIC")
    with pytest.raises(AtomicityClassificationError, match="ATOMIC_MISLABEL_UNPROVEN"):
        classify_execution_class(
            path, claimed_class="LOCAL_ATOMIC", single_tx_settlement_proven=False
        )
    assert (
        classify_execution_class(
            path, claimed_class="LOCAL_ATOMIC", single_tx_settlement_proven=True
        )
        == "LOCAL_ATOMIC"
    )
    with pytest.raises(SettlementError, match="CLAIMED_CLASS_UNKNOWN"):
        classify_execution_class(path, claimed_class="HFT_ATOMIC")
    with pytest.raises(SettlementError, match="MECHANISM_UNKNOWN"):
        SettlementPath(
            path_id="path-bad",
            source_domain=source,
            target_domain=target,
            settlement_mechanism="WARP",
        )


def test_settlement_traces_are_deterministic() -> None:
    first = execute_settlement_plan(
        _machine("pos-det", 100), inject_reorg_at(_happy_plan(), step=2)
    )
    second = execute_settlement_plan(
        _machine("pos-det", 100), inject_reorg_at(_happy_plan(), step=2)
    )
    assert first == second
    assert first.final_state is SettlementState.REORGED

    happy_first = execute_settlement_plan(_machine("pos-det2", 100), _happy_plan())
    happy_second = execute_settlement_plan(_machine("pos-det2", 100), _happy_plan())
    assert happy_first == happy_second
    assert happy_first.final_state is SettlementState.FINALIZED
