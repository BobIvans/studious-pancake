# Aftermath router adapter — additive schema pin (2026-11-19)

Status: `OFFICIAL_CONTRACT_EXTRACT_ONLY`. This dossier is ADDITIVE to the wave-1
dossier `docs/integrations/offline/providers-wave1-2026-11-13/AFTERMATH_SUI.md`
(SDK semantics, fees, error page, correlation) and the wave-2 dossier
`docs/integrations/offline/sui-market-wave2-2026-11-14/AFTERMATH_ROUTER_WAVE2.md`
(on-chain contract IDs, flash-lender verdict). It pins ONLY what those waves
left typed-unpinned and what the R13-A2 adapter (`src/gpr_sui_shadow/providers/aftermath.py`)
consumes. No capacity claim; discovery/quote evidence only.

## Source pins (all retrieved 2026-11-19 UTC)

| Source | URL | License | Retrieval |
|---|---|---|---|
| Production OpenAPI 3.1.0 document, `info.version: 1.0.0` | https://aftermath.finance/api/openapi/spec.json | MIT (`info.license`) | 2026-11-19 |
| Router SDK reference (docs `.md` variant) | https://docs.aftermath.finance/for-developers/typescript-sdk/products/router.md | docs site content | 2026-11-19 |
| Auxiliary endpoints (router family) | https://docs.aftermath.finance/for-developers/api/rest-api/auxiliary-endpoints.md | docs site content | 2026-11-19 |
| Error handling | https://docs.aftermath.finance/for-developers/api/rest-api/error-handling.md | docs site content | 2026-11-19 |
| API index | https://docs.aftermath.finance/for-developers/api.md | docs site content | 2026-11-19 |

## Resolved vs wave-1 typed gaps

1. **`/api/router/transactions/trade` schema** — wave-1 pin: `BLOCKED_MISSING_PIN`
   ("absent from OpenAPI; no documented request/response schema"). The
   2026-11-19 production OpenAPI document DECLARES it: request
   `{walletAddress, completeRoute, slippage, isSponsoredTx?, customRecipient?}`,
   response a legacy JSON-serialized transaction string, and marks it
   **deprecated** in favor of `/api/router/v1/transactions/trade`
   (base64 `TransactionKind`, `GasResolution::Defer`) and
   `/api/router/v1/transactions/add-trade` (`{walletAddress, completeRoute,
   slippage, txKind}` → `{txKind, coinOutId}`). Resolution recorded here; the
   adapter still consumes ONLY the quote surface (`trade-route`) — build ≠ quote.
2. **Integer wire encoding** — pinned by the OpenAPI overview: responses encode
   64/128-bit integers as decimal strings with a trailing `n` (`"5000000n"`);
   requests accept a JSON integer, a decimal string, or the `n`-suffixed
   string (mixable). Malformed values fail with error code `2026`.
3. **`trade-route` response schema** — pinned as `CompleteTradeRoute`:
   required `{routes: TradeRoute[], coinIn: TradeCoin, coinOut: TradeCoin,
   spotPrice: number}`; optional `{externalFee, feeBreakdown:
   FeeBreakdownEntry[], netTradeFeePercentage, referrer, slippage}`.
   `TradeRoute` = `{paths: TradePath[], portion (1e18-scaled fraction),
   coinIn, coinOut, spotPrice}`; `TradePath` = `{protocolName, poolId,
   poolMetadata, coinIn, coinOut, spotPrice}`; `TradeCoin` = `{type, amount,
   tradeFee}`; `FeeBreakdownEntry` = `{recipient, coinType, amount,
   feePercentage}`.
4. **`trade-route` request schema** — pinned: required `{coinInType,
   coinOutType}` plus EXACTLY ONE of `coinInAmount` / `coinOutAmount`
   (`BigIntInput`); fixed-output REQUIRES `slippage` (fraction [0,1]);
   optional `{externalFee {recipient, feePercentage}, referrer,
   protocolWhitelist|protocolBlacklist, poolWhitelist|poolBlacklist}`.
5. **Supported-protocol endpoint** — NEW since wave-1:
   `POST /api/router/supported-protocols` → `{supported_protocols: string[]}`
   ("canonical protocol names, as accepted by route-request whitelists and
   blacklists"). The SDK's static `RouterProtocolName` union (Aftermath,
   BlueMove, Cetus, DeepBook, DeepBookV3, DoubleUpPump, FlowX, FlowXClmm,
   HopFun, Kriya, KriyaClmm, Metastable, MovePump, Obric, SuiSwap, Turbos,
   SpringSui, Bluefin, TurbosFun) remains the pinned name vocabulary.

## Pinned constants used by the adapter

- `Router.constants.maxExternalFeePercentage = 0.5` (SDK reference).
- Default rate limit `1000 requests / 10 seconds` (wave-1 authorization page;
  unchanged).
- `slippage` semantics on the v1 transaction surfaces: fraction in [0, 1],
  default `0.01` — the adapter pins the same unit for the quote request.
- Response `coinIn.tradeFee` / `coinOut.tradeFee`: pinned SOR fee page states
  "No protocol fee is taken on trades performed through the Aftermath
  Smart-Order Router" — the adapter records a zero as no-fee and REFUSES a
  nonzero value as drift against the pinned fee model (typed
  `COMPARABILITY_DRIFT`), never interprets it.

## Still unpinned (typed)

- Whether `feeBreakdown[].amount` is already deducted from `coinOut.amount`:
  NOT_PINNED → fee `inclusion_state` stays UNKNOWN in kernel evidence.
- `externalFee` response amount: the response object carries only
  `{recipient, feePercentage}` — no amount → `amount_raw=None` (UNKNOWN).
- Router-family explicit 429/Retry-After code list: UNKNOWN (wave-1 gap
  unchanged; only the default quota is published).
- `aftermath-ts-sdk` package.json version + license review: UNCHANGED from
  wave-1/wave-2 (docs reference "v3.3.1"); do not vendor SDK source without a
  license review.
- Freshness fields on `trade-route` responses: the pinned schema carries NO
  slot/checkpoint/expiry → kernel freshness records only the caller-supplied
  `received_at_ns`; nothing is synthesized.

## Flash-lender verdict (carried from wave-2, unchanged)

`MISSING_PIN`: no flash-loan entry point documented in the official Aftermath
docs. Aftermath is routing/discovery only; router quote capacity is a QUOTE
concept, never lender capacity (discovery vs capital kept separate).
