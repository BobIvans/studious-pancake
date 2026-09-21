from __future__ import annotations

import pytest

from src.mega8_03.common import EvidenceEnvelope, OfflineStatus
from src.mega8_03.pr186_keeper import (
    build_authorized_keeper_plan,
    discover_rebalance_jobs,
    price_keeper_reward_and_cost,
    qualify_keeper_operation,
)
from src.mega8_03.pr187_clmm import (
    detect_rebalance_residual,
    emit_clmm_position_candidate,
    estimate_fee_growth_dislocation,
    measure_clmm_range_pressure,
)
from src.mega8_03.pr188_rfq import (
    build_limit_order_fill_plan,
    ingest_solana_intent_quotes,
    price_rfq_fill_path,
    qualify_opt_in_intent_fill,
)
from src.mega8_03.pr189_orderflow import (
    detect_post_execution_residual,
    enforce_orderflow_permissions,
    estimate_scheduled_flow_impact,
    index_trigger_and_dca_orders,
)
from src.mega8_03.pr190_perp_research import (
    collect_perp_mark_index_funding,
    detect_spot_perp_basis,
    normalize_perp_contract_specs,
    rank_inventory_required_basis,
)
from src.mega8_03.pr191_spot_perp_sandbox import (
    build_spot_perp_hedge_plan,
    reconcile_hedged_position,
    reserve_margin_and_inventory,
    simulate_partial_fill_risk,
)
from src.mega8_03.pr192_liquidation_competition import (
    cluster_liquidation_queue,
    estimate_liquidation_competition,
    rank_tail_liquidations,
    simulate_liquidation_cascade,
)
from src.mega8_03.pr193_market_activation import (
    compare_router_direct_coverage,
    detect_new_market_activation,
    qualify_new_market_worker,
    verify_liquid_exit_path,
)
from src.mega8_03.pr194_recoveries import (
    attribute_affiliate_or_fee_refund,
    attribute_positive_slippage,
    attribute_transaction_rebate,
    reconcile_recovery_components,
)


def env(**overrides) -> EvidenceEnvelope:
    values = {
        "evidence_id": "fixture",
        "evidence_sha256": "a" * 64,
        "state_generation": "state-1",
        "deployment_generation": "deploy-1",
        "policy_generation": "policy-1",
        "observed_at_ns": 10,
        "available_at_ns": 20,
    }
    values.update(overrides)
    return EvidenceEnvelope(**values)


def assert_offline(decision) -> None:
    assert decision.execution_authority is False
    assert decision.signing_allowed is False
    assert decision.submission_allowed is False
    assert decision.live_enabled is False
    assert decision.automatic_capital_increase_allowed is False


def test_common_boundary_rejects_execution_authority() -> None:
    with pytest.raises(ValueError, match="cannot grant"):
        env(signer_allowed=True)


def test_pr186_keeper_contract_is_permission_and_net_bound() -> None:
    jobs = discover_rebalance_jobs(
        (
            {
                "job_id": "j1",
                "permission_ref": "permit-1",
                "authorized": True,
                "deployment_verified": True,
                "capacity_atomic": 100,
                "reward_atomic": 12,
            },
            {
                "job_id": "j2",
                "permission_ref": "permit-2",
                "authorized": False,
                "deployment_verified": True,
                "capacity_atomic": 100,
                "reward_atomic": 12,
            },
        ),
        envelope=env(),
    )
    assert [row["job_id"] for row in jobs] == ["j1"]
    economics = price_keeper_reward_and_cost(
        reward_atomic=12,
        network_fee_atomic=2,
        tip_atomic=1,
        state_change_cost_atomic=1,
    )
    plan = build_authorized_keeper_plan(jobs[0], economics, envelope=env())
    result = qualify_keeper_operation(plan, envelope=env())
    assert result.status is OfflineStatus.QUALIFIED_OFFLINE
    assert result.payload["economics"]["conservative_net_atomic"] == 8
    assert_offline(result)


