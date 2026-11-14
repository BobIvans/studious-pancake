# P0-3 Report — Exact direct-state verification: Raydium CLMM + Meteora DLMM

**Status:** `IMPLEMENTED_UNQUALIFIED` for Raydium CLMM (offline decoder + exact-in math + fixtures, verified against vendored vectors); **`BLOCKED_MISSING_PIN` for the Meteora DLMM amount-specific quote** (exact account/state decoders delivered; per-bin quote math is not derivable from the pinned snapshots); **Orca stays `BLOCKED_LICENSE_REVIEW`** (no code).
**Branch:** `codex/p0-3-direct-state-verification-2026-11-13` (review-only PR)
**Base main SHA:** `86be458a87ed3f499cc32ff56426b2866c90422a`
**Date:** 2026-11-13/14

## What was delivered

### 1. `src/providers/raydium_clmm_native.py` (new) — Raydium CLMM, IN_MAIN_UNQUALIFIED

Pinned to the vendored Apache-2.0 snapshots (`vendor-reference/raydium/clmm/`, upstream commit `6d7a0f82d2f293c553c69aaf943377367c6c4cc6`, blob-verified). Reuses the canonical `NativeAccount`/`NativeCaptureError` primitives — no second account infrastructure.

- **Decoders** (discriminator = `sha256("account:<Name>")[:8]`, exact lengths): `PoolState` (1544 B, zero-copy packed offsets per the vendored struct, incl. `status` bitflags where a set bit disables, `fee_on` modes 0/1/2, tick-array bitmap `[u64;16]`), `TickArrayState` (10240 B, `TICK_ARRAY_SIZE=60`, per-tick `TickState::LEN=168`, initialized = `liquidity_gross>0 || orders>0 || remaining>0`), `AmmConfig` (117 B, `trade_fee_rate`/`protocol_fee_rate` over the pinned `FEE_RATE_DENOMINATOR=1_000_000`). v2 `seed_index` layouts and unknown `fee_on` modes fail closed.
- **Tick math** — verbatim port of the pinned bit-by-bit algorithm (all 19 magic constants, `MIN/MAX_TICK=±443636`, `MIN/MAX_SQRT_PRICE_X64`): differential-tested against the vendored test vectors (boundary sqrt prices, the `tick_round_down` set for ±28861, monotonic sequence + round-trip properties over dense samples).
- **Swap-step math** — `compute_swap` ported with the pinned amount split (fee-inclusive `mul_div_floor/ceil` rules), the verbatim `get_delta_amount_0_unsigned`, the pinned fee accounting for all four exact-in fee cases (including the `amount_in + fee == amount_remaining` partial invariant and the fee-on-output dust fix), and the pinned `MaxTokenOverflow`-falls-through-to-from-input behavior. Two documented derivations, both property-tested: `_delta_amount_1` (token1 per sqrt interval: `liquidity·Δ >> 64`, the direct dual of the pinned token0 formula) and `_next_sqrt_price_from_input` (algebraic inverse, Uniswap rounding).
- **Traversal** (`clmm_exact_in_quote`): bitmap-validated tick-array walk (pool-level 1024-bit default bitmap; a walk needing the extension account fails `CLMM_TICK_ARRAY_BITMAP_EXTENSION_REQUIRED` — its layout is not vendored), initialized-tick crossing with the pinned liquidity sign (down = `+liquidity_net`), the pinned inclusive zero_for_one scan with a no-progress guard for the just-crossed tick, a final partial step through uninitialized range (rounding dust can no longer fake-exhaust a swap), and the full fail-closed set: wrong pool/config/vault/PDA/mint bindings, disabled status, zero active liquidity, crossing-to-zero-liquidity with input remaining, missing/duplicate/foreign arrays, amounts out of u64, 100k step limit.

### 2. `src/providers/meteora_dlmm_native.py` (new) — Meteora DLMM, state exact / quote BLOCKED

Pinned to the checked-in Anchor IDL (`lb_clmm.idl.json` 0.12.0, program `LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo`; discriminators byte-verified against `sha256("account:<Name>")[:8]`).

- **Decoders**: `LbPair` (904 B — active_id, bin_step, status, pair_type, mints/reserves, protocol fee, oracle, bin-array bitmap, per-side token-program flags → pinned SPL vs Token-2022 mapping, version byte fail-closed), `BinArray` (10136 B, 70×144-byte bins with amount_x/amount_y/price(u128)/liquidity_supply), pinned bin↔array index mapping (`BN.divmod` truncation semantics, verified: −1→−1, −70→−1, −71→−2) and the pinned per-bin fee law `base_factor · bin_step · 10 · 10^power_factor` (native units; the fee-precision denominator is not vendored, so no percentage conversion is claimed).
- **Reachable-state walk** (`dlmm_reachable_state`): follows the pinned advance rule (`swapForY ? activeId−=1 : activeId+=1`) reporting per-bin reserves — state verification only.
- **Honest boundary**: `dlmm_amount_specific_quote()` always raises `DLMM_AMOUNT_SPECIFIC_QUOTE_MISSING_PIN` — the SDK `./constants`/`./helpers` bodies (`swapExactInQuoteAtBin`, `getBinMaxAmountOut`, `getPriceOfBinByBinId`, `BASIS_POINT_MAX`, `SCALE_OFFSET`) are **not vendored**, so no amount-specific DLMM quote is produced from inferred math. Unblocking requires capturing those official artifacts into a new immutable dossier generation.

### 3. Program-ID defect fix (from the P0-3 baseline defect)

