# STON.fi DEX REST API v1 — contract extract

**Retrieved:** 2026-11-14 UTC
**Canonical URLs:** https://docs.ston.fi/developer-section/dex/api and https://docs.ston.fi/developer-section/dex/api/reference (docs build **v1.168.0**); official JS client https://github.com/ston-fi/api (`@ston-fi/api` **0.33.0**, commit `0a6113ba3aa43da2ac1c9094977e181d3881f226`, pushed 2026-11-05, MIT).
**Base URL:** `https://api.ston.fi`
**Auth:** none documented for discovery endpoints.
**Published limits:** "Currently, there are no limits for DEX API use." — self-imposed budgets still apply.
**Explorers:** Swagger UI https://api.ston.fi/swagger-ui/ and Redoc https://api.ston.fi/redoc (spec JSON URL not publicly discoverable this wave; `docs/swagger.json`, `openapi.json`, `swagger.json` all returned 404).

## Endpoints relevant to the radar (verbatim from official SDK `apiClient.ts` @ 0a6113ba)

- `GET /v1/assets` -> `{"asset_list": AssetInfoResponse[]}` (`apiClient.ts` line ~53: `await this.apiFetch<{ asset_list: AssetInfoResponse[] }>(... "/v1/assets" ...)`)
- `GET /v1/assets/query` -> `{"asset_list": AssetInfoV2Response[]}` (filters: search_term, sort_by, limit)
- `GET /v1/pools` -> `{"pool_list": PoolInfoResponse[]}` (`apiClient.ts` line ~201)
- `GET /v1/pools/by_market/{asset0Address}/{asset1Address}` and `GET /v1/pools/query` -> `{"pool_list": PoolInfoResponse[]}`
- `GET /v1/assets/{address}`, `GET /v1/pools/{address}`, `GET /v1/routers`, `GET /v1/markets`, farm/wallet/transaction families, swap/liquidity simulators.

### AssetInfoResponse (flat variant, verbatim required/optional fields)

`balance?`, `blacklisted`, `community`, `contract_address`, `decimals` (number), `default_symbol`, `deprecated`, `dex_price_usd?`, `display_name?`, `image_url?`, `kind` (`Ton|Wton|Jetton|NotAnAsset`), `priority`, `symbol`, `taxable`, `third_party_price_usd?`, `wallet_address?`, `popularity_index?`, `tags[]`, `custom_payload_api_uri?`, `scale?`, `extensions?`.

### AssetInfoV2Response (V2 variant)

`contract_address`, `kind`, `balance?`, `dex_price_usd?`, `meta?{decimals?, symbol?, display_name?, image_url?, custom_payload_api_uri?}`, `native_apr?`, ... The radar normalizer accepts both variants: flat `symbol` and `meta.symbol` wrapper.

### PoolInfoResponse (verbatim required/optional fields)

`address`, `apy_1d?`, `apy_7d?`, `apy_30d?`, `collected_token0_protocol_fee`, `collected_token1_protocol_fee`, `deprecated`, `lp_account_address?`, `lp_balance?`, `lp_fee`, `lp_price_usd?`, `lp_total_supply`, `lp_total_supply_usd?`, `lp_wallet_address?`, `popularity_index?`, `protocol_fee`, `protocol_fee_address`, `ref_fee`, `reserve0`, `reserve1`, `router_address`, `tags?`, `token0_address`, `token0_balance?`, `token1_address`, `token1_balance?`, `underlying_apr?`, `volume_24h_usd?`, `amp?`, `rate?`, `w0?`.

Amounts are strings in smallest units ("1 TON = \"1000000000\""). `reserve0/reserve1` are provider-reported indexed values, never exact chain state.

## Stats drift record (`DRIFT_RECORDED_NEEDS_LIVE_PIN`)

- Current documented stats endpoints (docs v1.168.0): `GET /v1/stats/dex`, `/v1/stats/pool`, `/v1/stats/operations`, `/v1/stats/fees`, `/v1/stats/fee_accruals`, `/v1/stats/fee_withdrawals` (fee endpoints cover DEX v2 vaults only; external DEX routes such as DeDust/TONCO are excluded from them).
- The official SDK 0.33.0 calls only `/v1/stats/operations`, `/v1/stats/fees`, `/v1/stats/fee_withdrawals`; it never calls plain `/v1/stats`.
- The radar's existing poll of `GET /v1/stats` with the `{"stats": {...}}` decode contract is therefore **legacy**: it is kept with fail-closed `SCHEMA_ERROR` handling. Migration to `/v1/stats/dex` requires a live capture (BLOCKED(LIVE_CAPTURE_NOT_AUTHORIZED) this wave) because its exact response schema was not captured.

## Snapshot pinning

Mirrored inert reference snapshots from the official SDK (MIT) with upstream Git blob SHA-1 pins verified by `verify_offline_bundle.py`:

| Local snapshot | Upstream blob SHA-1 |
|---|---|
| `vendor-reference/stonfi-api/asset.ts` | `7e5846c17019f27016aaf943cc26dcfcc4a528eb` |
| `vendor-reference/stonfi-api/pool.ts` | `ecc7d121f00cb4c3009459731d7d6a27cc57365f` |
| `vendor-reference/stonfi-api/apiClient.ts` | `345f2b3cfd2f722d5724994d665b5a1bccec9ec1` |
| `vendor-reference/stonfi-api/package.json` | `6ca8a846a825b24b4fc512eba38a792cc791d89f` |
| `vendor-reference/stonfi-api/LICENSE` | `97f4b94251791be7a63a9d256423e131c8df2fa7` |

These are reference snapshots, not runtime dependencies; the Python adapter does not import any SDK.
