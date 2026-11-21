# Project 0 (MarginFi 0.1.12) flashloan deployment rebind — pinned offline dossier (R02-CAP-D + R03-D / N07)

Versioned dossier: `p0-flashloan-rebind-2026-11-21`. Owner lanes: R02-CAP-D
(`src/providers/marginfi/bank_discovery.py` + `src/providers/marginfi/layouts.py`
+ `src/providers/marginfi/errors.py`) and R03-D
(`src/lending/unsigned_builders/project0_builder.py`). One lender, one PR, one
owner. Extends (never rewrites) `docs/roadmap/r02-capacity-recovery-2026-10-08/`
and the PR-028 resource `src/resources/marginfi_pr028.json` (which stays
immutable).

## 1. What this dossier rebinds and qualifies

1. **Full Bank layout** re-pinned from the marginfi 0.1.12 IDL (58 fields):
   `asset_share_value`, `liability_share_value`, `total_asset_shares`,
   `total_liability_shares` (WrappedI80F48, 16-byte signed LE, 48 fractional
   bits), `last_update` (i64), the 544-byte `BankConfig` (`depositLimit`,
   `borrowLimit`, `operationalState`, `oracleSetup`, 5 oracle keys, `riskTier`,
   `assetTag`) and the emissions fields. Cross-check: **every offset PR-028
   also pins matches exactly** (mint 0, mint_decimals 32, group 33,
   liquidity_vault 104, operational_state 600, oracle_setup 601, oracle_keys
   602, borrow_limit 768, risk_tier 776, asset_tag 777, flags 832), and the
   PR-028 bank `struct_size` 1856 equals the 0.1.12 body (3904) minus the
   trailing `_padding_1` array `[[u64; 8]; 32]` (2048 bytes) — the rebind is
   arithmetically proven, not guessed.
