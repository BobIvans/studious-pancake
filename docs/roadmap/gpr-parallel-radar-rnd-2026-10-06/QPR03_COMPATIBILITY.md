# QPR-03 COMPATIBILITY NOTES

This package is intentionally compatible with the campaign-start slice in PR #570.

## Reuse

- `SourceDossier`, `ProviderProfile`, `SourceReadRequest`, `SourceIntakePlane`
- campaign identity and evidence journal
- negative evidence retention
- deterministic QPR-03 candidate dedup/provenance
- QPR-02 independent RPC quorum
- existing exact graph owners

## Do not mutate away

Current QPR-03 `Candidate` is strongly Solana-specific. Do not weaken its pubkey checks just to admit Sui or TON. Add a chain-neutral research model above it.

Current `SourceDossier` requires `DISCOVERY_ONLY` and a discovery role. Keep it for indexed source intake. Amount-specific router quote adapters may need a sibling dossier/capability class with equally strict evidence semantics rather than pretending quotes are identical to pool-discovery records.

## Required bridge

```text
QPR-03 Candidate / raw envelope
      ↓
SolanaResearchAdapter
      ↓
ResearchRelation
      ↓
ResearchEconomicGraph
      ↓
VerificationRequest
      ↓
QPR-02 exact state
      ↓
MarketObservationV2
      ↓
ShadowMarketGraphIngest
      ↓
UniversalArbitrageGraph
```

For Sui:
```text
Sui source envelope
      ↓
SuiResearchAdapter
      ↓
ResearchRelation
      ↓
ResearchEconomicGraph
      ↓
Sui VerificationRequest
      ↓
gRPC/GraphQL exact state (future within GPR-03)
      ↓
Sui shadow exact result
```

There is no direct Sui-to-Solana executable graph edge.
