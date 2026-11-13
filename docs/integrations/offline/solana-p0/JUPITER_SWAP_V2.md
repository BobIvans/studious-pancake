# Jupiter Swap API V2 — offline contract notes

**Canonical specification:** `JUPITER_SWAP_V2.openapi.yaml` (official OpenAPI 3.0.3 / info.version 2.0.0).  
**Upstream docs commit:** `jup-ag/docs@d40d936979af3ec75a12a053e3fbeb1f75eb31ce`.

## Current API surface

Base URL: `https://api.jup.ag/swap/v2`

| Method | Path | Purpose | P0 handling |
|---|---|---|---|
| GET | `/order` | Aggregated quote; optionally assembles a transaction when a taker is provided | Use without `taker` for quote-only capture; preserve route and fee metadata |
| GET | `/build` | Quote plus raw instructions for custom transactions; Metis-only routing | Not required for comparable quote capture; if collected later, treat all bytes as inert |
| POST | `/execute` | Submits a signed transaction returned from `/order` | **Forbidden** in P0 |

### Authentication and limits

- Header: `x-api-key`.
- Official `llms.txt` at the pinned docs repository described keyless access at 0.5 requests/second, suitable only for lightweight tests; a free developer key is available through Jupiter Portal to unlock higher limits and analytics. Limits can change, so pin the actual plan terms before scheduling.
- Existing repo code references `JUPITER_API_KEY`. Retain this env contract unless a deliberate config migration is reviewed. Never store the key in a fixture, manifest, PR or log.
- Do not use the legacy `lite-api.jup.ag` host as a fallback.

## `GET /order` request

Required query parameters:
- `inputMint`: canonical input mint.
- `outputMint`: canonical output mint.
- `amount`: decimal string of the exact input quantity in the **smallest unit** (not UI token amount).

Optional:
- `taker`: public key of the wallet to sign; if omitted, the response contains a quote but no transaction. For a like-for-like taker-aware comparison, use the same public taker on both providers when the 0x request requires one.
- `swapMode`: currently `ExactIn`.
- `slippageBps`: integer 0..10000. Don't choose a value silently; record it in each capture.
- Other routing/receiver/payer options can change which engines participate. Keep them identical or clearly distinguish the experiment.

Default `/order` routers compete: Metis, JupiterZ RFQ, Dflow and OKX. This is an aggregator quote, not a single independent DEX quote. The same underlying venues/liquidity may overlap 0x routes; route legs must be retained to avoid double-counting.

## Relevant response data

The complete schema lives in the pinned OpenAPI file. Preserve at least:
- `inputMint`, `outputMint`, `inAmount`, `outAmount`, `otherAmountThreshold`, `swapMode`;
- `routePlan[].swapInfo` including AMM key/label, input/output mints and per-leg amounts;
- platform/other fee structures, price impact and routing metadata when returned;
- `contextSlot` when present;
- `requestId`, `router`, quote id/expiry fields when present.

Amounts must remain exact integer strings. Validate that response mints and input amount match the request. A missing slot remains null; never invent one.

## P0 implementation rules

1. Migrate the existing `src/solana_parallel_radar` quote owner from the current V1 `/swap/v1/quote` path to an explicit V2 contract. Do not add another Jupiter adapter beside it.
2. Add a distinct V2 parser/normalizer. V1 and V2 shapes must not be conflated.
3. Keep the endpoint request bounded by the existing `ProviderGovernance`, `SourceDossier`, `ReadContract`, evidence journal and request caps.
4. For quote-only mode, omit `taker`; no transaction is returned. Never call `/execute`.
5. When a public taker is used for comparability, treat any returned transaction bytes as untrusted, inert evidence and do not deserialize into a signer-capable flow.
6. Add fixtures for success, no route, 400, 401/403, 429, 5xx/timeout, malformed amount, response mint mismatch, missing fields, stale response and schema drift.

