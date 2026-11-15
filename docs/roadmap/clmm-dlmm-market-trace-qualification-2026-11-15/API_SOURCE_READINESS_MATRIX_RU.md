# API / source readiness matrix — Solana CLMM + DLMM trace

**Purpose:** one place for Codex/operator to see what can be wired into the existing pipeline and what still needs explicit permission, credentials, rooted evidence or source closure. This is not a claim that any API has been activated.

| Source | Endpoint / role | Access/auth & limits | Existing repo owner | Readiness | Must not be used as |
|---|---|---|---|---|---|
| DEX Screener | GET /latest/dex/search?q=..., /latest/dex/pairs/solana/{pairId}, /token-pairs/v1/solana/{mint}, /tokens/v1/solana/{mints} | Public limited; documented pair/search endpoints up to 300 rpm; token profile endpoints lower | PR #561 src/market/discovery.py, source catalog | Documented + bounded discovery adapter in repo; no live campaign claim | Exact output, depth, rooted state, executable liquidity |
| Raydium API V3 | GET https://api-v3.raydium.io/pools/info/ids, /pools/info/mint, /pools/info/list-v2, /pools/key/ids, /main/clmm-config, /main/clmm-dynamic-config | Public API; endpoint-specific quotas/SLA must be rechecked; no guaranteed free SLA | PR #561, source catalog; native decoder owns direct state | Discovery/config/reference metadata path exists; exact amounts must use RPC account state + decoder | Exact swap output or current pool liquidity at size |
| Meteora DLMM Data API | Official DLMM pools/index API (documented base https://dlmm.datapi.meteora.ag, pool listing/pagination) | Public limited; existing repo source inventory records 30 RPS; revalidate current page limits/quotas | PR #561 and src/market/source_catalog.py | Documented + bounded discovery source; state/quote path incomplete | Reachable-bin capacity, exact amount output or RPC quorum |
| Jupiter Swap API V2 | GET /swap/v2/order quote-only, no taker for initial read-only request | API key via x-api-key; existing docs record keyless ~0.5 RPS; recheck current docs/plan | PR #604 / P0-2 quote owner, radar | Adapter/normalizer + offline tests exist; no new live quote capture proven | Independent liquidity proof; duplicate pools are same resources |
| 0x Solana | POST https://api.0x.org/solana/swap-instructions | 0x-api-key, public taker address, exact raw input; Open Beta; recheck current endpoint header, including general 0x-version requirement | PR #604 / P0-2 normalizer | Offline contract path exists; no new live campaign proof | Signed transaction, execution permission or independent physical liquidity |
| Solana RPC | getMultipleAccounts (max 100 Pubkeys/request, one response context); accountSubscribe for change notifications | Operator's RPC URLs/keys; two independent operators/correlation groups required; approved governed profile/quotas | Existing governed transport, src/market/streams.py, src/qualification_campaign/, src/solana_parallel_radar/ | Contract known; current rooted independent quorum is human/credential gated | Pool discovery or quote provider by itself |
| Helius / Geyser / LaserStream | Optional streaming/change trigger + recovery | Product plan and endpoint credentials; current quotas/retention must be verified | Existing src/providers/helius/ | Optional supplement; not required to first bounded account-snapshot campaign | Substitute for rooted account state or second independent operator without proof |
| Jupiter Lend | Flashloan + Liquidity / TokenReserve rooted state via existing contracts | SDK/IDL + governed RPC; docs advertise no collateral/fee, but live on-chain state governs actual fee/capacity | Existing src/lending/jupiter_lend.py, R02 CAP-A and R03 builder | Offline reader + unsigned instruction contract exist; no qualified positive capital edge | Swap quote, independent market liquidity or signer authority |
| Flashloan signer | Not a market data API. Isolated signer service / operator authority boundary | Requires separate explicit authorization, policy review, key custody, simulation digest binding | Existing runtime/release authority only | Not in scope; remains absent/disabled | Market trace, API source or an automatic next step |

## Status vocabulary

- DOCUMENTED: official contract is linked and reviewed.
- BOUNDED_DISCOVERY_IN_REPO: adapter exists behind current source catalog/governance; only listing evidence.
- OFFLINE_ADAPTER: normalizer/state decoder exists and can replay fixtures.
- LIVE_READ_NOT_AUTHORIZED: no operator-approved credentials/profile/capture evidence in this task.
- ROOTED_STATE_UNQUALIFIED: no independent rooted proof yet.
- EXACT_QUOTE_BLOCKED: direct amount quote must reject until all quote math/state dependencies are complete.
- CAPITAL_UNQUALIFIED: lender resource has no qualified FlashCapitalEdge.
- SIGNING_DISABLED: no signing/submission.

## What this means now

- Discovery APIs and adapters are largely represented in the repo already. Do not create a second discovery catalog.
- Jupiter V2 and 0x are quote comparators, not market truth. Record the physical pool lineage of returned routes and de-duplicate.
- For direct CLMM/DLMM quotes, on-chain accounts are the state. APIs only help find pool IDs/config and refresh source metadata.
- A getMultipleAccounts response covers at most 100 accounts and returns one shared response context. More than one request creates more than one context; use minContextSlot and an explicit bounded-skew policy, or reject/retry under governance.
- Account subscriptions can trigger a refresh, but finalized/rooted account snapshots must still feed quote evidence.
- Helius is optional to initial MVP. A second truly independent RPC provider is not optional for a claimed quorum.
- Credentials and quotas are unknown until the operator configures an approved profile. Do not request or expose key values in chat.

## Official documentation links (re-pin on implementation)

### Discovery
- DEX Screener API: https://docs.dexscreener.com/api/reference
- Raydium API V3 Swagger: https://api-v3.raydium.io/docs/
- Meteora DLMM API overview: https://github.com/MeteoraAg/docs/blob/main/developer-guides/dlmm/api-reference/overview.mdx

### Quotes
- Jupiter Swap V2 overview: https://developers.jup.ag/docs/swap
- Jupiter V2 Order endpoint: https://developers.jup.ag/docs/api-reference/swap/order
- 0x Solana Swap API: https://docs.0x.org/solana/solana-swap-api/introduction
- 0x Solana swap-instructions: https://docs.0x.org/api-reference/solana-swap-ap-is/swap/instructions

### Direct state and venue math
- Solana RPC getMultipleAccounts: https://solana.com/docs/rpc/http/getmultipleaccounts
- Solana RPC accountSubscribe: https://solana.com/docs/rpc/websocket/accountsubscribe
- Raydium CLMM math/dynamic fee: https://github.com/raydium-io/raydium-docs-v1/blob/main/products/clmm/math.mdx
- Raydium CLMM instruction requirements: https://github.com/raydium-io/raydium-docs-v1/blob/main/products/clmm/instructions.mdx
- Raydium pinned program source: https://github.com/raydium-io/raydium-clmm/tree/6d7a0f82d2f293c553c69aaf943377367c6c4cc6
- Meteora TypeScript SDK reference: https://github.com/MeteoraAg/docs/blob/main/developer-guides/dlmm/typescript-sdk/reference.mdx
- Meteora pinned SDK commit: https://github.com/MeteoraAg/dlmm-sdk/tree/1532e540db41ac405dbf4c5bb2ddfceaa1f98ff1

### Flash capital
- Jupiter Lend flashloan overview: https://developers.jup.ag/docs/lend/flashloan
- Jupiter Lend flashloan execute: https://developers.jup.ag/docs/lend/flashloan/execute
- Repo reader: src/lending/jupiter_lend.py
- Repo R02 CAP-A/R03 unsigned builder tasks: docs/roadmap/agent-execution-master-2026-11-13/tasks/R02_CAPITAL_READERS.md and R03_UNSIGNED_BUILDERS.md

## Required environment-variable names (names only; confirm current owner before adding)

- SOLANA_RPC_URL_PRIMARY
- SOLANA_RPC_URL_SECONDARY
- JUPITER_API_KEY (confirm current config naming)
- ZEROX_API_KEY or the exact canonical name accepted by existing P0-2 owner (do not introduce another alias until reconciled)
- Optional Helius key/URL only if an existing provider profile requires it.

Never commit values. Never send secrets to Codex prompt, PR body, fixture, logs, screenshots or replay reports.
