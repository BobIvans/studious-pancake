# TON state providers wave-2 — TON Center v2 and TonAPI v2 method contracts (spec-pinned)

**Retrieved:** 2026-11-14 UTC
**Purpose:** resolve the wave-1 `BLOCKED_MISSING_PIN` records for method contracts, auth header and pagination of the two main TON state-read providers. Both are now pinned at the **official machine-readable specification** level, mirrored offline. No live TON RPC/API call was made; no state adapter is enabled by this wave.

## TON Center (v2)

- **Spec pin:** `GET https://toncenter.com/api/v2/openapi.json` — this is the file the official swagger UI (`https://toncenter.com/api/v2/`) loads (`url: '/api/v2/openapi.json'`). Note: wave-1 probed `swagger.json` (404); the live spec path is `openapi.json` (drift record vs wave-1 probe notes, no contract impact).
- **Mirrored snapshot:** `vendor-reference/toncenter-v2/openapi.json`, SHA-256 `5e5ee5641c6cdbcb9b3d8436a865aec61a2e87e7ae4c544beb7427c2c0ce999b` (261,206 bytes). Spec `info`: title **"TON HTTP API C++"**, version **"v2.1.17-7e98895"**, `openapi: 3.1.1`, 37 paths. Provider-side license: **not stated in the spec** (`license: not stated in spec file; provider terms apply`).
- **Auth (verbatim from spec `securitySchemes`):** `APIKeyHeader` — "API key header of the form `X-API-Key: <token>`"; `APIKeyQuery` — "API key query parameter of the form `?api_key=<token>` ... Equivalent to the header method." Keys are per-network (docs.ton.org/api/rate-limit, wave-1 pin).
- **Rate limits:** unchanged from wave-1 (`docs.ton.org/api/rate-limit`: anonymous 1 RPS; Free 10 RPS; Plus 25 RPS aggregated; Advanced 100 RPS; 429 body `{"ok": false, "result": "Ratelimit exceed", "code": 429}`).
- **Success envelope (`TonlibResponse`, required `["ok", "result", "@extra"]`):** `ok: boolean`; `result` "Only present when `ok` is `true`" (string / TonlibObject / array); optional `jsonrpc`, `id` (`JsonRpcResponse` allOf). **Error envelope (`TonlibErrorResponse`, required `["ok", "error", "code"]`):** `ok` always `false`; `code` "HTTP status code. Common values: 404 (not found), 409 (conflict), 422 (validation error), 429 (rate limit), 500 (server error), 504 (timeout), 542 (liteserver error)."
- **State-read methods now pinned (subset relevant to future research):**
  - `POST /api/v2/getAddressInformation` -> `TonlibResponse` with result `raw.fullAccountState` (`AddressInformation`, required `["@type", "balance", "extra_currencies", "code", "data", "last_transaction_id", "block_id", "frozen_hash", "sync_utime", "state"]`; `balance` is Int256 "Account balance in nanotons as a decimal string. 1 TON = 1,000,000,000 nanotons.").
  - `POST /api/v2/getExtendedAddressInformation`, `POST /api/v2/getWalletInformation`, `POST /api/v2/getTokenData` (jetton master/wallet data) — same `TonlibResponse` envelope.
  - `POST /api/v2/runGetMethod` — request `RunGetMethodRequest` (required `["address", "method", "stack"]`; `method` is a get-method name string or numeric ID; `stack` is TVM entries `["num"|"cell"|"slice", value]`; optional `seqno`); result `RunGetMethodResult` (required fields include `@type`, `gas_used`, `stack`, `exit_code`, `block_id`, `last_transaction_id`). A `runGetMethodStd` variant exists.
- **Consequence:** the wave-1 TON Center `BLOCKED_MISSING_PIN` (method schemas) is resolved at specification level. A state-view adapter is still **not** added: live-capture authorization remains outstanding, and provider-reported state is never exact chain state.

## TonAPI (tonapi.io, REST v2)

- **Spec pin:** `https://raw.githubusercontent.com/tonkeeper/opentonapi/master/api/openapi.yml`, linked verbatim from the official REST API docs page (`https://docs.tonapi.io/tonapi/rest-api`): "the full Swagger specification is available on GitHub".
- **Mirrored snapshot:** `vendor-reference/opentonapi/openapi.yml`, SHA-256 `c42e755ccf0e99fb798224da8a2b7a3400c568f18579b81a51bbd8edf0c87880` (292,623 bytes), upstream Git blob SHA-1 `ec4d5d4cd40aef6df52acef3228c05e66c5ae77b` at `tonkeeper/opentonapi` `master` commit `acd5268222651503ef048a86b446aa345c5934f9` (committer date 2026-10-19). License **MIT** (mirrored `vendor-reference/opentonapi/LICENSE`, blob `fdb7079858d6a7302ef6b49fd1c3068899b9743d`). Spec `info`: title "REST api to TON blockchain explorer", **version 2.0.0**, `openapi: 3.0.0`; servers `https://tonapi.io`, `https://testnet.tonapi.io`.
- **Auth (official repo README, `tonkeeper/tonapi`):** "an **Authorization** header should be passed to access the method" with the value shape `Bearer <JWT-like token>` (verbatim example header `'Authorization': 'Bearer '+serverSideKey`). This resolves the wave-1 missing auth-header pin.
- **Rate limits:** free tier default "1 request per second (1 RPS)" per `https://docs.tonapi.io/tonapi/dapp/free-limits` ("a default rate limit of 1 request per second (1 RPS)"; a valid key is required even when proxied). Paid tiers Start 1 / Lite 10 / Standart 100 / Plus 300 / Heavy 1000 RPS were pinned in wave-1 and are unchanged in this wave's re-check of the official page family.
- **Method contracts now pinned (subset relevant to future research):**
  - `GET /v2/accounts/{account_id}` -> `Account` (required `["address", "balance", "status", "last_activity", "get_methods", "is_wallet"]`; properties also include `extra_balance`, `currencies_balance`, `interfaces`, `name`, `is_scam`, `icon`, `memo_required`, `is_suspended`; `balance` is `int64`).
  - `GET /v2/accounts/{account_id}/jettons` -> `JettonsBalances` (required `["balances"]`; `JettonBalance` properties `balance`, `price`, `wallet_address`, `jetton`, `defi_asset`, `extensions`, `balance_lt`, `lock`).
  - `GET /v2/blockchain/accounts/{account_id}/transactions` -> `Transactions`; pagination parameters are **`after_lt`, `before_lt`, `limit`, `sort_order`** (logical-time cursor pagination). This resolves the wave-1 "cursor-based per swagger (not pinned)" record.
- **Consequence:** the wave-1 TonAPI `BLOCKED_MISSING_PIN` records — (a) response schema, (b) API-key header name, (c) pagination semantics — are resolved at specification level. No TonAPI adapter is added; live-capture authorization remains outstanding.

## Boundary (unchanged from wave 1)

- Both providers are state-read/research evidence only. `429` handling must preserve `Retry-After` and never retire a market; unknown is not zero; provider-reported balances/reserves are never exact chain state; no decoder may be written from anything but the pinned specs above.
- No adapter, poller or state-view was added in wave 2. The pinned contracts exist so that a future, separately-approved adapter wave can implement fail-closed decoders against these exact snapshots with offline replay fixtures.
