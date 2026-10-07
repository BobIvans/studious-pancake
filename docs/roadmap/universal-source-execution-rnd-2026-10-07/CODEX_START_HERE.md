# CODEX START HERE — Universal Source + Execution Expansion

Base: published GPR-01 contracts from PR #571.

Read:
1. MASTER_CONTEXT.md
2. PROVIDER_MATRIX.md
3. PROVIDER_MATRIX.json
4. EXECUTION_BUILDER_CONTRACT.md
5. SLUMLORD_ATA_RENT.md
6. DYNAMIC_UNIVERSE_AND_RELATIONS.md
7. FLASH_CAPITAL_GRAPH.md
8. CORRELATION_LEDGER.md
9. OBSERVATION_SCHEMA_V3.json
10. IMPLEMENTATION_ROADMAP.md
11. ACCEPTANCE_TESTS.md

## Do not replace GPR-01

Reuse:
- `src/research_economic_graph`
- AssetRegistry / CampaignSeed
- ResearchRelation
- ResearchEconomicGraph
- CandidateScore
- VerificationQueue
- HardBoundIdentityGate
- QPR-02/QPR-03 evidence owners
- MarketObservationV2 / exact graph / PR118 owners

## Immediate implementation direction

This package extends GPR-02 and GPR-03; it does not restart GPR-01.

Implement provider contracts first, then Solana and Sui adapters in isolated worktrees.

### Solana
Build a quote/build race across:
- 0x
- Titan
- Jupiter
- OpenOcean
- OKX DEX
- Rango
plus direct venue/radar sources.

Jupiter remains a reference/fallback. Its 1 RPS general Free limit must not serialize the entire qualification loop.

### Sui
Build a quote/PTB race across:
- Aftermath
- Cetus Aggregator
- 7K / Bluefin7K
- FlowX MetaAggregator
- OKX DEX
- Rango
- direct DeepBook/Cetus state paths

### Signing policy

Providers only return instructions / serialized unsigned transaction / PTB.
Private keys remain local.

During qualification:
`sign_enabled = false`.
Build + normalize + simulate only.

A separate future production gate may enable a LocalSigner.

### Slumlord

Implement only after the instruction-composable Solana builder contract exists.

Slumlord may finance rent only when the transaction can close every Slumlord-funded temporary token account and repay the SOL loan in the same transaction.

It is not a promise of free persistent ATAs for every pair.

## Stop conditions

Each implementation PR must stop after its scoped provider/radar/builder slice and produce evidence:
- provider limits observed
- build success/failure
- simulation result
- correlation group
- quote/route fingerprints
- no private key exposure
- no live send unless separately authorized
