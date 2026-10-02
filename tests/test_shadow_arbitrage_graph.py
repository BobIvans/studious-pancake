from __future__ import annotations

from dataclasses import replace

import pytest

from src.market.snapshots import (
    CompletenessState,
    MarketObservationV2,
    ObservationBatch,
    ObservationGeneration,
    SourceCursor,
)
from src.strategy.arbitrage_graph import (
    CircularGraphCandidateDetector,
    CircularGraphPolicy,
    CircularShadowRoute,
    DirectedQuoteEdge,
    GraphSearchStop,
    UniversalArbitrageGraph,
    VenueIdentity,
)
from src.strategy.interfaces import StrategyMode
from src.strategy.strategies import OrderbookAmmStrategy

pytestmark = pytest.mark.unit
NOW = 1000.0


def _edge(
    name: str, source: str, target: str, amount: int, output: int, **overrides
) -> DirectedQuoteEdge:
    values = dict(
        provider="recorded",
        source="fixture",
        input_mint=source,
        output_mint=target,
        input_amount=amount,
        expected_output=output + 10,
        guaranteed_output=output,
        slot=100,
        observed_at=NOW - 1,
        expires_at=NOW + 1,
        quote_id=name,
        request_fingerprint="request-" + name,
        response_hash="response-" + name,
        cursor=SourceCursor("fixture", name, 0, 100),
    )
    values.update(overrides)
    return DirectedQuoteEdge(
        VenueIdentity("amm-program", name), MarketObservationV2(**values)
    )


def _cycle(hops: int = 3, amount: int = 10, final: int = 15):
    assets = ("A", "B", "C", "D")[:hops] + ("A",)
    return tuple(
        _edge(
            f"pool-{hops}-{index}-{amount}",
            assets[index],
            assets[index + 1],
            amount + index,
            final if index == hops - 1 else amount + index + 1,
        )
        for index in range(hops)
    )


def _graph(edges, **batch_options) -> UniversalArbitrageGraph:
    return UniversalArbitrageGraph(
        ObservationBatch(
            tuple(edge.observation for edge in edges), published_at=NOW, **batch_options
        ),
        tuple(edges),
    )


def _detector(**overrides) -> CircularGraphCandidateDetector:
    values = dict(base_mint="A", lower_amount_base_units=10, upper_amount_base_units=10)
    values.update(overrides)
    return CircularGraphCandidateDetector(CircularGraphPolicy(**values))


@pytest.mark.parametrize("hops", [3, 4])
def test_exact_guaranteed_amounts_couple_every_hop(hops):
    result = _detector().detect(_graph(_cycle(hops)), now=NOW)
    assert result.stop_reason is GraphSearchStop.COMPLETE
    (route,) = result.candidates
    assert route.amounts_base_units == tuple(range(10, 10 + hops)) + (15,)
    assert route.gross_profit_base_units == 5
    assert len(route.edges) == hops
    assert not hasattr(route, "strategy_name")  # Not an executable Opportunity.


@pytest.mark.parametrize("hop", [0, 1, 2, 3])
def test_no_scaling_or_expected_output_coupling(hop):
    edges = list(_cycle(4))
    # An optimistic expected-output input is never a valid downstream input.
    quote = edges[hop].observation
    edges[hop] = replace(
        edges[hop], observation=replace(quote, input_amount=quote.input_amount + 10)
    )
    result = _detector().detect(_graph(edges), now=NOW)
    assert result.candidates == ()
    assert dict(result.rejections)["amount_mismatch"] > 0


@pytest.mark.parametrize(
    "changes",
    [
        {"observed_at": NOW - 10},
        {"expires_at": NOW},
        {"observed_at": NOW + 0.1},
        {"expires_at": None, "confidence": "live"},
    ],
)
def test_stale_expired_future_or_unbounded_live_quote_rejected(changes):
    edges = list(_cycle())
    edges[1] = replace(edges[1], observation=replace(edges[1].observation, **changes))
    result = _detector().detect(_graph(edges), now=NOW)
    assert result.candidates == ()
    assert dict(result.rejections)["stale_or_future_snapshot"] == 1


def test_slot_spread_is_route_wide_not_only_adjacent():
    edges = list(_cycle())
    for index in (1, 2):
        quote = edges[index].observation
        edges[index] = replace(
            edges[index],
            observation=replace(
                quote, slot=100 + index, cursor=replace(quote.cursor, slot=100 + index)
            ),
        )
    result = _detector(max_slot_skew=1).detect(_graph(edges), now=NOW)
    assert result.candidates == ()
    assert dict(result.rejections)["slot_skew"] == 1
    assert (
        len(_detector(max_slot_skew=2).detect(_graph(edges), now=NOW).candidates) == 1
    )


