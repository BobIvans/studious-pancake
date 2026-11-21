# CODEX START HERE — CLMM/DLMM exact-state + multi-source market tracing

**Зависимость:** PR #659 (R10-1 CPMM exact route binding). На момент создания этого assignment PR #659 открыт и не объединён. Не реализовывать CLMM/DLMM binding до merge #659: сначала проверить его финальный head и CI, затем обновить эту ветку от актуального main и повторно проверить owner map.

**Ветка assignment:** codex/clmm-dlmm-market-trace-qualification-2026-11-15  
**main при создании:** 731915149365d7b31f5f93deb1b08e894372b0f8  
**Область:** продолжение уже существующего market-data / route / capital / paper pipeline. Strategy expansion остаётся на паузе.

## 0. Цель и граница готовности

Довести Raydium CLMM и Meteora DLMM от offline decoder/state boundary до **amount-specific, replayable direct quotes**, а затем включить эти quotes в уже существующий canonical path:

discovery → verified identity → coherent rooted state → exact venue quote → canonical MarketObservationV2 → graph route → pool/resource dedup → PR118 size grid → all-in economics → lender/builder/simulation gates → sender-free paper evidence.

Это последняя крупная venue-model qualification работа перед отдельным controlled read-only API-capture campaign. Она **не** даёт live trading permission, не доказывает прибыльность, не включает signer и не означает, что внешние credentials уже установлены.

Критические результаты:
1. Raydium CLMM: полная зависимая account closure, включая TickArrayBitmapExtension + current DynamicFeeInfo/config state, exact swap step fees and full exact-in traversal.
2. Meteora DLMM: immutable source closure for quote math, full active/directionally reachable BinArray + bitmap extension + fee/volatility/clock/token-extension evidence, exact amount-specific quote with consumed input semantics.
3. Both direct venue evaluators are injected into the existing R10-1 route/observation owners from #659, not a new graph/solver.
4. A bounded read-only capture manifest enumerates every external source/API/RPC dependency, environment-variable NAME only, scopes/quotas, provenance and unresolved human prerequisites.
5. The existing Jupiter Lend CAP-A reader + R03 unsigned builder is connected to route qualification as a separate financing gate, but remains unqualified until real rooted capacity evidence and QPR gates pass.

## 1. Preflight and ownership reconciliation

Before editing:
- Read AGENTS.md, root CODEX_START_HERE.md, PROJECT_KNOWLEDGE_BASE_MAP.md, TASK_INDEX.md, MULTI_AGENT_EXECUTION_PLAN.md.
- Read PR #659 and its final merged commit if merged; inspect implementation report, src/strategy/cpmm_cycle_binding.py, tests and replay report.
- Read merged PRs #491 (MPR-2622), #507 (AGG-06), #512 (SUPER-03), #561 (bounded discovery + graph aggregation), #593 (P0-1), #604 (P0-2), #613 (P0-3) and #638 (R13-K).
- Read docs/integrations/offline/solana-p0/DIRECT_STATE_RAYDIUM_ORCA_METEORA.md, SOURCE_MANIFEST.json, VENDOR_SOURCE_MANIFEST.json, P0_3_REPORT.md, R07_PROVIDER_EXPANSION.md, R02_CAPITAL_READERS.md, R03_UNSIGNED_BUILDERS.md, R04/R05/R06, docs/shadow_market_sources_ru.md, docs/shadow_market_data_aggregation.md.
- Refresh main SHA, open PRs, branches, worktrees and current source pins. Do not trust snapshot SHA from the docs.
- PR #649 Curve LLAMMA, #655 MarginFi capital bridge and #657 strategy docs are separate lanes; do not overlap them.
- If PR #659 has not merged, do not re-implement R10-1. This branch may prepare docs/pins/tests, but before implementation rebase onto the merged #659 result and preserve its owner contract.

## 2. Canonical owners to reuse

