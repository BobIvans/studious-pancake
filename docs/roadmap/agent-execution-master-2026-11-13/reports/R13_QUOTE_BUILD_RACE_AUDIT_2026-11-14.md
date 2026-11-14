# R13-A — Multi-provider quote/build race audit: documented vs implemented vs wired

**Lane:** R13-A (read-only audit + typed gaps report + additive contract tests)
**Date:** 2026-11-14
**Branch:** `agent/r13-quote-build-audit`
**Base SHA:** `e2b65c0ceefdc6f9f99cdc0187ff23dc7815acc8` (merge of PR #620)
**Main at time of audit:** `5e0c0e7f` (merge of PR #621) — one commit ahead of this base; no src/ drift between the two, the delta is docs/integrations/offline/providers-wave1-2026-11-13/ only (see §5).
**Scope:** audit the ACTUAL code vs documented contracts for the quote/build race capability (Solana + Sui). Document names are not proof of executable classes or boot-path wiring; every claim below was verified by reading the pinned worktree code and running existing offline tests.

---

## 0. Executive summary (headline counts)

R13 candidates (per `tasks/R13_MULTIPROVIDER_QUOTES_AND_BUILDS.md`):

| Chain | Candidates | Documented contract (source-pinned dossier) | Adapter class in code | Wired into a supported boot path | Fully executable today |
|---|---|---|---|---|---|
| Solana | 6 (Jupiter V2, 0x, Titan, OpenOcean, OKX DEX, Rango) | **6/6** | **4/6** (Titan, Rango: NONE) | **4/6 with caveats** (Jupiter full; 0x wired but credential-blocked; OKX discovery-only; OpenOcean disabled without key) | **1/6** (Jupiter router only) |
| Sui | 7 (Aftermath, Cetus Aggregator, 7K/Bluefin7K, FlowX, OKX DEX, Rango, direct DeepBook) | **7/7** (wave-1 dossiers merged on main via PR #621, post-base) + existing GPR-03 state pins | **0/7 swap-quote adapters** (DeepBook/Aftermath/Cetus exist only as *state discovery* + *flash-financing* owners, not quote owners) | **0/7** for the quote/PTB race | **0/7** |

Headline structural findings:

1. **There is no single `QuoteProvider` / `TransactionBuilder` / `UnsignedExecutionPlan` / `ProviderCorrelation` / `BuildEvidence` kernel (UXE-00 is NOT implemented as one owner).** The documented class names from `EXECUTION_BUILDER_CONTRACT.md` / `IMPLEMENTATION_ROADMAP.md` exist nowhere as executable classes (grep across src/): `NormalizedQuote` survives only as an alias in two *separate* planes. The contract pipeline `QuoteProvider[] -> NormalizedQuote[] -> correlation-aware ranking -> TransactionBuilder -> UnsignedExecutionPlan -> simulation` is realized today only as fragments spread across three partially overlapping planes (§2). No code path connects a won quote to an R-03 unsigned plan.
2. **Two Solana quote planes exist and must not be conflated:** the governed research plane (`src/solana_parallel_radar/`, P0-2 owner #604, `execution_authority=false`) and the production discovery plane (`src/routing/`, wired into the supported paper/shadow boot path via `src/runtime_discovery_builder.py` and `src/paper_shadow/composition.py`). A third legacy adapter set (`src/ingest/swap_providers.py`) is importable but is on **no** supported boot path (compatibility shim only).
3. **Sui has zero swap-quote adapters.** All Sui provider code is (a) checkpoint/pool/state discovery (`src/gpr_sui_shadow/`, GraphQL/gRPC only, live bindings deterministically `BLOCKED`), or (b) flash-capital financing/PTB planning (`src/multichain/sui.py`, `src/lending/unsigned_builders/navi_ptb_builder.py`). The R13 Sui quote/PTB race has no starting adapter; it is not "implemented but unwired", it is absent.
4. **Multiple aggregator quotes are not independent liquidity.** Code TODAY preserves the evidence needed to detect overlap (Jupiter `routePlan` amm keys, 0x `route_plan` dex program ids, routing-plane `correlation_labels = ("aggregator:<id>", "underlying:<venue>", ...)`) but **no pool-ID intersection dedup is computed anywhere**; `compare_quotes` treats different correlation-group labels as `independent=True` even when route legs share pools. OpenOcean is a documented composite of Jupiter + Titan; Titan's own quote map carries Metis/OKX entries; the whole Sui aggregator family inter-wraps. Typed gap `R13_GAP_NO_POOL_DEDUP`.
5. **No quote extrapolation hooks exist** (verified positively): the governed comparator rejects any amount/mint/taker mismatch (`QUOTE_UNITS_OR_REPRESENTATION_MISMATCH`, `QUOTE_TAKER_PARITY_MISMATCH`), the routing fingerprint binds the exact base-unit amount, and `route_graph.input_amount` must equal `quote.input_amount`. Every nonlinear sizing point must re-quote; nothing in the code offers scaling.
6. Losing quotes ARE preserved today (governed plane appends every rejected/failed read as typed negative receipts; the routing plane returns `DiscoveryBatch(quotes, failures)` and `classify()` keeps all discovery candidates with per-quote `NonSelectionReason`s).

Typed gap taxonomy used below (definitions):
- `R13_GAP_NO_SOURCE_PIN` — no pinned dossier; nothing may be built.
- `R13_GAP_DOC_ONLY` — documented contract exists, zero code.
- `R13_GAP_NO_ADAPTER` — documented + partially consumed as state/financing, but no quote/build adapter.
- `R13_GAP_UNWIRED` — adapter class exists but is not on a supported boot path or is held at discovery-only/disabled by governance.
- `R13_GAP_PARTIAL_WIRING` — wired into a boot path but blocked by missing operator inputs (credentials/taker), i.e. code path exists, evidence path blocked.
- `R13_GAP_NO_BUILD_PLAN_CONVERSION` — build artifact (instructions/PTB/serialized tx) is retained as inert evidence but never converted to an R-03 `UnsignedExecutionPlan`.
- `R13_GAP_NO_POOL_DEDUP` — correlation labels/route legs retained, but no aggregator/pool intersection dedup or independence proof.

---

## 1. Solana provider matrix

### 1.1 Jupiter Swap API V2

| Audit dimension | Finding (file:line in this worktree) |
|---|---|
| Documented contract | YES. `docs/integrations/offline/solana-p0/JUPITER_SWAP_V2.md` + `JUPITER_SWAP_V2.openapi.yaml`, git-SHA + blob pins enforced by `ReadContract.__post_init__` (`src/solana_parallel_radar/probes.py:48-64`). Task owner: P0-2, merged PR #604. |
| Adapter class in code | YES, twice (deliberately, per owner rules): governed research plane — `jupiter_request()` `probes.py:283` + `normalize_jupiter_v2()` `src/solana_parallel_radar/funnel.py:91` (quote-only; a V1 payload carrying `contextSlot`/`instructionVersion` is rejected `JUPITER_V1_QUOTE_SCHEMA_REJECTED`); production routing plane — `src/routing/adapters.py:99 JupiterRouterAdapter` + `src/routing/clients.py:250` (GET `/swap/v2/build`). A third legacy `JupiterSwapV2Adapter` (`src/ingest/swap_providers.py:148`) is explicitly not on the active path (PR-011 comment, `swap_providers.py:215-218`). |
| Wired into supported boot path | YES, both active planes. Governed: `src/solana_parallel_radar/cli.py:773-794` (`capture` command; entitlements at :600-612, max 4 quote reads/plan). Production: `ProviderRegistry.from_env` `src/routing/registry.py:194-201` -> `build_runtime_discovery` `src/runtime_discovery_builder.py:41` -> supported paper/shadow composition `src/paper_shadow/composition.py:253`. Jupiter quota: shared `JupiterQuotaManager` (PR-031) on discovery purpose; the governed plane uses a per-provider 4-request campaign entitlement, not a shared serialization point (matches the "do not serialize unrelated providers behind the Jupiter bucket" rule). |
| Build mode | Governed plane: **quote-only** — a present `transaction` field is rejected (`JUPITER_V2_TRANSACTION_PRESENT`, `funnel.py:131-134`). Routing plane: **composable raw instruction bundle** (`swapInstruction`, `computeBudgetInstructions`, `setupInstructions`, `otherInstructions`, `cleanupInstruction`, `blockhashWithMetadata`, `addressesByLookupTableAddress`; `adapters.py:283-301`, `ExecutionArtifactKind.RAW_INSTRUCTIONS` `src/routing/capabilities.py:5`). |
| Correlation groups | Governed: `correlation_group="jupiter-metis-router"` (`cli.py:157-169`), route legs retained with `ammKey`/`label` (`probes.py:346-375`). Routing: `correlation_labels=("aggregator:jupiter_router", "underlying:<dex>", ...)` (`clients.py:87-95`), `RouteGraph` with per-edge venue labels. |
| Quota/auth | `JUPITER_API_KEY` (x-api-key); governed 4 req/plan; routing 60 req/60s pin + quota manager; missing key disables the router adapter in production plane only if `require_api_key=True` (`clients.py:262-270`). |
| Typed gap | `R13_GAP_NO_BUILD_PLAN_CONVERSION` — the routing plane validates and retains raw instructions but nothing converts them into an R-03 `UnsignedExecutionPlan`; governed plane is quote-only by contract. No `R13_GAP_*` for the quote race itself: documented, implemented, wired. |

### 1.2 0x Solana

| Audit dimension | Finding |
|---|---|
| Documented contract | YES. `docs/integrations/offline/solana-p0/ZEROX_SOLANA_SWAP.md` + fern pins (`fern/openapi-solana-swap.json`); `ReadContract` enforces POST only against `https://api.0x.org/solana/swap-instructions` (`probes.py:66-69`). |
| Adapter class in code | YES. `GovernedReadPlane.collect` POST path with exact 5-key body, slippage bound 0-50 bps, pubkey validation, native-sentinel rejection (`probes.py:135-149`); `normalize_zero_x` `probes.py:317`; route metadata with `dex_address`/`dex_label`/`dex_program_id` `probes.py:378-397`. Production-plane `ZeroXSolanaAdapter` (`src/ingest/swap_providers.py:201`) is a **feature-gated stub** (enabled=False; quote raises `UnsupportedProviderCapability`). |
| Wired into supported boot path | PARTIAL. `cli.py:754-768` fires the 0x POST only when `--zero-x-taker` is supplied; otherwise a typed `missing-public-taker` receipt is appended and no physical read happens (`cli.py:738-753`). Credential `ZEROX_API_KEY` read from env. 0x is NOT in the production routing registry. |
| Build mode | **Quote + inert unsigned instructions**: the swap-instructions response is hashed/redacted as raw evidence; `normalize_zero_x` consumes only amounts + route plan. Instructions are never decoded into a plan (per P0-2 rule 10). |
| Correlation groups | `correlation_group="0x-solana-router"`; per-leg dex attribution retained (the field that enables future pool dedup). No slot synthesized — slot stays `None` (`probes.py:325-343`). |
| Quota/auth | `ZEROX_API_KEY` (0x-api-key header), governed 2 req/plan; no guessed rate-limit tier. |
| Typed gap | `R13_GAP_PARTIAL_WIRING` (operator must supply public taker + key for any physical capture) and `R13_GAP_NO_BUILD_PLAN_CONVERSION`. |

### 1.3 Titan

| Audit dimension | Finding |
|---|---|
| Documented contract | YES — but only on main post-base: `docs/integrations/offline/providers-wave1-2026-11-13/TITAN_SOLANA.md` (PR #621, commit `3a825639`, NOT in this worktree's base). Documents GET `/api/v1/quote/swap` (portal REST, x-api-key / Gateway msgpack Bearer JWT / Direct WS), `userPublicKey` required, response = map of per-provider `SwapRoute`s with `instructions` + `addressLookupTables` + `computeUnitsSafe` + `metadata.ExpectedWinner`, `expiresAtMs`/`expiresAfterSlot`, fee asymmetry (`feeBps` request vs `fee_bps` response), quota UNKNOWN. |
| Adapter class in code | **NONE.** Only textual mentions: `src/routing/capabilities.py:5` (OpenOcean pin: "meta-aggregator over Jupiter/Titan") and `src/planning/rent_sponsor_planner.py:329-333` (`titan_payer` sponsor profile, `verified_offline=False`, tier INACTIVE). |
| Wired into supported boot path | NO. |
| Build mode (documented) | Unsigned **instruction bundle + ALTs**; integrator assembles + signs the VersionedTransaction client-side. |
| Typed gap | `R13_GAP_NO_ADAPTER` (+ the dossier is post-base: cite commit `3a825639`; the worktree cannot see it until rebase/merge). |

### 1.4 OpenOcean (Solana)

| Audit dimension | Finding |
|---|---|
| Documented contract | YES. Capabilities pin `openocean-solana-meta-aggregator-2026-07-19` (`src/routing/capabilities.py:5`); wave-1 dossier `OPENOCEAN_SOLANA.md` on main post-base (V4 quote endpoint, hex serialized unsigned tx build with `isVersioned`, paid-subscriber build access, referrer fee 0.01-5% with a 3% page discrepancy recorded as `BLOCKED_MISSING_PIN`). |
| Adapter class in code | YES, twice: `src/routing/adapters.py:528 OpenOceanAdapter` + `src/routing/clients.py:398` (GET `https://open-api.openocean.finance/v4/solana/quote`, echo validation of in/out/account); legacy `OpenOceanSolanaAdapter` `src/ingest/swap_providers.py:209` (both quote and instructions raise `UnsupportedProviderCapability`). |
| Wired into supported boot path | PARTIAL. In `ProviderRegistry.from_env`; without `OPENOCEAN_API_KEY` the capabilities flip to `OPENOCEAN_DISABLED_CAPABILITIES` (role DISABLED, health DISABLED_MISSING_CREDENTIALS, `adapters.py:531-543`) and `enabled_adapters()` excludes it. With a key it races as **DISCOVERY_ONLY** (`ExecutionArtifactKind.NONE`, admission reason "no raw-instruction contract admitted"). |
| Build mode | Code: quote-only, artifact NONE. Documented: serialized unsigned transaction (hex) behind whitelist — no code parses it. |
| Correlation groups | Dossier + pin both record that OpenOcean composites Jupiter + Titan: **zero liquidity independence** from either. Code emits `underlying:` labels from returned `sources`/`dexes` when present. |
| Typed gap | `R13_GAP_UNWIRED` (disabled without credential; discovery-only with it) + `R13_GAP_NO_POOL_DEDUP` (its Jupiter/Titan overlap is documented but not enforced in any dedup). |

### 1.5 OKX DEX (Solana)

| Audit dimension | Finding |
|---|---|
| Documented contract | YES. Capabilities pin `okx-solana-swap-instruction-2026-07-19` with explicit promotion precondition ("promotion requires fixtures, auth vectors, ALT/instruction losslessness, opt-in contract test and composed simulation", `src/routing/capabilities.py:6`); wave-1 dossier `OKX_DEX_MULTICHAIN.md` on main post-base (swap-instruction bundle vs `/swap` serialized tx with mandatory fresh blockhash, HMAC OK-ACCESS-* auth, error 50011/429). |
| Adapter class in code | YES, twice: `src/routing/adapters.py:322 OkxDexAdapter` + `src/routing/clients.py:341` (GET `https://web3.okx.com/api/v6/dex/aggregator/swap-instruction`, HMAC headers, `instructionLists` + ALT validation); legacy `OKXSolanaAdapter` `src/ingest/swap_providers.py:177`. |
| Wired into supported boot path | PARTIAL. In `ProviderRegistry.from_env` unconditionally; role `DISCOVERY_ONLY`, so it is raced for **discovery quotes** on the supported paper/shadow path but can never be selected executable (`admits_raw_instructions()` false for its role; `classify()` filters it). |
| Build mode | Code: raw instruction artifacts validated (artifact `RAW_INSTRUCTIONS`) but role-blocked. Documented: instruction bundle + ALT list; also serialized-tx variant on `/swap`. |
| Correlation groups | OKX is named inside Titan's quote map and inside Jupiter's default router set — one OKX capture can share pools with Jupiter/Titan captures (dossier overlap notes). |
| Typed gap | `R13_GAP_UNWIRED` (execution promotion explicitly gated) + `R13_GAP_NO_POOL_DEDUP`. |

### 1.6 Rango

| Audit dimension | Finding |
|---|---|
| Documented contract | YES, main post-base only: `docs/integrations/offline/providers-wave1-2026-11-13/RANGO_MULTICHAIN.md` (chain-typed unsigned instruction bundle via `type` discriminator, swapper/swapperGroups attribution, route expiry error 1303 ~1-5 min, affiliate fee not available for Solana, Rango adds ~0.15% on top of affiliate fee). |
| Adapter class in code | **NONE** (no `rango` token anywhere in src/). |
| Wired into supported boot path | NO. |
| Typed gap | `R13_GAP_NO_ADAPTER`. Cross-chain note: only single-step same-chain routes are comparable; cross-chain flows carry bridge fees (dossier). |

### 1.7 Odos (present in code, outside the R13 candidate list — recorded for completeness)

`src/routing/adapters.py:655 OdosAdapter` (SOR v3, `ASSEMBLED_TRANSACTION`, non-composable, DISCOVERY_ONLY) exists and is exported by `src/routing/__init__.py` but is **not** in `ProviderRegistry.from_env` — `R13_GAP_UNWIRED` (and out of R13 scope; needs its own dossier before promotion).

---

## 2. The documented UXE-00/01 pipeline vs three real planes

`EXECUTION_BUILDER_CONTRACT.md` specifies one pipeline. Actual code has three planes; none implements it end to end:

| Documented concept | Governed research plane (`src/solana_parallel_radar/`) | Production routing plane (`src/routing/`) | Legacy plane (`src/ingest/swap_providers.py`) | R-03 builder plane (`src/lending/unsigned_builders/`) |
|---|---|---|---|---|
| QuoteProvider | `GovernedReadPlane` + `ReadContract` (2 providers) | `DiscoveryProvider` protocol + `DiscoveryPlane` (`registry.py:250`) racing enabled adapters concurrently | `SwapProvider` protocol (Jupiter stub not active; OKX/0x/OpenOcean gated) | none |
| NormalizedQuote | `QuotePreview` (`funnel.py:37`, frozen, evidence_state locked to `DISCOVERY_ONLY`) | `CanonicalQuoteV2` (`models.py:292`; `NormalizedQuote = CanonicalQuoteV2` alias `models.py:486`) | its own `NormalizedQuote` dataclass (`swap_providers.py:66`) — a THIRD, distinct type | none |
| correlation-aware ranking | `compare_quotes` (`funnel.py:175`): units/taker parity, bounded freshness (<=45s, slot gap <=32), `independent` = label inequality, `execution_authority=False` | `classify()`/`select_executable()` (`registry.py:447-483`): dedupe by route provenance, min-output proof, echo proof, conservative net result; losers kept with typed reasons | `execution_shortlist` + `select_after_simulation` (simulation-gated) | none |
| TransactionBuilder | none (quote-only by contract) | `RawInstructionArtifact` (`models.py:490`, EXECUTABLE-role only) — instructions retained, not assembled | `InstructionBundle` (`swap_providers.py:78`) | R-03 builders: Jupiter Lend / Kamino / NAVI PTB / Project0, all `BUILT_OFFLINE_UNQUALIFIED` |
| UnsignedExecutionPlan | none | none | none | `FinalizedUnsignedSolanaPlan` (`contract.py:934`) — lending-domain only, never fed by a quote |
| ProviderCorrelation | `correlation_group` field + route-leg metadata | `QuoteProvenance.correlation_labels` + `RouteGraph` venue labels | `route_steps` dex labels | none |
| BuildEvidence | response hashes + request fingerprints + typed negatives | `QuoteProvenance.response_hash`, `raw_field_paths` | `ProviderPerformanceRecord` | `BuilderSourcePin` + canonical hashes |

**Typed gap `R13_GAP_NO_KERNEL`:** the frozen-interface precondition written into the R13 task ("Extend the current QuoteProvider/TransactionBuilder owner only after code audit and one frozen interface contract") resolves to: there is no single owner to extend. Any R13 implementation lane must first pick/freeze ONE canonical contract (the routing plane's `QuoteRequest`/`CanonicalQuoteV2`/`DiscoveryBatch` is the most complete) and explicitly map the other planes onto it, or the codebase will drift into a fourth plane.

Wiring of the supported boot path (verified): `build_runtime_discovery` (`src/runtime_discovery_builder.py:15-61`) is constructed inside the supported sender-free paper/shadow runtime (`src/paper_shadow/composition.py:253`), honors `config.providers.jupiter.enabled` (removes the adapter and its API key from env when disabled, `:31-49`), and the coordinator blocks the whole cycle without a wallet public key (`src/runtime_discovery_coordinator.py:65-71`). `src/ingest/swap_providers.py` consumers are limited to the `MultiAggregatorClient` compatibility shim (`src/ingest/multi_aggregator_client.py`); no boot path constructs it.

---

## 3. Sui provider matrix

All seven R13 Sui candidates are documented on main post-base (PR #621) and **none has a swap-quote/PTB adapter**. Sui code today is exact-state discovery + flash financing only:

| Provider | Documented contract | Quote/PTB adapter in code | State/financing owner that DOES exist | Wired (quote race) | Build mode (documented) | Typed gap |
|---|---|---|---|---|---|---|
| Aftermath | YES: `AFTERMATH_SUI.md` (#621): SOR `trade-route`, composable `add-trade` PTB, 1000 req/10s default limit, signed-request rate-limit lift NOT_PINNED_THIS_WAVE | NONE | pool-index bulk read `src/gpr_sui_shadow/sources.py:37 aftermath_pools_request` (1 MiB/20k-node cap, fails closed) wired into the GPR-03 shadow campaign (`src/gpr_sui_shadow/campaign.py:59-62`) | NO | economic quote + **composable PTB** | `R13_GAP_NO_ADAPTER` |
| Cetus Aggregator | YES: `CETUS_AGGREGATOR_SUI.md` (#621): ResponseV3 fields, `find_routes` quote, `routerSwap*` composable PTBs, `sponsored` mode, `overlayFee`/`totalDeepFee` | NONE | (a) pool-state venue in `src/gpr_sui_shadow/sources.py:114-125` (CETUS_RESPONSE_SCHEMA_REJECTED guard); (b) `CetusFinancingAdapter` flash-loan/flash-swap receipts `src/multichain/sui.py:280-298` | NO | quote route ref + **composable PTB** | `R13_GAP_NO_ADAPTER` |
| 7K / Bluefin7K | YES: `SEVENK_BLUEFIN7K_SUI.md` (#621): `getQuote` + `buildTx` fresh/extend PTB, 5 rps default, MetaAg comparator over bluefin7k/flowx/cetus/okx, Pyth-oracle source exclusion | NONE | — | NO | quote + **composable PTB** | `R13_GAP_NO_ADAPTER` |
| FlowX | YES: `FLOWX_SUI.md` (#621): quote routes; `TradeBuilder.buildTransaction()` fresh PTB and `trade.swap({tx})` composable append; **commission-inclusive `amountOut` is DISPLAY-ONLY by official warning** | NONE | — | NO | quote + fresh/append PTB | `R13_GAP_NO_ADAPTER` |
| OKX DEX (Sui) | YES: `OKX_DEX_MULTICHAIN.md` covers Sui surface (error 80005; OKX provider inside 7K MetaAg with apiKey/secretKey/apiPassphrase/projectId) | NONE (Solana adapter only) | — | NO | Solana-class bundle; Sui PTB semantics unpinned | `R13_GAP_NO_ADAPTER` |
| Rango (Sui) | YES: `RANGO_MULTICHAIN.md` (`tx.type=SUI`) | NONE | — | NO | chain-typed instruction bundle | `R13_GAP_NO_ADAPTER` |
| Direct DeepBook | YES: GPR-03 lane pins `deepbook-index` GraphQL source (`src/gpr_sui_shadow/campaign.py:48-53`, `sources.py` DeepBook book decoders with sorted/noncrossed/two-sided reference guards) | NONE as swap-quote adapter (book state decoders are exact-state, not quotes) | state owner + `DeepBookFinancingAdapter` (`src/multichain/sui.py:244-268`) | state: YES (GPR-03 shadow). quotes: NO | n/a (order book) | `R13_GAP_NO_ADAPTER` for the quote/PTB race; the *state* owner is the one structurally distinct Sui depth source (dossier rule) |

Sui transport and authority invariants TRUE TODAY (asserted by the new contract tests):
- Only `graphql`/`grpc` transports are legal for provider bindings (`src/gpr_sui_shadow/providers.py:23`) — no legacy JSON-RPC fallback.
- Live Sui provider binding is deterministically `BLOCKED` with `LIVE_SUI_PROVIDERS_NOT_AUTHORIZED`; no env var/credential can flip it (`providers.py:197-210`).
- Two bindings sharing `profile_id`/`provider`/`operator`/`correlation_group` are rejected `SUI_CORRELATED_PROVIDERS_BLOCKED` (`providers.py:151-159`) — correlation governance exists for *state* providers and is the model the quote race must reuse.
- PTB planning is unsigned and inert: `SuiPtbAdapter.compile` is a deterministic proof compiler with no signing/sending (`src/multichain/sui.py:166-170`), and `build_navi_flashloan_ptb` emits frozen R03 DTOs with `BUILT_OFFLINE_UNQUALIFIED` status.

---

## 4. Cross-cutting invariants verified TRUE TODAY (now asserted by tests/test_r13_quote_race_contract.py)

1. **Losing quotes are preserved.** Governed plane: every non-200/schema-drift read lands as a typed receipt (`quality_state` in {rate-limited, unauthorized, http-error, quota-or-transport-error, cancelled, missing-credential-binding}, `probes.py:244-267`) and rejected normalizations append `gpr02_quote_rejected` (`probes.py:440-449`). Routing plane: `DiscoveryBatch` carries `quotes` AND `failures`; `classify()` keeps every quote in `discovery_candidates` with a typed `NonSelectionReason` (STALE / UNPROVEN_MIN_OUTPUT / INVALID_ROUTE_GRAPH / UNPROVEN_RESPONSE_ECHO / NON_COMPOSABLE / DUPLICATE / MISSING_COST / LOWER_CONSERVATIVE_NET).
2. **No extrapolation / no scaling.** `compare_quotes` raises on any (mint, mint, amount) mismatch and on taker-mode mismatch; `QuoteRequest.fingerprint` binds exact base-unit amount; `CanonicalQuoteV2` requires `route_graph.input_amount == input_amount` (`models.py:400`). No scale/convert/interpolate function exists in either plane (grep-verified). The governed campaign pins a single fixed input (1_000_000 raw units, `cli.py:574`) and re-issues a fresh physical read for the final diagnostic quote (`cli.py:785-794`).
3. **Bounded freshness.** `max_age_ns <= 45_000_000_000`, `max_slot_gap <= 32` are hard argument bounds; stale/future quotes rejected. Providers that do not expose a slot get `None` (never synthesized) for Jupiter V2 and 0x.
4. **Aggregator independence is NOT assumed.** The governed comparison emits `independent: correlation_group != correlation_group` and retains per-leg route/venue attribution (`route_legs` with ammKey/dex program ids) — the raw material for pool dedup. It does NOT yet compute pool-ID intersections: two aggregators routing the same pool would still be labeled independent (typical pair: `jupiter-metis-router` vs `0x-solana-router`). **Statement for every consumer of these feeds: multiple aggregator quotes are correlated observations of shared underlying pools, not independent liquidity confirmations; the only structurally distinct depth is direct pool/book state (P0-3 / GPR-03 owners).** Typed gap `R13_GAP_NO_POOL_DEDUP`.
5. **Authority ceilings.** Governed comparison payload hardcodes `execution_authority=False`, `production_promotion=False`; every QuotePreview is locked to `evidence_state="DISCOVERY_ONLY"`; qualification blockers require both 0x preview and Jupiter final quote plus startup hard-bound receipts (`funnel.py:212-233`); Token-2022 is explicitly unsupported in QPR-02 decoding.
6. **Sponsor/payer requirements are explicit metadata, not assumptions.** Rent sponsor tier 2 (`PROVIDER_SPONSORED`) is INACTIVE: both `0x_sponsor` and `titan_payer` have `verified_offline=False` (`src/planning/rent_sponsor_planner.py:323-333`); claims without verified evidence are refused with typed rejections. R-03 builders keep `build_status != capacity_status` and every plan `BUILT_OFFLINE_UNQUALIFIED` / `NOT_EVALUATED`.
7. **Providers are disabled until their individual evidence gates pass.** Jupiter runs EXECUTABLE; OKX is pinned DISCOVERY_ONLY with a written promotion precondition; OpenOcean is DISABLED without a key and discovery-only with one; 0x (production stub) is feature-gated; Odos is out of the registry; all Sui live bindings are BLOCKED.

---

## 5. Dossier availability and the wave-1 PR dependency

- In THIS worktree (base `e2b65c0c`): only `docs/integrations/offline/solana-p0/` (Jupiter V2 + 0x) and `docs/integrations/offline/ton-wave1-2026-11-13/`.
- On main (`5e0c0e7f` = merge of **PR #621**, merged 2026-11-14T00:52:59Z, commit `3a825639`): `docs/integrations/offline/providers-wave1-2026-11-13/` — 8 dossiers (TITAN_SOLANA, OKX_DEX_MULTICHAIN, OPENOCEAN_SOLANA, RANGO_MULTICHAIN, AFTERMATH_SUI, CETUS_AGGREGATOR_SUI, SEVENK_BLUEFIN7K_SUI, FLOWX_SUI) + PROVIDER_OVERLAP_NOTES.md + SOURCE_MANIFEST.json + zero-network verifier. Jupiter V2 + 0x are referenced from solana-p0, not re-pinned.
- **Dependency status: RESOLVED.** The wave-1 dossier PR (#621) is already merged into main; this lane's PR adds no conflict (docs report + one test file). The dossiers post-date this base SHA, so every matrix row above that cites them is pinned to commit `3a825639` (branch `agent/provider-dossiers-wave1`) rather than to worktree files. No `R13_GAP_NO_SOURCE_PIN` remains for any of the 13 audited providers; the wave-2 gaps that DO remain are listed in the dossiers themselves (e.g. Aftermath signed-request headers NOT_PINNED_THIS_WAVE, OpenOcean binding Solana fee limit BLOCKED_MISSING_PIN, Titan numeric quota UNKNOWN).

---

## 6. Offline test evidence (exact counts, socket-disabled, fixtures only)

| Test file | Result |
|---|---|
| `tests/test_gpr02_solana_parallel_radar.py` (governed quote funnel: Jupiter V2 + 0x normalization, comparison, negative classes, structural comparisons) | **112 passed** (74.99s) |
| `tests/routing/` (discovery plane, router client conformance, quota integration, canonical semantics, governed transport bounds) | **67 passed** (56.74s) |
| `tests/test_gpr03_sui_shadow.py` (Sui state providers, checkpoint/object provenance, bounded queries) | **86 passed** (132.60s) |
| `tests/test_pr056_runtime_discovery.py` + `tests/test_pr006_swap_providers.py` (runtime discovery wiring; legacy provider gating) | **13 passed** (6.58s) |
| `tests/test_r03_jupiter_builder.py` (unsigned Jupiter Lend builder) | **15 passed** (11.71s) |
| `tests/test_r03_unsigned_builder_contract.py` + `tests/test_r03_navi_ptb_builder.py` + `tests/test_rent_sponsor_planner.py` | **73 passed** (34.50s) |
| `tests/test_r13_quote_race_contract.py` (NEW, this PR: 25 offline invariant tests over the governed plane, routing plane, Sui provider bindings, R-03 pins, sponsor tiers) | **25 passed** (2.60s) |

Zero network: runs use the repo's offline fixtures/mock transports under pytest-socket; no provider enabled; no credentials present.

---

## 7. Ranked typed blockers for the R13 implementation wave

1. `R13_GAP_NO_KERNEL` — freeze ONE QuoteProvider/NormalizedQuote/build-artifact contract before adding any adapter (highest risk of creating the forbidden parallel quote plane; three partially-overlapping types already exist).
2. `R13_GAP_NO_POOL_DEDUP` — implement underlying-venue/pool-ID intersection dedup + independence proof from the already-retained route legs (Jupiter `ammKey`, 0x `dex_program_id`, routing `underlying:` labels, Titan per-provider map when added); until then every aggregator-vs-aggregator comparison must be consumed as correlation evidence only.
3. `R13_GAP_NO_ADAPTER` (Sui x7) — the Sui quote/PTB race has no starting point; the first slice should be ONE adapter (Aftermath or 7K, both composable-PTB and documented with quotas) reusing `CheckpointProviderBinding`-style correlation governance and the existing GraphQL/gRPC transport rules.
4. `R13_GAP_NO_ADAPTER` (Titan, Rango on Solana) — dossiers ready; Titan is the higher-value addition (instruction bundle + ExpectedWinner semantics + it is OpenOcean's other leg).
5. `R13_GAP_UNWIRED` (OKX execution promotion, OpenOcean enablement, Odos registry admission) — each requires its pinned evidence gate (fixtures, auth vectors, ALT/instruction losslessness, opt-in contract test, composed simulation) before role promotion; do not promote by config.
6. `R13_GAP_PARTIAL_WIRING` (0x governed capture) — operational, not code: public taker + `ZEROX_API_KEY` under a bounded opt-in live command.
7. `R13_GAP_NO_BUILD_PLAN_CONVERSION` — define the quote->plan bridge (routing `RawInstructionArtifact` -> R-03 `UnsignedExecutionPlan`) as a separate frozen-interface PR; until then build outputs stay inert evidence, which is the correct safety posture.

**Recommendation:** keep R13 execution gated behind blocker 1 (kernel freeze) and blocker 2 (pool dedup) as one coherent pair; add adapters one at a time per the R13 task's per-provider PR rule; do not treat any aggregator pair as independent liquidity in strategies or sizing; re-quote at every nonlinear sizing point (the code already makes scaling impossible — keep it that way).
