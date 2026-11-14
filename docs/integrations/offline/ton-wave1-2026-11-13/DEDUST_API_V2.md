# DeDust REST API v2 — contract extract

**Retrieved:** 2026-11-14 UTC
**Canonical URL:** https://docs.dedust.io/reference/getting-available-pools (operation id `getting-available-pools`); SDK docs at https://docs.dedust.io (TypeScript SDK `@dedust/sdk`, not mirrored, not used by the Python adapter).
**Base URL:** `https://api.dedust.io/v2`
**Auth:** none documented. **Published limits:** none captured — the radar self-imposes a single whole-universe capture per poll.

## `GET /v2/pools` (verbatim)

- Method/Path: `GET` `"/v2/pools"`.
- Query parameters: none defined in the official spec; no pagination (cursor/limit/offset) documented — the endpoint returns the full pool list.
- `200` -> `application/json`, a bare JSON **array** of pool objects.
- `400` -> empty JSON object `"{}"` (so an object payload is a schema error, not a valid empty universe).
- Official examples: `curl https://api.dedust.io/v2/pools` and `const pools = await dedustClient.getPools();` with `new DeDustClient({ endpointUrl: 'https://api.dedust.io/v2' })`.

## Pool object fields (verbatim names)

- `address` — e.g. `"EQDcm06RlreuMurm-yik9WbL6kI617B77OrSRF_ZjoCYFuny"` (friendly mainnet TON address).
- `lt` — e.g. `"40826635000009"` (last-transaction logical time as string).
- `totalSupply` — e.g. `"1682429759745607"` (string).
- `type` — e.g. `"volatile"`.
- `tradeFee` — e.g. `"1"`.
- `assets` — array; items: `{"type": "native"}` (no address) or `{"type": "jetton", "address": "<friendly>", "metadata": {"name", "symbol", "image", "decimals"}}`.
- `lastPrice` — e.g. `"3.3592561783648293975"` (string).
- `reserves` — array of strings, e.g. `"235087171534646"` (indexed by asset order).
- `stats` — object with `fees` and `volume`, each an array of strings (one per asset).

**Numeric encoding:** all numeric values are returned as strings. `reserves`, `lastPrice`, `totalSupply`, `stats` are provider-reported indexed values — recorded verbatim as provider metadata with `state_verified=False`; they are never exact chain state and never decimal-normalized locally.

## Radar decode contract (`normalize_dedust_payload`)

- Payload must be a JSON array of objects; length must not exceed the record budget (`max_records`, default 50,000) — overflow fails closed as `SCHEMA_ERROR` with the raw payload preserved.
- Each pool row must have exactly two assets; `type == "native"` maps to the reserved non-address marker `ton:native`; every jetton address passes `canonical_ton_address` (friendly CRC16 or raw form; mainnet tags only).
- `reserves` must be an array of two strings; pool `address` must be a valid canonical TON address; `address` identity deduplicates conflicting rows fail-closed ("duplicate TON identity disagrees").
- Market records: `record_id=ton:dedust:<pool>`, `venue="dedust"`, `correlation_group=ton:pool:<pool>` (shared-liquidity aliasing with STON/swap.coffee records for the same underlying pool address), provider fields (`type`, `tradeFee`, `lt`, `totalSupply`, `reserves`, `lastPrice`, `stats`) kept verbatim inside `provider_metadata`.
- The documented `400 -> {}` shape decodes as `SCHEMA_ERROR` ("missing pool array"), so an empty-object response is negative evidence, never an empty universe.