| Concern | Canonical owner |
|---|---|
| Discovery and source catalog | src/market/discovery.py, src/market/source_catalog.py, src/resources/market_source_catalog.json, src/discovery/dynamic_universe/ |
| Provider governance and bounded transport | src/provider_governance/, src/qualification_campaign/, src/routing/transport.py |
| Radar and quote acquisition | src/solana_parallel_radar/, existing Jupiter V2 and 0x adapters / P0-2 |
| RPC evidence and observations | src/market/observations.py, src/market/streams.py, WatermarkedObservationBuffer, FanoutMatrix, DurableCursorStore |
| Asset identity | src/assets/resolution/, canonical registry; no symbol-to-mint guess |
| Native CPMM / CLMM / DLMM | src/providers/raydium_cpmm_native.py, src/providers/raydium_clmm_native.py, src/providers/meteora_dlmm_native.py |
| Venue capability/conformance | src/direct_venue/mpr2617.py, src/direct_venue/super03.py |
| Graph / route | src/strategy/market_graph_ingest.py, src/strategy/arbitrage_graph.py, src/strategy/multihop_solver.py, src/strategy/detectors.py, post-#659 cycle binding owner |
| Pool/route identity dedup | src/execution/quote_build_kernel.py (R13-K PoolIdentityDeduplicator) |
| Sizing / shared split resources | src/economics/non_monotonic_sizing.py (PR118), src/economics/split_flow.py (only after single-route exact qualification) |
| Financing / unsigned builder | src/economics/flash_capital_graph/, src/lending/jupiter_lend.py, src/lending/unsigned_builders/, R02/R03 |
| Simulation and paper | src/execution/exact_simulation.py, src/paper_shadow/, QPR/campaign/evidence owners |
| Signer and execution authority | Existing runtime/release authority only. No new signer service, key store, sender or authority gate in this PR. |

Do not add a second source catalog, REST transport, RPC quorum, graph, solver, quote kernel, observation store, journal, capital graph, scheduler, strategy registry or signer.

## 3. Raydium CLMM completion

### Existing verified baseline

Current canonical decoder is src/providers/raydium_clmm_native.py. It already decodes PoolState (1544 B), in-pool 1024-bit tick-array bitmap, TickArrayState (10240 B, 60 ticks × 168 B) and AmmConfig; it has integer Q64.64 exact-in traversal/math and fee-on direction handling. Source pin: raydium-io/raydium-clmm@6d7a0f82d2f293c553c69aaf943377367c6c4cc6, Apache-2.0.

The present decoder fails closed when:
- traversal crosses beyond in-pool bitmap and needs TickArrayBitmapExtension;
- DynamicFeeInfo is non-zero / cannot be interpreted;
- the current fee state or a required dependent account is absent;
- unsupported custom v2 seed index, account layout or token extension is present.

### Required completion

1. Mirror the minimum exact transitive upstream source closure from the same pinned commit into docs/integrations/offline/solana-p0/vendor-reference/raydium/clmm/ as inert reference text, with upstream path, commit, blob SHA, local SHA-256, license and retrieval date. At minimum re-evaluate and pin:
   - programs/amm/src/states/tickarray_bitmap_extension.rs
   - programs/amm/src/states/pool_fee.rs (contains DynamicFeeInfo, CollectFeeOn and fee-state semantics)
   - programs/amm/src/states/dynamic_fee_config.rs
   - programs/amm/src/instructions/swap.rs and/or swap_v2.rs where needed for exact remaining-account and fee update semantics.
   - Any dependency actually used by the dynamic fee path; compute and record the transitive closure rather than copying the whole repository.
2. Extend the existing decoder, never create a second CLMM provider:
   - Decode/validate TickArrayBitmapExtension owner, discriminator, exact length, pool binding, PDA and positive/negative bit ranges.
   - Traverse extension bitmap correctly across all required tick-array starts in swap direction; derive exact tick-array PDAs and fetch complete dependent arrays.
   - Decode all 80 bytes of PoolState DynamicFeeInfo, validate all fields and padding/version assumptions, and bind it to the pinned DynamicFeeConfig account/config if the program version requires it.
   - Reproduce current on-chain dynamic-fee update order (filter/decay/reference/volatility accumulator), formula, clamping, fee split and rounding. Bind Unix/block time, slot, epoch and config state to the observation. The online docs' formula is not by itself sufficient implementation proof; use the pinned deployed-source revision and differential vectors.
   - Preserve fee_on values 0/1/2 and all applicable trade/protocol/fund fees. Never assume the fee is always deducted from input.
   - Ensure full requested input is consumed; partial output / incomplete tick coverage is a typed rejection unless partial-fill is explicitly modeled and excluded from cycle promotion.
