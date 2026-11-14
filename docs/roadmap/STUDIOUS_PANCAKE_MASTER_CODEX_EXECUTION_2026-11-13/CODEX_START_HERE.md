# CODEX START HERE — MASTER FLASHLOAN MARKET INTEGRATION

**This is the entrypoint requested by the project owner.** Read root `AGENTS.md` and the canonical orchestration folder first; this folder extends strategy/pair/source coverage and does not replace those owners.

## Current main / PR truth
- main at this audit: `86be458a87ed3f499cc32ff56426b2866c90422a`.
- #595 and #586 merged; they supersede prior master and R-02 documentation snapshots.
- #593 P0-1 is **OPEN, NOT IN MAIN**, based on an older base and materially behind current main. Review/rebase this existing work; do not create another P0-1 implementation.
- #590 is **closed without merge** and superseded by #595. #594 remains open but stale/diverged; do not merge it unchanged.
- #583 is closed without merge and superseded by the merged offline references; #578 is historical R-01 documentation and must not re-open reconciliation.
- R-01 is complete (#584). R-02 remains BLOCKED with zero qualified capital edges (#585); #586 provides offline SDK references, not live reserve capacity.
- Current runtime remains safe/disabled, paper/shadow bounded and sender-free; live is hard-denied. This assignment does not change runtime authority.

## FIRST TASK — MASTER-00 (one audit/inventory PR)
Read `MASTER_00_RECONCILIATION.md`, all source archive paths in `ARCHIVE_RESEARCH_CROSSWALK.md`, and all canonical registries/owners in `CURRENT_REPO_OWNER_MAP.md`.
1. Refresh current main and all relevant PR/branch/CI dependencies.
2. Reconcile every archive pair row and route family with AssetResolver, Dynamic Universe, ResearchEconomicGraph, current source/venue catalogs and FlashCapitalGraph. Symbol-only matching is a *candidate key*; never auto-merge identities.
3. Produce exact, machine-readable pair delta, source/venue coverage, strategy crosswalk, duplicate/collision queues, exclusions and blocker register.
4. Map each strategy to its canonical owner and distinguish implemented / disabled / fixture-only / unqualified / missing.
5. Publish the shared identity/evidence envelope and file ownership map for parallel workers.
6. Deliver a docs/data PR only; no bulk adapters or strategy implementations in MASTER-00.

## FIRST IMPLEMENTATION WAVE — P0-1 / P0-2 / P0-3 in parallel
After MASTER-00 freezes the shared identity/evidence contract, dispatch separate worktrees:
- P0-1: review/rebase current PR #593 (not a fresh duplicate) for safe indexed intake and Dynamic Universe cadence/coverage.
- P0-2: migrate the existing Jupiter quote owner to current Jupiter Swap API V2 and add same-size comparable 0x capture/replay.
- P0-3: keep Raydium CPMM canonical; complete Raydium CLMM and Meteora DLMM exact state separately; Orca remains license-gated.
They may read, write fixtures and implement independent owners concurrently. Final integrated qualification waits for compatible evidence. Do not serialize them as three sequential giant implementation phases.

## Parallel lanes beyond Solana P0
- R-02 CAP-A Jupiter / CAP-B Kamino / CAP-C NAVI / CAP-D Project 0 bank-only readers (read-only).
- R-03-00 shared unsigned plan contract and protocol-specific offline builders.
- R-09 Sui, TON, EVM, CEX and oracle/reference source research.
- R-10 strategy universe expansion using the crosswalk in this folder and existing `strategy_evolution` owners.
- R-11 reproducibility / CI / Windows-WSL; R-12 dependency security.
These are independent research/offline lanes; use isolated worktrees and avoid concurrent writes to the same canonical file.

## Gated integration
R-04 (amount/capital-aware route selection) needs current exact market quotes + relevant R-02 capacity + R-03 builder. R-05 needs full current-state unsigned transaction/PTB simulation. R-06 needs QPR readiness and exact simulation. R-07 adds one extra lender/provider per focused PR. None is promoted by research topology or the number of agents working.

## Required final report
For each lane: PR URL/base/head, current main ancestry, code owners reused, changed files, actual tests/CI, source pins/licence, evidence receipt/hash, slot/checkpoint/block/amount, status vocabulary, unresolved dependencies, and next task. Record `NOT_RUN` honestly for anything not executed. No merge without owner approval (this request authorizes merging this documentation update only, not code lanes).
