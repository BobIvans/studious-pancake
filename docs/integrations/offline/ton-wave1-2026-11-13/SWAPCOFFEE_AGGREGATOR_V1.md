# swap.coffee Aggregator API v1 — contract extract (pools read path)

**Retrieved:** 2026-11-14 UTC
**Canonical URLs:** https://docs.swap.coffee/technical-guides/aggregator-api (REST API at backend.swap.coffee/swagger-ui), OpenAPI entity page https://docs.swap.coffee/technical-guides/aggregator-api-openapi/entity/returns-list-of-pools-which-correspond-to-the-given-params, docs index https://docs.swap.coffee/llms.txt
**Base URL:** `https://backend.swap.coffee/`
**Auth:** "Our API is public, which means it allows unauthorized access." Heavier users request an API key via the official Typeform; key endpoints use the `X-Api-Key` header.
**Published limits (verbatim):** "We believe that the average load of 1 request per second per IP is more than acceptable." Exceeding yields `429 Too Many Requests`. The radar self-imposes <= 4 pages per poll with a page cursor.

## `GET /v1/pools` (verbatim from the OpenAPI entity page; operationId `getPools`)

Query parameters: `blockchains` (array of enum, `ton`), `dexes` (array of enum: e.g. `stonfi`, `dedust`, `coffee`, `tonco`, ...), `trusted` (boolean, default `true` — "Returns only those pools which are trusted by DEXes or community"), `with_active_boosts`, `recently_created`, `with_liquidity_from`, `search_text`, `order` (`tvl|volume|apr`), `descending_order` (default true), `in_groups`, `size` (integer, default 10, **min 1 max 100**), `page` (integer, default 1, min 1). Pagination uses `page`/`size`, not `limit`/`offset`.

Response `200`: `{"total_count": ..., "pools": [{"pool": ApiPoolInfo, "info": Statistics}]}`. Errors: `{"error": "..."}`.

### ApiPoolInfo (verbatim required/optional)

- required: `dex`, `address`, `type` (enum `public|private|slumbering|invalid`), `amm_type` (`constant_product|cubic_stable|curve_fi_stable|concentrated_v3|tonstakers|weighted_constant_product|weighted_stable|bidask|moon_dlmm|bidask_damm|dedust_v2`), `tokens`, `reserves`, `fees`
- optional: `amm_settings`, `restrictions`, `unavailable_until` ("UTC unix timestamp in seconds")
- `tokens[]`: `address{blockchain, address}` + `metadata{name, symbol, decimals, listed, verification: whitelisted|blacklisted|community|unknown, image_url?}`
- `fees`: `average_gas` (required), `divider`, `input`, `output`, `first_token`, `second_token`
- `reserves`: array of doubles (provider-reported, not exact chain state)

### Statistics (`info`, verbatim required)

`address`, `tvl_usd`, `volume_usd`, `fee_usd`, `apr`, `lp_apr`, `boost_apr`; optional `locked_asset_amount`.

## Radar decode contract (`normalize_swap_coffee_payload`)

- Payload must be an object with integer/number `total_count` and array `pools`; rows over the record budget fail closed.
- Each row: `pool.address` passes `canonical_ton_address`; exactly two `tokens`; both token addresses pass `canonical_ton_address`; `pool.dex` is recorded verbatim as `provider_dex` (it is an aggregator label, not a chain identity — a Tonco pool seen here is still a Tonco candidate).
- Market records: `record_id=ton:swapcoffee:<pool>`, `venue="swap.coffee"`, `correlation_group=ton:pool:<pool>` so the same underlying pool address seen through STON/DeDust/swap.coffee is one shared-liquidity identity, never independent confirmation.
- The adapter requests `blockchains=ton` and `trusted=false` (explicit) to preserve the maximum research universe; provider verification labels are kept in `provider_metadata.tokens` verbatim, `identifier_verified=False` throughout.
- The adapter passes query parameters through the injected `Transport.request(..., params=...)` interface; the shared transport owns query sanitation. Repository transport policies default to `allow_url_query=False`, so enabling this source requires an explicit operator-configured policy for `backend.swap.coffee` — the adapter never smuggles a query string past the policy.

## Out of scope (explicit)

Route endpoints (`Returns the best route...`), pre-built transaction endpoints ("Returns pre-built transactions for the given route. It is assumed that transactions will be signed and sent by the sender via wallet"), route execution status, referral/auth-token management: none of these are called by the radar; no route/quote promotion to an exact graph, no transaction building.