3. Add account dependency manifest for each quote: pool, AmmConfig, DynamicFeeConfig (when needed), TickArrayBitmapExtension (when needed), ordered tick arrays, mints, vaults, Token-2022 extension accounts and observation/clock dependencies as required by pinned version.
4. Quote output must contain amount in/out raw units, exact fee fields by denomination, ticks crossed, arrays used, final sqrt price/tick/liquidity, dynamic-fee provenance, consumed input, source slot/generation, raw account hashes, decoder/math revisions and rejection reasons.
5. Do not claim a dynamic-fee pool exact if any fee input or state transition is unknown. Unknown is not zero.

## 4. Meteora DLMM completion

### Existing verified baseline

Current canonical state owner is src/providers/meteora_dlmm_native.py. It decodes LbPair, BinArray (70 bins/array), bin bitmap extension, token X/Y, reserves, program/token flags and directionally reachable bin arrays. Amount-specific quote intentionally returns DLMM_AMOUNT_SPECIFIC_QUOTE_MISSING_PIN.

Existing offline SDK pin: MeteoraAg/dlmm-sdk@1532e540db41ac405dbf4c5bb2ddfceaa1f98ff1, @meteora-ag/dlmm 1.9.15, package metadata license ISC, IDL 0.12.0. Before code, compare against current official docs/release and retain this immutable historical pin as its own generation; never silently replace it with mutable main.

### Required source closure and quote work

1. Mirror only the minimal quote/math dependency closure from that commit into the existing vendor-reference/meteora/ path. The current repo has the SDK index, IDL, package metadata, binArray/lbPair/types and a quote example, but P0-3 did not mirror the helpers that determine exact quote behavior. Recheck and pin at minimum:
   - ts-client/src/dlmm/helpers/bin.ts
   - helpers/fee.ts
   - helpers/math.ts
   - helpers/u64xu64_math.ts
   - helpers/weight.ts
   - helpers/token_2022.ts
   - constants/index.ts
   - helpers/binArray.ts and helpers/derive.ts only if existing mirrors are missing/stale or the quote closure requires exact revisions.
   - Relevant imported types and the quote call site in ts-client/src/dlmm/index.ts.
   Record upstream path, commit, blob SHA, local SHA-256, package version, ISC license text/metadata, dependency closure and retrieval date. Do not vendor the full SDK or introduce it as an unreviewed runtime dependency.
2. Implement the amount-specific exact-in quote in the existing src/providers/meteora_dlmm_native.py using only the pinned closure:
   - directional getBinArrayForSwap(swapForY) semantics, starting activeId and bitmap/extension traversal;
   - active and each reachable bin's X/Y reserves, Q64 price, binStep, pair type/version, limit-order participation support or explicit fail-closed exclusion;
   - base fee, variable volatility fee, protocol share, fee caps, rounding and fee-on-input/output rules;
   - per-bin exact input fill and output, transfer-fee excluded/included amount, Token-2022 transfer-fee epoch selection and transfer-hook/unknown-extension rejection;
   - maximum arrays/bins and bounded traversal/compute limits;
   - exact consumedInAmount, outAmount, fee, protocolFee, minOutAmount, endPrice, binArraysPubkey, feeOnInput, bins and arrays used.
3. For circular flashloan route promotion require consumed input == requested input (or explicitly supported fee semantics preserving the same principal); partial-fill quote must remain non-promotable.
4. Reject incomplete reachable bins, bitmap gaps, stale/mixed generations, wrong token program, unsupported pair type/version, missing clock/epoch, transfer hook not resolvable, amount overflow, unsupported limit-order resource or missing fee state.
5. Differential-test against SDK vectors or a pinned independent local harness, with positive and negative cases; synthetic fixtures remain synthetic. Do not label an SDK-derived model as live-verified.

## 5. Multi-source market tracing and API readiness

Reuse src/market/source_catalog.py, src/resources/market_source_catalog.json, src/market/discovery.py, src/strategy/market_graph_ingest.py, src/solana_parallel_radar/ and the existing governed Transport.

Build a readiness artifact that answers, for every producer:
- exact official URL/endpoint/method/schema and API version;
- auth type + environment-variable NAME only (never value);
- quota/rate limit, payload/page/timeout bounds, 429 Retry-After behavior;
- data class: discovery, aggregator quote, exact account state, reference stream, financing state;
- source/operator/correlation group, provider ID and generation;
- owner module and existing PR;
- live authorization status, credential availability status (do not probe credentials), current integration state;
- tests/fixture/replay, raw request/response hashes and last reviewed time;
- exact blockers, next bounded probe and owner expected to perform it.

