# Kamino (klend) reserve capacity qualification — pinned offline dossier (R02-CAP-B / N08)

Versioned dossier: `kamino-reserve-qualification-2026-11-21`. Owner lane: R02-CAP-B
(`src/lending/kamino.py`) + R03-B (`src/lending/unsigned_builders/kamino_builder.py`).
One lender, one PR, one owner. Supersedes nothing: it extends the earlier pins in
`docs/roadmap/r02-capacity-recovery-2026-10-08/offline/` and
`docs/integrations/offline/kamino-flash-builder-2026-11-14/` (both remain
immutable and authoritative for what they pinned).

## 1. What this dossier qualifies

Exact flash-capacity semantics for one klend reserve resource, pinned offline:

1. **Config tail layout** (Reserve bytes 4904..5496): `borrowLimit`, `depositLimit`,
   `borrowFactorPct`, `borrowRateCurve` (11 × CurvePoint), withdrawal caps and the
   borrow-limit fields — previously `CONFIG_TAIL_LAYOUT_UNPINNED` /
   `BORROW_LIMIT_UNDECODABLE_OFFLINE`.
2. **Exact flash fee math**: fee rule, minimum fee, disabled sentinel, referral
   split — previously `FEE_ROUNDING_RULE_UNPINNED` /
   `ORIGINATION_FEE_PAYABLE_AMOUNT_UNPINNED` / `REFERRER_FEE_VALUATION_UNPINNED`.
3. **Flash fee deduction semantics**: fee charged at repay, borrow transfers the
   exact amount — previously `FLASH_FEE_DEDUCTION_SEMANTICS_UNAUDITED`.
4. **Flash-path eligibility semantics**: emergency mode, Obsolete status, program
   version, no oracle eligibility, `totalAvailableAmount`-only capacity check —
   previously `EMERGENCY_MODE_SEMANTICS_UNPINNED`, `RESERVE_STATUS_ENUM_UNPINNED`,
   `RESERVE_VERSION_SEMANTICS_UNPINNED`, `ORACLE_HEALTH_ELIGIBILITY_UNPINNED`.
5. **LendingMarket eligibility prefix** (referral fee bps, emergency mode,
   borrow-disabled) — previously `LENDING_MARKET_LAYOUT_UNPINNED`.
6. **SPL mint decode** — previously `MINT_ACCOUNT_NOT_DECODED_OFFLINE`.

## 2. Source pins (unchanged qualification base)

| Field | Value |
| --- | --- |
| SDK repo | `https://github.com/Kamino-Finance/klend-sdk` |
| Pinned SDK commit | `3c3a38d4ff9d7cf7b0380a383b81c9cd4f0f58b8` |
| Package version | `13.0.2` (MIT) |
| Program source repo | `https://github.com/Kamino-Finance/klend` |
| Pinned program commit | `a08760976f51a3a58c4a0c6ea27b4a0e565bca79` |
| Program version | `1.25.0` — **BUSL-1.1 reference-only; studied, never vendored** |
| Program id | `KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD` |
| Retrieval channel | `raw.githubusercontent.com` raw blob endpoint at the exact pinned commit |
| Reproduction | `git hash-object <local_path>` must equal the recorded `upstream_git_blob_sha` |

## 3. Upstream drift re-verification (2026-11-21, AGENTS.md rule 4)

| Repo | Pinned commit | Current HEAD at re-verification | Drift |
| --- | --- | --- | --- |
| Kamino-Finance/klend-sdk | `3c3a38d4` | `6a26d6f1b5afb29953ffd139ee8c0c4ca5f26ce6` (2026-10-20) | **DRIFTED** |
| Kamino-Finance/klend | `a087609` | `686913ee421e0c5f3dc44c4c8344461ee0e4fb89` (2026-11-06) | **DRIFTED** |

Both drifts are recorded, not merged: the qualification base stays at the pinned
commits because the deployed program build attestation is itself an UNQUALIFIED
fact that only an authorized rooted read can confirm. Re-pinning the reader to a
newer SDK/program commit is a separate bounded PR gated on that attestation.

## 4. Newly vendored blobs (byte-exact, pure-LF)

From `Kamino-Finance/klend-sdk@3c3a38d4`, `src/@codegen/klend/types/` and
`accounts/`, all MIT codegen:

