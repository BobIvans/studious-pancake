# Rango — Basic API (single step), Solana + Sui: offline contract extract

**Flag:** OFFICIAL_CONTRACT_EXTRACT_ONLY
**Official sources (retrieved 2026-11-14 UTC, see manifest):**
- Docs index: https://docs.rango.exchange/llms.txt (all pages below have `.md` variants)
- API key & rate limits: https://docs.rango.exchange/api-integration/api-key-and-rate-limits.md
- Get Quote: https://docs.rango.exchange/api-integration/basic-api-single-step/api-reference/get-quote.md
- Create Transaction (Swap): https://docs.rango.exchange/api-integration/basic-api-single-step/api-reference/create-transaction-swap.md
- Sample transactions: https://docs.rango.exchange/api-integration/basic-api-single-step/sample-transactions.md
- Fee structure: https://docs.rango.exchange/technical/fee-structure.md
- Monetization (Basic API): https://docs.rango.exchange/api-integration/basic-api-single-step/monetization.md
- API troubleshooting/error codes: https://docs.rango.exchange/api-troubleshooting.md
- OpenAPI JSON schema file is linked from the API Reference page (`/files/EsrXvOjOsHXzDUhQUtOC`); not downloaded this wave (typed note in manifest).

## Hosts and authentication (credential names only)

- Public test key host: `https://public-api.rango.exchange`
- Private key host: `https://api.rango.exchange`
- Auth: the API key is attached to **every request as a query parameter** `apiKey=<YOUR-API-KEY>` (official example: `'https://public-api.rango.exchange/path/to/resource?apiKey=<YOUR-API-KEY>'`). It is a query param, not a header.
- Keys are requested via a ticket on the `users-support` channel of Rango's Discord. The docs publish a public test API key with "a fixed low rate limit... should not be used in production". This dossier records the credential NAME (`apiKey`) only; the published test-key literal is in official docs and is not a secret, but this repo stores no values.
- Enterprise dedicated endpoints exist ("isolate their API calls").

## Rate limits (published policy, unpublished numbers)

"We provide our API free of charge to our B2B partners, but it comes with default rate limits per IP and API key. If you require custom rate limits, please get in touch." Numeric default limits are NOT published (UNKNOWN; typed acquisition row). Server-side callers "requiring us to whitelist your servers' IPs or increase your rate limit per IP" — i.e. per-IP throttling is active even with a key.

## Quote semantics — ECONOMIC QUOTE

`GET {host}/basic/quote` params (required): `from`, `to` (asset ids like `SOLANA.SOL`, `SOLANA.USDC--EPjFW...`), `amount` ("machine readable amount" in base units). Optional: `slippage` (percent; "if you don't send it, it will assume 0.5% slippage"), `referrerCode`, `referrerFee` (percent), `swappers`, `swappersExclude`, `swapperGroups`, `swappersGroupsExclude`, `contractCall`, `sourceContract`, `destinationContract`, `imMessage`, `messagingProtocols`, `avoidNativeFee`, `enableCentralizedSwappers` (requires passing user IP for compliance; KYC hold risk).

Cross-chain routing is Rango's core; single-step same-chain Solana/Sui swaps are a subset of the same endpoints.

## Swap semantics — INSTRUCTION BUNDLE (type-tagged per chain)

