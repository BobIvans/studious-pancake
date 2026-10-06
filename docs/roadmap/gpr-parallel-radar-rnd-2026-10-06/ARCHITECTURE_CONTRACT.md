# ARCHITECTURE CONTRACT — GPR V2

## 1. Preserve the two-graph boundary

### ResearchEconomicGraph

May contain observations and relationships that rank **verification work**:

- discovery market;
- router quote preview;
- reference/oracle price;
- protocol redemption/exchange rate;
- LST/LRT/staking relation;
- vault/basket/JLP NAV;
- orderbook/AMM reference;
- financing capacity;
- cost/funding signal;
- economic-equivalence / bridge-representation relation;
- cross-chain basis observation;
- event;
- exact-state reference.

### UniversalArbitrageGraph

Remains the chain-local exact/executable shadow graph. Entry requires canonical exact state and existing `MarketObservationV2`/binding rules.

No research relation promotes itself.

## 2. Ontology

```text
EconomicAsset
  economic_asset_key

Representation
  representation_id
  economic_asset_key
  chain
  canonical_id
  standard
  representation_kind
  verification_status
  identity_generation

VenueState
  chain
  venue/program
  market/object/pool identity
  state generation / slot / checkpoint

Transformation
  source_representation
  target_representation
  transformation_kind
  evidence
  atomicity_domain
```

The same human ticker must never imply identity equality.

## 3. Identity status gates

Supported research statuses:

- `RND_VERIFIED_CURRENT`
- `RND_VERIFIED_SPECIFIC_REPRESENTATION`
- `REVALIDATE_CURRENT`
- `REVALIDATE_ISSUER_STATUS`
- `UNRESOLVED`

Rules:

- all statuses are `runtime_enabled=false` by default;
- R&D verification may permit graph observation, never exact execution;
- `REVALIDATE_*` cannot cross into exact verification without a fresh identity receipt;
- `UNRESOLVED` cannot produce a canonical request;
- a Token-2022 identity may still be blocked by unqualified extension semantics.

## 4. Research identities

Add chain-neutral research owners above, not instead of, QPR-03 Solana Candidate.

Suggested types:

```text
ResearchAssetRef
ResearchRepresentationRef
ResearchMarketRef
ResearchRelation
ResearchEvidenceRef
```

QPR-03 Solana candidates adapt into this layer without weakening Solana pubkey/program checks.

## 5. Representation relations

Research graph may model:

- same economic asset / different chain;
- same economic asset / different bridge representation;
- issuer equivalence;
- protocol redemption;
- wrapper parity;
- LST/LRT underlying;
- NAV/share relationship.

These are relations between representations, not free conversion assumptions.

## 6. Cross-chain edge classes

The initial non-atomic edge taxonomy is:

1. `ISSUER_EQUIVALENCE`
2. `NATIVE_BURN_MINT`
3. `LOCK_MINT_BRIDGE`
4. `ECONOMIC_UNDERLYING`
5. `PROTOCOL_REDEMPTION`
6. `INVENTORY_REBALANCE`

Every one has `atomicity_domain = RESEARCH_ONLY_NON_ATOMIC` unless a future separately qualified mechanism proves otherwise.

## 7. CandidateScore

CandidateScore is a scheduling score, not profit:

```text
+ inter_source_divergence
+ structural_anchor_deviation
+ route_topology_change
+ liquidity_change
+ volume_acceleration
+ orderbook_amm_gap
+ oracle_market_gap
+ representation_basis
+ cross_chain_basis
+ historical_recurrence
+ size_convexity
- source_correlation_penalty
- staleness_penalty
- unresolved_identity_penalty
- rebalance_latency_penalty
```

## 8. VerificationRequest

Top relations produce a bounded request with:

- chain/domain;
- relation id;
- full representation identities;
- identity verification statuses;
- suspected venues/pools/objects;
- amount grid;
- required accounts/objects;
- independent-provider requirement;
- evidence refs;
- score decomposition;
- request budget;
- expected atomicity domain.

Solana exact requests reuse QPR-02.
Sui exact requests require governed checkpoint/object state.
Cross-chain requests cannot promote into the atomic graph.

## 9. Parallel source scheduler

One async scheduler with provider-specific budgets:

- provider rate descriptor;
- campaign safety cap;
- batch width;
- period/credit budget;
- chain priority;
- correlation group;
- failure/backoff policy;
- deterministic ordering.

Do not sum correlated provider limits into fake evidence independence.

## 10. QuotePreviewProvider

Read-only interface:

- `quote_exact_in`;
- optional `quote_exact_out`;
- amount/input/output;
- route fingerprint;
- provider fees;
- price impact;
- source time;
- request/response hashes;
- raw evidence ref;
- correlation metadata.

It cannot sign/send/submit.

Solana:
1. 0x
2. Jupiter
3. Sanctum specialized LST
4. optional OpenOcean comparator

Sui:
1. Aftermath router
2. direct Cetus/DeepBook research/state path

## 11. Structural transformation graph

The research graph should eventually support transformations beyond swaps:

```text
swap
stake
unstake / instant-exit
redeem
mint
wrap / unwrap
borrow
flash-borrow
supply
NAV conversion
bridge/rebalance reference
```

Atomic search remains chain-local. Cross-chain transformation cost belongs to later prefunded/rebalance simulation.

## 12. Sui transport

New Sui exact-state work uses gRPC/GraphQL/checkpoint/object provenance. Do not introduce a new legacy JSON-RPC dependency.

Reuse `src/multichain/sui.py` PTB/object semantics where useful, but the offline model alone grants no live authority.
