# CODEX START HERE — Universal Source + Execution Expansion

Base: published GPR-01 contracts from PR #571.

Read:
1. `MASTER_CONTEXT.md`
2. `PROVIDER_MATRIX.md`
3. `PROVIDER_MATRIX.json`
4. `SOURCE_LINKS_AND_ONBOARDING.md`
5. `EXECUTION_BUILDER_CONTRACT.md`
6. `RENT_SPONSOR_PLANNER.md`
7. `SLUMLORD_ATA_RENT.md`
8. `DYNAMIC_UNIVERSE_AND_RELATIONS.md`
9. `FLASH_CAPITAL_GRAPH.md`
10. `CORRELATION_LEDGER.md`
11. `OBSERVATION_SCHEMA_V3.json`
12. `IMPLEMENTATION_ROADMAP.md`
13. `ACCEPTANCE_TESTS.md`

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

Use `RentSponsorPlanner` for account/rent costs:
existing account -> provider sponsor/payer -> Slumlord ephemeral -> persistent local ATA.

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

### Dynamic universe / data

Use live registries and market discovery rather than manually polling hundreds of pairs:
- Sanctum LST registry
- Manifest/Raydium/Meteora/Orca markets
- DeepBook/Aftermath/Cetus/NAVI/Scallop/7K/FlowX/Bluefin
- STON/Omniston/swap.coffee/DeDust/Tonco
- oracle/CEX/reference sources for structural and lead-lag research.

## Stop conditions

Each implementation PR must stop after its scoped provider/radar/builder slice and produce evidence:
- provider limits observed
- build success/failure
- simulation result
- correlation group
- quote/route fingerprints
- rent/sponsor plan
- no private key exposure
- no live send unless separately authorized
