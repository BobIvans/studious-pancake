# Bounded shadow circular graph

Design input: [Universal Arbitrage Graph + nonlinear profit solver + event-driven local market-state engine](https://docs.google.com/document/d/1f-asFbZuFDnlWfi0aGKWV8Zjkj739hsPN2t220uUD7k/edit).

Before implementation, `main` was fetched and inspected at
`6499e0f2d936a072897970d3af3202ef6d7ea349` (2026-10-02). Compared with the
reported `b31fa445218900702c0d0c4202481488a259c6f8` baseline, the relevant gaps
remain: `CircularArbitrageDetector` handles configured two-leg pairs;
`OrderbookAmmStrategy` is disabled awaiting verified subscriptions; no universal
graph or multi-path solver was found. The design document's broader activation,
execution, lender and live-profit proposals are outside this PR.

## Existing authorities reused

- `src.market.observations` via `src.market.snapshots`: immutable V2 observations,
  batch completeness, active corrections, generation/watermark provenance,
  freshness and `exact_output_for`. Amounts remain integer base units of each mint.
- `src/economics/non_monotonic_sizing.py`: PR118 owns integer amount grids,
  `evaluate_pr118_non_monotonic_sizing`, exact evidence and the typed cost ledger.
  The detector calls `build_pr118_amount_grid`; a rejected size does not prune
  larger points. Historical `*_lamports` grid parameter names do not convert
  assets. No duplicate size optimizer, legacy float CPMM sizing or best-size
  economic selection is introduced. PR118's capital evaluator remains separate;
  its native settlement boundary must not be used for arbitrary token amounts.

## API and invariants

`src.strategy.arbitrage_graph` provides typed `AssetNode`, `VenueIdentity`,
`DirectedQuoteEdge`, `UniversalArbitrageGraph`, `CircularShadowRoute`, policy,
detector and an immutable result with stop reason and rejection counts.

Build a graph from an existing `ObservationBatch` plus explicit edge bindings.
Each binding must use an active observation from that batch. Bind the actual
underlying program and market/pool address, consistently across providers and
directions. Never infer a market from a provider name or treat an opaque aggregate
route as a single verified pool. The bindings are caller-supplied shadow data;
this PR does not establish verified subscriptions or venue execution capability.

```python
graph = UniversalArbitrageGraph(batch, (
    DirectedQuoteEdge(VenueIdentity(program_id, pool_address), exact_observation),
    # Other exact observed conversions, including parallel pools.
))
policy = CircularGraphPolicy(
    base_mint=settlement_mint,
    lower_amount_base_units=10,
    upper_amount_base_units=30,
    max_amount_points=3,
)
result = CircularGraphCandidateDetector(policy).detect(graph, now=replay_time)
```

This is bounded DFS over observed edges, limited to 3/4-hop asset-simple circular
routes and a selected base mint. Every hop's request amount must exactly equal
the previous hop's **guaranteed** output. Expected output is retained as evidence
but never substituted into coupling. No interpolation, marginal-rate inference,
quote fetch or venue math approximation occurs. Missing amount-coupled snapshots
produce no route. Gross profit is final guaranteed amount minus initial amount;
it excludes flash fees and other costs and is not an economic approval.

The entire route's maximum slot minus minimum slot must fit policy. All route
observations must share a generation. Incomplete batches, stale/expired/future
evidence, repeated intermediate assets and repeated underlying markets are
rejected. Different markets under one program are allowed. Corrections supersede
old observations before graph binding; retractions cannot become edges.

Identity hashes bind ordered edge evidence, underlying market, exact amounts,
expected/guaranteed outputs, quote/request/response provenance, timing, cursor,
generation and batch/watermark. They are replay-evidence identities, not stable
economic path IDs across changed snapshots. Edge input order cannot change the
search or output for an identical explicit canonical batch/watermark.

Hard limits: 512 graph edges, 8 amount points, 100,000 expansions and 1,000
candidates. Defaults are 512 / 8 / 4,096 / 100. Each examined edge consumes an
expansion, including rejected branches. Budget stops are explicit; a truncated
result is not a complete universe search. Candidate cap reports truncation
conservatively even if the last candidate happened to exhaust the universe.
Candidates are sorted by evidence identity, not economic value.

## Shadow boundary

The result contains `CircularShadowRoute`, not runtime `Opportunity`. There is
no registry/config activation, automatic planner adapter, sender, signer,
transaction construction/submission, live authorization, new market subscription
or orderbook activation. Existing two-leg runtime behavior is unchanged. This
module is callable by an offline/shadow harness; connecting it to a verified
runtime observation producer is a separate change.

## Verification

```bash
python -m pytest tests/test_shadow_arbitrage_graph.py tests/test_pr113_amount_coupled_discovery.py tests/test_pr118_non_monotonic_sizing.py -q --disable-socket --allow-unix-socket
python -m black --check src/strategy/arbitrage_graph.py tests/test_shadow_arbitrage_graph.py
```

Tests cover exact 3/4-hop coupling, optimistic/mismatched inputs, timestamp/expiry
and whole-route slot rejection, repeat-market/provider constraints, parallel
markets, generation/completeness/corrections, evidence identity and insertion
order, non-monotonic amount points, bounded truncation and disabled orderbooks.
