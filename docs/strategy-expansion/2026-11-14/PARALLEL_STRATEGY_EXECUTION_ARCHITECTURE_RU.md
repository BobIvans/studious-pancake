# Parallel strategy execution architecture — design contract

## 1. Objective

Run many strategy detectors, exact evaluators and replay experiments concurrently while preserving one coherent market state and preventing the same pool, collateral, lender capacity, account lock, inventory, orderbook depth, quota or compute budget from being spent twice.

Parallel means concurrent research/evaluation, not unconstrained simultaneous execution. The current product boundary remains sender-free paper/shadow.

## 2. Shared pipeline (reuse existing owners)

```text
Source receipts / subscriptions
  → canonical identity + revision-bound state
  → typed market edges + conditional hyperedges
  → relation discovery / candidate generation
  → strategy-specific exact evaluator
  → PR118 amount grid + capacity curve
  → full economics + funding feasibility
  → conflict/resource scheduler
  → build/simulation/paper gates (only when supplied and qualified)
  → immutable outcome + replay + portfolio analytics
```

Canonical owners to reuse:
- Asset and representation identity: existing AssetResolver / research-economic graph registry.
- Market state and source lineage: existing streams, durable journal, MarketObservation and provider governance.
- Relations/residuals: `src/strategy/relation_generators/` and `src/research/correlation_ledger/`.
- Graph/shortlist: `src/strategy/arbitrage_graph.py`, `multihop_solver.py`.
- Sizing: `src/economics/non_monotonic_sizing.py` (PR118).
- Split-flow: existing `src/economics/split_flow.py` and shared-state replay owners.
- Capital: `src/economics/flash_capital_graph/`.
- Conflict scheduling: `src/strategy/conflict_scheduler.py`.
- Admission/queue/tracking: existing strategy admission, queue, tracker.
- Analytics/retention: existing DurableRawJournal, MarketObservationV2, MarketEpisode, Parquet/DuckDB and decision dataset owners.
- Paper vertical: existing sender-free paper/shadow composition root and exact simulation/reconciliation stages.

Do not create a competing global market DB, event journal, asset registry, graph, solver, quote provider catalog, capital graph, correlation ledger, scheduler or release authority.

## 3. Resource reservation contract

Every candidate must expose a deterministic read/write resource manifest:
- read resources: pool state generation, tick/bin arrays, book sequence, oracle round, lender reserve, collateral account, issuer buffer, intent auction and source receipt;
- consumed resources: per-pool input liquidity, per-bin/tick capacity, orderbook levels/quantity, collateral/debt, lender principal, inventory, account locks, blockspace and provider quota;
- exclusive resources: nonce/account locks, mutable state accounts, callback/receipt objects, auction/order IDs;
- shared costs: fixed transaction cost, rent, route overhead, source/compute costs.

Resource identity is not a ticker or aggregator label. Two quotes that resolve to the same underlying pool/orderbook/market state are correlated and must not be counted as independent liquidity.

A scheduler reservation is bound to:
`(strategy_id, candidate_id, state_generation, resource_manifest_hash, amount_vector, expiry, reservation_id)`.

Reservations must be idempotent, expire deterministically, support rollback, and never mutate the underlying market snapshot. For shadow, reservations are simulated ledger entries only.

## 4. Parallelism model

- **Stage A — fan-out read-only discovery:** many providers and strategy families may read independent sources concurrently within per-source budgets.
- **Stage B — fan-out candidate generation:** each strategy consumes the same immutable snapshot generation; candidates carry exact source lineage.
- **Stage C — parallel exact evaluation:** evaluate candidates with disjoint immutable resource manifests. Candidates sharing a resource may be evaluated in parallel as counterfactuals, but cannot be jointly allocated without a shared-state joint replay.
- **Stage D — conflict resolution:** one canonical scheduler computes feasible sets / reservations. Use bounded deterministic search; no greedy order-dependent hidden behavior.
- **Stage E — joint allocation:** portfolio optimizer compares single candidate, split flow, netting, batch clearing and independent execution baselines on one shared state.
- **Stage F — paper/shadow:** only individually qualified candidates enter the existing paper gate. A research family cannot borrow the capability of another.
- **Stage G — post-trade/replay:** immutable outcomes record accepted, rejected, stale, partial, reverted, not-filled and no-trade results with reason.

## 5. Portfolio selection objective

Optimize expected conservative net value under explicit constraints, not raw gross spread:
- maximize risk-adjusted net outcome across selected candidates;
- constraints: shared resource capacities, flash principal and repayment, collateral/borrow caps, inventory, exposure, concentration, chain/settlement class, time horizon, account locks, request/compute budget and per-strategy risk limits;
- compare with independent execution baseline and single-best strategy;
- include probability of fill/inclusion only when calibrated from real observations; unknown probability blocks expected-value claims;
- do not multiply snapshot liquidity by worker count or strategy count;
- do not count the same pool or lender capacity in several simultaneous strategies.

A route portfolio is not a proof of global optimality. Record finite search bounds, explored nodes, budget exhaustion and best-found-not-proven-optimal status.

## 6. Scheduling and learning

Use existing AGG-05 conflict scheduler and candidate queue. Add strategy-level scheduling only through their canonical extension points. Prioritize by evidence readiness, expected marginal verification value, freshness decay, source cost and diversity; queue scores are scheduling units, not PnL.

ML/context-bandit may choose which source/strategy to verify next. It may not:
- invent a price, identity, capacity, quote or causal relation;
- suppress hard rejections;
- change execution class or evidence state;
- bypass exact quote, funding, build, simulation or paper gates.

## 7. Parallel acceptance tests

- 1/2/4/8 worker deterministic replay produces identical canonical outputs for identical input/seed/budgets.
- Reordering worker completion cannot alter selected feasible set.
- Shared pool, book level, tick/bin, collateral, lender capacity, nonce/account lock and provider quota cannot be consumed twice.
- Same aggregator route mapped to same physical pool is one resource.
- Stale state, reorg, sequence gap, duplicate receipt, missing quote or budget exhaustion fails closed with typed reason.
- Joint split/clearing result conserves every asset and obligation and beats independent baseline after all costs; otherwise no promotion.
- Cancellation, worker crash and replay restart leave reservations recoverable and no phantom capacity.
- No worker imports sender/signer/live submission modules.

## 8. Operational metrics

Track per strategy and aggregate: candidate count, exact-evaluation count, rejection reasons, state age, quote coverage, capacity, tested size points, conservative net, resource conflicts, source/API/compute cost, replay determinism, false positive rate, no-trade rate, paper qualification and unresolved blockers. Include unknown denominator and budget-exhausted count.
