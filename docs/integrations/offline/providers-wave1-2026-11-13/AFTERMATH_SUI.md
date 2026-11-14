# Aftermath — Sui Smart-Order Router + SDK: offline contract extract

**Flag:** OFFICIAL_CONTRACT_EXTRACT_ONLY + SDK pin
**Official sources (retrieved 2026-11-14 UTC, see manifest):**
- Docs index: https://docs.aftermath.finance/llms.txt
- Developer API: https://docs.aftermath.finance/for-developers/api.md
- Authorization/rate limits: https://docs.aftermath.finance/for-developers/api/rest-api/authorization.md
- Additional endpoints (router family): https://docs.aftermath.finance/for-developers/api/rest-api/auxiliary-endpoints.md
- Error handling: https://docs.aftermath.finance/for-developers/api/rest-api/error-handling.md
- TypeScript SDK: https://docs.aftermath.finance/for-developers/typescript-sdk.md and `.../typescript-sdk/products/router.md`
- SOR fees: https://docs.aftermath.finance/trade/smart-order-router/fees.md
- Production OpenAPI reference: https://aftermath.finance/docs/ (linked officially; not downloaded this wave — typed note)

## Scope note

Aftermath operates a full exchange family (perpetuals, AMM pools, DCA, limit orders, liquid staking afSUI). This dossier pins only the **spot router (Smart-Order Router)** surface needed for the Sui quote/PTB race. Perpetuals transaction builders under `/api/perpetuals/*` are explicitly out of scope here.

## Router endpoints (production, per official "Router Utilities" section)

```
GET  /api/router/supported-coins
POST /api/router/trade-route
POST /api/router/transactions/add-trade
POST /api/router/transactions/trade      # responds in production but ABSENT from OpenAPI declaration
```

Base host: `aftermath.finance` (paths above under `/api/...`; live updates use `wss://aftermath.finance/api/perpetuals/ws/updates`).

Endpoint facts (official):
- `trade-route` "requires `coinInType` and `coinOutType`. Send exactly one amount: `coinInAmount` for fixed input or `coinOutAmount` for fixed output." "Fixed-output routing requires `slippage`. Route filters, `externalFee`, and `referrer` remain optional."
- `transactions/add-trade` "composes a quoted `completeRoute` into an existing serialized transaction and returns `{ tx, coinOutId }`." "coinOutId uses SDK-style Sui argument casing such as `{ "Input": 0 }`, `{ "Result": 3 }`, or `{ "NestedResult": [2, 1] }`."
- `supported-coins` "returns a flat JSON array of Sui coin type strings... The response is large (92,803 entries, about 7.8 MB on 2026-08-22), so cache it instead of fetching it on a hot path." (Official docs state this size themselves — this is the same response-scale hazard that GPR-03 recorded as "Aftermath responses exceeded the bounded profile". Any intake must be bounded.)
- "supported-coins and transactions/trade respond in production but are absent from the OpenAPI declaration. `transactions/trade` has no documented request or response schema and no v3.3.1 SDK method; use `transactions/add-trade` until it does." — typed BLOCKED_MISSING_PIN for `/transactions/trade`.

## SDK semantics (aftermath-ts-sdk Router)

Initialization: `Aftermath.create({ network: "MAINNET" })` → `afSdk.Router()`. Router methods (SDK reference):
- `getCompleteTradeRouteGivenAmountIn({coinInType, coinOutType, coinInAmount (BigInt), referrer?, externalFee? {recipient, feePercentage: 0.01 = 1%}, protocolBlacklist?|protocolWhitelist?, poolBlacklist?|poolWhitelist?})` → complete route (economic quote)
- `getCompleteTradeRouteGivenAmountOut({...coinOutAmount, slippage...})` → exact-out route
- `getTransactionForCompleteTradeRoute({walletAddress, completeRoute, slippage, isSponsoredTx?})` → builds a **Sui Transaction (PTB)** for the route
- `addTransactionForCompleteTradeRoute({tx, completeRoute, slippage, walletAddress, coinInId?})` → **COMPOSABLE PTB**: composes the trade into the caller's existing `Transaction`, returns `{ tx, coinOutId }` ("swap can be performed before or after any logic within the existing transaction")

