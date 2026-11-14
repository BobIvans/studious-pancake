> **Master dependency:** execute the complete original MASTER/GPR/DV/F/F6 programme in `MASTER_FLASHLOAN_MARKET_INTEGRATION_AND_BUILD_BIGGER_UNIVERSE_RU.md` before considering this matrix a complete project plan. SX/EXP/W6 assignments add strategy economics and research/portfolio layers; they do not replace asset/market/source discovery or direct venue/flash-source work.

# Strategy campaign assignments — launch matrix

Полные технические требования, acceptance, dependencies and safety rules are in CODEX_STRATEGY_CAMPAIGN_START_HERE.md and STRATEGY_RESEARCH_CROSSWALK_AND_NEW_GAPS_RU.md. This file is the dispatch matrix, not a second source of truth.

## COORD-00 — coordinator
Refresh current main, PRs, CI, branch protection and exact owners. Reconcile S01–S07, OP/WG, R10, SX, EXP and W6 IDs. Refresh crosswalk and dashboard through the single canonical owner. Never trust snapshot SHA.

## SX — merged vs remaining
- Merged: SX-00 #639, SX-01 #641, SX-02 #653, SX-07 #651, SX-08 #648, SX-09 #642, SX-10/SX-11 #643, SX-12 #645. Do not repeat these offline/research/contract packages.
- SX-17 archive detector/anomaly taxonomy #654 is merged; exact pair archive dataset #650 is merged separately. Preserve SX-17 for taxonomy; runtime fanout is SX-18.
- SX-03 #649 remains open and source/evidence blocked. R10-2 #655 is open for an offline MarginFi bridge and needs current-main rebase/review. Check current heads/CI before dispatch.
- SX-02 flash-mint/lender comparison; SX-04 OEV; SX-05 JIT/LVR; SX-06 CLOB/RFQ/queue; SX-07 complete-set claims; SX-13 causal/learning; SX-14 verifiable procurement/mechanism lab; SX-15 observability; SX-16 coordinator integration.
- #646 Build Bigger Universe master recovery is merged. #650 is the separate exact archival relationship dataset follow-up; check its status and do not duplicate its rows.
- SX-12 depends on SX-01+AGG-05; SX-15 consumes evidence from completed lanes; SX-16 runs last.

## SX-17 — V3/V4/V6 archive detector and anomaly taxonomy
- Read `ARCHIVE_DETECTOR_TAXONOMY_COVERAGE_GATE_RU.md` and `ARCHIVE_DETECTOR_TAXONOMY_CROSSWALK_V1.json`.
- Reconcile all 64 V3 anomaly IDs, 25 V4 detector templates, 19 V3 route families, 36 V6 route hypotheses, 12 V6 conditional hyperedges and 4 V6 funding primitive families to canonical owners.
- Distinguish strategy families from exact-state guards, source-quality controls, identity constraints, settlement constraints and reference signals. Do not instantiate one runtime strategy per anomaly label.
- Investigate true uncovered mechanisms only (multi-token pool hyperedges, Mento session windows, Balancer rate-provider drift, Phoenix version/queue semantics and hook custom accounting are explicit checks).
- Extend existing owners; no duplicate graph, registry, solver, quote kernel, capital graph, ledger, scheduler or data store.

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
The repository owner explicitly authorized autonomous engineering PR creation, review and merge for this Studious Pancake strategy / Build Bigger Universe / flashloan campaign in the direct instruction dated 2026-11-14. This is the human approval required by AGENTS.md for in-scope campaign PRs; no new confirmation is needed for those PRs. Merge only after current required checks are green, source/license evidence is reviewed, clean rebase and owner-overlap audit pass, all review threads are resolved, the PR is mergeable and branch protection allows it. Never bypass checks, fake statuses or force-push main. This authority is limited to this engineering campaign, not unrelated PRs or any on-chain/financial action. No keys/accounts/wallets, signing, sending, borrowing, spending, deployments, live enablement or production promotion. No tokenized equities, sandwich/frontrun, user targeting or unauthorized private flow. Unknown is not zero; every amount needs a fresh exact quote; TVL is not capacity.



## SX-18 — Runtime multi-strategy fanout (NEW CROSS-CUTTING GAP)
See `tasks/SX18_MULTI_STRATEGY_RUNTIME_FANOUT_RU.md`. Strategy inventory/library coverage is not installed runtime coverage. Audit the six current registrations and single real two-leg shadow detector. Reuse SX-01, merged SX-12 #645, R08, OpportunityConsumer, AGG-05 and existing paper/shadow root. Build bounded deterministic fanout over one immutable snapshot, with deadline/cancellation, failure isolation, backpressure and conflict-safe resource admission. Do not add a second registry/runner/scheduler or enable stubs. R04/R05/R06 remain promotion gates.

## W6-12 — Observed participant strategy intelligence (NEW MARKET ECOLOGY GAP)
See `tasks/W6_12_OBSERVED_PARTICIPANT_STRATEGY_INTELLIGENCE_RU.md`. Extend W6-01/02/05/06 using public/authorized pseudonymous on-chain participant episodes and existing MarketEpisode/replay/decision/causal owners. Evaluate full net outcomes, failed attempts, inventory, liabilities, fees, capital lock, censoring and held-out generalization. No deanonymization, doxxing, private flow or automatic copy-trading; research only.

## Latest verified campaign snapshot
- Main: `9f173d7632cb30190bb8d9174ceba6d116eaec70` after #654.
- Merged: #645 SX-12, #646 MASTER + Build Bigger Universe archive handoff, #647 Titan adapter, #648 SX-08 rate/refinance, #650 exact archived pair/relationship seed dataset, #651 SX-07 complete-set claims, #653 SX-02 flash-mint economics, #654 SX-17 archive detector/anomaly taxonomy.
- Open: #649 SX-03 LLAMMA (research-only; source license/commit/whitepaper/unit and rooted market-state blockers); #655 R10-2 MarginFi offline qualification bridge (requires current main rebase/recheck); #657 is the clean-base SX-18/W6-12 successor. Predecessor #656 is closed as superseded.
- Preserve SX-17 for the archive taxonomy. Runtime fanout is SX-18. W6-12 is a new child of Market Ecology; it does not renumber W6-00…W6-11 or historical W6F-001…096.
