from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from solders.pubkey import Pubkey

from src.config.chain_registry import ChainRegistry
from src.market.discovery import DiscoveryRequest, PublicMarketDiscovery
from src.market.observations import (
    CorrectionKind,
    MarketObservationV2,
    ObservationError,
    ObservationGeneration,
    SourceCursor,
)
from src.market.source_catalog import (
    SourceAccess,
    SourceFamily,
    load_market_source_catalog,
)
from src.market.streams import DurableCursorStore
from src.strategy.arbitrage_graph import (
    CircularGraphCandidateDetector,
    CircularGraphPolicy,
    GraphSearchStop,
    VenueIdentity,
)
from src.strategy.interfaces import StrategyMode
from src.strategy.market_graph_ingest import (
    ShadowMarketBinding,
    ShadowMarketGraphIngest,
)
from src.strategy.strategies import OrderbookAmmStrategy

pytestmark = pytest.mark.unit
NOW = 1000.0
GENESIS = ChainRegistry.load_default().canonical_genesis_hashes["mainnet-beta"]


def _key(index):
    return str(Pubkey.from_bytes(bytes([index]) * 32))


A, B, C = (_key(i) for i in (1, 2, 3))


class FixtureTransport:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    async def request(self, method, url, *, params=None, headers=None, json_body=None):
        self.calls.append((method, url, params, headers, json_body))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        status, payload = reply
        return status, {}, payload


def _payload(source, markets=(10,), *, mint_a=A):
    if source == "dexscreener":
        return [
            dict(
                chainId="solana",
                pairAddress=_key(i),
                dexId="fixture-dex",
                baseToken=dict(address=mint_a, symbol="SAME"),
                quoteToken=dict(address=B, symbol="SAME"),
                priceUsd="12345",
                liquidity=dict(usd=999999),
            )
            for i in markets
        ]
    if source == "raydium":
        return dict(
            success=True,
            data=dict(
                data=[
                    dict(id=_key(i), mintA=dict(address=mint_a), mintB=dict(address=B))
                    for i in markets
                ]
            ),
        )
    if source == "geckoterminal":
        return dict(
            data=[
                dict(
                    attributes=dict(address=_key(i)),
                    relationships=dict(
                        base_token=dict(data=dict(id="solana_" + mint_a)),
                        quote_token=dict(data=dict(id="solana_" + B)),
                        dex=dict(data=dict(id="fixture-dex")),
                    ),
                )
                for i in markets
            ]
        )
    return dict(
        data=[
            dict(address=_key(i), token_x=dict(address=mint_a), token_y=dict(address=B))
            for i in markets
        ]
    )


def _request(source):
    return DiscoveryRequest(source, token_mint=A if source == "dexscreener" else None)


def _collect(transport, requests, **options):
    return asyncio.run(
        PublicMarketDiscovery(transport, load_market_source_catalog()).collect(
            requests, observed_at=NOW, **options
        )
    )


def _bindings():
    return tuple(
        ShadowMarketBinding(
            f"pool-{i}",
            source,
            "fixture-feed",
            VenueIdentity(_key(20), _key(10 + i)),
            (mint_a, mint_b),
            "recorded-fixture.v1",
        )
        for i, (source, mint_a, mint_b) in enumerate(
            (("raydium", A, B), ("orca", B, C), ("meteora-dlmm", C, A))
        )
    )


def _quote(binding, index, **changes):
    values = dict(
        provider=binding.source_id,
        source="offline-fixture",
        input_mint=(A, B, C)[index],
        output_mint=(B, C, A)[index],
        input_amount=10 + index,
        expected_output=30,
        guaranteed_output=11 + index if index < 2 else 15,
        slot=100,
        observed_at=NOW - 1,
        expires_at=NOW + 1,
        confidence="recorded",
        request_fingerprint=f"request-{index}",
        response_hash=f"response-{index}",
        generation=ObservationGeneration(genesis_hash=GENESIS),
        cursor=SourceCursor(binding.cursor_source, binding.binding_id, 0, 100),
    )
    values.update(changes)
    return MarketObservationV2(**values)


