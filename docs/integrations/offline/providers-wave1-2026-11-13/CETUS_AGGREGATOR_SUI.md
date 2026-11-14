# Cetus Aggregator (Cetus Plus Swap Aggregator) — Sui: offline contract extract

**Flag:** OFFICIAL_CONTRACT_EXTRACT_ONLY + SDK pin
**Official sources (retrieved 2026-11-14 UTC, see manifest):**
- Developer docs index: https://cetus-1.gitbook.io/cetus-developer-docs/llms.txt
- Aggregator overview: https://cetus-1.gitbook.io/cetus-developer-docs/developer/cetus-plus-aggregator
- Getting started (V3 endpoint/packages/providers): https://cetus-1.gitbook.io/cetus-developer-docs/developer/cetus-aggregator/getting-started.md
- Features available (find router + build tx): https://cetus-1.gitbook.io/cetus-developer-docs/developer/cetus-aggregator/features-available.md
- Official repo: https://github.com/CetusProtocol/aggregator (README = SDK guide)

## Version posture (official, load-bearing)

"For builders and dApps who are using Cetus Aggregator, please upgrade to Aggregator V3 SDK asap... V2 and older versions will be deprecated soon."
- V3 service endpoint: `https://api-sui.cetus.zone/router_v3/find_routes`
- V2 service endpoint (deprecated soon): `https://api-sui.cetus.zone/router_v2/find_routes`
- V3 requires npm package `@cetusprotocol/aggregator-sdk` >= 1.1.1; latest published package version in docs: `@cetusprotocol/aggregator-sdk@1.7.5`

Any adapter must target V3 (`paths`-based response) — V2's `routes` field is a different structure ("v3 replaces the `router` field with `paths`" per features-available compatibility note; the README example uses `routerRes` naming for the older shape).

## Quote semantics — ECONOMIC QUOTE (find router)

`client.findRouters({from, target, amount (BN|string|number|bigint), byAmountIn})` — `byAmountIn: true` fixes input, `false` fixes output. Optional: `providers` (provider list; construct via `getAllProviders()`/`getProvidersIncluding()`/`getProvidersExcluding()`), `depth` (1..3, default 3 = hops), `splitAlgorithm` (`devide_equally` [sic] default / `geometric`), `splitFactor`, `splitCount` (max splits, default 20). Pool filters (SDK v1.7.5+): `includePools`/`excludePools` — "up to 50 entries and 4096 UTF-8 bytes in its comma-separated representation"; exclusions take precedence; "do not override provider selection or service-side pool bans".

ResponseV3 fields (official table): `quoteID` ("randomly generated ID from the aggregator service for tracking index transactions and quotes"), `amountIn` (BN), `amountOut` (BN), `byAmountIn`, `paths[]`, `insufficientLiquidity` (bool), `deviationRatio` ("Price deviation ratio, (0.01 means 1%), indicating the degree of difference between the aggregator result and market price"), `packages` (Map of latest aggregator packages when version params passed), `overlayFee` ("The amount for overlay fee"), `totalDeepFee` ("Calculated need deep fee for deep pools"), `error` (RouterError).

Build-output class of the quote: **economic quote / route reference with path structure** — no transaction is produced by `find_routes` itself.

## Build semantics — COMPOSABLE PTB

Official swap-method comparison (features-available):

| Method | Input coin | Output | Recommended use |
|---|---|---|---|
| `fastRouterSwap` | prepared automatically (coinWithBalance) | delivered automatically | simple swaps |
| `routerSwapWithMaxAmountIn` | caller-provided + `maxAmountIn` | returns target coin object | "composable PTBs requiring external input coins with a maximum input protection" |
| `routerSwap` | caller-provided | returns target coin object | "composable PTBs where the full input coin balance should be used" |

All three take a caller-owned `txb: Transaction` (required param) — build-output class: **composable Sui Transaction/PTB commands**, not a standalone serialized transaction.

Required build params: `router` (quote object), `slippage` (decimal, `0 <= slippage < 1`, e.g. `0.01` = 1%), `txb`. Optional: `partner` / `cetusDlmmPartner` (partner address for fee share; "will soon be deprecated" in swap params — set at client init instead), `refreshAllCoins`, `payDeepFeeAmount` ("The deep amount for pay deep fee in deepbookv3 path. Currently, all pools that charge a swap fee are covered by Cetus."), `sponsored`.

Sponsored mode (official): "Set `sponsored: true` when a separate sponsor or gas station pays the transaction gas. In this mode, the swap does not use `txb.gas` as its input or output because the gas coin belongs to the sponsor." Full sponsor flow (buildTransactionKind, sponsor gas data, dual signatures) is documented at `features-available/sponsored-transactions.md` — NOT_PINNED_THIS_WAVE.

## Fee fields

