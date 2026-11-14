# FlowX Finance — Sui Swap Aggregator SDK: offline contract extract

**Flag:** OFFICIAL_CONTRACT_EXTRACT_ONLY + SDK pin (license UNKNOWN — typed note)
**Official sources (retrieved 2026-11-14 UTC, see manifest):**
- Swap Aggregator docs: https://docs.flowx.finance/developer/flowx-sdk/swap-aggregator.md (docs index: https://docs.flowx.finance/llms.txt)
- Official SDK repo: https://github.com/FlowX-Finance/sdk (README links the docs page above)
- npm: `@flowx-finance/sdk` (registry metadata)

## SDK pin

| Artifact | Pin |
|---|---|
| GitHub `FlowX-Finance/sdk` | master `9a3290888c05c0ef635d32c5cbcfb901789a15dc` (2026-01-29); no release tags exist; repo license endpoint 404, npm `license: None` — **license UNKNOWN, no LICENSE file** (typed note: default-copyright; do not copy source without license review) |
| npm `@flowx-finance/sdk` | latest `2.1.0`; description "An FlowX Typescript SDK is a software development kit... to interact with FlowX protocols using the Typescript programming language" |

## Aggregator endpoints (official SDK source `src/universal-router/constants.ts`, mainnet block)

```
singleQuoteURI:    https://api.flowx.finance/flowx-ag-routing/api/v1/quote
batchQuoteURI:     https://api.flowx.finance/flowx-ag-routing/api/v1/batch-quotes
multipleQuotesURI: https://api.flowx.finance/flowx-ag-routing/api/v1/multi-quotes
requestTimeout:    30000 (ms)
graphql.baseURI:   https://api.flowx.finance/flowx-be/graphql
pyth.priceServiceEndpoint: https://hermes.pyth.network/v2
```

Auth: the AggregatorQuoter appends the API key as a **query parameter** — `apiKey` (official source: `` `${CONFIGS[this.network].quoter.batchQuoteURI}?apiKey=${this.apiKey}` ``; constructor takes `public readonly apiKey?: string`). No values recorded. Whether anonymous quotes are served without a key: UNKNOWN (typed acquisition row).

Published numeric rate limits: none found on reviewed docs pages (`docs.flowx.finance` llms-full grep for rate limit / API key / 429 produced no hits) — UNKNOWN, typed acquisition row. A "multi-provider" note: the SDK also ships `src/meta-ag/MetaAggregatorQuoter.ts` (FlowX-side meta-aggregation) — contract NOT_PINNED_THIS_WAVE.

## Quote semantics — ECONOMIC QUOTE

`AggregatorQuoter('mainnet').getRoutes({tokenIn, tokenOut, amountIn, includeSources?, excludeSources?, commission?, maxHops?, splitDistributionPercent?, excludePools?})`:
- `maxHops`: "optional: default and max is 3"
- `splitDistributionPercent`: "optional: default 1 and max 100"
- `excludePools`: "list pool you want excude example: 0xpool1,0xpool2"
- Official WARNING displayed at the top of the docs: "`amountOut` FROM QUOTE WHEN USE WITH COMMISSION ONLY FOR DISPLAY, NOT FOR CALCULATE ONCHAIN." — any commission-inclusive quote output is display-only; on-chain amount must be recomputed, never copied.

Build-output class: **economic quote (routes)** — no transaction from the quoter.

## Build semantics — PTB (fresh) and COMPOSABLE (append)

Fresh full transaction:
```js
const tradeBuilder = new TradeBuilder(NETWORK.MAINNET, routes);
const tx = tradeBuilder.sender('0xSenderAddress')            // optional if coin passed later
  .slippage((1 / 100) * 1e6)                                 // 1% — slippage scale is Q64-ish 1e6 base ("percent of 1e6")
  .commission(null)
  .build()
  .buildTransaction({ client });
```

Composable append (official "Return coin for later use"):
```js
const tx = new Transaction();
const trade = tradeBuilder.sender(...).slippage(...).commission(null).build();
const coinOut = trade.swap({ client, tx });                  // appends into the caller's Transaction
```

