# Titan — Solana swap meta-aggregator: offline contract extract

**Flag:** OFFICIAL_CONTRACT_EXTRACT_ONLY
**Official sources (retrieved 2026-11-14 UTC, see manifest):**
- Developer docs root: https://titan-exchange.gitbook.io/titan/titan-developer-docs (markdown at `.../developer-doc/home.md`)
- Portal quickstart: https://titan-exchange.gitbook.io/titan/titan-developer-docs/developers-portal/quickstart.md
- Gateway quickstart: https://titan-exchange.gitbook.io/titan/titan-developer-docs/swap-api/quickstart.md
- Authentication: https://titan-exchange.gitbook.io/titan/titan-developer-docs/getting-started/authentication.md
- Fee collection: https://titan-exchange.gitbook.io/titan/titan-developer-docs/swap-api/guides/fee-collection.md
- SDK reference: https://titan-exchange.gitbook.io/titan/titan-developer-docs/resources/sdk.md
- SDK repo: https://github.com/Titan-Pathfinder/titan-sdk-ts

## What Titan is (official statement)

"Titan is the swap meta-aggregator behind the best execution on Solana. Quotes from multiple providers, simulated on-chain by Argos." Routes come from Argos plus external aggregators and RFQ venues; the app docs describe zero per-swap fees on Titan routes and up to 1 bps on DART routes. Titan also operates as a named router inside other aggregators (its own quote map exposes per-provider entries keyed `Titan`, `Metis`, `Okx`, …), which is load-bearing for correlation grouping (see `PROVIDER_OVERLAP_NOTES.md`).

## Interfaces

Three access methods share the same Argos routing engine (official `developer-doc/home.md`):

| Interface | Transport | Auth | Host |
|---|---|---|---|
| Developers Portal REST | HTTP JSON (`Accept: application/json`) | `x-api-key` header | `https://portal.api.titan.exchange` |
| Titan Gateway (distributor) | HTTP MessagePack (`Accept: application/vnd.msgpack`) | `Authorization: Bearer <jwt>` | distributor-supplied endpoint |
| Titan Direct | WebSocket `wss://<endpoint>/api/v1/ws?auth=<jwt>` | `?auth=<jwt>` query param | distributor-supplied endpoint |

Self-serve API keys: developer.titan.exchange (keys scoped to an organization). Free Sandbox tier is stated on the developer-doc home page; numeric quota per tier is NOT published (UNKNOWN).

"Credentials are not interchangeable. An API key sent to a distributor endpoint, or a JWT sent to `portal.api.titan.exchange`, returns `401`." (authentication.md)

## Quote endpoint (comparable-quote-race endpoint)

`GET https://portal.api.titan.exchange/api/v1/quote/swap` with query params:

| Param | Meaning |
|---|---|
| `inputMint`, `outputMint` | canonical mints (SOL example `So1111...11112`, USDC `EPjFW...Dt1v`) |
| `amount` | exact base-unit string (e.g. `1000000000` = 1 SOL in lamports) |
| `userPublicKey` | required — "Swap quote requests require a `userPublicKey`" |
| `slippageBps` | e.g. `50` |
| `feeAccount`, `feeBps`, `feeFromInputMint` | optional integrator fee params (see below) |

Gateway path is identical (`/api/v1/quote/swap`) but MessagePack-encoded responses.

## Response semantics — INSTRUCTION BUNDLE, not a serialized transaction

The quote response is a map `quotes` keyed by provider ID. Each entry (`SwapRoute`) carries:
- `inAmount`, `outAmount`, `slippageBps`
- `computeUnitsSafe` — "recommended compute budget that accounts for on-chain variance"
- `instructions` — "the swap instructions to include in your transaction" (portal JSON uses short field names: `p` = programId, `a` = accounts, `d` = data)
- `addressLookupTables` — "ALT addresses needed to compile a V0 transaction"
- optional `expiresAtMs` (ms UNIX) and `expiresAfterSlot`
- `metadata.ExpectedWinner` — official guidance: select `quotes[metadata.ExpectedWinner]`, do not sort by `outAmount`

