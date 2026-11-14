# Archive detector/anomaly taxonomy reconciliation — SX-17

## Purpose

The V3/V4/V6 archives contain different conceptual layers: **64 anomaly classes, 25 detector templates, 19 V3 research route families, 36 V6 route hypotheses, 12 conditional protocol hyperedges and 4 flash-funding primitive families**. These are not 164 independent trading strategies. Some describe market opportunity families; others are data-quality, identity, exact-state, capital, settlement or risk guards.

SX-17 reconciles every archive ID to the existing code/research owner and identifies only genuinely orphaned work. It is additive; do not create another graph, solver, asset registry, relation registry, correlation ledger, source store, quote kernel, capital graph, or scheduler.

## Source-backed counts and semantics

| Archive layer | Count | Meaning |
|---|---:|---|
| V3 anomaly taxonomy | 64 | Detection hypotheses, state/risk guards, data-quality controls and reference signals |
| V4 detector templates | 25 | Hypotheses only; each has execution permission NONE and requires negative examples |
| V3 route families | 19 | Discovery-only symbolic topology; strict_exec_proof=false |
| V6 route families | 36 | Archived composition candidates; atomicity, funding capacity, exact quotes and net PnL not verified |
| V6 conditional hyperedges | 12 | Rights/transformations; includes delayed and cross-chain cases, not ordinary swap edges |
| V6 flash-funding models | 4 | Project 0, DeepBook V3, Morpho Blue and Aave V3; documented primitive does not prove current capacity |

The exact source IDs and mapped owners are in `ARCHIVE_DETECTOR_TAXONOMY_CROSSWALK_V1.json`.

## Mapping principles

1. **Anomaly ≠ strategy.** `QUOTE_FRESHNESS_DRIFT`, `PROVIDER_SCHEMA_DRIFT`, `SHARED_LIQUIDITY_ALIAS` and `ORACLE_CONTRACT_VERSION_CHANGE` are evidence guards, not alpha families.
2. **Transformation ≠ swap.** ERC-4626 redemption, Pendle maturity, USUAL split/combine, queues, caller eligibility and buffer constraints require typed vectors, rights and same-transaction postconditions.
3. **Reference signal ≠ executable quote.** CCTP/OFT flow, CEX lead/lag, oracle/FX/gold and multi-period funding may prioritize a local search or a distinct inventory strategy, but do not provide local flash liquidity or atomic settlement.
4. **Route labels ≠ independent liquidity.** `MULTIVENUE`, `ROUTER_TOPOLOGY_FLIP`, `SHARED_LIQUIDITY_ALIAS` and `PENDLE_ROUTER_ALIAS` require physical pool/book/resource lineage and correlation-group deduplication.
5. **Protocol math is revision-specific.** Hook-driven Uniswap v4, Pancake Infinity LBAMM, Balancer rate providers, CLMM ticks and DLMM bins need exact state/fee/rounding models. Never fall back to constant product outside proven model scope.
6. **No implicit execution.** Every V4 detector is HYPOTHESIS / execution_permission NONE. All 36 V6 routes have sign/broadcast, atomicity, capacity, exact quote and net-PnL flags false in the archived snapshot.

## Preserved V3 route families

All 19 are `DISCOVERY_ONLY`: USD_STABLE_TRIANGLE, CURRENCY_FX, BTC_WRAPPER_TRIANGLE, ETH_LST_NAV, HYPE_LST_NAV, SUI_LST_RELATIVE, SOL_LST_RELATIVE, USDT0_LOCAL_FLOW, RON_CHAIN_RWA, MONAD_MENTO_FX, PT_MATURITY_PAIR, PLASMA_YIELD, X_LAYER_STABLE, INK_BTC, ARC_BTC, TON_LST_DATA, COSMOS_SQS, BALANCER_VAULT, CETUS_DEEPBOOK. They include stable triangles, FX, BTC wrappers, LST/NAV, PT maturity, cross-chain flow, yield, multi-asset Balancer and Cetus/DeepBook. A route family does not prove that every leg exists concurrently.

## V6 structures to retain

### Conditional hyperedges

- USUAL USD0 split to bUSD0 + rt-bUSD0 and early-exit combine.
- EUR0 swapper buffer: T+0 only when buffer is available; otherwise T+1…T+5.
- sUSD0 and sEUR0 ERC-4626 redemption.
- frxUSD direct USDC exit; maxRedeem, USTB liquidity, sender eligibility and allowance must be proven.
- sfrxUSD and scrvUSD share redemption.
- Ethena sUSDe exit has a 1–7 day cooldown.
- Pendle PT-USDG redemption is time-locked; before maturity a verified DEX sale is a separate market route.
- CCTP USDC and USDT0 OFT are asynchronous cross-chain transformations for signal/rebalance only.

The JSON preserves exact hyperedge IDs, chain, operation kind and archived execution class. Do not put delayed or bridge operations in the normal flashloan critical path.

### Flash-funding primitive references

Project 0, DeepBook V3, Morpho Blue and Aave V3 are all marked `PRIMITIVE_DOCUMENTED_CAPACITY_UNKNOWN`. Refresh current reserve/bank/pool balance, fee, caller rights, callback/repayment, deployment identity and freshness before considering any provider edge. Documentation of a primitive is not a live capacity read.

## SX-17 assignment

**Owner:** strategy-campaign coordinator with existing domain owners.

1. Refresh current main, open PRs, current R10/SX/EXP/W6 owner maps and the latest pair reconciliation (PAIR-00). Do not trust snapshot SHAs.
2. Reconcile all 64/25/19/36/12/4 archive IDs to a canonical owner, category, chain/settlement class, data dependency, exact proof gate, current status and next bounded task.
3. Identify true orphaned work only. Explicitly check multi-token pool/resource hyperedges (Balancer/Curve/Aftermath), Mento FX sessions, Balancer rate-provider drift, Phoenix version/queue semantics and hook custom accounting.
4. Keep multi-token pools as one state/resource with vector balances. Do not decompose one Balancer/Curve pool into independently spendable pair capacities.
5. Extend existing owners/tests only. No new global registry, feature store, graph, scheduler or exact quote kernel.
6. Add negative cases: missing/ambiguous pool, identity collision, stale state, incomplete ticks/bins, hook mismatch, redemption queue, zero capacity, aliased route, partial fill, bridge timeout, token restriction and no-trade.
7. Pin official source URLs, versions/revisions, content hashes, retrieval dates and licenses before adding protocol-specific behavior.

## SX-17 acceptance

- The machine crosswalk validates exactly 64 / 25 / 19 / 36 / 12 / 4 entries.
- All archive IDs are included once, with lineage/overlap recorded separately.
- Every ID maps to an existing owner or typed `ORPHANED_RESEARCH_ONLY`; no silent omissions.
- Detector, guard, signal, route, hyperedge and funding concepts are not conflated.
- Historical no-permission and unknown-evidence states are preserved until current proof exists.
- Shared pool/book/tick/bin/collateral/lender capacity cannot be double-counted.
- JSON/schema validation and deterministic offline tests pass; no runtime enablement or live financial action.

## Relationship to PAIR-00

PAIR-00 is responsible for every archived pair/asset row's identity, venue, pool and current evidence. SX-17 covers the detector/anomaly/route/hyperedge/funding concepts that sit above or beside those pair records. Do not redo PAIR-00 or the already-owned P0 source/quote work.