def test_pr187_clmm_is_research_only_and_integer_bounded() -> None:
    pressure = measure_clmm_range_pressure(
        current_index=11,
        lower_index=10,
        upper_index=20,
        active_liquidity_atomic=1_000,
    )
    residual = detect_rebalance_residual(
        reference_price_ppm=1_000_000,
        post_rebalance_price_ppm=1_020_000,
        minimum_dislocation_ppm=10_000,
    )
    fee = estimate_fee_growth_dislocation(
        observed_fee_growth_atomic=15,
        expected_fee_growth_atomic=10,
        position_liquidity_atomic=100,
    )
    result = emit_clmm_position_candidate(
        envelope=env(),
        range_pressure=pressure,
        residual=residual,
        fee_growth=fee,
        minimum_net_atomic=0,
        conservative_net_atomic=5,
    )
    assert pressure["pressure_ppm"] > 0
    assert residual["actionable_offline"] is True
    assert result.status is OfflineStatus.RESEARCH_ONLY
    assert_offline(result)


def test_pr188_rfq_requires_opt_in_expiry_and_economic_advantage() -> None:
    rows = ingest_solana_intent_quotes(
        (
            {
                "intent_id": "i1",
                "quote_id": "q1",
                "opt_in": True,
                "expires_at_ns": 100,
            },
            {
                "intent_id": "i2",
                "quote_id": "q2",
                "opt_in": False,
                "expires_at_ns": 100,
            },
        ),
        now_ns=50,
    )
    assert len(rows) == 1
    economics = price_rfq_fill_path(
        offered_output_atomic=110,
        direct_route_output_atomic=100,
        execution_cost_atomic=2,
    )
    plan = build_limit_order_fill_plan(rows[0], economics, envelope=env())
    result = qualify_opt_in_intent_fill(plan, envelope=env(), now_ns=60)
    assert result.status is OfflineStatus.QUALIFIED_OFFLINE
    assert economics["rfq_advantage_atomic"] == 8
    assert_offline(result)


def test_pr189_orderflow_never_authorizes_harmful_preexecution_ordering() -> None:
    rows = index_trigger_and_dca_orders(
        (
            {
                "order_id": "o1",
                "public_or_opt_in": True,
                "scheduled_amount_atomic": 100,
            },
            {
                "order_id": "o2",
                "public_or_opt_in": False,
                "scheduled_amount_atomic": 100,
            },
        )
    )
    assert len(rows) == 1
    assert (
        estimate_scheduled_flow_impact(
            scheduled_amount_atomic=10,
            visible_liquidity_atomic=100,
        )["estimated_impact_ppm"]
        == 100_000
    )
    residual = detect_post_execution_residual(
        execution_finalized=True,
        pre_reference_atomic=100,
        post_state_atomic=120,
        minimum_residual_atomic=10,
    )
    assert residual["eligible_post_state_only"] is True
    rejected = enforce_orderflow_permissions(
        envelope=env(),
        public_or_opt_in=True,
        execution_finalized=False,
        attempts_pre_execution_ordering=True,
    )
    assert rejected.status is OfflineStatus.REJECTED
    assert "HARMFUL_FRONTRUN_POLICY_FORBIDDEN" in rejected.reason_codes
    assert_offline(rejected)


def test_pr190_perp_basis_is_inventory_research_only() -> None:
    observations = collect_perp_mark_index_funding(
        (
            {
                "market_id": "SOL-PERP",
                "mark_price_atomic": 105,
                "index_price_atomic": 100,
                "funding_rate_ppm": 10,
                "open_interest_atomic": 1_000,
                "available_at_ns": 50,
            },
        )
    )
    spec = normalize_perp_contract_specs(
        {
            "market_id": "SOL-PERP",
            "base_lot_atomic": 1,
            "quote_lot_atomic": 1,
            "maintenance_margin_ppm": 50_000,
            "max_leverage_ppm": 5_000_000,
        }
    )
    basis = detect_spot_perp_basis(spot_price_atomic=100, perp_mark_atomic=105)
    ranked = rank_inventory_required_basis(
        (
            {
                "market_id": "SOL-PERP",
                "conservative_net_atomic": 5,
                "required_margin_atomic": 100,
            },
        ),
        envelope=env(),
    )
    assert observations[0]["market_id"] == spec["market_id"]
    assert basis["basis_ppm"] == 50_000
    assert ranked[0].status is OfflineStatus.RESEARCH_ONLY
    assert_offline(ranked[0])