def _ready(bindings=None, **options):
    bindings = _bindings() if bindings is None else bindings
    bridge = ShadowMarketGraphIngest(load_market_source_catalog(), bindings, **options)
    quotes = tuple(_quote(binding, i) for i, binding in enumerate(bindings))
    for binding, quote in zip(bindings, quotes):
        assert bridge.ingest(binding.binding_id, quote)
    bridge.mark_backfill_complete("fixture-feed")
    return bridge, bindings, quotes


def _detect(snapshot):
    return CircularGraphCandidateDetector(CircularGraphPolicy(A, 10, 10)).detect(
        snapshot.graph, now=NOW
    )


def test_installable_catalog_separates_access_and_never_promotes_orderbooks():
    catalog = load_market_source_catalog()
    assert len(catalog.sources) == 43
    assert catalog.require("helius").access is SourceAccess.FREE_TIER_KEY
    assert catalog.require("yellowstone-grpc").access is SourceAccess.OPEN_SOURCE
    assert catalog.require("odos").access is SourceAccess.UNVERIFIED
    assert {
        s.source_id for s in catalog.sources if s.family is SourceFamily.ORDERBOOK
    } == {"phoenix-legacy", "openbook-v2", "manifest"}
    with pytest.raises(ValueError, match="unregistered"):
        catalog.require("unlisted")


@pytest.mark.parametrize(
    "source", ["dexscreener", "geckoterminal", "raydium", "meteora-dlmm"]
)
def test_discovery_collects_addresses_with_receipts_but_never_quotes(source):
    transport = FixtureTransport([(200, _payload(source))])
    batch = _collect(transport, (_request(source),))
    assert batch.market_count == 1
    (market,) = batch.markets
    (receipt,) = batch.receipts
    assert market.receipt_id == receipt.identity
    assert receipt.response_hash and receipt.request_fingerprint
    assert market.mints == tuple(sorted((A, B)))
    assert not hasattr(market, "input_amount")
    assert not hasattr(market, "guaranteed_output")
    method, url, params, headers, body = transport.calls[0]
    assert method == "GET" and url.startswith("https://")
    assert headers is None and body is None
    assert batch.rejections == ()


def test_discovery_keeps_two_sources_provenance_and_counts_physical_pool_once():
    batch = _collect(
        FixtureTransport([(200, _payload("dexscreener")), (200, _payload("raydium"))]),
        (_request("dexscreener"), _request("raydium")),
    )
    assert batch.market_count == 1
    assert len(batch.markets) == len(batch.receipts) == 2
    assert {market.source_id for market in batch.markets} == {"dexscreener", "raydium"}


def test_response_identity_changes_with_content_not_mapping_key_order():
    payload = _payload("raydium")
    first = _collect(FixtureTransport([(200, payload)]), (_request("raydium"),))
    reordered = {"data": payload["data"], "success": True}
    second = _collect(FixtureTransport([(200, reordered)]), (_request("raydium"),))
    assert first.receipts == second.receipts
    changed = _collect(
        FixtureTransport([(200, _payload("raydium", mint_a=C))]), (_request("raydium"),)
    )
    assert first.receipts[0].identity != changed.receipts[0].identity


def test_discovery_cap_selects_same_markets_when_api_rows_reorder():
    first = _collect(
        FixtureTransport([(200, _payload("dexscreener", (10, 11, 12)))]),
        (_request("dexscreener"),),
        max_markets=2,
    )
    second = _collect(
        FixtureTransport([(200, _payload("dexscreener", (12, 11, 10)))]),
        (_request("dexscreener"),),
        max_markets=2,
    )
    assert tuple(m.market_id for m in first.markets) == tuple(
        m.market_id for m in second.markets
    )
    assert first.truncated and dict(first.rejections)["market-limit"] == 1


def test_wrong_chain_invalid_addresses_and_same_mint_are_not_markets():
    payload = _payload("dexscreener", (10, 11, 12))
    payload[0]["chainId"] = "ethereum"
    payload[1]["pairAddress"] = "BTC-USDC"
    payload[2]["baseToken"]["address"] = B
    batch = _collect(FixtureTransport([(200, payload)]), (_request("dexscreener"),))
    assert batch.markets == () and dict(batch.rejections)["invalid-market"] == 3


