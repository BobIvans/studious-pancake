from __future__ import annotations

import pytest

from src.mega8_07.core import (
    CapitalEvidence,
    EvidenceBinding,
    MarginRequirement,
    Mega807Error,
    RatePoint,
)
from src.mega8_07.pr279 import (
    apply_growth_policy,
    cap_profit_redeployment,
    compute_reinvestment_budget,
    reconcile_growth_cycle,
)
from src.mega8_07.pr280 import (
    allocate_wallet_roles,
    audit_wallet_segregation,
    isolate_canary_treasury,
    rotate_wallet_generation,
)
from src.mega8_07.pr281 import (
    detect_capacity_shortfall,
    forecast_flash_liquidity,
    release_capacity_reservation,
    reserve_lender_capacity,
)
from src.mega8_07.pr282 import (
    gate_non_atomic_leverage,
    normalize_margin_requirements,
    optimize_collateral_allocation,
    simulate_margin_liquidation,
)
from src.mega8_07.pr283 import (
    build_rate_arbitrage_plan,
    collect_lending_rate_curves,
    detect_borrow_supply_spread,
    qualify_rate_strategy,
)
from src.mega8_07.pr284 import (
    StablecoinReserveModel,
    emit_depeg_risk_signal,
    ingest_redemption_capacity,
    register_stablecoin_reserve_model,
    stress_stablecoin_run,
)
from src.mega8_07.pr285 import (
    FixedRateInstrument,
    build_term_structure_curve,
    detect_term_basis,
    normalize_fixed_rate_instruments,
    qualify_term_structure_trade,
)
from src.mega8_07.pr286 import (
    LiquidationMechanism,
    allocate_liquidation_capital,
    index_cross_protocol_liquidations,
    reconcile_liquidation_portfolio,
    value_protocol_owned_collateral,
)


def evidence() -> EvidenceBinding:
    return EvidenceBinding(
        "evidence-capital",
        "b" * 64,
        "generation-capital",
        "policy-capital",
        1,
        100,
    )


def test_reinvestment_uses_only_finalized_spendable_capacity() -> None:
    capital = CapitalEvidence(
        finalized_profit=50,
        protected_reserve=20,
        available_balance=100,
        capacity_limit=40,
        evidence=evidence(),
    )
    assert compute_reinvestment_budget(capital, now=2) == 40
    assert (
        apply_growth_policy(
            40,
            current_scale=100,
            max_growth_ppm=200_000,
        )
        == 20
    )
    assert (
        cap_profit_redeployment(
            30,
            capacity_limit=25,
        )
        == 25
    )
    assert (
        cap_profit_redeployment(
            30,
            capacity_limit=25,
            protected_reserve_shortfall=1,
        )
        == 0
    )
    cycle = reconcile_growth_cycle(
        starting_capital=100,
        redeployed=20,
        finalized_delta=5,
    )
    assert cycle["ending"] == 105


def test_wallet_roles_are_segregated_and_pending_unknowns_block_rotation() -> None:
    roles = allocate_wallet_roles(
        ("wallet-canary", "wallet-treasury", "wallet-research", "wallet-settlement")
    )
    assert isolate_canary_treasury(roles)
    rotated = rotate_wallet_generation(
        roles,
        generation=1,
    )
    assert rotated["generation"] == 2
    assert audit_wallet_segregation(
        roles,
        (("wallet-research", "wallet-treasury"),),
    ) == ("RESEARCH_TO_TREASURY_REQUIRES_SEPARATE_ADMISSION",)
    with pytest.raises(Mega807Error, match="PENDING_UNKNOWN"):
        rotate_wallet_generation(
            roles,
            generation=1,
            pending_unknown_roles=("research",),
        )


def test_flash_liquidity_forecast_and_reservation_are_conservative() -> None:
    capacity = forecast_flash_liquidity(
        lender_id="lender-1",
        asset_id="USDC",
        observations=(100, 80, 90, 70),
        generation="g1",
        evidence=evidence(),
        now=2,
    )
    assert capacity.conservative_capacity == 70
    reservation = reserve_lender_capacity(
        capacity,
        amount=60,
        reservation_id="reservation-1",
        now=2,
    )
    assert reservation.amount == 60
    assert not detect_capacity_shortfall(
        capacity,
        required_amount=60,
        current_generation="g1",
    )
    assert release_capacity_reservation(reservation).released
    with pytest.raises(Mega807Error, match="SHORTFALL"):
        reserve_lender_capacity(
            capacity,
            amount=71,
            reservation_id="reservation-2",
            now=2,
        )


