from dataclasses import replace
import hashlib

import pytest

from src.inventory import (
    AllocationCandidate,
    Disposition,
    DurableInventoryLedger,
    FillReceipt,
    InstrumentIdentity,
    InventoryError,
    InventoryQualificationEvidence,
    MarketRights,
    NonAtomicHypothesis,
    OrderIntent,
    OrderSide,
    OrderStatus,
    RecoveryAction,
    ResearchError,
    StrategyFamily,
    allocate_inventory_budget,
    evaluate_hypothesis,
    qualify_inventory_platform,
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _instrument() -> InstrumentIdentity:
    return InstrumentIdentity(
        venue="example-exchange",
        instrument="BTC-PERP",
        settlement_asset="USDC",
        quantity_unit="satoshi",
    )


def _intent() -> OrderIntent:
    return OrderIntent(
        client_order_id="client-1",
        strategy_id="basis-1",
        instrument=_instrument(),
        side=OrderSide.BUY,
        quantity_base_units=100,
        max_partial_fill_loss_quote_units=50,
        created_at_ns=100,
        policy_sha256=_h("policy"),
    )


def _fill(
    *,
    fill_id: str = "fill-1",
    quantity: int = 40,
    cash: int = -4_000,
) -> FillReceipt:
    return FillReceipt(
        fill_id=fill_id,
        client_order_id="client-1",
        exchange_order_id="ex-1",
        quantity_base_units=quantity,
        cash_delta_quote_base_units=cash,
        fee_quote_base_units=5,
        observed_at_ns=300,
        evidence_sha256=_h(fill_id),
    )


def test_agg13_partial_fill_survives_restart_and_requires_recovery(
    tmp_path,
) -> None:
    path = tmp_path / "inventory.sqlite3"
    with DurableInventoryLedger(path) as ledger:
        ledger.register_order(_intent())
        ledger.acknowledge_order(
            client_order_id="client-1",
            exchange_order_id="ex-1",
            observed_at_ns=200,
        )
        order, position = ledger.record_fill(_fill())
        assert order.status is OrderStatus.PARTIALLY_FILLED
        assert order.remaining_quantity_base_units == 60
        assert position.signed_quantity_base_units == 40
        plan = ledger.recovery_plan("client-1")
        assert plan.exposure_open is True
        assert RecoveryAction.CANCEL_REMAINDER in plan.actions
        assert RecoveryAction.HEDGE_OPEN_POSITION in plan.actions

    with DurableInventoryLedger(path) as reopened:
        order = reopened.order_snapshot("client-1")
        position = reopened.position_for_order("client-1")
        assert order.cumulative_filled_base_units == 40
        assert position.signed_quantity_base_units == 40
        assert reopened.recovery_plan("client-1").exposure_open is True


def test_agg13_duplicate_fill_is_idempotent_and_conflict_rejected(
    tmp_path,
) -> None:
    with DurableInventoryLedger(tmp_path / "inventory.sqlite3") as ledger:
        ledger.register_order(_intent())
        ledger.acknowledge_order(
            client_order_id="client-1",
            exchange_order_id="ex-1",
            observed_at_ns=200,
        )
        ledger.record_fill(_fill())
        ledger.record_fill(_fill())
        assert ledger.position_for_order("client-1").signed_quantity_base_units == 40
        with pytest.raises(
            InventoryError,
            match="AGG13_FILL_IDEMPOTENCY_CONFLICT",
        ):
            ledger.record_fill(_fill(quantity=41, cash=-4_100))


def test_agg13_cancel_race_and_missing_fill_are_not_fabricated(tmp_path) -> None:
    with DurableInventoryLedger(tmp_path / "inventory.sqlite3") as ledger:
        ledger.register_order(_intent())
        ledger.acknowledge_order(
            client_order_id="client-1",
            exchange_order_id="ex-1",
            observed_at_ns=200,
        )
        ledger.mark_status(
            client_order_id="client-1",
            status=OrderStatus.CANCEL_PENDING,
            observed_at_ns=250,
        )
        order, _ = ledger.record_fill(_fill())
        assert order.status is OrderStatus.CANCEL_PENDING
        reconciled = ledger.reconcile_exchange_state(
            client_order_id="client-1",
            exchange_status=OrderStatus.CANCELED,
            exchange_cumulative_filled_base_units=45,
            observed_at_ns=400,
        )
        assert reconciled.status is OrderStatus.UNKNOWN
        plan = ledger.recovery_plan("client-1")
        assert RecoveryAction.RECONCILE_UNKNOWN_ORDER in plan.actions
        assert plan.exposure_open is True


def _rights(**overrides) -> MarketRights:
    values = dict(
        venue="example-exchange",
        instrument="BTC-PERP",
        market_data_allowed=True,
        trading_access_verified=True,
        settlement_verified=True,
        session_open=True,
        redemption_right_verified=True,
        compliance_access_verified=True,
        rights_evidence_sha256=_h("rights"),
    )
    values.update(overrides)
    return MarketRights(**values)


def _hypothesis(
    family: StrategyFamily,
    **overrides,
) -> NonAtomicHypothesis:
    values = dict(
        family=family,
        hypothesis_id=f"hyp-{family.value}",
        leg_ids=("leg-a", "leg-b"),
        atomic_claim=False,
        prefunded_inventory=True,
        hedge_plan_verified=True,
        funding_schedule_verified=True,
        margin_stress_passed=True,
        statistical_controls_verified=True,
        transfer_required_for_same_cycle=True,
        max_unhedged_loss_quote_units=10,
        tail_loss_budget_quote_units=20,
        evidence_sha256=_h(family.value),
    )
    values.update(overrides)
    return NonAtomicHypothesis(**values)


def test_agg13_cross_chain_never_atomic_and_closed_session_blocks() -> None:
    atomic = evaluate_hypothesis(
        _hypothesis(StrategyFamily.CROSS_CHAIN, atomic_claim=True),
        rights=(_rights(), _rights(instrument="ETH-PERP")),
    )
    assert atomic.disposition is Disposition.BLOCKED
    assert atomic.atomic_execution_allowed is False
    assert (
        "AGG13_NON_ATOMIC_STRATEGY_CANNOT_CLAIM_ATOMIC_EXECUTION"
        in atomic.blockers
    )

    closed = evaluate_hypothesis(
        _hypothesis(StrategyFamily.RWA_RIGHTS),
        rights=(
            _rights(session_open=False),
            _rights(instrument="RWA-2"),
        ),
    )
    assert closed.disposition is Disposition.BLOCKED
    assert "AGG13_MARKET_SESSION_CLOSED" in closed.blockers


def test_agg13_research_only_families_do_not_promote_to_execution() -> None:
    verdict = evaluate_hypothesis(
        _hypothesis(StrategyFamily.FIAT_P2P),
        rights=(_rights(), _rights(instrument="FIAT-2")),
    )
    assert verdict.disposition is Disposition.RESEARCH_ONLY
    assert verdict.atomic_execution_allowed is False


def test_agg13_allocator_preserves_gas_and_tail_budget() -> None:
    decision = allocate_inventory_budget(
        candidates=(
            AllocationCandidate("a", 100, 100, 50, priority=0),
            AllocationCandidate("b", 100, 100, 100, priority=1),
        ),
        free_capital_quote_units=180,
        reserved_gas_quote_units=30,
        tail_loss_budget_quote_units=80,
    )
    allocations = dict(decision.allocations)
    assert allocations["a"] == 100
    assert allocations["b"] == 30
    assert decision.unallocated_quote_units == 20
    assert decision.remaining_tail_loss_budget_quote_units == 0

    with pytest.raises(
        ResearchError,
        match="AGG13_MODEL_CANNOT_INCREASE_REVIEWED_EXPOSURE",
    ):
        replace(
            AllocationCandidate("x", 10, 10, 1, 0),
            model_scale_bps=10_001,
        )


def test_agg13_inventory_qualification_is_scope_bound_and_no_live() -> None:
    evidence = InventoryQualificationEvidence(
        restart_replay_passed=True,
        partial_fill_model_passed=True,
        actual_reconciliation_passed=False,
        disconnect_recovery_passed=True,
        funding_flip_stress_passed=True,
        margin_shock_passed=True,
        instrument_access_verified=True,
        scope_sha256=_h("scope"),
    )
    verdict = qualify_inventory_platform(evidence)
    assert verdict.qualified is False
    assert "AGG13_ACTUAL_RECONCILIATION_MISSING" in verdict.blockers
    assert verdict.live_authorized is False

    complete = qualify_inventory_platform(
        replace(evidence, actual_reconciliation_passed=True)
    )
    assert complete.qualified is True
    assert complete.live_authorized is False