Build-output classes: **fresh Sui PTB** (`buildTransaction`) and **composable Sui PTB** (`trade.swap({tx})` returning `coinOut`).

## Commission (fee) fields

`Commission('0xPartnerAddress', new Coin('0x2::sui::SUI'), CommissionType.PERCENTAGE, '500', true)`:
- `CommissionType.PERCENTAGE`: "value should be input `1/100 * 1e6`... example of 1%"; `CommissionType.FLAT`: "value should be the amount of token you want to fee include decimals".
- `directTransfer` (bool): "if `true` then commission will transfer directly to partner address, else you need go to contract and claim partner fee later".
- Fee-collecting coin choice matters: "if you pass SUI is coin collect fee, when you swap SUI -> USDC or USDC->SUI you will collect SUI is a fee, but if you swap FLX->USDC and USDC->FLX you receive nothing and coin is SUI, then you SHOULD NOT pass commission to TradeBuilder".
- Pass the same `commission` to **both** `getRoutes` (for exact quote values) and `TradeBuilder` (for on-chain inclusion).
- On-chain collect event (official constants): `0xc263060d3cbb4155057f0010f92f63ca56d5121c298d01f7a33607342ec299b0::partner_manager::Collect`.

## Supported protocols (official `Protocol` enum, SDK source)

`FLOWX` (v2 AMM), `FLOWX_CLMM` (v3), `KRIYA`, `KRIYA_CLMM`, `TURBOS`, `CETUS`, `AFTERMATH`, `AFTERMATH_LSD`, `DEEPBOOK`, `DEEPBOOK_V3`, `BLUEMOVE`, `BLUEMOVE_FUN`, `BLUEFIN`, `FLOWX_PMM`, `HOP_FUN`, `7K_FUN`, `SEVENK_V1`, `TURBOS_FUN`, `OBRIC`, `HAEDAL_PMM`, `HAEDAL`, `SPRING_SUI`, `ALPHA_FI`, `VOLO_LSD`, `STEAMM`, `METASTABLE`, `MAGMA_FINANCE`, `MOMENTUM_FINANCE`, `FULL_SAIL`, `IPX_TIDE`, plus swap-entity classes for `DeepbookV3Swap`, `DipCoinDexSwap`, `FerraClmmSwap` etc. This is the second primary Sui overlap evidence set: FlowX routes include Aftermath, 7K (`SEVENK_V1`/`7K_FUN`), Cetus, Bluefin and DeepBook venues directly (see `PROVIDER_OVERLAP_NOTES.md`).

## Errors / freshness

- `requestTimeout: 30000` is the SDK-side timeout constant.
- Quoter error contract (HTTP codes, error bodies) was NOT documented on reviewed pages — UNKNOWN, typed acquisition row.
- Quote freshness/expiry field on routes: not documented on reviewed pages — UNKNOWN. Do not infer.

## Comparison requirements

Same full Move coin types + exact base-unit `amountIn` + explicit slippage-scale conversion (`1e6` scale here; 1% = `10000` of 1e6) + bounded time skew. If commission configured, recompute expected output on-chain semantics rather than trusting `amountOut` (official warning). Preserve `includeSources`/`excludeSources` attribution and pool IDs for correlation.

## Safety boundary

Transactions are evidence only: never sign, never submit, never construct with a funded `client` (use offline/devInspect-free flows only). `sign_enabled=false`, `send_enabled=false`.

## Missing / unpinned items (typed)

1. Repo/package license: UNKNOWN (no LICENSE file, npm `license: None`).
2. Anonymous (keyless) quote availability + `apiKey` issuance process: UNKNOWN.
3. Published rate limits: UNKNOWN (none found on reviewed pages).
4. Quoter error-code/HTTP contract: NOT_PINNED_THIS_WAVE.
5. Quote expiry/freshness fields: UNKNOWN.
6. `MetaAggregatorQuoter` (FlowX-side meta-ag) contract: NOT_PINNED_THIS_WAVE.