- `overlayFee` and `totalDeepFee` are explicit response fields (DeepBook path fee).
- `payDeepFeeAmount` is the build-time companion.
- Partner/affiliate fee: via `partner` (address) — split mechanics documented in `partner-swap.md` (NOT_PINNED_THIS_WAVE); no `referralFee`-style percent field was reviewed on the aggregator pages (partner percent UNKNOWN).
- Underlying LP fees are inside path/AMM semantics, not a flat response field (UNKNOWN).

## On-chain packages (official getting-started table, Sui mainnet)

- `AggregatorV3` packageId `0x33ec64e9bb369bf045ddc198c81adbf2acab424da37465d95296ee02045d2b17` (version 3)
- Named routers include (packageId → abbreviated): `CetusRouter` `0xb1e11cea...`, `AftermathRouter` `0xb20fbe0c...`, `FlowxRouter` `0x5307d1e8...`, `BluefinRouter` `0xaa4c2913...`, `DeepbookV3Router` `0xbb2796b4...`, `HaedalRouter`, `KriyaRouter`, `MagmaRouter`, `MetastableRouter`, `MomentumRouter`, `ObricRouter`, `ScallopRouter`, `SteammRouter`, `SpringSuiRouter`, `TurbosRouter`, `VoloRouter`, `FullsailRouter`, `CetusDlmmRouter`, `FerraClmmRouter`/`FerraDlmmRouter`, `BoltRouter`, `MagmaProPammRouter`, `DipcoinRouter`, `AlphafiRouter`, `AfsuiRouter` — full table copied in the official docs page; treat as current-at-retrieval, re-verify before builder work (package IDs are upgradeable object publish records, not bytecode attestations).

## Default providers (official, SDK v1.5.5 row)

`deepbookv3, flowx v2/v3, kriya v2/v3, aftermath, turbos, volo, afsui, scallop, springsui, bluefin, haedalhmm&v2, alphafi, steamm(cpmm&omm&ommv2), metastable, obric, haedal(hasui & hawal), momentum, magma, fullsail, cetusdlmm, ferraclmm, ferradlmm, bolt, magmapropamm`

This list is the primary Sui overlap evidence: Cetus routes include Aftermath, FlowX, Bluefin/7K-adjacent and DeepBook venues directly (see `PROVIDER_OVERLAP_NOTES.md`).

## SDK pin

| Artifact | Pin |
|---|---|
| npm `@cetusprotocol/aggregator-sdk` | version `1.7.5` (package.json at repo main); `license: null` in package.json — no SPDX license declared (typed note: UNKNOWN, do not copy source without license review) |
| GitHub `CetusProtocol/aggregator` | main `ae5bc1e7fe710d96a60ca5dbcc2591966d29de9c` (2026-10-19); latest tag `v1.7.5` = same commit |
| Dependencies (package.json) | `@mysten/sui` `2.31.2`, `bn.js` (peer via example), `json-bigint`, `node-fetch`, `bip39`, `dotenv`, `@pythnetwork/hermes-client` `^3.1.0` |

## Auth / rate limits / errors

- No API key surface appears on reviewed official pages ("Initialize the SDK with the required configuration parameters. This typically includes setting up the network and API keys, if needed." — conditional wording, no documented key parameter in the reviewed contract). Record: API key requirement UNKNOWN; no credential names published.
- Published numeric rate limits: none found on reviewed pages (UNKNOWN; typed acquisition row).
- Errors: `error` (RouterError) field with "Error code and msg for aggregator" — the concrete code table was NOT extracted this wave (typed note). `insufficientLiquidity` is the documented no-route-adjacent signal; `deviationRatio` is the documented price-deviation warning.

## Comparison requirements

Same full Move coin types, exact BN amount, explicit `byAmountIn`, same slippage decimal scale (0–1 here vs bps/percent elsewhere), bounded time skew; retain `quoteID`, `paths` (venue/provider attribution), `overlayFee`/`totalDeepFee`, `deviationRatio`, and `insufficientLiquidity` negative outcomes. Losing provider-split paths are evidence.

## Safety boundary

PTB commands are evidence only: never assemble into a signable transaction in qualification, never use `sponsored`/sponsor flows, never devInspect with a funded keypair. `sign_enabled=false`, `send_enabled=false`.

## Missing / unpinned items (typed)

1. API key requirement / auth: UNKNOWN (no documented surface on reviewed pages).
2. Numeric rate limits: UNKNOWN.
3. RouterError code table: NOT_PINNED_THIS_WAVE.
4. Partner fee percent/split mechanics: NOT_PINNED_THIS_WAVE (`partner-swap.md`).
5. Sponsored-transaction full flow: NOT_PINNED_THIS_WAVE.
6. Package license: UNKNOWN (`license: null`; no LICENSE file at repo root — 404 via GitHub contents API).
