# MASTER CONTEXT — GPR V2 / Multi-layer Economic Topology

Date: 2026-10-06  
Repository: `BobIvans/studious-pancake`  
Canonical continuation: PR #571 / branch `rnd/gpr-parallel-radar-2026-10-06`

## State inherited from QPR

QPR-01/02/03 were implemented as a stacked sequence. The public `main` branch is not the reliable indicator of the whole stack because the master handoff PR #567 is still open. GPR implementation must therefore use the #571 continuation branch until the stack is reconciled.

Existing owners remain authoritative:

- QPR-01 campaign/runtime authority identity;
- QPR-02 governed independent RPC/direct-state qualification;
- QPR-03 SourceDossier / ProviderProfile / SourceIntakePlane / raw+negative evidence;
- `MarketObservationV2`;
- `ShadowMarketGraphIngest`;
- `UniversalArbitrageGraph`;
- bounded multihop solver;
- PR118 non-monotonic sizing;
- split-flow and RouteGraph owners.

## Renewed strategy

The next system is not primarily a list of pairs.

The ontology is:

```text
EconomicAsset
    ↓
Representation
    ↓
Chain
    ↓
Venue / Protocol
    ↓
Transformation
```

This prevents ticker aliasing and allows one economic asset to have several non-interchangeable executable representations.

Examples:
- native USDC on Solana;
- native USDC on Sui;
- Wormhole USDC on Sui;
- SOL on Solana;
- Wormhole SOL on Sui;
- cbBTC/tBTC/Wormhole-WBTC on Solana;
- XBTC/Wormhole-WBTC/Sui-Bridge-WBTC/zwBTC on Sui.

## Asset Registry V2

`ASSET_REGISTRY_V2.json` contains **88 research identity rows** spanning Solana, Sui and TON.

The renewed registry adds:
- larger Solana LST graph: hSOL, dSOL, BNSOL, bbSOL, bpSOL, laineSOL, dfdvSOL;
- Solana restaking/LRT: sSOL, fragSOL;
- Solana stable/yield/NAV: USDG, FDUSD, EURC, JLP;
- Sui stable mechanisms: native/bridge USDT, Wormhole USDT/USDC, FDUSD, USDY, suiUSDe, BUCK, mUSD;
- Sui BTC representations: XBTC, Wormhole WBTC, Sui-Bridge WBTC, zwBTC;
- Sui staking: afSUI, haSUI, vSUI, scaSUI;
- Wormhole SOL on Sui;
- TON canonical research identities.

All rows remain runtime-disabled until stronger qualification.

## Strong anomaly families

Prioritize structural relations over random token count:

1. Solana LST/LRT relative value and instant-exit basis.
2. JLP market price vs reconstructed NAV.
3. stable mechanism divergence.
4. native-vs-bridged stable basis on Sui.
5. BTC representation basis.
6. AMM vs CLOB / DeepBook.
7. direct-vs-synthetic path residuals.
8. amount/route-topology non-monotonicity.
9. lending/flash-capacity and funding-cost regime changes.
10. cross-chain basis signals between prefunded execution islands.

## Solana + Sui

Develop both chains after shared GPR-01 contracts:

### Solana exact-primary
Cheap/indexed radar -> 0x -> Jupiter -> Sanctum when LST -> independent RPC/direct state -> existing exact graph.

### Sui shadow-primary
Aftermath + Cetus/DeepBook research -> checkpoint/object state via gRPC/GraphQL -> Sui shadow exact evidence.

Do not introduce a new Sui JSON-RPC dependency.

## Cross-chain research

Solana and Sui are two local execution islands connected economically, not atomically.

Initial anchors:
- native USDC Solana <-> native USDC Sui;
- SOL Solana <-> Wormhole SOL Sui;
- FDUSD Solana <-> FDUSD Sui;
- USDY Solana <-> USDY Sui;
- BTC representation families;
- chain-local LST/funding regimes.

The future strategy is **prefunded simultaneous local execution + later rebalance**, not bridge latency inside the critical arbitrage transaction.

## Hard restrictions

- Discovery/router data never becomes executable truth directly.
- Registry identity is not proof of pool/venue state.
- `REVALIDATE_CURRENT`, `REVALIDATE_ISSUER_STATUS`, and `UNRESOLVED` statuses fail closed.
- Token-2022 semantics must be qualified separately.
- Bridge/equivalence edges never enter the atomic graph.
- No signing/sending/submission/live trading in this R&D wave.