def test_pr191_spot_perp_sandbox_keeps_non_atomic_domain_separate() -> None:
    plan = build_spot_perp_hedge_plan(
        spot_amount_atomic=100,
        perp_hedge_amount_atomic=100,
        max_holding_ns=1_000,
        envelope=env(),
    )
    reservation = reserve_margin_and_inventory(
        plan,
        available_margin_atomic=100,
        available_inventory_atomic=100,
        required_margin_atomic=50,
    )
    risk = simulate_partial_fill_risk(
        spot_filled_atomic=100,
        perp_filled_atomic=100,
        reference_price_atomic=2,
        stress_move_ppm=100_000,
    )
    result = reconcile_hedged_position(
        envelope=env(),
        reservation=reservation,
        partial_fill_risk=risk,
        finalized=True,
    )
    assert plan["atomic_profile"] is False
    assert reservation["reservation_is_internal_only"] is True
    assert risk["unhedged_atomic"] == 0
    assert result.status is OfflineStatus.RESEARCH_ONLY
    assert_offline(result)


def test_pr192_liquidation_competition_uses_bonus_minus_exit_and_competition() -> None:
    competition = estimate_liquidation_competition(
        competing_signatures=10,
        landed_competitors=4,
        observation_windows=5,
    )
    clusters = cluster_liquidation_queue(
        (
            {"position_id": "p1", "health_ppm": 100},
            {"position_id": "p2", "health_ppm": 120},
        ),
        bucket_width_ppm=50,
    )
    cascade = simulate_liquidation_cascade(
        (
            {"health_buffer_ppm": 50_000, "debt_atomic": 100},
            {"health_buffer_ppm": 200_000, "debt_atomic": 200},
        ),
        price_shock_ppm=100_000,
    )
    ranked = rank_tail_liquidations(
        (
            {
                "position_id": "p1",
                "bonus_atomic": 20,
                "exit_cost_atomic": 5,
                "competition_cost_atomic": 3,
            },
        ),
        envelope=env(),
    )
    assert competition["landed_share_ppm"] == 400_000
    assert clusters
    assert cascade["triggered_positions"] == 1
    assert ranked[0].payload["conservative_net_atomic"] == 12
    assert_offline(ranked[0])


def test_pr193_market_activation_requires_verified_liquid_exit() -> None:
    activated = detect_new_market_activation(
        (
            {
                "market_id": "m1",
                "deployment_verified": True,
                "active": True,
                "available_at_ns": 1,
            },
        )
    )
    coverage = compare_router_direct_coverage(
        router_market_ids=("m1",),
        direct_market_ids=("m1", "m2"),
    )
    exit_path = verify_liquid_exit_path(
        exit_capacity_atomic=100,
        required_exit_atomic=50,
        quote_current=True,
        token_semantics_verified=True,
    )
    result = qualify_new_market_worker(
        envelope=env(),
        coverage=coverage,
        exit_path=exit_path,
        direct_adapter_qualified=True,
    )
    assert activated[0]["market_id"] == "m1"
    assert coverage["direct_only"] == ("m2",)
    assert result.status is OfflineStatus.RESEARCH_ONLY
    assert_offline(result)


def test_pr194_recovery_attribution_does_not_relabel_recovery_as_alpha() -> None:
    assert (
        attribute_positive_slippage(
            quoted_output_atomic=100, finalized_output_atomic=105
        )
        == 5
    )
    assert (
        attribute_transaction_rebate(finalized_rebate_atomic=4, receipt_verified=True)
        == 4
    )
    assert (
        attribute_affiliate_or_fee_refund(
            finalized_refund_atomic=3, source_verified=False
        )
        == 0
    )
    result = reconcile_recovery_components(
        (
            {"amount_atomic": 4, "finalized": True, "source_verified": True},
            {"amount_atomic": 9, "finalized": False, "source_verified": True},
        ),
        envelope=env(),
        strategy_net_before_recoveries_atomic=10,
        finalized=True,
    )
    assert result.payload["accounting_total_atomic"] == 14
    assert result.payload["recoveries_are_strategy_alpha"] is False
    assert_offline(result)


def test_replay_identity_is_stable_for_same_keeper_evidence() -> None:
    job = {
        "job_id": "j1",
        "permission_ref": "permit-1",
        "capacity_atomic": 10,
    }
    economics = price_keeper_reward_and_cost(
        reward_atomic=10,
        network_fee_atomic=1,
        tip_atomic=0,
        state_change_cost_atomic=0,
    )
    plan = build_authorized_keeper_plan(job, economics, envelope=env())
    first = qualify_keeper_operation(plan, envelope=env())
    second = qualify_keeper_operation(plan, envelope=env())
    assert first.evidence_sha256 == second.evidence_sha256
