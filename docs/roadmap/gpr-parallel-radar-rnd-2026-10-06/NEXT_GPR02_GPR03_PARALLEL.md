# NEXT GOALS AFTER GPR-01 PUBLICATION — GPR-02 + GPR-03 PARALLEL

These two streams are prepared now but must use the **published/reconciled GPR-01 contracts** as their base.

## GPR-02 — Solana Parallel Radar + Qualification Funnel

### Objective

Turn the first Solana campaign families into a real read-only radar -> quote-preview -> exact-verification pipeline.

### Priority first-campaign families

1. USDG/USDC
2. USD1/USDT
3. USD1/USDC
4. xBTC_OKX/cbBTC
5. JLP/USDC vs live JLP NAV
6. BNSOL/bbSOL/hSOL/dSOL vs SOL

### Radar/data plane

Use cheap/high-throughput sources first:

```text
Manifest books
+ DEX Screener batches
+ Meteora/Raydium indexed state
+ Jupiter token/route metadata
        ↓
ResearchEconomicGraph
```

### Quote-preview funnel

```text
candidate
 -> 0x read-only quote preview
 -> Jupiter reference/final quote
 -> Sanctum for LST/LRT structural comparisons
 -> optional correlated comparator
 -> QPR-02 exact independent RPC/direct state
 -> MarketObservationV2
 -> existing exact graph
```

### Mandatory Token-2022 work

USDG and PYUSD are Token-2022.

Do not merely accept the mint. HARD_BOUND must assert relevant owner/program/decimals/extensions/fee/transfer semantics before exact promotion.

### Outputs

- measured source availability/limits;
- anomaly recurrence;
- quote disagreement;
- direct-vs-synthetic residuals;
- exact verification pass/fail reasons;
- request cost/budget accounting;
- evidence-based next decoder priorities.

No signer/sender/live execution.

---

## GPR-03 — Sui Parallel Shadow Qualification

### Objective

Build the equivalent Sui research -> exact-state shadow path without introducing a live PTB executor.

### Priority families

1. WUSDC_ETH_ORIGIN / USDC_NATIVE
2. USDT_WORMHOLE / USDT_SUI_BRIDGE
3. suiUSDe/USDC + SUI/suiUSDe
4. USDSUI/USDC + SUI/USDSUI
5. XBTC/USDC + ZWBTC/USDC
6. sSUI/afSUI/haSUI/vSUI/scaSUI
7. XAUM vs XAU/USD
8. USDC_SOL_PORTAL_ON_SUI representation-basis signal

### Read-only data plane

```text
DeepBook known pools/books
+ Aftermath
+ Cetus
+ Scallop rates
+ oracle/reference inputs
        ↓
ResearchEconomicGraph
        ↓
VerificationQueue
        ↓
governed gRPC/GraphQL checkpoint/object state
```

### Known DeepBook seeds

Use `SUI_DEEPBOOK_POOLS_V2_1.json` as identifier input only.

Each pool still requires current object/checkpoint/depth/fee verification.

### Transport semantics

Do not create fake token nodes for:
- CCTP;
- Wormhole route;
- USDT0 Legacy Mesh.

Use `TRANSFORMATION_REGISTRY_V2_2.json`.

### Outputs

- pool/object/checkpoint receipts;
- representation-basis anomalies;
- LST exchange-rate vs market residuals;
- DeepBook vs AMM/router divergence;
- oracle/reference residuals for XAUM;
- exact-state qualification gaps.

No JSON-RPC reintroduction, signer, sender, PTB live executor or live capital.

---

## Parallelism rule

GPR-02 and GPR-03 may run in parallel **after** the published GPR-01 contract is reconciled.

They share:
- AssetIdentity / Representation types;
- ResearchRelation classification;
- ResearchEconomicGraph;
- VerificationQueue;
- HARD_BOUND receipt contract.

They do not share:
- chain-specific exact-state transport;
- chain-specific execution authority;
- atomic transaction domain.

## Stop condition for each stream

Each stream should stop after a bounded real-data qualification slice and produce a handoff/problem report. Do not silently advance into live execution.
