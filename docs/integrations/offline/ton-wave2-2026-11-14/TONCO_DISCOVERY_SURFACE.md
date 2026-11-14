# TONCO — discovery surface contract extract (wave-2)

**Retrieved:** 2026-11-14 UTC
**Canonical URLs:** https://docs.tonco.io/en/ (official docs), https://docs.tonco.io/en/technical-reference/integration-faq.html (official integration FAQ), https://github.com/cryptoalgebra/tonco-sdk (official SDK repository)
**Classification correction vs the wave-2 task hypothesis:** official documentation describes TONCO as a **concentrated-liquidity AMM, not an orderbook DEX**. Verbatim (docs.tonco.io): TONCO is "a decentralized exchange (DEX) on TON Blockchain that introduces concentrated liquidity", the "First CLAMM DEX on TON", "Developed by Algebra Team". The wave-1 record ("SDK-only; no REST schema") is confirmed and refined below.

## Official SDK pin

- Repository: `cryptoalgebra/tonco-sdk` (GitHub), default branch `main`, HEAD commit `a7f2c9c60d5599a941da1a5ea4ca4b786e1a48ee` (commit dated 2025-10-24; repository `pushed_at` 2026-08-04T09:37:39Z), license **MIT**.
- Distribution: no npm release / no GitHub releases; the official README installs a dist-tag: `npm install @toncodex/sdk@mainnet`. No versioned release pin exists.
- What the SDK wraps: on-chain contract getters via `@ton/ton` `TonClient` — `getPoolStateAndConfiguration()`, `GetPositionInfo()`, `get_nft_address_by_index()`, `getCollectedFees`, `getMintEstimate`, `getSwapEstimate`; plus swap simulation (`SwapSimulator`) and message creation (`PoolMessageManager`). Message/transaction building is out of radar scope.
- Contract-version constants in the SDK: `DEX_VERSION.v1` and `DEX_VERSION.v1_6`.

## Documented discovery surfaces (integration FAQ, verbatim paths)

1. **GraphQL indexer (pools/positions):** `https://indexer.tonco.io` (mainnet), `https://testnet-indexer.tonco.io` (testnet). The FAQ documents the endpoints but **no GraphQL schema document, no field list and no pagination contract** was captured this wave. Typed `MISSING_PIN` (GraphQL schema): no Tonco row decoder may be written from these URLs alone.
2. **Farming backend (REST, one documented shape):** `GET https://api-farming.tonco.io/apr?pool=<pool address>` returning an `apr` value plus a `farmings` array (active when `rewardsLeft` is not zero). Farming APR is REFERENCE_ONLY metadata, never pool state.
3. **On-chain get-methods** (via SDK or TonClient): listed above. These are liteserver-level contract reads, not an HTTP market-data API.

## Contract addresses (verbatim from the official FAQ)

Mainnet: Router V1 `EQC_-t0nCnOFMdp7E7qPxAOCbCWGFz-e3pwxb6tTvFmshjt5`; Router V1.6 `EQBt0NCO16Ng6QqOb8YaRcnV_vzIAfbLKhMMBBZpYNUbl3sB` (described as "a valid but demosissioned router"); Router V2 `EQAT0nCO20vC6gzpyUJbWI7ELnRvAAB3VHJ3Z1jXQsw6KGJ4`; ProxyTON/ProxyGRAM V1 `EQCUnExmdgwAKADi-j2KPKThyQqTc7U650cgM0g78UzZXn9J`; ProxyTON/ProxyGRAM V2 `EQBwGRAMjTY_CMNWKhzBeHA-VPjp2rD9vB3rwepG2co5eScs`. Testnet: Router V1 `kQDnfag9lHlc0rS6YeI7WwRq-3ltcKSsYxLiXmveB7gNU4jE`; Router V1.6 `kQBGCWvd9WaV39yYG4KTWnkx8AwtP4iHIGETdOnxGhTRUVa5`.
Display note (official): Toncoin -> Gram is a display-only rename as of June 15, 2026; same addresses and contracts.

## Limits and auth

No rate limits and no authentication are documented on the captured Tonco pages. A "no published limit" statement is a priority hint, never an unbounded polling license.

## Radar consequence

- TONCO keeps **no radar adapter** in wave 2. The wave-1 `BLOCKED_MISSING_PIN` is refined but not resolved: the GraphQL indexer schema is not pinned, and the REST surface is farming-APR only. The typed seam in `src/discovery/dynamic_universe/ton_radar.py` records `MISSING_PIN`.
- Tonco candidates continue to enter the research universe through the swap.coffee aggregator `dexes` enum (`provider_dex="tonco"`), which is already decoded fail-closed by `normalize_swap_coffee_payload`.
- No swap/message building, no settlement, no live capture is in scope.