### Source roles

**Discovery only:** DEX Screener, Raydium API V3, Meteora DLMM Data API. They identify candidate pools/metadata; their price, TVL or volume is never executable depth.

**Aggregator route comparison:** Jupiter Swap API V2 GET /swap/v2/order and 0x Solana POST /solana/swap-instructions. Same canonical mint pair, same raw amount, same quote mode and bounded timestamp skew. Aggregator overlap is de-duplicated by physical pool identity. 0x instructions remain inert evidence; do not sign or submit them. Revalidate 0x API version/header requirements against the exact Solana endpoint before first request.

**Direct exact state:** Solana RPC getMultipleAccounts finalized/rooted snapshots. Account groups should fit the 100-address request limit where possible; preserve each response context slot. If more than one request is needed, enforce minContextSlot and bounded observed skew; never synthesize one common slot from separate responses. Subscribe via existing account stream/transport only as a change trigger; periodically re-root and reconcile complete state. Require at least two independently operated RPC sources with different provenance/correlation groups before claiming quorum. Two aggregators are not two independent RPCs or two independent liquidity resources.

**Optional event/stream supplement:** existing Helius provider modules may provide notifications/recovery. They do not replace rooted direct account snapshots or exact state decoders. Keep optional for first MVP unless the existing owner map proves a direct required path.

**Flash capital:** Jupiter Lend current CAP-A reader + R03 unsigned builder. It is not a quote provider. Read current TokenReserve/vault/borrow-position/admin/fee/capacity state under governed rooted RPC and create a positive FlashCapitalEdge only after all exact R02 conditions pass.

## 6. Currency pairs and route tests

Use exact canonical token identity (Solana mainnet genesis + mint + token program + decimals + extensions); symbols are labels and must never create an edge. The first benchmark set should be discovered from live/current pool metadata but may use these search hints:
- SOL/USDC: primary benchmark. These assets already appear in the existing core-jupiter-lend-jupiter-v1 profile / runtime discovery. Use exact mint identities; don't assume all venues currently have a pool.
- USDC/USDT: optional stable pair if both exact mints and each venue's pool are currently verified.
- SOL/mSOL or SOL/JitoSOL: only direct DEX swap pools. Do not model staking, unstake queues, epoch exits or redeem functions as immediate swap edges.
- Long-tail pairs: include only after pool, mint, Token-2022 extensions and source freshness are verified.

Required route cases:
1. Same mint pair, Raydium CLMM vs Meteora DLMM: A→B on one physical pool, B→A on another, both directions. Verify resources independent.
2. Mixed CPMM/CLMM/DLMM 3-leg closed triangle, only if each edge has a current exact evaluator and same coherent state generation.
3. Mixed 4-leg cycle after 3-leg passes.
4. Aggregator route where Jupiter and 0x use the same underlying pool: it is one physical resource; reject false independent-venue arbitrage.
5. Same venue family but alias/wrapper mint: reject if canonical asset identities differ, unless an explicit reviewed conversion edge exists.
6. Negative route if one venue quote is stale, incomplete, partial, dynamic fee unresolved or has unknown transfer-fee behavior.

Do not hardcode that a particular path exists. Search hints only; actual paths are created from current exact mints/pools.

## 7. Jupiter Lend, financing and signer boundary

The existing src/lending/jupiter_lend.py, R02 CAP-A reader, src/lending/unsigned_builders/jupiter_builder.py, R03 FinancingPort/UnsignedExecutionPlan and src/economics/flash_capital_graph/ are the only financing owners to extend.

Required:
- prove mint, reserve PDA, TokenReserve owner/discriminator/layout, vault owner/mint/token program/balance, borrow-position debt ceiling/active borrowing, lending program identity, admin state/status, current flashloan fee and rounding, available borrow amount and liabilities, slot/freshness and independent source provenance;
- capacity is UNKNOWN until rooted state proves it. Do not infer from TVL, vault total, admin flag, documentation fee or one RPC;
- docs currently advertise no-collateral/no-fee Jupiter flashloans, but the repository reader contains a flashloan_fee state field. Never hardcode fee=0 from docs. Read the current on-chain state and decode the deployed version;
- represent order in unsigned instruction plan only: borrow → exact route instructions → payback. Validate same borrowed mint/amount, repay semantics and atomic transaction ordering;
- use a fixture-only public signer key in offline tests if a signer account-meta is structurally required. Do not create a wallet or request a key in chat.
- **No signer integration in this PR.** Do not read private keys, seed phrases, keypair files, environment secrets or remote signer credentials. Do not load a signer object, sign, serialize a signed transaction, broadcast, borrow, spend or create ATAs/accounts. Keep live/sign/send false. Any future isolated signer adapter requires its own explicit authorization and review.
- R05 exact simulation is separate and blocked until R02 capacity and R03 builder evidence are qualified; R06 paper requires the existing QPR gates.

