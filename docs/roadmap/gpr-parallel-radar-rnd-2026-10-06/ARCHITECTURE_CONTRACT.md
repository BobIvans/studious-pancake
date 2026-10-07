# ARCHITECTURE CONTRACT — GPR V2.1

## 1. Two graph boundary

### ResearchEconomicGraph
May contain discovery, quote preview, structural anchors, representation basis, NAV, oracle, financing/cost and cross-chain signals.

### UniversalArbitrageGraph
Remains chain-local exact/executable shadow evidence only.

No research relation promotes itself.

## 2. Asset identity

```text
AssetIdentity
  asset_id
  chain
  canonical_identifier
  token_program_or_move_type
  decimals
  economic_asset
  representation_kind
  origin_chain?
  bridge?
  issuer?
  verification_state
  verification_sources[]
  identity_generation
```

Identity is representation-specific.

Examples that must never alias:
- USDC_SOL_NATIVE
- USDC_SUI_NATIVE
- WUSDC_ETH_ORIGIN on Sui
- USDC_SOL_PORTAL_ON_SUI

and:
- SOLANA_xBTC_OKX
- SOLANA_cbBTC
- SOLANA_WBTC_WORMHOLE
- SOLANA_tBTC

## 3. Identity proof states

Registry statuses remain research-level identity governance:
- RND_VERIFIED_CURRENT
- RND_VERIFIED_SPECIFIC_REPRESENTATION
- REVALIDATE_CURRENT
- REVALIDATE_ISSUER_STATUS
- UNRESOLVED

Relation evidence uses a separate lifecycle:
- DISCOVERY_ONLY
- IDENTIFIER_VERIFIED
- RPC_VERIFIED
- EXECUTABLE

Do not conflate registry status with relation evidence state.

## 4. Mandatory relation classification

Every ResearchRelation has independent:

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

Rules:
- HOT does not mean executable.
- LOCAL_ATOMIC means topology could be chain-local atomic if verified; it does not grant authority.
- LOCAL_SIGNAL is analysis/reference until promoted.
- CROSS_CHAIN_SIGNAL never enters local atomic route search.
- REBALANCE_ONLY is transport/inventory accounting, never an atomic trade edge.

## 5. Structural anchors

ResearchRelation can carry:

```text
anchor_type:
  USD_REDEMPTION
  STAKING_EXCHANGE_RATE
  NAV
  SAME_UNDERLYING
  BRIDGE_PARITY
  ORACLE_REFERENCE
```

Multiple anchors may coexist.

## 6. HARD_BOUND startup receipt

Before any identifier is accepted for exact use, produce chain-state evidence for:
- canonical identifier;
- owner/program or Move type;
- decimals;
- token standard/extensions;
- issuer/bridge representation if material;
- deprecation/replacement status;
- campaign/repository generation.

Token-2022 identities such as renewed USDG/PYUSD or other extension-bearing assets remain blocked until relevant semantics are qualified.

## 7. ResearchRelation shape

At minimum:

```text
relation_id
relation_class
representations[]
heat
execution_class
evidence_state
anchor_types[]
direct_venues[]
known_pool_or_book_ids[]
synthetic_paths[]
observed_at
slot/checkpoint/source_time?
source/provenance refs[]
request/response hashes
correlation_group
staleness
quality
```

## 8. CandidateScore

Scheduling only, not profit:

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

## 9. VerificationRequest

Top relations produce bounded chain-specific verification work.

Solana:
`VerificationRequest -> QPR-02/direct state -> MarketObservationV2 -> exact graph`.

Sui:
`VerificationRequest -> governed gRPC/GraphQL checkpoint/object state -> Sui shadow exact evidence`.

Cross-chain:
verification may strengthen a signal but never promotes the bridge relation into UniversalArbitrageGraph.

## 10. DeepBook pool identifiers

`SUI_DEEPBOOK_POOLS_V2_1.json` provides 9 read-only seed pool IDs.

These IDs are implementation-ready identifiers for research onboarding, not proof of current depth, fee semantics or checkpoint state.

## 11. Parallel source scheduler

One scheduler with provider-specific token/credit budgets and deterministic work ordering.

Prioritize cheap radar. Do not spend RPC/quote budgets uniformly over all symbolic relations.

First high-value seed is `FIRST_CAMPAIGN_FAMILIES_V2_1.json`.

## 12. QuotePreviewProvider

Read-only interface retains:
- exact input/output amount;
- route fingerprint;
- provider fee/impact;
- request/response hashes;
- source time;
- raw evidence ref;
- correlation metadata.

Cannot sign/send/submit.

Solana: 0x, Jupiter, Sanctum, optional OpenOcean.
Sui: Aftermath plus direct DeepBook/Cetus research/state paths.

## 13. Transformations

Research graph may model:
- swap
- stake/unstake/instant exit
- redeem/mint
- wrap/unwrap
- borrow/flash-borrow/supply
- NAV conversion
- oracle reference
- bridge/rebalance reference

Atomic search remains chain-local.

## 14. Safety

No live authority is granted by registry identifiers, pool IDs, heat labels or router quotes.
