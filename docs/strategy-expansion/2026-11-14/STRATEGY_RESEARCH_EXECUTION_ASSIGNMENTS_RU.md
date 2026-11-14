> **Master dependency:** execute the complete original MASTER/GPR/DV/F/F6 programme in `MASTER_FLASHLOAN_MARKET_INTEGRATION_AND_BUILD_BIGGER_UNIVERSE_RU.md` before considering this matrix a complete project plan. SX/EXP/W6 assignments add strategy economics and research/portfolio layers; they do not replace asset/market/source discovery or direct venue/flash-source work.

# Strategy campaign assignments — launch matrix

Полные технические требования, acceptance, dependencies and safety rules are in CODEX_STRATEGY_CAMPAIGN_START_HERE.md and STRATEGY_RESEARCH_CROSSWALK_AND_NEW_GAPS_RU.md. This file is the dispatch matrix, not a second source of truth.

## COORD-00 — coordinator
Refresh current main, PRs, CI, branch protection and exact owners. Reconcile S01–S07, OP/WG, R10, SX, EXP and W6 IDs. Refresh crosswalk and dashboard through the single canonical owner. Never trust snapshot SHA.

## SX — merged vs remaining
- SX-00 #639, SX-01 #641, SX-09 #642, SX-10/SX-11 #643: merged at the checked snapshot; don't repeat.
- SX-12 #645 remains an open lane in the latest checked state; it consumes SX-01 ResourceManifest and AGG-05. Review its current head/checks; do not duplicate it.
- SX-03 #649 and SX-08 #648 are open implementation lanes; review their exact current heads/source pins before dispatching follow-up work.
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



## DS-00…DS-11 — broad arbitrage data-source integration workstream

Canonical assignments and acceptance are in ARBITRAGE_MAP_DATA_SOURCE_ASSIGNMENTS_RU.md; strategy/source semantics are in ARBITRAGE_MAP_STRATEGY_AND_DATA_SOURCE_ATLAS_RU.md; the machine source ledger is ARBITRAGE_DATA_SOURCE_CATALOG_V1.json.

- DS-00 source pins, license, quotas and current entitlement audit.
- DS-01 Solana/Sui/EVM/TON/Cosmos raw chain intake, finality, slots/checkpoints and replay.
- DS-02 canonical asset, pool, book, token representation and claim identity.
- DS-03 33 direct venue families and exact invariant/state/quote math.
- DS-04 Jupiter V2/0x/Titan plus future Solana/Sui/EVM quote/build sources; preserve losing quotes and dedupe underlying liquidity.
- DS-05 public CEX/perps books/trades/funding/OI/mark/index; reference or inventory strategies.
- DS-06 oracle, stablecoin issuer, PSM, LST/LRT, vault and redemption state.
- DS-07 R02/R03 flash capital, liquidation/keeper rights, capacity/fees and builders.
- DS-08 bridges/message/attestation/finality; signal or inventory only.
- DS-09 launch/migration/new pool and long-tail event radar.
- DS-10 The Graph/Substreams, Dune/DefiLlama/CoinGecko/GeckoTerminal, protocol history and market-ecology replay.
- DS-11 strategy→source→identity→state→quote→capital→builder→simulation→paper/replay coverage and installed-runtime reachability.

This is a data integration overlay on existing P0/GPR/DV/R02/R03/R13/R10/SX/EXP/W6 owners, not a new source registry or runtime.
