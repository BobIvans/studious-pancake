# Jupiter Lend (Fluid) flashloan capacity qualification — offline dossier (R02-CAP-A + R03-A / N06)

Versioned dossier: `jupiter-lend-qualification-2026-11-21`. Owner lanes:
R02-CAP-A (`src/lending/jupiter_lend.py`) + R03-A
(`src/lending/unsigned_builders/jupiter_builder.py`). One lender, one PR, one
owner. Extends (never rewrites) `docs/roadmap/r02-capacity-recovery-2026-10-08/`
(the Jupiter 192-byte TokenReserve layout dossier stays immutable).

**No upstream bytes are vendored in this dossier**: both upstreams are
license-restricted (`Instadapp/fluid-solana-programs` is BSL-1.1 — the
program source is studied, cited and never copied; `jup-ag/jupiter-lend` has
no license file). Provenance is carried by exact commit + git-blob-hash
references instead, consistent with the original R-02 pins.

## 1. What this dossier qualifies

1. **Exact flashloan fee/rounding rule** — previously
   `FEE_ROUNDING_RULE_UNPINNED`:
   `fee = ceil(amount × flashloan_fee / 10_000)` (u128 product, ROUND UP via
   `safe_div_ceil`), scale `1e4 = 100%`, max fee `50` (= 0.5%), minimum
   flashloan amount `1000`; fee charged **at payback**
   (`payback = amount + fee`), the borrow transfers the exact amount; the
   payback instruction must exist later in the same transaction and CPI into
   the flashloan program is forbidden. Implemented as
   `calculate_jupiter_flashloan_fee()` (pure, exact integers).
2. **Flash borrow position (debt ceiling) layout** — previously
   `FLASH_BORROW_POSITION_DEBT_CEILING_UNDECODED`: the liquidity
   `UserBorrowPosition` is a 112-byte `zero_copy` `repr(C, packed)` account:
   protocol @0, mint @32, with_interest @64, amount @65, debt_ceiling @73,
   last_update @81, expand_pct @89 (1e2 scale), expand_duration @91 (secs),
   base_debt_ceiling @95, max_debt_ceiling @103, status @111 (0 Paused /
   1 Active / 2 NotSet). Implemented as
   `decode_jupiter_flash_borrow_position()` (fail-closed on length, owner,
   mint binding).
3. **Utilization scale** — previously `UTILIZATION_SCALE_UNPINNED`: the
   liquidity rate model stores utilization and rates in the 1e2 scale
   (100% = 10_000, 1% = 100).
4. **Precision pins**: `EXCHANGE_PRICES_PRECISION = 1e12`; token decimals
   bounded to `[2, 9]`; `MAX_TOKEN_AMOUNT_CAP = 2^60 − 1`;
   `MIN_OPERATE_AMOUNT = 10`.

## 2. Source pins (qualification base unchanged)

| Field | Value |
| --- | --- |
| Flashloan program | `jupgfSgfuAXv4B6R2Uxu85Z1qdzgju79s6MfZekN6XS` |
| Flashloan IDL | `jup-ag/jupiter-lend@33a22cf7a5bfdd32ab1712dda4adfbeb9b348ad9`, `target/idl/flashloan.json`, blob `0d0ae6d624b33355315e98baaf0a5d00d317beb8`, version `0.1.4` (no license file upstream → hash-pinned, not vendored) |
| Liquidity program | `jupeiUmn818Jg1ekPURTpr4mFo29p46vygyykFJ3wZC` |
| Liquidity IDL | `jup-ag/jupiter-lend@a484ddcf9b34ef6f6d575ad10b0673a18d9c8f31`, `target/idl/liquidity.json`, blob `09209f553900df7da61f84a106ad85767fdac71d`, version `0.1.8` |
| Program source (study-only) | `Instadapp/fluid-solana-programs@626b177f235224bc5d074d39439cd2558f542886` — **BSL-1.1, not vendored** |

## 3. Upstream drift re-verification (2026-11-21, AGENTS.md rule 4)

| Repo | Pinned commit | Current HEAD at re-verification | Drift |
| --- | --- | --- | --- |
| Instadapp/fluid-solana-programs | `626b177` | `626b177` (HEAD unchanged) | **none** |
| jup-ag/jupiter-lend | `a484ddcf` / `33a22cf` (IDLs) | `7960a14a5a760abc41db3ed1395dc5cb56a1f8db` (2026-10-09) | **DRIFTED** |

The jupiter-lend drift is recorded, not merged: the deployed program build
attestation is itself an UNQUALIFIED fact pending an authorized rooted read.
The `flashloan.json` blob re-fetched at the pinned commit reproduces the
pinned hash `0d0ae6d6...` exactly (blob-level provenance verified).

## 4. Remaining honest gaps (unknown is not zero)

`MAX_UTILIZATION_SEMANTICS_UNPINNED` (the enforcement of `max_utilization`
inside the liquidity operate path is not proven here),
`EXCHANGE_PRICE_VALUATION_UNAUDITED` (the precision is pinned at 1e12, but
the exact exchange-price accrual/valuation math is not audited in this
repository), `TOTAL_CLAIM_SEMANTICS_UNPINNED`,
`VAULT_AUTHORITY_BINDING_UNPROVEN`,
`MIN_OPERATE_AMOUNT_ENFORCEMENT_UNPINNED`,
`FLASH_BORROW_POSITION_STATUS_SEMANTICS_UNPINNED` (status values are pinned;
the position-status enforcement in the operate path is not). Effective
capacity stays UNKNOWN: the reserve-side bound requires audited
exchange-price/claim math that this dossier does not provide, so
`MISSING_EFFECTIVE_FLASH_CAP` + `LIVE_ROOTED_RPC_NOT_AUTHORIZED` remain in
every observation.

## 5. Capture plan (for the future operator-authorized CAPTURE_ONLY run)

Resource identity set per reviewed mint: TokenReserve PDA
(`[b"reserve", mint]`, 192 bytes), vault token account, FlashloanAdmin PDA
(93 bytes), and the `flashloan_borrow_position_on_liquidity` UserBorrowPosition
(112 bytes) referenced by the flashloan instruction accounts. Quorum:
≥2 separately operated providers, same genesis, rooted commitment, explicit
slot per response (`DATA_CAPTURE_RUNBOOK_V1.md` S5); single-RPC verdicts stay
`BLOCKED_SINGLE_SOURCE`.

## 6. Verification

Tests: `tests/test_r02_cap_a_reader.py` (N06 section),
`tests/test_r02_cap_a_offline_replay.py`, `tests/test_r03_jupiter_builder.py`.
`verify_n06_pins.py` re-checks the offset arithmetic, exact fee vectors and
gap lists deterministically (network-free).
