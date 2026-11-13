# MASTER CODEX HANDOFF — Studious Pancake research + flashloan arbitrage

Updated: 2026-11-13  
Repo: https://github.com/BobIvans/studious-pancake  
Target: current main; re-fetch and record exact SHA before starting.

## Choose the correct agent mode

### COORDINATOR MODE — recommended for a large multi-agent coding budget

Read `PARALLEL_EXECUTION_MANDATE.md` and act as the master coordinator for the full project. Audit current main and the complete offline technical knowledge base, then run independent research/implementation workstreams concurrently in isolated worktrees/branches. This is **not** one mega-PR: each agent/task owns a bounded vertical, exact paths, tests, evidence and a separate reviewable PR. Freeze shared contracts, enforce dependencies and coordinate integration.

**Do not interpret TASK_INDEX's “one assignment per PR” as “only one workstream may run at a time”.** It means each PR must stay narrow. The coordinator is explicitly allowed to dispatch all independent workstreams in parallel.

### SINGLE-TASK MODE

Read `TASK_INDEX.md`, select one scoped assignment and use its exact task prompt. Do not restart completed work.

## Copy-ready trigger prompt

Continue the existing Studious Pancake project from the latest `main`. Start in **COORDINATOR MODE**. Read `AGENTS.md`, this master handoff, `TASK_INDEX.md`, and `PARALLEL_EXECUTION_MANDATE.md` completely. Then audit current main, merged PRs, open PRs, code owners, source dossiers, tests, CI and capability flags. Produce a machine-readable current-state/owner/dependency matrix before changing code.

Do not rebuild GPR-01, GPR-02, GPR-03, AssetResolver, DynamicUniverse, ResearchEconomicGraph, UniversalArbitrageGraph, FlashCapitalGraph, relation generators, Slumlord, PR118 sizing, exact simulation or QPR/DIN governance if those owners already exist. Reuse them and fill proven gaps only. Current main contains GPR-01 contracts, GPR-02 Solana radar/quote qualification, GPR-03 Sui shadow qualification, Dynamic Universe/TON radar, FlashCapitalGraph and a sender-free Slumlord instruction adapter; the published reports document incomplete real qualification and integration blockers.

Run independent source research, documentation acquisition, fixture work and non-overlapping code tasks in parallel using isolated worktrees. Launch the P0 market-data tasks, GPR-03 Sui remediation, R-02 CAP-A/B/C/D readers, offline R-03 unsigned builders, additional provider dossier/adapter work, TON-RADAR, Dynamic Universe integration, CorrelationLedger verification and Slumlord RentSponsorPlanner work concurrently where dependencies permit. Freeze shared contracts first and never let two agents edit the same canonical owner. Each stream must create its own PR/report with exact SHAs, tests, source pins, evidence and blockers. The coordinator owns dependency-aware integration and merge review.

