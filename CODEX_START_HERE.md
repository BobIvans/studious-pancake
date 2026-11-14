# Главный coding-agent trigger — MASTER FLASHLOAN MARKET INTEGRATION + Build Bigger Universe Graph

**Это основное задание для полного market-universe / flashloan проекта.** Не использовать короткий Strategy Expansion trigger вместо него.

Read first:
1. docs/strategy-expansion/2026-11-14/MASTER_FLASHLOAN_MARKET_INTEGRATION_AND_BUILD_BIGGER_UNIVERSE_RU.md
2. docs/strategy-expansion/2026-11-14/BUILD_BIGGER_UNIVERSE_GRAPH_ARCHIVE_RECONCILIATION_RU.md
3. docs/strategy-expansion/2026-11-14/BUILD_BIGGER_UNIVERSE_GRAPH_WORKPACKAGES_V1.json
4. docs/strategy-expansion/2026-11-14/BUILD_BIGGER_UNIVERSE_GRAPH_ARCHIVE_MANIFEST_V1.json

Сохраняй полный исходный MASTER scope: MASTER-00 → P0 → Sui → CLOB → EVM → additional economic integrations. Новый архивный crosswalk дополняет, а не заменяет master roadmap. Strategy Expansion SX/EXP/W6 остаётся связанным дочерним workstream.

## Strategy campaign update — 2026-11-14

The expanded all-project strategy campaign now lives at:
`docs/strategy-expansion/2026-11-14/CODEX_STRATEGY_CAMPAIGN_START_HERE.md`

Read next:
1. `STRATEGY_RESEARCH_CROSSWALK_AND_NEW_GAPS_RU.md`
2. `STRATEGY_RESEARCH_EXECUTION_ASSIGNMENTS_RU.md`
3. `STRATEGY_RESEARCH_ACCEPTANCE_MATRIX_V2.json`
4. `ARCHIVE_DETECTOR_TAXONOMY_COVERAGE_GATE_RU.md` and `ARCHIVE_DETECTOR_TAXONOMY_CROSSWALK_V1.json` (SX-17)
5. `ARCHIVE_SOURCE_MATERIALIZATION_RU.md` (verify original source archives before PAIR-00 completion)

It extends merged #599/#622/#631/#637 and the SX/R10 work with recovered parallel-chat strategies and Wave-6 Market Ecology. Snapshot at authoring: `d52e61f36ece249c1221c8e71d22aa29ef476e21`; #643 merged (SX-10/SX-11), #645 open (SX-12). Always re-fetch current main, open PRs and checks. Do not duplicate existing/open work. PAIR-00 row-level archive reconciliation is mandatory; see `PAIR_ARCHIVE_COVERAGE_AND_IMPORT_GATE_RU.md` and the preserved V6 175-pair catalog. SX-17 separately reconciles 64 V3 anomalies, 25 V4 detectors, 19 V3 routes, 36 V6 routes, 12 V6 hyperedges and 4 funding primitive references. The repository owner expressly authorized autonomous create/review/merge of in-scope campaign PRs in the ChatGPT instruction dated 2026-11-14; merges remain conditional on all CI, review, provenance, ownership and branch-protection gates. This authority does not authorize live/on-chain financial actions.

# Start here — Studious Pancake

For Codex CLI, GLM-5.3-Flash and other coding agents:

1. Read `AGENTS.md`.
2. Read `docs/roadmap/agent-execution-master-2026-11-13/CODEX_START_HERE.md`.
3. Read `MULTI_AGENT_EXECUTION_PLAN.md`, `PROJECT_KNOWLEDGE_BASE_MAP.md`, and `TASK_INDEX.md`.
4. Read the strategy overlay at `docs/roadmap/STUDIOUS_PANCAKE_MASTER_CODEX_EXECUTION_2026-11-13/CODEX_START_HERE.md` and the canonical `PARALLEL_EXECUTION_STATUS.json`.
5. Fetch latest main, open PRs and CI; record the exact SHA before dispatch.
6. Use a coordinator and isolated worker worktrees. One task, one owner, one focused PR. Shared-owner edits are serialized.

