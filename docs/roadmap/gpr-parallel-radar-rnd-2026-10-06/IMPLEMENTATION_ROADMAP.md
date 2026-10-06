# IMPLEMENTATION ROADMAP — GPR V2

## GPR-00 — Stack reconciliation / evidence hardening

Before new implementation, inspect the actual #571 base and the former #569/#570 review findings. Fix only findings that still exist.

Required boundary:
- physical reads cannot lose evidence;
- credentials cannot escape through derived context;
- replay fails closed on missing evidence;
- readiness cannot PASS on unusable schemas;
- current branch identity is reproducible.

This gate is not permission to do broad cleanup.

## GPR-01 — Asset/Representation Registry + Research Economic Graph + Verification Queue

**NEXT CODE PR. Stop after this PR.**

Implement:

### A. Asset Registry V2
- typed loader for `ASSET_REGISTRY_V2.json`;
- EconomicAsset vs Representation separation;
- chain + canonical-id uniqueness;
- status gating;
- generation/digest identity;
- no ticker-only lookup for exact work.

### B. ResearchEconomicGraph
- chain-neutral representation nodes;
- QPR-03 Solana adapter;
- deterministic relation identity/dedup;
- structural-anchor relations;
- relation provenance and negative evidence;
- interchain relation loading as research-only.

### C. CandidateScore
- decomposed scheduling score;
- representation/correlation/staleness penalties;
- no profitability claim.

### D. VerificationQueue
- bounded deterministic top-K;
- full representation identity;
- evidence refs;
- request/amount budgets;
- chain-specific exact-verification target.

Acceptance:
- registry loads deterministically;
- all 88 rows default runtime-disabled;
- same ticker across chains never aliases;
- bridge representations never alias native representations;
- `REVALIDATE_*` and `UNRESOLVED` fail closed for exact promotion;
- Token-2022 semantic gate remains explicit;
- cross-chain edges cannot enter UniversalArbitrageGraph;
- QPR-03 indexed candidates can rank verification work;
- replay reproduces graph identities/scores.

## GPR-02 — Solana Parallel Radar + Dual Quote Preview

May start in parallel with GPR-03 **only after GPR-01 contracts are stable**.

Integrate/adapt in evidence-driven order:

1. Meteora DLMM high-throughput radar.
2. 0x Solana quote preview.
3. Jupiter quote preview.
4. Sanctum LST quote/instant-exit structural path.
5. optional OpenOcean comparator with underlying-router correlation.
6. optional Vybe/reference sources.

Funnel:

```text
DEX Screener + Meteora + Raydium + Gecko
 -> ResearchEconomicGraph
 -> heat/anomaly trigger
 -> 0x
 -> Jupiter
 -> Sanctum if LST/LRT
 -> selected comparators
 -> QPR-02 independent RPC/direct state
 -> MarketObservationV2
 -> existing exact graph
```

Initial high-value clusters:
- SOL + JitoSOL/JupSOL/mSOL/bSOL/INF;
- hSOL/dSOL/BNSOL/bbSOL/bpSOL/laineSOL/dfdvSOL;
- sSOL/fragSOL restaking basis;
- USDC/USDT/PYUSD/USDS/JupUSD/USDe/USDG/FDUSD;
- cbBTC/WBTC_WORMHOLE/tBTC;
- JLP market-vs-NAV;
- EURC vs EUR/USD reference.

No live executor.

## GPR-03 — Sui Parallel Shadow Research / Exact-State Qualification

Parallel branch after GPR-01.

Implement:
- Aftermath router radar;
- Cetus/DeepBook direct references;
- Sui gRPC/GraphQL state transport;
- checkpoint/object-version provenance;
- representation-aware stable/BTC/LST graph;
- adapter to existing `src/multichain/sui.py` domain types.

Priority clusters:
- SUI/USDC;
- native/bridge USDT and Wormhole USDT;
- native USDC and Wormhole USDC;
- USDsui/suiUSDe/FDUSD/USDY/BUCK/mUSD;
- DEEP/WAL;
- XBTC/Wormhole-WBTC/Sui-Bridge-WBTC/zwBTC;
- afSUI/haSUI/vSUI/scaSUI;
- Wormhole SOL on Sui.

No new JSON-RPC dependency.
No live PTB signer/executor.

## GPR-04 — Dynamic Watch Universe + Heat Scheduler

Operate over evidence, not one polling loop per pair.

Tiers:
- HOT
- WARM
- COLD
- EVENT

Inputs:
- volume/liquidity changes;
- structural-anchor deviation;
- route topology changes;
- representation basis;
- provider disagreement;
- historical recurrence;
- cost/capacity regimes.

## GPR-05 — Structural Transformation Graph

Deepen state transformations:

### Solana
- LST/LRT exchange and instant exit;
- JLP NAV;
- stable/yield anchors;
- BTC wrapper parity;
- flash-capacity / borrow-cost / Jito tip / priority fee.

### Sui
- staking and instant exit;
- lending/flash capacity;
- AMM <-> DeepBook;
- native-vs-bridged stables;
- BTC representation basis.

The solver should increasingly search transformations, not just ticker pairs.

## GPR-06 — Solana <-> Sui Cross-Chain Economic Graph

Load `INTERCHAIN_RELATIONS_V2.json`.

Research:
- USDC native basis / CCTP rebalance relation;
- SOL vs Wormhole-SOL basis;
- FDUSD same-issuer basis;
- USDY yield-basis divergence;
- BTC representation basis;
- LST premium regimes;
- funding/capital-cost divergence;
- liquidity migration / which chain leads price discovery.

Bridges are not atomic swap edges.

## GPR-07 — Prefunded Cross-Chain Arbitrage Simulator

Only after GPR-06 evidence.

Model:

```text
prefunded inventory on Solana
+
prefunded inventory on Sui
 -> simultaneous chain-local execution
 -> hedge/inventory accounting
 -> later CCTP/Wormhole/other rebalance
```

Include:
- local execution costs;
- hedge cost;
- inventory opportunity cost;
- expected rebalance/bridge cost;
- latency risk;
- capital fragmentation.

No live cross-chain executor in this PR.

## GPR-08 — TON High-Throughput Research Laboratory

Use STON.fi research APIs with self-imposed caps. Keep TON as research-only until a separately justified execution architecture exists.

## Production boundary

Live signer/sender/submission/promotion remains outside this roadmap until explicitly authorized after qualification evidence.
