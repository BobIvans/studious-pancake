> **Master dependency:** execute the complete original MASTER/GPR/DV/F/F6 programme in `MASTER_FLASHLOAN_MARKET_INTEGRATION_AND_BUILD_BIGGER_UNIVERSE_RU.md` before considering this matrix a complete project plan. SX/EXP/W6 assignments add strategy economics and research/portfolio layers; they do not replace asset/market/source discovery or direct venue/flash-source work.

# Strategy campaign assignments — launch matrix

Полные технические требования, acceptance, dependencies and safety rules are in CODEX_STRATEGY_CAMPAIGN_START_HERE.md and STRATEGY_RESEARCH_CROSSWALK_AND_NEW_GAPS_RU.md. This file is the dispatch matrix, not a second source of truth.

## COORD-00 — coordinator
Refresh current main, PRs, CI, branch protection and exact owners. Reconcile S01–S07, OP/WG, R10, SX, EXP and W6 IDs. Refresh crosswalk and dashboard through the single canonical owner. Never trust snapshot SHA.

## SX — merged vs remaining
- SX-00 #639, SX-01 #641, SX-09 #642, SX-10/SX-11 #643: merged at the checked snapshot; don't repeat.
- SX-12 #645: open at checked snapshot; inspect/review its exact head and merge only after required evidence/checks. It consumes SX-01 ResourceManifest and AGG-05.
- SX-02 flash-mint/lender comparison; SX-03 LLAMMA; SX-04 OEV; SX-05 JIT/LVR; SX-06 CLOB/RFQ/queue; SX-07 complete-set claims; SX-08 lending rate/refinance; SX-13 causal/learning; SX-14 verifiable procurement/mechanism lab; SX-15 observability; SX-16 coordinator integration.
- SX-12 depends on SX-01+AGG-05; SX-15 consumes evidence from completed lanes; SX-16 runs last.

## R10 follow-through
- R10-1: bind CPMM exact evaluator to graph→PR118 sizing→native paper qualification.
- R10-2: replay pinned MarginFi bank evidence to produce only evidence-backed FlashCapitalEdges; no live capacity inference.
- R10-3: residual-fed LST shadow detectors using existing anchors and StrategyContext; missing anchors produce typed exclusions.
- Continue existing R10-A…I by extending only its canonical owner and preserving task IDs.

## EXP — recovered missing/under-specified strategies
- EXP-01 post-confirmed-swap residual, exact quote and opportunity lifetime.
- EXP-02 Meteora DBC curve/graduation→DAMM migration and post-migration identity.
- EXP-03 Raydium CLMM/Meteora DLMM tick/bin liquidity cliff + exact evaluator binding.
- EXP-04 Token-2022 epoch transfer fees, withheld amount and transfer-hook account closure.
- EXP-05 monitor-only lending liquidation forecasts and cascade evidence.
- EXP-06 protocol invariant/state-transition anomaly sidecar.
- EXP-07 empirical opportunity survival, crowding and latency calibration.
- EXP-08 one official intent/RFQ/CoW batch auction pilot; EVM-specific.
- EXP-09 spot-perp/futures/options/funding basis, hedged/non-atomic by default.
- EXP-10 per-pool Uniswap v4 Hook, dynamic fees, custom accounting and exact simulation.

## W6 — recovered Market Ecology
Preserve W6-00…W6-11 and W6F-001…W6F-096:
W6-00 ownership/synthetic-real; W6-01 archetype IR; W6-02 empirical population calibration; W6-03 deterministic ecology; W6-04 own-impact; W6-05 competition/survival; W6-06 bounded PSRO/self-play; W6-07 mechanism design; W6-08 co-adaptation/edge decay; W6-09 sim-to-real; W6-10 MCP/A2A federation; W6-11 knowledge distillation.

## Parallel ownership
Run 4–8 independent workers as a soft target, each with its own current-main worktree, task owner and PR. Shared graph/registry/capability/status/quote/capital/scheduler/simulation owners are serialized. Do not duplicate P0-1/2/3, R02/R03, R13-K or AGG-05. Continue unrelated offline work if another lane is BLOCKED.

## Merge and safety
Autonomous PR creation/merge is authorized only after current required checks, tests, source/license verification, no overlapping owner, clean rebase and mergeability pass. Do not bypass branch protection or fake CI. No keys/accounts/wallets, signing, sending, borrowing, spending, deployments, live enablement or production promotion. No tokenized equities, sandwich/frontrun, user targeting or unauthorized private flow. Unknown is not zero; every amount needs a fresh exact quote; TVL is not capacity.



## SX-17 — Runtime multi-strategy fanout (NEW GAP)
See tasks/SX17_MULTI_STRATEGY_RUNTIME_FANOUT_RU.md. Strategy catalog/library coverage is not runtime coverage. Audit the installed application, six current registrations and the single real two-leg shadow detector. Reuse SX-01, R08, OpportunityConsumer, AGG-05, SX-12 and the existing paper/shadow root. Build bounded deterministic fanout over one immutable snapshot, failure isolation, backpressure, per-strategy budgets and resource conflict admission. Do not add another registry/runner/scheduler or enable stubs. R04/R05/R06 remain promotion gates.

## W6-12 — Observed participant strategy intelligence (NEW GAP)
See tasks/W6_12_OBSERVED_PARTICIPANT_STRATEGY_INTELLIGENCE_RU.md. Extend W6-01/02/05/06 using public/authorized on-chain participant episodes and existing MarketEpisode/decision/replay owners. Evaluate complete net outcomes, failed attempts, inventory, liabilities, fees, capital lock, censoring and drawdown. No real-world identity resolution, doxxing, private flow or automatic copy trading. Research only.

## Current dispatch snapshot after master PR #646 and Titan PR #647
- Current main at this update: 73911801f12eb8c365421d5dcaea40c20a503a0a.
- #646 MASTER FLASHLOAN + Build Bigger Universe archive handoff is merged; it preserves the original full master scope and recovered archive lineage.
- #647 R13 Titan adapter is merged; quote/build kernel remains the shared R13 owner.
- #645 SX-12, #648 SX-08 and #649 SX-03 are still open at this snapshot and have stale bases / are not mergeable against latest main. Rebase/recheck before review; #649 carries a proprietary Curve source license / missing commit and whitepaper blockers and must not be treated as source-qualified.
- Re-fetch main, PRs and CI before dispatch; this is a dated snapshot, not live authority.
