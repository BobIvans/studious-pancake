# Titan adapter — additive exact wire-schema pin (R13-A1)

**Flag:** OFFICIAL_CONTRACT_EXTRACT_ONLY (field/type transcription of current official pages; no full page copies vendored — upstream page copyright, same policy as the wave-1 bundle)
**Retrieved:** 2026-11-14 UTC (R13-A1 lane)
**Base dossier:** `docs/integrations/offline/providers-wave1-2026-11-13/TITAN_SOLANA.md` (PR #621) — endpoint, auth, quotas, fee asymmetry and build-output semantics there remain authoritative; this file pins the EXACT response field shapes the wave-1 dossier did not enumerate.
**Consumer:** `src/solana_parallel_radar/providers/titan.py` (adapter, offline, fail-closed) + `tests/test_r13_titan_adapter.py`

## Sources pinned this wave

| # | URL (canonical) | Retrieved (UTC) | What it pins | License/access |
|---|---|---|---|---|
| S1 | https://titan-exchange.gitbook.io/titan/developer-doc/swap-api/reference/direct/new-swap-quote-stream.md (markdown variant of https://titan-exchange.gitbook.io/titan/titan-developer-docs/swap-api/reference/direct/new-swap-quote-stream.md) | 2026-11-14 | `SwapQuoteRequest`/`SwapParams`/`TransactionParams`, `SwapQuotes`, `SwapQuotesMetadata`, `SwapRoute`, `RoutePlanStep`, `PlatformFee` exact field names + Rust/TS types | Proprietary Titan docs, publicly readable; editorial transcription only |
| S2 | https://titan-exchange.gitbook.io/titan/developer-doc/swap-api/reference/types.md | 2026-11-14 | Type index; "Field names are camelCase on the wire (MessagePack)"; `Instruction` `{p,a,d}`, `AccountMeta` `{p,s,w}`, `Pubkey` 32-byte; `SwapMode` `ExactIn`/`ExactOut` | same |
| S3 | https://titan-exchange.gitbook.io/titan/developer-doc/swap-api/quickstart.md | 2026-11-14 | Portal/Gateway request flow, `quotes` map iteration, `metadata.ExpectedWinner` selection rule | same |
| S4 | https://titan-exchange.gitbook.io/titan/developer-doc/swap-api/guides/stream-and-execute.md | 2026-11-14 | Client-side V0 assembly from `instructions`+`addressLookupTables`; `computeUnitsSafe` budget rule; expiry checks | same |
| S5 | https://titan-exchange.gitbook.io/titan/developer-doc/swap-api/guides/transaction-template.md (referenced from S1 wire-format hint) | 2026-11-14 (via S1 hint text) | Short-name wire format: `Instruction {p,a,d}`, `AccountMeta {p,s,w}`, `AddressLookupTableAccount {p,a}`; "Pubkeys are raw 32-byte arrays, not Base58 strings" (MessagePack) | same |

SDK pins unchanged from the wave-1 dossier (npm `@titanexchange/sdk-ts` 0.1.6 MIT; crates `titan-api-types = "5"`, `titan-api-codec = "1.2"`).

## Exact response shapes (transcribed from S1, Rust struct variants — authoritative types)

### `SwapQuotes` (top-level quote batch)

| Field | Type (Rust) | Notes for the adapter |
|---|---|---|
| `id` | `String` | required — batch id; adapter requires non-empty string |
| `inputMint` | `Pubkey` | required — must equal request mint |
| `outputMint` | `Pubkey` | required — must equal request mint |
| `swapMode` | `SwapMode` | required — wire values `ExactIn` / `ExactOut` (identical to kernel `QuoteDirection`) |
| `amount` | `u64` | required — must equal request amount |
| `quotes` | `HashMap<String, SwapRoute>` | required — keyed by provider ID (`"Titan"`, `"Metis"`, `"Okx"`, …); NOT an array |
| `metadata` | `Option<SwapQuotesMetadata>` | optional; `ExpectedWinner: Option<String>` — official winner-selection rule `quotes[metadata.ExpectedWinner]` |
| `alts` | `Option<Vec<AddressLookupTableAccount>>` | optional; only with `update.includeAltContents`; entries `{p: Pubkey, a: [Pubkey]}` |

### `SwapRoute` (one provider entry)

| Field | Type (Rust) | Adapter mapping |
|---|---|---|
| `inAmount` | `u64` | `input_amount_raw` (must equal request amount for ExactIn) |
| `outAmount` | `u64` | `output_amount_raw` |
| `slippageBps` | `u16` | evidence field; must be ≤ 10000 |
| `platformFee` | `Option<PlatformFee>` | `QuoteFeeComponent(kind="platform_fee")` |
| `steps` | `Vec<RoutePlanStep>` | route venues + pool identities |
| `instructions` | `Vec<Instruction>` | build-output classification; "May not be provided if a full transaction is provided instead" |
| `addressLookupTables` | `Vec<Pubkey>` | evidence-only ALT addresses |
| `contextSlot` | `Option<u64>` | `QuoteFreshness.slot` ONLY when supplied (resolves wave-1 typed unknown #4: `contextSlot` is now PINNED as an optional `SwapRoute` field) |
| `timeTakenNs` | `Option<u64>` | duration, not a timestamp — never used as generation time |
| `expiresAtMs` | `Option<u64>` | ms UNIX → `QuoteFreshness.expires_at_ns` (exact ms→ns multiply) |
| `expiresAfterSlot` | `Option<u64>` | evidence field on `TitanQuoteEntry` |
| `computeUnits` | `Option<u32>` | fallback `compute_unit_estimate` |
| `computeUnitsSafe` | `Option<u32>` | preferred `compute_unit_estimate` ("recommended compute budget that accounts for on-chain variance") |
| `transaction` | `Option<Vec<u8>>` | "Transaction for the user to sign, if instructions are not provided" — evidence-only; NEVER decoded/compiled/signed |
| `reference_id` | `Option<String>` | provider-specific ref (mainly RFQ); evidence field |

### `RoutePlanStep`

| Field | Type (Rust) | Adapter mapping |
|---|---|---|
| `ammKey` | `Pubkey` | `PoolIdentity(AMM_KEY, …)` — the ONLY pool-identity source; empty steps = pool evidence UNKNOWN |
| `label` | `String` | `RouteVenue.venue_label` |
| `inputMint`/`outputMint` | `Pubkey` | step validation only |
| `inAmount`/`outAmount` | `u64` | step validation only |
| `allocPpb` | `u32` | `RouteVenue.share_bps` ONLY on exact `ppb % 100_000 == 0` division (ppb→bps); otherwise UNKNOWN (never rounded) |
| `feeMint` | `Option<Pubkey>` | venue-fee component asset (with `feeAmount`, never alone) |
| `feeAmount` | `Option<u64>` | `QuoteFeeComponent(kind="route_step_{i}_venue_fee")`, inclusion UNKNOWN |
| `contextSlot` | `Option<u64>` | per-pool context; not promoted to quote freshness |

### `PlatformFee`

| Field | Type (Rust) | Adapter mapping |
|---|---|---|
| `amount` | `u64` | fee component `amount_raw` |
| `fee_bps` | `u8` | fee component `rate_text` (documented asymmetry: request `feeBps`, response `fee_bps`) |

Inclusion: official fee-collection doc states the fee is deducted FROM the swap amount → `FeeInclusionState.PROVEN`. The fee SIDE is not carried by the response → `asset_id=None` (UNKNOWN, never assumed).

### `Instruction` / `AccountMeta` (wire short names per S2/S5)

- `Instruction` = `{ p: Pubkey, a: [AccountMeta], d: [u8] }` (`p`=programId, `a`=accounts, `d`=data).
- `AccountMeta` = `{ p: Pubkey, s: bool, w: bool }`.
- MessagePack: `Pubkey` is a raw 32-byte array; portal JSON uses the same short field names (wave-1 dossier). The adapter consumes decoded JSON-shaped mappings and requires base58 strings for `p` fields.

## Adapter decode rules (typed; nothing guessed)

1. **u64 fields**: only exact JSON integers in `[0, 2^64)` are accepted. String-encoded numerics are refused with `SCHEMA_MISSING_PIN` — the portal JSON u64 encoding (number vs string) is NOT pinned (see typed unknowns below).
2. **normalized == raw**: `SwapRoute` amounts are pinned exact base units ("Raw number of tokens to swap, not scaled by decimals"), so `input_amount_normalized == input_amount_raw` and `output_amount_normalized == output_amount_raw`; no decimal rescaling is fabricated.
3. **minimum_output_raw = None** always: Titan exposes no minimum-output field on this surface (UNKNOWN, never zero).
4. **Correlation**: group `titan-argos-router` for every entry of one capture (one operator observation — Argos). Lineage per entry: `("titan", <entry-key-lowercase>)` so Titan `Okx` entries dedup against OKX DEX captures (overlap notes) and OpenOcean composites correlate via the shared `titan` lineage member. Pool ids ONLY from `steps[].ammKey`.
5. **Build-output classification**: `INSTRUCTION_BUNDLE` (non-empty `instructions`), `UNSIGNED_TRANSACTION` (opaque `transaction` string present; bytes evidence-only), `QUOTE_ONLY` (neither). `instructions` absent is tolerated ONLY when `transaction` is present (official mutual-exclusion note); both present = schema drift.
6. **Fee request parameters**: only portal-pinned query params are emitted (`inputMint`, `outputMint`, `amount`, `userPublicKey`, `slippageBps`, `feeAccount`, `feeBps`, `feeFromInputMint`). `feeBps > 10000` is refused at request construction (documented no-quotes rejection).

## Typed unknowns / unpinned items this wave (fail-closed)

| ID | Item | State | Adapter behavior |
|---|---|---|---|
| TITAN-U1 | Portal JSON encoding of u64 amounts (number vs string) | UNPINNED | integers-only decode; strings → `SCHEMA_MISSING_PIN` |
| TITAN-U2 | Portal JSON encoding of `transaction` bytes (base58/hex/raw) | UNPINNED | opaque string accepted as evidence; other shapes → `SCHEMA_MISSING_PIN`; bytes never decoded |
| TITAN-U3 | Portal JSON encoding of instruction `d` data | UNPINNED as string-vs-array | integer array `[0,255]` only (from pinned `Vec<u8>`); else `SCHEMA_MISSING_PIN` |
| TITAN-U4 | Numeric rate limits per tier | UNKNOWN (wave-1) | not modeled; 429 mapped to typed `RATE_LIMITED` on the documented status code only |
| TITAN-U5 | `swapMode` query parameter on the portal REST surface | NOT_PINNED (portal param table omits it; Direct `SwapParams.swapMode` pinned) | portal requests emit no `swapMode`; `ExactOut` on portal → `SCHEMA_MISSING_PIN` |
| TITAN-U6 | MessagePack transport decode (Gateway/Direct binary wire) | NOT_IMPLEMENTED | adapter consumes decoded JSON-shaped mappings only; a msgpack typed decoder needs its own capture + pin |
| TITAN-U7 | Error-code taxonomy beyond 401 / no-quotes / 429 | UNKNOWN (wave-1) | all other statuses → typed `HTTP_ERROR` with detail preserved |
| TITAN-U8 | `timeTakenNs` TS-variant name (`timeTaken` in the TS tab) | NAME_DIVERGENCE (Rust `timeTakenNs` authoritative) | not consumed; treated as optional evidence, never generation time |

## Integrity

Content sha256 of this file (line-ending-normalized) is recorded in `SOURCE_MANIFEST_ADDENDUM.json` alongside acquisition metadata. This is an ADDITIVE versioned dossier; the wave-1 bundle under `providers-wave1-2026-11-13/` is untouched.