The official quickstart instructs the integrator to assemble a `VersionedTransaction` client-side and sign it. Titan does not return a serialized unsigned transaction on this surface. Build-output class: **unsigned instruction bundle + ALTs**.

Freshness: "Routes are computed against the on-chain state at `contextSlot` and expire within seconds. Do not cache quotes." A different signer than the quoted `userPublicKey` fails. Compute budget: check for a compute-budget program before adding one; use `computeUnitsSafe` when the route omits it. The documented response does not establish an on-chain context slot field for P0 evidence — record slot as UNKNOWN unless the provider exposes it (same rule as the 0x extract).

## Fee fields

Request (per `fee-collection.md`):
- `feeAccount` — ATA to receive the fee; must already exist, or the integrator must add the ATA creation instruction itself
- `feeBps` (u16) — basis points; maximum `10000`; "the limit is the same for every account tier and does not depend on validation status"; higher values are rejected and return no quotes
- `feeFromInputMint` (bool) — default fee side is the **output** token; input side requires `feeFromInputMint: true` and an input-mint ATA
- Fee is deducted **from** the swap amount, not added on top ("with 1 SOL swapped at 1%... user receives output for 0.99 SOL worth of input")
- Only validated/approved accounts may set `feeAccount`

Response: every active-fee `SwapRoute` includes `platformFee` with `amount` (u64, smallest unit) and `fee_bps` (u8). Note the request/response name asymmetry: request `feeBps`, response `fee_bps`.

LP/referral fee fields: not documented on the fee page (UNKNOWN — no referral field seen).

## SDK pins

| Artifact | Pin |
|---|---|
| npm `@titanexchange/sdk-ts` | package.json version `0.1.6`; license MIT; engines node >=18.19 |
| GitHub `Titan-Pathfinder/titan-sdk-ts` | latest tag `v0.1.5` = `cdf9234024058155d2295a6f37bb1253a9e3cc0d`; main `7588482454bee284a7437d0bd5fce6c02edfb60f` (2026-09-08) |
| Rust crates | `titan-api-types = "5"`, `titan-api-codec = "1.2"` (install snippet, sdk.md) |

TS SDK covers Titan Direct (WebSocket) streaming quotes only; Gateway needs `@msgpack/msgpack`. Neither SDK auto-reconnects. Node 18.19+.

## Rate limits / errors

- Published numeric rate limits: none found on any reviewed official page (recorded UNKNOWN; per-tier quotas not published).
- Documented auth failure: `401` for credential/host mismatch (see above).
- Documented fee rejection: `feeBps > 10000` → no quotes returned.
- Error taxonomy beyond HTTP status/statusText: not documented on reviewed pages (UNKNOWN). Official guidance is basic `res.ok` handling.

## Comparison requirements for the quote race

Same canonical mints, exact same base-unit amount, same public `userPublicKey` (taker) as Jupiter/0x when taker-aware comparison is selected, same slippage assumption, bounded time skew; select the officially recommended winner via `metadata.ExpectedWinner` but retain all per-provider entries as losing-quote evidence with their `platformFee`, `computeUnitsSafe`, `instructions` program IDs (route venue identity) and `addressLookupTables`.

## Safety boundary

Returned `instructions`/ALTs are captured as evidence only. Do not compile, sign, submit, or execute. No `feeAccount` setup, no ATA creation, no sponsorship flows. `sign_enabled=false`, `send_enabled=false`.

## Missing / unpinned items (typed)

1. Published numeric rate limits per tier: UNKNOWN (no official page states them).
2. Error-code taxonomy beyond 401/no-quote cases: not documented (UNKNOWN).
3. Exact DART Swap API contract (`/titan/developer-doc/dart-swap-api/overview.md` exists but was not extracted this wave; DART has its own API key): NOT_PINNED_THIS_WAVE.
4. `contextSlot` field in quote response: not established by reviewed pages (UNKNOWN).
5. Referral/LP fee fields: not documented (UNKNOWN).

Acquisition manifest entries for these are in `SOURCE_MANIFEST.json` → `acquisitions`.
