"""Stream H relation-generator tightening: positive and negative evidence.

Covers: synthetic A/HUB/B identity-proof gates, structural parity common
underlying + representation distinction, cross-chain research-only
classification, lender qualification flags, aggregator alias independence
rules and bounded-cycle per-edge proof exclusions.
"""

from dataclasses import replace

from src.assets.resolution.evidence import EvidenceStore, digest
from src.assets.resolution.resolver import (
    AssetIdentity,
    AssetResolutionJob,
    ResolutionState,
    resolve,
)
from src.discovery.dynamic_universe.promotion import (
    MarketProof,
    PromotionBoundary,
    PromotionStage,
    QPRReadiness,
)
from src.discovery.dynamic_universe.universe import MarketIdentity
from src.market.observations import ObservationBatch
from src.strategy.arbitrage_graph import (
    CircularShadowRoute,
    DirectedQuoteEdge,
    UniversalArbitrageGraph,
    VenueIdentity,
)
from src.strategy.relation_generators.generators import (
    ANCHOR_UNDERLYING_PROVEN,
    CROSS_CHAIN_RESEARCH_ONLY,
    LENDER_QUALIFIED,
    REPRESENTATION_DISTINCT,
    SYNTHETIC_LEGS_VERIFIED,
    StructuralAnchor,
    generate,
    shortlist_verified_cycles,
)
from tests.test_dynamic_asset_resolution import (
    MINT,
    OTHER,
    candidate,
    evidence,
    proof,
)
from tests.test_dynamic_flash_capital import capital
from tests.test_dynamic_universe import market
from tests.test_dynamic_promotion_campaign import readiness

THIRD = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
SUI_BTC = "0x0000000000000000000000000000000000000000000000000000000000000002::btc::BTC"


def asset(identifier=MINT, **changes):
    return resolve(
        AssetResolutionJob("solana", identifier, "campaign"),
        (candidate(identifier=identifier, **changes),),
        (proof(identifier=identifier),),
        now=101,
    ).identity


def sui_asset(**changes):
    return AssetIdentity(
        "sui-btc",
        "sui",
        SUI_BTC,
        "BTC",
        9,
        "0x2::btc",
        "btc",
        "bridged",
        "campaign",
        ("sui-ref",),
        "sui-gen",
        **changes,
    )


def kinds(batch):
    return {r.kind for r in batch.relations}


def test_synthetic_requires_verified_hub_and_both_real_legs():
    assets = (asset(MINT), asset(OTHER), asset(THIRD))
    markets = (
        market(),
        market(
            market_id="pool-c",
            base=THIRD,
            correlation_group="pool-c",
            underlying_resources=("pool-c",),
        ),
    )
    batch = generate(
        assets, markets, (), hubs=frozenset((OTHER,)), now=101, generation="campaign"
    )
    synthetic = [r for r in batch.relations if r.kind == "SYNTHETIC_CROSS"]
    assert synthetic and all(
        SYNTHETIC_LEGS_VERIFIED in r.provenance_flags for r in synthetic
    )
    assert all(r.correlation_groups and r.liquidity_resources for r in synthetic)

    # Negative: a hub that is not an identity-verified asset is refused even
    # though a market pair references it.
    batch = generate(
        assets, markets, (), hubs=frozenset((THIRD,)), now=101, generation="campaign"
    )
    assert not any(r.kind == "SYNTHETIC_CROSS" for r in batch.relations)


def test_unverified_leg_assets_are_excluded_from_all_relations():
    candidate_asset = replace(asset(), verification_state=ResolutionState.CANDIDATE)
    markets = (market(),)
    batch = generate(
        (candidate_asset, asset(OTHER)),
        markets,
        (),
        hubs=frozenset(),
        now=101,
        generation="campaign",
    )
    assert batch.relations == ()


