# DATA_INTEGRATION_PLAN — real external data → evidence graph → exact qualification

**Stage:** DIN-00..DIN-07, only **after** RCN-00 reconciliation. **Chains:** Solana P0 and Sui P1 in parallel after common contracts; TON deferred to optional read-only radar. **Scope:** read-only discovery, quotation, direct state verification, unsigned build/simulation and paper economics. **Out of scope:** private-key handling, signing, sending, live flash borrowing, production promotion.

## 1. Two critical optimization principles

**Spend free indexer budget broadly; spend API quote/RPC budget narrowly.** Cheap searchable/batch resources discover promising edges and dynamics; high-fidelity quote, independent direct-chain state and simulations validate just a bounded candidate queue. Never assume a DEX Screener price or a successful quote equals an executable arbitrage.

**Extend existing owners, not a second market-data system.** The repo already has QPR SourceDossier / ProviderProfile / governed SourceIntakePlane, GPR ResearchEconomicGraph + VerificationQueue, MarketObservationV2, ShadowMarketGraphIngest, existing AGG-02 raw journal / analysis dataset / replay, PR #576 Dynamic Universe, relation generators, correlation ledger and FlashCapitalGraph. Add typed adapters through these ports, leave proof owners unchanged.

## 2. Canonical data-plane

```text
P0 SourceCatalog + versioned ProviderProfile + entitlement/budget
    ├── Registry and direct venue metadata (asset/pool/book identity)
    ├── Broad public indexers (DEX Screener, GeckoTerminal, Raydium, Meteora)
    ├── Venue-specific books/feeds (Manifest, DeepBook, Cetus...)
    └── Optional oracle/CEX/webhook *research* context
          │  raw payload hash + bounded transport outcome + negative evidence
          ▼
P1 SourceIntakePlane / outer cross-chain ResearchAdapter
          │  chain_id, program/package, mint/type, pool, representation,
          │  operator/correlation group, retrieval time, block context
          ▼
P2 Dynamic Universe + Asset Resolver + Economic Research Graph
          │  normalized identity, de-duplicated markets, relation generators,
          │  shared-liquidity aliases, heat score, candidate ranking
          ▼
P3 VerificationQueue + cost-aware adaptive quota scheduler
          │  prioritize only actionable, sufficiently fresh candidates
          ├── P4a Solana 0x/Titan/Jupiter quotes (compare OpenOcean/OKX/Rango)
          └── P4b Sui Aftermath/Cetus/7K/FlowX/DeepBook quotes/PTB plans
          │  retain losing and failed quotes; no false independence
          ▼
P5 Direct-state verification
          ├── Solana: QPR-02 independent rooted RPC, exact mint/pool/fees
          └── Sui: independent checkpoint/object via gRPC/GraphQL
          │  reject mismatch, obsolete slot, unreviewed Token-2022/Move type
          ▼
P6 Existing MarketObservationV2 / shadow graph exact ownership
          │  unsigned instruction/PTB build + dry-run simulation (feature-gated)
          ▼
P7 Paper sizing (PR118), flash-capital constraints, full costs,
   reconciliation, replayable evidence + 24h Qualification Campaign
```

A single HTTP 200 is evidence of a **transport response**, not approval of source freshness, decoder semantics, or executable truth. All levels preserve typed reason codes and negative observations.

## 3. Identity, schema and correlation requirements

An adapter must emit a canonical governed envelope (directly reuse/extend existing models, do NOT create a competing owner):
- `chain_id`, `source_id`, `provider_id`, `operator_id`, `dependency_id`, `correlation_group`, `schema_version`, `source_generation`, `quota_generation`.
- `asset_id` / `representation_id`, verified mint or Move type, token program/package version, decimals, observed pool/book/account IDs, independent source of identifier.
- `observed_at` (provider time, if any), `received_at`, slot/commitment/blockhash or Sui checkpoint/object version/digest, staleness threshold per use case. Never compare mismatched time frames as if simultaneous.
- `request_fingerprint`, `raw_sha256`, response-size bytes, status, admitted physical call count, auth class, entitlement, `failure_reason`, immutable journal reference.
- `price` and amounts as bounded integer base-units or exact decimals, not binary float for trade math; side, source denomination, fees, route hops, pool liquidity and executable size.
- `proof_class`: indexed discovery / authenticated quotation / exact independent state / simulation / paper; untrusted sources never grant themselves a higher class.
- provider correlation: OpenOcean Solana references Jupiter + Titan; routes obtained via 7K/FlowX/etc may share Cetus/Aftermath/DeepBook liquidity. Correlated answers can improve price selection but **cannot form independent state quorum**.

