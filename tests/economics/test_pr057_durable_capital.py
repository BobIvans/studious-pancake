from __future__ import annotations

import asyncio

from src.economics.capital import (
    CapitalCandidate,
    CapitalPolicy,
    NativeCostBreakdown,
    NoTradeReason,
    lamports_from_sol_string,
)
from src.economics.durable_reservations import (
    DurableCapitalLedger,
    active_reservation_ids,
)
from src.economics.runtime_precheck import (
    CapitalEngineOpportunityPrecheck,
    build_capital_precheck,
    opportunity_to_capital_candidate,
)
from src.strategy.domain import Opportunity


def _candidate(candidate_id: str = "candidate-1") -> CapitalCandidate:
    return CapitalCandidate(
        candidate_id=candidate_id,
        guaranteed_min_out_lamports=12_000_000,
        flash_repayment_lamports=10_000_000,
        requested_flash_loan_lamports=10_000_000,
        native_costs=NativeCostBreakdown(
            base_network_fee_lamports=5_000,
            priority_fee_lamports=50_000,
            jito_tip_lamports=1_000,
            peak_rent_lamports=1_000_000,
            rent_loss_lamports=0,
        ),
        protocol_fee_lamports=10_000,
        slippage_buffer_lamports=10_000,
        uncertainty_buffer_lamports=10_000,
        message_hash="abc123",
    )


def test_pr057_durable_reservation_survives_restart_and_releases(tmp_path):
    policy = CapitalPolicy(
        protected_reserve_lamports=10_000_000,
        minimum_net_profit_lamports=100_000,
        maximum_priority_fee_lamports=100_000,
        maximum_jito_tip_lamports=10_000,
        maximum_peak_rent_lamports=2_000_000,
        contingency_lamports=500_000,
    )
    db_path = tmp_path / "capital.sqlite"
    wallet_lamports = lamports_from_sol_string("0.015")

    ledger = DurableCapitalLedger(
        db_path,
        wallet_lamports=wallet_lamports,
        policy=policy,
    )
    decision = ledger.reserve(_candidate())

    assert decision.allowed is True
    assert decision.reason is NoTradeReason.TRADE_PERMITTED
    assert decision.reservation_id is not None

    recovered = DurableCapitalLedger(
        db_path,
        wallet_lamports=wallet_lamports,
        policy=policy,
    )
    snapshot = recovered.snapshot()

    assert snapshot.active_reserved_lamports == decision.required_native_lamports
    assert active_reservation_ids(snapshot) == (decision.reservation_id,)
    assert recovered.available_native_lamports() < wallet_lamports
    assert recovered.release(decision.reservation_id) is True
    assert recovered.release(decision.reservation_id) is False
    assert recovered.snapshot().active_reserved_lamports == 0


def test_pr057_protected_reserve_blocks_second_candidate(tmp_path):
    policy = CapitalPolicy(
        protected_reserve_lamports=10_000_000,
        minimum_net_profit_lamports=100_000,
        maximum_priority_fee_lamports=100_000,
        maximum_jito_tip_lamports=10_000,
        maximum_peak_rent_lamports=2_000_000,
        contingency_lamports=500_000,
    )
    ledger = DurableCapitalLedger(
        tmp_path / "capital.sqlite",
        wallet_lamports=lamports_from_sol_string("0.015"),
        policy=policy,
    )

    first = ledger.reserve(_candidate("first"))
    second = ledger.reserve(_candidate("second"))

    assert first.allowed is True
    assert second.allowed is False
    assert second.reason is NoTradeReason.INSUFFICIENT_NATIVE_BALANCE
    assert ledger.snapshot().active_reserved_lamports == first.required_native_lamports


def test_pr057_opportunity_precheck_uses_canonical_capital_engine(tmp_path):
    policy = CapitalPolicy(
        protected_reserve_lamports=10_000_000,
        minimum_net_profit_lamports=100_000,
        maximum_priority_fee_lamports=100_000,
        maximum_jito_tip_lamports=10_000,
        maximum_peak_rent_lamports=2_000_000,
        contingency_lamports=500_000,
    )
    ledger = DurableCapitalLedger(
        tmp_path / "capital.sqlite",
        wallet_lamports=lamports_from_sol_string("0.015"),
        policy=policy,
    )
    precheck = CapitalEngineOpportunityPrecheck(ledger, reserve=True)
    opportunity = Opportunity.create(
        strategy_name="circular_arbitrage",
        opportunity_type="recorded_fixture",
        detection_slot=123,
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="So11111111111111111111111111111111111111112",
        proposed_amount_base_units=10_000_000,
        expected_gross_profit=2_000_000.0,
        ttl_seconds=30,
        metadata={
            "gross_profit_lamports": 2_000_000,
            "base_network_fee_lamports": 5_000,
            "priority_fee_lamports": 50_000,
            "jito_tip_lamports": 1_000,
            "peak_rent_lamports": 1_000_000,
            "protocol_fee_lamports": 10_000,
            "slippage_buffer_lamports": 10_000,
            "uncertainty_buffer_lamports": 10_000,
            "message_hash": "abc123",
        },
    )

    decision = asyncio.run(precheck.assess(opportunity))

    assert decision.allowed is True
    assert decision.reason_code == "trade_permitted"
    assert decision.details["reservation_id"] is not None
    assert ledger.snapshot().active_reserved_lamports == int(
        decision.details["required_native_lamports"]
    )


def test_pr057_precheck_requires_real_wallet_snapshot():
    precheck = build_capital_precheck(config=None)
    opportunity = Opportunity.create(
        strategy_name="circular_arbitrage",
        opportunity_type="recorded_fixture",
        detection_slot=123,
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="So11111111111111111111111111111111111111112",
        proposed_amount_base_units=10_000_000,
        expected_gross_profit=2_000_000.0,
        ttl_seconds=30,
        metadata={"gross_profit_lamports": 2_000_000},
    )

    decision = asyncio.run(precheck.assess(opportunity))

    assert decision.allowed is False
    assert decision.reason_code == "capital_wallet_snapshot_missing"


def test_pr057_opportunity_mapper_fails_closed_without_economic_floor():
    opportunity = Opportunity.create(
        strategy_name="circular_arbitrage",
        opportunity_type="recorded_fixture",
        detection_slot=123,
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="So11111111111111111111111111111111111111112",
        proposed_amount_base_units=10_000_000,
        expected_gross_profit=2_000_000.0,
        ttl_seconds=30,
        metadata={"base_network_fee_lamports": 5_000},
    )

    try:
        opportunity_to_capital_candidate(opportunity)
    except Exception as exc:  # noqa: BLE001 - assert stable fail-closed message
        assert "guaranteed_min_out_lamports" in str(exc)
    else:
        raise AssertionError("missing economics must fail closed")
