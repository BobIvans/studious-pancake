# R13-A1 — Titan quote adapter on the frozen kernel (offline, fail-closed, sender-free)

**Lane:** R13-A1 · **Date:** 2026-11-14 · **Base:** `77d57e94f46bb4be05b433b1ff7eea14596b07b1` (origin/main at lane start, post-#639) · **Branch:** `agent/r13-titan-adapter` · **Evidence state:** `ADAPTER_BUILT_OFFLINE_UNQUALIFIED`

## What this lane closes

The R13 quote/build race audit (`R13_QUOTE_BUILD_RACE_AUDIT_2026-11-14.md`) recorded **Titan adapter: NONE** (`R13_GAP_NO_ADAPTER` for Titan). This lane closes that gap ADDITIVELY: a typed, sender-free, offline adapter that produces kernel `NormalizedProviderQuote` evidence for the pinned Titan quote surface. No kernel type is redefined; no existing owner is edited.

## Frozen / implemented

- **Consumes (frozen):** `src/execution/quote_build_kernel.py` — `NormalizedProviderQuote`, `ProviderCorrelation`, `QuoteFreshness`, `QuoteFeeComponent`, `RouteVenue`, `PoolIdentity(AMM_KEY)`, `QuoteRaceRequest/Result`, `PoolIdentityDeduplicator`, `refuse_amount_extrapolation`, `ProviderReadFailure(Class)`. Import-only; zero duplication.
- **NEW `src/solana_parallel_radar/providers/__init__.py` + `providers/titan.py`:**
  - typed request construction for the pinned portal `GET /api/v1/quote/swap` (only portal-pinned params; `swapMode` portal param unpinned → `SCHEMA_MISSING_PIN` refusal for ExactOut, TITAN-U5);
  - response normalization into kernel quotes: exact base-unit amounts (`normalized == raw` — the wire is pinned "raw number of tokens, not scaled by decimals"; no decimal rescaling fabricated), `minimum_output_raw=None` (UNKNOWN, never zero), `computeUnitsSafe`-preferred compute estimate, `contextSlot`→freshness slot ONLY when supplied, `expiresAtMs`→exact ms→ns expiry, fees (`platformFee` PROVEN inclusion per official deduction semantics with UNKNOWN side; per-step venue fees UNKNOWN inclusion), route venues + `steps[].ammKey` pool identities, per-entry lineage `("titan", <entry-lowercase>)` under one operator group `titan-argos-router`;
  - build-output classification per the pinned dossier: `QUOTE_ONLY` / `INSTRUCTION_BUNDLE` / `UNSIGNED_TRANSACTION` (opaque tx string is evidence-only, never decoded/compiled/signed; `instructions`+`transaction` together = schema drift);
  - typed failures with frozen kernel-class mapping (`RATE_LIMITED`, `UNAUTHORIZED`, `TIMEOUT`→`TRANSPORT`, `TRANSPORT`, `INVALID_SCHEMA`, `SCHEMA_MISSING_PIN`, `EMPTY_QUOTES`, `COMPARABILITY_DRIFT`); transport is an injectable callable — the module ships NONE, `normalize_via_transport(None, …)` refuses typed `DISABLED`;
  - constant live-capture gate `TITAN_LIVE_CAPTURE_NOT_AUTHORIZED` (`titan_live_capture_verdict()` is always `BLOCKED`; no env var/credential/fixture can flip it), mirroring `src/gpr_sui_shadow/providers.py`.

## Pins added (new additive dossier dir)

`docs/integrations/offline/titan-adapter-2026-11-14/` — `TITAN_ADAPTER_SCHEMA_PIN.md` + `SOURCE_MANIFEST_ADDENDUM.json`:
- exact `SwapQuotes`/`SwapRoute`/`RoutePlanStep`/`PlatformFee`/`Instruction{p,a,d}`/`AccountMeta{p,s,w}` shapes transcribed from official Titan developer docs (titan-exchange.gitbook.io `swap-api/reference/direct/new-swap-quote-stream.md`, `swap-api/reference/types.md`, quickstart, stream-and-execute guide; retrieved 2026-11-14; OFFICIAL_CONTRACT_EXTRACT_ONLY, no page vendoring);
- resolves the wave-1 typed unknown #4: `contextSlot` is a pinned optional `SwapRoute` field → freshness slot recorded when supplied;
- 8 new typed unknowns recorded (`TITAN-U1..U8`: portal JSON u64/tx/data encodings UNPINNED → integers/opaque-string-only decode with typed `SCHEMA_MISSING_PIN` refusal; msgpack transport NOT_IMPLEMENTED; portal `swapMode` NOT_PINNED; rate-limit taxonomy UNKNOWN).
- Wave-1 dossier `providers-wave1-2026-11-13/` untouched; correlation facts reused from `PROVIDER_OVERLAP_NOTES.md` (Titan carries Metis/Okx entries → lineage-based dedup).

## Tests

`tests/test_r13_titan_adapter.py` (+ fixture `tests/fixtures/r13_titan_adapter/quote_swap_portal_wave1.json`, built ONLY from the pinned schema): **58 passed, 0 failed, 0 skipped** (venv pytest, offline; pytest-socket applies in CI; no network call anywhere — every transport is injected or `None`).
Coverage: exact-field positives; unknown-stays-None; platform/venue fee components; venue share ppb→bps exact-or-None; build-output classes; request construction positives/negatives incl. fee-limit and unpinned-swapMode; schema-drift negatives (quotes-not-map, missing id/steps, string-encoded amounts → MISSING_PIN, amount/mint/swapMode drift, instruction-data encoding, tx+instructions drift, steps beyond kernel venue bound, ExpectedWinner drift); 429/401/500/timeout/transport typed failures; empty-quotes typed; kernel race integration (ExpectedWinner wins, losers keep typed reasons); stale quote never wins (`max_age_ns` and slot-gap bounds); future observation refused; pool-identity dedup (Titan `Okx` entry ↔ OKX-direct capture CORRELATED via lineage+pool; disjoint-pool INDEPENDENT; pool-less UNKNOWN never independent; transitive single cluster; `independence_set` never double-counts the Titan family); kernel extrapolation refusal (exact bound passes, ±1/±1000/×2 refuse with frozen kernel code).

**mypy:** `src/solana_parallel_radar/providers/titan.py` + package `__init__.py` → **0 errors** (checked with `--follow-imports=silent`; with default following, the same 10 pre-existing errors appear as for the existing `src/solana_parallel_radar/probes.py` baseline — parent-package chain into `src/config/strict_yaml.py` (yaml stubs) and `src/qualification_campaign/sources.py`; not touched by this lane). **black:** all three new Python files formatted.

## Evidence states

- Adapter + fixtures + tests: `ADAPTER_BUILT_OFFLINE_UNQUALIFIED` (kernel `execution_authority=False` on every quote; discovery evidence only).
- Live capture: `BLOCKED / TITAN_LIVE_CAPTURE_NOT_AUTHORIZED` (constant; user-gated, out of scope).
- No provider enabled; `sign_enabled=false`, `send_enabled=false`; no credentials exist in this environment.

## Explicitly NOT done (deferred / blocked)

- **Funnel wiring DEFERRED:** no edits to `probes.py`/`funnel.py`/`cli.py`/kernel (per lane constraints). The adapter is a NEW module the P0-2 owner can call later; wiring lane should add batch→race contribution at the existing funnel seam without touching provider planes.
- Portal JSON u64/`transaction`/instruction-`d` encodings are UNPINNED (TITAN-U1..U3): a future LIVE capture lane must re-pin the actual portal encodings (new dossier version) before any live parse can succeed beyond fixtures.
- MessagePack (Gateway/Direct) decode: NOT_IMPLEMENTED (needs its own capture + pin, TITAN-U6).
- Qualification (`OFFLINE_UNQUALIFIED → QUALIFIED*`) requires user-gated live evidence; not attempted here.

## Changed paths (all NEW; zero edits to existing files)

- `src/solana_parallel_radar/providers/__init__.py`
- `src/solana_parallel_radar/providers/titan.py`
- `tests/test_r13_titan_adapter.py`
- `tests/fixtures/r13_titan_adapter/quote_swap_portal_wave1.json`
- `docs/integrations/offline/titan-adapter-2026-11-14/TITAN_ADAPTER_SCHEMA_PIN.md`
- `docs/integrations/offline/titan-adapter-2026-11-14/SOURCE_MANIFEST_ADDENDUM.json`
- `docs/roadmap/agent-execution-master-2026-11-13/reports/R13_TITAN_ADAPTER_2026-11-14.md` (this file)

## Recommendation

Next lane: funnel/race wiring (consume `titan.kernel_race_inputs()` at the P0-2 funnel seam behind the existing disabled-by-default stance), then the user-gated live-capture lane that re-pins TITAN-U1..U3 portal encodings from a real capture.
