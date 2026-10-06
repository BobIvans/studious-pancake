# CODEX START HERE — GPR V2.1: Evidence-Classified Asset/Representation Graph

Canonical continuation PR: **#571**  
Branch: `rnd/gpr-parallel-radar-2026-10-06`

## Repository state

QPR-01/#568, QPR-02/#569 and QPR-03/#570 are the stacked qualification foundation. Master handoff PR #567 points to this continuation branch.

Do not restart the QPR sequence.

## Read first

1. `MASTER_CONTEXT.md`
2. `ASSET_REGISTRY_V2.json`
3. `ASSET_PROVENANCE_V2.md`
4. `FIRST_CAMPAIGN_FAMILIES_V2_1.json`
5. `SUI_DEEPBOOK_POOLS_V2_1.json`
6. `UNIVERSE_V2_EXPANSION.md`
7. `INTERCHAIN_RELATIONS_V2.json`
8. `ARCHITECTURE_CONTRACT.md`
9. `IMPLEMENTATION_ROADMAP.md`
10. `SOURCE_MATRIX.md`
11. `ANOMALY_TAXONOMY.json`
12. `ACCEPTANCE_TESTS.md`
13. existing QPR implementation handoff under `docs/roadmap/prequal-rnd-2026-10-06/implementation/`

## V2.1 corrections

The renewed attachment changes several assumptions:

- Solana `USDG` and `PYUSD` are Token-2022 identities; token program/extension semantics must be asserted, never inferred from ticker.
- Solana `xBTC_OKX` is added as a distinct BTC representation.
- Sui generic Wormhole wUSDC is separated from Solana-origin `USDCsol` Portal representation.
- Sui `XAUM` is added as a tokenized-gold / XAU reference experiment.
- Nine current DeepBook pool identifiers are materialized for read-only onboarding.
- Priority is no longer represented by one label such as HOT-EXEC.

## Mandatory three-axis relation state

Every ResearchRelation must carry three independent dimensions:

```text
heat:
  HOT | WARM | COLD | EVENT

execution_class:
  LOCAL_ATOMIC
  LOCAL_SIGNAL
  CROSS_CHAIN_SIGNAL
  REBALANCE_ONLY

evidence_state:
  DISCOVERY_ONLY
  IDENTIFIER_VERIFIED
  RPC_VERIFIED
  EXECUTABLE
```

Never infer execution authority from heat.

Examples:
- USDG/USDC may be `HOT + LOCAL_ATOMIC + IDENTIFIER_VERIFIED`.
- USDC_SOL ↔ USDC_SUI may be `HOT + CROSS_CHAIN_SIGNAL + IDENTIFIER_VERIFIED`.
- Neither is `EXECUTABLE` until the required exact verification exists.

## Immediate implementation scope

Implement only:

# GPR-01 — Asset/Representation Registry + Evidence-Classified Research Graph + Verification Queue

### GPR-01A — AssetIdentity / Representation

Implement chain-neutral identity with at least:

```text
asset_id
chain
canonical_identifier
token_program_or_move_type
decimals
economic_asset
representation_kind
origin_chain
bridge
issuer
verification_state
verification_sources[]
identity_generation
```

The exact identity is the full representation, never the ticker.

Must remain distinct:
- Solana USDC vs Sui native USDC vs Sui ETH-origin Wormhole wUSDC vs Sui Solana-origin USDCsol.
- Solana xBTC_OKX vs cbBTC vs WBTC_WORMHOLE vs tBTC.
- Sui XBTC vs WBTC_WORMHOLE vs WBTC_SUI_BRIDGE vs ZWBTC.

### GPR-01B — ResearchRelation

Add:
- `heat`
- `execution_class`
- `evidence_state`
- `anchor_type[]`
- exact representation refs
- source/provenance refs
- direct venue/pool refs when known
- synthetic paths
- correlation and staleness data

Anchor types must include at least:
- USD_REDEMPTION
- STAKING_EXCHANGE_RATE
- NAV
- SAME_UNDERLYING
- BRIDGE_PARITY
- ORACLE_REFERENCE

### GPR-01C — Startup HARD_BOUND gate

A registry identifier may be research-visible at `IDENTIFIER_VERIFIED`, but before any exact/HARD_BOUND use assert chain state for:
- owner/program or Move type;
- decimals;
- token standard/extensions where applicable;
- exact canonical identifier;
- issuer/bridge representation where material.

Produce a machine-readable identity receipt bound to campaign/repository generation.

### GPR-01D — ResearchEconomicGraph + VerificationQueue

Reuse QPR-03 evidence and existing exact graph owners.

Solana exact promotion:
`VerificationRequest -> QPR-02/direct state -> MarketObservationV2 -> ShadowMarketGraphIngest -> UniversalArbitrageGraph`.

Sui remains shadow/read-only until governed checkpoint/object verification exists.

Cross-chain bridge/CCTP relations remain research/rebalance only.

## First campaign seed

Do not poll all 330 relationships equally.

Load `FIRST_CAMPAIGN_FAMILIES_V2_1.json` as the initial high-value qualification corpus. It contains 14 families spanning:
- USDG/USD1 stables;
- Solana xBTC/cbBTC;
- JLP vs NAV;
- selected Solana LSTs;
- Sui native/bridged stable representations;
- suiUSDe/USDsui;
- Sui BTC representations;
- Sui LSTs;
- XAUM/XAU reference;
- USDC Solana↔Sui cross-chain signal.

The broader universe stays dynamic/cheap and is promoted only from evidence.

## Stop condition

After GPR-01:
- registry/relation schemas implemented;
- deterministic replay passes;
- 14 families load;
- 9 DeepBook pool IDs load as research-only;
- all identity aliases are proven safe;
- HARD_BOUND gate fails closed;
- no CROSS_CHAIN_SIGNAL or REBALANCE_ONLY relation enters the atomic graph;
- report readiness for parallel GPR-02 Solana and GPR-03 Sui;
- STOP.

## Safety

No signer. No sender. No transaction submission. No live capital. No automatic production promotion.
