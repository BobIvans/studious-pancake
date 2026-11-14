# Strategy gap analysis — current coverage vs unexplored / under-specified mechanisms

Дата среза: 2026-11-14. Это аудит документации и owner maps, а не утверждение о live readiness.

## 1. Что уже покрыто — не создавать заново

| Existing coverage | Canonical source / owner | Truthful status |
|---|---|---|
| Direct two-leg, venue fragmentation, direct-vs-synthetic, bounded cycles 2–5 hops | `src/strategy/relation_generators/`, `arbitrage_graph.py`, `multihop_solver.py` | Topology/research/shadow owners exist; exact per-amount proof and route economics incomplete outside qualified CPMM |
| Non-monotonic sizing, finite amount grids, exact route cost ledger | `src/economics/non_monotonic_sizing.py` (PR118), existing economics owners | Reuse; never introduce alternate sizing solver |
| Split-flow/shared pool replay | `src/economics/split_flow.py`, `src/strategy/cpmm_split_replay.py` and shared execution state | Partial/offline; multi-venue state closure and full search remain |
| Stablecoin residuals, LST/NAV, wrappers, oracle and VWAP residuals | `src/research/correlation_ledger/`, `src/strategy/relation_generators/` (#614) | Research signal only; 7 residual families, 12 features; not execution evidence |
| PSM/mint/redeem, LST/LRT, BTC wrappers, vault shares, Pendle PT/YT, conditional claims | `src/strategy_evolution/`, economic graph, rights lifecycle | Research/partial owners; caller rights, exact state, maturity and atomicity missing |
| Liquidation/health factor | `src/liquidation/`, `src/lending_indexer/` | Fixture/shadow planner only; reserve, oracle, borrow/repay and collateral-unwind evidence missing |
| CLOB/AMM, Phoenix/OpenBook/DeepBook | `src/providers/orderbook/`, `market_graph_ingest.py`, strategy shells | Fixture-gated; live subscriptions/depth/fill/sequence proof missing |
| CLMM/DLMM and dynamic fees | `src/direct_venue/`, native Raydium CLMM/Meteora decoders | Math/decoder work exists; graph exact-evaluator binding and rooted current state remain |
| Intent/RFQ, CEX/DEX lead-lag, cross-chain, governance/events, blockspace | Existing residual, event, intent, TON radar and strategy-evolution owners | Advisory/research/disabled; no permission to route or execute |
| 28 opportunity classes and WG-01…WG-28 | `25_OPPORTUNITY_ATLAS_RU.md`, `data/tasks.json` | Broad research plan, not 28 working strategies |
| R10-A…I | `R10_STRATEGIES_AND_INTELLIGENCE.md` | Already assigned as parallel strategy research lanes; do not duplicate |

## 2. Material gaps not yet represented as complete, independently testable strategy packs

These are the main additive gaps or under-specified families. Some are named in the R10 assignment, but do not yet have a complete canonical strategy contract, measurable acceptance matrix and portfolio/resource integration.

### G01 — Flash-mint / protocol-native temporary issuance
A distinct funding/conversion mechanism, not the same as lender flash-loan. Model mint eligibility, callback/receiver restrictions, fee, caps, asset liabilities, same-transaction burn/repay and exact postconditions. Compare with lender funding as a financing option; never assume free capital.

### G02 — Curve LLAMMA / banded collateral liquidation and soft-liquidation arbitrage
Model active bands, collateral/borrowed asset conversion, oracle bands, liquidation/health transitions, band inventory, fees and unwind. Keep separate from generic lending liquidation; do not approximate LLAMMA as constant-product pool. Research/shadow until protocol-specific account state and official math vectors are pinned.

### G03 — Oracle extractable value (OEV), oracle update auctions and keeper competition
Model update timing, auction rights, stale/updated price windows, keeper eligibility, bid/payment, liquidation/settlement consequences and value attribution. Oracle price itself is not a quote. Treat as event/auction research until permissions and atomic route are proven.

### G04 — Legitimate JIT liquidity and just-in-time LP placement
Model transaction/batch visibility permissions, pool state at inclusion, range selection, fee share, gas/compute, adverse selection, inventory delta and withdrawal rights. This is not passive LP and not permission to front-run users. No sandwich, victim targeting or unauthorized private-flow use.

### G05 — LVR / toxic-flow-aware liquidity provision
Measure loss-versus-rebalancing, adverse selection, markout horizons, volatility-conditioned fee income, inventory drift and hedging costs. Distinct from static CLMM market making; requires event-level fill and subsequent price path. Resting LP capital is not financed by a standard flashloan.

### G06 — Rebate-, maker/taker- and queue-aware market making
Separate passive CLOB, RFQ market making, concentrated liquidity and private firm quotes. Model queue position only when exchange semantics prove it; partial fills, cancel latency, maker rebates, toxic flow, inventory and capital utilization. A quote is not a fill.

### G07 — Prediction-market complete sets and conditional-outcome arbitrage
Model outcome vector, mutually exclusive/exhaustive condition, split/merge/settlement rights, oracle resolution, fees, collateral and redemption timing. Complete-set conservation is a vector/hyperedge, not independent token pair swaps. Add one market protocol only after official settlement semantics are pinned.

### G08 — Cross-rollup / shared-sequencer / synchronous interoperability hypotheses
Research only. Separate domains by chain ID, rollup, sequencer, finality and proof/settlement. A shared sequencer or fast message does not imply atomicity. Only a demonstrated single-transaction settlement domain may be considered local atomic; otherwise model prefunded inventory and failure/timeout risk.

### G09 — Lending-rate / utilization / collateral-efficiency and refinance strategies
Beyond liquidations: variable borrow/supply rate spreads, collateral migration, debt refinance, eMode/health-factor constraints, utilization cliffs, caps, oracle risk and unwind. Separate instant atomic refinance from multi-period carry. Flashloan can bridge an intra-transaction refinance, not finance a long holding period.

### G10 — LP position lifecycle and fee/inventory harvesting
Mint/burn/collect/compound/shift range, impermanent loss, fee claims, token balances, NFT/position rights, gas and rebalance costs. Distinct from swap arbitrage and from passive market-making strategy; must include persistent inventory/capital lock.

### G11 — Transaction-ordering / permitted backrun / auction-aware execution
Only public or explicitly authorized order-flow and permitted backrun mechanisms. Model transaction dependency, state-before/state-after, inclusion probability, competing bids, priority fee/tip, revert cost and realized settlement. No sandwich, frontrun, user-targeting or claims that Jito access is implemented.

### G12 — Cross-protocol collateral / shared-liquidity portfolio optimizer
Not an alpha signal. Optimize scarce borrow capacity, collateral reuse, borrow caps, protocol concentration, liquidation correlation, lender fees and strategy opportunity cost across concurrent strategies. Never count one collateral unit, pool reserve or flash capacity twice.

### G13 — Strategy portfolio / capital allocator
Choose among simultaneously valid opportunities using marginal net value, capacity curves, shared resources, execution probability, risk budget, concentration, correlation, compute/request budget and opportunity cost. Must compare against independent-strategy baseline; no leverage multiplier assumptions.

### G14 — Data and compute procurement / verifiable quote service
A research/product strategy rather than a trading strategy: compare independent source/operator accuracy, latency, cost, rights and reproducibility for exact decode/quote/replay tasks. Extend existing INST-01 procurement owners; do not create a second marketplace, provider registry or payment system.

### G15 — Mechanism-design / auction-rule experimentation
Offline lab for auctions, fee schedules, allocation, batch clearing, solver competition, rebates and incentives. Compare rule changes on fixed workloads and report welfare/surplus ownership, manipulation resistance, latency and costs. No deployment or real market operation in this pack.

### G16 — Multi-objective strategy discovery and causal validation
Extend deterministic anomaly baselines, context-bandit scheduling and ML challenger evaluation with time-aware labels, purged holdouts, source/pool leakage controls, multiple-testing correction, null hypotheses and negative examples. Models prioritize verification only; they cannot create identity, exact quotes, capacity or execution permissions.

## 3. Under-specified rather than wholly missing

- Flash-loan provider selection: fee/capacity/freshness/reliability/atomicity/repayment and route compatibility should be a comparable capital graph decision, not a hardcoded lender choice.
- Route composition across swaps + transformations + collateral + claims: typed hyperedges with vector conservation, rights, callback/hot-potato semantics and state postconditions.
- Multiple strategies competing for the same pool, account lock, collateral, lender capacity, compute budget or provider quota: common reservation model must be the single source of truth.
- Portfolio-level PnL: distinguish gross spread, embedded swap fees, flash fee, priority fee/tip, compute, rent, provider cost, hedge/funding, residual assets, failed/reverted costs and inventory markout.
- Strategy-specific no-trade outcomes and counterfactual baselines: every family needs bounded negative examples, not only positive synthetic demos.

## 4. Explicitly excluded or non-atomic

- Robinhood Stock Tokens and tokenized equities: excluded by user policy.
- Cross-chain bridge, CEX withdrawal/deposit, TON async multi-contract, delayed unstake/redemption, PT/YT maturity and perpetual/funding carry: not a standard same-transaction flashloan leg. They may be separate inventory, signal or rebalance strategies.
- Oracle/reference, CEX lead/lag, TVL and aggregator route discovery: signals/inputs only, never executable quote/capacity.
- Sandwich/frontrun, user-targeted MEV, unauthorized private-flow exploitation: excluded.

## 5. Strategy-pack completion definition

A family is not “covered” just because a heading exists. It is covered at a declared tier only when it has: canonical ID; falsifiable hypothesis/null; typed economic relation; chain/settlement class; asset/right identity; primary-source dossier; current state/depth/quote requirements; exact size/capacity/economics model; shared-resource conflicts; risk/failure taxonomy; deterministic offline tests; replay corpus and time holdout; status and next promotion gate; named canonical code owner. If any item is unknown, preserve UNKNOWN/BLOCKED, never fill with zero or a synthetic success.
