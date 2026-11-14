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

It extends merged #599/#622/#631/#637 and the SX/R10 work with recovered parallel-chat strategies and Wave-6 Market Ecology. Snapshot at authoring: `d52e61f36ece249c1221c8e71d22aa29ef476e21`; #643 merged (SX-10/SX-11), #645 open (SX-12). Always re-fetch current main, open PRs and checks. Do not duplicate existing/open work. PAIR-00 row-level archive reconciliation is mandatory; see `PAIR_ARCHIVE_COVERAGE_AND_IMPORT_GATE_RU.md` and the preserved V6 175-pair catalog. The repository owner expressly authorized autonomous create/review/merge of in-scope campaign PRs in the ChatGPT instruction dated 2026-11-14; merges remain conditional on all CI, review, provenance, ownership and branch-protection gates. This authority does not authorize live/on-chain financial actions.

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



## New execution-critical gaps — 2026-11-14

The full MASTER assignment remains the single top-level trigger. The strategy campaign is a child workstream and now adds two explicit assignments:
- SX-17 runtime multi-strategy fanout: docs/strategy-expansion/2026-11-14/tasks/SX17_MULTI_STRATEGY_RUNTIME_FANOUT_RU.md
- W6-12 observed participant strategy intelligence: docs/strategy-expansion/2026-11-14/tasks/W6_12_OBSERVED_PARTICIPANT_STRATEGY_INTELLIGENCE_RU.md

**Do not mistake strategy inventory for a running parallel strategy engine.** At the latest inspected source, src/strategy/strategies.py still had six registrations; only circular_arbitrage had a real two-leg shadow detector. LST remained stubbed, liquidation/orderbook remained disabled or fixture-only, and Pump remained boundary-only. SX-01 is a typed advisory contract, not a runtime registry. R08 reports 15/27 owner groups wired and 12 library-only. SX-17 must close the safe runtime fanout/composition gap by extending the existing application, StrategyRegistry, OpportunityConsumer, queue, AGG-05 and paper/shadow owners.

W6-12 adds public/authorized, pseudonymous on-chain participant episodes and evidence-backed strategy archetypes. It explicitly forbids real-world identity resolution, doxxing, private orderflow and automatic copy-trading. Reuse the existing MarketEpisode, raw journal, decision dataset and causal/replay owners.

Latest checked main at this docs update: c9ed36b6902502fc4dc51610f0094d27a50fd6fb (after #646, #647, #645 and #648). #645 SX-12 and #648 SX-08 are merged as offline/research models. #649 SX-03 remains open and source-blocked (missing Curve source commit SHA, whitepaper, unit-scale reconciliation and rooted per-market state). Re-fetch current main/PRs before dispatch.

The final completion target is not “all ideas enabled”. It is every strategy family assigned a truthful status and owner, every implemented detector reachable through the supported sender-free runtime only after its own gates, every shared resource allocated once, and every unresolved source/rights/capacity item recorded as BLOCKED/RESEARCH_ONLY/EXCLUDED. R04/R05/R06 and any later production authority remain separate gates.
