# CAM-03: source identity crosswalk and docs recheck (2026-11-22)

PR #679 lane `campaign-data-sources`. Official docs recheck only — no endpoint
health check, no provider activation, no capture. Per owner-review point 6:
`checked_at` here means **docs-pin freshness** (dossier `require_current`
semantics); it does NOT mean the API endpoint was operationally observed.

## 1. Four-way identity crosswalk

| Approved-plan id (V2/#671) | Catalog id (`market_source_catalog.json`) | DiscoveryRequest id (`src/market/discovery.py:39-44`) | Adapter | Endpoint (code, pinned) | Operator/correlation |
|---|---|---|---|---|---|
| `dexscreener` | `dexscreener` | `dexscreener` | `CatalogDiscoveryAdapter` (requires `token_mint`) | `https://api.dexscreener.com/token-pairs/v1/solana/{mint}` | dexscreener / dexscreener-indexed |
| `geckoterminal` | `geckoterminal` | `geckoterminal` | `CatalogDiscoveryAdapter` | `https://api.geckoterminal.com/api/v2/networks/solana/pools` | geckoterminal / geckoterminal-indexed |
| `raydium_api_v3` (docs-only alias) | `raydium` (family amm-tool) | `raydium` | `CatalogDiscoveryAdapter` (requires `required_program_id`) | `https://api-v3.raydium.io/pools/info/list` | raydium / raydium-indexed |
| `meteora_dlmm_data` (docs-only alias) | `meteora-dlmm` | `meteora-dlmm` | `CatalogDiscoveryAdapter` | `https://dlmm.datapi.meteora.ag/pools` | meteora-dlmm / meteora-dlmm-indexed |

Additional spellings recorded (NOT aliases in code; mapping is documentation
only until a registry alias owner with tests exists):
- `raydium-indexer` — `config/qualification/din00-source-status.json` (DIN-00 status vocabulary).
- `raydium_sdk_v2` — `docs/integrations/offline/solana-p0/SOURCE_MANIFEST.json` (offline P0 dossier).

Canonical registry IDs are NOT renamed (review point 6): the DiscoveryRequest
closed set stays `{dexscreener, geckoterminal, raydium, meteora-dlmm}`; the
V2/#671 spellings are plan-layer labels whose crosswalk mapping lives here.

## 2. Official docs recheck (retrieved 2026-11-22T10:37:27Z)

Raw fetched bytes and SHA-256 (kept out of git by size; hashes are the pins):

| Source | Official docs URL (pinned) | Bytes | SHA-256 |
|---|---|---|---|
| DexScreener | `https://docs.dexscreener.com/api/reference` | 677 383 | `31ffb19b28eabdf39f68801b622f23a83f220a09cda78db610bdb09515ab0180` |
| GeckoTerminal (via CoinGecko docs) | `https://docs.coingecko.com/reference/introduction` | 144 118 | `ef32801458b105de5ca8b960d67d0d3bd448fcbf5cb7e004e9cbdaa38e3b9302` |
| Raydium API V3 | `https://api-v3.raydium.io/docs/` (Swagger UI shell) | 3 748 | `16c4e2adaa51fca04d52f34ad1782bfafc75e7d37892b499ad288b815b6ebdb1` |
| Meteora DLMM reference | `https://docs.meteora.ag/developer-guides/dlmm/api-reference/overview.md` | 5 817 | `974fe594580a62e58b7995ebf7ee893cf0412ce6e39325eee03b00071a2850fd` |

Findings and dispositions:

- **DexScreener** — docs reachable; route `/token-pairs/v1/solana/{mint}`
  matches the pinned code endpoint. Documented rate limits were NOT
  re-confirmed from the current docs content in this pass → quota semantics
  stay UNKNOWN (fail-closed), no historical limit inferred.
- **GeckoTerminal** — the previously pinned `www.geckoterminal.com/dex-api`
  and `api.geckoterminal.com/docs/index.html` redirect/drift to CoinGecko
  docs; the official-docs pin is updated to
  `docs.coingecko.com/reference/introduction` (catalog `evidence_urls` and
  dossier `official_docs`). Historic "30/min" limit NOT confirmed from
  current source → stays UNKNOWN. Endpoint pinned in code
  (`api.geckoterminal.com/api/v2/networks/solana/pools`) unchanged.
- **Raydium API V3** — docs root reachable (Swagger UI); the OpenAPI spec is
  rendered dynamically and no static spec file could be pinned this pass
  (`/openapi.json`, `/swagger.json`, `/docs/openapi.{json,yaml}` do not serve
  a machine-readable spec). Route `/pools/info/list` remains the pinned code
  endpoint; spec extraction is recorded as a limitation, not fabricated.
  Terms of use remain at `https://raydium.io/terms-of-use/` (not re-fetched
  here; semantics unchanged).
- **Meteora DLMM** — the previously hardcoded docs URL
  `docs.meteora.ag/api-reference/dlmm/overview` is now **404**; current
  official reference is
  `docs.meteora.ag/developer-guides/dlmm/api-reference/overview.md`, which
  documents base `https://dlmm.datapi.meteora.ag`, `GET /pools`, parameters
  `page` / `page_size` (pools ≤ 1000) / `query` / `sort_by` / `filter_by`,
  and **"All DLMM APIs have a rate limit of 30 requests per second (30 RPS)"**.
  No auth stated; pricing/terms NOT stated on the page → cost semantics stay
  UNKNOWN (fail-closed). The endpoint matches the existing adapter code
  (`discovery.py:81`) exactly.

No status was promoted to CURRENT beyond the docs pins themselves; all four
sources remain DISCOVERY_ONLY / `public-rate-limited`, quota/cost semantics
UNKNOWN where not confirmed, and no operational endpoint check was performed
(reviews point 6). If docs or terms become inaccessible, the dossier status
is typed BLOCKED, never silently CURRENT.

## 3. Changes carried by this PR

- `config/qualification/representative-sources.json`: all four sources; fresh
  `checked_at` = 2026-11-22T10:37:27+00:00; refreshed `docs_sha256` pins;
  `schema_fingerprint` = digest of the current adapter `schema_contract()`
  (three existing fingerprints unchanged, meteora-dlmm added with its own).
- `src/resources/market_source_catalog.json`: `checked_at` 2026-11-22;
  GeckoTerminal `evidence_urls` repinned to the current CoinGecko docs.
- `src/solana_parallel_radar/cli.py`: **NOT edited** — the file is a
  byte-hash-pinned research reference
  (`RESEARCH_REFERENCE_REVIEW_HASH_MISMATCH` on integration CI); the stale
  Meteora docs URL refresh requires a coordinated review-hash update.
  Recorded as a backlog task (owner: radar/pin lane).