Build-output class: **economic quote (route) + composable Sui PTB** (both fresh-build and append-to-existing are official SDK methods).

SDK caveat (official warning block): production router endpoints are `trade-route`, `transactions/add-trade`, `supported-coins`; "Legacy SDK helpers such as `getVolume24hrs`, `searchSupportedCoins`, and `getInteractionEvents`... should not be assumed to work against the current public service"; `getSupportedCoins` calls `GET /api/router/supported-coins` and "The response is large: 92,803 coin types, about 7.8 MB, on 2026-08-22. Cache it rather than calling it on a hot path."

## Authentication / rate limits (published)

- "Default rate limit: 1000 requests per 10 seconds." (authorization.md — the only numeric quota published.)
- Increased limits via signed requests: ticket format `sui-address: <...>` / `rate-limit-requests: [<sdk-call>: <desired-rate-limit>]` on Discord. The authorization flow uses **local wallet signatures** (Ed25519/Secp256k1/Secp256r1 keypair examples with `@mysten/sui` cryptography) — credential names are Sui addresses/signatures; no API-key values. Exact signed-request header names were NOT extracted this wave (typed note; the authorization.md page contains the construction code but the full header mapping was not transcribed).
- Signed Requests page (`rest-api/authentication.md`) exists ("Wallet signatures and authentication requirements across the Aftermath API") — referenced, full contract NOT_PINNED_THIS_WAVE.

## Fees (official, SOR fees page)

- "Aggregator Fees are split into two categories: Protocol Fee and Integrator Fee."
- "No protocol fee is taken on trades performed through the Aftermath Smart-Order Router."
- Integrator fee: optional platform fee configurable per swap via `externalFee {recipient, feePercentage}` (SDK param; 0.01 = 1%). "When a fee is applied, Aftermath retains 2.5% of whatever platform fee is set, as part of its protocol overhead."
- "Trades performed on Aftermath.finance do not charge an Integrator Fee." Zero default fee when none configured.
- LP/venue-level fees of underlying pools are not broken out in the router response fields reviewed (UNKNOWN).

## Error semantics (official error-handling page)

- API error variants: `{error_code: number, message: string, short_message?: string|null}`, or `{error: string}`, or plain string, or null. Headers `X-Error-Code` (numeric) and `X-Error-Message` when present. "Preview errors use `{ error }` and set `X-Error-Message: true`."
- "Some preview routes can return HTTP `200` with an error payload... `data.error` is the primary signal. Do not depend on the header alone." (HTTP-200-wrapped failures — treat as failure, not success.)
- The error page's primary orientation is CCXT/perpetuals; router-specific error codes were NOT enumerated this wave (typed note).
- 429/Retry-After semantics for the router family: not extracted (UNKNOWN beyond the 1000 req/10s default).

## Correlation facts

`protocolBlacklist?: ["Cetus", "BlueMove"]` / `protocolWhitelist?: ["Aftermath", "Cetus"]` appear in official SDK examples: Aftermath routes over other named venues (Cetus, BlueMove, ...), and Aftermath itself is a protocol inside Cetus/FlowX/7K provider lists. One observation per provider is NOT independent evidence (see `PROVIDER_OVERLAP_NOTES.md`).

## Safety boundary

Routes/PTBs are evidence only: never sign, never execute, never use `isSponsoredTx`/sponsor flows during qualification. Bounded intake mandatory for `supported-coins` (official 7.8 MB scale). `sign_enabled=false`, `send_enabled=false`.

## Missing / unpinned items (typed)

1. `POST /api/router/transactions/trade` schema: BLOCKED_MISSING_PIN (officially absent from OpenAPI; official guidance is to use `add-trade`).
2. Production OpenAPI document download (https://aftermath.finance/docs/): NOT_DOWNLOADED_THIS_WAVE.
3. Signed-request header names for increased rate limits: NOT_PINNED_THIS_WAVE.
4. Router-family explicit 429 code list: UNKNOWN.
5. SDK `aftermath-ts-sdk` package version at verification time: npm page not fetched this wave; docs say "npm i aftermath-ts-sdk" and reference an SDK version "v3.3.1" in the router-endpoint warning — exact current package.json version UNKNOWN (acquisition row recorded).