## 8. First capture and route tracing runbook (prepare, do not activate)

Prepare configuration and an operator checklist, but do not perform external network reads in this implementation PR. A later human-authorized read-only campaign should:
1. Start one bounded pair-universe discovery read through existing adapters for SOL/USDC plus dynamically discovered candidates.
2. Resolve every pool to canonical mints, program ID, pool identity, fee/model revision and current token program/decimals.
3. Read CLMM pool + config + dynamic-fee + bitmap extension if required + all reachable tick arrays + vault/mint accounts; do the equivalent DLMM LbPair + bitmap extension + active/directional BinArray set + clock/epoch + token metadata.
4. Read each dependent set with finalized commitment and source-specific context slot; compare at least two independent RPC providers.
5. Run direct amount-specific quote grids on both venues and aggregator comparison on the same raw sizes (the provider read is evidence only; do not build or send instructions).
6. Feed only verified complete quotes into the post-#659 canonical observation/route path, dedup physical resources, run PR118 sizing and record all economic cost terms.
7. Produce trace rows for every candidate, including no-trade/rejection; preserve raw request/response and account hashes.
8. Replay exactly from retained evidence with no outbound network.

## 9. Deliverables and acceptance

- Update existing P0 vendor source manifest and verifier with new source files and hashes; no parallel manifest authority.
- Update existing SOURCE_MANIFEST.json/provider-source dossiers where contract pins are refreshed; do not create a competing source catalog.
- Extend existing CLMM and DLMM native decoders/math; no parallel adapters.
- Extend existing market observation/graph binding and #659 route binding; no parallel graph or solver.
- Update SUPER-03 venue conformance evidence with full closure and typed external blockers; status is offline conformance only until real rooted data/independent reference parity.
- Add deterministic tests for Raydium bitmap positive/negative traversal, positive/negative extension offsets, pool binding, dynamic fee state, fee_on modes, fee rounding, tick crossing, missing/duplicate/foreign arrays, stale slot; Meteora dynamic fee, base fee, fee cap/rounding, positive/negative bin arrays, bitmap extension range, X↔Y direction, multi-bin, partial fill, Token-2022 transfer fees, unsupported hooks, missing/stale array, amount bounds and overflow.
- Add mixed CPMM/CLMM/DLMM route replay, same-pair cross-venue loop, 3/4-hop mixed cycles, pool alias dedup, stale and incomplete state, dynamic fee change, unknown costs, no lender edge, builder-unqualified, simulation blocked and paper gate blocked.
- Add updated API/source readiness matrix, exact curl/CLI command templates with redacted auth placeholders, config schema and readiness report. Never include secret values.
- Record actual test commands/results, changed files, source hashes, exact status of each source, API activation not performed, and remaining human gates.
- Report counts separately: discovery candidates; identity-verified pools; rooted direct-state pools; exact CLMM quotes; exact DLMM quotes; CLMM/DLMM mixed exact routes; unique underlying-resource routes; net-positive routes; lender-eligible routes; builder-conformant routes; simulation pass; paper complete. Separate fixture/replay and live-source counts at all times.

**Stop condition:** both venue models have deterministic exact quote/replay over complete dependency closure and can produce a typed, provenance-rich canonical observation accepted by the existing #659 route path. The first human-authorized bounded live-read campaign can then be started as a separate PR/operation. Do not claim profitability, capital qualification, paper success, or production readiness from fixture evidence.

## 10. Hard prohibitions

No new strategy families; no new graph/solver/quote kernel/source catalog/transport/quorum/journal/capital graph/signer/sender; no symbol-based identity; no TVL-as-depth; no quote extrapolation; no unknown-fee-as-zero; no pool double-counting; no async/cross-chain/maturity/queued exit as local atomic leg; no credential probing; no API activation; no account/ATA creation; no private keys; no signing; no sending; no borrowing; no spending; no deployment; no live mode; no production promotion.