`GET {host}/basic/swap` adds required `slippage`, `fromAddress`, `toAddress`; optional `disableEstimate` (true skips server-side balance/fee validation and is "much slower" when false — the doc's wording is inverted for response time; read as: estimate validation costs time), `referrerAddress`, `referrerFee`, route filters.

Official Solana response shape (`sample-transactions.md`): `"tx": { "type": "SOLANA", ..., "instructions": [ ], "recentBlockhash": null, "signatures": [ ], ... }`
- "List of instructions" — a **Solana instruction bundle** for client-side message assembly, not a serialized transaction.
- `recentBlockhash` "Nullable. Filled only if message is already partially signed"; `signatures` likewise.
- Broadcast note: "Remember to broadcast the signed transaction to Solana RPCs with **base64** encoding. The base58 encoding is deprecated."
- Versioning: "All supported routes for Solana are `VERSIONED` transactions except a special case of converting `SOL` to `WSOL` or vice versa via Solana Wrapper."
- EVM responses carry `approveData`/`approveTo` (approval bundling); other chain types include `SUI` ("For SUI transactions") — the exact SUI tx sub-shape was NOT extracted this wave (typed note).

Build-output class: **chain-typed unsigned instruction bundle** (`type` discriminator), route fields returned alongside.

## Fees

- `referrerFee` (percent units; "1.12 means 1.12 percent"): "the maximum amount fee you could charge the user is 3 percent... The default fee is 10 bps or 0.1 percent."
- Rango's own share: "When using Rango Public Test API Key or Private API Key, Rango typically adds a 0.15% fee on top of the affiliate fee."
- Solana affiliate fee charging is "not yet available for all dApps due to its complexity and is not ready for public use"; the affiliate program does not currently support Solana, Cosmos, Tron chains (fee-structure page warning).
- Swapper fees are charged by underlying protocols, not Rango; Rango dApp itself is zero-fee. Fee token selection on cross-chain routes can move fees to a more stable/high-market-cap asset.
- On-chain fee collection mechanics inside instructions: not documented on reviewed pages (UNKNOWN).

## Route expiry / freshness

- `1303`: "The route has expired... occurs if the integrator attempts to create the transaction more than 5 minutes after the quote response... we recommend doing so within 1 minute due to high rate fluctuations."

## Error semantics (published taxonomy)

Responses carry `{error, errorCode, traceId}`; four-digit codes `{category}{type}`:
- 11xx server: `1101` internal error, `1102` underlying-protocol exception
- 12xx validation: `1201` bad request, `1202` input outside swapper min/max (response returns the thresholds), `1203` wallet-balance retrieval failure, `1204` invalid tx hash, `1205` token not found, `1206` unsupported/wrong-type blockchain
- 13xx routing: `1301` loss > 18% of input USD value, `1302` quote/create amount discrepancy, `1303` route expired (5-minute window), `1304` no valid route
- 14xx authentication (`1401` invalid credentials), 15xx KYC
HTTP-level 429 behavior is not documented on the reviewed page (typed note; only numeric limits are unknown, backoff policy is integrator-side).

## Comparison requirements

Rango must be treated as a **swapper-attributable** aggregator: preserve per-route `swappers`/`swapperGroups` attribution and any returned route venue IDs so Rango observations can be mapped onto the Jupiter/Titan/OKX/underlying-DEX correlation groups. Rango is also a Sui surface (`tx.type=SUI`) — same rule applies there against Cetus/FlowX/7K/Aftermath groups (see `PROVIDER_OVERLAP_NOTES.md`). Same canonical assets, exact base-unit `amount`, same public `fromAddress`, percent-vs-bps slippage conversion explicit, quote created within the 1–5 minute window.

## Safety boundary

`/basic/swap` output is an unsigned instruction bundle: assemble/decode offline as evidence only. Never sign, never broadcast (the docs' base64-broadcast note is integrator-side guidance, not authorization). Never enable `enableCentralizedSwappers` (KYC/IP compliance surface) during qualification. `sign_enabled=false`, `send_enabled=false`.

## Missing / unpinned items (typed)

1. Numeric default rate limits: UNKNOWN (policy published, numbers not).
2. SUI `tx` sub-shape fields: NOT_PINNED_THIS_WAVE.
3. OpenAPI JSON schema file (`/files/EsrXvOjOsHXzDUhQUtOC`): NOT_DOWNLOADED_THIS_WAVE.
4. On-chain fee-collection instruction layout: UNKNOWN.
