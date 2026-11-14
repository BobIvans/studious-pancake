"""R10 strategy inventory replay experiment (read-only audit lane).

Bounded, deterministic, offline replay over EXISTING intelligence owners only:

A. Residual family generation fail-closed gates (src/research/correlation_ledger/
   residuals.py): unproven anchors/costs/rates are excluded with typed reasons and
   carry value=None (unknown is never zero); only proven, chain-aligned samples
   materialize as ledger observations.
B. Correlation-ledger lead/lag gating (src/research/correlation_ledger/ledger.py):
   windows are computed only over CHAIN_ALIGNED samples; UNALIGNED samples are
   excluded with a typed reason; shared correlation groups collapse confidence to
   zero; findings stay DISCOVERY_ONLY and replay deterministically.
C. Multihop bounded search + exact-evaluation binding (src/strategy/multihop_solver.py):
   the marginal shortlist finds/gates 2..5-hop cycles, but a route is not a
   profitable candidate until a caller-supplied exact evaluator binds amount,
   state and full resource costs (negative net => NON_POSITIVE_NET rejection).
D. Relation-generator discovery on a synthetic fixture universe
   (src/strategy/relation_generators/generators.py): DIRECT_MARKET /
   VENUE_FRAGMENTATION / SYNTHETIC_CROSS / DIRECT_SYNTHETIC_RESIDUAL emissions
   carry liquidity provenance; the identity gate and FLASH_CAPITAL lender
   qualification gates fail closed.

No network, no sender, no live evidence. Model/correlation outputs are advisory:
nothing here can promote a strategy family past shadow/paper (R10 acceptance).
"""

from dataclasses import replace

import pytest

from src.assets.resolution.resolver import ResolutionState
from src.research.correlation_ledger.ledger import (
    CHAIN_ALIGNED,
    CorrelationLedger,
    NormalizedObservation,
)
from src.research.correlation_ledger.residuals import (
    INSTANT_EXIT_UNPROVEN,
    LST_RATE_UNPROVEN,
    ORACLE_MARKET,
    REFERENCE_UNPROVEN,
    SLOT_MISALIGNED,
    WRAPPER_BASIS,
    lst_premium_residual,
    oracle_market_residual,
    residual_observation,
    wrapper_basis_residual,
)
from src.strategy.multihop_solver import (
    ResourceLimits,
    RouteRejection,
    RouteVariant,
    SearchEdge,
    SearchStopReason,
    build_multihop_candidate,
    evaluate_shortlisted_routes,
    rank_resource_feasible_routes,
    search_bounded_cycles,
)
from src.strategy.relation_generators.generators import (
    LENDER_QUALIFIED,
    SYNTHETIC_LEGS_VERIFIED,
    generate,
)
from tests.test_dynamic_asset_resolution import MINT, OTHER, evidence
from tests.test_dynamic_flash_capital import capital
from tests.test_dynamic_universe import market
from tests.test_relation_h_generators import THIRD, asset

# ---------------------------------------------------------------------------
# Shared deterministic fixture helpers (offline, timestamped around t=200).
# ---------------------------------------------------------------------------


def _ledger_observation(market_id, t, value, *, aligned=True, group=None):
    """One normalized residual observation; provider/group are per-market."""
    e = replace(
        evidence(market_id, position=round(t * 100), timestamp=t),
        correlation_group=group or market_id,
    )
    return NormalizedObservation(
        "solana",
        market_id,
        "relation-" + market_id,
        e,
        (("stable_residual", value),),
        (market_id,),
        "quiet",
        timestamp_alignment=CHAIN_ALIGNED if aligned else "UNALIGNED",
    )


def _search_edge(edge_id, source, target, pool, *, num, den):
    return SearchEdge(
        edge_id=edge_id,
        input_asset=source,
        output_asset=target,
        pool_key=pool,
        marginal_rate_numerator=num,
        marginal_rate_denominator=den,
        state_generation="frame-1",
    )


def _variant(route, *, conservative_net_units):
    return RouteVariant(
        route_id=route.route_id,
        hop_count=route.hop_count,
        amount_units=10_000_000,
        conservative_net_units=conservative_net_units,
        compute_units=50_000,
        message_bytes=800,
        writable_accounts=("acct-a", "acct-b"),
        rent_units=0,
        fee_units=5_000,
        state_generation=route.edges[0].state_generation,
    )


