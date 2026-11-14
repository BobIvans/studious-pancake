# TON Wave-2 — offline technical dossier

**Prepared:** 2026-11-14 (wave label `ton-wave2-2026-11-14`, branch `agent/ton-radar-wave2`, base `e2b65c0ceefdc6f9f99cdc0187ff23dc7815acc8`)
**Purpose:** wave-2 verification layer on top of `ton-wave1-2026-11-13/` (never overwrites wave-1): Tonco discovery surface, Omniston v1beta8 currency re-check, STON.fi "v2" schema verification, TON Center v2 + TonAPI v2 spec-pinned method contracts, and the typed TON flash-loan atomicity negative-evidence note.

## Read order

1. `SOURCE_MANIFEST.json` — per-source status (`PINNED_CURRENT` / `MISSING_PIN`), spec pins (URL, SHA-256, Git blob SHA-1, license, retrieval date), drift records, blockers.
2. `TONCO_DISCOVERY_SURFACE.md` — Tonco (concentrated-liquidity AMM, not an orderbook): GraphQL indexer + farming REST + SDK pins; GraphQL schema stays `MISSING_PIN`; no radar adapter.
3. `OMNISTON_V1BETA8_VERIFY.md` — `stonfi.omni.v1beta8` re-verified as the current namespace; environments unchanged; radar reader unchanged.
4. `STONFI_SCHEMA_VERIFY_WAVE2.md` — no REST v2 exists; `@ston-fi/api` 0.33.0 / commit `0a6113ba` still current (wave-1 snapshots byte-current); additive drift records (`/v1/stats/stake`, POST query endpoints, plain `/v1/stats` still undocumented).
5. `TON_STATE_PROVIDERS_WAVE2.md` — TON Center v2 (`openapi.json` mirrored, auth `X-API-Key`/`?api_key=`, Tonlib envelopes, `getAddressInformation`/`runGetMethod` contracts) and TonAPI v2 (`opentonapi/openapi.yml` mirrored, auth `Authorization: Bearer`, `Account`/`JettonsBalances` schemas, lt-cursor pagination). Wave-1 missing pins resolved at spec level; still no state adapter.
6. `TON_ATOMICITY_RESEARCH.md` — typed `ATOMICITY_RESEARCH` negative-evidence note: TON's execution model (one-account transactions, actions+bounce phases, multi-transaction traces) admits no native flash-loan primitive; verbatim-official-statement gap typed `MISSING_PIN`.
7. `vendor-reference/toncenter-v2/openapi.json`, `vendor-reference/opentonapi/openapi.yml`, `vendor-reference/opentonapi/LICENSE` — inert mirrored official artifacts (hash-pinned in the manifest).
8. `verify_offline_bundle.py` — zero-network verifier (required files + SHA-256 of mirrored specs + manifest structure).
9. `REPORT.md` — wave-2 status table and what changed vs wave-1.

## Agent rules (inherited and unchanged)

1. Wave-1 dossiers remain the field-level contracts; wave 2 only re-verifies, refines, and adds. Unknown is not zero; fixtures are never live evidence.
2. No live TON RPC/API call from repository code or tests. No adapter was enabled by wave 2; all providers stay disabled until individual evidence gates pass.
3. TON stays `TON_ASYNC_MULTI_CONTRACT` / `DISCOVERY_ONLY` / `executable=False`. No flash-capital edge may be created for TON on the strength of this wave; see `TON_ATOMICITY_RESEARCH.md`.
4. A failed capture or schema error is durable negative evidence and never retires a market.

## Suggested local verification

From repository root:

```powershell
python docs/integrations/offline/ton-wave2-2026-11-14/verify_offline_bundle.py
```

The verifier is network-free: it checks required files, recomputes SHA-256 over the two mirrored official specs, cross-checks the manifest pins and statuses, and prints audit digests. It does not perform live provider qualification.
