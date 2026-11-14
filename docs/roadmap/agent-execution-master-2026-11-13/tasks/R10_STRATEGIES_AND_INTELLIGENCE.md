# Assignment — R-10 broad strategy universe, relation crosswalk and falsifiable learning

**Purpose:** preserve every explored strategy concept and connect it to current canonical owners, while separating local atomic market opportunities from conditional rights, hedged strategies and signals. This assignment does not grant execution authority.

## Read these current sources first
- `PARALLEL_EXECUTION_STATUS.json` (refresh against current main; stored snapshot may be one commit behind).
- master strategy overlay `STRATEGY_CROSSWALK.json`, `STRATEGY_UNIVERSE_ATLAS.md`, `ARCHIVE_RESEARCH_CROSSWALK.md`, `MASTER_STRATEGY_EXECUTION_ASSIGNMENTS_V2.md`.
- current code: `src/strategy/strategies.py`, registry, arbitrage graph, multihop solver, relation_generators, `src/research/correlation_ledger/`, strategy_evolution packages, stable_peg, liquidation, non_monotonic_sizing, exact_simulation, paper owners.
- PR #614: seven provenance-gated residual families and timestamp-aligned lead/lag are already in main. Reuse the existing owner; no new correlation ledger.

## Strategy families to cover
A. Local atomic market: direct two-leg, venue fragmentation/resource dedup, bounded 2–5 hop, multi-path split-flow with joint constraints, direct-vs-synthetic, stablecoin triangles, CLOB/AMM VWAP and CLMM/DLMM/hooks/bin state.
B. Conditional rights: issuer PSM/redemption, flash-mint, mint/burn, LST/LRT/NAV, instant exit vs queue/epoch/unstake, BTC wrapper basis, ERC-4626/7540/7575 vault rights, Pendle PT/YT/SY/maturity, Curve LLAMMA bands, liquidation/solvency.
C. Market making/flow: legitimate JIT liquidity (never sandwich/frontrun/user-target), LVR/toxic-flow risk, rebate-aware routing, blockspace/account-lock auction costs, OEV/oracle auctions, intent/RFQ/Coincidence-of-Wants, permitted MEV-Share backruns only.
D. Non-atomic/signal: spot-perp/funding, options/futures parity, prediction-market complete sets, CEX/DEX lead-lag, cross-chain bridge flow/finality/inventory, cross-rollup/shared-sequencer atomic hypotheses, FX/gold/session references, governance/incentive/event/migration.
E. Learning/research: anomaly and context-bandit ranking; advisory only.

## Existing owner map
- DIRECT_MARKET, VENUE_FRAGMENTATION, DIRECT_VS_SYNTHETIC, BOUNDED_CYCLE in `src/strategy/relation_generators/`.
- #614 residual families: stable/redemption; LST premium vs exchange/instant exit; BTC wrapper; JLP/NAV; AMM-vs-CLOB exact-size VWAP; direct-vs-synthetic; oracle-vs-market. Reuse generators and alignment/provenance gates.
- Strategy topology/ranking: `src/strategy/registry.py`, arbitrage graph, multihop solver and ranker. A shortlist is not exact profit.
- Size search: `src/economics/non_monotonic_sizing.py` / PR118 owners; fresh exact quote for every size.
- `src/strategy_evolution/` contains nine existing packages, all DISABLED. Do not clone or enable them.
- Liquidation remains a shadow planner. Stable peg math exists; do not fork.
- P0-3 #613 contributes Raydium CLMM/Meteora DLMM offline math/decoders, not live quote proof.

## Parallel R10 worktrees
1. R10-A issuer/PSM/flash-mint: caller eligibility, fees, caps and buffer state; conditional hyperedges.
2. R10-B LST/LRT/BTC: exchange rate, queue/instant exit, slashing, custody and bridge identity; AssetResolver + #614.
3. R10-C Curve LLAMMA/liquidation: per-market factory/AMM, active bands, collateral/borrowed assets, oracle/health state; shadow only.
4. R10-D Pendle/vault rights: PT/YT/SY maturity and implied vs underlying yield; ERC-4626 etc redemption/withdraw queues.
5. R10-E CLOB/AMM/multipath: exact VWAP, IOC/partial fill, book freshness, ticks/bins, dynamic fees and shared resource constraints.
6. R10-F spot-perp/options/prediction: instrument identity, settlement, hedge, funding/inventory costs; non-atomic by default.
7. R10-G intents/OEV/MEV/JIT/rebates: signed-intent limits, quote TTL, selective-data permissions, auction eligibility, legitimate liquidity provision. MEV-Share is backrun-only; no sandwich/frontrun.
8. R10-H bridge/rollup/TON/Cosmos: finality, queue and inventory; default SIGNAL_ONLY/ASYNC.
9. R10-I relations/ML: REL-01..REL-14 and V3/V4 detectors with time-aware replay/holdout.

## Falsifiable experiment protocol
Define mechanism, expected sign, null and controls; canonical assets/markets; settlement class (LOCAL_ATOMIC, CONDITIONAL_HYPEREDGE, HEDGED_NON_ATOMIC, SIGNAL_ONLY, EXCLUDED); source dependencies; amount grid/exact quotes; fee/cap/rights/all-in cost; resource correlation; failure modes; immutable positive/negative/no-trade episodes; time-blocked holdout; pool/provider alias leakage controls; source ablation; multiple-testing correction and counterexamples. Deterministic baseline before ML. Report sample size, confidence, calibration, false positives/negatives, latency, drift and costs.

## Acceptance
Machine-readable crosswalk with IDs, owners, evidence class, status, missing proof and next bounded task. Replay or typed BLOCKED_NOT_ENOUGH_DATA report per selected hypothesis. No new graph, solver, registry, ledger, authority or live promotion.