def test_repeated_underlying_market_rejected_across_providers():
    edges = list(_cycle())
    edges[-1] = replace(
        edges[-1],
        venue=edges[0].venue,
        observation=replace(edges[-1].observation, provider="other-provider"),
    )
    result = _detector().detect(_graph(edges), now=NOW)
    assert result.candidates == ()
    assert dict(result.rejections)["repeated_venue"] == 1


def test_same_program_distinct_markets_and_parallel_edges_remain_distinct():
    edges = _cycle()
    parallel = replace(edges[0], venue=VenueIdentity("amm-program", "parallel-pool"))
    graph = _graph(edges + (parallel,))
    result = _detector().detect(graph, now=NOW)
    assert len(graph.nodes) == 3
    assert len(result.candidates) == 2
    assert len({route.identity for route in result.candidates}) == 2


def test_repeated_intermediate_asset_does_not_form_a_four_hop_candidate():
    edges = (
        _edge("ab", "A", "B", 10, 11),
        _edge("bc", "B", "C", 11, 12),
        _edge("cb", "C", "B", 12, 13),
        _edge("ba", "B", "A", 13, 15),
    )
    result = _detector().detect(_graph(edges), now=NOW)
    assert result.candidates == ()
    assert dict(result.rejections)["repeated_asset"] == 1


@pytest.mark.parametrize(
    "state", [CompletenessState.DEGRADED, CompletenessState.BLOCKED]
)
def test_incomplete_batch_never_searches(state):
    result = _detector().detect(_graph(_cycle(), completeness=state), now=NOW)
    assert result.candidates == ()
    assert result.expansions == 0
    assert result.stop_reason is GraphSearchStop.INCOMPLETE_BATCH


def test_mixed_generation_fails_closed():
    edges = list(_cycle())
    edges[1] = replace(
        edges[1],
        observation=replace(
            edges[1].observation,
            generation=ObservationGeneration(code_generation="other-code"),
        ),
    )
    result = _detector().detect(_graph(edges), now=NOW)
    assert result.candidates == ()
    assert dict(result.rejections)["mixed_generation"] == 1


def test_graph_cannot_bind_external_or_superseded_observation():
    edges = _cycle()
    batch = ObservationBatch(
        tuple(edge.observation for edge in edges), published_at=NOW
    )
    external = replace(
        edges[0], observation=replace(edges[0].observation, input_amount=999)
    )
    with pytest.raises(ValueError, match="active observation"):
        UniversalArbitrageGraph(batch, (external,))
    corrected = replace(
        edges[0].observation,
        guaranteed_output=10,
        correction_kind="correction",
        supersedes_id=edges[0].observation.observation_id,
    )
    corrected_batch = ObservationBatch(
        batch.observations + (corrected,), published_at=NOW
    )
    with pytest.raises(ValueError, match="active observation"):
        UniversalArbitrageGraph(corrected_batch, edges)


def test_route_identity_and_bounded_search_ignore_insertion_order():
    edges = _cycle(3) + _cycle(4)
    detector = _detector(max_candidates=1)
    forward = detector.detect(_graph(edges), now=NOW)
    backward = detector.detect(_graph(tuple(reversed(edges))), now=NOW)
    assert forward == backward
    assert forward.stop_reason is GraphSearchStop.CANDIDATE_LIMIT
    assert len(forward.candidates) == 1


@pytest.mark.parametrize(
    "change",
    ["venue", "quote_id", "expected_output", "expiry", "slot", "amount", "generation"],
)
def test_route_identity_binds_order_amounts_venue_and_quote_provenance(change):
    edges = _cycle()
    (original,) = _detector().detect(_graph(edges), now=NOW).candidates
    changed = list(edges)
    edge = changed[-1]
    quote = edge.observation
    if change == "venue":
        changed[-1] = replace(edge, venue=VenueIdentity("other-program", "other-pool"))
    elif change == "quote_id":
        changed[-1] = replace(edge, observation=replace(quote, quote_id="other-quote"))
    elif change == "expected_output":
        changed[-1] = replace(
            edge, observation=replace(quote, expected_output=quote.expected_output + 1)
        )
    elif change == "expiry":
        changed[-1] = replace(edge, observation=replace(quote, expires_at=NOW + 2))
    elif change == "amount":
        changed[-1] = replace(edge, observation=replace(quote, guaranteed_output=16))
    else:
        for index, item in enumerate(changed):
            values = (
                {"generation": ObservationGeneration(code_generation="new-code")}
                if change == "generation"
                else {"slot": 101, "cursor": replace(item.observation.cursor, slot=101)}
            )
            changed[index] = replace(
                item, observation=replace(item.observation, **values)
            )
    (updated,) = _detector().detect(_graph(changed), now=NOW).candidates
    assert original.identity != updated.identity


