# CODEX START HERE — Strategy Expansion Pack (separate from market integration)

Repository: `BobIvans/studious-pancake`

## Mission

Build the broadest technically grounded, safely qualified strategy knowledge and execution-preparation layer by reconciling all prior strategy discussions, current repo strategy packs and the new additive files in this directory.

**This is NOT the MASTER FLASHLOAN MARKET INTEGRATION assignment. Do not copy, rewrite, extend in-place, replace, or take ownership of that assignment.** Existing agents own it. Do not modify its files. This pack is the strategy-family/economics/parallel-execution overlay and must coordinate with the market-integration agents through evidence contracts only.

## Read first

1. `README_RU.md`
2. `STRATEGY_GAP_ANALYSIS_RU.md`
3. `STRATEGY_CATALOG_AND_EXECUTION_CLASSES_RU.md`
4. `PARALLEL_STRATEGY_EXECUTION_ARCHITECTURE_RU.md`
5. `STRATEGY_EXPANSION_ASSIGNMENTS_RU.md`
6. `STRATEGY_ACCEPTANCE_MATRIX.json`
7. Existing S01–S07, OP-01…OP-28, WG-01…WG-28, STRATEGY_UNIVERSE_ATLAS, STRATEGY_CROSSWALK, R10 strategy task/inventory/replay report.

Refresh all statuses against current main and open PRs. Do not rely on snapshot SHAs or stale task statuses.

## First action: SX-00 only

Produce an evidence-based reconciliation report before editing source:
- every existing strategy family, opportunity, work package and R10-A…I lane;
- what is already represented, what has a canonical owner, what is actually implemented, fixture-only, stub, planned, blocked or research-only;
- missing acceptance fields and genuinely new families from the gap analysis;
- exact next bounded task and dependency per family;
- active PR/file ownership conflicts;
- duplicate/retired assignments to avoid.

Do not redo the P0 market-intake, Jupiter/0x quote capture, Raydium CLMM/Meteora DLMM or other work in the separate MASTER market-integration assignment. Consume its future verified evidence through the existing contracts.

## Execution

After SX-00, run independent work packages from SX-01…SX-15 in parallel only when their canonical owners and files do not overlap. Use one coordinator for shared files and dependency integration. Preserve original S/WG/OP/R10 IDs. No new graph, solver, registry, ledger, journal, data store, scheduler, capital graph or release authority.

Use the exact owner map in the assignments. Each PR must be small, bounded, tested, evidence-backed and additive. If external proof, license, live data, credentials or human approval is missing, deliver a typed BLOCKED result with the exact missing artifact; do not fake it.

## Mandatory deliverables

1. Refreshed strategy crosswalk (machine-readable + human-readable).
2. Owner-level gap report with no duplicate assignments.
3. Contract/schema mapping into existing canonical models.
4. Per-family falsifiable hypothesis, null, controls, economics, resources, failure modes and acceptance gates.
5. Deterministic replay corpus including positive, negative, stale, partial, rejected and no-trade episodes.
6. Parallel strategy scheduler/portfolio resource model using existing AGG-05 and shared state owners.
7. Separate evidence bundles and capability status per strategy family.
8. PR links and exact changed files; no automatic merge.

## Safety and correctness

- Keep live hard-denied. No signing, sender, wallet creation, borrow, submission, Jito live path, production promotion or env-flag bypass.
- Keep `OrderbookAmmStrategy`, liquidation and other fixture-gated shells disabled until their own gates pass.
- Exact quote each amount; no quote scaling or marginal-weight profit claims.
- No TVL capacity; no shared-pool double counting.
- Bridges, CEX settlement, TON async, queues, maturity and multi-period funding are inventory/research strategies unless proven otherwise.
- No Robinhood Stock Tokens/tokenized equities.
- No sandwich, frontrun, user targeting or unauthorized private flow.
- Models/correlation are advisory only.

## Definition of done

A strategy is only “covered” at the tier evidenced by its identity, source rights, exact state, quote, capacity, all-in economics, shared-resource feasibility, build/simulation/paper artifacts and holdout replay. A documented idea without those proofs remains research/blocked. Do not call the bot production-ready or profitable.


## Research expansion v2 — current continuation

The original SX-00 reconciliation is already merged in PR #639; do not repeat it from its old 5769 baseline. PR #640 has wired unsigned Kamino plan references into the existing planner; do not reimplement it. Refresh current main, open PRs and CI before dispatch.

Read:
- STRATEGY_RESEARCH_ARCHIVE_ADDENDUM_RU.md
- STRATEGY_RESEARCH_ACCEPTANCE_MATRIX_V2.json

The v2 addendum adds SX-17…SX-25: DEX-native flash accounting, collateral-first callbacks, credit-conditioned AMM liquidity, derivatives basis/options, inventory-aware OMS, public trader/bot archetype intelligence, event lifecycle, chain/dataset admission and opportunity half-life/competition intelligence.

Execute all original SX-01…SX-16 residual work plus SX-17…SX-25. Use SX-00 (#639) dispositions as the starting owner map, then refresh statuses against latest main. Do not duplicate R10 items 1–3 (R04/R06, R02-CAP, R10 owners), P0/R09/provider lanes, PR #638 kernel or PR #640 Kamino planner wiring.

The v2 machine-readable acceptance matrix is an additive overlay; keep v1 intact and reconcile both in SX-16. “Ready system” means every family has one owner, execution class, evidence requirements, reproducible tests/replay, typed status and next dependency. It does not mean every family is live or profitable.
