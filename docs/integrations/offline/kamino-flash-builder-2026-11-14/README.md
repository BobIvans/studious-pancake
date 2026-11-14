# Kamino (klend) flash borrow/repay — pinned offline unsigned-builder dossier (R03-B)

Versioned dossier: `kamino-flash-builder-2026-11-14`. Owner lane: R03-B.
Supersedes the "modules absent" state recorded in
`docs/roadmap/r02-capacity-recovery-2026-10-08/offline/` and in the earlier
`tests/fixtures/r03/kamino_golden.json` note: the previously missing generated
flash instruction modules are now pinned below, so the typed blocker
`R03_MISSING_PINNED_BUILDER_ABI` for Kamino flash borrow/repay is removed.

## 1. Source pins

| Field | Value |
| --- | --- |
| Upstream repo | `https://github.com/Kamino-Finance/klend-sdk` |
| Pinned commit | `3c3a38d4ff9d7cf7b0380a383b81c9cd4f0f58b8` |
| Package version | `13.0.2` (declared in pinned `package.json`, blob `efce3196423cab1e81125a74a49014ad36cf6ace`) |
| License | MIT (package.json `license` field at the pinned commit) |
| Retrieval date | 2026-11-14 |
| Retrieval channel | `raw.githubusercontent.com` raw blob endpoint at the exact pinned commit |
| Reproduction | `git hash-object <local_path>` must equal the recorded `upstream_git_blob_sha` |

Pinned blobs added by this dossier (byte-exact copies under
`vendor-reference/klend/`, all pure-LF):

| Local path | Upstream path | Git blob SHA1 |
| --- | --- | --- |
| `vendor-reference/klend/flashBorrowReserveLiquidity.ts.txt` | `src/@codegen/klend/instructions/flashBorrowReserveLiquidity.ts` | `d3e4062acbfac32d9fdb48604832762c33f31c0e` |
| `vendor-reference/klend/flashRepayReserveLiquidity.ts.txt` | `src/@codegen/klend/instructions/flashRepayReserveLiquidity.ts` | `369cd6ac39e4f160d6482790050c469a6d10d811` |
| `vendor-reference/klend/programId.ts.txt` | `src/@codegen/klend/programId.ts` | `e41d81b7d076e2c85c24bc3b45803c2b974a9b2c` |

Previously pinned (unchanged, still authoritative for fee semantics), from the
R-02 offline kit `VENDOR_MANIFEST.json`:

| Local path | Git blob SHA1 |
| --- | --- |
| `docs/roadmap/r02-capacity-recovery-2026-10-08/offline/vendor/kamino/ReserveFees.ts.txt` | `54358dac24be146a1f7b310d2851dd7b61d69789` |
| `docs/roadmap/r02-capacity-recovery-2026-10-08/offline/vendor/kamino/fraction.ts.txt` | `0020a1293fd0bced5987b2429a6b5ed8e2f693e8` |

Program id (pinned `programId.ts`): `KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD`.

## 2. Pinned instruction layout (from the vendored codegen blobs)

### 2.1 `flashBorrowReserveLiquidity`

- Discriminator: `DISCRIMINATOR = Buffer.from([135, 231, 52, 167, 7, 52, 212, 193])`
  = hex `87e734a70734d4c1`.
- Args (borsh struct): `liquidityAmount: u64` (little-endian). Data =
  discriminator (8 bytes) + u64 LE → 16 bytes total.
- Accounts (fixed order, 12 metas; `@solana/kit` roles: 0 = readonly,
  1 = writable, 2 = readonly signer):

| # | Codegen name | Flags |
| --- | --- | --- |
| 1 | `userTransferAuthority` | signer, readonly |
| 2 | `lendingMarketAuthority` | readonly |
| 3 | `lendingMarket` | readonly |
| 4 | `reserve` | writable |
| 5 | `reserveLiquidityMint` | readonly |
| 6 | `reserveSourceLiquidity` | writable |
| 7 | `userDestinationLiquidity` | writable |
| 8 | `reserveLiquidityFeeReceiver` | writable |
| 9 | `referrerTokenState` | optional: `Some` -> writable; `None` -> program address, readonly |
| 10 | `referrerAccount` | optional: `Some` -> writable; `None` -> program address, readonly |
| 11 | `sysvarInfo` | readonly |
| 12 | `tokenProgram` | readonly |

### 2.2 `flashRepayReserveLiquidity`

- Discriminator: `DISCRIMINATOR = Buffer.from([185, 117, 0, 203, 96, 245, 180, 186])`
  = hex `b97500cb60f5b4ba`.
- Args (borsh struct): `liquidityAmount: u64`, `borrowInstructionIndex: u8`
  (little-endian u64 then one u8 byte). Data = discriminator + u64 + u8
  → 17 bytes total.
