# R10 — Strategy coverage inventory + ranked promotion shortlist (2026-11-14)

Task: `R10_STRATEGIES_AND_INTELLIGENCE.md` (this directory). Lane: **read-only audit + docs**;
no `src/` strategy owner was edited. Branch `agent/r10-strategies-audit`, base `e2b65c0c`
(current main at audit time; includes Stream H wave merges #614, #607 (P0-3), #619 (R02-CAP-D),
#620 (TON radar wave 1), #617, #618).

Status vocabulary is the repo vocabulary from `PROJECT_STATUS.json#status_vocabulary`
(`IN_MAIN_VERIFIED`, `IMPLEMENTED_UNQUALIFIED`, `IMPLEMENTED_UNBOUND`, `FIXTURE_ONLY`, `STUB`,
`PLANNED`, `LIVE_READ_PROVEN`, `RPC_EXACT`, `BUILT_OFFLINE_UNQUALIFIED`, `SIMULATION_PASS`,
`PAPER_QUALIFIED`, `BLOCKED`, `RETIRED`). "shadow-ready" below refers to the capability-matrix
value in `src/resources/capabilities.json`, not a promotion to execution.

---

## 1. Machine-readable inventory

### 1.1 Runtime strategy registry (`src/application.py#build_application`, `src/strategy/strategies.py`)

All six registrations are wired in the supported entrypoint (`flashloan-bot`) via
`src/application.py:200-210`; capability declarations live in `src/resources/capabilities.json`
(schema `pr023.capabilities.v1`). Live mode is hard-denied (`ArbitrageApplication.validate`,
`src/application.py:122-126`).

| Registry name | Class (owner) | Capability | Status | Evidence in main | Promotion blockers (typed) |
|---|---|---|---|---|---|
| `circular_arbitrage` | `CircularArbitrageStrategy` (`src/strategy/strategies.py:53`), detector `CircularArbitrageDetector` (`src/strategy/detectors.py`) | `shadow-ready`, allowed `disabled/shadow` | IN_MAIN_VERIFIED (shadow-only) | PR-056 runtime discovery produces provenance-rich SOL/USDC + selected LST snapshots; `tests/test_pr056_runtime_discovery.py` (5), `tests/test_pr033_snapshot_detectors.py` (4) | Detector is two-leg pair probing only (`DetectorPair`); no exact capacity binding in the runtime detect path (`src/strategy/exact_cpmm_capacity.py` is a separate owner); queue consumer is `ShadowOnlyOpportunityHandler`/`CapitalAwareShadowOpportunityHandler` (`src/strategy/consumer.py`) — shadow-not-executed outcomes only; no planner/simulator/sender wired into the runtime path |
| `lst_depeg` | `LSTDepegStrategy` (`src/strategy/strategies.py:41`) | `disabled` | STUB (`detector_not_implemented`; inherited `detect_once` returns `()`) | capability manifest: "Detector returns no opportunities and has no canonical execution pipeline" | `detector_not_implemented`; anchor feed exists only as research relation `LST_FAIR_VALUE` + residual `lst_premium_residual` (`src/research/correlation_ledger/residuals.py:158`), no detector consumes them |
| `lst_unstake` | `LSTUnstakeStrategy` (`src/strategy/strategies.py:47`) | `disabled` | STUB (same as `lst_depeg`) | same | `detector_not_implemented`; unstake/exchange-rate anchor proofs not consumed by any detector |
| `kamino_liquidation` | `KaminoLiquidationStrategy` (`src/strategy/strategies.py:90`) | `fixture-only`, `quarantined`, allowed `disabled` only | FIXTURE_ONLY | legacy execution quarantined; PR-020 shadow planner `src/liquidation/strategy.py#ShadowLiquidationStrategy` has no sender access; `tests/test_liquidation_shadow_simulation.py` (1) | `provider.kamino` fixture-only-blocked (`src/resources/capabilities.json`): rooted deployed account vectors, full reserve/fee/capacity proof, reviewed IDL/source identity, human review all missing (matches `CAP-R02` blocker set in `PROJECT_STATUS.json`) |
| `pump_fun_migration` | `PumpMigrationStrategy` (`src/strategy/strategies.py:100`) | `shadow-ready` (adapter boundary), but constructed `adapter_configured=False` | PLANNED (detector yields nothing by construction) | PR-048 Pump official IDL provenance pin + shadow-only adapter boundary `src/venues/pump`; `detect_once` intentionally returns `()` (PR-021 comment, `src/strategy/strategies.py:110-115`) | `PUMP_ADAPTER_NOT_CONFIGURED_SHADOW_ONLY`; discovery-only until token, program and pool are exact verified (R10 family #11 rule); graduation/backrun heuristics explicitly not adapted into opportunities |
| `orderbook_amm_arbitrage` | `OrderbookAmmStrategy` (`src/strategy/strategies.py:118`) | `fixture-only`, `quarantined` | FIXTURE_ONLY | `tests/test_orderbook_shadow_replay.py` (5) — fixture replay only | "canonical Phoenix Legacy/OpenBook V2 orderbook path is shadow-only; detector wiring awaits verified market subscriptions"; no verified live market subscription evidence |

### 1.2 Relation generator families (`src/strategy/relation_generators/generators.py`, tightened in #614)

`generate()` emits `ResearchRelation` rows with `atomicity_class="RESEARCH_ONLY"` by default;
market-derived relations always carry `correlation_group` + `underlying_resources` so shared
pools can never count as independent liquidity; identity gate excludes non-verified assets
(`generators.py:108-129`). Emitted kinds and status:

| Relation kind | Producer block | atomicity_class | Status | Evidence | Feeds from this wave |
|---|---|---|---|---|---|
| `DIRECT_MARKET` | fresh verified markets (`generators.py:189`) | RESEARCH_ONLY | IN_MAIN_VERIFIED (research signal) | `tests/test_dynamic_relations.py` (7), `tests/test_relation_h_generators.py` (13) | P0-3 exact decoders `src/providers/raydium_clmm_native.py`, `src/providers/meteora_dlmm_native.py` (#607) can upgrade underlying edges to exact-state observations; Raydium CPMM already exact via `src/strategy/exact_cpmm_capacity.py#QualifiedCpmmState` |
| `VENUE_FRAGMENTATION` | ≥2 venues, disjoint correlation groups/resources (`generators.py:197-213`) | RESEARCH_ONLY | IN_MAIN_VERIFIED (research signal) | same | P0-3 exact venue math (per-venue exact state) |
| `SYNTHETIC_CROSS` | hub with both legs identity-verified, `SYNTHETIC_LEGS_VERIFIED` (`generators.py:214-239`) | RESEARCH_ONLY | IN_MAIN_VERIFIED (research signal) | same | — |
| `DIRECT_SYNTHETIC_RESIDUAL` | direct market vs synthetic path (`generators.py:240-257`) | RESEARCH_ONLY | IN_MAIN_VERIFIED (research signal) | same | residual family `direct_synthetic_route_residual` (`residuals.py:319`) |
| `LST_FAIR_VALUE` / `NAV_BASIS` / `STABLE_RESIDUAL` / `WRAPPER_BASIS` / `ORACLE_MARKET` / `STRUCTURAL_PARITY` | anchor loop, requires `underlying_proven` + fresh anchor evidence (`generators.py:260-291`) | RESEARCH_ONLY | IN_MAIN_VERIFIED (research signal); anchors in production data are proof-limited | same + `tests/test_relation_h_residuals.py` (12) | residual families `lst_premium`, `nav_basis`, `stable_residual`, `wrapper_basis`, `oracle_residual` (#614) |
| `CROSS_CHAIN_BASIS` | parity across chains, `REPRESENTATION_DISTINCT` + `CROSS_CHAIN_RESEARCH_ONLY` (`generators.py:292-326`) | SIGNAL_REBALANCE_ONLY | IN_MAIN_VERIFIED (research/rebalance only, never execution) | same | F14 (`FIRST_CAMPAIGN_FAMILIES_V2_2.json`) |
| `FLASH_CAPITAL` | capital edges gated on `LENDER_QUALIFIED`, `LOCAL_ATOMIC_CANDIDATE`, evidence ≤30 s fresh, live capacity > 0 (`generators.py:327-348`) | LOCAL_ATOMIC_CANDIDATE | IMPLEMENTED_UNQUALIFIED — **zero qualified edges in main** (`CAP-R02: BLOCKED`, `PROJECT_STATUS.json`) | `tests/test_dynamic_flash_capital.py` (7) | R02-CAP-D MarginFi bank discovery/capacity reader `src/providers/marginfi/bank_discovery.py` (#619) — offline fail-closed decode of caller-supplied captures; live `get_program_accounts` enumeration typed blocked |

Keeper rule (R10 task §"Keep the four core relation generator owners"): DIRECT_MARKET,
VENUE_FRAGMENTATION, DIRECT_VS_SYNTHETIC (as `SYNTHETIC_CROSS` + `DIRECT_SYNTHETIC_RESIDUAL`)
and BOUNDED_CYCLE (via `bounded_exact_cycles` → `CircularGraphCandidateDetector`) are retained;
no second solver was invented (`generators.py:352-365`).

### 1.3 Bounded cycles and exact economics

| Owner | Scope | Status | Evidence | Promotion blockers (typed) |
|---|---|---|---|---|
| `CircularGraphCandidateDetector` + `CircularShadowRoute` (`src/strategy/arbitrage_graph.py:121,234`) | exact 3/4-hop shadow cycles over `UniversalArbitrageGraph`, guaranteed-output coupled at every hop; "shadow evidence, not executable Opportunities" | IMPLEMENTED_UNQUALIFIED (paper-candidate producer) | `tests/test_shadow_arbitrage_graph.py` (45) | paper contract requires qualified route candidates (R04) + current 24 h paper PASS (none; `PAPER-R06`) |
| `search_bounded_cycles` (`src/strategy/multihop_solver.py:153`) | 2..5-hop shortlist via marginal graph; "a route is not an executable or profitable candidate until a caller-supplied exact evaluator has bound amount, state generation and full resource costs" | IMPLEMENTED_UNQUALIFIED (topology shortlist) | `tests/test_agg05_multihop_solver.py` (8) | shortlists never equal exact route/economic proof; 5-hop does not acquire a new exact paper contract |
| `shortlist_verified_cycles` + `edge_cycle_proof` (`src/strategy/relation_generators/generators.py:368-461`) | 3..5-hop projection with per-edge `RPC_EXACT` QPR receipt, ≤5 s freshness, positive guaranteed output; typed exclusions (`receipt_unreplayable`, `edge_state_not_exact_verified`, `edge_quote_not_current`, `missing_exact_edge_receipt`) | IMPLEMENTED_UNQUALIFIED | `tests/test_relation_h_generators.py` | requires complete canonical graph + QPR readiness + exact receipts for every edge — none current in main |
| `src/strategy/exact_cpmm_capacity.py` | exact Raydium CPMM edge evaluation (`QualifiedCpmmState`, `CpmmEvaluationRejection`) | IN_MAIN_VERIFIED (CPMM only) | `tests/test_exact_cpmm_capacity.py` (24), `tests/test_cpmm_split_replay.py` (3), `tests/test_cpmm_fee_accounting.py` (5) | CLMM/DLMM exact math landed (#607) but is **not yet bound** into a graph evaluator; only CPMM pools covered |
| `src/economics/non_monotonic_sizing.py#build_pr118_amount_grid` | PR118 amount grids / non-monotonic sizing | IN_MAIN_VERIFIED | AGG-05 tests | remains the sizing owner; no learned output may replace it |

### 1.4 GPR-01 research universe (`src/research_economic_graph/`, `docs/roadmap/gpr-parallel-radar-rnd-2026-10-06/`)

| Item | Status | Evidence |
|---|---|---|
| `AssetRegistry` V2.2 (`src/research_economic_graph/registry.py:57`) | IMPLEMENTED_UNQUALIFIED — research-only by hard bound | 92 research identities (solana 51 / sui 33 / ton 8), **every asset `runtime_enabled=false`, `exact_graph_allowed=false`**; registry refuses transport-mechanism fake identities (CCTP/Wormhole/USDT0, `registry.py:83-89`) |
| First-campaign families F01–F14 (`FIRST_CAMPAIGN_FAMILIES_V2_2.json`) | IDENTIFIER_VERIFIED, research seeds | classes: STABLE_PEG×2 (F01,F02), WRAPPER_PARITY×2 (F04,F11), LST_RELATIVE_VALUE×2 (F06,F12), REPRESENTATION_BASIS×2 (F07,F08), STABLE_SYNTHETIC×2 (F09,F10), DIRECT_VS_SYNTHETIC×1 (F03), NAV_MARKET_BASIS×1 (F05), ORACLE_MARKET_BASIS×1 (F13), CROSS_CHAIN_NATIVE_BASIS×1 (F14); execution classes LOCAL_ATOMIC×3, LOCAL_SIGNAL×10, CROSS_CHAIN_SIGNAL×1; heat HOT×6/WARM×7/COLD×1 |
| DeepBook pool refs (`SUI_DEEPBOOK_POOLS_V2_1.json`, 9 pools) | IDENTIFIER_VERIFIED, research-only (`DeepBookPoolReference.__post_init__` refuses runtime/exact flags) | `tests/test_gpr01_research_economic_graph.py` (89) |
| Transport transformations V2.2 (4 non-token) | IMPLEMENTED_UNQUALIFIED — USDT0/CCTP/Wormhole stay non-atomic research/rebalance | `tests/test_gpr01_v22_delta.py` (7) |
| Verification queue (`src/research_economic_graph/queue.py#CandidateScore`) | IN_MAIN_VERIFIED as scheduling unit ("scores are scheduling units, not PnL") | GPR-01 suite |
| GPR-02 Solana parallel radar | fixture-replay + bounded discovery diagnostics | `tests/test_gpr02_solana_parallel_radar.py` (112); live Jupiter/RPC/STON requests denied by proxy in the recorded diagnostic (exit 2/BLOCKED) |
| GPR-03 Sui shadow + Parquet ledger | shadow fixtures | `tests/test_gpr03_sui_shadow.py` (86) |

### 1.5 Correlation ledger + residual families (#614)

| Owner | Content | Status | Evidence |
|---|---|---|---|
| `src/research/correlation_ledger/ledger.py` | immutable partitioned Parquet residual observations; 12 `FEATURES`; `CHAIN_ALIGNED`/`UNALIGNED` provenance per row; lead/lag windows 0.1/0.5/1/5/30/300 s only over CHAIN_ALIGNED samples; findings stay `DISCOVERY_ONLY` | IN_MAIN_VERIFIED | `tests/test_dynamic_correlation_ledger.py` (4) |
| `src/research/correlation_ledger/residuals.py` | 7 typed residual families: `stable_redemption_residual`, `lst_premium_residual`, `wrapper_basis_residual`, `nav_basis_residual`, `vwap_execution_residual`, `direct_synthetic_route_residual`, `oracle_market_residual`; 9 typed exclusion reasons; excluded samples carry `value=None` (never zero) | IN_MAIN_VERIFIED | `tests/test_relation_h_residuals.py` (12) |

### 1.6 Capital, paper verticals, scheduling, intelligence

| Owner | Status | Evidence / blockers |
|---|---|---|
| `src/economics/flash_capital_graph/graph.py` (`FlashCapitalEdge`) | IMPLEMENTED_UNQUALIFIED; `CAP-R02: BLOCKED` — zero qualified edges, 27 providers disabled | MarginFi reader (#619) is the closest qualification feed; Jupiter/Kamino/NAVI capacity proofs missing |
| `src/paper_shadow/atomic_vertical.py` (PR-058) | IMPLEMENTED_UNQUALIFIED — MarginFi+Jupiter plan → canonical v0 exact simulation → economic reconciliation, sender-free | SIM-R05 blockers: live/current RPC, lender reader, route build conformance |
| `src/paper_shadow/canonical_paper_vertical.py` (MEGA-PR A startup contract) | IN_MAIN_VERIFIED contract; required surfaces `atomic_stage_suite`, `exact_fee_workflow`, `verified_marginfi_provider`, `jupiter_v2_build` | startup stays `blocked_*` until those surfaces are verified |
| `src/paper_shadow/native_cpmm_qualification.py` | IN_MAIN_VERIFIED (CPMM paper qualification path) | `tests/test_native_cpmm_qualification.py` (34) |
| `src/strategy/conflict_scheduler.py` (AGG-05) | IN_MAIN_VERIFIED — reservation-authority-gated scheduling, typed `SchedulerRejectReason` | `tests/test_agg05_conflict_scheduler.py` (13) |
| `src/strategy/admission.py` (PR-005 evidence gate), `src/strategy/queue.py`, `src/strategy/tracker.py` | IN_MAIN_VERIFIED | `tests/test_live_admission.py` (2), `tests/test_pr147_policy_admission.py` (8), `tests/test_pr153_policy_admission.py` (9), `tests/test_pr099_evidence_bound_external_admission.py` (3) |
| `src/decision/` (PR-022 dataset, `PurgedGroupedTimeSplit` with embargo, `ModelStatus.BASELINE_ONLY→SHADOW_CHALLENGER`), `src/strategy/ranker.py#DecisionIntelligenceRanker` | IMPLEMENTED_UNQUALIFIED — advisory-only ranker with deterministic baseline fallback | model scores can never skip identity/quote/capacity/simulation/paper gates (`ranker.py` multiplies baseline priority; `shadow_only=True` default) |
| `src/strategy_evolution/residual_discovery.py` (EVO-09), `src/decision/agg10.py#lead_lag_research` | IMPLEMENTED_UNQUALIFIED replay research | explicit `FEATURE_LEAKAGE` / `SOURCE_UNLICENSED` guards; Spearman lead/lag vs deterministic baseline |
| TON radar (`src/discovery/dynamic_universe/ton_radar.py`: `Ston/Dedust/SwapCoffeeRadarIngestor`) | IMPLEMENTED_UNQUALIFIED — `TON_ASYNC_MULTI_CONTRACT`, `verification_state="DISCOVERY_ONLY"`; wave-1 source pins #620 | `LIVE_CAPTURE_NOT_AUTHORIZED` (no live capture this wave); no route/quote promotion; failed pages never retire markets |

### 1.7 R10 family coverage map (task brief families 1–13)

| Brief family | Covered by | Current status |
|---|---|---|
| 1. Direct two-leg market arbitrage | `DIRECT_MARKET` relations + `circular_arbitrage` detector + CPMM exact evaluator | research signal IN_MAIN_VERIFIED; detector shadow-ready; exact math CPMM-only |
| 2. Venue fragmentation / route overlap | `VENUE_FRAGMENTATION` | research signal IN_MAIN_VERIFIED |
| 3. Direct vs synthetic/wrapped paths | `SYNTHETIC_CROSS` + `DIRECT_SYNTHETIC_RESIDUAL` + F03/F09/F10 | research signal IN_MAIN_VERIFIED |
| 4. Bounded circular cycles 2–5 hops, exact re-quote | `CircularShadowRoute` (3/4), `search_bounded_cycles` (2–5), `shortlist_verified_cycles` (3–5, per-edge proofs) | IMPLEMENTED_UNQUALIFIED; exact re-quote exists only for CPMM |
| 5. Stablecoin triangles / peg deviation | F01/F02 + `STABLE_RESIDUAL` anchor + `stable_redemption_residual` | research-only; redemption anchor proofs fixture-level in production data |
| 6. LST/staking derivatives | F06/F12 + `LST_FAIR_VALUE` + `lst_premium_residual`; registry `lst_depeg`/`lst_unstake` | detectors STUB; residual/anchor owners IN_MAIN_VERIFIED |
| 7. BTC wrapper/bridged basis | F04/F11 + `WRAPPER_BASIS` + `wrapper_basis_residual` | research-only |
| 8. Liquidation / health-factor | `kamino_liquidation` + `src/liquidation/` (planner/sizer/simulation) | FIXTURE_ONLY/quarantined; protocol risk-state proof missing |
| 9. Funding/carry/basis, event-driven | GPR heat `Lifecycle.EVENT`, JLP NAV basis F05 | research-only; no funding-rate source owner qualified |
| 10. CEX lead/lag, orderbook imbalance, oracle divergence | `orderbook_amm_arbitrage` + `vwap_execution_residual` + `oracle_market_residual` + AGG-10 lead/lag | FIXTURE_ONLY (orderbook) + research residuals |
| 11. Memecoin/migration discovery | `pump_fun_migration` (PR-048/PR-021 boundary) | PLANNED/disabled; discovery-only until exact token/program/pool proof |
| 12. Cross-chain/bridge basis | F14 + `CROSS_CHAIN_BASIS` (`SIGNAL_REBALANCE_ONLY`) + transformations V2.2 | research/rebalance only, never local atomic route |
| 13. RWA/xStocks/gold representations | F13 (XAUM) + `ORACLE_MARKET_BASIS`; `representation_kind="rwa"` in `REPRESENTATION_KINDS` | research-only, COLD heat; separate legal/access evidence class required |

---

## 2. What correlation/residual signals may and may NOT do (binding statement)

Residual/correlation output (all 7 families in `src/research/correlation_ledger/residuals.py`,
the 12 features in `ledger.py`, `CandidateScore` in `src/research_economic_graph/queue.py`,
`heat()` in `src/strategy/relation_generators/heat.py`, AGG-10 lead/lag, EVO-09, and any
`ModelStatus.SHADOW_CHALLENGER` score) **may**:

1. Order, prioritize and schedule verification/replay work (`CandidateScore` explicitly:
   "scores are scheduling units, not PnL").
2. Choose which relations/pools/assets receive scarce exact-verification quota (heat/queue).
3. Provide advisory ranking input (`DecisionIntelligenceRanker` baseline-priority adjustment)
   and replayable training features (`src/decision/dataset.py`, purged grouped time split with
   embargo, no look-ahead).

They **may NOT** (owners enforce; tests pin):

1. Alter `execution_class`, `evidence_state`, `heat` classification or any promotion boundary
   (`ledger.py` header: "Findings remain DISCOVERY_ONLY"; `generators.py` header: "never alter
   execution_class, evidence_state, heat or any promotion boundary").
2. Prove causation — correlation over residuals is a scheduling signal only, never proof of
   causation or execution (Stream H mandate line; `residuals.py` module docstring).
3. Substitute for identity, quote, capacity, exact simulation or paper gates — no learned or
   correlated output can skip them (`residuals.py`: excluded samples carry `value=None`, never
   zero; unknown is never treated as a proof).
4. Serve as execution or profit evidence: lead/lag windows (100 ms/500 ms/1 s/5 s/30 s/5 m) are
   computed only over `CHAIN_ALIGNED` samples; unaligned samples are excluded with a typed
   reason and can never support an execution claim.
5. Cross-chain basis signals are `SIGNAL_REBALANCE_ONLY` and must never be labeled a local
   atomic flashloan route.

---

## 3. Ranked promotion shortlist

Ranking = evidence completeness × economic value × owner readiness (0–5 each; scores are
auditor judgment anchored to the evidence column of §1). **Promotion here means "next evidence
tier" (stub → implemented shadow detector; fixture → wired shadow; shortlist → exact paper
candidate). No item promotes past shadow/paper, and live gates stay BLOCKED by repo law
(`capabilities.json` runtime_modes.live.available=false; AGENTS.md rule 8).**

| Rank | Opportunity | Evidence (0–5) | Value (0–5) | Readiness (0–5) | Typed blocker to the *next* tier |
|---|---|---|---|---|---|
| 1 | **Bind CPMM exact evaluator into the bounded-cycle paper path** (`exact_cpmm_capacity` × `CircularGraphCandidateDetector` × `native_cpmm_qualification`) | 5 — all three owners merged and tested (24+45+34 tests), PR-056 supplies provenance-rich snapshots | 5 — the only family with a complete exact-math → shadow-cycle → paper-qualification chain | 5 — no new owner needed, only an integration binding | `route_candidates_not_qualified` (R04) then `no_current_24h_paper_pass` (R06) |
| 2 | **MarginFi bank capacity → first `LENDER_QUALIFIED` `FlashCapitalEdge`** | 4 — R02-CAP-D reader decodes caller-supplied captures fail-closed (#619); `FLASH_CAPITAL` emitter + `LENDER_QUALIFIED` flag tested | 5 — financing is the graph dimension that unlocks LOCAL_ATOMIC economics for the whole universe (AGENTS.md rule 5) | 4 — emitter ready; needs capture-qualified capacity replay and, for live freshness (≤30 s), a separately gated live read | `live_capacity_read_not_authorized` (offline replay can pre-qualify the decode path only) |
| 3 | **`lst_unstake`/`lst_depeg` stubs → residual-fed shadow detectors** | 4 — `LST_FAIR_VALUE` relations + `lst_premium_residual` + registry universe (23 LST representations) all in main and tested | 4 — F06/F12 are 2 of 14 families, WARM, cross-venue LST relative value | 4 — detector shell + context exist; needs detector body consuming residual series + exchange-rate anchor proofs | `lst_exchange_rate_unproven` / `instant_exit_unproven` on production samples (typed exclusion reasons already implemented) |
| 4 | **Stable peg F01/F02 (HOT, LOCAL_ATOMIC) → exact stable triangle detector** | 3 — `stable_redemption_residual` implemented; USDG/USD1/USDC/USDT identities verified; venues unqualified | 5 — deepest-liquidity family, LOCAL_ATOMIC execution class | 3 — anchor proof (issuer redemption evidence) absent in main | `redemption_anchor_unproven`; venue edges need exact state |
| 5 | **Orderbook AMM → shadow wiring via verified subscriptions** | 3 — fixture replay tests (5), `vwap_execution_residual` implemented, PR-056-style ingest pattern exists (`ShadowMarketGraphIngest`) | 4 — AMM-vs-CLOB VWAP residual is a flagship Stream-H family | 3 — Phoenix/OpenBook market subscriptions unverified (capability manifest reason) | `market_subscriptions_unverified`; fixture orderbooks stay blocked (`market_graph_ingest.py` fails closed) |
| 6 | **`pump_fun_migration` detector wiring (discovery-only)** | 4 — PR-048 IDL pin + shadow adapter boundary already `shadow-ready` in the manifest | 3 — migration/liquidity events are discovery-only until exact pool proof | 3 — needs `adapter_configured=True` feed + verified migration pool identity | `PUMP_ADAPTER_NOT_CONFIGURED_SHADOW_ONLY`; exact token/program/pool proof required before any candidacy |
| 7 | **NAV basis F05 (JLP) anchor proof** | 2 — `nav_basis_residual` implemented; JLP identity verified | 4 — HOT family, unique LP-NAV exposure | 2 — no protocol NAV-per-share source owner qualified | `nav_per_share_unproven` |
| 8 | **RWA F13 (XAUM) oracle-market basis** | 2 — `oracle_market_residual` implemented; identity verified | 2 — COLD, separate legal/access evidence class | 2 — no oracle reference feed | `oracle_slot_misaligned` / legal-access class separation |
| 9 | **Cross-chain basis F14** | 4 — relations + transformations implemented | 3 — rebalance research value only | 5 — permanently research-only by design | none to research tier; **never promotes to execution** (`SIGNAL_REBALANCE_ONLY`) |

Items 1–3 are the actionable wave candidates; 4–6 need one new proof each; 7–9 are
keep-warm research with no promotion path this cycle.

---

## 4. Per-item next tasks (exact owner files)

1. **CPMM cycle→paper binding** — integrate the exact CPMM evaluators
   (`src/strategy/exact_cpmm_capacity.py`: `ExactCpmmEdgeEvaluation.evaluate`,
   `evaluate_exact_cpmm_route`, `enumerate_exact_cpmm_routes`) as the caller-supplied exact
   evaluator behind `CircularGraphCandidateDetector` candidates
   (`src/strategy/arbitrage_graph.py`), reusing `build_pr118_amount_grid`
   (`src/economics/non_monotonic_sizing.py`) for amount grids and
   `src/paper_shadow/native_cpmm_qualification.py` for the paper contract. Offline tests only;
   no sender. Next PR belongs to R04/R06 lanes; R10 supplies this inventory.
2. **MarginFi edge qualification (offline)** — extend
   `src/providers/marginfi/bank_discovery.py` consumers to produce replayed
   `FlashCapitalEdge` qualification evidence from pinned captures
   (`src/resources/marginfi_pr028.json`, PR-055 main-group pin) through
   `src/economics/flash_capital_graph/graph.py`; live `get_program_accounts` stays typed
   blocked. R02-CAP lane.
3. **LST shadow detectors** — implement detector bodies in
   `src/strategy/strategies.py` (`LSTDepegStrategy`, `LSTUnstakeStrategy`) that consume
   `lst_premium_residual` samples + `LST_FAIR_VALUE` relations via `StrategyContext`
   (`src/strategy/interfaces.py`), emitting `Opportunity` rows with provenance only when
   anchor proofs are present (no `value=None` substitution). Update
   `src/resources/capabilities.json` capability contract in the same PR.
4. **Stable triangle** — needs issuer redemption-anchor evidence class before any detector;
   file under GPR/UNIVERSE lanes, not R10.
5. **Orderbook subscriptions** — R07/provider lane: verified Phoenix Legacy/OpenBook V2
   subscriptions pinned; then wire `OrderbookAmmStrategy.detect_once` against
   `ShadowMarketGraphIngest` (`src/strategy/market_graph_ingest.py`).
6. **Pump migration feed** — configure the verified adapter boundary (`src/venues/pump`) and
   gate `PumpMigrationStrategy(adapter_configured=True)` behind exact migration-pool identity;
   discovery-only emissions.
7. **NAV/oracle anchors** — new source-dossier work (R07): protocol NAV per-share and XAUM
   oracle reference pins feeding `StructuralAnchor.underlying_proven`.

---

## 5. Offline test baseline (run natively 2026-11-14, worktree base `e2b65c0c`)

Interpreter: shared venv `studious-pancake/.venv/Scripts/python.exe`, cwd = worktree;
pytest 3 batches, `602 passed / 0 failed / 0 skipped` total.

Batch 1 — strategy core (148 passed, 29.78 s):

| File | Tests |
|---|---|
| `tests/test_shadow_arbitrage_graph.py` | 45 |
| `tests/test_exact_cpmm_capacity.py` | 24 |
| `tests/test_agg05_conflict_scheduler.py` | 13 |
| `tests/test_relation_h_generators.py` | 13 |
| `tests/test_relation_h_residuals.py` | 12 |
| `tests/test_pr122_opportunity_identity.py` | 8 |
| `tests/test_agg05_multihop_solver.py` | 8 |
| `tests/test_dynamic_relations.py` | 7 |
| `tests/test_pr033_snapshot_detectors.py` | 4 |
| `tests/test_dynamic_correlation_ledger.py` | 4 |
| `tests/test_cpmm_fee_accounting.py` | 5 |
| `tests/test_cpmm_split_replay.py` | 3 |
| `tests/test_shadow_workers.py` | 2 |

Batch 2 — research graph/universe/GPR (372 passed, 266.28 s): `tests/test_gpr02_solana_parallel_radar.py`
(112), `tests/test_gpr01_research_economic_graph.py` (89), `tests/test_gpr03_sui_shadow.py` (86),
`tests/test_dynamic_asset_resolution.py` (15), `tests/test_dynamic_promotion_campaign.py` (14),
`tests/strategy_evolution/test_pr353_strategy_evolution.py` (12),
`tests/strategy_evolution/test_pr353_semantic_conformance.py` (9),
`tests/strategies/stable_peg/test_mpr2622_stable_peg.py` (9),
`tests/test_gpr01_v22_delta.py` (7), `tests/test_dynamic_universe.py` (7),
`tests/test_dynamic_flash_capital.py` (7), `tests/test_din01_bounded_discovery.py` (4),
`tests/strategies/stable_peg/test_mpr2622_architecture.py` (1).

Batch 3 — shadow-ready path/admission/paper (82 passed, 26.95 s):
`tests/test_native_cpmm_qualification.py` (34), `tests/test_runtime_vertical_slice_pr007.py` (11),
`tests/test_pr153_policy_admission.py` (9), `tests/test_pr147_policy_admission.py` (8),
`tests/test_orderbook_shadow_replay.py` (5), `tests/test_pr056_runtime_discovery.py` (5),
`tests/test_live_admission.py` (2), `tests/test_pr099_evidence_bound_external_admission.py` (3),
`tests/test_pr113_amount_coupled_discovery.py` (3), `tests/test_liquidation_shadow_simulation.py` (1),
`tests/test_shadow_calculation_market.py` (1).

All batches are offline (mocked transports; the httpx log lines in batch 2/3 are mock-transport
replays of pinned fixtures). Black/mypy intentionally not run (docs-only lane).

---

## 6. Safety flags, blockers, next task

- **Safety:** docs-only PR; zero `src/` changes; no live gates assumed or requested — live stays
  hard-denied (`capabilities.json` `runtime_modes.live.available=false`; registry assets all
  `runtime_enabled=false`/`exact_graph_allowed=false`; TON `LIVE_CAPTURE_NOT_AUTHORIZED`;
  MarginFi live enumeration typed blocked). Nothing in this inventory promotes a strategy class
  to shadow-ready/live by itself (R10 acceptance rule).
- **Blockers observed (typed):** `detector_not_implemented` (lst_depeg/lst_unstake),
  `PUMP_ADAPTER_NOT_CONFIGURED_SHADOW_ONLY`, fixture-only providers (kamino, orderbook),
  `zero_qualified_capital_edges` (CAP-R02), `no_current_24h_paper_pass` (PAPER-R06),
  `route_candidates_not_qualified` (ROUTE-R04), CLMM/DLMM evaluator binding absent (P0-3 math
  landed, not yet an exact evaluator behind the graph), anchor proofs unproven in production
  data (`redemption_anchor_unproven`, `nav_per_share_unproven`, `lst_exchange_rate_unproven`,
  `underlying_reference_unproven`).
- **Next task for the follow-up wave:** item 1 of §4 — the CPMM bounded-cycle exact-evaluator
  binding PR (offline), with item 2 (MarginFi offline edge-qualification replay) as the parallel
  candidate; both must keep model/correlation outputs advisory per §2.
