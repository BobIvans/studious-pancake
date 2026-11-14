> **Primary assignment update:** the full project trigger is now MASTER FLASHLOAN MARKET INTEGRATION + BUILD BIGGER UNIVERSE GRAPH. Read the canonical master assignment and archive reconciliation first; the original scope is preserved and expanded with GPR-01A…GPR-05, TON-RADAR-01, all 25 prior-chat strategy families, 33 direct venue families, 17 funding candidates, V3/V4/V5/V6 pair/graph deltas, DV-00…08 and F/F6 execution lanes. The previous EXP-01…10 + Wave-6 strategy campaign below is a supporting workstream, not a replacement for MASTER. SX-17 additionally closes the V3/V4/V6 detector/anomaly taxonomy reconciliation.

Canonical files:
- `docs/strategy-expansion/2026-11-14/MASTER_FLASHLOAN_MARKET_INTEGRATION_AND_BUILD_BIGGER_UNIVERSE_RU.md`
- `docs/strategy-expansion/2026-11-14/BUILD_BIGGER_UNIVERSE_GRAPH_ARCHIVE_RECONCILIATION_RU.md`
- `docs/strategy-expansion/2026-11-14/BUILD_BIGGER_UNIVERSE_GRAPH_WORKPACKAGES_V1.json`
- `docs/strategy-expansion/2026-11-14/BUILD_BIGGER_UNIVERSE_GRAPH_ARCHIVE_MANIFEST_V1.json`

# CODEX STRATEGY CAMPAIGN — полный запуск стратегии и параллельного R&D

Repository: BobIvans/studious-pancake

## Назначение

Превратить уже объединённые PR и знания в реальные, проверяемые shadow/paper implementations. Это не новая strategy registry и не ещё один план вместо кода. Источником истины являются текущий main, тесты, официальные source pins и действующие PR. Любой snapshot в документах исторический: перед каждым запуском обновляй main SHA, PR states, CI и ownership.

## Стартовый prompt для агента

Ты — lead engineering orchestrator всего Studious Pancake. Получи полный текущий контекст, выполни source/code/PR audit, затем организуй параллельное завершение всех независимых заданий из этого кампейна.

Читай в порядке:
1. AGENTS.md, root CODEX_START_HERE.md, master CODEX handoff, TASK_INDEX.md, MULTI_AGENT_EXECUTION_PLAN.md, PROJECT_KNOWLEDGE_BASE_MAP.md.
2. MASTER-00: docs/roadmap/STUDIOUS_PANCAKE_MASTER_CODEX_EXECUTION_2026-11-13/ (entrypoint, atlas, crosswalk, owner map, owner interface freeze).
3. R10: R10_STRATEGIES_AND_INTELLIGENCE.md, R10_STRATEGY_INVENTORY_2026-11-14.md и R10_STRATEGY_REPLAY_EXPERIMENTS_2026-11-14.md.
4. Strategy Expansion: README_RU.md, STRATEGY_GAP_ANALYSIS_RU.md, STRATEGY_CATALOG_AND_EXECUTION_CLASSES_RU.md, STRATEGY_EXPANSION_ASSIGNMENTS_RU.md, STRATEGY_ACCEPTANCE_MATRIX.json, SX00_RECONCILIATION_2026-11-14.md/json.
5. Новые документы этой кампании: STRATEGY_RESEARCH_CROSSWALK_AND_NEW_GAPS_RU.md, STRATEGY_RESEARCH_EXECUTION_ASSIGNMENTS_RU.md, STRATEGY_RESEARCH_ACCEPTANCE_MATRIX_V2.json.
6. SX-17 archive taxonomy: ARCHIVE_DETECTOR_TAXONOMY_COVERAGE_GATE_RU.md and ARCHIVE_DETECTOR_TAXONOMY_CROSSWALK_V1.json.

Сначала проверь все open/merged PR и их текущие head/base SHA. При snapshot d52e61f36ece249c1221c8e71d22aa29ef476e21 PR #641 (SX-01), #642 (SX-09) и #643 (SX-10/SX-11) уже merged; #645 (SX-12) был открыт и уже содержал portfolio optimizer по SX-01 ResourceManifest + AGG-05. Это только исторический срез — проверь статусы заново. Не создавай повторно SX-00, SX-01, SX-09, SX-10, SX-11 или SX-12, если их PR уже merged/open. #639 — historical receipt на старом SHA, а не текущий dashboard.

