# MASTER CODEX HANDOFF — Studious Pancake research + flashloan arbitrage

Updated: 2026-11-13  
Repo: https://github.com/BobIvans/studious-pancake  
Target: current main; re-fetch and record exact SHA before starting.

## Copy-ready trigger prompt

Continue the existing Studious Pancake project from the latest main. Do not redesign or duplicate its engines. Read this master handoff and TASK_INDEX.md, then read the linked P0 market-data and R-02/R-03 flash-capital offline dossiers completely. R-01 is already complete (#584); do not repeat branch reconciliation or re-merge old branches. QPR-01 fixes are already part of the current project state; verify current owner hashes, do not recreate them. R-02 is still BLOCKED at live resource capacity: #585 records only partial Jupiter/Kamino/Sui observations, zero qualified capital edges and 27 disabled candidates. #586 is merged and supplies pinned offline SDK/layout references. First run all local offline verifiers, audit latest code/PRs/CI and produce a code-owner/status matrix. Then execute one narrowly scoped task at a time: R02-CAP-A Jupiter, R02-CAP-B Kamino, R02-CAP-C NAVI, R02-CAP-D wallet-optional Project 0; in parallel only offline/unsigned R03 contracts/builders. After relevant R-02 evidence and market P0 exact-state/quote gates are complete, proceed to R04 capital-aware route selection, R05 full atomic simulation, R06 gated replayable paper qualification, and only then R07 additional providers. Preserve the maximum research universe (Solana, Sui, TON, EVM, long-tail assets, LSTs, stables, wrappers and cross-chain signals); do not shrink discovery to lender-supported tokens. Reuse existing AssetResolver, DynamicUniverse, ResearchEconomicGraph, UniversalArbitrageGraph, FlashCapitalGraph, relation generators, PR118 sizing, ExactSimulationFinalizer, QPR/DIN governance and paper lifecycle. No second graph, market resolver, execution kernel, authority or source-governance system. Use checked-in offline dossiers first; because internet is available, verify official source versions only where freshness matters, record exact URLs/versions/commit/blob hashes/licenses and update versioned dossiers instead of guessing. Missing docs/state/deployment/capacity becomes typed BLOCKED evidence, never a fabricated PASS. No wallet secrets, account/ATA/position creation, signing, sending, borrowing, spending or production promotion. Produce small review-only PRs targeting current main with exact SHAs, tests, offline replay, live/negative receipts and remaining blockers. Do not merge implementation PRs without explicit human approval.

## Current authoritative workstreams

### A. Market-data P0 — three already documented tasks
- P0-1 safe Solana indexed intake → Dynamic Universe.
- P0-2 Jupiter V2 + 0x amount-comparable quote capture (migrate existing owner; do not add duplicate adapters).
- P0-3 direct state / exact amount math for Raydium CPMM/CLMM, Meteora DLMM; Orca stays blocked pending license approval.
Start: docs/roadmap/p0-offline-execution-master-2026-11-13/CODEX_START_HERE.md.

### B. Flash-capital R-02 / R-03
- R-02: live, read-only capital readers for Jupiter Lend, Kamino, NAVI and Project 0.
- R-03: source-pinned unsigned borrow/repay builders and Sui PTB hot-potato correctness.
Start: docs/roadmap/r02-capacity-recovery-2026-10-08/CODEX_START_HERE.md.
Broad provider research: docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/README.md.

### C. Integrated route qualification
- R-04 capital-aware route/lender/amount selection.
- R-05 complete exact transaction/PTB simulation and economic reconciliation.
- R-06 campaign-gated, replayable paper qualification (24h only when entry conditions pass).
- R-07 expand independently qualified providers from the 27-candidate catalog.
Full sequence and prompts: TASK_INDEX.md and tasks/.

## Offline knowledge base policy
Read local source snapshots before browsing. Internet is an optional verification/update mechanism, not a missing-document workaround. Every changed external contract requires a versioned dossier with canonical URL, retrieval date, exact version/commit, blob/SHA-256, license, scope, request/account schema, units/decimals, fees/rounding, quotas, freshness, negative fixtures and local verifier. Do not overwrite historical captures. Do not copy source under restrictive/custom license; record the legal blocker.

The offline verifiers validate provenance/layout snapshots only; they do not establish deployed code, current chain state, real capacity or profitability.

## First commands
- git status --short --branch
- git fetch origin
- git rev-parse origin/main
- python docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/verify_bundle.py
- python docs/roadmap/r02-capacity-recovery-2026-10-08/offline/verify_offline.py
- python docs/integrations/offline/solana-p0/verify_offline_bundle.py

Use the task index to select exactly one implementation slice. Keep broad research alive, but never confuse a research relation with an executable route or a lender marketing statement with borrowable capital.
