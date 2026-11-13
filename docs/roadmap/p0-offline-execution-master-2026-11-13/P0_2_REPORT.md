# P0-2 Report — Jupiter Swap API V2 + 0x comparable quote capture

**Status:** `IMPLEMENTED_UNQUALIFIED` (offline contract migration, fixtures, deterministic replay delivered; live capture remains a separately opted-in command and was **not** executed)
**Branch:** `codex/p0-2-jupiter-v2-0x-quotes-2026-11-13` (review-only PR)
**Base main SHA:** `64a11d33f46291504847cb1bdfd6cdc3dcff5da9`
**Date:** 2026-11-13

## What was delivered

The single governed GPR-02 quote owner (`src/solana_parallel_radar/`) migrates from the legacy Jupiter V1 `/swap/v1/quote` probe to the pinned official **Jupiter Swap API V2 `GET /order`** contract. No second Jupiter adapter was created. Production's active contract (`/swap/v2/build` router) is untouched.

### Migration details

| Change | Where |
|---|---|
| V2 request builder: `GET https://api.jup.ag/swap/v2/order` with `inputMint`, `outputMint`, exact base-unit string `amount`, `swapMode=ExactIn`, `slippageBps`, optional public `taker`; **V1-only params dropped** (`restrictIntermediateTokens`, `onlyDirectRoutes`, `dexes`, `instructionVersion` — none exist in the pinned V2 OpenAPI) | `probes.py::jupiter_request` |
| Distinct **V2 parser** `normalize_jupiter_v2`: rejects V1 payloads explicitly (`contextSlot`/`instructionVersion` ⇒ `JUPITER_V1_QUOTE_SCHEMA_REJECTED`); requires V2 markers (`mode`, `router` ∈ {metis, jupiterz, dflow, okx}); enforces request/response identity (mints, base-unit amount, slippage echo, taker echo); bounded routePlan 1..16 with per-leg `swapInfo` (ammKey/label/mints/amounts); `slot` stays `None` — the V2 order response has **no contextSlot**; `transaction` present or `errorCode` ⇒ not a comparable quote | `funnel.py::normalize_jupiter_v2` |
| **Taker parity**: `QuotePreview` gains an explicit optional `taker` (public address, validated); `compare_quotes` raises `QUOTE_TAKER_PARITY_MISMATCH` across modes and reports `taker_mode` (`QUOTE_ONLY` / `PUBLIC_TAKER_AWARE`) | `funnel.py` |
| Quote evidence now retains route/fee metadata next to the normalized quote: Jupiter `router`, `mode`, `requestId`, `quoteId`, `feeBps`, `feeMint`, `platformFee`, `gasless`, full route legs (ammKey/label/mints/amounts); 0x route legs (`dex_label`, `dex_program_id`), `zid`; both `slot: None` by contract | `probes.py::_jupiter_v2_quote_metadata`, `_zero_x_quote_metadata`, `normalized_reference` |
| **Native-SOL sentinel rejected** in both pinned quote contracts (Jupiter request mints and 0x `token_in`/`token_out`): `NATIVE_SOL_SENTINEL_REJECTED` — quotes bind the registry's WSOL mint, never the system-program sentinel | `probes.py::NATIVE_SOL_SENTINEL` |
| 0x preview records its factual public taker | `probes.py::normalize_zero_x` |
| CLI capture: taker-aware Jupiter capture when a public taker is configured (same taker as 0x, same 1_000_000 base-unit input, explicit `slippageBps`); comparisons only between matching modes; the V1 `dexes=Sanctum,…` inclusion probe is gone (not expressible in V2 — the Sanctum structural owner `structural.py` is unchanged) | `cli.py::capture` |
| Profile + pins: endpoint, docs URL and `allowed_query_parameters` pinned to V2; `config/qualification/gpr02-solana-contracts.json` pins.jupiter → upstream `jup-ag/docs@d40d9369` / blob `c8bad7a7dc9ff60149b55c20e46d7d57e75e2dd8`, hashes of the checked-in mirrors (`JUPITER_SWAP_V2.openapi.yaml`, `JUPITER_SWAP_V2.md`), `live_provider_schema_verified: false` unchanged | `cli.py::read_contracts`, pins JSON |
| **Quarantine re-review** (by design): `scripts/verify_mpr_next_08_jupiter_v2_contract.py` research-reference URL/literals → V2; `config/jupiter_endpoint_quarantine.json` review hashes re-pinned to the migrated LF bytes. Production forbidden markers and the `/swap/v2/build` active contract are **unchanged**; the review-note field records the migration | verifier script + quarantine JSON |
| `retained_quote` re-derivation uses the V2 parser | `qualification.py` |

