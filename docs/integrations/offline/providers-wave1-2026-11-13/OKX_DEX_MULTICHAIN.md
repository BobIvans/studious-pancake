# OKX DEX API — Solana (chainIndex 501) + Sui surface: offline contract extract

**Flag:** OFFICIAL_CONTRACT_EXTRACT_ONLY
**Official sources (retrieved 2026-11-14 UTC, see manifest):**
- Solana quick start: https://web3.okx.com/onchainos/dev-docs/trade/dex-use-swap-solana-quick-start
- Get Quotes reference: https://web3.okx.com/onchainos/dev-docs/trade/dex-get-quote
- Get Solana Swap Instructions: https://web3.okx.com/onchainos/dev-docs/trade/dex-solana-swap-instruction
- Swap API error codes: https://web3.okx.com/onchainos/dev-docs/trade/dex-error-code
- Official binary repo: https://github.com/okx/dex-solana-binary (noted, not pinned this wave)

## Base URL and endpoints

Base: `https://web3.okx.com` (Onchain OS docs examples; older `develop.okx.com` / `www.okx.com/web3/build/docs` surfaces redirect into this).

| Purpose | Method | Path |
|---|---|---|
| Economic quote | GET | `/api/v6/dex/aggregator/quote` |
| Swap build (serialized tx) | GET | `/api/v6/dex/aggregator/swap` |
| Solana instruction assembly | GET | `/api/v6/dex/aggregator/swap-instruction` |
| Simulation (whitelist-only) | POST | `/api/v6/dex/pre-transaction/simulate` |
| Gas/compute limit (POST) | POST | `/api/v6/dex/pre-transaction/gas-limit` |
| Broadcast (whitelist-only) | POST | `/api/v6/dex/pre-transaction/broadcast-transaction` |
| Order tracking | GET | `/api/v6/dex/post-transaction/orders` |
| Swap history | GET | `/api/v6/dex/aggregator/history` |

Solana `chainIndex` = `501`; SOL token address `11111111111111111111111111111111`; USDC `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`.

## Authentication (credential names only — never values)

Headers (exact names, from the official quick-start `getHeaders`):
- `OK-ACCESS-KEY`
- `OK-ACCESS-SIGN` — Base64 of `HmacSHA256(timestamp + method + requestPath + (queryString || body), secretKey)`
- `OK-ACCESS-TIMESTAMP` — ISO timestamp
- `OK-ACCESS-PASSPHRASE`

The 7K SDK's OKX provider additionally names a `projectId` (see `SEVENK_BLUEFIN7K_SUI.md`); the reviewed OKX pages themselves do not document a project-ID header — recorded as a known asymmetry, value UNKNOWN.

## Quote endpoint semantics — ECONOMIC QUOTE

`GET /api/v6/dex/aggregator/quote` returns route economics, no transaction. Documented request parameters include: `chainIndex`, `amount` (smallest unit; meaning depends on `swapMode`), `fromTokenAddress`, `toTokenAddress`, `swapMode` (`exactIn` default; `exactOut` EVM-only; `maxIn` Solana-only), `dexIds`, `excludeDexIds`, `forJitoBundle`, `excludePoolAddresses` (up to 20), `directRoute` (Solana-only, default false), `singleRouteOnly`, `singlePoolPerHop`, `assetAwareRouting`, `priceImpactProtectionPercent` (default `90`), `feePercent` (referrer commission of fromTokenAmount; "max percentage: 10 for Solana, 3 for all other chains"; up to 9 decimals).

Response: `chainIndex`, `swapMode`, `dexRouterList[]` (with `dexProtocol.dexName`, `percent`, `fromTokenIndex`/`toTokenIndex`, `router`), `fromTokenAmount`, `toTokenAmount`, `tradeFee` ("Estimated network fee (USD) of the quote route"), `estimateGasFee` (smallest units), `priceImpactPercent` ("(Received value – Paid value) / Paid value"), `fromToken`/`toToken` (incl. `tokenContractAddress`, `tokenSymbol`, `tokenUnitPrice` may be null, `decimal` "for reference only", `isHoneyPot`, `taxRate`), `dexName`, `amountOut`.

Note: this endpoint has no `slippage` parameter; slippage belongs to the swap/build endpoints.

## Swap-instruction endpoint semantics — INSTRUCTION BUNDLE

