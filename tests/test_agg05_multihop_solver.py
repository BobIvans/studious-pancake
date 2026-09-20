from __future__ import annotations

import pytest

from src.strategy.multihop_solver import (
    ExactEvaluationStopReason,
    FeeBidOption,
    ResourceLimits,
    RouteRejection,
    RouteVariant,
    SearchEdge,
    SearchStopReason,
    build_multihop_candidate,
    evaluate_shortlisted_routes,
    rank_resource_feasible_routes,
    search_bounded_cycles,
    select_bounded_fee_bid,
)


def _edge(
    edge_id: str,
    source: str,
    target: str,
    pool: str,
    *,
    num: int = 101,
    den: int = 100,
) -> SearchEdge:
    return SearchEdge(
        edge_id=edge_id,
        input_asset=source,
        output_asset=target,
        pool_key=pool,
        marginal_rate_numerator=num,
        marginal_rate_denominator=den,
        state_generation="frame-1",
    )


def test_search_finds_two_three_and_five_hop_cycles() -> None:
    edges = (
        _edge("ab", "A", "B", "p1"),
        _edge("ba", "B", "A", "p2"),
        _edge("ac", "A", "C", "p3"),
        _edge("cd", "C", "D", "p4"),
        _edge("da", "D", "A", "p5"),
        _edge("ae", "A", "E", "p6"),
        _edge("ef", "E", "F", "p7"),
        _edge("fg", "F", "G", "p8"),
        _edge("gh", "G", "H", "p9"),
        _edge("ha", "H", "A", "p10"),
    )
    result = search_bounded_cycles(edges, start_asset="A")
    assert {route.hop_count for route in result.routes} == {2, 3, 5}
    assert result.stop_reason is SearchStopReason.COMPLETE


def test_pool_simple_search_does_not_double_count_one_pool() -> None:
    result = search_bounded_cycles(
        (
            _edge("ab", "A", "B", "same"),
            _edge("ba", "B", "A", "same"),
        ),
        start_asset="A",
    )
    assert result.routes == ()


def test_search_budget_exhaustion_is_not_no_alpha_claim() -> None:
    edges = tuple(_edge(f"a{i}", "A", f"X{i}", f"p{i}") for i in range(10))
    result = search_bounded_cycles(
        edges,
        start_asset="A",
        max_expansions=3,
    )
    assert result.stop_reason is SearchStopReason.BUDGET_EXHAUSTED
    assert result.expansions == 3


def test_exact_evaluation_is_amount_state_bound_and_budgeted() -> None:
    routes = search_bounded_cycles(
        (
            _edge("ab", "A", "B", "p1"),
            _edge("ba", "B", "A", "p2"),
            _edge("ac", "A", "C", "p3"),
            _edge("ca", "C", "A", "p4"),
        ),
        start_asset="A",
    ).routes

    def evaluate(route):
        return RouteVariant(
            route_id=route.route_id,
            hop_count=route.hop_count,
            amount_units=100,
            conservative_net_units=5,
            compute_units=10,
            message_bytes=100,
            writable_accounts=("w",),
            rent_units=1,
            fee_units=1,
            state_generation="frame-1",
        )

    result = evaluate_shortlisted_routes(
        routes,
        exact_evaluator=evaluate,
        max_evaluations=1,
    )
    assert len(result.variants) == 1
    assert result.stop_reason is ExactEvaluationStopReason.BUDGET_EXHAUSTED


def test_resource_ranking_rejects_nominal_edge_that_cannot_compile() -> None:
    variant = RouteVariant(
        route_id="r",
        hop_count=3,
        amount_units=100,
        conservative_net_units=20,
        compute_units=10,
        message_bytes=2_000,
        writable_accounts=("w",),
        rent_units=1,
        fee_units=1,
        state_generation="frame-1",
    )
    ranked = rank_resource_feasible_routes(
        (variant,),
        limits=ResourceLimits(
            max_hops=5,
            max_compute_units=100,
            max_message_bytes=1_000,
            max_writable_accounts=10,
            max_rent_units=10,
            max_total_cost_units=20,
        ),
    )
    assert ranked.accepted == ()
    assert ranked.rejections == (("r", RouteRejection.MESSAGE_SIZE_LIMIT),)


def test_fee_bid_never_exceeds_cap_and_unlabelled_probability_is_rejected() -> None:
    with pytest.raises(ValueError):
        FeeBidOption(
            "bad",
            priority_fee_units=1,
            tip_units=1,
            observed_landing_probability_ppm=900_000,
            label_count=0,
        )
    decision = select_bounded_fee_bid(
        (
            FeeBidOption("cheap", 2, 1),
            FeeBidOption("expensive", 100, 100),
        ),
        gross_edge_units=30,
        base_network_fee_units=5,
        max_total_bid_units=10,
    )
    assert decision.selected is not None
    assert decision.selected.option_id == "cheap"
    assert decision.conservative_net_units == 22


def test_multihop_candidate_requires_exact_positive_full_cost_variant() -> None:
    route = search_bounded_cycles(
        (
            _edge("ab", "A", "B", "p1"),
            _edge("bc", "B", "C", "p2"),
            _edge("ca", "C", "A", "p3"),
        ),
        start_asset="A",
    ).routes[0]
    variant = RouteVariant(
        route_id=route.route_id,
        hop_count=3,
        amount_units=100,
        conservative_net_units=7,
        compute_units=30,
        message_bytes=300,
        writable_accounts=("w",),
        rent_units=2,
        fee_units=3,
        state_generation="frame-1",
    )
    candidate = build_multihop_candidate(route, variant)
    assert candidate.hop_count == 3
    assert candidate.conservative_net_units == 7
