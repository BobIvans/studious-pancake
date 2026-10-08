# QPR-03 COMPATIBILITY NOTES — GPR V2

GPR V2 is an extension above the QPR-03 campaign-start slice. It must not weaken QPR evidence boundaries.

## Reuse

- SourceDossier / ProviderProfile / SourceReadRequest / SourceIntakePlane;
- campaign identity and evidence journal;
- raw + negative evidence;
- deterministic QPR-03 candidate provenance;
- QPR-02 independent RPC/direct-state quorum;
- MarketObservationV2;
- existing exact graph / multihop / PR118 owners.

## Do not mutate away

QPR-03 Candidate is Solana-specific by design. Do not relax pubkey/program/chain checks to admit Sui or TON.

Add chain-neutral EconomicAsset/Representation/ResearchRelation owners above it.

The new Asset Registry V2 is a research identity catalog. It does not replace QPR-02/QPR-03 proof.

## Solana bridge

```text
ASSET_REGISTRY_V2
 +
QPR-03 Candidate/raw evidence
      ↓
SolanaResearchAdapter
      ↓
ResearchRepresentation + ResearchRelation
      ↓
ResearchEconomicGraph
      ↓
CandidateScore / VerificationRequest
      ↓
QPR-02 exact state
      ↓
MarketObservationV2
      ↓
ShadowMarketGraphIngest
      ↓
UniversalArbitrageGraph
```

## Sui bridge

```text
ASSET_REGISTRY_V2
 +
Sui source evidence
      ↓
SuiResearchAdapter
      ↓
ResearchRepresentation + ResearchRelation
      ↓
ResearchEconomicGraph
      ↓
Sui VerificationRequest
      ↓
gRPC/GraphQL checkpoint/object state
      ↓
Sui shadow exact result
```

Do not add Sui to the Solana exact graph by weakening domain checks.

## Interchain bridge

```text
Solana Representation
       ↕
research-only economic/rebalance relation
       ↕
Sui Representation
```

There is no direct Solana-to-Sui atomic executable graph edge.

Examples:
- USDC Solana <-> USDC Sui via CCTP research/rebalance relation;
- SOL Solana <-> Wormhole SOL Sui;
- FDUSD Solana <-> FDUSD Sui;
- USDY Solana <-> USDY Sui;
- BTC economic representation families.

A future prefunded simulator may compare simultaneous local executions and later rebalance, but that is outside GPR-01.