R-01 is complete (#584); do not repeat it. R-02 remains BLOCKED at live resource capacity per #585, with zero qualified capital edges and 27 disabled candidates; #586 provides offline SDK/layout pins, not live readers. GPR-02/GPR-03 have implementation and bounded read-only evidence, but quote, independent-state, exact-decoder and representation blockers remain as recorded in their handoffs. P0-1/P0-2/P0-3 and R-02/R-03 are not complete merely because an adapter class or source dossier exists.

Preserve the maximum research universe across Solana, Sui, TON, EVM, LSTs, stables, wrappers, RWA, event assets and cross-chain relationships. Do not shrink discovery to flash-borrowable assets. Reuse existing source governance, evidence journal, replay, market graphs, capital graph, exact simulation and paper lifecycle. No second graph, resolver, quote plane, execution kernel, authority or source-governance system.

Use the checked-in offline technical dossiers first. Verify current official contracts online only through tools actually exposed to the agent environment; record exact URLs, versions, retrieval timestamps, commits/blob hashes and licenses. If browser/search/MCP access is absent, report `TOOL_ACCESS_MISSING` and create an acquisition manifest; never invent a live result. Missing docs/state/deployment/capacity becomes typed BLOCKED evidence, never a fabricated PASS.

All qualification stays sender-free: no private keys/seeds, no real account/ATA/position/obligation creation, no signing, sending, borrowing, spending or production promotion. Build unsigned plans and simulate with local tools only. Keep `sign_enabled=false` and `send_enabled=false`.

Do not merge implementation PRs automatically. The coordinator may prepare many parallel PRs, but integration must follow shared-contract and evidence gates and each implementation PR requires human review/approval.

## Current authoritative workstreams

### A. Market-data P0
- P0-1 safe Solana indexed intake → Dynamic Universe.
- P0-2 Jupiter V2 + 0x amount-comparable quote capture; migrate the existing owner, no duplicate adapter.
- P0-3 Raydium CPMM/CLMM + Meteora DLMM direct state/math; Orca remains license-gated.
Start: `docs/roadmap/p0-offline-execution-master-2026-11-13/CODEX_START_HERE.md`.

### B. Flash-capital R-02 / unsigned R-03
- R-02 read-only capacity/fee/resource readers: Jupiter Lend, Kamino, NAVI and wallet-optional Project 0.
- R-03 pinned unsigned borrow/repay builders and Sui PTB hot-potato correctness.
Start: `docs/roadmap/r02-capacity-recovery-2026-10-08/CODEX_START_HERE.md`.

### C. GPR / Dynamic Universe / multi-chain source expansion
- GPR-02 Solana: follow the current handoff blockers; do not rewrite the completed radar.
- GPR-03 Sui: resolve measured checkpoint/object/provider/decoder blockers; remain read-only.
- Dynamic Universe: wire existing live registry/relationship/correlation owners into the supported boot path only where current gates allow.
- TON-RADAR: use existing STON reader, verify current schemas, add Omniston/swap.coffee/direct venue/state lanes where official source contracts support them.
- Additional quote/build providers: Titan, OKX, OpenOcean, Rango, Aftermath, Cetus, 7K/Bluefin7K, FlowX and others one provider at a time with correlation/provenance.
Start: `docs/roadmap/gpr-parallel-radar-rnd-2026-10-07/`, `docs/roadmap/dynamic-universe-master-2026-10-07/`, and `docs/roadmap/universal-source-execution-rnd-2026-10-07/`.

### D. Integrated route qualification
- R-04 capital-aware route/lender/amount selection.
- R-05 full exact unsigned transaction/PTB simulation and economic reconciliation.
- R-06 campaign-gated replayable paper qualification (24h only after all entry conditions pass).
- R-07 broader independently qualified providers.
Full sequence: `TASK_INDEX.md` and the task texts.

## Offline knowledge base policy

Read local source snapshots before browsing. Every changed external contract requires a versioned dossier with canonical URL, retrieval date, exact version/commit/blob hash, license, scope, request/account schema, units/decimals, fees/rounding, quotas, freshness, negative fixtures and local verifier. Do not overwrite historical captures. Do not copy restrictive/custom-licensed source; record a legal blocker.

Offline verifiers prove source/layout provenance only. They do not prove deployed code, current chain state, real capacity, executable liquidity or profitability.

## First commands

- `git status --short --branch`
- `git fetch origin`
- `git rev-parse origin/main`
- `python docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/verify_bundle.py`
- `python docs/roadmap/r02-capacity-recovery-2026-10-08/offline/verify_offline.py`
- `python docs/integrations/offline/solana-p0/verify_offline_bundle.py`

For a large agent budget, use COORDINATOR MODE and `PARALLEL_EXECUTION_MANDATE.md`; use TASK_INDEX only to scope each child PR. Keep all research active, but never confuse research relations with executable routes or lender marketing statements with borrowable capacity.