`LBUZKhRxPF3XUpBCjp4YzTKgLLjggiJWUna9LZJRQD3` (wrong) → canonical `…LccjZhTSDM9YuVaPwxo` in `src/config/addresses.py`, `src/ingest/amm_math_dispatcher.py`, `src/ingest/tx_builder.py` (quarantined path: ID correction only, no behavior promotion). The two fabricated "variant" IDs (`whirLbMi2tG34uFp881tua2RZBY9oXKVvVf9xrq7Rqi`, `LbS9W8ioppRE44Yfczz7Spx3SJJ86VNoX8s6iF5K1nL`) are removed — unverified IDs now fail closed (`UNKNOWN_VENUE_OR_POOL`), asserted by a new test.

### 4. Verification hygiene

`.gitattributes` pins `-text` (no EOL conversion) for the two byte-hash-pinned research-reference files — the root cause of the recurring local `core.autocrlf` hash mismatches, without renormalizing the repository.

## Fixtures and tests

`tests/raydium_clmm_fixtures.py` + `tests/meteora_dlmm_fixtures.py`: synthetic byte builders (no mainnet bytes; u128 fields packed as low/high words; i128 `liquidity_net` in two's complement). `tests/test_raydium_clmm_meteora_dlmm_native.py` — **28 tests**, all runnable offline (providers are fcntl-free):

- vendored differential vectors (boundaries, rounding, sequence, round-trip);
- pinned swap-step identities (target-reached exactness incl. overflow corners) and partial-step fee invariants;
- decoder positive facts (PDA/vault/mint bindings, status bits, token-program flags) and the negative matrix (wrong owner/discriminator/length/seed-index, pool/start/PDA mismatches, disabled status, bad fee_on, zero liquidity, missing/duplicate/foreign/not-in-bitmap arrays, extension-required range, config spacing, amount bounds, DLMM version/token-flag/pair binding);
- amount-specific boundary sensitivity (larger amounts cross more ticks, move the price further, pay more fees) and crossing-to-zero-liquidity fail-closed;
- the DLMM missing-pin boundary asserted both directions (state works, quote refuses).

**Execution status:** 28/28 passed locally (Windows, CPython 3.13) — this suite has no fcntl dependency; `tests/test_amm_math_dispatcher.py` 18/18 (ID defect fix); quarantine suite 24/24 (LF re-checkout + `.gitattributes`); offline bundle verifier exit 0; black/flake8/mypy clean on all changed files. CI runs the same suites on Linux (see PR checks).

## Safety

Decoders and math only — no RPC capture loop, no signer/sender/submission/borrowing, no production promotion, no env-flag bypass. Everything is offline fixture evidence (`SYNTHETIC_TEST`); no live chain data was captured or claimed. Orca remains untouched (`BLOCKED_LICENSE_REVIEW`).

## Blockers

| ID | Blocker | Owner |
|---|---|---|
| B-P03-1 | Orca license review (custom Orca License, 2025-02-27+) | user/legal — stays BLOCKED |
| B-P03-2 | Meteora per-bin quote constants/bodies not vendored (`BASIS_POINT_MAX`, `SCALE_OFFSET`, `swapExactInQuoteAtBin`, …) | new immutable dossier generation from official SDK artifacts |
| B-P03-3 | CLMM `DynamicFeeInfo` (80 B) and bitmap-extension layout not vendored — pools needing them fail closed, quotes carry `dynamic_fee_decoded=false` | dossier extension |
| B-P03-4 | No real mainnet account bytes in repo — live read-only RPC qualification is the separate bounded step | opt-in governed capture |

## Next

P0 market-data exit-gate review across PRs #593 (P0-1), #596 (P0-2), and this PR. Live bounded captures and the capital workstream (PRs #583/#586) remain separate lanes.

## Reconciliation note (2026-11-14) — conflicting P0-3 owners resolved

A parallel lane landed its own P0-3 (PR #613, commit `d197b4a0`) while this PR was open. The two implementations **conflict on a pinned fact**: the lane's decoder hard-codes `TICK_ARRAY_STATE_LEN = 10720` / `TICK_STATE_LEN = 176`, but the vendored authoritative snapshot (`vendor-reference/raydium/clmm/tick_array.rs.txt`, blob-verified) declares `LEN = 8 + 32 + 4 + TickState::LEN*60 + 1 + 115` with TickState fields summing to exactly **168** → **10240**. A 10720-byte decoder rejects every real TickArrayState account. Resolution: this PR's vendored-correct decoders are the decoder of record; the lane's module was replaced in the rebase.

Consequences, recorded transparently:
- The lane's test files (`tests/test_p0_3_clmm_native.py`, `tests/test_p0_3_dlmm_native.py`, `tests/p0_3_fixtures.py`) pin the lane's module API (capture envelopes, `array_start_index`, `dlmm_exact_in_quote`) and are removed with this PR; this suite's 28 tests cover the equivalent surface. Their 50 tests passed against their own modules before replacement.
- Dropped lane features that need re-derivation against the correct layout before re-landing: `BinArrayBitmapExtension` (1576 B) decoder, the CLMM protocol/fund fee split in the quote, the CLMM/DLMM "coherent capture envelope", and the DLMM exact-in bin-walk quote — the latter additionally rests on SDK constants that are **not vendored** (`BASIS_POINT_MAX`, `SCALE_OFFSET`, `swapExactInQuoteAtBin`), so this PR's fail-closed `DLMM_AMOUNT_SPECIFIC_QUOTE_MISSING_PIN` boundary remains the honest state.
- Kept from the lane: the canonical DLMM program-id fix in `src/config/addresses.py` (equivalent to this PR's broader dispatcher/tx_builder fix, which this PR also carries).