@pytest.mark.parametrize("status", [401, 429, 500])
def test_http_failures_stop_requests_without_retry_or_secret_body(status):
    transport = FixtureTransport(
        [(status, dict(secret="never-persist")), (200, _payload("raydium"))]
    )
    batch = _collect(transport, (_request("raydium"), _request("raydium")))
    assert len(transport.calls) == 1 and not batch.markets
    assert batch.receipts[0].http_status == status
    assert "never-persist" not in repr(batch)


def test_transport_error_is_redacted_and_cancellation_propagates():
    batch = _collect(
        FixtureTransport([RuntimeError("Authorization: sensitive")]),
        (_request("raydium"),),
    )
    assert dict(batch.rejections) == {"transport-error": 1}
    assert "sensitive" not in repr(batch)

    class CancelledTransport:
        async def request(self, *args, **kwargs):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        _collect(CancelledTransport(), (_request("raydium"),))


@pytest.mark.parametrize(
    "payload",
    [
        {"success": False, "data": {"data": []}},
        {"success": True, "data": []},
        {"success": True, "data": {"data": [None] * 1001}},
        [],
    ],
)
def test_schema_drift_is_explicit_and_never_silent_empty_success(payload):
    batch = _collect(FixtureTransport([(200, payload)]), (_request("raydium"),))
    assert not batch.markets and dict(batch.rejections) == {"invalid-schema": 1}
    assert batch.receipts[0].error == "invalid-schema"


def test_request_bounds_and_unimplemented_catalog_sources_fail_before_io():
    transport = FixtureTransport([])
    with pytest.raises(ValueError, match="1..8"):
        _collect(transport, (_request("raydium"),) * 9)
    with pytest.raises(ValueError):
        DiscoveryRequest("helius")
    with pytest.raises(ValueError):
        DiscoveryRequest("dexscreener", token_mint="SOL")
    with pytest.raises(ValueError):
        DiscoveryRequest("raydium", page=9)
    assert transport.calls == []


def test_bound_quotes_feed_existing_graph_with_exact_amounts_and_trace():
    bridge, bindings, quotes = _ready()
    discovered = _collect(
        FixtureTransport([(200, _payload("raydium", (10, 11, 12, 13)))]),
        (_request("raydium"),),
    )
    snapshot = bridge.publish(now=NOW, discovery=discovered)
    (route,) = _detect(snapshot).candidates
    assert route.amounts_base_units == (10, 11, 12, 15)
    assert len(snapshot.traces) == len(snapshot.graph.edges) == 3
    assert {trace.edge_identity for trace in snapshot.traces} == {
        edge.identity for edge in route.edges
    }
    assert snapshot.coverage.discovered_markets == 4
    assert (
        snapshot.coverage.exact_quoted_markets
        == snapshot.coverage.fresh_quoted_markets
        == 3
    )
    assert snapshot.coverage.batch_complete
    assert all(
        trace.response_hash and trace.decoder_revision for trace in snapshot.traces
    )


def test_discovery_records_cannot_be_admitted_as_quotes_or_auto_bindings():
    bridge, bindings, _ = _ready()
    discovery = _collect(
        FixtureTransport([(200, _payload("raydium"))]), (_request("raydium"),)
    )
    with pytest.raises(ValueError, match="cannot become graph quotes"):
        bridge.ingest(bindings[0].binding_id, discovery.markets[0])


@pytest.mark.parametrize(
    "change",
    ["provider", "cursor_source", "partition", "mint", "genesis", "provenance"],
)
def test_wrong_binding_or_domain_or_untraceable_observation_rejected(change):
    bindings = _bindings()
    bridge = ShadowMarketGraphIngest(load_market_source_catalog(), bindings)
    quote = _quote(bindings[0], 0)
    if change == "provider":
        quote = replace(quote, provider="jupiter")
    elif change in ("cursor_source", "partition"):
        quote = replace(
            quote,
            cursor=replace(
                quote.cursor,
                **(
                    {"source": "other"}
                    if change == "cursor_source"
                    else {"partition": "other"}
                ),
            ),
        )
    elif change == "mint":
        quote = replace(quote, input_mint=C)
    elif change == "genesis":
        quote = replace(quote, generation=ObservationGeneration(genesis_hash="foreign"))
    else:
        quote = replace(quote, response_hash=None)
    with pytest.raises(ValueError):
        bridge.ingest(bindings[0].binding_id, quote)
    assert not bridge.publish(now=NOW).graph.edges


