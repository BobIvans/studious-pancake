# R-02 — test matrix and acceptance

## R-01 precondition
Must first publish or record R-01 disposition. No old-branch megamerge. Show exact code ancestor and unique QPR commit treatment; record current SHA. Full verify_repo.py passes or blockers documented and fixed in distinct PR.

## Contract/unit tests for EACH of four readers
1. Unsupported provider, wrong chain, wrong network genesis, owner/program/package mismatch => no edge, typed negative.
2. No raw evidence, stale slot/checkpoint, source generation differs from resolver generation, missing protocol deployment/source version pin => no edge.
3. Mint mismatch, token program mismatch, Sui coin type alias/decimals mismatch, unreviewed wrapper/tag => no edge.
4. Paused/disabled/active in-progress flashloan, empty vault, insufficient available borrow capacity, zero or negative asset amount => no edge.
5. Borrow cap smaller than vault, locked/reserved funds, fee-on-transfer/token2022 hooks, unknown rounding/precision => safe bound or reject (never vault-balance-only fallback).
6. Exact fee: tested nonzero fees, rounding up in atoms, integer math, fractional rate; ambiguous UI %, SDK float or stale fee => reject.
7. Lender position/account init detection YES/NO/UNKNOWN and cost estimate: account-free shortlist cannot include YES or UNKNOWN as VERIFIED_NO_SETUP; missing ATA must not be hidden.
8. Quota/rate/429/retries: one operator quota across aliases, bounded attempts and serialized negative outcomes; no credentials in capture/logs.
9. Offline capture/replay: same capital edge IDs, byte hashes and negatives, no RPC/network in replay, tampered evidence blocked.
10. Production gates: sign_enabled=false, send_enabled=false; no createMarginfiAccountTx, initializeAccount, initObligation, addPosition, sendTransaction, executeTransaction or wallet keypath called under R-02.
11. No network available: process returns honest report and zero qualified edges, not fabricated live snapshots.
12. Current real snapshot should be traceable to block/slot/checkpoint, RPC identity, decoded authoritative state and underlying source pin. No soft fallback to static assets.

## Provider-focused
- Jupiter: admin paused, active, fee!=0, mismatched liquidity program, signer ATA absent, incompatible on-chain decoded version; no broad whitelist bypass.
- Kamino: invalid reserve owner, distinct regular/flash borrow, unverified flashfee, wrong instruction index/ABI version, absent user obligation should not trigger initialization.
- NAVI: getAllFlashLoanAssets max and flashloanFee parsed from exact strings, resource id + decimals reviewed, Sui checkpoint/no legacy JSON-RPC, PTB receipt preserved for R-03.
- P0: first-time missing account => blocked/no create; existing account read-only; DEFAULT vs integration banks; SDK v2.8.0+ pin; CPI/direct ordering.
- DeepBook optional: pool-share vs borrowable flash cap and BalanceManager cost are distinct.

## Execution plan and acceptance thresholds
R02-0: select official versions and validate owner identities; no live requests until quota source admission. R02-A/B on Solana may be independent worktrees; R02-C NAVI on Sui independent; R02-D Project0 account-dependent independent. All PRs target main with one capital graph schema owner integrated serially.

**PASS** only when 4 readers have pinned source and strict schema tests, at least one independently verified actual on-chain snapshot per available provider (or truthful typed negative due to access), reproducible offline replay, cost/account classification, and successful existing QPR/Graph tests. Unavailable external connectivity does NOT count as positive-live PASS; mark BLOCKED_LIVE_READ honestly and keep readers opt-in.

After R-02 acceptance: R-03 protocol builders -> R-04 selector -> R-05 full atomic simulation -> R-06 repeatable paper campaign -> R-08 explicit promotion review. Even successful simulation is not profit/production proof.
