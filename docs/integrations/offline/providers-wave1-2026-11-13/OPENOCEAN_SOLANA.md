# OpenOcean — Solana Meta-Aggregator Swap API: offline contract extract

**Flag:** OFFICIAL_CONTRACT_EXTRACT_ONLY + typed BLOCKED_MISSING_PIN rows (see manifest `acquisitions`)
**Official sources (retrieved 2026-11-14 UTC, see manifest):**
- Solana Swap API overview: https://docs.openocean.finance/docs/solana-swap-api
- Swap API V4 index: https://docs.openocean.finance/docs/swap-api/v4
- Swap API guide: https://docs.openocean.finance/docs/swap-api/guide
- Prerequisites (rate limits/429): https://docs.openocean.finance/docs/skills/prerequisites
- Official examples repo: https://github.com/openocean-finance/OpenOcean-API-Examples (`frontend/src/pages/SwapSol.js`, official Solana demo)

## What OpenOcean is on Solana (official statement)

"OpenOcean provides a high-performance Solana Meta-Aggregator Swap API designed to deliver the best execution for Solana token swaps", integrating "liquidity from the two major Solana Dex aggregators - Jupiter and Titan". This is the single most important correlation fact for this provider: an OpenOcean Solana quote is a Jupiter/Titan composite view, not independent venue depth (see `PROVIDER_OVERLAP_NOTES.md`).

## Access model

- "OpenOcean charges zero API fees for Solana swaps"; integrators get a fee split — "OpenOcean will share 20% of the fees by default".
- Solana API access is for **whitelisted users with an API key** (supported-chains overview; API key obtained by contacting OpenOcean DevRel/BD — official pointer: Telegram group `t.me/De1_API`).
- Default rate limit: "It's 2RPS by default" (Solana overview). The skills prerequisites page states the same number as the free tier and documents backoff: "If you receive a 429 (rate limit) or 5xx (server error) response, wait briefly before retrying", lengthening waits progressively.

## Authentication — typed blocker on exact header name

The exact HTTP header name used to present the API key was NOT verified from a primary page this wave. A WebSearch summary attributes `api-key: <key>` to OpenOcean docs, but no reviewed primary page names the header, and the official `SwapSol.js` example performs unauthenticated GETs without showing the header. Recorded as **BLOCKED_MISSING_PIN** in the manifest with an exact acquisition entry. Never assume a header name from this dossier.

## Endpoints (V4)

Base: `https://open-api.openocean.finance`

| Purpose | Method | Path |
|---|---|---|
| Quote | GET | `/v4/:chain/quote` |
| Reverse quote | GET | `/v4/:chain/reverseQuote` |
| Swap (build) | GET | `/v4/:chain/swap` |
| Token list | GET | `/v4/:chain/tokenList` |
| Dex list | GET | `/v4/:chain/dexList` |
| Gas price | GET | `/v4/:chain/gasPrice` |
| Transaction status | GET | `/v4/:chain/getTransaction` |
| Decode input data | GET/POST | `/v4/:chain/decodeInputData` |
| Swagger UI | GET | `/v4/swagger-ui.html` |

Chain slug for Solana: the official example code uses `chainId = 'solana'` in the URL template `/v4/${chain.chainId}/quote`; a WebSearch result references `/v4/sol/...`. The exact accepted slug set is **BLOCKED_MISSING_PIN** (acquisition entry; verify against the Swagger UI/official page before any adapter). Do not assume.

A machine-readable OpenAPI document was not reachable: `https://open-api.openocean.finance/v4/v3/api-docs`, `/v4/api-docs`, `/v3/api-docs`, `/v4/openapi.json` all returned HTTP 404 (probed 2026-11-14, public unauthenticated). **BLOCKED_MISSING_PIN** — exact response schema must be captured from the Swagger UI or official docs before adapter work.

## Quote semantics — ECONOMIC QUOTE

Official Solana example params: `inTokenAddress`, `outTokenAddress`, `amountDecimals`, `slippage`, `gasPrice`. (V4 index note: "We are deprecating `amount` and `gasPrice`. Use `amountDecimals` and `gasPriceDecimals` respectively.")

Documented response shape (guide): "inToken, outToken, inAmount, outAmount, estimatedGas, path, price_impact, etc."; the example reads `data.data.outAmount`. `"estimatedGas in the response is only a reference"` (official note).

## Swap/build semantics — SERIALIZED UNSIGNED TRANSACTION

Official `SwapSol.js`: the `/swap` GET params add `account`; the response is `res.data.data.data` and the code does:

```js
if (res.isVersioned) { transaction = VersionedTransaction.deserialize(Buffer.from(data, 'hex')); }
else { transaction = Transaction.from(Buffer.from(data, 'hex')); }
```

Build-output class: **serialized unsigned transaction, hex-encoded** (versioned or legacy, with an explicit `isVersioned` discriminator). The wallet signs; the example sends the raw transaction to an RPC. A search-level summary states the Solana `/swap` build is available to paid subscribers only — consistent with the whitelisted-access model, but the exact entitlement tier is NOT verified on a primary page (recorded UNKNOWN in acquisitions).

## Fee/referral fields

- V4 SwapQuote section documents `referrer` / `referrerFee` with a **0.01%–5%** fee range (V4 index page).
- Solana overview page describes on-chain referral-fee collection "configurable up to 3%" — the 3% vs 5% discrepancy between pages is recorded verbatim here; the binding Solana limit is **BLOCKED_MISSING_PIN** (verify on the Solana swap page once whitelisted).
- The displayed `amountOut` when a commission/referrer is configured: Cetus-style display-only warnings are not documented for OpenOcean on reviewed pages (UNKNOWN).

## Comparison requirements

Because OpenOcean Solana is a composite of Jupiter + Titan routes, any OpenOcean observation must be tagged to the same correlation group as Jupiter V2 and Titan; preserve `path`/`data` route evidence (the returned serialized tx can be decoded offline to recover venue program IDs without submission — offline decode only). Same canonical mints, exact base-unit amount, same public `account`, same slippage representation (`slippage` percent-style per official example: `slippage: 0.5` = 0.5%), bounded time skew.

## Safety boundary

The `/swap` response is an unsigned serialized transaction: decode offline for evidence; never sign; never broadcast via any RPC; never call `getTransaction`-style tracking in production mode during qualification. `sign_enabled=false`, `send_enabled=false`.

## Missing / unpinned items (typed — exact rows in manifest acquisitions)

1. Auth header name for API key presentation: BLOCKED_MISSING_PIN.
2. Machine-readable OpenAPI spec: BLOCKED_MISSING_PIN (404s recorded).
3. Accepted Solana chain slug (`sol` vs `solana`): BLOCKED_MISSING_PIN.
4. Solana `/swap` entitlement tier (paid-subscriber scope): UNKNOWN (search-level only).
5. Binding Solana referral-fee cap (3% vs 5% across pages): BLOCKED_MISSING_PIN.