@pytest.mark.parametrize(
    "source",
    [
        "phoenix-legacy",
        "openbook-v2",
        "manifest",
        "jupiter",
        "pyth-hermes",
        "binance-spot",
        "uniswap",
    ],
)
def test_orderbook_reference_opaque_router_and_foreign_domain_cannot_enter_spot_graph(
    source,
):
    binding = replace(_bindings()[0], source_id=source)
    with pytest.raises(ValueError, match="not an admitted Solana AMM"):
        ShadowMarketGraphIngest(load_market_source_catalog(), (binding,))
    assert OrderbookAmmStrategy().mode is StrategyMode.DISABLED


def test_missing_bound_market_blocks_even_with_source_backfill_complete():
    bindings = _bindings()
    bridge = ShadowMarketGraphIngest(load_market_source_catalog(), bindings)
    bridge.ingest(bindings[0].binding_id, _quote(bindings[0], 0))
    bridge.mark_backfill_complete("fixture-feed")
    snapshot = bridge.publish(now=NOW)
    assert snapshot.coverage.missing_bindings == ("pool-1", "pool-2")
    assert not snapshot.coverage.batch_complete
    assert _detect(snapshot).stop_reason is GraphSearchStop.INCOMPLETE_BATCH


def test_canonical_backfill_reconnect_and_epoch_rejection_are_reused():
    bridge, bindings, quotes = _ready()
    assert bridge.begin_reconnect() == 1
    assert not bridge.publish(now=NOW).graph.edges
    with pytest.raises(ObservationError, match="stale reconnect"):
        bridge.ingest(bindings[0].binding_id, quotes[0])
    for binding, quote in zip(bindings, quotes):
        bridge.ingest(
            binding.binding_id,
            replace(quote, cursor=replace(quote.cursor, reconnect_epoch=1)),
        )
    assert not bridge.publish(now=NOW).coverage.batch_complete
    bridge.mark_backfill_complete("fixture-feed")
    assert bridge.publish(now=NOW).coverage.batch_complete


def test_stale_and_slot_mismatch_keep_coverage_honest_and_reject_candidates():
    bridge, _, _ = _ready()
    snapshot = bridge.publish(now=NOW + 10)
    assert snapshot.coverage.exact_quoted_markets == 3
    assert snapshot.coverage.fresh_quoted_markets == 0
    detector = CircularGraphCandidateDetector(CircularGraphPolicy(A, 10, 10))
    assert detector.detect(snapshot.graph, now=NOW + 10).candidates == ()
    assert (
        detector.detect(bridge.publish(now=NOW - 2).graph, now=NOW - 2).candidates == ()
    )
    bindings = _bindings()
    bridge = ShadowMarketGraphIngest(load_market_source_catalog(), bindings)
    for i, binding in enumerate(bindings):
        quote = _quote(binding, i)
        bridge.ingest(
            binding.binding_id,
            replace(quote, slot=100 + i, cursor=replace(quote.cursor, slot=100 + i)),
        )
    bridge.mark_backfill_complete("fixture-feed")
    assert not bridge.publish(now=NOW).coverage.batch_complete


def test_duplicate_cursors_and_changed_identity_never_overwrite_trace():
    bridge, bindings, quotes = _ready()
    before = bridge.publish(now=NOW)
    assert bridge.ingest(bindings[0].binding_id, quotes[0]) is False
    with pytest.raises(ValueError, match="identity reused"):
        bridge.ingest(bindings[0].binding_id, replace(quotes[0], expected_output=99))
    assert bridge.publish(now=NOW) == before


def test_corrections_retractions_and_generation_invalidation_remove_edges_and_traces():
    bridge, bindings, quotes = _ready()
    corrected = replace(
        quotes[0],
        cursor=replace(quotes[0].cursor, offset=1),
        response_hash="corrected",
        guaranteed_output=12,
        correction_kind=CorrectionKind.CORRECTION,
        supersedes_id=quotes[0].observation_id,
    )
    bridge.ingest(bindings[0].binding_id, corrected)
    snapshot = bridge.publish(now=NOW)
    assert quotes[0].observation_id not in {t.observation_id for t in snapshot.traces}
    assert _detect(snapshot).candidates == ()  # Exact amount coupling lost.
    retract = replace(
        corrected,
        cursor=replace(corrected.cursor, offset=2),
        response_hash="retract",
        correction_kind=CorrectionKind.RETRACTION,
        supersedes_id=corrected.observation_id,
    )
    bridge.ingest(bindings[0].binding_id, retract)
    assert bridge.publish(now=NOW).coverage.missing_bindings == ("pool-0",)
    bridge.invalidate_generation(quotes[1].generation.identity)
    empty = bridge.publish(now=NOW)
    assert empty.graph.edges == empty.traces == ()


