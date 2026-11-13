# Solana indexed discovery sources — P0-1

Reviewed: 2026-11-13. These APIs are for **candidate discovery / metadata only**. The official URLs, contracts and version caveats are also recorded in `SOURCE_MANIFEST.json`.

## DEX Screener API

Official reference: https://docs.dexscreener.com/api/reference

Useful public GET endpoints:
- `GET /latest/dex/search?q={query}` — pair search.
- `GET /latest/dex/pairs/{chainId}/{pairId}` — pair detail.
- `GET /token-pairs/v1/{chainId}/{tokenAddress}` — all pairs for a token.
- `GET /tokens/v1/{chainId}/{tokenAddresses}` — up to 30 token addresses per request.

Published limits in the current reference:
- pair/search/token endpoints: 300 requests/minute;
- profiles, boosts, community takeovers, ads and orders: 60 requests/minute.

Useful response metadata includes `chainId`, `dexId`, `pairAddress`, base/quote token addresses, `liquidity`, price and activity fields. Only canonical chain/pair/token addresses are candidate keys. Never bind by `symbol` or `name`.

**Boundary:** response liquidity/price is indexed metadata, not slot-consistent vault balances, tick/bin state or an executable exact-in quote. Keep this source in the discovery tier and verify every pool directly on-chain.

## Raydium API V3

Official docs:
- Overview: https://docs.raydium.io/api-reference/api-v3/overview
- REST service conventions: https://docs.raydium.io/sdk-api/rest-api
- Mainnet host: `https://api-v3.raydium.io`
- Devnet host: `https://api-v3-devnet.raydium.io`

Useful read endpoints include:
- `GET /pools/info/ids` — pool details by exact pool ids;
- `GET /pools/info/list` and `/pools/info/list-v2` — indexed pool lists;
- `GET /pools/info/mint` — pools related to token mints;
- `GET /pools/key/ids` — pool key/config metadata;
- `GET /mint/ids` and `/mint/list` — mint metadata.

The current docs describe a response envelope with success/error information and note 429 + `Retry-After`; pool API cache/freshness varies by endpoint. The narrative REST page and endpoint overview do not state one uniform TTL (they describe 5–60 seconds for most API v3 reads and 1–5 minutes for some overview paths). Treat API data as stale-able discovery metadata and pin the actual endpoint's OpenAPI response/TTL when integrating it.

**Boundary:** use the Raydium API to find candidate pool ids and hydrate metadata; fetch actual pool, vault, mint and tick accounts over RPC for exact state. Do not use the API's liquidity sort value as exact available depth.

## Meteora DLMM Data API

Official sources:
- Data API overview: https://docs.meteora.ag/developer-guides/dlmm/api-reference/overview
- Production API: `https://dlmm.datapi.meteora.ag`
- Production Swagger: https://dlmm.datapi.meteora.ag/swagger-ui/
- Program account model: https://docs.meteora.ag/developer-guides/dlmm/program/accounts
- SDK reference: https://docs.meteora.ag/developer-guides/dlmm/typescript-sdk/reference

The current overview states a limit of 30 requests/second. This is an indexed, read-only discovery layer. Use it for pool candidates and metadata; it does not replace the on-chain `LbPair`, vault, active BinArray, BinArrayBitmapExtension, Oracle and dynamic-fee reads described in `DIRECT_STATE_RAYDIUM_ORCA_METEORA.md`.

## GeckoTerminal API V2

Official reference: https://api.geckoterminal.com/docs/index.html  
OpenAPI: https://api.geckoterminal.com/docs/v2/swagger.json  
Base URL: `https://api.geckoterminal.com/api/v2`

Current documentation identifies API V2 as beta and recommends explicitly setting:
`Accept: application/json;version=20230203`.

Current documented characteristics:
- approximately 10 public API calls/minute (may fluctuate with network traffic);
- endpoints are cached for about 1 minute;
- published data may update 2–3 seconds after a confirmed transaction, subject to network availability.

Earlier repository notes referring to 30 calls/minute are stale relative to this current official reference. Start with a conservative local request budget and re-check before any live campaign. Do not turn a beta contract into a fixed assumption.

**Boundary:** GeckoTerminal is an indexing source. It cannot establish exact account state, pool owner, token program or amount-specific executable output.

## Manifest and Sanctum

Existing GPR source pins for Manifest and Sanctum live in:
`config/qualification/gpr02-solana-contracts.json`.

- Manifest upstream repository pin in the existing manifest: `CKS-Systems/manifest`; verify the exact mainnet program/account contract and current stats endpoint before new live reads.
- Sanctum list/pool source pins are already present in the GPR source contract file. Treat the LST list as identity discovery only; assert mint, owner, decimals, pool and program using RPC.

If these source contracts are not locally mirrored with a checked source manifest, they are still **source-pinned references**, not a full offline provider dossier.

## P0-1 quota policy

Use repository Source Governance as the only request admission owner. Per-source quotas should be lower than published provider maximums and must be configuration-controlled. Preserve 429/Retry-After, failures, empty responses and malformed rows. Never refresh a docs timestamp or TTL without rechecking the official current contract.
