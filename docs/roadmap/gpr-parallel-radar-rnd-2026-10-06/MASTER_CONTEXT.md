# MASTER CONTEXT — GPR V2.1 / Qualification Topology

Date: 2026-10-06  
Repository: `BobIvans/studious-pancake`  
Continuation: PR #571

## Foundation

Reuse:
- QPR-01 authority identity;
- QPR-02 governed Solana RPC/direct-state qualification;
- QPR-03 SourceIntakePlane and durable raw/negative evidence;
- MarketObservationV2;
- ShadowMarketGraphIngest;
- UniversalArbitrageGraph;
- multihop / PR118 / split-flow / RouteGraph owners.

## Ontology

```text
EconomicAsset
  -> Representation
  -> Chain
  -> Venue / Protocol
  -> Transformation
```

Ticker equality never means execution identity equality.

## Registry V2.1

`ASSET_REGISTRY_V2.json` now contains **91 research identities**.

Important V2.1 corrections/additions:
- USDG = Token-2022.
- PYUSD = Token-2022.
- Solana xBTC_OKX added.
- Sui generic Wormhole wUSDC is explicitly ETH-origin.
- Sui Solana-origin USDCsol Portal representation added separately.
- Sui XAUM tokenized-gold identity added.
- all remain runtime-disabled / exact-graph-disabled by default.

## Relation state is three-dimensional

Do not overload HOT/WARM with execution truth.

```text
heat = HOT | WARM | COLD | EVENT
execution_class =
  LOCAL_ATOMIC | LOCAL_SIGNAL | CROSS_CHAIN_SIGNAL | REBALANCE_ONLY
evidence_state =
  DISCOVERY_ONLY | IDENTIFIER_VERIFIED | RPC_VERIFIED | EXECUTABLE
```

This lets a market be watched constantly while still being unverified or non-atomic.

## Initial 14-family campaign

The first high-value rotation is materialized in `FIRST_CAMPAIGN_FAMILIES_V2_1.json`.

Priorities:
1. USDG/USDC Solana — HOT local-atomic candidate.
2. USD1/USDT + USD1/USDC — HOT local-atomic candidates.
3. PYUSD/USDG — WARM synthetic first; direct market only if discovered.
4. xBTC_OKX/cbBTC — WARM local-atomic candidate with HOT signal priority.
5. JLP/USDC + live NAV — HOT signal / NAV basis.
6. BNSOL/bbSOL/hSOL/dSOL vs SOL — WARM structural.
7. Sui wUSDC/native USDC — HOT representation-basis signal.
8. Sui Wormhole USDT vs Sui-Bridge USDT — HOT signal.
9. suiUSDe/USDC + SUI/suiUSDe.
10. USDsui/USDC + SUI/USDsui.
11. XBTC/USDC + ZWBTC/USDC.
12. afSUI/haSUI/vSUI/scaSUI.
13. XAUM vs XAU/USD — research.
14. USDC Solana ↔ native USDC Sui ↔ Solana-origin USDCsol on Sui — HOT cross-chain signal, never an atomic bridge leg.

Everything outside this batch remains cheap/dynamic research until evidence promotes it.

## DeepBook seed

`SUI_DEEPBOOK_POOLS_V2_1.json` contains 9 current pool IDs for the priority Sui representation/stable/BTC experiments. Pool IDs are identifiers for read-only onboarding, not exact state proof.

## Structural anchors

ResearchRelation should carry explicit anchor semantics:
- USD_REDEMPTION
- STAKING_EXCHANGE_RATE
- NAV
- SAME_UNDERLYING
- BRIDGE_PARITY
- ORACLE_REFERENCE

This is the difference between economic anomaly research and simple API price disagreement.

## Verification boundary

A known identifier is not HARD_BOUND.

At campaign startup, exact promotion requires a receipt asserting:
- owner/program or Move type;
- decimals;
- extensions/token standard;
- exact pool/book identity;
- slot/checkpoint/state;
- fee/depth semantics;
- campaign/repository generation.

Solana then uses QPR-02/direct state.
Sui uses its separate governed checkpoint/object path once implemented.

## Cross-chain

Solana and Sui are economic execution islands.

Cross-chain USDC/FDUSD/USDY/SOL/BTC relations are signals and future rebalance inputs. Bridge/CCTP/Wormhole is not inserted into the local atomic arbitrage solver.

## Safety

No signer, sender, submission, live capital or promotion authority.