_LIMITS = ResourceLimits(
    max_hops=5,
    max_compute_units=200_000,
    max_message_bytes=1232,
    max_writable_accounts=64,
    max_rent_units=1_000_000,
    max_total_cost_units=100_000,
)


# ---------------------------------------------------------------------------
# Experiment A: residual family generation is fail-closed on unproven proofs.
# ---------------------------------------------------------------------------


def test_residual_families_fail_closed_on_unproven_anchors():
    # LST premium without a proven exchange rate: excluded, value None.
    sample = lst_premium_residual(
        lst_price=1.05,
        underlying_price=1.0,
        exchange_rate=1.02,
        scale=1.0,
        rate_proven=False,
        instant_exit_available=True,
        instant_exit_cost=0.005,
        evidences=(
            evidence("oracle", position=1000, timestamp=200),
            evidence("amm", position=1001, timestamp=200.5),
        ),
    )
    assert sample.value is None
    assert sample.exclusions == (LST_RATE_UNPROVEN,)

    # LST premium with a proven rate but no instant exit: excluded (a tradable
    # premium without a proven redemption route is not a residual).
    sample = lst_premium_residual(
        lst_price=1.05,
        underlying_price=1.0,
        exchange_rate=1.02,
        scale=1.0,
        rate_proven=True,
        instant_exit_available=False,
        instant_exit_cost=0.005,
        evidences=(
            evidence("oracle", position=1000, timestamp=200),
            evidence("amm", position=1001, timestamp=200.5),
        ),
    )
    assert sample.value is None
    assert INSTANT_EXIT_UNPROVEN in sample.exclusions

    # Wrapper basis without a proven underlying reference: excluded.
    sample = wrapper_basis_residual(
        wrapper_price=0.999,
        reference_price=1.0,
        wrap_cost=0.002,
        scale=1.0,
        reference_proven=False,
        wrap_cost_known=True,
        evidences=(evidence("btc-ref", position=500, timestamp=200),),
    )
    assert sample.value is None
    assert sample.exclusions == (REFERENCE_UNPROVEN,)

    # Oracle-vs-market residual with slot positions 5 apart (> max gap 3):
    # misaligned, excluded, never silently correlated.
    sample = oracle_market_residual(
        market_price=100.5,
        oracle_price=100.0,
        confidence_scale=0.2,
        evidences=(
            evidence("oracle", position=1000, timestamp=200),
            evidence("amm", position=1005, timestamp=200),
        ),
    )
    assert sample.value is None
    assert sample.exclusions == (SLOT_MISALIGNED,)
    assert sample.timestamp_alignment == "UNALIGNED"


def test_proven_residuals_compute_values_and_materialize_aligned_observations(
    tmp_path,
):
    # Fully proven LST premium: residual = (1.05 - 1.0*1.02 - 0.005) / 1.0.
    proven_evidences = (
        evidence("oracle", position=1000, timestamp=200),
        evidence("amm", position=1001, timestamp=200.5),
    )
    lst = lst_premium_residual(
        lst_price=1.05,
        underlying_price=1.0,
        exchange_rate=1.02,
        scale=1.0,
        rate_proven=True,
        instant_exit_available=True,
        instant_exit_cost=0.005,
        evidences=proven_evidences,
    )
    assert lst.exclusions == ()
    assert lst.value == pytest.approx(0.025)
    assert lst.timestamp_alignment == CHAIN_ALIGNED

    # Fully proven wrapper basis: residual = (0.999 - 1.0 - 0.002) / 1.0.
    wrapper = wrapper_basis_residual(
        wrapper_price=0.999,
        reference_price=1.0,
        wrap_cost=0.002,
        scale=1.0,
        reference_proven=True,
        wrap_cost_known=True,
        evidences=(evidence("btc-ref", position=500, timestamp=200),),
    )
    assert wrapper.value == pytest.approx(-0.003)
    assert wrapper.feature == WRAPPER_BASIS

    # Proven, chain-aligned oracle residual.
    oracle = oracle_market_residual(
        market_price=100.5,
        oracle_price=100.0,
        confidence_scale=0.2,
        evidences=(
            evidence("oracle", position=1000, timestamp=200),
            evidence("amm", position=1001, timestamp=200),
        ),
    )
    assert oracle.value == pytest.approx(2.5)
    assert oracle.feature == ORACLE_MARKET

    # Materialization: only proven aligned samples enter the ledger; excluded
    # samples materialize as None and are never written (unknown is not zero).
    observation = residual_observation(
        lst,
        chain="solana",
        market_id="lst-amm",
        relation_id="relation-lst",
        evidence=proven_evidences[1],
        liquidity_resources=("lst-amm",),
        regime="quiet",
    )
    assert isinstance(observation, NormalizedObservation)
    assert observation.features[0][0] == "lst_premium"
    assert observation.features[0][1] == pytest.approx(0.025)
    assert observation.timestamp_alignment == CHAIN_ALIGNED
    assert (
        residual_observation(
            replace(lst, value=None),
            chain="solana",
            market_id="lst-amm",
            relation_id="relation-lst",
            evidence=proven_evidences[1],
            liquidity_resources=("lst-amm",),
            regime="quiet",
        )
        is None
    )

    ledger = CorrelationLedger(tmp_path, "campaign")
    ledger.append(observation)
    assert len(ledger.observations()) == 1


