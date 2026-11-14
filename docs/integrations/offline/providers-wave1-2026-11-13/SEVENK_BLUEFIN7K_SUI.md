# 7K / Bluefin7K Aggregator — Sui: offline contract extract

**Flag:** OFFICIAL_CONTRACT_EXTRACT_ONLY + SDK pins
**Official sources (retrieved 2026-11-14 UTC, see manifest):**
- Docs index: https://docs.7k.ag/llms.txt ; Overview: https://docs.7k.ag/7k-aggregator/overview.md ; SDK page: https://docs.7k.ag/developers/sdk.md
- Direct aggregator SDK repo: https://github.com/fireflyprotocol/bluefin7k-typescript-sdk (README, docs/SWAP.md, src/constants/apiEndpoints.ts, src/constants/_7k.ts)
- npm: `@bluefin-exchange/bluefin7k-aggregator-sdk` (registry metadata)
- Meta-aggregator SDK: https://github.com/7k-ag/7k-sdk-ts (README, docs/META_AG.md) + npm `@7kprotocol/sdk-ts`

## Identity note (naming)

Two official artifacts carry the "7K" name and this dossier pins both:
1. **Bluefin7K Aggregator** — the Sui aggregator service (default endpoint provider name `"Bluefin7k"`; docs.7k.ag is its documentation site; official examples call it "7K Aggregator" / "Bluefin7K").
2. **7K MetaAg SDK** (`@7kprotocol/sdk-ts`) — an official multi-provider SDK that compares quotes from `bluefin7k`, `flowx`, `cetus`, `okx`. It is a client-side comparator, not a separate liquidity source.

## Direct aggregator API (Bluefin7K)

Base URLs (from official SDK source `src/constants/apiEndpoints.ts`):
- Main: `https://aggregator.api.sui-prod.bluefin.io`
- LO/DCA: `https://lod-dca.7k.ag`
- Statistic: `https://statistic.7k.ag`
- Endpoint-provider versions: `"Bluefin7k"` (default) uses `v2/quote`; `"Bluefin7kV2"` uses `v3/quote` "with RFQ support" (README).

On-chain constants (official `src/constants/_7k.ts`): current `_7K_PACKAGE_ID 0x62412b7268c35f3808336aee57a52836501f40b8ba5d936f8ad275e672befd04`; `_7K_CONFIG 0x47442a93f7727d188ba7cb71031170d1786af70013cb7ad5115f3fe877ff0c54`; `_7K_VAULT 0x442ad50389ed5cda6f7a6f5a7ae6361a4c05ef1d9fb2e54fbba5a268d690bfe6`; legacy V1–V4 package IDs are commented in the same file (recorded there, not re-listed here).

## Quote semantics — ECONOMIC QUOTE

`getQuote({tokenIn, tokenOut, amountIn, sources?})` (docs/SWAP.md). `sources` optional list of DEX sources; "if empty, the latest sources supported by the current SDK version will be used". Documented source set (README/SWAP examples): `suiswap, turbos, cetus, bluemove, kriya, kriya_v3, aftermath, flowx, bluefinx, obric, haedal_pmm, sevenk_v1, steamm_oracle_quoter, steamm_oracle_quoter_v2`.

Oracle caveat (official): "Oracle-priced sources (`obric`, `haedal_pmm`, `sevenk_v1`, `steamm_oracle_quoter`, `steamm_oracle_quoter_v2`) are excluded until a Pyth endpoint is configured, whether you pass them explicitly or fall back to the defaults." Pyth `updateDataUrl` must answer `GET <url>?ids=<comma-separated feed ids>` and is configured once before any `getQuote`. "Quotes and swaps work fine without any Pyth setup" (non-oracle sources only).

## Build semantics — COMPOSABLE PTB

`buildTx({quoteResponse, accountAddress, slippage, commission?, extendTx?})` returns `{tx, coinOut}`:
- Fresh build: returns a full Sui `Transaction`.
- Append mode: `extendTx: {tx, coinIn?}` composes the swap into the caller's existing `Transaction` with an explicit input coin ("explicitly consume this coin object instead of loading all available coin objects from wallet").
- Slippage is decimal (`0.01` = 1%).
- `commission: {partner, commissionBps}` — "1bps = 0.01%, for example, 20bps = 0.2%". "Even when commissionBps is set to 0, you must still provide a partner address. This is required for partner tracking and analytics purposes."

Build-output class: **composable Sui PTB** (fresh or extend) from an economic quote. The SDK also ships `executeTx` / signing flows (out of scope; never used).

## Authentication / rate limits (published)

| Usage | API Key required | Default rate limit | Higher limit |
|---|---|---|---|
| Frontend (in-browser) | No | 5 requests/second | No |
| Backend (server-side) | Optional | 5 requests/second (without key) | Yes — requires API key + partner info |

"Config.setApiKey("YOUR_API_KEY")" is the setter (credential NAME only; no values). Increase requests via Discord ticket (`discord.gg/bluefinapp`). A separate `Config.setBluefinXApiKey(...)` exists for routing through BluefinX ("for example, to avoid rate limits when routing through BluefinX").