| Local path (under `vendor-reference/klend-types/`) | Upstream path | Git blob SHA1 |
| --- | --- | --- |
| `BorrowRateCurve.ts.txt` | `types/BorrowRateCurve.ts` | `d2e169a34dc486b5a4c635d81f4aa1f85a1520ac` |
| `CurvePoint.ts.txt` | `types/CurvePoint.ts` | `f2e39273412251c720175e5834d6d9cd99e196ea` |
| `TokenInfo.ts.txt` | `types/TokenInfo.ts` | `54b02c7013f58f819ab2046177d02da4467ecd4e` |
| `PriceHeuristic.ts.txt` | `types/PriceHeuristic.ts` | `e1aa1296113bcc08e57f1ba92d8e905656c214ad` |
| `ScopeConfiguration.ts.txt` | `types/ScopeConfiguration.ts` | `955b2fb62e529a6fee765898828c61a0295eca42` |
| `SwitchboardConfiguration.ts.txt` | `types/SwitchboardConfiguration.ts` | `04da9be3573ee23810c4f6017fd50a6cfd10971e` |
| `PythConfiguration.ts.txt` | `types/PythConfiguration.ts` | `49b6f189e2c082a24cb4f8bfd2c68bae97fda1c9` |
| `WithdrawalCaps.ts.txt` | `types/WithdrawalCaps.ts` | `ad50521ffd3f6d782d69ea346735767b74245720` |
| `BigFractionBytes.ts.txt` | `types/BigFractionBytes.ts` | `3b70a96beb46a43fc11d3a096cde22fecb8424a0` |
| `LendingMarket.ts.txt` | `accounts/LendingMarket.ts` | `80cffa8bc61feb51d491ca23a56b64e52908f667` |

Previously vendored (unchanged, still authoritative): the R-02 offline kit
`docs/roadmap/r02-capacity-recovery-2026-10-08/offline/vendor/kamino/` (`Reserve.ts`,
`ReserveLiquidity.ts`, `ReserveCollateral.ts`, `ReserveConfig.ts`, `ReserveFees.ts`,
`LastUpdate.ts`, `WithdrawQueue.ts`, `fraction.ts`, `package.json`) and the R03-B
flash-instruction codegen in `kamino-flash-builder-2026-11-14/`.

## 5. Program constants (klend@a087609, BUSL-1.1 study-only citations)

From `programs/klend/src/utils/consts.rs`: `PROGRAM_VERSION = 1`,
`RESERVE_SIZE = 8616`, `RESERVE_CONFIG_SIZE = 952`, `LENDING_MARKET_SIZE = 4656`.
From `programs/klend/src/state/reserve.rs`: `enum ReserveStatus { Active = 0,
Obsolete = 1, Hidden = 2 }`. The offset arithmetic of the full Reserve layout
closes on 8616 exactly (config 4840..5792 + configPadding 896 + elevation-group
amounts + withdrawQueue 32 + padding 1632), and `RESERVE_CONFIG_SIZE = 952`
matches the codegen-derived config span — two independent consistency proofs.

## 6. Exact flash fee semantics (pinned)