# ---------------------------------------------------------------------------
# Experiment B: lead/lag windows over CHAIN_ALIGNED samples only.
# ---------------------------------------------------------------------------


def test_lead_lag_windows_only_over_chain_aligned_samples(tmp_path):
    # Deterministic synthetic series: "clob" lags "amms" by exactly 0.1 s and
    # carries 2x the value, so lag-0.1 correlation must be +1.
    values = (0.2, -0.4, 0.6, -0.1, 0.3)
    aligned = tuple(
        observation
        for i, value in enumerate(values)
        for observation in (
            _ledger_observation("amms", 200 + i, value),
            _ledger_observation("clob", 200.1 + i, value * 2),
        )
    )
    # One unalignable sample inside the report window: excluded with a typed
    # reason, never promoted to alignment, never silently dropped as zero.
    unaligned = _ledger_observation("clob", 204.5, 9.9, aligned=False)
    ledger = CorrelationLedger(tmp_path, "campaign")
    ledger.append_many(aligned + (unaligned,))
    assert len(ledger.observations()) == 11

    report = ledger.lead_lag_report(
        "amms", "clob", (5,), feature="stable_residual", now=205, lags=(0, 0.1)
    )
    # Provenance gate: exactly one excluded sample, typed reason.
    assert len(report.exclusions) == 1
    exclusion = report.exclusions[0]
    assert exclusion.reason == "timestamp_alignment_unproven"
    assert exclusion.sample_count == 1

    lag_zero, lag_point_one = report.findings
    assert lag_zero.lag_seconds == 0
    assert lag_zero.sample_count == 0
    assert lag_zero.correlation is None
    assert lag_point_one.lag_seconds == 0.1
    assert lag_point_one.sample_count == 5
    assert lag_point_one.correlation == pytest.approx(1)
    # Distinct providers/groups/resources -> no alias penalty.
    assert lag_point_one.source_correlation_penalty == 0
    assert lag_point_one.confidence == pytest.approx(min(1, 5 / 30))
    # Findings are discovery-only, never execution evidence.
    assert all(f.verification_state == "DISCOVERY_ONLY" for f in report.findings)

    # Deterministic replay: a restarted ledger produces identical findings.
    restarted = CorrelationLedger(tmp_path, "campaign")
    assert (
        restarted.lead_lag_report(
            "amms", "clob", (5,), feature="stable_residual", now=205, lags=(0, 0.1)
        )
        == report
    )


def test_shared_correlation_group_collapses_confidence(tmp_path):
    # Same correlation group (aggregator alias / shared pool): even a perfect
    # correlation earns zero confidence — aliases are not independent evidence.
    ledger = CorrelationLedger(tmp_path, "campaign")
    ledger.append_many(
        tuple(
            observation
            for i in range(5)
            for observation in (
                _ledger_observation("amms", 200 + i, i, group="shared"),
                _ledger_observation("clob", 200.1 + i, i * 2, group="shared"),
            )
        )
    )
    report = ledger.lead_lag_report(
        "amms", "clob", (5,), feature="stable_residual", now=205, lags=(0.1,)
    )
    finding = report.findings[0]
    assert finding.correlation == pytest.approx(1)
    assert finding.source_correlation_penalty == 1
    assert finding.confidence == 0
    assert finding.verification_state == "DISCOVERY_ONLY"
    assert report.exclusions == ()


# ---------------------------------------------------------------------------
# Experiment C: bounded multihop search and exact-evaluation binding.
# ---------------------------------------------------------------------------