## Существующие owners — reuse, do not replace

- Strategy identity/contracts: SX-01 canonical typed contract (src/strategy/strategy_contract.py).
- Quotes, amount parity, pool correlation and builder handoff: R13-K (src/execution/quote_build_kernel.py).
- Sizing: PR118 non_monotonic_sizing.py. Новый quote на каждый точный amount; никакого scaling/extrapolation.
- Graph/cycles: UniversalArbitrageGraph, arbitrage_graph.py, multihop_solver.py.
- Shared resources: split_flow/cpmm_split_replay and AGG-05 conflict_scheduler. SX-12 is the sole portfolio optimizer extension.
- Market identity/state: AssetResolver, Dynamic Universe, MarketObservation, streams, GPR/QPR/DIN source governance.
- Relations: relation_generators and CorrelationLedger (#614), including seven evidence-gated residual families.
- Funding: FlashCapitalGraph and existing R02/R03 readers/builders. Build status is not capacity.
- LP lifecycle: merged #642 generic offline model; venue-specific fee/state/rights still require official pins.
- Backrun and asynchronous settlement: merged #643 offline models; synthetic replay is not live permission or calibrated profit.
- Procurement/data intelligence: INST-01, decision dataset/ranker, EVO-01…09 and existing causal/benchmark owners.

Do not create a second graph, solver, quote schema/kernel, asset/source registry, market-state DB, journal, feature store, capital graph, scheduler, paper ledger or release authority.

## Parallel workstreams

### A. Finish original SX pack
Refresh the current state and execute only the remaining packages:
- SX-02 flash-mint and lender selection: caller eligibility, callback/receiver, fees, cap, exact repayment and freshness; compare options in existing capital graph.
- SX-03 Curve LLAMMA: official contracts/math, band/oracle/collateral transitions, boundary replay; never approximate as CPMM.
- SX-04 OEV/oracle auctions: auction rights, keeper eligibility, update timeline and bid costs; oracle prices are signals, not quotes.
- SX-05 JIT/LVR/adverse selection: event-level fill-to-markout, fees, inventory and rights; no sandwich/front-running.
- SX-06 CLOB/RFQ/queue/rebate: exact sequence/depth/partial fills/cancel latency; quote does not imply fill.
- SX-07 prediction-market complete sets: outcome vectors, split/merge, resolution/dispute and conservation; non-atomic maturity remains non-atomic.
- SX-08 lending rate/refinance: utilization/APR curves, caps, health-factor transitions; separate atomic refinance from multi-period carry.
- SX-12 portfolio allocator: only if #645 is not already merged; consume SX-01 ResourceManifest and AGG-05, deterministic 1/2/4/8 workers, no double consumption.
- SX-13 causal evaluation/context bandit: nulls, controls, time holdouts, leakage, multiple-testing and negative/no-trade corpus.
- SX-14 verifiable compute/data procurement and offline mechanism lab; extend INST-01, no second marketplace/payment authority.
- SX-15 per-family observability/release evidence; consume existing receipts.
- SX-16 coordinator integration of IDs, contracts, capabilities, crosswalk and true statuses. One shared-file owner.

SX-00 is merged as #639, SX-01 as #641, SX-09 as #642, SX-10/SX-11 as #643 at the recorded snapshot. Re-check, don't redo.

### B. R10 implementation follow-through
1. CPMM exact evaluator → bounded-cycle paper path: bind existing ExactCpmmEdgeEvaluation/CircularGraphCandidateDetector, PR118 amount grid and native_cpmm_qualification. Offline first.
2. MarginFi offline FlashCapitalEdge evidence from pinned public captures through existing FlashCapitalGraph. Live capacity remains UNKNOWN until separately authorized/read-proven.
3. LST residual-fed shadow detectors: extend existing lst_depeg/lst_unstake shells using current residual/anchor owners. Only emit when exchange-rate and instant-exit proofs are present.
4. Continue R10-A…I, but preserve the current KEEP/EXTEND dispositions in SX-00; don't reassign or duplicate R10 lanes.

### C. Archive taxonomy completion — SX-17
Map all V3/V4/V6 anomaly, detector, route, hyperedge and lender IDs to the canonical owners. Use the new taxonomy gate and JSON crosswalk. Anomaly labels are not 1:1 trading strategies. Do not add duplicate runtime registrations or rebuild PAIR-00/P0 work.

### D. Recovered parallel-chat gaps: EXP-01…EXP-10
- EXP-01 Post-state dislocation after a confirmed large swap: correlate affected pools/state generation, compute residual, exact re-quote, measure first/last positive time and opportunity survival. Confirmed state only; no mempool sniping or victim targeting.
- EXP-02 Meteora DBC lifecycle/graduation to DAMM: official config/curve/fee/migration-threshold/keeper dossier; map pre/post pool identity, quote mint, liquidity and fee allocation; predicted threshold is not proof of migration.
- EXP-03 CLMM/DLMM tick/bin liquidity cliffs: bind Raydium/Meteora exact tick/bin state, consumed input, dynamic fee and partial fills into canonical exact evaluator. Existing P0-3 owns decoders; don't duplicate them.
- EXP-04 Token-2022 transfer economics: epoch-aware transfer fees, withheld amounts, fee caps/rounding, transfer-hook program and extra-account-meta closure. This is a route-feasibility/control-plane guard, not standalone alpha.
- EXP-05 Liquidation forecast/cascade: monitor-only public position trajectories, health/threshold distance, collateral/debt, exact unwind, real capacity and competition. No account creation, borrowing or sender.
- EXP-06 Protocol invariant/state-transition anomalies: one pinned protocol pilot, deterministic invariants first, explainable evidence, false-positive/negative and time-held-out replay. Anomaly scores only prioritize research.
- EXP-07 Opportunity survival/crowding/latency: empirical first-seen/first-exact-positive/last-positive/fill/revert/no-fill labels, censoring and calibration. Public/authorized aggregate observations only; no harmful MEV tactics.
- EXP-08 Intent/RFQ/CoW batch auctions: one official EVM protocol pilot; signed constraints, Coincidence-of-Wants, solver competition, partial fill, fairness/surplus and exact settlement. Never infer Solana atomicity.
- EXP-09 Derivatives/inventory basis: spot-perp, futures calendar, options parity/volatility, funding, hedge, margin/liquidation/expiry. HEDGED_NON_ATOMIC/SIGNAL_ONLY by default; flashloan is not duration financing.
- EXP-10 Uniswap v4 Hooks/dynamic fees/custom accounting: one deployed Hook/pool per dossier, bytecode/permission/source/license pin, callback order, hook/protocol/LP fee separation, custom accounting and exact simulation. Do not apply generic v3 math.

### E. Wave-6 Market Ecology: W6-00…W6-11
Preserve W6F-001…W6F-096 identities and their original 8-function ranges:
- W6-00 current-head/owner/synthetic-real boundary.
- W6-01 participant archetype IR with observable policies, rights, capital and latency.
- W6-02 calibration from public/authorized historical participant behavior.
- W6-03 deterministic multi-agent ecology environment wrapping existing state/mechanism owners.
- W6-04 own-impact and second-order market feedback.
- W6-05 benign competition and opportunity survival.
- W6-06 bounded PSRO/self-play best response, exploitability, regret and pathology.
- W6-07 mechanism-design and auction/fee/cap counterfactual sandbox.
- W6-08 co-adaptation and edge decay.
- W6-09 sim-to-real reality-gap benchmark on held-out regimes.
- W6-10 MCP/A2A research federation with local artifact verification and independent replay.
- W6-11 knowledge distillation/curriculum; raw observations remain canonical.
Reuse existing simulator, causal twin and benchmarks. AgentTorch/ABIDES/OpenSpiel/PSRO/PettingZoo/cadCAD are candidates for evaluation, not automatic dependencies. Synthetic trajectories must remain labelled synthetic; remote agent output is untrusted until locally replicated.

## Order and parallelism

- Coordinator first: refresh main, PR list, status and owner map; map every existing S/WG/OP/R10/SX ID and new EXP/W6 work.
- Then 4–8 independent workers in isolated worktrees (soft target, constrained by the coding harness). One work package, one owner, one PR. Parallelize docs/source dossiers/independent modules; serialize shared-owner changes.
- Run SX-02/03/04/05/06/07/08/13/14 and disjoint EXP/W6 models in parallel where ownership allows.
- SX-12 depends on SX-01 ResourceManifest + AGG-05. SX-15 consumes evidence. SX-16 integrates last.
- EXP-03 waits for the canonical exact-evaluator seam; EXP-05 waits for real rooted position/capacity evidence; EXP-08/09/10 require protocol-specific rights/settlement profiles.
- Continue independent offline tasks when one lane is BLOCKED.

## Per-PR acceptance
Every PR includes current base/head SHA and ancestry, changed paths, owner-overlap check, task IDs, official source URL/revision/hash/license/retrieval date, falsifiable hypothesis/null/control, execution/settlement class, exact identity/state/amount/quote/funding/cost/resource proof, positive/negative/stale/partial/rejected/no-trade fixtures, deterministic replay, tests/type/format/security output, evidence hashes, blockers and rollback. Record NOT_RUN/SKIPPED honestly. Unknown remains UNKNOWN, never zero. TVL, listings, program existence, API max and offline ABI are not live-capacity evidence.

## Autonomous merge scope

The repository owner explicitly grants the coding agent autonomous repository-engineering authority for this defined Studious Pancake strategy / Build Bigger Universe / flashloan campaign, including implementation, review, creation and merge of its in-scope PRs. The user's direct instruction in the ChatGPT conversation on 2026-11-14 requesting full agent authority to execute and merge is the explicit human approval required by AGENTS.md rule 11 for this campaign. This approval covers only PRs produced by these campaign assignments, not unrelated PRs or on-chain/financial actions.

The agent may merge an in-scope PR only after the latest required CI/branch-protection checks are green, relevant tests and source/license pins are reviewed, current-main ancestry is verified, the diff and owner-overlap audit is clean, all review threads are resolved, there are no conflicts, the PR is mergeable, and repository policy permits the merge. It must never bypass required checks, fake statuses, force-push main, merge a PR with a failing/in-progress/unknown gate, or merge when source provenance or ownership is uncertain. Rebase its own work to current main and continue independent packages when one lane is blocked. This is the explicit owner approval; no additional merge confirmation is required for a qualifying in-scope PR.

This authority grants no access to secrets/private keys and no authority for wallet/account creation, signing, broadcasting, transaction submission, borrowing, spending, deployment, provider activation, live trading, QPR/DIN override or production promotion. If a credential, paid license, operator input or live-read authorization is required, deliver an exact BLOCKED artifact and continue independent work.

## Hard safety boundaries
No private keys, wallet/account/ATA/obligation/position creation, signing, sending, borrowing, spending, deployments, provider activation, live trading or production promotion. No Robinhood Stock Tokens/tokenized equities. No sandwich, frontrun, user targeting or unauthorized private orderflow. Models, anomalies, correlations and ecological agents are advisory/research-only. Bridges, CEX settlement, TON async, maturity, unstaking queues and multi-period carry are not atomic flashloan legs unless a real single-transaction boundary is proven.

## Definition of complete
Not every PR title merged and not every idea given a class. Every family has one owner, truthful evidence tier, dependency, test/replay and next action. Selected implementations are merged or explicitly BLOCKED/RESEARCH_ONLY/EXCLUDED with evidence. Qualified paths are reachable in the supported shadow/paper architecture. Resource allocation is deterministic and cannot double spend. Dashboard/crosswalk match final main SHA. No claim of profitability or production readiness from documentation merges.



## G. Broad arbitrage strategy + data-source integration map

Before implementing another strategy, read:
- ARBITRAGE_MAP_STRATEGY_AND_DATA_SOURCE_ATLAS_RU.md
- ARBITRAGE_DATA_SOURCE_CATALOG_V1.json
- ARBITRAGE_MAP_DATA_SOURCE_ASSIGNMENTS_RU.md
- CODEX_ARBITRAGE_MAP_START_HERE.md

These extend the existing 25 strategy families, 33 direct venues, 17 flash-funding candidates, 19 route templates, 64/25/36/12/4 taxonomy structures and EXP/SX/W6 work. DS-00…DS-11 covers source pins, raw chain intake, identity, direct venue state, quote/build providers, CEX/perps, oracle/redemption, capital/liquidation, bridges, launch/migration, indexers/replay and full strategy wiring.

Do not expand only by adding tickers or router names. Every new strategy/source must map to canonical identity, exact state, exact amount quote, capital and builder where applicable, economic costs, execution class, evidence lineage, negative tests and replay. Keep the maximum research universe; execution eligibility is a separate subset. Data-source additions are to be wired through current P0/GPR/DV/R02/R03/R13 and existing graph/economics/paper owners, not a parallel system.
