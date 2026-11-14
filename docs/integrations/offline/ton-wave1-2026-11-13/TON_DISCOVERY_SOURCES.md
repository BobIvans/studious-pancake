# TON discovery sources — contracts and polling budgets

**Retrieved:** 2026-11-14 (UTC, date granularity; retrieval session documented in `SOURCE_MANIFEST.json`)
**Classification:** discovery only. Every source below enumerates an overlapping but distinct subset of TON markets; no single aggregator is the whole TON universe.

## Source inventory

| Source | Transport | Verified surface | Pagination | Auth | Published limits | Radar budget |
|---|---|---|---|---|---|---|
| STON.fi DEX API v1 | HTTPS `https://api.ston.fi` | `GET /v1/assets` (`asset_list`), `GET /v1/pools` (`pool_list`), stats drift recorded | whole-universe lists, no pagination documented | none documented | "Currently, there are no limits for DEX API use." (self-imposed budget still required) | round-robin cursor over (assets, pools, stats), budget <= 4 calls/poll incl. optional enrichment |
| Omniston | JSON-RPC 2.0 over WebSocket / gRPC | `stonfi.omni.v1beta8.QuoteRpc.Quote` + notifications `ack`/`quote_updated`/`no_quote`/`keep_alive` | subscription streams | none captured | none captured | injected read-only reader only; 1 enrichment call per poll, only when budget remains and pools were seen |
| DeDust API v2 | HTTPS `https://api.dedust.io/v2` | `GET /v2/pools` -> bare array | none documented (full list) | none documented | none captured | 1 whole-universe capture per poll (`budget in {0,1}`), record/byte bounds enforced |
| swap.coffee Aggregator v1 | HTTPS `https://backend.swap.coffee` | `GET /v1/pools?blockchains=ton&trusted=false&size&page` -> `{total_count, pools}` | `page`/`size` (size 1..100) | public; optional `X-Api-Key` for heavy use | ~1 request/second per IP self-published; 429 beyond that | <= 4 pages per poll (page cursor), size <= 100 |
| TONCO | SDK-only (cryptoalgebra/tonco-sdk) | none published as REST | n/a | n/a | n/a | no adapter (BLOCKED_MISSING_PIN); candidates arrive via swap.coffee `dexes` enum |
| TON Center | HTTPS v2/v3 | rate limits + 429 envelope verified; method schemas not pinned | per-method | API key plans | 1 RPS anonymous; free 10 RPS; plus 25 RPS aggregated | no state adapter this wave |
| TonAPI (tonapi.io) | HTTPS v2 | base URL + endpoint families + tiers verified; response schemas not pinned | cursor-based per swagger (not pinned) | key header not captured | Start free RPS 1; Lite 10; Standart 100; Plus 300; Heavy 1000 | no state adapter this wave |

## Self-imposed budget rules (binding for all TON radar adapters)

1. A published "no limits" or "acceptable load" statement is a priority hint, never an unbounded polling license.
2. Every poll carries an explicit integer budget (0..4), a bounded request timeout (0..60s], and `max_attempts=1` per blind window so each failure stays separately observable.
3. Every response passes through record-count and provider-payload bounds; a page over budget fails closed as `SCHEMA_ERROR` negative evidence with the raw payload preserved.
4. HTTP 429, transport errors, timeouts and provider exceptions are recorded as durable negative evidence with `Retry-After` preserved; exception text is never persisted (may contain credentials).
5. A failed page never retires a market: retirement requires a complete fresh capture with non-negative evidence, and replay validates hashes before any record is re-derived.
6. TON is asynchronous and multi-contract: no record here is a local atomic flash-capital edge; `execution_class=TON_ASYNC_MULTI_CONTRACT`, `verification_state=DISCOVERY_ONLY`, `executable=False` are frozen in every envelope.

## Cross-venue identity conventions

- Canonical identity: `canonical_ton_address` normalizes raw (`workchain:64hex`) and friendly (CRC16-verified, mainnet-tag) addresses to `workchain:hex`. Testnet tags are refused.
- Pool records use `record_id ton:ston:<pool>` / `ton:dedust:<pool>` / `ton:swapcoffee:<pool>` and share `correlation_group=ton:pool:<pool>` so the same underlying pool address seen through different aggregators is recognized as shared liquidity, never as independent confirmation.
- DeDust native-coin asset rows have no address (`assets[].type == "native"`); the radar records the reserved marker `ton:native` and never invents an address for it.
