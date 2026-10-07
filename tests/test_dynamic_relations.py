from dataclasses import replace

import pytest

from src.assets.resolution.resolver import resolve, AssetResolutionJob
from src.discovery.dynamic_universe.universe import Lifecycle
from src.strategy.relation_generators.generators import (
    StructuralAnchor,
    bounded_exact_cycles,
    generate,
)
from src.strategy.relation_generators.heat import HeatInputs, HeatScheduler, heat
from tests.test_dynamic_asset_resolution import candidate, proof, evidence, MINT, OTHER
from tests.test_dynamic_universe import market

THIRD = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"


def asset(identifier=MINT):
    return resolve(
        AssetResolutionJob("solana", identifier, "campaign"),
        (candidate(identifier=identifier),),
        (proof(identifier=identifier),),
        now=101,
    ).identity


def test_direct_fragmented_synthetic_and_anchors_are_evidence_driven():
    assets = tuple(asset(mint) for mint in (MINT, OTHER, THIRD))
    markets = (
        market(),
        market(
            market_id="pool-b",
            venue="raydium",
            correlation_group="pool-b",
            underlying_resources=("pool-b",),
        ),
        market(
            market_id="pool-c",
            base=THIRD,
            correlation_group="pool-c",
            underlying_resources=("pool-c",),
        ),
        market(
            market_id="pool-d",
            base=MINT,
            quote=THIRD,
            correlation_group="pool-d",
            underlying_resources=("pool-d",),
        ),
    )
    anchors = tuple(
        StructuralAnchor(assets[0].asset_id, kind, "SOL", evidence(), True)
        for kind in ("LST", "NAV", "USD", "WRAPPER", "ORACLE", "PARITY")
    )
    batch = generate(
        assets,
        markets,
        anchors,
        hubs=frozenset((OTHER,)),
        now=101,
        generation="campaign",
    )
    kinds = {r.kind for r in batch.relations}
    assert {
        "DIRECT_MARKET",
        "VENUE_FRAGMENTATION",
        "SYNTHETIC_CROSS",
        "DIRECT_SYNTHETIC_RESIDUAL",
        "LST_FAIR_VALUE",
        "NAV_BASIS",
        "STABLE_RESIDUAL",
        "WRAPPER_BASIS",
        "ORACLE_MARKET",
        "STRUCTURAL_PARITY",
    } <= kinds
    assert all(r.evidence_refs for r in batch.relations)
    assert batch == generate(
        tuple(reversed(assets)),
        tuple(reversed(markets)),
        tuple(reversed(anchors)),
        hubs=frozenset((OTHER,)),
        now=101,
        generation="campaign",
    )


def test_aliases_are_not_independent_and_budget_is_bounded():
    assets = (asset(), asset(OTHER))
    aliases = tuple(market(market_id=f"alias-{i}") for i in range(100))
    batch = generate(
        assets,
        aliases,
        (),
        hubs=frozenset((OTHER,)),
        now=101,
        generation="campaign",
        max_work=10,
        max_relations=10,
    )
    assert len(batch.relations) == 10 and batch.examined == 10 and batch.truncated
    assert not any(r.kind == "VENUE_FRAGMENTATION" for r in batch.relations)


def test_discovery_relations_cannot_become_exact_cycles():
    with pytest.raises(ValueError, match="research relations"):
        bounded_exact_cycles(graph=(), policy=None, now=101)


def test_flash_capacity_is_a_separate_supported_relation():
    from tests.test_dynamic_flash_capital import capital

    batch = generate(
        (asset(),),
        (),
        (),
        hubs=frozenset(),
        now=101,
        generation="campaign",
        capital_edges=(capital(),),
    )
    assert [r.kind for r in batch.relations] == ["FLASH_CAPITAL"]
    assert batch.relations[0].atomicity_class == "LOCAL_ATOMIC_CANDIDATE"


def test_stale_or_wrong_generation_anchors_do_not_promote():
    a = asset()
    anchors = (StructuralAnchor(a.asset_id, "NAV", "SOL", evidence(timestamp=1), True),)
    batch = generate(
        (a, asset(OTHER)),
        (market(evidence=evidence(timestamp=500)),),
        anchors,
        hubs=frozenset(),
        now=500,
        generation="campaign",
    )
    assert {r.kind for r in batch.relations} == {"DIRECT_MARKET"}


def test_heat_demotes_and_never_counts_one_venue_as_hot():
    strong = HeatInputs(
        executable_depth=3,
        independent_venues=2,
        structural_anchor=2,
        recurrence=2,
        verification_success=1,
    )
    assert heat(strong)[1] == Lifecycle.HOT
    assert heat(replace(strong, staleness=1))[1] == Lifecycle.COLD
    assert heat(replace(strong, independent_venues=1))[1] != Lifecycle.HOT
    assert heat(replace(strong, event_only=True))[1] == Lifecycle.EVENT


def test_scheduler_learns_blind_window_and_requires_trigger():
    scheduler = HeatScheduler(request_budget=2)
    assert not scheduler.admit(
        "rpc", priority=3, state=Lifecycle.HOT, anomaly=False, now=100
    )
    scheduler.observe_failure("rpc", now=100, reason="rate_limit", retry_after=10)
    assert not scheduler.admit(
        "rpc", priority=3, state=Lifecycle.HOT, anomaly=True, now=105
    )
    assert scheduler.admit(
        "rpc", priority=3, state=Lifecycle.HOT, anomaly=True, now=111
    )
    assert scheduler.admit(
        "registry", priority=0, state=Lifecycle.COLD, anomaly=False, now=111
    )
    assert not scheduler.admit(
        "registry", priority=0, state=Lifecycle.COLD, anomaly=False, now=111
    )
    assert scheduler.negative_evidence == [("rpc", 100, "rate_limit")]