def test_event_budget_rejects_before_canonical_state_mutation():
    bridge, bindings, quotes = _ready(max_events=3)
    before = bridge.publish(now=NOW)
    assert bridge.ingest(bindings[0].binding_id, quotes[0]) is False
    with pytest.raises(ValueError, match="window full"):
        bridge.ingest(
            bindings[0].binding_id,
            replace(
                quotes[0],
                response_hash="new",
                cursor=replace(quotes[0].cursor, offset=1),
            ),
        )
    assert bridge.publish(now=NOW) == before


def test_binding_order_does_not_change_route_or_trace_identity():
    first, _, _ = _ready()
    bindings = _bindings()
    second = ShadowMarketGraphIngest(
        load_market_source_catalog(), tuple(reversed(bindings))
    )
    for i in (2, 1, 0):
        second.ingest(bindings[i].binding_id, _quote(bindings[i], i))
    second.mark_backfill_complete("fixture-feed")
    left, right = first.publish(now=NOW), second.publish(now=NOW)
    assert left == right
    assert _detect(left).candidates[0].identity == _detect(right).candidates[0].identity


def test_durable_resume_cursor_does_not_create_phantom_market_coverage(tmp_path):
    bindings = _bindings()
    store = DurableCursorStore(tmp_path / "cursors.json")
    first, _, quotes = _ready(cursor_store=store)
    assert first.publish(now=NOW).coverage.batch_complete
    resumed = ShadowMarketGraphIngest(
        load_market_source_catalog(), bindings, cursor_store=store
    )
    resumed.mark_backfill_complete("fixture-feed")
    assert not resumed.publish(now=NOW).coverage.batch_complete
    assert not resumed.publish(now=NOW).graph.edges
    epoch = resumed.begin_reconnect()
    for binding, quote in zip(bindings, quotes):
        resumed.ingest(
            binding.binding_id,
            replace(quote, cursor=replace(quote.cursor, reconnect_epoch=epoch)),
        )
    resumed.mark_backfill_complete("fixture-feed")
    assert resumed.publish(now=NOW).coverage.batch_complete


def test_market_binding_contract_cannot_be_mutated_after_fanout_creation():
    bridge, _, _ = _ready()
    with pytest.raises(TypeError):
        bridge.bindings["injected"] = _bindings()[0]


def test_duplicate_correction_and_retraction_replay_is_idempotent():
    bridge, bindings, quotes = _ready()
    corrected = replace(
        quotes[0],
        response_hash="corrected",
        cursor=replace(quotes[0].cursor, offset=1),
        correction_kind=CorrectionKind.CORRECTION,
        supersedes_id=quotes[0].observation_id,
    )
    assert bridge.ingest(bindings[0].binding_id, corrected)
    assert bridge.ingest(bindings[0].binding_id, corrected) is False
    retract = replace(
        corrected,
        response_hash="retracted",
        cursor=replace(corrected.cursor, offset=2),
        correction_kind=CorrectionKind.RETRACTION,
        supersedes_id=corrected.observation_id,
    )
    assert bridge.ingest(bindings[0].binding_id, retract)
    assert bridge.ingest(bindings[0].binding_id, retract) is False
    assert bridge.publish(now=NOW).coverage.missing_bindings == ("pool-0",)


def test_nonfinite_quote_evidence_fails_before_stream_state_mutation():
    bridge, bindings, quotes = _ready()
    before = bridge.publish(now=NOW)
    invalid = replace(
        quotes[0],
        observed_at=float("nan"),
        response_hash="invalid",
        cursor=replace(quotes[0].cursor, offset=1),
    )
    with pytest.raises(ValueError):
        bridge.ingest(bindings[0].binding_id, invalid)
    assert bridge.publish(now=NOW) == before
