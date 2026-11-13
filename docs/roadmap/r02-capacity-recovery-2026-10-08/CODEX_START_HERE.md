# CODEX START HERE — R02-CAP-UNBLOCK first, R03 contract-only in parallel
This directory is the complete source-of-truth for the next task; all SDK/IDL references needed to start are local in `offline/`. `main` current HEAD must be re-read; the base above is a point-in-time audit only.

## Stage 0 — verify before coding
Read `MASTER_CONTEXT.md` and #585's `docs/verification/r02-2026-10-08/RECEIPT.json`; do not rewrite/reinterpret historical captures. Run `offline/verify_offline.py` and `offline/test_probe_structural.py` with Python stdlib only. Verify vendor Git blob checks. Inspect each vendored upstream SDK reference; files end `.ts.txt` intentionally to prevent auto-import/compilation, but bytes match original Git blob at pinned version. Read `LICENSE_AND_PROVENANCE.md` first for code reuse limits. No website access required.

## Stage 1 — R-02 targeted code PRs (base=main, never merge automatically)
### R02-CAP-A Jupiter
Use `offline/jupiter_token_reserve_layout.json` and existing `src/lending/jupiter_lend.py`. Derive exact `TokenReserve` PDA from pinned Liquidity program using seeds `[b"reserve", mint_pubkey]` (source proof in R02_UNBLOCK_MATRIX.md). Fetch **reserve + mint + SPL vault + flashloan user borrow position + relevant protocol limits** at one finalized/rooted slot and verify program owners & decimals/mints. Add narrow `jupiter_lend` capital graph allowance only when full fee/cap/dynamic borrow gating and independent rooted RPC quorum pass. Existing admin fee=0 is not lender-capacity evidence. Negative where any resource/version cap missing.

### R02-CAP-B Kamino
Use vendored codegen `Reserve.ts`, `ReserveLiquidity.ts`, `ReserveConfig.ts`, `ReserveFees.ts`, Fraction and LastUpdate at klend-sdk SHA `3c3a38d...`; source package `@kamino-finance/klend-sdk@13.0.2`. Exact read via an installed/locally compiled pinned decoder, **NOT fixture decoder**. Inspect reserve liquidity `totalAvailableAmount`, mint/supply vault/tokenProgram, lastUpdate, config status, flashLoanFeeSf (scaled 2^60), caps, oracle and vault actual balance, and lending market/account owner. The local Python prefix probe cannot prove fee/cap, only helps debug byte layouts.

### R02-CAP-C NAVI
Use vendored `@naviprotocol/lending@2.0.12` sources at `naviprotocol-monorepo@40d971c...`. `getAllFlashLoanAssets` fetches NAVI's **off-chain OpenAPI** and may cache; treat as discovery, never on-chain capacity. Read matching current shared pool state/config package/coin decimals through approved Sui gRPC/GraphQL at a recorded checkpoint. v1 vs v2 PTB target determined by `getConfig().version` and must be recorded; no R03 PTB build without deployed package binding.

### R02-CAP-D P0
Use pinned MIT `@0dotxyz/p0-ts-sdk` git version 2.10.0 snapshot `8a8353bb...`. Without a supplied public authority, do **bank discovery mode** (protocol-only read) and report `USER_ACCOUNT_UNKNOWN`; don't block A–C. With authorized public authority, query `client.getAccountAddresses(authority)`, then read & verify an existing marginfi PDA. No `createMarginfiAccountTx`; never generate/account-create a missing position. If none found, `BLOCKED_NO_EXISTING_P0_ACCOUNT`, not absent proof in a different wallet.

## Stage 2 — R03 allowed earlier only as OFFLINE, UNSIGNED test work
Read `R03_SHADOW_BUILDERS.md`. In isolated worktrees, build source-pinned `UnsignedExecutionPlan` contracts / instruction-identity tests and deterministic PTB fixtures for Jupiter, Kamino and NAVI (P0 only with pre-existing account supplied). DO NOT wire any new signer or sender, run on-chain transactions, or claim a live-capable route. Do not let unfinished R02 prevent offline compiler tests; but live-capital-dependent R03 candidate promotion is BLOCKED until R02 per-provider evidence passes. Each code PR targets **main** and is review-only.

## Final completion report
For each provider report PASS_PARTIAL_STRUCTURAL vs LIVE_READ_PROVEN vs BLOCKED with actual slot/checkpoint and provenance, exact reserve/mint/fee/cap and account setup status; mark unknown costs. Include tests executed, negative receipts, new code PR URL and remaining blockers. `sign_enabled=false`, `send_enabled=false`, 27 catalog providers remain disabled. No merge without user approval.