## Current truth (2026-11-14 audit)
- P0-1 #593, P0-2 #604 and P0-3 #613 are **already merged baselines**. Do not reimplement; continue their residual qualification only.
- R-02 CAP-A #602, CAP-B #612 and CAP-C #609 are merged partial/offline readers; effective live capacity is still UNKNOWN. CAP-D Project 0 bank-only reader remains an active lane.
- R-03 #606 is merged as unsigned/offline builder contracts. Jupiter/NAVI are BUILT_OFFLINE_UNQUALIFIED; Kamino ABI and P0 existing-account path remain blocked.
- #614 adds seven evidence-gated residual families and aligned lead/lag; reuse the canonical relation/correlation owner.
- R-01 #584 is complete. R-02 still has 0 qualified capital edges. R-04/R-05/R-06 remain dependency-gated.
- #615 is the canonical parallel status dashboard. Its recorded snapshot uses the preceding main SHA; refresh it before dispatch/reporting. Do not create a second PROJECT_STATUS owner.

## Next execution order
**MASTER-00 crosswalk refresh first**: reconcile pair/source/strategy/dependency history against today's main, without rebuilding P0-1/2/3. After the interface/ownership map is refreshed, parallelize residual work: R-02 CAP-D and user-gated live evidence, R-03 Kamino/P0 builder conformance, R-09 data feeds, R-10 strategy experiments, R-13 multiprovider quote/build research, R-14 rent economics and R-08 composition audit.

R-04 selector → R-05 complete unsigned transaction/PTB simulation → R-06 paper qualification remain gated by exact quotes, relevant effective capital capacity, matching builder conformance, complete same-state simulation and QPR readiness.

Keep the research universe broad, while separating LOCAL_ATOMIC, CONDITIONAL_HYPEREDGE, HEDGED_NON_ATOMIC, SIGNAL_ONLY and EXCLUDED classes. Robinhood Stock Tokens and tokenized equities remain excluded. No private keys, accounts/ATAs/obligations creation, signing, sending, borrowing, spending, deployments, provider enabling or production promotion. Live stays hard-denied.



## Latest strategy campaign expansion — 2026-11-14

The current verified main snapshot is `9f173d7632cb30190bb8d9174ceba6d116eaec70` (after PR #654). The full archive-backed MASTER handoff is #646; exact historical relationship rows are #650; archive taxonomy is #654 (**SX-17**). Keep the full MASTER scope first.

Additional assignments:
- **SX-18 runtime parallel strategy fanout:** `docs/strategy-expansion/2026-11-14/tasks/SX18_MULTI_STRATEGY_RUNTIME_FANOUT_RU.md`. Current registry has six entries but only one real two-leg shadow detector. Reuse existing app/registry/consumer/AGG-05/paper owners; no second runtime infrastructure.
- **W6-12 observed participant strategy intelligence:** `docs/strategy-expansion/2026-11-14/tasks/W6_12_OBSERVED_PARTICIPANT_STRATEGY_INTELLIGENCE_RU.md`. Public/authorized pseudonymous on-chain episodes, complete net attribution, replay and holdout only; no deanonymization or copy-trading.

Merged since the prior snapshot: #645 SX-12, #646 master/archive handoff, #647 Titan adapter, #648 SX-08, #650 pair archive dataset, #651 SX-07, #653 SX-02 and #654 SX-17 archive taxonomy.
Open work requiring current rebase/source review: #649 SX-03 (Curve source/license/whitepaper/unit/rooted-state blockers) and #655 R10-2 (MarginFi offline qualification bridge). #656 is the predecessor documentation PR; this clean-base successor is intended to replace it after checks. Re-fetch main/open PRs/CI before dispatch; this dated snapshot is not permanent truth.
