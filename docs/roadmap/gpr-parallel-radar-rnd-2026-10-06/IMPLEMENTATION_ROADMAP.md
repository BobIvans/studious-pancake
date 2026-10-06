# IMPLEMENTATION ROADMAP

## GPR-00 — Base-stack hardening gate

Before adding new sources, re-check unresolved review threads from PR #569/#570. Fix only findings that remain real. Required: evidence cannot be lost after physical reads, credentials cannot escape via derived context, replay fails closed on missing evidence, and readiness cannot PASS on unusable schemas.

Stop if the base stack is not trustworthy.

## GPR-01 — Research Economic Graph + Verification Queue (NEXT IMPLEMENTATION PR)

This is the next code PR.

Implement:
- chain-neutral `ResearchAssetRef`, `ResearchMarketRef`, `ResearchRelation`;
- adapter from QPR-03 Solana candidates/envelopes;
- `ResearchEconomicGraph`;
- deterministic relation identity/dedup;
- CandidateScore with decomposed features;
- `VerificationRequest` and bounded priority queue;
- placeholder asset registry loader;
- relationship materializer using the symbolic universe;
- hard guard: unresolved placeholders can exist in research graph but can never be promoted into exact graph;
- evidence references back to QPR campaign journal.

Do NOT integrate all providers in this PR. Use fake/fixture providers plus existing QPR-03 sources to prove the graph.

Acceptance:
- QPR-03 indexed data can rank candidates;
- zero new indexed data reaches `UniversalArbitrageGraph`;
- relation generation is deterministic;
- 330 symbolic relationships load without any mint address;
- unresolved assets are blocked from verification requiring canonical ids;
- replay produces same graph identities and scores.

## GPR-02 — Solana Parallel Radar + Dual Quote Preview

Implement source adapters in this order:
1. Meteora DLMM indexed API — 30 RPS documented, pool pages up to 1000.
2. 0x Solana quote preview — ~5 RPS free/standard.
3. Jupiter quote preview — free unlimited usage but 1 RPS general limit.
4. Sanctum LST quote-only adapter — targeted structural anchor.
5. optional OpenOcean — 2 RPS, correlation-tagged Jupiter+Titan meta route.
6. optional Vybe — 60 RPM/25k credits for parsed references.

Create provider-specific token buckets and a scheduler that spends cheap/high-throughput calls first.

Suggested funnel:
```text
DEX Screener + Meteora + Raydium + Gecko (+ Vybe)
 -> ResearchEconomicGraph
 -> heat/anomaly trigger
 -> 0x
 -> Jupiter
 -> Sanctum if LST
 -> OpenOcean/OKX only for selected comparisons
 -> QPR-02 exact RPC verification
```

Build `QuotePreviewProvider`; do not build a sender.

## GPR-03 — Sui Shadow Research Plane (parallel branch after GPR-01)

Sui can be developed in parallel with GPR-02 once GPR-01 identity/graph contracts are stable.

Implement:
- Sui `ResearchAssetRef` canonical-id placeholder type (coin type unresolved initially);
- Aftermath adapter with provider cap 1000/10s documented, engineering cap lower;
- Cetus pool/tick reference adapter;
- Sui gRPC/GraphQL read-only transport abstraction;
- checkpoint/object-version provenance;
- adapter to existing `src/multichain/sui.py` state/PTB types where useful;
- DeepBook/Cetus exact-state qualification only when the required object semantics are proven.

Do NOT add a new JSON-RPC dependency.
Do NOT create a live PTB executor/signer.

Initial Sui funnel:
```text
Aftermath router
 + Cetus direct reference
 + Sui checkpoint/object state
 + DeepBook reference
 -> ResearchEconomicGraph
 -> Sui VerificationRequest
 -> exact-state shadow result
```

## GPR-04 — Heat Scheduler / Rolling Universe

Consume the 330 seed pair relationships and dynamic route generators.

Tiers:
- HOT: continuous/event-driven cheap radar
- WARM: frequent cheap radar
- COLD: batched indexed scans
- EVENT: wake only on market/volume/route/pool events

Features:
- promotion/demotion from observed evidence;
- per-provider quotas and credits;
- per-chain worker budgets;
- top-K verification queue;
- staleness/correlation penalties;
- no polling loop per symbolic pair.

## GPR-05 — TON High-Throughput Research Laboratory

Use STON.fi DEX API (official docs currently state no rate limits) with a self-imposed campaign cap. Build markets/pools/swap-simulation research relations. Keep TON research-only; do not claim Solana-style atomic flash execution.

## Later evidence-driven PRs

Only after campaigns:
- exact Meteora/Orca/Manifest/Raydium decoder priorities from observed opportunity frequency;
- Token-2022 semantics where actual candidates require it;
- Sui DeepBook/Cetus financing/execution qualification if evidence warrants;
- cost/financing/priority-fee layers;
- live execution authority only in a separately approved production phase.
