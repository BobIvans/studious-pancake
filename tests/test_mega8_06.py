from __future__ import annotations

import importlib
import inspect

import pytest

from src.mega8_06 import CHILDREN, FUNCTION_COUNT, NF_IDS, Mega806Error
from src.mega8_06.pr255 import (
    compute_markout_curve,
    estimate_adverse_selection,
    gate_toxic_fill,
    predict_fill_quality,
)
from src.mega8_06.pr256 import (
    cap_route_size_by_impact,
    estimate_capacity_frontier,
    fit_market_impact_curve,
    simulate_self_impact,
)
from src.mega8_06.pr258 import (
    build_opportunity_portfolio,
    reconcile_portfolio_outcomes,
    solve_portfolio_admission,
)
from src.mega8_06.pr259 import (
    allocate_microcapital_budget,
    compute_risk_of_ruin,
    trigger_survival_stop,
)
from src.mega8_06.pr263 import route_read_request
from src.mega8_06.pr265 import simulate_direct_send_policy
from src.mega8_06.pr266 import route_submission_variant
from src.mega8_06.pr267 import gate_ordering_fragility, simulate_adversarial_ordering
from src.mega8_06.pr268 import (
    build_protective_backrun_plan,
    register_opt_in_orderflow_policy,
    verify_orderflow_consent,
)
from src.mega8_06.pr269 import (
    build_execution_trajectory_dataset,
    evaluate_execution_policy_offline,
    gate_policy_deployment,
    train_offline_execution_policy,
)
from src.mega8_06.pr270 import (
    build_fee_bid_dataset,
    calibrate_bid_risk,
    select_guarded_fee_bid,
    train_safe_bid_policy,
)


def test_manifest_is_exact_and_every_owner_symbol_exists() -> None:
    assert sorted(CHILDREN) == list(range(255, 271))
    assert FUNCTION_COUNT == 64
    assert NF_IDS == tuple(range(705, 769))
    names = []
    for child, (_, rows) in CHILDREN.items():
        module = importlib.import_module(f"src.mega8_06.pr{child}")
        for _, name in rows:
            value = getattr(module, name)
            assert inspect.isfunction(value)
            names.append(name)
    assert len(names) == len(set(names)) == 64


def test_microstructure_markouts_are_side_aware_and_fail_closed() -> None:
    curve = compute_markout_curve(100, {1: 99, 5: 98}, side="buy")
    assert curve == ((1, -10_000), (5, -20_000))
    adverse = estimate_adverse_selection([x for _, x in curve])
    assert adverse == 15_000
    assert predict_fill_quality([x for _, x in curve], toxicity_ppm=5_000) == 980_000
    with pytest.raises(Mega806Error, match="ADVERSE_SELECTION_LIMIT"):
        gate_toxic_fill(
            [x for _, x in curve],
            max_adverse_ppm=10_000,
            max_toxicity_ppm=30_000,
        )


def test_impact_capacity_never_extrapolates() -> None:
    curve = fit_market_impact_curve(((10, 1000), (20, 1500), (20, 1700), (30, 5000)))
    assert curve == ((10, 1000), (20, 1600), (30, 5000))
    frontier = estimate_capacity_frontier(
        curve, expected_edge_ppm=4500, uncertainty_ppm=1000
    )
    assert frontier == 20
    assert cap_route_size_by_impact(99, frontier) == 20
    with pytest.raises(Mega806Error, match="OUTSIDE_IMPACT_SUPPORT"):
        simulate_self_impact(5, curve)


def test_portfolio_counts_shared_resources_once_and_freezes_unknowns() -> None:
    candidates = build_opportunity_portfolio(
        (
            {
                "id": "a",
                "capital": 5,
                "tail_loss": 1,
                "expected_net": 9,
                "resources": ("pool",),
            },
            {
                "id": "b",
                "capital": 5,
                "tail_loss": 1,
                "expected_net": 8,
                "resources": ("pool",),
            },
            {
                "id": "c",
                "capital": 4,
                "tail_loss": 1,
                "expected_net": 7,
                "resources": ("other",),
            },
        )
    )
    assert solve_portfolio_admission(candidates, capital_budget=9, tail_budget=2) == (
        "a",
        "c",
    )
    reconciled = reconcile_portfolio_outcomes(("a", "c"), {"a": 2, "c": None})
    assert reconciled["freeze_conflicting_capital"] is True
    assert reconciled["unknown_children"] == ("c",)