- Accounts (fixed order, 12 metas, same slot flags as borrow):

| # | Codegen name | Flags |
| --- | --- | --- |
| 1 | `userTransferAuthority` | signer, readonly |
| 2 | `lendingMarketAuthority` | readonly |
| 3 | `lendingMarket` | readonly |
| 4 | `reserve` | writable |
| 5 | `reserveLiquidityMint` | readonly |
| 6 | `reserveDestinationLiquidity` | writable |
| 7 | `userSourceLiquidity` | writable |
| 8 | `reserveLiquidityFeeReceiver` | writable |
| 9 | `referrerTokenState` | optional: `Some` -> writable; `None` -> program address, readonly |
| 10 | `referrerAccount` | optional: `Some` -> writable; `None` -> program address, readonly |
| 11 | `sysvarInfo` | readonly |
| 12 | `tokenProgram` | readonly |

### 2.3 Flash-bracket account identity (why borrow/repay metas match)

The frozen R03-00 contract (`check_account_order`) requires the borrow and
repay bookends to bind the exact same ordered metas. The pinned codegen names
differ at slots 6–7 (`reserveSourceLiquidity`/`userDestinationLiquidity` for
borrow vs `reserveDestinationLiquidity`/`userSourceLiquidity` for repay), but
the flash-bracket semantics bind the same two pubkeys:

- slot 6: the reserve's liquidity supply vault — funds leave it on borrow and
  return to it on repay;
- slot 7: the user's liquidity token account — receives the flash principal on
  borrow and repays from itself (plus fee to slot 8) on repay.

The builder therefore encodes one account binding used by both bookends and
fail-closes (typed `R03_ACCOUNT_ORDER_MISMATCH` from the contract) if a caller
supplies divergent repay accounts.

### 2.4 `borrowInstructionIndex` (u8) semantics

The repay data embeds the absolute index of the flash-borrow instruction in the
final compiled message, as `u8`, after compute-budget instructions and any
route insertion. The builder resolves it via
`resolve_absolute_borrow_index` / `retarget_borrow_index` (pinned in the
Kamino builder since the stub) and `assemble_kamino_flash_message` fail-closes
if the embedded index differs from the final ordering. Index > 255 is a typed
`R03_REPAY_INDEX_OVERFLOW`.

## 3. Units / decimals

- `liquidityAmount` and the fee projection are in the reserve liquidity
  mint's **base units** (raw token smallest units; decimals are mint metadata,
  not encoded in the instruction).
- `ReserveFees.flashLoanFeeSf` / `originationFeeSf` are `Fraction` fixed-point
  with scale 2^60 (`ONE_SF`), per the pinned `fraction.ts` /
  `ReserveFees.ts` blobs. Fee projection (floor/ceil, u64 bounds) is unchanged
  from the stub and stays explicitly `onchain_rounding_known=False`.
- The flash-repay fee is transferred to `reserveLiquidityFeeReceiver` (slot 8)
  by the onchain program; the builder encodes only `liquidityAmount` (the
  principal) in both instructions — the exact onchain fee settlement remains
  `UNKNOWN`, never coerced to zero, and the plan's
  `required_repayment_base_units` stays the conservative principal + ceil-fee
  projection.

## 4. What this unblocks / what stays blocked

- Removed blocker: `R03_MISSING_PINNED_BUILDER_ABI` for Kamino flash
  borrow/repay — the builder now emits real discriminators, ordered metas and
  u64/u8 data with `build_status=BUILT_OFFLINE_UNQUALIFIED`.
- Still true and unchanged: `capacity_status=NOT_EVALUATED` — an offline build
  is never live-capital evidence (R-02 gates remain the only capacity
  authority). No signer, no send, no account/ATA/obligation creation, no
  provider enablement.
- Missing accounts remain typed `R03_NEEDS_ACCOUNT_SETUP`; an absent account
  binding is typed `R03_OPERATOR_ACCOUNT_INPUT_REQUIRED`.
- Referrer accounts (`referrerTokenState`, `referrerAccount`) default to the
  codegen `None` semantics (program address, readonly). `Some` values are
  supported only as caller-supplied pubkeys, encoded exactly as the pinned
  codegen does (writable, in order).
- Exact onchain fee rounding/settlement: `UNKNOWN` (not zero), recorded via
  `onchain_rounding_known=False`.

## 5. Verification

Run offline (no network):

```
python -I docs/integrations/offline/kamino-flash-builder-2026-11-14/verify_offline_bundle.py
```

It re-hashes every vendored blob with `git hash-object` against
`SOURCE_MANIFEST.json` and re-derives the two discriminators and the
borrow/repay data encodings from the vendored codegen text itself.
