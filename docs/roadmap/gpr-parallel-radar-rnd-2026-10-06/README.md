# GPR V2 — Multi-layer Economic Topology

This is the renewed continuation strategy for the Qualification Campaign.

## Core architecture

```text
cheap/indexed/router observations
          ↓
AssetIdentity / Representation registry
          ↓
ResearchEconomicGraph
          ↓
heat + anomaly ranking
          ↓
bounded VerificationQueue
          ↓
chain-specific exact verification
          ↓
existing exact graph / route / sizing owners
```

The graph now distinguishes:

```text
EconomicAsset -> Representation -> Chain -> Venue -> Transformation
```

rather than treating a ticker as a token identity.

## What changed from V1

- Added `ASSET_REGISTRY_V2.json` with 88 Solana/Sui/TON research identities.
- Added the expanded Solana LST/LRT/stable/NAV universe.
- Added the expanded Sui stable/BTC/LST representation universe.
- Added `INTERCHAIN_RELATIONS_V2.json` with 12 initial Solana<->Sui research relationships.
- Added `UNIVERSE_V2_EXPANSION.md`.
- GPR-01 now implements Asset/Representation Registry + ResearchEconomicGraph + VerificationQueue.
- After GPR-01, Solana GPR-02 and Sui GPR-03 may proceed in parallel.
- Cross-chain execution is modeled later as prefunded local execution + rebalance, never as an assumed atomic bridge route.

## Safety

All registry assets default to `runtime_enabled=false` and `exact_graph_allowed=false`.

Canonical mint/coin/Jetton identity is necessary but not sufficient for exact or live use. QPR exact state, token semantics, venue state, costs and authority remain mandatory.

No signer, sender, submission or live-capital authority is introduced here.