## Transport

SDK v7 constructs a Sui client for "transaction execution, simulation, and coin fetching" — README recommends **gRPC** for best performance (`baseUrl` configurable, example `https://fullnode.mainnet.sui.io:443`). This matches the mandate's "no legacy Sui JSON-RPC" direction for Sui transports; exact client-method surface was NOT extracted this wave (typed note).

## 7K MetaAg SDK (`@7kprotocol/sdk-ts`)

- npm version `5.0.0-beta.2` (package.json at repo main `4c9804b234cb81fe538060f2841d77317e347645`, 2026-05-21); latest stable tag `v4.0.0` = `281e9ae48cd0963c1d879e7e068bc48a287f0d03`; license MIT. Mainnet-only ("this package only supports mainnet").
- v5 constructs `SuiGrpcClient` against Sui mainnet by default; `MetaAgOptions.client` accepts any `ClientWithCoreApi` (`SuiGrpcClient`, `SuiGraphQLClient`, `SuiJsonRpcClient`).
- Official Cetus transport caveat (documented by 7K): `@cetusprotocol/aggregator-sdk@^1.5.4` "still types its internal client as `SuiJsonRpcClient` and calls legacy JSON-RPC methods... routes that touch Pyth oracles (e.g. `HAEDALPMM`) will fail" on non-JSON-RPC transports.
- `MetaAg.quote({amountIn, coinTypeIn, coinTypeOut, signer?, timeout? (default 2000ms)}, simulation?)` → `MetaQuote[]` with `id`, `provider` (`"bluefin7k"|"flowx"|"cetus"|"okx"`), `quote` (raw provider response), `rawAmountOut`, `amountOut` (after commissions), `simulatedAmountOut`, `gasUsed` (GasCostSummary). Simulation uses dev-inspect with a `sender` address; deferred `onSimulated` callback supported.
- `MetaAg.swap({quote, signer, tx, coinIn}, slippageBps?)` → `TransactionObjectArgument` — composable PTB: caller-owned `Transaction`, "You must add subsequent commands (like transferObjects) to consume the returned coin object."
- `MetaAg.fastSwap(...)` builds, signs and executes — out of scope, never called.
- Commission/tip knobs: `partner` (default zero address), `partnerCommissionBps` (default 0), `slippageBps` (default 100), `tipBps` ("Tip to 7K Protocol", default 0).
- OKX provider requires `apiKey`, `secretKey`, `apiPassphrase`, `projectId` (credential names only).

## SDK pin table

| Artifact | Pin |
|---|---|
| npm `@bluefin-exchange/bluefin7k-aggregator-sdk` | latest `7.7.0`; license MIT |
| GitHub `fireflyprotocol/bluefin7k-typescript-sdk` | latest tag `bluefin7k-sdk-release-7.6.3` = `947da0666a3fb4893656f0914472d5a30feead4b`; main pushed 2026-09-28; license MIT |
| npm `@7kprotocol/sdk-ts` | `5.0.0-beta.2` (main); license MIT; tag `v4.0.0` = `281e9ae48cd0963c1d879e7e068bc48a287f0d03` |

## Fees summary

- Integrator: `commission.commissionBps` (direct buildTx) or `partnerCommissionBps` (MetaAg) — bps units.
- Protocol: `tipBps` "Tip to 7K Protocol" (MetaAg knob). Any default platform fee charged by the Bluefin7K aggregator service itself was not documented on reviewed pages (UNKNOWN; typed acquisition row).

## Errors / 429

Published numeric limit is 5 RPS default (see table). Exceeding it: the docs reference rate limits in the BluefinX routing context; an explicit 429 error-code table for the aggregator endpoints was NOT found on reviewed pages (typed note; UNKNOWN). Pyth-misconfiguration behavior is documented (source exclusion with SDK log line).

## Comparison requirements

Same full Move coin types + exact base-unit `amountIn` + decimal slippage conversion (0.01 = 1% = 100 bps) + bounded time skew. Preserve `sources` attribution per quote and `provider` per MetaQuote; `sevenk_v1` is itself an oracle-priced internal source name — venue attribution must not be collapsed (see `PROVIDER_OVERLAP_NOTES.md`).

## Safety boundary

`buildTx`/`swap` outputs are PTB evidence only. Never call `executeTx`/`fastSwap`/`signAndExecuteTransaction`; never configure real keys (`Config.setApiKey` etc. exist in code paths but are never invoked in qualification). `sign_enabled=false`, `send_enabled=false`.

## Missing / unpinned items (typed)

1. Aggregator-service 429/error-code table: UNKNOWN.
2. Any service-side platform fee default: UNKNOWN.
3. `v3/quote` (RFQ) request/response schema deltas vs `v2/quote`: NOT_PINNED_THIS_WAVE.
4. Exact gRPC client-method surface used by the SDK: NOT_PINNED_THIS_WAVE.
5. BluefinX routing mechanics (what `bluefinx` source is and its rate-limit interaction): NOT_PINNED_THIS_WAVE.
