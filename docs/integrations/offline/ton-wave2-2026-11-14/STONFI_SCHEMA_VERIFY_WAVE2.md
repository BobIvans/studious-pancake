# STON.fi REST schema — wave-2 verification against the wave-1 pin

**Retrieved:** 2026-11-14 UTC
**Verification URLs:** https://docs.ston.fi/llms.txt (docs index), https://docs.ston.fi/developer-section/dex/api.md (REST API page), https://docs.ston.fi/developer-section/dex/api/reference.md (API reference), npm registry metadata for `@ston-fi/api`, GitHub API for `ston-fi/api`
**Result: `PINNED_CURRENT`** for the endpoints the radar uses, with two additive drift records below. The wave-1 dossier (`../ton-wave1-2026-11-13/STONFI_REST_V1.md`) remains the full field-level contract; nothing in it was invalidated.

## Pin currency re-verification

- Official JS client `@ston-fi/api`: npm `dist-tags.latest` is still **0.33.0** (published 2026-10-30, MIT, repository `git+https://github.com/ston-fi/api.git`). Repository `main` HEAD is still commit **`0a6113ba3aa43da2ac1c9094977e181d3881f226`** (committer date 2026-11-05) — exactly the commit pinned by the wave-1 vendor snapshots. The wave-1 mirrored `apiClient.ts`/`asset.ts`/`pool.ts` snapshots (Git blob SHA-1 table in wave-1) therefore remain byte-current.
- API page still states: "Currently, there are no limits for DEX API use." (self-imposed budgets unchanged) and base URL `api.ston.fi`.

## "STON.fi v2" — what v2 actually is (wave-2 finding)

- **There is no REST API v2.** The current API reference documents only `/v1/...` paths (plus `/export/...`). The string "v2" appears in the reference only as a filter parameter (`dex_v2`: Boolean to filter V2 pools/routers) and in DEX-v2 fee-vault endpoint names.
- DEX v2 exists as **on-chain contracts** documented at `docs.ston.fi/developer-section/dex/smart-contracts/v2` (Router, Pool, LpAccount, LpWallet, Vault, op-codes, message flows) and in the SDK (`dex/sdk/v2`, `dex/sdk/swap`). Contract-level integration is out of radar scope (no transaction building, no signing).
- Radar pool discovery is unaffected: `GET /v1/assets` and `GET /v1/pools` (the pinned decode contracts) are still documented verbatim.

## Drift records (additive to wave-1; nothing overwritten)

1. `DRIFT_RECORDED` (docs surface): the Statistics family now additionally documents **`GET /v1/stats/stake`** (wave-1 listed `/v1/stats/dex`, `/v1/stats/pool`, `/v1/stats/operations`, `/v1/stats/fees`, `/v1/stats/fee_accruals`, `/v1/stats/fee_withdrawals`). The radar's legacy `GET /v1/stats` poll and its fail-closed `SCHEMA_ERROR` handling are unchanged; the wave-1 `DRIFT_RECORDED_NEEDS_LIVE_PIN` record for plain `/v1/stats` **still stands** (plain `/v1/stats` remains undocumented in the current reference).
2. `DRIFT_RECORDED` (docs surface vs SDK method shapes): the reference now documents **`POST /v1/assets/query`**, **`POST /v1/assets/search`** and **`POST /v1/pools/query`** (with "`/v1/pool/query` remains for backward compatibility"). Wave-1 recorded the SDK query methods; the npm registry corroborates POST semantics (package version 0.27.0 is deprecated "due to invalid POST body for a /v1/assets/query endpoint"). The radar does not call any query/search endpoint, so no decoder is affected.
3. `DRIFT_RECORDED` (docs build number): wave-1 recorded "docs build v1.168.0"; the current docs pages no longer expose a build/version number to automated capture. The docs-build pin method (footer build id) is recorded as `MISSING_PIN` this wave; pin currency is instead established through the SDK commit + npm dist-tag above.

## Radar consequence

- `StonRadarIngestor` poll surface (`assets`, `pools`, `stats` round-robin + optional Omniston enrichment) is unchanged and remains schema-pinned by the wave-1 snapshots, now re-verified current.
- No new STON.fi endpoint is enabled. No `/export/...`, wallet, farm, transaction or simulator endpoint is in radar scope.
