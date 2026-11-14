# Canonical strategy catalog and execution contract

## 1. Strategy family taxonomy

| Group | Family IDs | Strategy concepts | Default execution class |
|---|---|---|---|
| Local swap arbitrage | ARB-01…ARB-08 | direct 2-leg, venue fragmentation, triangles, 2–5-hop, synthetic/direct, split-flow, stable routing, exact size islands | LOCAL_ATOMIC_CANDIDATE |
| Market microstructure | MICRO-01…MICRO-07 | AMM/CLOB, VWAP/depth, maker/taker, RFQ, JIT liquidity, LVR/toxic-flow, blockspace/auction-aware execution | MIXED; passive inventory is HEDGED_NON_ATOMIC |
| Primary-market transformations | TRANS-01…TRANS-08 | PSM, flash-mint, issuer mint/burn, instant redeem, wrappers, LST/LRT, LP share decomposition, ERC-4626/7540/7575 | CONDITIONAL_HYPEREDGE |
| Financial claims | CLAIM-01…CLAIM-07 | PT/YT/SY, fixed/floating claims, maturity, complete sets/prediction outcomes, rights conversion | CONDITIONAL_HYPEREDGE or HEDGED_NON_ATOMIC |
| Credit and solvency | CREDIT-01…CREDIT-07 | liquidation, LLAMMA, refinance, collateral swap, utilization/rate, shared collateral optimization, solvency events | LOCAL_ATOMIC_CANDIDATE for proven callbacks; otherwise HEDGED_NON_ATOMIC |
| Liquidity provision | LP-01…LP-05 | passive CLOB, RFQ market making, CLMM LP, JIT LP, LP lifecycle/fee harvesting | HEDGED_NON_ATOMIC; JIT only if a fully authorized atomic recipe is proven |
| Inventory/basis | BASIS-01…BASIS-08 | CEX/DEX, spot/perp, futures calendars, options parity, lending carry, cross-chain rebalance, wrapper basis, FX/gold reference | HEDGED_NON_ATOMIC or SIGNAL_ONLY |
| Event/mechanism | EVENT-01…EVENT-06 | launch/migration, governance/incentives, oracle update/OEV auctions, blockspace, auction design, market-mechanism experiments | SIGNAL_ONLY / RESEARCH_ONLY |
| Intelligence/data products | INTEL-01…INTEL-05 | anomaly detection, context bandit, source allocation, verifiable computation procurement, strategy learning | RESEARCH_ONLY; no direct execution rights |
| Portfolio/capital control | PORT-01…PORT-06 | flash lender selection, shared capacity, route portfolio, inventory and risk budgets, conflict scheduling, capital efficiency | CONTROL_PLANE; not a standalone alpha family |

The catalog extends, rather than replaces, S01–S07, OP-01…OP-28, WG-01…WG-28 and R10 A…I. Keep original IDs intact. Add stable IDs only for genuinely new mechanisms.

## 2. Execution classes (mandatory, mutually explicit)

- `LOCAL_ATOMIC_CANDIDATE`: all legs settle in one proven transaction/PTB and one compatible repayment domain. A strategy can be evaluated here only after protocol semantics, exact state and repayment are proven.
- `CONDITIONAL_HYPEREDGE`: transformation depends on rights, caller eligibility, caps, callback, receipt/hot-potato, vector outputs or same-tx postconditions. It is not an ordinary swap edge.
- `HEDGED_NON_ATOMIC`: multiple domains or time periods; requires prefunded inventory, margin, hedge, borrow/funding, settlement and failure-state model. Standard flash principal cannot finance the wait.
- `SIGNAL_ONLY`: external flow, oracle, event, lead/lag, macro or bridge signal that may prioritize local verification, never itself an executable leg.
- `CONTROL_PLANE`: capital allocation, scheduling, quota, conflict, provider procurement and risk controls.
- `RESEARCH_ONLY`: mechanism design, new-market discovery, data/compute market and offline hypothesis experiments.
- `EXCLUDED`: prohibited by user policy or safety constraints.

Never silently upgrade a family from one class to another. Each candidate route inherits the strictest class of all legs and must satisfy all obligations.

## 3. Canonical strategy contract

Every strategy package must declare these fields (JSON schema to be aligned with existing domain models; do not add a parallel runtime registry):

1. `strategy_id`, `family_id`, `version`, `owner`, `status`, `source_task_ids`.
2. Hypothesis, expected sign, null hypothesis, controls and counterexamples.
3. Input asset/claim vector and output asset/claim vector; canonical chain, issuer, mint/address, decimals and representation provenance.
4. Execution class, settlement domain, transaction boundary, finality and maximum holding horizon.
5. Market dependencies: venue, program/contract revision, pool/orderbook ID, underlying resource IDs, state generation and freshness.
6. Quote requirements: side, exact input/output, amount, fees, rounding, slippage, partial fill, dust, TTL, consumed input and residual assets.
7. Funding requirements: provider, asset, caller eligibility, borrow amount, fee, capacity, repayment asset/amount, callback and atomicity proof.
8. Full costs: DEX fee, maker/taker, flash fee, network/priority/tip, compute, rent, provider/API cost, hedge, funding, borrow, inventory markout and failed-attempt cost.
9. Capacity curve and sizing owner; each tested size re-quotes every affected leg in coherent state.
10. Shared resource set: pools, ticks/bins, books, collateral, borrower, lender, accounts, quota and blockspace.
11. Risk model: stale/reorg, depeg, oracle, slashing, pause, cap, queue, maturity, adverse selection, partial fill, liquidation, bridge/withdrawal/finality, MEV competition.
12. Deterministic replay inputs, data lineage, source rights, corpus hash, tests, no-trade reasons and held-out evaluation.
13. Typed promotion evidence and explicit blockers; no strategy self-promotion.

## 4. Common economics invariants

- Net outcome is computed in canonical units; principal and repayment obligations are separate from profit.
- Do not double-charge swap fees already embedded in quote output.
- A route is not profitable because marginal graph weights or spot prices imply a positive cycle.
- Every amount point is evaluated by exact amount-specific quotes and current state; no scaling a quote by a multiplier.
- A split path applies shared fixed costs once and variable costs per path, and consumes shared state sequentially/atomically.
- Vector claims, collateral/debt and split/merge operations conserve each asset/claim separately; no scalarized fake swaps.
- Flash capacity is not TVL; lender capacity, eligibility, fee and repay must be evidenced.
- Missing values remain null/unknown with typed rejection; never coerce to zero.
- Profit after costs must beat a same-time independent-execution baseline and risk-adjusted threshold; report uncertainty and failed attempts.

## 5. Promotion ladder

`RESEARCH_SEED → IDENTITY_VERIFIED → STATE_READ_PROVEN → EXACT_QUOTE → CAPACITY_PROVEN → BUILD_CONFORMANT → SIMULATION_PASS → PAPER_QUALIFIED`

The ladder is per strategy/venue/protocol/asset/chain revision. A proof for one pool, amount, chain or code revision does not promote another. Live remains hard-denied outside this pack.
