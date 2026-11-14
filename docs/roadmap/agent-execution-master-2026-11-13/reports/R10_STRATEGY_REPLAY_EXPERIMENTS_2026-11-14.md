# R10 — Strategy family inventory + bounded offline replay experiments (2026-11-14)

Lane: **read-only audit + offline experiments**. Branch `agent/r10-strategies-audit`,
audit base `e2b65c0ceefdc6f9f99cdc0187ff23dc7815acc8` (current main at audit time;
includes #614 relation/residual tightening, #607 P0-3 native decoders, #619 R02-CAP-D
MarginFi reader, #620 TON radar wave 1); rebased onto current main `eb6cb247` before
PR. Zero `src/` changes; new files are this report,
`tests/test_r10_strategy_inventory_replay.py` and `scripts/r10_offline_replay.py`.

## 0. Reconciliation with the parallel R10 lane (PR #622, merged)

While this lane worked, a parallel R10 lane landed the docs-only inventory
`docs/roadmap/agent-execution-master-2026-11-13/tasks/R10_STRATEGY_INVENTORY_2026-11-14.md`
(PR #622, merged as `d04bc9f8`). The two deliverables are complementary, with no
file-path collision:

- **Where this report agrees with the merged inventory** — its §1 registry table
  (6 strategies and capability values), §1.2 relation-kind table (12 kinds, gates,
  statuses), §1.3 bounded-cycle/exact-economics owners, §1.4 GPR-01 universe, §1.5
  correlation ledger + 7 residual families / 9 typed exclusion reasons / 12 features,
  §1.6 capital/paper/scheduling/intelligence owners, §1.7 brief-family coverage map
  and §2 binding statement were each re-verified against owner source in this
  worktree during the audit; **no factual disagreement was found**. Cited from it
  without independent recount: the 92-identity GPR registry split (solana 51 / sui 33
  / ton 8) and the F01–F14 class/heat tallies.
- **What this report adds that the inventory does not contain**:
  1. Bounded, deterministic **offline replay experiments with exact recorded
     outputs** (§4) — residual fail-closed gates (unknown is never zero), lead/lag
     `CHAIN_ALIGNED` gating with typed `timestamp_alignment_unproven` exclusion and
     alias-confidence collapse, multihop shortlist-not-profitable binding
     (`NON_POSITIVE_NET` on a marginally profitable route), relation-discovery counts
     on a fixture universe, identity/`FLASH_CAPITAL` fail-closed gates — as an
     additive test file (8 tests) and a standalone JSON receipt runner.
  2. Per-family **discovery inputs / sizing path / simulation requirements /
     typed promotion-evidence alphabet** columns (§2), which the inventory's tables
     do not carry.
  3. **Cross-chain applicability classes** per family (Solana exact-local vs Sui PTB
     vs TON async vs EVM research-only; §2).
  4. Blockers **split into user-gated (R02 capacity) vs evidence-gated (quote/build/
     sim/paper) classes** for the coordinator dashboard (§5).
  5. PR #599 atlas cross-check (§6) and exact test counts (§4.5).
- The inventory's ranked 9-item promotion shortlist (§3 there) is consistent with §7
  here; its top-3 (CPMM cycle→paper binding, MarginFi offline edge qualification,
  LST stub→residual-fed shadow detectors) are unchanged by this report's findings —
  the experiments mechanically confirm why item 1's binding is the prerequisite
  (marginal shortlists alone cannot establish profit).

Method: every claim below was verified by reading the owner source in this worktree and
by running the offline replay experiment (§4). Task file:
`../tasks/R10_STRATEGIES_AND_INTELLIGENCE.md`. PR #599's `STRATEGY_UNIVERSE_ATLAS.md`
was fetched read-only from the PR branch (`docs/master-strategy-atlas-2026-11-13`) and
cross-checked per family in §6; it was **not** merged or copied.

State vocabulary: `SHADOW_READY` (capability-matrix value; shadow detection wired, not
execution), `DISABLED`, `FIXTURE_ONLY`, `STUB`, `PLANNED`, `RESEARCH_ONLY_VERIFIED`
(relation/residual owner in main and tested, produces advisory research signals only).
Nothing here is a promotion: live stays hard-denied (`capabilities.json`
`runtime_modes.live.available=false`; AGENTS.md rule 8).

---

## 1. Runtime strategy registry (`src/application.py#build_application`, `src/strategy/strategies.py`)

Six registrations in the supported entrypoint (`src/application.py` ~line 200):
`LSTDepegStrategy`, `LSTUnstakeStrategy`, `CircularArbitrageStrategy`,
`KaminoLiquidationStrategy()`, `PumpMigrationStrategy(adapter_configured=False)`,
`OrderbookAmmStrategy()`. Declarations live in `src/resources/capabilities.json`
(schema `pr023.capabilities.v1`); `ArbitrageApplication.validate` hard-denies live.

| Registry name | Owner (file/class) | Capability value | R10 state | Verified evidence | Typed promotion blocker |
|---|---|---|---|---|---|
| `circular_arbitrage` | `src/strategy/strategies.py:53` `CircularArbitrageStrategy` + `src/strategy/detectors.py` `CircularArbitrageDetector` | `shadow-ready` (allowed `disabled/shadow`) | SHADOW_READY (shadow only) | `tests/test_pr056_runtime_discovery.py` (5), `tests/test_pr033_snapshot_detectors.py` (4), `tests/test_shadow_workers.py` (2); consumer is `ShadowOnlyOpportunityHandler`/`CapitalAwareShadowOpportunityHandler` (`src/strategy/consumer.py`) — shadow-not-executed outcomes | Detector is two-leg pair probing (`DetectorPair`) only; no exact capacity binding in the runtime detect path; planner/simulator/sender not wired |
| `lst_depeg` | `src/strategy/strategies.py:41` `LSTDepegStrategy` | `disabled` | STUB (`detector_not_implemented`; inherited `detect_once` returns `()`) | capability manifest reason; anchor owners exist but no detector consumes them | `detector_not_implemented`; `lst_exchange_rate_unproven`/`instant_exit_unproven` on production samples |
| `lst_unstake` | `src/strategy/strategies.py:47` `LSTUnstakeStrategy` | `disabled` | STUB (same) | same | same |
| `kamino_liquidation` | `src/strategy/strategies.py:90` `KaminoLiquidationStrategy` (`DisabledShellStrategy`); shadow planner `src/liquidation/strategy.py` (PR-023 quarantine header: "No sender, signer, Jito, keypair, or live permit modules") | `fixture-only`, `quarantined`, `active_in_supported_entrypoint=false` | FIXTURE_ONLY | `tests/test_liquidation_shadow_simulation.py` (1) | `provider.kamino` fixture_only_blocked set (rooted deployed account vectors, full reserve/fee/capacity proof, reviewed IDL/source identity, human review) — CAP-R02 |
| `pump_fun_migration` | `src/strategy/strategies.py:100` `PumpMigrationStrategy`; boundary `src/venues/pump` (PR-048 IDL pin) | `shadow-ready` (boundary), but constructed `adapter_configured=False` | PLANNED (detector yields nothing by construction; PR-021 comment at `strategies.py:111-115`) | IDL provenance pin; `detect_once` intentionally `()` | `PUMP_ADAPTER_NOT_CONFIGURED_SHADOW_ONLY`; discovery-only until token/program/pool exact-verified |
| `orderbook_amm_arbitrage` | `src/strategy/strategies.py:118` `OrderbookAmmStrategy` (`DisabledShellStrategy`) | `fixture-only`, `quarantined`, `active_in_supported_entrypoint=false` | FIXTURE_ONLY | `tests/test_orderbook_shadow_replay.py` (5) | `market_subscriptions_unverified` (Phoenix Legacy/OpenBook V2); fixture orderbooks fail closed in `src/strategy/market_graph_ingest.py` |

Registry counts: **6 total / 2 shadow-ready / 2 disabled (STUB) / 2 fixture-only**
(of the shadow-ready, `pump_fun_migration` is boundary-only and constructs disabled).

---

## 2. Task-brief strategy families 1–13 (typed inventory)

Columns: discovery inputs = what must be proven before the family can produce
candidates; promotion evidence is typed in the repo's evidence alphabet
(`EXACT_QUOTE` = exact per-amount re-quote, `CAPACITY` = R02 lender/venue capacity,
`BUILD` = transaction build conformance, `SIM` = exact atomic simulation,
`PAPER` = R06 paper pass). Cross-chain applicability: **Solana exact-local** is the
only proven local-atomicity domain today; Sui PTB (programmable transaction block)
is a research-only same-tx model until proven; TON is async multi-contract
(`TON_ASYNC_MULTI_CONTRACT`, never local atomic); EVM out of repo scope — research
only unless local atomicity is proven.

| # | Family | Owner file/class | Discovery inputs required | Relation generator used | Sizing path | Simulation requirements | Current state | Promotion evidence (typed) | Cross-chain applicability |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Direct two-leg market arbitrage | `src/strategy/detectors.py#CircularArbitrageDetector`, `src/strategy/strategies.py#CircularArbitrageStrategy`; exact math `src/strategy/exact_cpmm_capacity.py#ExactCpmmEdgeEvaluation` | Identity-verified asset pairs (`ResolutionState.IDENTIFIER_VERIFIED` + evidence refs); admissible `ObservationBatch`; snapshot age ≤ 5 s; slot skew 0 | `DIRECT_MARKET` (`relation_generators/generators.py:189`) | `DetectorPair.probe_amount_base_units` (runtime); `build_pr118_amount_grid` + `evaluate_pr118_non_monotonic_sizing` (`src/economics/non_monotonic_sizing.py`) for grid/conservative-net | Exact re-quote at every amount (CPMM only today: `evaluate_exact_cpmm_route`); PR118 typed cost ledger; canonical v0 sim for paper | SHADOW_READY (detector); exact math CPMM-only; execution DISABLED | `EXACT_QUOTE` (CLMM/DLMM binding) + `CAPACITY` + `BUILD` + `SIM` + `PAPER` | Solana exact-local; Sui PTB research; TON async → signal only |
| 2 | Venue fragmentation / route overlap | `src/strategy/relation_generators/generators.py:197-213` (`VENUE_FRAGMENTATION` block) | ≥ 2 identity-verified venues on one canonical pair with disjoint `correlation_group` + `underlying_resources` | `VENUE_FRAGMENTATION` | PR118 grid (via cycle path) | Exact re-quote per venue leg | RESEARCH_ONLY_VERIFIED; no detector consumes the relation yet | `EXACT_QUOTE` per venue + `CAPACITY` + `BUILD` + `SIM` | Same-chain only (Solana local; Sui PTB research; TON signal) |
| 3 | Direct vs synthetic/wrapped representation paths | `generators.py:214-257` (`SYNTHETIC_CROSS` + `DIRECT_SYNTHETIC_RESIDUAL`); residual `src/research/correlation_ledger/residuals.py#direct_synthetic_route_residual` | Verified hub + both real legs (`SYNTHETIC_LEGS_VERIFIED`); disjoint liquidity; `legs_proven_equal` for the residual | `SYNTHETIC_CROSS`, `DIRECT_SYNTHETIC_RESIDUAL` | PR118; residual is scale-normalized (no sizing until detector exists) | Route-leg-set equivalence proof; exact re-quote both routes | RESEARCH_ONLY_VERIFIED; detector STUB | `EXACT_QUOTE` both routes + leg proof + `CAPACITY` + `BUILD` + `SIM` | Solana local; Sui PTB research; TON rebalance signal |
| 4 | Bounded circular cycles (2–5 hops), exact re-quote at every amount | `src/strategy/arbitrage_graph.py#CircularGraphCandidateDetector`/`CircularShadowRoute` (3/4-hop, guaranteed-output coupled); `src/strategy/multihop_solver.py#search_bounded_cycles` (2–5 shortlist); `generators.py#shortlist_verified_cycles`+`edge_cycle_proof` (3–5 with per-edge proofs) | Admissible batch; single observation generation; ≤ 512 edges; PR118 amount points; per-edge `RPC_EXACT` QPR receipt ≤ 5 s for the verified shortlist | `bounded_exact_cycles` delegates to the existing owner (no second solver, `generators.py:352-365`) | `build_pr118_amount_grid` via `CircularGraphPolicy.amount_points`; `evaluate_shortlisted_routes` binds exact variants; `rank_resource_feasible_routes` enforces typed limits; `select_bounded_fee_bid` bounded | Exact evaluator must bind amount/state/full resource costs per route (shortlist alone is not a candidate — proven in §4 experiment C) | IMPLEMENTED_UNQUALIFIED (topology shortlist + 3/4-hop shadow routes); no current paper pass | `EXACT_QUOTE` all legs (CPMM ✓; CLMM/DLMM math landed #607, evaluator binding absent) + `CAPACITY` + `BUILD` + `SIM` + ROUTE-R04 + `PAPER` | Solana exact-local only; never TON async; Sui PTB research |
| 5 | Stablecoin triangles, peg deviation, cross-venue dislocations | anchor `STABLE_RESIDUAL` (`generators.py:260-291`), `residuals.py#stable_redemption_residual`; seeds F01/F02 (`docs/roadmap/gpr-parallel-radar-rnd-2026-10-06/FIRST_CAMPAIGN_FAMILIES_V2_2.json`); `src/strategies/stable_peg/` (MPR-2622) | Proven issuer redemption anchor + exit cost (`redemption_proven`, `exit_cost_known`); verified identities; fresh evidence ≤ 300 s | `STABLE_RESIDUAL` (flag `ANCHOR_UNDERLYING_PROVEN`) | Not wired (no detector) | Issuer mint/burn/redemption route conformance — unproven | RESEARCH_ONLY_VERIFIED (residual owner); detector STUB | `REDEMPTION_ANCHOR` proof + `EXACT_QUOTE` + `CAPACITY` + `BUILD` + `SIM` | Solana (USDG/USD1/USDC/USDT); cross-chain variants → rebalance only |
| 6 | LST/staking derivatives (mint/redeem/unstake, exchange-rate/NAV residuals) | `src/strategy/strategies.py#LSTDepegStrategy`/`LSTUnstakeStrategy` (shells); anchor `LST_FAIR_VALUE`; `residuals.py#lst_premium_residual`; F06/F12; `src/strategy_evolution/stake_queue.py` | `rate_proven` + `instant_exit_available` (+ cost); fresh anchor evidence; verified LST identities (23 LST representations in registry) | `LST_FAIR_VALUE` | Not wired | Unstake/instant-exit route conformance (cooldown/epoch semantics) | Registry STUB (`detector_not_implemented`); residual/anchor owners RESEARCH_ONLY_VERIFIED | `LST_RATE` + `INSTANT_EXIT` proofs + `EXACT_QUOTE` + `CAPACITY` + `BUILD` + `SIM` → residual-fed shadow detector | Solana LSTs; Sui LSTs (afSUI/haSUI/vSUI) PTB research |
| 7 | BTC wrapper/bridged representation basis | anchor `WRAPPER_BASIS`; `residuals.py#wrapper_basis_residual`; F04/F11 | `reference_proven` (BTC reference) + `wrap_cost_known`; distinct representations (`REPRESENTATION_DISTINCT`) | `WRAPPER_BASIS` | Not wired | Wrap/unwrap route conformance | RESEARCH_ONLY_VERIFIED | `REFERENCE` + `COST` proofs + `EXACT_QUOTE` + `CAPACITY` + `BUILD` + `SIM` | Solana wrappers; cross-chain basis is `SIGNAL_REBALANCE_ONLY` |
| 8 | Liquidation / health-factor (protocol risk-state proof) | `src/strategy/strategies.py#KaminoLiquidationStrategy`; `src/liquidation/` (planner/sizer/simulation/eligibility; `strategy.py` header: fixture-only quarantine, no sender/signer imports) | Rooted deployed-account vectors; full reserve/fee/capacity proof; reviewed IDL/source identity; human review (CAP-R02 set) | none (not relation-generated) | `LiquidationSizer`/`LiquidationSizingPolicy` (fixture) | `LiquidationSimulationReconciler` (fixture replay) | FIXTURE_ONLY (quarantined) | R02 `provider.kamino` gate + `EXACT_QUOTE` + `BUILD` + `SIM` | Solana Kamino; Sui NAVI research only |
| 9 | Funding/carry/basis and event-driven dislocations | F05 NAV basis (JLP); `Lifecycle.EVENT` heat (`src/discovery/dynamic_universe/universe.py`); `residuals.py#nav_basis_residual` | NAV-per-share source owner + `nav_proven`; no funding-rate source owner exists | `NAV_BASIS` | Not wired | Carry PnL over time is a separate economic family, not instant-flash profit | RESEARCH_ONLY (PLANNED detector) | Funding/rate source dossier + `NAV` proof + `EXACT_QUOTE` + `SIM` | Signal only, all chains |
| 10 | CEX lead/lag, orderbook imbalance, oracle/reference divergence | `src/strategy/strategies.py#OrderbookAmmStrategy` (fixture); `residuals.py#vwap_execution_residual` + `oracle_market_residual`; `src/decision/agg10.py#lead_lag_research`; `src/strategy/ranker.py#DecisionIntelligenceRanker` (advisory) | Verified market subscriptions; exact-size matched AMM/CLOB quotes (`amm_size == clob_size`); oracle slot alignment (≤ 3 slots, ≤ 1.0 s skew) | `ORACLE_MARKET` (anchor); VWAP residual is a ledger feature family | Not wired | IOC/maker-taker conformance unproven | FIXTURE_ONLY (orderbook leg) + RESEARCH_ONLY_VERIFIED (residual/intelligence owners) | `MARKET_SUBSCRIPTIONS` verified + `SIZE_ALIGNED` quotes + `EXACT_QUOTE` + `CAPACITY` + `BUILD` + `SIM` | CEX signals advisory-only (never qualify a route); Sui DeepBook research (GPR) |
| 11 | Memecoin/event token migration/liquidity events (discovery-only) | `src/strategy/strategies.py#PumpMigrationStrategy`; `src/venues/pump` (PR-048 IDL pin); TON radar analog `src/discovery/dynamic_universe/ton_radar.py` | Exact token/program/pool verification; configured verified adapter feed; migration event evidence | none (boundary-only) | Not wired | Migration pool conformance unproven | PLANNED / DISABLED (`PUMP_ADAPTER_NOT_CONFIGURED_SHADOW_ONLY`) | `ADAPTER_CONFIGURED` + exact migration-pool identity + `EXACT_QUOTE` + `CAPACITY` + `BUILD` + `SIM` | Solana Pump; TON discovery-only |
| 12 | Cross-chain/bridge basis, asynchronous settlement signals | `generators.py:292-326` (`CROSS_CHAIN_BASIS`, `SIGNAL_REBALANCE_ONLY`); transport transformations V2.2 (`src/research_economic_graph/transformations.py`); F14; TON radar | Parity across chains with distinct proven representations (`REPRESENTATION_DISTINCT` + `CROSS_CHAIN_RESEARCH_ONLY`); no transport-mechanism fake identities (registry refuses CCTP/Wormhole/USDT0 as tokens, `research_economic_graph/registry.py`) | `CROSS_CHAIN_BASIS` | Not wired | None (never execution) | RESEARCH_ONLY by design (permanent) | None to execution; rebalance tier needs `CHAIN_ALIGNED` basis + liquidity proof | TON async / Sui / bridges: rebalance signal, **never** a local atomic flashloan route |
| 13 | RWA/xStocks/gold-like representations (separate legal/access class) | F13 (XAUM) seed; `ORACLE_MARKET` anchor; `residuals.py#oracle_market_residual`; `representation_kind="rwa"` in `REPRESENTATION_KINDS` (`generators.py:30-32`) | Oracle reference feed (`oracle_slot_misaligned` otherwise); legal/access evidence class (separate) | `ORACLE_MARKET`, `STRUCTURAL_PARITY` (rwa) | Not wired | None yet | RESEARCH_ONLY (COLD heat) | Oracle reference pin + legal-access class + `EXACT_QUOTE` + `SIM` | Oracle-anchored; tokenized equities excluded by user policy (atlas §I consistent) |

Family-state counts: SHADOW_READY detector coverage 1/13 (family 1); research-signal
owners verified but detector stub/planned 9/13 (2, 3, 5, 6, 7, 9, 10-part, 11, 13);
FIXTURE_ONLY 1/13 (8) plus the orderbook leg of 10; research-only-by-design 1/13 (12).

---

## 3. Relation generator kinds (`src/strategy/relation_generators/generators.py`, wave #614)

`generate()` emits `ResearchRelation` rows; identity gate excludes non-verified assets
(`generators.py:108-129`); market-derived relations must carry `correlation_group` +
`underlying_resources` (`generators.py:154-155`, else `ValueError`); relations never
alter `execution_class`, `evidence_state`, `heat` or any promotion boundary (module
docstring). 12 emitted kinds:

| Kind | Gate | atomicity_class | State |
|---|---|---|---|
| `DIRECT_MARKET` | fresh verified markets | RESEARCH_ONLY | RESEARCH_ONLY_VERIFIED |
| `VENUE_FRAGMENTATION` | ≥ 2 venues, disjoint groups/resources | RESEARCH_ONLY | RESEARCH_ONLY_VERIFIED |
| `SYNTHETIC_CROSS` | verified hub + both legs | RESEARCH_ONLY (`SYNTHETIC_LEGS_VERIFIED`) | RESEARCH_ONLY_VERIFIED |
| `DIRECT_SYNTHETIC_RESIDUAL` | + direct market, disjoint liquidity | RESEARCH_ONLY | RESEARCH_ONLY_VERIFIED |
| `LST_FAIR_VALUE` / `NAV_BASIS` / `STABLE_RESIDUAL` / `WRAPPER_BASIS` / `ORACLE_MARKET` / `STRUCTURAL_PARITY` | `underlying_proven` + fresh anchor ≤ 300 s | RESEARCH_ONLY (`ANCHOR_UNDERLYING_PROVEN`) | RESEARCH_ONLY_VERIFIED (anchors proof-limited in production data) |
| `CROSS_CHAIN_BASIS` | distinct proven representations cross-chain | SIGNAL_REBALANCE_ONLY (`CROSS_CHAIN_RESEARCH_ONLY`) | RESEARCH_ONLY_VERIFIED (never execution) |
| `FLASH_CAPITAL` | `LENDER_QUALIFIED`, evidence ≤ 30 s fresh, live capacity > 0, LOCAL_ATOMIC_CANDIDATE | LOCAL_ATOMIC_CANDIDATE | IMPLEMENTED_UNQUALIFIED — **zero qualified edges in main** (CAP-R02) |

Core-owner retention (task rule): DIRECT_MARKET, VENUE_FRAGMENTATION,
DIRECT_VS_SYNTHETIC (as `SYNTHETIC_CROSS` + `DIRECT_SYNTHETIC_RESIDUAL`) and
BOUNDED_CYCLE (via `bounded_exact_cycles` → `CircularGraphCandidateDetector`) are all
retained; `bounded_exact_cycles` raises on non-`UniversalArbitrageGraph` input and
delegates — no second solver exists.

---

## 4. Offline replay experiment (deterministic, bounded, no network)

Files: `tests/test_r10_strategy_inventory_replay.py` (8 tests) and
`scripts/r10_offline_replay.py` (standalone receipt runner, convention mirror of
`scripts/verify_agg14_research.py`). Selected shadow-ready relation families:
LST-premium / wrapper-basis / oracle-market residuals (§4.1), the correlation-ledger
lead/lag gate (§4.2), and the multihop bounded solver on a synthetic fixture graph
(§4.3), plus relation-generator discovery + capital gating (§4.4). All inputs are
in-repo fixtures; timestamps are pinned (t≈200, `now=101`/`205`).

### 4.1 Residual family gates (families 6/7/13 anchors) — fail-closed confirmed

- `lst_premium_residual(rate_proven=False)` → `value=None`, exclusion
  `lst_exchange_rate_unproven`. `instant_exit_available=False` →
  `instant_exit_unproven`. Proven → exact value `(1.05 − 1.0·1.02 − 0.005)/1.0 = 0.025`.
- `wrapper_basis_residual(reference_proven=False)` → `underlying_reference_unproven`;
  proven → `−0.003` (feature `wrapper_basis`).
- `oracle_market_residual` with slot positions 1000/1005 (gap 5 > max 3) →
  `oracle_slot_misaligned`, `UNALIGNED`; aligned (1000/1001) → value `2.5`.
- `residual_observation()` materializes only proven CHAIN_ALIGNED samples; excluded
  samples materialize as `None` and are never written to the ledger (unknown is never
  zero). Ledger row count after append: **1**.

### 4.2 Lead/lag provenance gating — typed exclusion confirmed

Synthetic series: `amms` values `(0.2, −0.4, 0.6, −0.1, 0.3)` at t=200+i; `clob`
duplicates ×2 at t=200.1+i (0.1 s lag); plus one UNALIGNED sample at t=204.5.
`lead_lag_report("amms","clob",(5,),feature="stable_residual",now=205,lags=(0,0.1))`:

- exclusions: **1** row, reason `timestamp_alignment_unproven`, sample_count 1;
- lag 0: sample_count 0, correlation None; lag 0.1: sample_count 5,
  **correlation ≈ 1.0**, penalty 0, confidence `min(1, 5/30) ≈ 0.16667`;
- every finding `verification_state="DISCOVERY_ONLY"`;
- shared correlation group (`group="shared"` on both markets): correlation still 1 but
  penalty 1 → **confidence 0** (aliases are not independent evidence);
- restarted ledger reproduces byte-identical findings (deterministic replay).

### 4.3 Multihop bounded search + exact-evaluation binding — shortlist ≠ profit confirmed

Fixture graph (`SearchEdge` marginal rates): 2-hop cycle product `10200/10100 ≈ 1.0099`;
3-hop `104·103·100/100·100·107 ≈ 1.00112`; a 0.99-product cycle; a same-pool round trip.

- `search_bounded_cycles(start="A")`: finds exactly the 2-hop and 3-hop cycles
  (`stop_reason=complete`); the 0.99 cycle is excluded by the ≥ 1.0 marginal
  threshold; `minimum_marginal_gain_ppm=5000` additionally drops the 3-hop;
  same-pool round trip returns no routes (`pool_simple`);
  `max_expansions=3` on a fan-out graph → `BUDGET_EXHAUSTED` with `expansions == 3`
  (a typed stop reason, not a "no alpha" claim).
- Exact binding: evaluator returns `conservative_net_units=−50` for the 2-hop
  shortlist route → `rank_resource_feasible_routes` rejects with
  **`NON_POSITIVE_NET`**; a positive evaluation (net 40) at 3 hops is accepted and
  promotes to `MultiHopCandidate` (2-hop refuses with "requires 3-5 hops");
  an evaluator returning a fabricated `route_id` raises
  `ValueError("exact evaluator returned a different route identity")` — fail-closed.

### 4.4 Relation-generator discovery + capital gates on a synthetic fixture universe

Three verified assets (SOL/USDC/USDT mints), four disjoint pools (two venues on one
pair, a THIRD/OTHER pool, a direct THIRD/MINT pool), hub = USDC:

- Emissions: `DIRECT_MARKET` ×4, `SYNTHETIC_CROSS` ×2, `DIRECT_SYNTHETIC_RESIDUAL` ×2,
  `VENUE_FRAGMENTATION` ×1 (`truncated=False`); every market-derived relation carries
  correlation groups + liquidity resources.
- Identity gate: unverify the hub (`CANDIDATE` state) → only 1 `DIRECT_MARKET`
  remains; no synthetic/residual/fragmentation relations.
- Capital gate: a `LOCAL_ATOMIC_CANDIDATE` edge with current evidence and capacity 1000
  emits exactly `["FLASH_CAPITAL"]` with `LENDER_QUALIFIED`; zero capacity, stale
  evidence (> 30 s) and an unverified asset id emit **nothing**. (The edge owner itself
  refuses non-`LOCAL_ATOMIC_CANDIDATE` atomicity at construction.)

### 4.5 Exact test counts and receipt

`tests/test_r10_strategy_inventory_replay.py`: **8 passed / 0 failed / 0 skipped**.
Regression batch (18 related suites, run natively 2026-11-14, worktree base `e2b65c0c`):
**194 passed / 0 failed / 0 skipped** —
test_r10_strategy_inventory_replay 8, test_shadow_arbitrage_graph 45,
test_native_cpmm_qualification 34, test_exact_cpmm_capacity 24,
test_relation_h_generators 13, test_relation_h_residuals 12, test_agg05_multihop_solver 8,
test_dynamic_universe 7, test_dynamic_relations 7, test_dynamic_flash_capital 7,
test_pr056_runtime_discovery 5, test_orderbook_shadow_replay 5, test_cpmm_fee_accounting 5,
test_pr033_snapshot_detectors 4, test_dynamic_correlation_ledger 4, test_cpmm_split_replay 3,
test_shadow_workers 2, test_liquidation_shadow_simulation 1.
`scripts/r10_offline_replay.py --json` exits 0 with receipt
`schema="r10.offline-replay.v1", ok=true` containing the per-experiment numbers above.

---

## 5. Typed promotion blockers (feed-forward to coordinator dashboard)

### 5.1 BLOCKED BY R02 CAPACITY (user-gated live authorization; AGENTS.md rule 8)

- `FLASH_CAPITAL` qualification: zero `LENDER_QUALIFIED` edges in main; MarginFi bank
  reader (#619) decodes caller-supplied captures offline fail-closed only; live
  `get_program_accounts` enumeration is typed blocked. Unlocks LOCAL_ATOMIC economics
  for the whole universe — user-gated, not evidence-gated alone.
- Any live capacity/freshness read (the ≤ 30 s freshness gate on capital edges cannot
  be satisfied offline for live use; offline replay can pre-qualify the decode path only).
- `kamino_liquidation`: `provider.kamino` fixture_only_blocked set (rooted account
  vectors, reserve/fee/capacity proof, reviewed IDL, human review).
- Live runtime mode itself: `capabilities.json runtime_modes.live.available=false`.

### 5.2 BLOCKED BY QUOTE/BUILD/SIMULATION/PAPER gaps (evidence-gated, no user gate needed)

- **CLMM/DLMM exact-evaluator binding**: `src/providers/raydium_clmm_native.py` and
  `src/providers/meteora_dlmm_native.py` decoders landed (#607) but are not bound as an
  exact evaluator behind the graph/shortlist (only CPMM via
  `src/strategy/exact_cpmm_capacity.py`). Highest-leverage next integration.
- ROUTE-R04 `route_candidates_not_qualified` and PAPER-R06 `no_current_24h_paper_pass`
  (paper contract requires qualified route candidates + current 24 h paper PASS).
- SIM-R05 surfaces for the canonical paper vertical (`atomic_stage_suite`,
  `exact_fee_workflow`, `verified_marginfi_provider`, `jupiter_v2_build`).
- `detector_not_implemented` (lst_depeg/lst_unstake registry stubs) — the residual and
  anchor owners they need are already merged and tested.
- `PUMP_ADAPTER_NOT_CONFIGURED_SHADOW_ONLY` (+ exact migration-pool identity proof).
- `market_subscriptions_unverified` (Phoenix Legacy/OpenBook V2) for orderbook families.
- Anchor proofs unproven in production data: `redemption_anchor_unproven`,
  `nav_per_share_unproven`, `lst_exchange_rate_unproven`, `instant_exit_unproven`,
  `underlying_reference_unproven`, `oracle_slot_misaligned` (typed exclusion reasons
  implemented in `residuals.py`; the proofs themselves are missing source dossiers).

### 5.3 Advisory-output boundary (binding)

Correlation/residual/model output (ledger findings, `CandidateScore`, heat, AGG-10
lead/lag, EVO-09, `ModelStatus.SHADOW_CHALLENGER` scores) may order/schedule/rank only;
it may not alter `execution_class`/`evidence_state`/`heat`, prove causation, substitute
for identity/quote/capacity/simulation/paper gates, or serve as execution evidence.
Experiments §4.1–4.2 pin the mechanical side of this (typed exclusions, confidence 0
on aliases, `DISCOVERY_ONLY` state). Cross-chain basis is `SIGNAL_REBALANCE_ONLY` and
must never be labeled a local atomic flashloan route.

---

## 6. PR #599 `STRATEGY_UNIVERSE_ATLAS.md` cross-check (cited, not merged)

PR #599 is **OPEN** (unmerged, branch `docs/master-strategy-atlas-2026-11-13`); its
atlas is a research crosswalk ("not an assertion that the strategies are executable").
Per-family agreement check against actual code:

- **§A Core local arbitrage — AGREE.** "Current circular detector is two-leg; multihop
  solver returns a shortlist until exact evaluation" matches `detectors.py`
  (`DetectorPair`) and `multihop_solver.py` docstring, and is mechanically proven by
  §4.3 (marginal 1.0099 route rejected `NON_POSITIVE_NET` by exact evaluation).
- **§B Stablecoin/issuer economics — AGREE on state** (no issuer-rights/maturity/exit
  proof owners; "not every redemption is atomic" is consistent with the
  `redemption_anchor_unproven` gate). The atlas lists far more protocols (USDT0
  triangles, EUR0/EURC, USD0 splits) than have owners; those are seeds/registry rows
  only (F01/F02/F09/F10 heat classes), correctly not claimed as executable.
- **§C LST/LRT/NAV — AGREE.** "Existing LST strategy classes in
  `src/strategy/strategies.py` are shells/disabled" verified verbatim (`detector_not_
  implemented` shells). "Need current issuer semantics and exact exitability" matches
  `lst_exchange_rate_unproven`/`instant_exit_unproven`.
- **§D Wrappers/bridge/cross-chain — AGREE.** "Bridge and async multi-chain transfer is
  NOT a local atomic flashloan leg. A bridge may be a lead/lag feature only" matches
  `CROSS_CHAIN_RESEARCH_ONLY`/`SIGNAL_REBALANCE_ONLY` and the registry's refusal of
  transport-mechanism fake identities.
- **§E CLOB/AMM/microstructure — AGREE on state** ("Orderbook/AMM strategy is disabled
  until verified subscriptions" matches the quarantined capability). Refinement: the
  atlas names CLMM/DLMM/Whirlpools/V3/V4 active-state math; in code only Raydium CLMM +
  Meteora DLMM native decoders exist (#607) and no exact evaluator binding yet (§5.2).
- **§F Vault/yield/maturity — AGREE** (research owners in `src/strategy_evolution/`;
  "delayed maturity/cooldown is not immediate settlement" consistent with fail-closed
  residual gating).
- **§G Lending/credit/capital events — AGREE with one refinement.** Atlas says
  "Liquidation strategy is shadow-only"; in the runtime registry it is
  DISABLED/FIXTURE_ONLY quarantined, with the shadow planner quarantined in
  `src/liquidation/strategy.py` — shadow-only planning exists, but no detector wiring
  and no provider gate passed.
- **§H Events/governance/blockspace — AGREE** (mostly research-only; Pump shell +
  PR-048 boundary; TON radar discovery-only with `LIVE_CAPTURE_NOT_AUTHORIZED`).
- **§I Reference-only/excluded — AGREE** (CEX-DEX lead/lag and oracle residuals are
  reference features; tokenized equities excluded by user policy — consistent with
  F13 XAUM remaining a COLD research seed).

No disagreement on facts was found; the atlas is broader in protocol enumeration than
code reality (expected for a crosswalk) and its state claims matched code everywhere
the code has an owner.

---

## 7. Safety, recommendation, next tasks

- **Safety**: read-only wrt `src/`; no network/live calls; no new graph/solver/registry
  owner; experiment uses existing owners only; ML/correlation outputs rank/alert only.
  Live remains hard-denied; nothing in this report promotes a strategy class by itself
  (R10 acceptance rule).
- **Recommendation** (unchanged from the ranked shortlist; now experiment-confirmed):
  1. Bind the CPMM exact evaluator into the bounded-cycle paper path
     (`exact_cpmm_capacity` × `CircularGraphCandidateDetector` ×
     `native_cpmm_qualification`, PR118 grids) — R04/R06 lane; R10 supplies inventory.
  2. MarginFi offline edge-qualification replay through `FlashCapitalGraph` from pinned
     captures — R02-CAP lane (live reads stay user-gated).
  3. LST stub → residual-fed shadow detectors consuming `lst_premium_residual` +
     `LST_FAIR_VALUE` via `StrategyContext` — R10 follow-up.
- **Remaining promotion gates by class**: R02-capacity/user-gated (capital edges, live
  reads, Kamino provider) vs evidence-gated (CLMM/DLMM evaluator binding, ROUTE-R04,
  PAPER-R06, SIM-R05 surfaces, detector bodies, subscriptions, anchor-proof dossiers).
