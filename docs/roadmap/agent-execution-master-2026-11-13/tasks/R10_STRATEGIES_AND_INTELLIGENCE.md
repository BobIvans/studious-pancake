# Assignment — R-10 strategy universe, correlation ledger and learning experiments

Copy-ready trigger: Audit all existing strategy/relationship owners and tests before proposing new strategies. Preserve the maximum research universe and implement candidate generation only through canonical asset identities and exact market evidence. This task is about research, strategy coverage, explainability and replay; it does not authorize execution.

## Inventory existing owners
Inspect strategy registry and supported capability manifest, src/strategy/strategies.py, relation_generators, arbitrage_graph, multihop_solver, Dynamic Universe, ResearchEconomicGraph, CorrelationLedger, economic sizing and paper outcomes.

## Strategy families to inventory/qualify
1. Direct two-leg market arbitrage.
2. Venue fragmentation and route overlap.
3. Direct vs synthetic/wrapped representation paths.
4. Bounded circular cycles (2–5 hops) with exact re-quote at every amount.
5. Stablecoin triangles, peg deviation and cross-venue dislocations.
6. LST/staking derivatives: mint/redeem/unstake paths, exchange-rate and NAV residuals.
7. BTC wrapper/bridged representation basis.
8. Liquidation and health-factor opportunities only with protocol risk-state proof.
9. Funding/carry/basis and event-driven dislocations.
10. CEX lead/lag, orderbook imbalance and oracle/reference divergence as signal features.
11. Memecoin/event token migration/liquidity events as discovery-only candidates until token, program and pool are exact verified.
12. Cross-chain/bridge-basis and asynchronous settlement signals; never mislabel as local atomic flashloan route.
13. RWA/xStocks/gold-like representation research as a separate legal/access/economic evidence class.

Keep the four core relation generator owners when applicable: DIRECT_MARKET, VENUE_FRAGMENTATION, DIRECT_VS_SYNTHETIC and BOUNDED_CYCLE. Other generators may be research-only additions with separate evidence classes.

## Intelligence/ML experiments
- Build replayable event/route episodes from immutable evidence, not copied live state without provenance.
- Use time-aware train/validation/test splits, no look-ahead leakage, no same-pool/provider alias leakage and no cross-source contamination.
- Compare to deterministic baselines; report sample size, confidence, latency, stability, false positives and costs.
- Feature families may include spread/residual, volatility/regime, depth/imbalance, slot/checkpoint age, source independence, quote divergence, fees, compute/gas costs, LST exchange rates and event features.
- Model scores remain advisory. No learned output can skip identity, quote, capacity, exact simulation or paper gates.

## Acceptance
Machine-readable strategy inventory with implemented/unqualified/blocked/retired states, owner paths/tests, evidence requirements and data classes. Deterministic replay dataset or report for each selected experiment. No shadow-ready/live promotion by merely adding a strategy class.