Use provenance-aware dedup IDs: `chain|economic asset + representation|venue|pool/book identity|direction|source generation|time bucket`. Keep every raw failure, retry receipt and losing quote separately. Registries with symbolic identities never silently hard-bind by ticker. Preserve tombstones/history when live identifiers change. Join Solana/Sui only through non-atomic *research* relations.

## 4. Source priorities for minimal cost

### Solana P0 — five bounded steps

1. **Bootstrap identity and pool inventory:** resolve WSOL, USDC, USDT, core LSTs/stables/NAV assets with existing PR #576 resolver and on-chain identity proofs. Use pre-existing GPR first campaign families, not a new hard-coded 160-pair list. Quarantine unresolved Token-2022 extensions.
2. **Public wide radar:** DEX Screener batch token/pair, GeckoTerminal reference, Raydium pools, Meteora DLMM pools. Add Manifest book market identity and Orca Whirlpool / Sanctum context after schema review. Compare `pairAddress`, executable venue, freshness and known token mint owners; indexer pool prices are **research** only.
3. **Selection and event heat:** dedupe same pool through different indexers; classify spread/structural parity/LST/stable/NAV/direct-vs-synthetic/cross-venue signals. Keep a rolling dynamic active universe (e.g. target 120–160 **tracked** pairs when inventory supports it) but do not generate 160 unconditional quote loops. A queue schedules high-priority candidates first.
4. **Quote/build test race:** existing GPR-02 0x and Jupiter as baseline; Titan additional independent router lineage; OpenOcean comparison (Jupiter+Titan-correlated), OKX and Rango optional gated integrations. Provider keys and whitelists first; record supported mint/amount/route instructions/fees and observed rate caps. Every losing quote retained. Never send private keys to providers. Quoted route must match the same intended input amount, token programs and time horizon for fair comparison.
5. **Exact verification:** QPR-02 distinct operator rooted snapshot of pool/mint state, approved AMM math, fee tiers and transfer semantics; reject stale or inconsistent state. Then unsigned transaction assembly and simulation with realistic account/rent/compute/Jito-tip estimates only in allowed offline or read-only modes.

Prioritize native Solana flash-capital feasibility **after** exact opportunity has been measured: Project 0 dynamic bank inventory/status, deposit-only tag exclusion, usable borrow capacity and fee; Kamino reserve-specific limits and construction. P0 fee may be zero, **but compute/rent/tips/slippage are not**. Slumlord is rent finance only, future explicit gated work, not trading flash capital.

### Sui P1 — genuinely parallel research, separate truth path

- Begin with DeepBook known pools/books, Cetus active pools/quotes, Aftermath targeted router/pool discovery, Scallop rate context. PR #573 already records a bad DeepBook `/all_pools` guess (fixed to official `/get_pools`), corrected Cetus response shape, Scallop host/encoding and Aftermath oversized responses. **Reuse those negative fixtures.**
- Dynamic Universe resolver proves full Move type, package and representation identity; avoid ticker matching and silent JSON-RPC fallback. Sui Foundation Mainnet JSON-RPC is disabled since July 2026. Use reviewed gRPC and GraphQL (separate provider/operator where possible) for checkpoint-object exactness.
- Later provider race: Aftermath, Cetus Aggregator, DeepBook direct first; then 7K/Bluefin7K, FlowX, OKX, Rango where SDK endpoint and provider lineage are pinned. Track nested routing overlap. Reject SDK routes that secretly require disabled legacy JSON-RPC.
- Flash capital: NAVI asset/mint type and max/fees, DeepBook pool-specific loan constraints, Scallop fee/capacity; include gas/PTB atomics and object-version conflicts. No assumption a Sui quote is Solana-style LOCAL_ATOMIC across chains.

### Optional slow/trigger/reference lanes