def test_route_type_enforces_invariants_independently_of_detector():
    edges = list(_cycle())
    edges[1] = replace(
        edges[1], observation=replace(edges[1].observation, input_amount=999)
    )
    with pytest.raises(ValueError, match="exact guaranteed amount"):
        CircularShadowRoute(tuple(edges), "batch", "watermark", "generation")


def test_amount_grid_reuses_pr118_and_rejection_does_not_prune_larger_sizes():
    edges = (
        _cycle(amount=10, final=15)
        + _cycle(amount=20, final=19)
        + _cycle(amount=30, final=40)
    )
    detector = _detector(upper_amount_base_units=30, max_amount_points=3)
    assert detector.policy.amount_points == (10, 20, 30)
    result = detector.detect(_graph(edges), now=NOW)
    assert sorted(route.amounts_base_units[0] for route in result.candidates) == [
        10,
        30,
    ]
    assert dict(result.rejections)["below_min_gross_profit"] == 1


def test_large_integer_base_units_never_pass_through_float_math():
    amount = 2**80 + 123
    detector = _detector(lower_amount_base_units=amount, upper_amount_base_units=amount)
    (route,) = detector.detect(
        _graph(_cycle(amount=amount, final=amount + 7)), now=NOW
    ).candidates
    assert route.amounts_base_units == (amount, amount + 1, amount + 2, amount + 7)
    assert route.gross_profit_base_units == 7


@pytest.mark.parametrize("hops", [2, 5])
def test_two_and_five_hop_cycles_are_outside_bounded_detector(hops):
    assets = tuple(f"asset-{index}" for index in range(hops))
    edges = tuple(
        _edge(
            f"market-{index}",
            assets[index],
            assets[(index + 1) % hops],
            10 + index,
            15 if index == hops - 1 else 11 + index,
        )
        for index in range(hops)
    )
    assert (
        _detector(base_mint=assets[0]).detect(_graph(edges), now=NOW).candidates == ()
    )


def test_route_identity_preserves_order_and_batch_watermark_provenance():
    edges = (
        _edge("ab", "A", "B", 10, 10),
        _edge("bc", "B", "C", 10, 10),
        _edge("ca", "C", "A", 10, 10),
    )
    route = CircularShadowRoute(edges, "batch", "watermark", "generation")
    rotated = replace(route, edges=edges[1:] + edges[:1])
    assert route.identity != rotated.identity
    assert (
        route.identity != replace(route, watermark_identity="other-watermark").identity
    )
    assert route.identity != replace(route, batch_id="other-batch").identity


def test_expansion_and_edge_limits_are_explicit_and_deterministic():
    graph = _graph(_cycle())
    result = _detector(max_expansions=2).detect(graph, now=NOW)
    assert result == _detector(max_expansions=2).detect(graph, now=NOW)
    assert result.expansions == 2
    assert result.candidates == ()
    assert result.stop_reason is GraphSearchStop.EXPANSION_LIMIT
    result = _detector(max_edges=2).detect(graph, now=NOW)
    assert result.stop_reason is GraphSearchStop.EDGE_LIMIT
    assert result.expansions == 0


def test_graph_hard_cap_and_duplicates_fail_before_search():
    graph = _graph(_cycle())
    with pytest.raises(ValueError, match="512-edge"):
        UniversalArbitrageGraph(graph.batch, (graph.edges[0],) * 513)
    with pytest.raises(ValueError, match="duplicate"):
        UniversalArbitrageGraph(graph.batch, (graph.edges[0],) * 2)


@pytest.mark.parametrize(
    "changes",
    [
        {"lower_amount_base_units": True},
        {"upper_amount_base_units": 1.5},
        {"max_amount_points": 9},
        {"max_edges": 513},
        {"max_candidates": 0},
        {"max_expansions": 0},
        {"max_slot_skew": -1},
        {"max_snapshot_age_seconds": float("nan")},
    ],
)
def test_invalid_or_unbounded_policy_rejected(changes):
    with pytest.raises(ValueError):
        _detector(**changes)


def test_orderbook_strategy_remains_disabled():
    strategy = OrderbookAmmStrategy()
    assert strategy.mode is StrategyMode.DISABLED
    assert "verified market subscriptions" in strategy.disabled_reason