`GET /api/v6/dex/aggregator/swap-instruction` ("Obtain transaction instruction data for redemption or custom assembly in Solana"). Required: `chainIndex`, `amount`, `fromTokenAddress`, `toTokenAddress`, `userWalletAddress`, `slippagePercent`, `swapMode` (`exactIn`/`maxIn`). Optional highlights: `autoSlippage`, `maxAutoSlippagePercent`, `maxCalldataSize`, `maxAccounts`, `swapReceiverAddress`, `closeAuthorityAddress` (Solana-only, mutually exclusive with `swapReceiverAddress`), `feePercent`, `fromTokenReferrerWalletAddress`, `toTokenReferrerWalletAddress`, `positiveSlippagePercent`/`positiveSlippageFeeAddress` (whitelist/enterprise only), `computeUnitPrice`, `computeUnitLimit`, `disableRFQ`, `forJitoBundle`, route filters.

Response: `instructionLists[]` (each `{data` base64, `accounts[]` `{isSigner, isWritable, pubkey}`, `programId`}), `addressLookupTableAccount[]`, `createTokenAccountList`, `routerResult` (same economics shape as quote, `estimateGasFee` in smallest units), `tx` (`from`, `to`, `minReceiveAmount`, `slippagePercent`), `wsolRentFee`.

Build-output class: **unsigned instruction bundle + ALT list** (custom assembly).

## Swap endpoint semantics — SERIALIZED UNSIGNED TRANSACTION

`GET /api/v6/dex/aggregator/swap` returns `data[0].tx.data` as a **base58-encoded serialized transaction** (quick start decodes then `VersionedTransaction.deserialize(...)`, falling back to legacy `Transaction.from(...)`). The quick start marks setting a fresh blockhash as "CRITICAL!": `transaction.message.recentBlockhash = recentBlockHash.blockhash` — i.e. the returned tx's blockhash is not guaranteed fresh, and the caller signs locally. Build-output class: **serialized unsigned transaction** (with mandatory local blockhash refresh).

## Fee fields

- `feePercent` (quote + swap-instruction): integrator/referrer commission on the **from** token; max 10% Solana / 3% other chains; separate `fromTokenReferrerWalletAddress` / `toTokenReferrerWalletAddress` on swap-instruction.
- `tradeFee` in responses is "Estimated network fee (USD) of the quote route" (gas estimate, not an LP/platform fee).
- `wsolRentFee` (swap-instruction response) — rent component.
- LP fee breakdown per venue: not exposed as a dedicated field on reviewed pages (UNKNOWN; `taxRate` on token objects is a token-transfer-tax field, 0.01 = 1%).

## Rate limits / errors (published)

From the official Swap API error-code page:
- `50011` / HTTP 429 — "Rate limit reached. Please refer to API documentation and throttle requests accordingly" (the only documented rate-limit signal; per-tier numeric quotas not published).
- Auth (HTTP 401): `50103`–`50113` (empty/invalid key, empty/incorrect passphrase, empty/invalid sign/timestamp, invalid signature).
- Parameter (HTTP 400): `50014` (param cannot be empty), `51000` (param error).
- Business (HTTP 200 body codes): `82000` insufficient liquidity, `82104` unsupported token, `82105` unsupported chain, `82102`/`82103` below-minimum/above-maximum, `80005` "Not enough Sui objects under the address for swapping" (documents an active Sui swap surface), `80000` repeated request, `50026`/500 system error, `0`/200 success.

## Sui surface

OKX DEX is a named Sui provider downstream (7K MetaAg exposes an OKX provider requiring `apiKey`/`secretKey`/`apiPassphrase`/`projectId`), and error code `80005` is Sui-specific. The Sui-specific quote/build path parameters were NOT extracted this wave (typed blocker in manifest acquisitions): no live calls, no assumptions.

## Comparison requirements

Same canonical mints + exact base-unit amount + same public `userWalletAddress` (required) + same slippage representation (`slippagePercent` here vs `slippageBps` elsewhere — convert explicitly, never silently) + bounded time skew. Preserve `dexRouterList` (venue identity + percent) as correlation evidence; OKX routes overlap Jupiter/Titan/0x route venues and must not be counted as independent liquidity (see `PROVIDER_OVERLAP_NOTES.md`).

## Safety boundary

`simulate` and `broadcast-transaction` endpoints are whitelist-only ("available to our whitelisted customers only") — out of scope. Returned serialized tx / instructions are evidence only: never sign locally with real keys, never submit. MEV protection (`extraData.enableMevProtection`, optional `jitoSignedTx`) is documented as an experimental third-party feature — excluded from P0 comparisons.

## Missing / unpinned items (typed)

1. Numeric per-tier rate quotas: UNKNOWN (only 50011/429 published).
2. Sui chainIndex + Sui quote/build parameter contract: NOT_PINNED_THIS_WAVE.
3. OpenAPI/machine-readable spec for these endpoints: not located on reviewed pages.
4. Auth request-schema for 7K-style `projectId`: OKX docs pages reviewed do not name it (UNKNOWN).
