from dataclasses import replace

import pytest

from src.assets.resolution.evidence import EvidenceStore, digest
from src.discovery.dynamic_universe.ingestors import (
    deepbook_parser,
    RegistryIngestor,
    sanctum_parser,
)
from src.discovery.dynamic_universe.universe import (
    DiscoveryEnvelope,
    DynamicUniverse,
    Lifecycle,
    MarketIdentity,
)
from tests.test_dynamic_asset_resolution import candidate, evidence, MINT, OTHER


def market(**changes):
    return replace(
        MarketIdentity(
            "solana",
            "orca",
            "program",
            "pool",
            MINT,
            OTHER,
            "30",
            "pool",
            ("pool",),
            evidence(),
        ),
        **changes,
    )


def test_live_registry_and_market_arrive_and_retire(tmp_path):
    universe = DynamicUniverse("campaign", EvidenceStore(tmp_path))
    envelope = DiscoveryEnvelope(evidence(), (candidate(),), (market(),), True)
    universe.ingest(envelope, now=101)
    assert len(universe.records) == 2 and len(universe.active_markets()) == 1
    universe.ingest(
        DiscoveryEnvelope(evidence(timestamp=102), complete_snapshot=True), now=102
    )
    assert not universe.active_markets()
    assert all(r.lifecycle == Lifecycle.RETIRED for r in universe.records.values())
    assert len(universe.history) == 4


def test_duplicate_market_provider_alias_is_one_resource(tmp_path):
    universe = DynamicUniverse("campaign", EvidenceStore(tmp_path))
    universe.ingest(DiscoveryEnvelope(evidence(), markets=(market(),)), now=101)
    other_source = replace(evidence("router-b"), source="https://example.com/other")
    universe.ingest(
        DiscoveryEnvelope(other_source, markets=(market(evidence=other_source),)),
        now=101,
    )
    assert len(universe.active_markets()) == 1


def test_partial_stale_or_negative_snapshot_never_retires(tmp_path):
    universe = DynamicUniverse("campaign", EvidenceStore(tmp_path))
    universe.ingest(
        DiscoveryEnvelope(evidence(), markets=(market(),), complete_snapshot=True),
        now=101,
    )
    for envelope in [
        DiscoveryEnvelope(replace(evidence(), negative_reason="timeout")),
        DiscoveryEnvelope(evidence(timestamp=1), complete_snapshot=True),
        DiscoveryEnvelope(evidence(), truncated=True),
    ]:
        universe.ingest(envelope, now=400)
    assert len(universe.active_markets()) == 1
    assert len(universe.negative_evidence) == 2


def test_conflicting_duplicate_metadata_fails_before_mutation(tmp_path):
    universe = DynamicUniverse("campaign", EvidenceStore(tmp_path))
    with pytest.raises(ValueError):
        universe.ingest(
            DiscoveryEnvelope(evidence(), assets=(candidate(), candidate(decimals=6))),
            now=101,
        )
    assert not universe.records


def test_registry_schema_drift_and_bounded_paging():
    body = (
        '[[sanctum_lst_list]]\nmint="'
        + MINT
        + '"\nsymbol="NEW"\ndecimals=9\ntoken_program="'
        + candidate().program_or_package
        + '"\n'
    )

    class Fetch:
        def fetch(self, *_):
            return {"body": body}, evidence()

    ingestor = RegistryIngestor(
        Fetch(), "https://example.com", "registry", sanctum_parser, max_rows=1
    )
    first = ingestor.poll(None, 1)[0]
    assert first.assets[0].symbol == "NEW" and first.complete_snapshot
    assert ingestor.poll(None, 0) == ()
    body = "{}"
    failed = ingestor.poll(None, 1)[0]
    assert failed.evidence.negative_reason == "schema_drift_or_invalid_cursor"


def test_deepbook_uses_full_coin_type_not_symbol():
    body = """export const mainnetCoins: CoinMap = {
    SUI: { type: `0x2::sui::SUI`, scalar: 1000000000, },
    USDC: { type: `0x3::usdc::USDC`, scalar: 1000000, },
};
export const mainnetPools: PoolMap = {
    SUI_USDC: { address: `0x4`, baseCoin: 'SUI', quoteCoin: 'USDC', },
};"""
    assets, markets = deepbook_parser(body, evidence())
    assert len(assets) == 2 and len(markets) == 1
    assert markets[0].base.endswith("::sui::SUI")
    assert markets[0].fee_tier == "unverified"


def test_universe_cap(tmp_path):
    universe = DynamicUniverse("campaign", EvidenceStore(tmp_path), max_entities=1)
    with pytest.raises(ValueError):
        universe.ingest(
            DiscoveryEnvelope(evidence(), (candidate(),), (market(),)), now=101
        )
    assert not universe.records
