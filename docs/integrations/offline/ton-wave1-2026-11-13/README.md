# TON Wave-1 — offline technical dossier

**Prepared:** 2026-11-14 (wave label `ton-wave1-2026-11-13`)
**Purpose:** provide offline technical contracts for the bounded TON research radar: STON.fi REST (assets/pools/stats), Omniston RFQ, DeDust API v2 pools, swap.coffee aggregator pools, and the TON state providers (TON Center, TonAPI), with TONCO recorded as blocked.

## Read order

1. `SOURCE_MANIFEST.json` — canonical URLs, retrieval dates, API versions, verified fields, published limits, drift, blockers.
2. `TON_DISCOVERY_SOURCES.md` — discovery-source contracts and self-imposed polling budgets (STON.fi, DeDust, swap.coffee, Omniston, Tonco).
3. `STONFI_REST_V1.md` — current STON.fi REST v1 endpoint/response contracts and the `/v1/stats` drift record.
4. `OMNISTON_V1BETA8.md` — Omniston JSON-RPC-over-WebSocket contract (quote/read-only path only).
5. `DEDUST_API_V2.md` — DeDust `GET /v2/pools` response contract.
6. `SWAPCOFFEE_AGGREGATOR_V1.md` — swap.coffee `GET /v1/pools` request/response contract.
7. `TON_STATE_PROVIDERS.md` — TON Center v2/v3 and TonAPI v2 rate limits, 429 envelopes and the exact missing pins.
8. `vendor-reference/stonfi-api/` — official MIT SDK type/client snapshots pinned by upstream Git blob SHA-1.
9. `verify_offline_bundle.py` — zero-network verifier (see below).

## Important truth about offline completeness

- STON.fi response schemas are pinned through the **official** JS client `ston-fi/api` (`@ston-fi/api` 0.33.0, commit `0a6113ba3aa43da2ac1c9094977e181d3881f226`, MIT): `GET /v1/assets` returns `{"asset_list": [...]}` and `GET /v1/pools` returns `{"pool_list": [...]}`. Asset rows exist in a flat variant and a V2 variant with display fields wrapped in `meta{}`; the radar normalizer accepts both.
- **Drift:** plain `GET /v1/stats` is not in the current documented surface (docs build v1.168.0 documents `/v1/stats/dex`, `/v1/stats/pool`, `/v1/stats/operations`, `/v1/stats/fees`, ...). The radar keeps the legacy `{"stats": {...}}` decode contract with fail-closed schema errors until a live capture is authorized. This is recorded as `DRIFT_RECORDED_NEEDS_LIVE_PIN`.
- DeDust `GET /v2/pools` and swap.coffee `GET /v1/pools` are verified from their official documentation pages (field names quoted verbatim). DeDust returns a bare JSON array with **no documented pagination**; swap.coffee paginates with `page`/`size` (size max 100).
- Tonco publishes **no official REST schema** in its captured docs (SDK-only via `cryptoalgebra/tonco-sdk`). Its pools can still enter the research universe through the swap.coffee `dexes` enum. Typed `BLOCKED_MISSING_PIN`.
- TON Center and TonAPI rate limits and 429 envelopes are verified, but per-method state-read response schemas are **not pinned** this wave. No state adapter may decode unverified field layouts. Typed `BLOCKED_MISSING_PIN`.
- Omniston is pinned at namespace `stonfi.omni.v1beta8` (JSON-RPC 2.0 over WebSocket; production `wss://omni-ws.ston.fi`). The repository adapter keeps Omniston as an **injected read-only reader interface**; this owner never opens sockets, never builds transactions, never settles.

## Agent rules

1. Read this dossier before changing TON radar code. Never infer API fields from a ticker, UI, old adapter or an HTTP 200.
2. TON stays `TON_ASYNC_MULTI_CONTRACT` / `DISCOVERY_ONLY`. Never assume Solana-style atomicity; never assume one aggregator enumerates the whole TON universe (STON.fi, DeDust, swap.coffee, Tonco each enumerate overlapping but distinct subsets).
3. A "no published rate limit" statement (STON.fi) is **not** an unlimited polling license. Keep the self-imposed per-source budgets, round-robin cursors and backoff in the adapters.
4. Unknown is not zero: provider reserves/TVL/lastPrice are recorded verbatim as provider metadata with `state_verified=False`, never as exact chain state.
5. A failed page or schema error never retires a market; it is durable negative evidence (`RATE_LIMIT`, `HTTP_ERROR`, `TIMEOUT`, `TRANSPORT_ERROR`, `PROVIDER_ERROR`, `SCHEMA_ERROR`) with the raw payload preserved for replay.
6. No live TON capture, signing, sending, transaction building or settlement is in scope. Quotes/RFQ are candidate evidence only.

## Suggested local verification

From repository root:

```powershell
python docs/integrations/offline/ton-wave1-2026-11-13/verify_offline_bundle.py
```

The verifier is network-free. It checks every required file and all five mirrored ston-fi/api snapshots against the manifest SHA-256 pins and upstream Git blob SHA-1 values (`git hash-object`), validates the manifest structure and drift/blocker records, and prints SHA-256 audit digests. It does not perform live provider qualification.
