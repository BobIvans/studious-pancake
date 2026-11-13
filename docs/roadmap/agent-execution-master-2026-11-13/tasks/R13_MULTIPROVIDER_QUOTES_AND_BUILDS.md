# Assignment — R-13 multi-provider quote / build race (Solana + Sui)

**Purpose:** broaden quote/build coverage without creating a parallel quote plane or transaction kernel. This lane can run concurrently with R-02 readers, R-03 offline builder work, strategy research and source documentation, subject to canonical-owner collision rules.

## Before coding
Read:
- docs/roadmap/universal-source-execution-rnd-2026-10-07/EXECUTION_BUILDER_CONTRACT.md
- docs/roadmap/universal-source-execution-rnd-2026-10-07/IMPLEMENTATION_ROADMAP.md
- docs/roadmap/universal-source-execution-rnd-2026-10-07/CODEX_START_HERE.md
- docs/roadmap/p0-offline-execution-master-2026-11-13/tasks/P0-2_JUPITER_0X_QUOTES.md
- current quote/market owners, QPR/DIN governance, provider catalog and R-02/R-03 evidence contracts.

Treat QuoteProvider, NormalizedQuote, ProviderCorrelation, TransactionBuilder and UnsignedExecutionPlan in the existing dossiers as documented contracts to verify against current code. Do not claim a class or runtime integration exists from a document alone.

## Provider work packages

### Solana quote race
Candidates: 0x, Titan, Jupiter, OpenOcean, OKX DEX and Rango.

Start with the already assigned P0-2 Jupiter V2 + 0x pair. Then add comparator/build providers one at a time only after their current official API/SDK/auth/limit/build contracts are pinned.

- Jupiter: existing GPR-02 quote owner migration to Swap API V2; do not add another Jupiter adapter. Keep Jupiter 1 RPS/plan entitlements in a per-provider bucket and do not serialize unrelated providers behind it.
- 0x: exact POST /solana/swap-instructions quote/build contract; public taker only, secret-ref API key, explicit sponsor/payer capability and signer requirements.
- Titan: verify V3 quote/build/payer semantics and current quota/response contract.
- OpenOcean, OKX DEX, Rango: verify whether each returns an economic quote, composable instruction set, unsigned transaction or route reference. A route URL is not an instruction bundle.

### Sui quote/PTB race
Candidates: Aftermath, Cetus Aggregator, 7K/Bluefin7K, FlowX, OKX DEX, Rango and direct DeepBook.

- Use current governed Sui gRPC/GraphQL/checkpoint transport; no legacy Sui JSON-RPC fallback.
- Resolve exact full Move coin types, package IDs, shared/owned object IDs, decimals and checkpoint/object version.
- Distinguish a quote response from composable Transaction/PTB commands and from a fully built unsigned transaction.
- Do not assume that an aggregator route is a direct executable Move call or that every builder can compose with another provider's PTB.

## Normalization and evidence rules

For every quote/build response preserve:
- chain/genesis and exact canonical input/output representation IDs;
- exact-in/exact-out mode and amount in base units;
- public taker/authority mode (never private material);
- provider, provider generation, operator and correlation group;
- underlying DEX venues, pool IDs and route topology when actually returned;
- in/out amounts, fees, impact, slippage, price limits, account/object constraints;
- provider timestamp, actual slot/checkpoint only when supplied, expiry and freshness window;
- raw response hash, request fingerprint, source pin and typed negative/error outcome;
- build mode: quote-only, instruction bundle, unsigned Solana message, composable Sui PTB or opaque route reference;
- signer, payer, rent sponsor, ALT, account setup and co-sign requirements as explicit metadata.

Comparisons require identical canonical representations, exact same input base-unit amount, compatible taker and fee assumptions, and bounded time skew. Never scale a quote to a different amount; re-quote every amount used by the nonlinear sizing owner. Preserve losing quotes. Two aggregators routing to the same pool are correlated observations, not two independent liquidity sources.

## Integration boundaries
- Reuse current src/solana_parallel_radar/, src/gpr_sui_shadow/, provider governance, quote normalizers, source journal, replay and VerificationQueue.
- Extend the current QuoteProvider/TransactionBuilder owner only after code audit and one frozen interface contract.
- Reuse R-03 unsigned plans and exact simulation contracts; R-13 does not sign, send, borrow or claim an executable route.
- Do not edit the same canonical quote owner concurrently with P0-2. Split by provider adapters/fixtures or let one agent own that shared file.

## Acceptance
- One source-pinned dossier per provider/version with license, auth, quotas, endpoint, exact schema, units, fee, error, freshness and build semantics.
- Positive/negative/schema-drift fixtures and socket-disabled deterministic replay.
- Explicit correlation groups and underlying pool dedup; no aggregator double count.
- Current live captures only under separate bounded opt-in command; retain raw hashes and negative evidence.
- Review-only PR per provider or coherent adapter pair; actual tests, exact base/head SHA, blockers and source provenance.
- sign_enabled=false, send_enabled=false; provider-specific builder output remains unsigned and inert.