- Authenticated Pyth Hermes (since 2026-08-26 requires API key), optional Switchboard and issuer/NAV feeds; oracle is **reference context** and may be lagged.
- Solana websocket/account subscriptions / Helius or other permitted streams/webhooks: use for trigger/changes, not as stand-alone exact proof; capture reconnect/gap/backfill receipts. Do not depend on a temporary public tunnel for critical long-running campaign.
- CEX book streams (Binance/Coinbase/Kraken etc.) for lead/lag research only; no cross-CEX instant flashloan assumption. CoinGecko/DefiLlama and low-frequency ecosystem registries as slow baselines.
- TON STON/Omniston/etc. only optional research. Do not prioritize until Solana+Sui QPR/GPR qualification is reproducible; TON transfers are not reclassified as local flashloan atomics.

## 5. Scheduling without abusing free endpoints

- One `ProviderGovernance` physical admission per actual wire call; quota scope by **real dependency/operator** (not fake independent keys or aliases). Source schema generation and shared quota generation have distinct IDs.
- Configurable token buckets per provider/plan/endpoint, `Retry-After` and bounded exponential backoff with jitter, circuit breaker for repeated 429/403/5xx/schema-drift; zero retry storm. Safe jitter can be deterministic under replay.
- No arbitrary claimed 'unlimited' throughput: some sources have no published daily cap, but **minute limits, fair-use policy, key trial duration, IP ban risk and route costs still bind**.
- Indexed batches + TTL and cache by mint/pool/version; no request-on-every-block for cold pairs. Feed event triggers to `VerificationQueue`. Bounded concurrency by group, global time budget, byte/node caps and sorted prioritization.
- On budget exhaustion **record BLOCKED_BUDGET and defer**; never silently skip and report `PASS`. On price/route staleness, reissue new normalized request within remaining entitlements rather than reusing invalid old evidence.
- Per-source physical attempts and allowed quota should be visible in campaign report, alongside `429`, source availability, schema drift, auth success/failure, negative receipts and useful yielded candidates per 100 calls.

## 6. Security and provider onboarding

For each source: add a reviewed official endpoint+docs digest/SDK release pin, SourceDossier, ProviderProfile with `operator_id`, `credential_ref`, entitlement and allowed methods/paths; deterministic fixtures; bounded real smoke read; compare decoded example against exact identity; then admit to campaign config. `PROVIDER_CATALOG.json` is **planning inventory only**; do not auto-execute all entries.

Secrets: `JUPITER_API_KEY`, `ZEROX_API_KEY`, `PYTH_API_KEY` via existing `FLASHLOAN_PYTH_API_KEY_REFERENCE`, plus provider-specific keys **only after official registration**. Store secrets in local OS/env/CI secret manager. Never echo keys, token headers, signed payloads, seed phrases, wallet files, or private endpoints in journal, logs, issues, PRs or AI chat. No signer/submission modules in this wave; keep `sign_enabled=false`.

## 7. Paper qualification report and stop lines

Campaign sampling must be replayable under stable provider/profile generations and exact base/source refs. Initially deterministic fixtures; then bounded real smoke; then 24h observation (or a shorter diagnostic explicitly named as such). Metrics:
- Sources attempted/accepted/rejected, rate-limit and auth outcomes, provenance and operator independence.
- Inventoried live assets, resolved identities/ambiguities, active markets and data freshness distributions.
- Candidate edges and families, matched quotes per amount/slot, exact-state quorum counts, rejected reasons and simulation consistency.
- Net executable **paper** return after venue fees, AMM transfer effects, gas/priority fees, flash borrow fee/capacity, rent/sponsor and expected failed-trade cost; sensitivity bands and confidence, not guaranteed profit.
- Negative and disagreement evidence, quota costs per candidate, coverage holes and next provider onboarding needs.
- Gate outcomes separately: `READ_ONLY_REAL_DATA_CAMPAIGN_V1`, independent QPR exact checks, `PAPER_QUALIFIED`, `PRODUCTION_PROMOTION=false`.

**Hard stop** on stale identities, unsupported token extensions, insufficient independent state, provider correlation confusion, missing auth, estimated profits without exact consistent amount/size, unreviewed flashloan protocol constraints, or any signer/send request.