def _experiment_graph():
    """Synthetic fixture graph: two profitable cycles, one sub-threshold
    cycle, one same-pool round trip (pool_simple must refuse it)."""
    return (
        _search_edge("ab", "A", "B", "p1", num=102, den=100),
        _search_edge("ba", "B", "A", "p2", num=100, den=101),
        _search_edge("ac", "A", "C", "p3", num=104, den=100),
        _search_edge("cd", "C", "D", "p4", num=103, den=100),
        _search_edge("da", "D", "A", "p5", num=100, den=107),
        _search_edge("ae", "A", "E", "p6", num=99, den=100),
        _search_edge("ea", "E", "A", "p7", num=100, den=100),
        _search_edge("gh", "G", "H", "dup", num=102, den=100),
        _search_edge("hg", "H", "G", "dup", num=100, den=101),
    )


def test_multihop_shortlist_finds_and_gates_bounded_cycles():
    edges = _experiment_graph()
    result = search_bounded_cycles(edges, start_asset="A")
    assert result.stop_reason is SearchStopReason.COMPLETE
    assert {route.hop_count for route in result.routes} == {2, 3}
    two_hop = next(route for route in result.routes if route.hop_count == 2)
    three_hop = next(route for route in result.routes if route.hop_count == 3)
    # Exact marginal products of the fixture graph.
    assert two_hop.marginal_multiplier == pytest.approx((102 * 100) / (100 * 101))
    assert three_hop.marginal_multiplier == pytest.approx(
        (104 * 103 * 100) / (100 * 100 * 107)
    )
    # The 0.99-product cycle stays below the 1.0 threshold: not shortlisted.
    assert all(route.marginal_multiplier >= 1 for route in result.routes)

    # A 50 ppm minimum marginal gain excludes the 1.0011 3-hop cycle.
    strict = search_bounded_cycles(
        edges, start_asset="A", minimum_marginal_gain_ppm=5000
    )
    assert [route.hop_count for route in strict.routes] == [2]

    # pool_simple: one pool used twice in a round trip is not a cycle.
    same_pool = search_bounded_cycles(edges, start_asset="G")
    assert same_pool.routes == ()

    # Budget exhaustion is a typed stop reason, not a "no alpha" claim.
    fan = tuple(
        _search_edge(f"ax{i}", "A", f"X{i}", f"px{i}", num=100, den=100)
        for i in range(10)
    )
    budgeted = search_bounded_cycles(fan, start_asset="A", max_expansions=3)
    assert budgeted.stop_reason is SearchStopReason.BUDGET_EXHAUSTED
    assert budgeted.expansions == 3
    assert budgeted.routes == ()


def test_shortlist_is_not_profitable_until_exact_evaluation_binds():
    edges = _experiment_graph()
    result = search_bounded_cycles(edges, start_asset="A")
    two_hop = next(route for route in result.routes if route.hop_count == 2)
    three_hop = next(route for route in result.routes if route.hop_count == 3)

    # The exact evaluator binds a negative conservative net for the 2-hop
    # shortlist route: marginal topology looked profitable, exact costs
    # (fees/rent/slippage) say otherwise => typed NON_POSITIVE_NET rejection.
    lossy = _variant(two_hop, conservative_net_units=-50)
    evaluation = evaluate_shortlisted_routes(
        (two_hop,), exact_evaluator=lambda route: lossy, max_evaluations=8
    )
    assert evaluation.evaluated_route_ids == (two_hop.route_id,)
    ranked = rank_resource_feasible_routes(evaluation.variants, limits=_LIMITS)
    assert ranked.accepted == ()
    assert ranked.rejections == ((two_hop.route_id, RouteRejection.NON_POSITIVE_NET),)

    # A positive exact evaluation passes the resource gates and, at 3 hops,
    # may be promoted to a typed multihop candidate (2-hop cannot).
    profitable = _variant(three_hop, conservative_net_units=40)
    evaluation = evaluate_shortlisted_routes(
        (three_hop,), exact_evaluator=lambda route: profitable, max_evaluations=8
    )
    ranked = rank_resource_feasible_routes(evaluation.variants, limits=_LIMITS)
    assert [variant.conservative_net_units for variant in ranked.accepted] == [40]
    candidate = build_multihop_candidate(three_hop, profitable)
    assert candidate.hop_count == 3 and candidate.state_generation == "frame-1"
    with pytest.raises(ValueError, match="3-5 hops"):
        build_multihop_candidate(two_hop, lossy)

    # Fail-closed binding: an evaluator that returns a different route
    # identity is refused rather than silently attributed.
    with pytest.raises(ValueError, match="different route identity"):
        evaluate_shortlisted_routes(
            (two_hop,),
            exact_evaluator=lambda route: replace(
                profitable, route_id="fabricated-route-id"
            ),
            max_evaluations=8,
        )