def test_microcapital_has_protected_floor_and_no_loss_chasing() -> None:
    assert (
        allocate_microcapital_budget(100, protected_floor=80, max_spend_ppm=500_000)
        == 10
    )
    assert compute_risk_of_ruin(25, (-10, -5, 2), attempts=5) == 500_000
    assert trigger_survival_stop(90, protected_floor=80, unknown_cost=10) is True


def test_network_routing_never_merges_incoherent_critical_reads() -> None:
    rows = (
        {
            "region": "a",
            "latency_us": 1000,
            "gap_ppm": 0,
            "fork_agreement_ppm": 999_000,
            "reliability_ppm": 999_000,
            "quota_remaining": 1,
        },
        {
            "region": "b",
            "latency_us": 10,
            "gap_ppm": 0,
            "fork_agreement_ppm": 800_000,
            "reliability_ppm": 999_000,
            "quota_remaining": 1,
        },
    )
    assert route_read_request(rows, critical=True) == "a"


def test_direct_send_policy_freezes_ambiguous_outcome() -> None:
    result = simulate_direct_send_policy(({"ambiguous": True},), max_retries=3)
    assert result == {
        "allowed_retries": 0,
        "freeze": True,
        "reason": "AMBIGUOUS_OUTCOME",
    }


def test_transport_router_selects_only_qualified_and_never_sends() -> None:
    transports = (
        {"name": "rpc", "qualified": True},
        {"name": "experimental", "qualified": False},
    )
    metrics = {
        "rpc": {
            "inclusion_ppm": 900_000,
            "expected_cost": 100,
            "ambiguity_ppm": 10_000,
        },
        "experimental": {
            "inclusion_ppm": 1_000_000,
            "expected_cost": 0,
            "ambiguity_ppm": 0,
        },
    }
    assert route_submission_variant(transports, metrics) == "rpc"


def test_mev_counterfactual_rejects_insolvent_reordering() -> None:
    outcomes = simulate_adversarial_ordering(10, (-2, -20))
    with pytest.raises(Mega806Error, match="ORDERING_FRAGILITY"):
        gate_ordering_fragility(10, outcomes, max_loss=100)


def test_protective_orderflow_requires_current_consent_and_user_floor() -> None:
    policy = register_opt_in_orderflow_policy(
        intent_id="i",
        user_id="u",
        expires_at=100,
        min_user_output=90,
        consent_revision="r1",
    )
    assert verify_orderflow_consent(policy, now=99, consent_revision="r1")
    plan = build_protective_backrun_plan(policy, user_output=95, candidate_profit=3)
    assert plan["pre_user_execution"] is False
    assert plan["submission_authority"] is False
    with pytest.raises(Mega806Error, match="CONSENT_EXPIRED"):
        verify_orderflow_consent(policy, now=100, consent_revision="r1")


def test_offline_execution_policy_rejects_future_data_and_remains_advisory() -> None:
    with pytest.raises(Mega806Error, match="FUTURE_DATA_LEAKAGE"):
        build_execution_trajectory_dataset(
            (
                {
                    "action": "rpc",
                    "reward": 1,
                    "available_at": 2,
                    "decision_at": 1,
                    "supported": True,
                },
            )
        )
    dataset = build_execution_trajectory_dataset(
        (
            {
                "action": "rpc",
                "reward": 1,
                "available_at": 1,
                "decision_at": 1,
                "supported": True,
            },
            {
                "action": "jito",
                "reward": 3,
                "available_at": 1,
                "decision_at": 2,
                "supported": True,
            },
        )
    )
    policy = train_offline_execution_policy(dataset)
    evaluation = evaluate_execution_policy_offline(policy, dataset)
    assert (
        gate_policy_deployment(evaluation, baseline_reward=1) == "ADVISORY_SHADOW_ONLY"
    )


def test_fee_policy_obeys_hard_cap_and_unknown_is_not_success() -> None:
    dataset = build_fee_bid_dataset(
        (
            {"regime": "r", "bid": 10, "cost": 5, "outcome": "landed"},
            {"regime": "r", "bid": 20, "cost": 8, "outcome": "unknown"},
            {"regime": "r", "bid": 15, "cost": 7, "outcome": "not_landed"},
        )
    )
    policy = train_safe_bid_policy(dataset, hard_cap=12)
    calibration = calibrate_bid_risk(dataset, candidate_bid=15)
    assert (
        select_guarded_fee_bid(
            policy,
            calibration,
            max_overpayment=10,
            min_inclusion_ppm=400_000,
        )
        == 10
    )