2. **Deployment rebind finding (instruction ABI)**: the 0.1.12 IDL
   `lending_account_end_flashloan` requires a third readonly `group` account
   ("needed for the same-asset emode checks and the premium snapshot
   recompute") that the older PR-028 pin does not carry;
   `lending_account_start_flashloan` stays
   `{marginfi_account: writable, authority: signer, instructions_sysvar:
   readonly}` with args `end_index: u64` (LE) — matching PR-028.
3. **Operational-state semantics**: `BankOperationalState` unit enum pinned
   (0 Paused, 1 Operational, 2 ReduceOnly, 3 KilledByBankruptcy,
   4 Uninitialized, 5 ReduceOnlyWithBorrowingPower, 6 CircuitBroken); only
   Operational admits fresh borrows, everything else fail-closes into
   `R02CAPD_BANK_NOT_OPERATIONAL`.
4. **Vault PDA seeds** pinned from the SDK (`liquidity_vault_auth`,
   `liquidity_vault`, `insurance_vault_auth`, `insurance_vault`,
   `fee_vault_auth`, `fee_vault`, `feestate`, `emissions_auth_seed`,
   `emissions_vault` — each `[seed, bank]` under the pinned program).
5. **Offline borrow capacity bound** (not TVL, not vault cash):
   `min(liquidity_vault_amount, borrow_limit − total_liabilities)` with
   `total_liabilities = ceil(total_liability_shares × liability_share_value /
   2^96)` in exact i80F48 rational arithmetic (conservative ceiling for the
   lower bound; exact on-chain share-valuation rounding stays a typed gap).
   Repay obligation = amount + `ceil(amount × origination_fee_raw / 2^48)`
   (pinned PR-028 fee rule). Implemented as the pure function
   `derive_p0_offline_borrow_capacity_bound()`; fail-closed on
   non-Operational banks and missing share inputs. The observation keeps
   `effective_capacity_base_units=None` and its blockers unchanged — bound
   evidence only, never a positive edge.

## 2. Source pins (qualification base unchanged)

| Field | Value |
| --- | --- |
| SDK repo | `https://github.com/0dotxyz/p0-ts-sdk` |
| Pinned commit | `8a8353bb662459e5957b0cbbd2121f4fddb37fc3` |
| Package | `@0dotxyz/p0-ts-sdk`, git version `2.10.0`, MIT |
| IDL | `src/idl/marginfi_0.1.12.json` (vendored byte-exact below) |
| Program id | `MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnsebVacA` |
| Older PR-028 source | `0dotxyz/marginfi-v2@d4c70c84` (kept for provenance) |

## 3. Upstream drift re-verification (2026-11-21, AGENTS.md rule 4)

| Repo | Pinned commit | Current HEAD at re-verification | Drift |
| --- | --- | --- | --- |
| 0dotxyz/p0-ts-sdk | `8a8353bb` | `464699c20e5596ff8fa1514976ad5420821a0aed` (2026-11-03) | **DRIFTED** |

Recorded, not merged: the qualification base stays at the pinned commit until a
rooted deployed-build attestation exists.

## 4. Newly vendored blobs (byte-exact, pure-LF)

| Local path (under `vendor-reference/`) | Upstream path | Git blob SHA1 |
| --- | --- | --- |
| `idl/marginfi_0.1.12.json.txt` | `src/idl/marginfi_0.1.12.json` | `470aed70c225cf3613ef6c6bd92be44c5deed450` |
| `sdk/instructions.ts.txt` | `src/instructions.ts` | `46ad6a680dd27d232e8511b5463563ed4dffe070` |
| `sdk/pda.utils.ts.txt` | `src/utils/pda.utils.ts` | `59a64a30b7476c84a63c8830ef71dde881a234cb` |
| `sdk/share-conversions.utils.ts.txt` | `src/services/bank/utils/compute/share-conversions.utils.ts` | `d6a3f70e7961a7c5c1a7e9a44acd4a6d4d53f517` |

Previously vendored (unchanged, still authoritative): the R-02 offline kit
`offline/vendor/p0/` (`client.ts`, `flash-loan.ts`, `package.json`, LICENSE).

## 5. Gaps

- Cleared with the vendored IDL layout: `BANK_ASSET_SHARE_VALUE_LAYOUT_UNPINNED`,
  `BANK_LIABILITY_SHARE_VALUE_LAYOUT_UNPINNED`,
  `BANK_LIQUIDITY_SHARES_LAYOUT_UNPINNED`,
  `BANK_LAST_UPDATE_SLOT_LAYOUT_UNPINNED`, `BANK_EMISSIONS_LAYOUT_UNPINNED`,
  `BANK_BORROW_LIMIT_SEMANTICS_UNPINNED`.
- New typed gaps (added honestly by the rebind):
  `BANK_LAST_UPDATE_STALENESS_POLICY_UNPINNED` (layout pinned, staleness
  policy is not provable offline) and `BANK_SHARE_VALUATION_ROUNDING_UNAUDITED`
  (exact on-chain i80F48 share rounding; the SDK's BigNumber math is
  display-grade, the bound uses the conservative rational ceiling).
- Remaining (unchanged): `BANK_PDA_SEED_UNPINNED` (the bank PDA seed lives in
  the Rust program, not the TS SDK — banks are operator-supplied addresses and
  seed-based PDAs are verified in the handler),
  `MARGINFI_ACCOUNT_PDA_SEED_UNPINNED`, `ORACLE_PRICE_UNPROVEN`,
  `GROUP_PAUSE_STATE_UNPROVEN`, `BANK_ADDRESS_PROVENANCE_UNPROVEN`.
- R03-D: the start-flashloan instruction is now fully pinned (metas +
  discriminator + u64-le `end_index`); the end-flashloan instruction remains
  `R03_MISSING_PINNED_BUILDER_ABI` because the health remaining-accounts
  computation (`computeHealthAccountMetas` over `projectedActiveBanks`) is
  absent from the pinned kit. No account is ever created or bound; the
  outcome stays typed-BLOCKED in every reachable state.

## 6. Capture plan (for the future operator-authorized CAPTURE_ONLY run)

Resource identity set per reviewed bank (read-only, batches ≤ 100, per-batch
context): Bank account (3912-byte 0.1.12 layout, owner = pinned program),
`liquidity_vault` token account, `marginfi_group` account (panic pause flags),
and — for the user-gated existing-account path — the pre-existing marginfi
account (never created). Quorum: ≥2 independently operated providers, same
genesis, rooted/finalized commitment, explicit slot per response, bounded
skew (`DATA_CAPTURE_RUNBOOK_V1.md` S5); single-RPC verdicts stay
`BLOCKED_SINGLE_SOURCE`.

## 7. Verification

Tests: `tests/test_r02_cap_d_reader.py` (N07 section),
`tests/test_r02_cap_d_offline_replay.py`, `tests/test_r03_project0_builder.py`
(N07 section). Deterministic offline receipt: run the reader/builder test set
twice and compare digests; no network anywhere.