Source symbols (study-only): `programs/klend/src/state/reserve.rs`
`ReserveFees::calculate_flash_loan_fees` → `calculate_fees(...,
FeeCalculation::Exclusive, ...)`; `programs/klend/src/utils/fraction.rs`
(`fixed` crate `U68F60`, `to_round` = round half away from zero);
`libs/klend-interface` SDK mirror vendored as `fraction.ts` (`mul` = truncating,
`floorToBn`/`ceilToBn` mirror the program's `to_floor`/`to_ceil`).

1. `fee_f_sf = amount * flash_loan_fee_sf` (the U68F60 product
   `amount_f.mul(rate)` is lossless for integer amounts).
2. `fee_f_sf = max(fee_f_sf, 2^60)` — `minimum_fee = 1`, applied **before**
   rounding (program order).
3. `fee = round_half_up(fee_f_sf / 2^60)` — `to_round()` semantics.
4. Referral (only when a referrer account is actually provided):
   `referral_fee = floor(fee_f * bps/10000)` (bps = market `referralFeeBps`;
   bps = 10000 hands the whole fee to the referrer);
   `protocol_fee = fee - referral_fee`.
5. `fee >= amount` fails on-chain with `BorrowTooSmall`.
6. `flash_loan_fee_sf == u64::MAX` is the **disabled** sentinel
   (`FlashLoansDisabled`), never a fee.
7. `originationFeeSf` (4880) is the **standard-borrow** fee; the flash fee is
   `flashLoanFeeSf` (4888). They are distinct resources.

Pinned rule string: `U68F60_MUL_TRUNC_TO_ROUND_HALF_UP_MIN_1`
(`KAMINO_FEE_ROUNDING_RULE` in `src/lending/kamino.py`).

## 7. Exact flash borrow/repay semantics (pinned)

Source symbols (study-only): `handlers/handler_flash_borrow_reserve_liquidity.rs`,
`handlers/handler_flash_repay_reserve_liquidity.rs`,
`lending_market/flash_ixs.rs`, `lending_market/lending_operations.rs`,
`lending_market/lending_checks.rs`, `state/reserve.rs` at `a087609`:

- `flash_borrow_reserve_liquidity(liquidityAmount: u64)` transfers **exactly**
  `liquidityAmount` to the user; **no fee is charged at borrow**.
- Eligibility checks: `check_reserve_emergency_mode`, destination ≠ supply
  vault, `reserve.version == PROGRAM_VERSION (1)`, status ≠ `Obsolete`,
  `flash_loan_fee_sf != u64::MAX`. **No oracle account exists in the flash
  instruction struct and no oracle/price check runs on the flash path** —
  oracle health is only a standard-borrow/liquidation concern.
- Capacity check: `withdraw_including_queued` requires
  `liquidity_amount <= totalAvailableAmount` (byte 224). The flash path may
  consume queued-withdrawal liquidity and performs **no borrow-limit,
  elevation-group or utilization-limit check** —
  `KAMINO_FLASH_BORROW_IGNORES_BORROW_LIMIT = True`.
- `flash_repay_reserve_liquidity(liquidityAmount, borrowInstructionIndex: u8)`
  must appear **after the borrow in the same transaction** with
  `liquidityAmount == borrow.liquidityAmount` and
  `borrowInstructionIndex == borrow instruction index`; multiple borrows and
  multiple repays are forbidden; flash-via-CPI is forbidden.
- Repay transfers `amount + referral_fee` to the reserve, then transfers
  `protocol_fee` to the reserve fee vault. Stale-marking and refresh are
  program-managed; the caller needs no Obligation account.

**Real borrow capacity (not TVL, not vault cash):**
`bound = liquidity.totalAvailableAmount` (program-enforced upper bound of one
flash borrow), repay obligation = `bound + fee(bound)`. Implemented as the
pure function `derive_kamino_offline_flash_capacity_bound()`; it fail-closes on
stale/emergency/obsolete/version-mismatch/sentinel. The bound is **bound-level
offline evidence only**: `effective_capacity_base_units` stays `None` and
`MISSING_EFFECTIVE_FLASH_CAP` + `LIVE_ROOTED_RPC_NOT_AUTHORIZED` stay in the
observation blockers until an authorized rooted capture proves the live
resource state.

## 8. Capture plan (for the future operator-authorized CAPTURE_ONLY run)

Resource identity set per reviewed reserve (all read-only
`getAccountInfo`/`getMultipleAccounts`, batches ≤ 100, per-batch context):

1. Reserve account (8616 bytes, owner = klend program) — full layout pinned.
2. `liquidity.supplyVault` + `liquidity.feeVault` SPL token accounts.
3. `lendingMarket` account (eligibility prefix pinned; referralFeeBps needed
   for the exact repay amount).
4. `liquidity.mint` account (SPL/Token-2022; decimals + authority state).
5. Flashloan Admin equivalent is not required for klend.

Quorum: ≥ 2 separately operated providers/correlation groups, same genesis,
compatible rooted/finalized commitment, explicit slot per response, bounded
skew, state-hash comparison (`DATA_CAPTURE_RUNBOOK_V1.md` S5). Single-RPC
captures stay `BLOCKED_SINGLE_SOURCE`.

## 9. Remaining honest gaps (unknown is not zero)

`CUMULATIVE_BORROW_RATE_UNAUDITED`, `INTEREST_ACCRUAL_LAZY_UPDATE_UNAUDITED`,
`MARKET_PRICE_SEMANTICS_UNAUDITED`, `ORACLE_PRICE_STATUS_SEMANTICS_UNPINNED`,
`RISK_CONFIG_SEMANTICS_UNAUDITED`, `SUPPLY_VAULT_AUTHORITY_BINDING_UNPROVEN`,
`ELEVATION_GROUP_BORROW_LIMIT_SEMANTICS_UNPINNED` — all irrelevant to the
flash-path bound above but relevant to standard-borrow valuation, so they stay
typed and undefaulted. Deployed program build attestation and rooted live
state remain `BLOCKED_LIVE_STATE` / `BLOCKED_SINGLE_SOURCE` until an
operator-authorized capture run.

## 10. Verification

`python docs/integrations/offline/kamino-reserve-qualification-2026-11-21/verify_n08_pins.py`
(blob-hash provenance, offset arithmetic, exact fee vectors; deterministic,
network-free). Tests: `tests/test_r02_cap_b_reader.py` (N08 section),
`tests/test_r02_cap_b_offline_replay.py`, `tests/test_r03_kamino_builder.py`.
