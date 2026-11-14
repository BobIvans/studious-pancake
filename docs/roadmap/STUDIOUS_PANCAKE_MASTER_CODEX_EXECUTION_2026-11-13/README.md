# MASTER FLASHLOAN MARKET INTEGRATION — research/strategy execution overlay

**Repository:** `BobIvans/studious-pancake`  
**Audited main:** `86be458a87ed3f499cc32ff56426b2866c90422a` (2026-11-13 20:04:46 UTC)  
**Purpose:** connect the broad historical market/strategy research from parallel conversations to the current repository without creating duplicate code owners.

This directory is the strategy-coverage and MASTER-00 extension requested by the owner. The canonical orchestration handoff remains:
- `AGENTS.md`, root `CODEX_START_HERE.md`
- `docs/roadmap/agent-execution-master-2026-11-13/` — canonical current whole-project plan and task index
- `docs/roadmap/p0-offline-execution-master-2026-11-13/` — P0-1/2/3 assignments
- `docs/roadmap/r02-capacity-recovery-2026-10-08/` — R-02/R-03 offline lender source pack
- `docs/strategy_evolution/` and `src/strategy_evolution/` — existing strategy intelligence owners

## Read order
1. `CODEX_START_HERE.md`
2. `MASTER_00_RECONCILIATION.md`
3. `ARCHIVE_RESEARCH_CROSSWALK.md`
4. `CURRENT_REPO_OWNER_MAP.md`
5. `STRATEGY_UNIVERSE_ATLAS.md`
6. `MASTER_EXECUTION_ROADMAP.md`
7. `AGENT_ASSIGNMENTS.md`
8. `MASTER_PAIR_DELTA_SUMMARY.json`, `STRATEGY_CROSSWALK.json`, `DIRECT_VENUE_CROSSWALK.json`, `MASTER_PR_DEPENDENCY_INVENTORY.json`

## Critical execution decision
**MASTER-00 is the first task. P0-1, P0-2 and P0-3 are the first market-data implementation wave after the shared identity/evidence interface is frozen; they are independent parallel lanes, not a single monolithic first task and not a serial P0-1 → P0-2 → P0-3 implementation chain.** R-02 CAP-A/B/C/D and R-03-00 offline contracts can also proceed concurrently in isolated worktrees. Exact route integration remains dependency-gated.

The archive-derived pair index reports 1,897 source rows and 959 chain+casefold-symbol candidate clusters. These are *research keys only*: the 938 repeat mentions do not prove asset aliases, market duplicates, or shared liquidity. Codex must reconcile each candidate through the current AssetResolver/MarketIdentity owners. All archive pairs remain non-executable until current evidence proves identity, market, amount quote, lender capacity and settlement.

## Explicit constraints
- Keep Robinhood Stock Tokens and tokenized equities excluded from candidate execution and runtime selection.
- Keep other RWA/FX/gold data as reference-only unless independently qualified, and never turn a ticker into asset identity.
- No new graph, asset registry, market registry, quote engine, data-source catalog, strategy registry, correlation ledger, flash-capital ledger, route solver, journal, authority, or paper runtime.
- All providers remain disabled until their own proof gates pass. No signing, sending, borrowing, account/ATA/obligation creation, deployment, spending or production promotion.
- GLM-5.3-Flash's token allocation is a throughput resource, not a reason to run conflicting writes or bypass review. Use one worktree and one PR per owner/task.