### Credential decision (task item 1)

`ZEROX_API_KEY` remains the single canonical internal name (used by `cli.py`, `din00-source-status.json`). `ZEROEX_API_KEY` (provider docs' example name) appears nowhere in the repo; no compatibility alias was added.

## Contract traceability

- Pinned spec: `docs/integrations/offline/solana-p0/JUPITER_SWAP_V2.openapi.yaml` (OpenAPI 3.0.3 / info.version 2.0.0), upstream blob verified by `verify_offline_bundle.py` (exit 0 on this branch).
- 0x contract: `ZEROX_SOLANA_SWAP.md` extract (Open Beta; no machine-readable OpenAPI — pre-live-capture re-fetch blocker unchanged, recorded in `P0_BASELINE.json` B-P02-3).
- Known unpinned item kept explicit: 0x provider quota tier and context-slot absence — slot stays null; freshness comes from the existing ≤45 s window.

## Tests

`tests/test_gpr02_solana_parallel_radar.py` (migrated + new):
- `quote_payload()` lab fixture is now a pinned-V2 `/order` shape (mode/router/routePlan with `ammKey`+`label`, null `transaction`).
- New: `test_jupiter_v2_parser_accepts_pinned_order_shape_and_rejects_v1` (V1 payload with `contextSlot` rejected); a 7-case V2 fault matrix (missing/unknown router, transaction present, taker echo, slippage echo, identity mismatch, route endpoints); taker-aware echo parity + `QUOTE_TAKER_PARITY_MISMATCH` + `taker_mode` reporting; native-SOL sentinel rejection for both contracts.
- The funnel lab (`test_actual_funnel_reconstructs_quotes…`) is now taker-aware on both providers (same public taker) and re-derived via `normalize_jupiter_v2` + `retained_quote`.
- The 0x parser/instructions-inert tests are unchanged and still pass; the governed probe matrix (200/403/429/timeout/missing-key/reflection/quota/guard-generation/guard-quota) and the offline capture/replay tests are unchanged and pass.

**Execution status (honest):**
- **Executed on CI Linux** (see PR checks): `GPR-02 Solana read-only radar` (includes this suite), `MPR-NEXT-08 Jupiter V2 contract and quarantine` (24/24, includes `test_mpr_next_08_accepts_current_checkout` against the migrated checkout), `Read-only qualification campaign`, `Release authority`.
- **Executed locally (Windows, dev harness over the fcntl-gated modules):** pins/profile coherence, V2 request builder (incl. sentinel), V2 parser acceptance + full fault matrix + taker parity + metadata extraction, distinct legacy V1 parser retained — **all passed**.
- Local Windows subset (`tests/test_mpr_next_08…`, dynamic universe, asset resolution): 46 passed, no regressions. black/flake8/mypy clean.

## Replay

Deterministic offline replay unchanged: `python -m src.solana_parallel_radar.cli replay <dir>` and `portable.export_archive/replay_archive`; zero network. Live capture remains the opt-in `capture` command with `JUPITER_API_KEY`/`ZEROX_API_KEY` (+ `--zero-x-taker`); every request lands in the evidence journal with secret redaction.

## Safety

- No `/execute`, no transaction submission, no signing path; returned `transaction` bytes are inert and their presence **disqualifies** a quote from comparison.
- `execution_authority=false`, `production_promotion=false` preserved everywhere; production Jupiter contract (`/swap/v2/build`) untouched and re-verified.
- No live API requests were made in this work.

## Blockers

| ID | Blocker | Owner |
|---|---|---|
| B-P02-1 | `JUPITER_API_KEY` not configured locally | user opt-in for live capture |
| B-P02-2 | `ZEROX_API_KEY` + public taker not configured locally | user opt-in for live capture |
| B-P02-3 | 0x has no machine-readable OpenAPI pin (extract only) | bounded re-fetch before live qualification |
| B-ENV-2 | `fcntl` gate: local Windows runs of the radar suite need WSL | operator WSL install |