def test_alias_markets_without_verified_assets_emit_nothing():
    # Symbol-only collisions never become relations: assets arrive unresolved.
    from src.assets.resolution.resolver import resolve as _resolve

    receipt = _resolve(
        AssetResolutionJob("solana", "COLLISION", "campaign"),
        (candidate(), candidate(identifier=OTHER, symbol="COLLISION")),
        (proof(), proof(identifier=OTHER)),
        now=101,
    )
    assert receipt.state == ResolutionState.AMBIGUOUS and receipt.identity is None
    batch = generate(
        (), (market(),), (), hubs=frozenset(), now=101, generation="campaign"
    )
    assert batch.relations == ()


def test_parity_requires_proven_underlying_and_distinct_representations():
    same = (
        asset(MINT, economic_underlying="btc", representation_kind="wrapped"),
        asset(OTHER, economic_underlying="btc", representation_kind="native"),
    )
    batch = generate(same, (), (), hubs=frozenset(), now=101, generation="campaign")
    parity = [r for r in batch.relations if r.kind == "STRUCTURAL_PARITY"]
    assert len(parity) == 1
    assert REPRESENTATION_DISTINCT in parity[0].provenance_flags
    assert parity[0].representation_kinds == ("native", "wrapped")
    assert parity[0].atomicity_class == "SIGNAL_REBALANCE_ONLY"

    # Negative: identical representation kind and program on the same chain is
    # an alias, not parity.
    alias = (
        asset(MINT, economic_underlying="btc", representation_kind="wrapped"),
        asset(OTHER, economic_underlying="btc", representation_kind="wrapped"),
    )
    batch = generate(alias, (), (), hubs=frozenset(), now=101, generation="campaign")
    assert kinds(batch) == set()


def test_unknown_representation_or_underlying_never_produces_parity():
    unknown_underlying = (
        asset(MINT, representation_kind="wrapped"),
        asset(OTHER, representation_kind="native"),
    )
    batch = generate(
        unknown_underlying, (), (), hubs=frozenset(), now=101, generation="campaign"
    )
    assert kinds(batch) == set()
    unknown_representation = (
        asset(MINT, economic_underlying="btc"),
        asset(OTHER, economic_underlying="btc", representation_kind="native"),
    )
    batch = generate(
        unknown_representation, (), (), hubs=frozenset(), now=101, generation="campaign"
    )
    assert kinds(batch) == set()


def test_cross_chain_basis_is_research_rebalance_only():
    assets = (
        sui_asset(),
        asset(MINT, economic_underlying="btc", representation_kind="wrapped"),
    )
    batch = generate(assets, (), (), hubs=frozenset(), now=101, generation="campaign")
    cross = [r for r in batch.relations if r.kind == "CROSS_CHAIN_BASIS"]
    assert len(cross) == 1
    assert cross[0].atomicity_class == "SIGNAL_REBALANCE_ONLY"
    assert CROSS_CHAIN_RESEARCH_ONLY in cross[0].provenance_flags
    assert set(cross[0].representation_kinds) == {"bridged", "wrapped"}
    assert not cross[0].market_ids


def test_capital_edges_join_only_after_lender_qualification_flags():
    qualified = capital()
    batch = generate(
        (asset(),),
        (),
        (),
        hubs=frozenset(),
        now=101,
        generation="campaign",
        capital_edges=(qualified,),
    )
    assert [r.kind for r in batch.relations] == ["FLASH_CAPITAL"]
    assert LENDER_QUALIFIED in batch.relations[0].provenance_flags
    assert batch.relations[0].atomicity_class == "LOCAL_ATOMIC_CANDIDATE"

    stale = replace(qualified, evidence=evidence("lender", 10, timestamp=1))
    zero = replace(qualified, max_amount_live=0)
    wrong_generation = replace(
        qualified, evidence=evidence("lender", 10, generation="other")
    )
    unverified_asset = replace(qualified, asset_id="unverified")
    batch = generate(
        (asset(),),
        (),
        (),
        hubs=frozenset(),
        now=101,
        generation="campaign",
        capital_edges=(stale, zero, wrong_generation, unverified_asset),
    )
    assert batch.relations == ()


