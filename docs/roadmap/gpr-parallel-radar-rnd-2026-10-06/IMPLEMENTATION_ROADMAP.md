# IMPLEMENTATION ROADMAP — GPR V2.1

## GPR-00 — evidence hardening gate

Re-check any still-live QPR review blockers that can corrupt campaign evidence. Fix only what blocks trustworthy GPR-01.

## GPR-01 — Registry + Evidence-Classified Research Graph + Verification Queue

**NEXT CODE PR. STOP AFTER COMPLETION.**

### A. Registry V2.1
- typed loader for `ASSET_REGISTRY_V2.json`;
- support origin_chain / bridge / issuer / decimals;
- preserve representation identity;
- registry digest/generation;
- fail closed on REVALIDATE/UNRESOLVED;
- no ticker-only exact lookup.

### B. HARD_BOUND identity gate
At campaign startup, assert exact identifier + owner/program/Move-type + decimals + relevant extension/representation semantics and persist a receipt.

### C. ResearchRelation V2.1
Implement independent:
- heat;
- execution_class;
- evidence_state;
- anchor types;
- pool/book identifiers;
- synthetic paths;
- provenance.

### D. ResearchEconomicGraph
- chain-neutral representation nodes;
- QPR-03 Solana intake adapter;
- deterministic dedup;
- structural anchors;
- negative evidence;
- cross-chain relations as research/rebalance only.

### E. CandidateScore + VerificationQueue
- deterministic score decomposition;
- top-K bounded work;
- chain-specific verification target;
- no profitability claim.

### F. Load initial seed
- `FIRST_CAMPAIGN_FAMILIES_V2_1.json`;
- `SUI_DEEPBOOK_POOLS_V2_1.json`;
- broader symbolic universe remains cheap/dynamic.

Acceptance:
- 91 registry rows load deterministically;
- USDG and PYUSD retain Token-2022 identity metadata;
- Solana xBTC_OKX exists separately from cbBTC/WBTC/tBTC;
- four relevant USDC representations remain distinct;
- XAUM loads with XAU oracle/reference semantics;
- 14 families load with all 3 classification axes;
- 9 DeepBook pool IDs load as IDENTIFIER_VERIFIED research refs;
- HARD_BOUND fails closed without chain-state receipt;
- CROSS_CHAIN_SIGNAL/REBALANCE_ONLY never enter exact graph;
- replay reproduces graph identity and classification.

## GPR-02 — Solana Parallel Radar / first real campaign

Start after GPR-01 contract stability, in parallel with GPR-03.

Primary first-campaign families:
1. USDG/USDC — HOT local-atomic candidate.
2. USD1/USDT — HOT local-atomic candidate.
3. USD1/USDC — HOT local-atomic candidate.
4. xBTC_OKX/cbBTC — WARM local-atomic candidate, HOT signal priority.
5. JLP/USDC + live NAV — HOT signal.
6. BNSOL/bbSOL/hSOL/dSOL vs SOL — WARM structural.

Radar:
- Manifest books;
- DEX Screener batches;
- Meteora/Raydium indexed state;
- Jupiter token/route metadata.

Candidate quote funnel:
`cheap radar -> 0x -> Jupiter -> Sanctum for LST -> QPR-02 exact state`.

PYUSD/USDG stays WARM synthetic first:
`PYUSD/USDC ÷ USDG/USDC`.
Direct PYUSD/USDG is promoted only when discovery proves a current market.

## GPR-03 — Sui Parallel Shadow Campaign

Start in parallel with GPR-02 after GPR-01.

Priority families:
7. WUSDC_ETH_ORIGIN / USDC_NATIVE.
8. USDT_WORMHOLE vs USDT_SUI_BRIDGE.
9. suiUSDe/USDC + SUI/suiUSDe.
10. USDSUI/USDC + SUI/USDSUI.
11. XBTC/USDC + ZWBTC/USDC.
12. afSUI/haSUI/vSUI/scaSUI.
13. XAUM vs XAU/USD reference.

Use:
- DeepBook known pool IDs;
- Aftermath;
- Cetus;
- Scallop rates;
- governed Sui gRPC/GraphQL checkpoint/object state.

No new legacy JSON-RPC dependency.
No live PTB signer/executor.

## GPR-04 — Dynamic Watch Universe + heat scheduler

Use `heat` independently from execution/evidence state.

Promote/demote from measured:
- recurrence;
- divergence;
- liquidity/depth;
- topology changes;
- staleness;
- source disagreement;
- structural-anchor residual.

No polling loop per symbolic pair.

## GPR-05 — Structural transformation graph

Add deeper LST/LRT/NAV/lending/capacity/cost transformations only from campaign evidence.

## GPR-06 — Solana↔Sui economic signals

Family 14 first:
`USDC_SOL_NATIVE ↔ USDC_SUI_NATIVE ↔ USDC_SOL_PORTAL_ON_SUI`.

Use `CROSS_CHAIN_SIGNAL`; bridge/CCTP/Wormhole transport is `REBALANCE_ONLY`.

Then consider FDUSD/USDY/SOL/BTC/LST/funding regime relations from evidence.

## GPR-07 — Prefunded cross-chain simulator

Only after GPR-06.

Model simultaneous local execution with prefunded inventory and later rebalance. Include hedge, inventory, bridge/rebalance, latency and capital-fragmentation costs.

No live cross-chain executor.

## GPR-08 — TON research lab

Keep STON/TON high-throughput research separate from Solana/Sui exact execution until justified.

## Production boundary

Signer/sender/submission/promotion remain outside this roadmap.
