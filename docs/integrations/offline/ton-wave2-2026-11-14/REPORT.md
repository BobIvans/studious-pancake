# TON wave-2 report — source pins, verification results, atomicity evidence

**Wave label:** `ton-wave2-2026-11-14` — branch `agent/ton-radar-wave2`, base `e2b65c0ceefdc6f9f99cdc0187ff23dc7815acc8` (merge of #620, TON wave-1)
**Retrieval session:** 2026-11-14 UTC. Documentation/specification verification only. **Zero live TON RPC/API calls from repository code or tests**; pytest runs offline (`pytest-socket`). No provider enabled, no execution primitive claimed.

## Per-source status table

| Source | Wave-2 status | What was pinned / verified | Delta vs wave-1 |
|---|---|---|---|
| STON.fi DEX REST | `PINNED_CURRENT` | REST surface still all `/v1/`; no REST v2 exists ("v2" = on-chain contracts + `dex_v2` filter param); `@ston-fi/api` latest still 0.33.0 (2026-10-30, MIT), repo HEAD still `0a6113ba3aa43da2ac1c9094977e181d3881f226` — wave-1 vendor snapshots byte-current; "Currently, there are no limits for DEX API use." unchanged | Additive drift records: `GET /v1/stats/stake` newly documented; query/search endpoints now documented as POST; plain `/v1/stats` still undocumented (wave-1 drift stands); docs-build number no longer exposed (`MISSING_PIN` on the build-id pin method) |
| Omniston RFQ | `PINNED_CURRENT` | `stonfi.omni.v1beta8` still "the current API namespace"; v1beta7 listed as Legacy only; environments unchanged (`wss://omni-ws.ston.fi`, `omni-grpc.ston.fi:443`, sandbox counterparts) | None functional. New `MISSING_PIN`: official Omniston SDK package/version (radar does not import any SDK) |
| Tonco | `MISSING_PIN` (refined from wave-1 `BLOCKED_MISSING_PIN`) | Official docs: Tonco is a concentrated-liquidity AMM ("First CLAMM DEX on TON", Algebra), **not an orderbook**; GraphQL indexer `https://indexer.tonco.io` + testnet; farming REST `GET api-farming.tonco.io/apr`; SDK `@toncodex/sdk@mainnet` (repo `cryptoalgebra/tonco-sdk` HEAD `a7f2c9c6...`, MIT, no versioned release); router addresses V1/V1.6/V2 pinned | Still no radar adapter — GraphQL schema unpinned, typed `MISSING_PIN` seam in `ton_radar.py`; Tonco candidates keep arriving via swap.coffee `dexes` enum (already decoded fail-closed) |
| TON Center v2 | `PINNED_CURRENT` (spec level) | Live spec `https://toncenter.com/api/v2/openapi.json` mirrored + SHA-256 `5e5ee5...999b`; spec "TON HTTP API C++" v2.1.17-7e98895 (OpenAPI 3.1.1, 37 paths); auth `X-API-Key` header / `?api_key=` query; `TonlibResponse`/`TonlibErrorResponse` envelopes; `getAddressInformation` -> `raw.fullAccountState` and `runGetMethod` contracts pinned | Wave-1 `BLOCKED_MISSING_PIN` on method schemas **resolved at spec level**; spec-path drift recorded (`swagger.json` 404 -> `openapi.json`); still no state adapter (live capture unauthorized) |
| TonAPI v2 | `PINNED_CURRENT` (spec level) | Official spec `tonkeeper/opentonapi` `api/openapi.yml` @ `acd5268222651503ef048a86b446aa345c5934f9` mirrored + SHA-256 `c42e75...7880` + Git blob SHA-1 `ec4d5d4...77b`; spec v2.0.0 (OpenAPI 3.0.0); auth `Authorization: Bearer` (official tonkeeper/tonapi README); `GET /v2/accounts/{account_id}` -> `Account` schema; lt-cursor pagination (`after_lt`/`before_lt`/`limit`/`sort_order`); free tier 1 RPS | Wave-1 missing pins (a) response schema (b) auth header (c) pagination **all resolved at spec level**; still no state adapter |
| TON atomicity | `PINNED_CURRENT` (negative evidence) | Typed `ATOMICITY_RESEARCH` note: official docs pin one-account transactions, actions+bounce phases (no whole-chain rollback), multi-transaction traces (`n` transactions >= `n-1` messages); Omniston settlement is escrow/order infrastructure, not an atomic borrow primitive | New: formal negative baseline with typed gaps (`MISSING_PIN`: no verbatim official "no flash loans" sentence; docs.ton.org pages are URL+date captures, unversioned) |

Counts: 5 `PINNED_CURRENT`, 1 `MISSING_PIN` (Tonco schema), 0 `PINNED_STALE`, 0 `BLOCKED_*` new (wave-1 live-capture blocker remains in force for all sources).

## Code changes (bounded, additive)

- `src/discovery/dynamic_universe/ton_radar.py`: module docstring extended with the wave-2 boundary; new frozen research-metadata mapping `TON_SOURCE_PIN_STATES` (wave-2 sources only, typed states). **No behavior change** — no new adapter, no new source, no new decode path; `_REPLAY_SOURCES` unchanged; all envelopes remain `TON_ASYNC_MULTI_CONTRACT` / `DISCOVERY_ONLY` / `executable=False`.
- New tests in `tests/test_ton_radar_wave2.py` (additive; no existing test modified): pin-state registry consistency vs the manifest, Tonco `MISSING_PIN` enforcement, absence of any wave-2 adapter/replay registration, and unchanged frozen research-only constants.

## Explicit note on TON execution claims

**TON stays research-only.** No local-atomic settlement primitive is proven: TON's official execution model (one account per transaction; outgoing messages delivered as separate later transactions; failures surfaced via the bounce phase rather than whole-chain rollback) admits no native flash-loan primitive, and no official source documents one. The typed negative baseline lives in `TON_ATOMICITY_RESEARCH.md`; any future TON financing edge must refute it with its own versioned dossier and fail-closed qualification. Routing/quote APIs are never atomic-flash evidence.

## Blockers (typed)

- `BLOCKED(LIVE_CAPTURE_NOT_AUTHORIZED)` — all TON sources; wave 2 made no live provider request.
- `MISSING_PIN` — Tonco GraphQL indexer schema; versioned Tonco SDK release; official Omniston SDK package version; verbatim official "no flash loans" statement; docs.ton.org page version pins (URL+date only); STON.fi docs build number (no longer exposed).