# ---------------------------------------------------------------------------
# Experiment D: relation-generator discovery and capital gates.
# ---------------------------------------------------------------------------


def _fixture_universe():
    assets = (asset(MINT), asset(OTHER), asset(THIRD))
    markets = (
        # Orca-style MINT/OTHER pool.
        market(),
        # Second independent venue on the same pair (disjoint resources).
        market(
            market_id="pool-e",
            venue="raydium",
            program_id="program2",
            correlation_group="pool-e",
            underlying_resources=("pool-e",),
        ),
        # THIRD/OTHER pool (OTHER is the verified hub).
        market(
            market_id="pool-c",
            base=THIRD,
            correlation_group="pool-c",
            underlying_resources=("pool-c",),
        ),
        # Direct THIRD/MINT pool: completes the synthetic-vs-direct residual.
        market(
            market_id="pool-d",
            base=THIRD,
            quote=MINT,
            correlation_group="pool-d",
            underlying_resources=("pool-d",),
        ),
    )
    return assets, markets


def test_relation_generator_discovery_on_synthetic_fixture_universe():
    assets, markets = _fixture_universe()
    batch = generate(
        assets,
        markets,
        (),
        hubs=frozenset((OTHER,)),
        now=101,
        generation="campaign",
    )
    kinds = [relation.kind for relation in batch.relations]
    # Both MINT/OTHER venues pair with the THIRD/OTHER pool through the
    # verified hub, so two synthetic paths (each with its direct-vs-synthetic
    # residual against pool-d) are discovered.
    assert kinds.count("DIRECT_MARKET") == 4
    assert kinds.count("VENUE_FRAGMENTATION") == 1
    assert kinds.count("SYNTHETIC_CROSS") == 2
    assert kinds.count("DIRECT_SYNTHETIC_RESIDUAL") == 2
    assert batch.truncated is False

    synthetic = next(r for r in batch.relations if r.kind == "SYNTHETIC_CROSS")
    assert SYNTHETIC_LEGS_VERIFIED in synthetic.provenance_flags
    assert synthetic.atomicity_class == "RESEARCH_ONLY"

    # Every market-derived relation carries venue/pool liquidity provenance so
    # shared pools can never be counted as independent liquidity.
    for relation in batch.relations:
        if relation.market_ids:
            assert relation.correlation_groups and relation.liquidity_resources


def test_relation_generator_identity_gate_and_capital_edges_fail_closed():
    assets, markets = _fixture_universe()
    # Identity gate: an unverified hub asset removes every market that names it
    # from relation discovery; only the fully verified pair survives.
    unverified_hub = replace(asset(OTHER), verification_state=ResolutionState.CANDIDATE)
    batch = generate(
        (asset(MINT), unverified_hub, asset(THIRD)),
        markets,
        (),
        hubs=frozenset((OTHER,)),
        now=101,
        generation="campaign",
    )
    assert [relation.kind for relation in batch.relations] == ["DIRECT_MARKET"]

    # FLASH_CAPITAL: a qualified lender edge with current positive capacity
    # joins the relation set with the LENDER_QUALIFIED provenance flag...
    qualified = capital()
    capital_batch = generate(
        (asset(),),
        (),
        (),
        hubs=frozenset(),
        now=101,
        generation="campaign",
        capital_edges=(qualified,),
    )
    assert [relation.kind for relation in capital_batch.relations] == ["FLASH_CAPITAL"]
    assert LENDER_QUALIFIED in capital_batch.relations[0].provenance_flags
    assert capital_batch.relations[0].atomicity_class == "LOCAL_ATOMIC_CANDIDATE"

    # ...while zero observed capacity, stale evidence (> 30 s) and an asset id
    # outside the verified identity set all fail closed (no relation emitted).
    # (The edge owner itself refuses non-LOCAL_ATOMIC_CANDIDATE atomicity at
    # construction, so that gate cannot even be bypassed by a caller.)
    zero_capacity = replace(qualified, max_amount_live=0)
    stale = replace(qualified, evidence=evidence("lender", 10, timestamp=1))
    unverified_asset = replace(qualified, asset_id="unverified")
    denied = generate(
        (asset(),),
        (),
        (),
        hubs=frozenset(),
        now=101,
        generation="campaign",
        capital_edges=(zero_capacity, stale, unverified_asset),
    )
    assert denied.relations == ()