def test_margin_optimizer_stays_in_separate_non_atomic_domain() -> None:
    requirements = (
        MarginRequirement("venue-a", "USDC", 500_000, 250_000),
        MarginRequirement("venue-b", "SOL", 400_000, 200_000),
    )
    assert normalize_margin_requirements(requirements) == requirements
    allocations = optimize_collateral_allocation(
        requirements,
        {"USDC": 100, "SOL": 100},
    )
    assert allocations == (("venue-a:USDC", 50), ("venue-b:SOL", 40))
    stress = simulate_margin_liquidation(
        collateral_value=100,
        debt_value=80,
        maintenance_margin_ppm=100_000,
        stress_loss=20,
    )
    assert stress["liquidatable"] is True
    assert gate_non_atomic_leverage(
        gross_exposure=150,
        equity=100,
        max_leverage_ppm=2_000_000,
    )
    with pytest.raises(Mega807Error, match="LEVERAGE"):
        gate_non_atomic_leverage(
            gross_exposure=300,
            equity=100,
            max_leverage_ppm=2_000_000,
        )


def test_credit_rate_plan_requires_capacity_costs_and_inventory_permission() -> None:
    supply = RatePoint("supply", "USDC", 100_000, 0, 1000, 10)
    borrow = RatePoint("borrow", "USDC", 0, 20_000, 500, 10)
    assert collect_lending_rate_curves(
        (supply, borrow),
        cutoff=10,
    ) == (borrow, supply)
    assert detect_borrow_supply_spread(supply, borrow) == 80_000
    plan = build_rate_arbitrage_plan(
        supply=supply,
        borrow=borrow,
        amount=100,
        rebalance_cost=2,
    )
    assert plan["net_carry"] == 6
    assert qualify_rate_strategy(
        plan,
        minimum_net_carry=5,
        inventory_permission=True,
    )
    with pytest.raises(Mega807Error, match="INVENTORY_PERMISSION"):
        qualify_rate_strategy(
            plan,
            minimum_net_carry=5,
            inventory_permission=False,
        )


def test_stablecoin_stress_is_risk_signal_not_trade_authority() -> None:
    model = StablecoinReserveModel(
        asset_id="USDx",
        reserve_components={"cash": 80, "bonds": 20},
        redemption_capacity=70,
        queue_depth=0,
        evidence=evidence(),
    )
    assert len(register_stablecoin_reserve_model(model, now=2)) == 64
    assert ingest_redemption_capacity(model, now=2) == (70, 0)
    stress = stress_stablecoin_run(
        model,
        redemption_demand=90,
        reserve_haircut_ppm=200_000,
    )
    signal = emit_depeg_risk_signal(stress, signal_threshold=10)
    assert signal == {
        "risk_signal": True,
        "unmet_demand": 20,
        "trade_authority": False,
    }


def test_term_structure_separates_atomic_parity_from_carry() -> None:
    left = FixedRateInstrument("left", "USDC", 100, 100, 110, 1)
    right = FixedRateInstrument("right", "USDC", 100, 100, 105, 1)
    assert normalize_fixed_rate_instruments((right, left)) == (left, right)
    curve = build_term_structure_curve((left, right), cutoff=1)
    assert curve == ((100, 100_000), (100, 50_000))
    assert detect_term_basis(left, right) == 50_000
    atomic = qualify_term_structure_trade(
        basis_ppm=50_000,
        minimum_basis_ppm=10_000,
        atomic=True,
    )
    carry = qualify_term_structure_trade(
        basis_ppm=50_000,
        minimum_basis_ppm=10_000,
        atomic=False,
    )
    assert atomic["verdict"] == "PARITY_RESEARCH"
    assert carry["verdict"] == "CARRY_RESEARCH"
    assert not atomic["live_authority"]


def test_liquidation_portfolio_counts_shared_resource_once_and_reconciles() -> None:
    rows = (
        LiquidationMechanism("a", "proto-a", "SOL", 100, 90, 5, 20, "reserve-1"),
        LiquidationMechanism("b", "proto-b", "SOL", 80, 80, 5, 20, "reserve-1"),
        LiquidationMechanism("c", "proto-c", "USDC", 60, 60, 5, 20, "reserve-2"),
    )
    indexed = index_cross_protocol_liquidations(rows)
    assert len(indexed) == 3
    assert value_protocol_owned_collateral(rows[0]) == 85
    selected = allocate_liquidation_capital(rows, capital_budget=40)
    assert selected == ("a", "c")
    receipt = reconcile_liquidation_portfolio(
        selected,
        {"a": 10, "c": -2},
    )
    assert receipt["finalized_total"] == 8

def test_liquidation_portfolio_rejects_duplicate_mechanisms_and_selected_ids() -> None:
    duplicated = (
        LiquidationMechanism("a", "proto-a", "SOL", 100, 90, 5, 20, "reserve-1"),
        LiquidationMechanism("a", "proto-b", "USDC", 60, 60, 5, 20, "reserve-2"),
    )
    with pytest.raises(Mega807Error, match="DUPLICATE_LIQUIDATION_MECHANISM"):
        allocate_liquidation_capital(duplicated, capital_budget=40)
    with pytest.raises(Mega807Error, match="DUPLICATE_SELECTED_LIQUIDATION"):
        reconcile_liquidation_portfolio(("a", "a"), {"a": 10})
