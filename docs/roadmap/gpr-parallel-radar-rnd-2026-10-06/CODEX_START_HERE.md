# CODEX START HERE — GPR V2: Asset/Representation Graph + Parallel Radar

Canonical continuation PR: **#571**  
Branch: `rnd/gpr-parallel-radar-2026-10-06`

## Repository state

QPR-01/#568, QPR-02/#569 and QPR-03/#570 are closed as merged inside the stacked development chain, but the top-level handoff PR #567 is still open. Do **not** assume public `main` contains the whole QPR stack.

Use this #571 branch as the implementation base for the next wave. Master handoff PR #567 has been renewed to point here. Keep this work PR based on the QPR-03 implementation branch for clean GPR-01 development; integrate it back into the master handoff only after the GPR-01 boundary is complete.

Read in this order:

1. `MASTER_CONTEXT.md`
2. `ASSET_REGISTRY_V2.json`
3. `ASSET_PROVENANCE_V2.md`
4. `UNIVERSE_V2_EXPANSION.md`
5. `INTERCHAIN_RELATIONS_V2.json`
6. `ARCHITECTURE_CONTRACT.md`
7. `IMPLEMENTATION_ROADMAP.md`
8. `SOURCE_MATRIX.md`
9. `ANOMALY_TAXONOMY.json`
10. `ACCEPTANCE_TESTS.md`
11. existing QPR handoff under `docs/roadmap/prequal-rnd-2026-10-06/implementation/`

## Important change from GPR V1

The package is **no longer placeholders-only**.

`ASSET_REGISTRY_V2.json` contains research-verified canonical Solana mints, Sui Move coin types and TON Jetton/master identities from the renewed R&D strategy.

This does **not** grant execution authority.

Every registry row defaults to:

- `runtime_enabled=false`
- `exact_graph_allowed=false`

Status gates must be enforced:

- `RND_VERIFIED_CURRENT`: usable as a research identity, still requires exact chain-state qualification before exact graph.
- `RND_VERIFIED_SPECIFIC_REPRESENTATION`: never ticker-alias with another wrapper/bridge representation.
- `REVALIDATE_CURRENT`: revalidate before any exact/runtime use.
- `REVALIDATE_ISSUER_STATUS`: identity exists, but current issuer-chain status must be refreshed before stronger claims.
- `UNRESOLVED`: research symbol only; no exact lookup/promotion.

Examples that must stay restricted:
- Solana `tBTC` = `REVALIDATE_CURRENT`;
- Solana `sUSDS` = `UNRESOLVED`;
- Sui `AUSD` = `REVALIDATE_ISSUER_STATUS`;
- Solana `fragSOL` identity is research-ready but Token-2022 semantics remain an exact-qualification gate.

## Immediate implementation scope

Implement only:

# GPR-01 — Asset/Representation Registry + Research Economic Graph + Verification Queue

### GPR-01A — Registry model

Implement chain-neutral types roughly equivalent to:

```text
EconomicAsset
Representation
AssetIdentity
IdentityStatus
RepresentationRelation
```

An executable identity is the full representation, not a ticker.

Examples that must remain distinct:
- `USDC@Solana`
- `USDC_NATIVE@Sui`
- `USDC_WORMHOLE@Sui`
- `USDT_SUI_BRIDGE`
- `USDT_WORMHOLE@Sui`
- `cbBTC@Solana`
- `WBTC_WORMHOLE@Solana`
- `XBTC@Sui`
- `WBTC_WORMHOLE@Sui`
- `WBTC_SUI_BRIDGE@Sui`
- `ZWBTC@Sui`

### GPR-01B — Research graph

Add a chain-neutral `ResearchEconomicGraph` above QPR-03 without weakening the existing Solana `Candidate` checks.

It may contain:
- discovery/market relations;
- router quote previews;
- structural anchors;
- LST/LRT exchange/redeem relations;
- stable/yield/NAV relations;
- lending/flash-capacity/cost signals;
- representation/economic-equivalence relations;
- research-only interchain basis relations.

It must **not** auto-create executable edges.

### GPR-01C — Verification queue

Implement decomposed `CandidateScore` + deterministic bounded `VerificationRequest`.

Solana exact promotion must still go through QPR-02/direct-state qualification and existing `MarketObservationV2 -> ShadowMarketGraphIngest -> UniversalArbitrageGraph`.

Sui exact promotion remains blocked until the governed gRPC/GraphQL checkpoint/object-state path exists.

### GPR-01D — Interchain ontology, research only

Load the six research edge types from `INTERCHAIN_RELATIONS_V2.json`:

- ISSUER_EQUIVALENCE
- NATIVE_BURN_MINT
- LOCK_MINT_BRIDGE
- ECONOMIC_UNDERLYING
- PROTOCOL_REDEMPTION
- INVENTORY_REBALANCE

These are **never atomic swap edges** in GPR-01.

## Stop condition

After GPR-01:
- run deterministic tests/replay;
- prove representation aliasing is impossible;
- prove REVALIDATE/UNRESOLVED identities cannot enter exact graph;
- prove no cross-chain relation enters the atomic graph;
- report exact changed files and remaining blockers;
- STOP.

Then split work in parallel:

- **GPR-02 — Solana Parallel Radar + 0x/Jupiter/Sanctum/Meteora**
- **GPR-03 — Sui Shadow Research + Aftermath/Cetus/DeepBook + gRPC/GraphQL**

Do not implement GPR-04+ in the GPR-01 PR.

## Safety boundary

No signer. No sender. No transaction submission. No live capital. No automatic production promotion. Cross-chain bridges are research/rebalance relations only.