def test_anchor_relations_require_underlying_provenance_flag():
    a = asset()
    markets = (market(),)
    unproven = (StructuralAnchor(a.asset_id, "USD", "USD", evidence(), True),)
    batch = generate(
        (a, asset(OTHER)),
        markets,
        unproven,
        hubs=frozenset(),
        now=101,
        generation="campaign",
    )
    assert kinds(batch) == {"DIRECT_MARKET"}
    proven = (
        StructuralAnchor(
            a.asset_id, "USD", "USD", evidence(), True, underlying_proven=True
        ),
    )
    batch = generate(
        (a, asset(OTHER)),
        markets,
        proven,
        hubs=frozenset(),
        now=101,
        generation="campaign",
    )
    stable = [r for r in batch.relations if r.kind == "STABLE_RESIDUAL"]
    assert len(stable) == 1
    assert ANCHOR_UNDERLYING_PROVEN in stable[0].provenance_flags


def test_aggregator_aliases_and_shared_pools_are_never_independent():
    assets = (asset(MINT), asset(OTHER))
    # Two aggregator front-ends over the SAME pool resource with different
    # correlation groups: resource overlap forbids venue fragmentation.
    shared_pool = (
        market(
            market_id="front-a",
            venue="agg-a",
            correlation_group="agg-a",
        ),
        market(
            market_id="front-b",
            venue="agg-b",
            correlation_group="agg-b",
        ),
    )
    batch = generate(
        assets, shared_pool, (), hubs=frozenset(), now=101, generation="campaign"
    )
    assert not any(r.kind == "VENUE_FRAGMENTATION" for r in batch.relations)

    # Same correlation group (pure API aliasing) is also refused.
    aliases = tuple(
        market(market_id=f"alias-{i}", correlation_group="pool") for i in range(3)
    )
    batch = generate(
        assets, aliases, (), hubs=frozenset(), now=101, generation="campaign"
    )
    assert not any(r.kind == "VENUE_FRAGMENTATION" for r in batch.relations)
    # ... while every emitted relation still carries group/resource provenance.
    assert all(r.correlation_groups and r.liquidity_resources for r in batch.relations)


def test_independent_venues_still_fragment_with_full_provenance():
    assets = (asset(MINT), asset(OTHER))
    venues = (
        market(),
        market(
            market_id="pool-b",
            venue="raydium",
            correlation_group="pool-b",
            underlying_resources=("pool-b",),
        ),
    )
    batch = generate(
        assets, venues, (), hubs=frozenset(), now=101, generation="campaign"
    )
    fragmentation = [r for r in batch.relations if r.kind == "VENUE_FRAGMENTATION"]
    assert len(fragmentation) == 1
    assert set(fragmentation[0].correlation_groups) == {"pool", "pool-b"}
    assert set(fragmentation[0].liquidity_resources) == {"pool", "pool-b"}


