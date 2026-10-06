# ARCHITECTURE CONTRACT

## 1. Preserve the two-graph boundary

### ResearchEconomicGraph
May contain:
- discovery market
- router quote
- reference price
- oracle price
- redemption / LST exchange-rate anchor
- NAV/share relation
- orderbook reference
- financing capacity
- cost signal
- CEX/reference impulse
- event
- exact-state reference

It ranks **verification work**, not profit.

### UniversalArbitrageGraph
Remains the exact/executable shadow graph. Entry requires canonical exact state and existing `MarketObservationV2`/binding rules.

There must be no automatic promotion from the research graph.

## 2. New chain-neutral identities

Introduce a separate layer instead of weakening the current Solana `Candidate` validation:

```text
ResearchAssetRef
- chain
- symbolic_key
- canonical_id?           # absent until qualified
- decimals?
- token_standard?
- identity_generation
- status: PLACEHOLDER | RESOLVED | QUALIFIED

ResearchMarketRef
- chain
- market_id?              # may be absent for router-only relation
- venue
- asset_a
- asset_b
- source_id
- correlation_group

ResearchRelation
- relation_id
- relation_kind
- asset refs
- source provenance
- observed_at
- source_time/checkpoint/slot if available
- amount/input/output when amount-specific
- liquidity/volume signals when available
- route topology fingerprint
- response hash/request fingerprint
- quality
```

QPR-03 Solana `Candidate` is adapted into this layer; it is not replaced.

## 3. Candidate score

CandidateScore is a scheduling score only:

```text
+ inter_source_divergence
+ structural_anchor_deviation
+ route_topology_change
+ liquidity_change
+ volume_acceleration
+ orderbook_amm_gap
+ oracle_market_gap
+ historical_recurrence
+ size_convexity
- source_correlation_penalty
- staleness_penalty
- missing_identity_penalty
```

No profit claim may be created here.

## 4. Verification queue

Top relations produce `VerificationRequest` with:
- chain/domain
- candidate/relation id
- asset ids/status
- suspected venues/pools
- amount grid
- required state objects/accounts
- required independent provider count
- evidence refs
- reason/score decomposition
- request budget ceiling

Solana requests enter QPR-02 RPC quorum/native exact path.
Sui requests enter a new read-only gRPC/GraphQL exact-state path only when that path exists.
TON remains research-only in this wave.

## 5. Parallel source scheduler

One async scheduler, independent source token buckets:
- provider limit descriptor
- campaign safety cap
- batch width
- monthly/period credit budget
- per-chain priority
- correlation group
- failure/backoff policy
- deterministic work ordering

Do not calculate a fake global RPS by summing correlated providers. Quotas are a scheduling resource, not evidence quality.

## 6. Read-only quote preview interface

`QuotePreviewProvider`:
- `quote_exact_in`
- optional `quote_exact_out`
- returns normalized amount, route fingerprint, provider fees, price impact, source time, request/response hashes, raw evidence ref
- cannot sign, send, submit or create production authority

Solana implementations:
1. 0x
2. Jupiter
3. optional OpenOcean
4. Sanctum specialized adapter

Sui implementations after shared graph:
1. Aftermath router
2. direct Cetus/DeepBook preview/state adapter

## 7. Correlation rules

Examples:
- OpenOcean Solana -> correlation group includes Jupiter/Titan meta-routing.
- Sanctum `swapSrc=Jup` must not be counted independently from Jupiter.
- two RPC URLs from same operator/correlation group do not satisfy independent quorum.
- two route providers using the same underlying pool may disagree in fees but are not independent liquidity.

## 8. Sui transport

New Sui work must prefer gRPC/GraphQL. Official Sui docs state Foundation Mainnet JSON-RPC was disabled in July 2026 and is being removed. Reuse the existing `src/multichain/sui.py` PTB/object semantics, but do not grant execution authority from the offline model alone.
