# Bounded shadow market-data aggregation

Design input: [Universal Arbitrage Graph + nonlinear profit solver + event-driven local market-state engine](https://docs.google.com/document/d/1f-asFbZuFDnlWfi0aGKWV8Zjkj739hsPN2t220uUD7k/edit).

Base inspected on 2026-10-02: `main` initially at `91907282eaee685af1a3163acebf6aa0d9f954d5` (graph PR #559 merged), then updated and rebased to `4087d58104bc9cbb2cda56b7c951b35cc76235ab` (OCC/FAST-Q PR #558 merged). Canonical graph, snapshot, sizing, transport and orderbook owners are unchanged by that upstream update. This change adds a source inventory, bounded read-only discovery, and a canonical observation-to-graph bridge. It does not duplicate the merged graph implementation or sizing authority.

## Existing owners retained

| Concern | Existing owner | This change |
| --- | --- | --- |
| Integer amount grids / non-monotonic economic sizing | `src/economics/non_monotonic_sizing.py`, PR118 | Graph detector still uses the PR118 grid. No new optimizer. |
| Exact input, expected vs guaranteed output, freshness, generations | `src/market/observations.py` | Accepts `MarketObservationV2`; never scales a price or TVL into output. |
| Durable cursors, backfill, reconnect epochs, completeness | `src/market/streams.py` | Reuses `WatermarkedObservationBuffer`, `FanoutMatrix`, `DurableCursorStore`. |
| HTTP/TLS/URL/body limits and physical-attempt hooks | `src/routing/transport.py` | Caller supplies its existing governed `Transport`; no new HTTP stack. |
| Admission, deadline and provider spend | `src/provider_governance/` | No new provider profile, scheduler or automatic activation. |
| Typed multigraph, exact 3/4-hop shadow candidates | `src/strategy/arbitrage_graph.py`, PR559 | Produces this graph from explicitly bound canonical evidence. |
| Orderbook decoder / subscription promotion | `src/providers/orderbook/`, fixture-only quarantine | No import or activation of these adapters. All orderbook catalog sources are rejected by the bridge. |

## Implemented data paths

`src/resources/market_source_catalog.json` contains 43 source/tool/candidate records, checked against primary documentation where accessible. Access classes distinguish public rate-limited reads, keyed free tiers, open-source tools that require RPC/hosting, and unverified candidates. A catalog entry is neither an active connector nor proof of a free production service. Primary URLs and limitations are included per record; [the Russian inventory](shadow_market_sources_ru.md) renders the same catalog for review.

`PublicMarketDiscovery` implements four one-shot GET parsers: DEX Screener token pairs for an explicit Solana mint, GeckoTerminal Solana pools, Raydium v3 pool lists, and Meteora DLMM pool lists. Request paths/hosts are fixed. Pagination is explicit, not an unbounded crawler. Records contain mint addresses, pool addresses, domain, source, and request/response receipt references. Market identifiers never use ticker symbols. Repeated descriptions retain source receipts while physical pool coverage counts addresses once.

Hard bounds: 8 explicit requests, pages 1..8, 1,000 rows per response, and 512 retained discovery records. Transport body/depth/time limits remain owned by `HttpxJsonTransport`. HTTP failures and transport errors stop further requests; there is no collector retry loop. Schema drift and invalid rows are explicit rejection counters. No exceptions, response bodies or credentials are copied into error receipts. Cancellation propagates.

Discovery responses may be indexed, stale, sampled or incomplete. Empty successful pages do not establish market completeness. Four parser schemas are fixture-tested. A read-only smoke attempt in the implementation environment returned transport errors for all four hosts; live endpoint availability and current payload compatibility are **not verified**. These failures do not become successful empty coverage.

`ShadowMarketGraphIngest` takes a frozen, explicit set of up to 512 Solana AMM market bindings. Each binds source ID, stream source/partition, underlying program/pool, two mint addresses, and a decoder revision annotation. Only canonical exact observations can enter. Provider/cursor/mints/genesis must match the binding; request and response provenance is required. Corrections cannot supersede another binding. Discovery, oracle prices, opaque router routes, CEX orderbooks, EVM venues, and quarantined Solana orderbooks cannot enter this bridge.

The caller's decoder annotation is provenance, not certification. Canonical producers must verify account owner, decoder revision, account completeness, token semantics and actual amount-specific guarantees themselves. They must bind decision-affecting revisions to canonical observation generations/provenance. This PR adds no live normalizer or verification shortcut.

Publication reuses canonical completeness, additionally blocks missing configured markets, and emits graph edges plus source traces. Observation/cursor ordering is normalized for deterministic serialization; edge and route identities remain owned by PR559. Completeness refers to the configured fanout/market set, never all markets. Discovery errors are reported separately and cannot authorize graph use. Fresh market counts are separate from total exact-quoted counts; the existing detector enforces actual age/expiry/slot checks before producing candidates.

The staging window accepts at most 512 new events per reconnect epoch, including corrections/retractions. At the cap it fails before mutation. The caller publishes/checkpoints, opens a new reconnect epoch, and performs backfill. This is a bounded shadow window, not an unlimited market-state daemon. Persisted cursors alone never restore quote coverage.

## Offline demonstration and use

```bash
python -m scripts.shadow_market_graph_demo
python -m pytest tests/test_shadow_market_data_aggregation.py tests/test_shadow_arbitrage_graph.py
```

The demo emits synthetic graph nodes/edges, trace records, coverage and one exact coupled 3-hop candidate. Synthetic addresses/amounts are labelled; gross profit is before financing, fees, gas and all other costs. It makes no network calls.

For discovery, supply an already admitted, bounded read-only transport:

```python
collector = PublicMarketDiscovery(governed_transport, load_market_source_catalog())
discovery = await collector.collect(
    (DiscoveryRequest("raydium", page=1), DiscoveryRequest("meteora-dlmm", page=1)),
    observed_at=recorded_receive_time,
)
# Manually validated bindings + canonical exact observations are a separate path.
snapshot = ingest.publish(now=decision_time, discovery=discovery)
result = CircularGraphCandidateDetector(policy).detect(snapshot.graph, now=decision_time)
```

The production provider allowlist currently does not register these new discovery hosts. Extend the existing governance owner with validated profiles/budgets before runtime wiring. This module does not bypass that boundary or attach a collector to any active strategy.

To grow coverage, first discover addresses, then qualify a pinned venue-specific read-only normalizer/subscription, obtain exact observations at coupled integer inputs, and publish coherent bounded batches. API prices and depth tools alone do not supply those proofs. Split-flow, multi-path sizing, universal financial-product hyperedges, cross-domain settlement and continuous whole-market ingestion remain separate changes.

`OrderbookAmmStrategy` stays disabled. No sender, signer, transaction builder/submission, strategy startup change, wallet requirement or live authorization is added.