def _shortlist_store(tmp_path, *, corrupt_edge: bool):
    store = EvidenceStore(tmp_path)
    assets = []
    for identifier in (MINT, OTHER, THIRD):
        payload = {"identifier": identifier}
        registry = replace(evidence(), response_hash=digest(payload))
        rpc = replace(evidence("asset-rpc", 10), response_hash=digest(payload))
        store.append(registry, payload)
        store.append(rpc, payload)
        assets.append(
            resolve(
                AssetResolutionJob("solana", identifier, "campaign"),
                (candidate(identifier=identifier, evidence=registry),),
                (proof(identifier=identifier, evidence=rpc),),
                now=101,
            ).identity
        )
    boundary = PromotionBoundary(
        "campaign", store, readiness_evaluator=readiness(store)
    )
    edges, receipts = [], []
    mints, amounts = (MINT, OTHER, THIRD, MINT), (10, 11, 12, 16)
    for i in range(3):
        m = market(
            market_id=f"pool-{i}",
            base=mints[i],
            quote=mints[i + 1],
            correlation_group=f"pool-{i}",
            underlying_resources=(f"pool-{i}",),
        )
        proofs = []
        for provider in ("rpc-a", "rpc-b"):
            raw = {"market": m.market_id, "state": "exact"}
            e = replace(evidence(provider, 10), response_hash=digest(raw))
            store.append(e, raw)
            proofs.append(MarketProof(m, e, m.base, m.quote, digest(raw)))
        template = _quote_template(store)
        q = replace(
            template,
            input_mint=m.base,
            output_mint=m.quote,
            input_amount=amounts[i],
            expected_output=amounts[i + 1],
            guaranteed_output=amounts[i + 1],
            response_hash=proofs[0].evidence.response_hash,
        )
        receipts.append(boundary.evaluate(m, tuple(assets), tuple(proofs), q, now=101))
        edges.append(DirectedQuoteEdge(VenueIdentity(m.program_id, m.market_id), q))
    if corrupt_edge:
        # A receipt whose durable payload is no longer exact-verified: the
        # edge state flag fails and the edge must be excluded, not projected.
        target = receipts[1]
        payload = {
            "market_id": target.market_id,
            "generation": boundary.generation,
            "stage": PromotionStage.MARKET_VERIFIED,
            "reasons": ["fixture_not_exact"],
            "evidence_refs": [],
            "observation_id": target.observation_id,
            "observation_hash": None,
            "paper_net": None,
        }
        ref = store.append(
            replace(evidence("fixture", 10), response_hash=digest(payload)), payload
        )
        receipts[1] = replace(target, durable_ref=ref)
    graph = UniversalArbitrageGraph(
        ObservationBatch(tuple(e.observation for e in edges), published_at=101),
        tuple(edges),
    )
    return boundary, graph, tuple(receipts)


def _quote_template(store):
    from src.market.observations import MarketObservationV2, ObservationGeneration

    return MarketObservationV2(
        provider="rpc-a",
        source="exact-fixture",
        input_mint=MINT,
        output_mint=OTHER,
        input_amount=10,
        expected_output=12,
        guaranteed_output=11,
        slot=10,
        observed_at=100,
        commitment="finalized",
        response_hash=digest({"pool": "pool", "state": "exact"}),
        request_fingerprint=digest("request"),
        generation=ObservationGeneration(
            "mainnet", "rpc", "campaign", "campaign", "fixture"
        ),
    )


def test_bounded_cycles_exclude_unproven_edges_with_typed_reasons(tmp_path):
    boundary, graph, receipts = _shortlist_store(
        tmp_path / "proven", corrupt_edge=False
    )
    exclusions: list[tuple[str, str]] = []
    shortlist = shortlist_verified_cycles(
        graph, boundary, receipts, start_asset=MINT, now=101, exclusions=exclusions
    )
    assert shortlist.routes and shortlist.routes[0].hop_count == 3
    assert exclusions == []

    boundary2, graph2, receipts2 = _shortlist_store(
        tmp_path / "corrupt", corrupt_edge=True
    )
    exclusions2: list[tuple[str, str]] = []
    shortlist2 = shortlist_verified_cycles(
        graph2, boundary2, receipts2, start_asset=MINT, now=101, exclusions=exclusions2
    )
    assert shortlist2.routes == ()
    assert ("edge_state_not_exact_verified",) and any(
        reason == "edge_state_not_exact_verified" for _, reason in exclusions2
    )


def test_missing_receipt_excludes_edge_and_three_hop_cycle_cannot_close(tmp_path):
    boundary, graph, receipts = _shortlist_store(tmp_path, corrupt_edge=False)
    exclusions: list[tuple[str, str]] = []
    shortlist = shortlist_verified_cycles(
        graph,
        boundary,
        receipts[:1] + receipts[2:],
        start_asset=MINT,
        now=101,
        exclusions=exclusions,
    )
    assert shortlist.routes == ()
    assert any(reason == "missing_exact_edge_receipt" for _, reason in exclusions)


def test_noncanonical_market_identity_is_refused():
    with __import__("pytest").raises(ValueError):
        MarketIdentity(
            "solana", "orca", "program", "pool", MINT, MINT, "30", "pool", ("pool",)
        )
