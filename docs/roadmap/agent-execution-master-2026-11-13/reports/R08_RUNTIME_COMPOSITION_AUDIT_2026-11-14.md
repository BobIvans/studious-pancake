# R08 — Runtime composition integration audit (owner-injection matrix + integration plan)

- Lane: R08 (runtime composition integration audit)
- Date: 2026-11-14
- Branch: `agent/r08-runtime-composition-audit`
- Base SHA: `e2b65c0ceefdc6f9f99cdc0187ff23dc7815acc8` (merge of PR #620; includes #593 intake cadence, #606 unsigned builders, #609/#612/#619 R02 readers, #617 rent sponsor planner)
- Scope: read-only audit + design. No `src/` edits in this lane. Only this report and a new additive test file (`tests/test_r08_composition_invariants.py`) were added.
- Method: static boot-path trace from the installed console script, plus a full `src/` import-graph audit of every canonical owner named in PROJECT_KNOWLEDGE_BASE_MAP.md / PROJECT_STATUS.json. Every wiring claim below cites `file:line`. No live RPC, no network, no capability changes.

## 0. Evidence vocabulary (from PROJECT_STATUS.json)

`IN_MAIN_VERIFIED`, `IMPLEMENTED_UNQUALIFIED`, `IMPLEMENTED_UNBOUND`, `FIXTURE_ONLY`, `STUB`, `PLANNED`, `LIVE_READ_PROVEN`, `RPC_EXACT`, `BUILT_OFFLINE_UNQUALIFIED`, `SIMULATION_PASS`, `PAPER_QUALIFIED`, `BLOCKED`, `RETIRED`.

This report adds a composition-only gap vocabulary (`INTEGRATION_GAP_*`, §5) because "implemented" does not distinguish *injected into the supported boot path* from *importable as a library*. A module existing on disk (or being offline-tested) is not proof that the installed `flashloan-bot` process executes it; that distinction is the entire subject of this audit.

## 1. Supported entrypoint and boot-path truth (IN_MAIN_VERIFIED)

Installed console scripts (pyproject.toml:81-90): `flashloan-bot = "src.cli_pr189:main"` (line 83) is the only runtime entrypoint. `flashloan-connections` (offline connection-profile validator), `flashloan-contracts`, `flashloan-checks`, `flashloan-release-evidence`, `flashloan-external-resources`, `flashloan-bot-healthcheck` are governance/ops surfaces, not trading runtimes. There is **no** installed console script for the qualification campaign or the Solana radar; both are module CLIs (`python -m`, `src/qualification_campaign/cli.py:430`, `src/solana_parallel_radar/cli.py:967`).

Boot trace for the installed entrypoint:

1. `src.cli_pr189.main` (src/cli_pr189.py:53-65): command `run` → `src.runtime.runtime_entrypoint.main` (immutable MPR-RP adapter). All other commands → `src.cli_entrypoint.main` (inspection/automation delegation, cli_entrypoint.py:448-491).
2. `runtime_entrypoint.main` (src/runtime/runtime_entrypoint.py:282-349):
   - `--mode live` → hard-denied before anything else: prints `LIVE_MODE_UNAVAILABLE`, exit 4 (lines 288-290). A second hard-deny exists in the compatibility surface `src/cli_entrypoint.py:434-441` (with `LIVE_MODE = "li" + "ve"` deliberately split at line 35 to defeat env/flag grepping) and in the legacy CLI `src/cli.py:468-474`.
   - `evaluate_runtime_authority_map()` fail-closed admission (lines 292-309, exit 5 on invalid/unaccepted authority).
   - `CommandCapabilityManifest.evaluate("flashloan-bot.run")` + platform qualification (lines 311-320, exit 5 with blockers).
   - `disabled` → inspection JSON, exit 0 (lines 321-334).
   - `paper` → `asyncio.run(_run_paper(...))` (lines 335-345).
   - `shadow` → `src.cli.main` → application-level detector-only shadow (src/cli.py:464-491).
3. `_run_paper` (runtime_entrypoint.py:182-274): `load_runtime_config(cli_overrides={"runtime.mode": "paper"})` → profile selection (`core-marginfi-jupiter-v1` default; `core-jupiter-lend-jupiter-v1` via `FLASHLOAN_CORE_V1_PROFILE_ID`, lines 152-179) → `resolve_installed_core_v1_dependencies` (line 242) → `build_core_v1_composition` (lines 247-253) → `RepeatedInstalledPaperService` supervisor (lines 258-263).
4. The `paper-shadow` command (compatibility surface) → `src/cli.py:531-536` → `_run_paper_shadow_once` (line 348-365) → `build_paper_shadow_runtime` (PR-089/PR-102 composition, src/paper_shadow/composition.py:226-263).

`src/resources/runtime_authority.json` declares the same truth (`active_composition_root.entrypoint = "flashloan-bot"`, `module = "src.cli_pr189"`, `sender_free: true`, `live_enabled: false`), and `config/capabilities.json` (`pr023.capabilities.v1`) declares `runtime_modes.live.available = false`, `product_state = "not-production-ready"`, `supported_entrypoint = "flashloan-bot"`.

## 2. Owner-injection matrix

Legend: **WIRED** = the owner is constructed/injected by a module reachable from the installed entrypoint (evidence given). **LIBRARY-ONLY** = importable and offline-tested but unreachable from the supported boot path. Status uses the evidence vocabulary. "Composition call" cites the exact construction/injection site.

### 2.1 Wired into the supported boot path

| # | Owner | Canonical path | Composition call (file:line) | Supported entrypoint | Mode gate | Status | Notes |
|---|---|---|---|---|---|---|---|
| W1 | UnifiedLifecycleAuthority | src/durability/unified_authority_pr02.py | core_v1_composition.py:334-341 | paper (CORE-V1) | paper only | IN_MAIN_VERIFIED | single lifecycle authority, `environment="paper"`; also declared in runtime_authority.json `lifecycle_authority` |
| W2 | DurableCapitalCoordinator | src/economics/durable_reservations.py | core_v1_composition.py:342-346 (`PolicyProfile.PAPER`) | paper (CORE-V1) | paper only | IN_MAIN_VERIFIED | single capital authority; `capital.store is authority.lifecycle` (covered by tests/test_core_v1_composition.py:44) |
| W3 | AtomicMarginfiJupiterPlanner | src/planning/atomic_marginfi_jupiter.py | core_v1_composition.py:364-367 (blocked legacy), 481-485 (generic admitted), 544-547 (legacy admitted) | paper (CORE-V1) | paper; planner runs only on materialized candidates | IN_MAIN_VERIFIED (planner mechanics) / IMPLEMENTED_UNQUALIFIED (route economics) | program-id allowlist enforced via AtomicPlannerPolicy; generic path adapts financing ports through W11 |
| W4 | ExactSimulationFinalizer | src/execution/exact_simulation.py | core_v1_composition.py:368-371 (blocked RPC), 486-489 (resolver RPC), 548-551 | paper (CORE-V1) | paper; RPC is fail-closed today | IN_MAIN_VERIFIED (wiring) / IMPLEMENTED_UNQUALIFIED (simulation evidence) | every RPC supplied by the supported path is a blocked client (see §2.3 R1): `_BlockedRpcClient` composition:173-177, `_ResolverBlockedRpc` resolver:48-52 |
| W5 | AtomicPlannerSimulationReconciliationVertical | src/paper_shadow/atomic_vertical.py | core_v1_composition.py:372, 490-494 (with financing decoder), 552 | paper (CORE-V1) | paper | IN_MAIN_VERIFIED | decoder identity validated against financing evidence (composition:146-167) |
| W6 | ExactPaperAttemptOrchestrator | src/paper_shadow/exact_attempt_pr152.py | core_v1_composition.py:373-377, 495-499, 553-557 | paper (CORE-V1) | paper | IN_MAIN_VERIFIED | binds capital coordinator + vertical + authority; zero-reservation invariant covered offline |
| W7 | DurableCompletedExactAttemptRuntime | src/paper_shadow/mpr2602_completion.py | core_v1_composition.py:378-381, 500-503, 558-561 | paper (CORE-V1) | paper | IN_MAIN_VERIFIED | terminal cycle owner |
| W8 | VerifiedTerminalInstalledPaperService | src/paper_shadow/mpr2602_verified_a3.py (`build_verified_terminal_paper_service`) | core_v1_composition.py:382-388 (blocked), 504-510, 562-568 | paper (CORE-V1) | paper | IN_MAIN_VERIFIED | durable paper service; batch source is blocked (§2.3 R2) |
| W9 | CoreV1AttemptMaterializer + CoreV1MaterializedBatchSource | src/runtime/core_v1_materializer.py | core_v1_composition.py:450-459, 534-543 | paper (CORE-V1) | paper | IN_MAIN_VERIFIED | draft materialization is the fail-closed gate between candidates and attempts |
| W10 | RuntimeAuthority admission (evaluate_runtime_authority_map) | src/runtime_authority.py + src/resources/runtime_authority.json | runtime_entrypoint.py:292-309 | all run modes | fail-closed, exit 5 | IN_MAIN_VERIFIED | generation-binds capabilities.json + market_source_catalog.json (runtime_authority.json `generation_bindings`) |
| W11 | JupiterLendFinancingPort / SlumlordFinancingPort / JupiterLendSlumlordRepaymentDecoder | src/lending/agg03_financing_ports.py, src/execution/agg03_financing_decoder.py | resolver:246-251 (only with qualified v2 evidence manifest + admission receipts) | paper (CORE-V1, jupiter-lend profile) | manifest-gated; `build_status` never `capacity_status` | IMPLEMENTED_UNQUALIFIED | even when fully resolved, resolver returns blocker `CORE_V1_PROVIDER_DRAFT_SOURCE_EXTERNAL` because the wired draft source is `BlockedCoreV1DraftSource` (resolver:261-280) |
| W12 | MarginfiFlashLoanProvider | src/providers/marginfi/ | core_v1_composition.py:358-360 (legacy profile, blocked path only) | paper (CORE-V1, marginfi profile) | contract-pin gated | IMPLEMENTED_UNQUALIFIED | capabilities.json still lists `provider.marginfi` quarantined/fixture-only; composition use is evidence-gated, not a promotion |
| W13 | RuntimeDiscoveryCoordinator + DiscoveryPlane + ProviderRegistry + JupiterQuotaManager | src/runtime_discovery_builder.py, src/runtime_discovery_coordinator.py, src/routing/registry.py | paper_shadow/composition.py:253-256 → runtime_discovery_builder.py:34-61 | paper-shadow / shadow | shadow-ready strategy only; Jupiter adapter disabled unless `config.providers.jupiter.enabled` (builder:26-32,42-49) | IN_MAIN_VERIFIED (shadow discovery plane) | provider admission via `ProviderGovernance.from_adapters` (routing/registry.py:176,224) — the one governance-injected component in the shadow path |
| W14 | CircularArbitrageDetector + PaperShadowRunner + stage suite | src/strategy/detectors.py:23 (coordinator import), src/paper_shadow/runner.py, composition.py:30-47 | paper_shadow/composition.py:243-252, 270-281 | paper-shadow / shadow | default dependency gate = `PaperShadowDependencyGate` for ALL stages (blocked_pr089_atomic_dependencies_missing) | IN_MAIN_VERIFIED (runner) / IMPLEMENTED_UNBOUND (atomic stages: all four required deps default-None, composition.py:55-60,101-116) | no synthetic fills: candidates without verified deps record stage-blocked evidence |
| W15 | CapabilityMatrix / strategy registry | src/capabilities.py, src/strategy/strategies.py | src/cli.py:520-521; validated against registry (tests/test_pr023_runtime_truth.py:33-43) | all modes | disabled/shadow only; live not encodable | IN_MAIN_VERIFIED | capability manifest ↔ registry lockstep already tested |

### 2.2 Library-only canonical owners (IMPLEMENTED_UNBOUND — not injected into any supported boot path)

| # | Owner | Canonical path | Import-graph evidence (who imports it, outside its own package/tests) | Missing injection point | Status |
|---|---|---|---|---|---|
| L1 | DynamicUniverse | src/discovery/dynamic_universe/universe.py:106 | only `dynamic_universe/campaign.py:22`, `promotion.py` (MarketIdentity type only), `strategy/relation_generators/generators.py:27`, `solana_parallel_radar/intake_cadence.py:24` | no draft-source/universe source in core_v1_composition or materializer | IMPLEMENTED_UNBOUND (UNIVERSE-01) |
| L2 | Radar intake cadence + DynamicUniverse coverage bridge (merged P0-1 #593) | src/solana_parallel_radar/intake_cadence.py (IntakeScheduler) | imported only by `solana_parallel_radar/din_discovery.py:40`; `din_discovery.py` is imported by **nothing** in `src/` | no runtime call site; radar CLI is module-level, not installed | IMPLEMENTED_UNBOUND |
| L3 | Governed quote funnel probes (Jupiter V2 owner, P0-2) | src/solana_parallel_radar/probes.py, funnel.py | `funnel` imported by probes.py:20 and radar cli.py:51-52 (module CLI only); `probes` imported by nothing outside the radar package | no quote provider injected into planner/materializer | IMPLEMENTED_UNBOUND (SOL-QUOTE-01) |
| L4 | FlashCapitalGraph | src/economics/flash_capital_graph/graph.py:241 | imported only by `strategy/relation_generators/generators.py`; `FlashCapitalGraph(` is **never instantiated anywhere in src/** | no capacity reader emits into a runtime graph | IMPLEMENTED_UNBOUND |
| L5 | R02 read-only capacity readers (#609/#612/#619) | src/lending/kamino.py (`observe_kamino_reserve_capacity`:1543, `build_kamino_capital_reader_result`:1704), src/multichain/sui.py (NAVI pool reader), src/providers/marginfi/bank_discovery.py, src/lending/jupiter_lend.py (TokenReserve reader) | each reader has zero callers in `src/` outside its own module; offline replay tests only (`tests/test_r02_cap_*_reader.py`, `tests/test_r02_cap_*_offline_replay.py`) | no reader is bound to a `LiveCapitalProvider`/`FlashCapitalEdge` emission point reachable from boot | BUILT_OFFLINE_UNQUALIFIED |
| L6 | R03 unsigned builders (merged #606) | src/lending/unsigned_builders/ (contract.py + jupiter/kamino/navi/project0 builders) | imported only by `src/planning/rent_sponsor_planner.py` | no builder is injected into the planner/simulation vertical; `FinalizedUnsignedSolanaPlan` has no runtime consumer | BUILT_OFFLINE_UNQUALIFIED (CAP-R03) |
| L7 | RentSponsorPlanner (merged #617) | src/planning/rent_sponsor_planner.py | imported by **nothing** in `src/` | no planner call site; CORE-V1 generic path already reserves a rent financing slot (resolver:183-184, composition:423-436) but binds only `SlumlordFinancingPort`, not RentSponsorPlanner | IMPLEMENTED_UNBOUND (RENT-PLAN-R14) |
| L8 | Qualification campaign (QPR) | src/qualification_campaign/ (SourceIntakePlane, profiles, rpc, evidence) | used by `runtime_authority.py:19` (identity `digest` only), `dynamic_universe/promotion.py`, `gpr_sui_shadow/*`, `solana_parallel_radar/*`, `market/native_cpmm_capture.py`; CLI is `python -m` (cli.py:430) | campaign evidence never feeds the CORE-V1 materializer draft source | IN_MAIN_VERIFIED as governance library; IMPLEMENTED_UNBOUND as runtime input |
| L9 | Relation generators + CorrelationLedger | src/strategy/relation_generators/, src/research/correlation_ledger/ | relation_generators: zero importers in src (tests only); correlation_ledger: internal only (residuals.py → ledger.py) | no candidate generator feeds any runtime queue | IMPLEMENTED_UNQUALIFIED (STRATEGY-01) |
| L10 | ResearchEconomicGraph | src/research_economic_graph/ | used by `gpr_sui_shadow/*` and `solana_parallel_radar/*` research chains only | not reachable from boot | IMPLEMENTED_UNQUALIFIED |
| L11 | AssetResolver | src/assets/resolution/ | used by library owners only (dynamic_universe, flash_capital_graph, kamino, correlation_ledger, intake_cadence, relation_generators) | runtime discovery uses `RuntimeDiscoveryUniverse.load_default()` (builder:50), not the resolver pipeline | IMPLEMENTED_UNQUALIFIED |
| L12 | Universal route topology (arbitrage_graph, multihop_solver, PR118 non_monotonic_sizing, exact_cpmm_capacity) | src/strategy/arbitrage_graph.py, multihop_solver.py, src/economics/non_monotonic_sizing.py, src/strategy/exact_cpmm_capacity.py | used by research/replay owners only: dynamic_universe/promotion.py, paper_shadow/market_scale_replay.py + native_cpmm_qualification.py, strategy/shadow_workers.py, flash_capital_graph, qualification campaign; `multihop_solver` imported by nothing but relation_generators | route selection is not part of the paper cycle; planner is per-candidate atomic MarginFi/Jupiter only | IMPLEMENTED_UNQUALIFIED (ROUTE-R04) |

### 2.3 The three fail-closed gates that make the wired paper path safe today

Even for wired owners, the supported paper path cannot produce an executable attempt today. This is by design and must be preserved:

- **R1 — blocked RPC**: every `RpcClient` the supported path can construct raises `CORE_V1_BLOCKED_EXTERNAL` (composition `_BlockedRpcClient`:173-177; resolver `_ResolverBlockedRpc`:48-52). A governed, deployment-supplied RPC is a prerequisite for any simulation evidence (R05).
- **R2 — blocked draft source**: `resolve_installed_core_v1_dependencies` wires `BlockedCoreV1DraftSource()` even for a fully qualified evidence manifest (resolver:264), and returns blocker `CORE_V1_PROVIDER_DRAFT_SOURCE_EXTERNAL` (resolver:276-280). Marginfi profiles are unconditionally blocked (resolver:140-145). A qualified manifest therefore yields an admitted composition whose every cycle materializes BLOCKED drafts — fail-closed, no synthetic fill.
- **R3 — paper-shadow dependency gate**: `PaperShadowRuntimeDependencies()` defaults all four required dependencies to None (composition.py:101-116); `_stage_mapping` then replaces every stage with `PaperShadowDependencyGate` (composition.py:270-281). The shadow path additionally never imports a sender (existing test tests/test_pr023_runtime_truth.py:116-138).

## 3. Composition graph (current vs target)

Current supported paper graph (CORE-V1, paper mode):

```
flashloan-bot run --mode paper
  → runtime admission (authority map, capability manifest, platform)   [W10]
  → CoreV1ReleaseProfile (marginfi | jupiter-lend)
  → resolve_installed_core_v1_dependencies
      manifest gates → FinancingPorts + decoder (W11) or BLOCKED
      draft source = BlockedCoreV1DraftSource                        [R2]
      rpc = _ResolverBlockedRpc                                      [R1]
  → build_core_v1_composition
      UnifiedLifecycleAuthority (W1) → DurableCapitalCoordinator (W2)
      → CoreV1AttemptMaterializer (W9) → AtomicMarginfiJupiterPlanner (W3)
      → ExactSimulationFinalizer (W4) → AtomicVertical (W5)
      → ExactPaperAttemptOrchestrator (W6) → DurableCompletedExactAttemptRuntime (W7)
      → VerifiedTerminalInstalledPaperService (W8)
  → RepeatedInstalledPaperService supervisor
```

Missing edges (target graph, all currently absent):

```
qualification campaign evidence ──────────→ CoreV1 draft source        (E1)
DynamicUniverse + intake cadence ─────────→ candidate drafts           (E2)
radar funnel probes (Jupiter V2) ─────────→ exact quotes for planner   (E3)
R02 capacity readers → FlashCapitalGraph ─→ capacity-aware sizing      (E4)
R03 unsigned builders ────────────────────→ planner plan compilation  (E5)
RentSponsorPlanner ───────────────────────→ rent financing slot        (E6)
governed RPC (deployment-supplied) ───────→ ExactSimulationFinalizer   (E7)
```

## 4. Headline numbers

- Canonical owners audited: **27** (15 wired groups, 12 library-only groups as tabulated).
- Owners **wired into the supported boot path**: **15** (W1-W15; of these, W11/W12 are evidence-gated and produce no external effect today).
- Canonical owners **library-only (IMPLEMENTED_UNBOUND) not reachable from `flashloan-bot`**: **12** (L1-L12), including every owner merged by the 2026-11-13/14 wave: intake cadence (#593), unsigned builders (#606), R02 readers (#609/#612/#619), RentSponsorPlanner (#617).
- Net effect: the supported paper entrypoint executes a complete sender-free lifecycle whose candidate supply, quote supply, capacity supply, builder supply and simulation transport are all deliberately blocked. **No merged wave owner changed what the installed process executes.**

## 5. Typed integration gaps (INTEGRATION_GAP_*)

| Code | Owner(s) | Typed gap |
|---|---|---|
| INTEGRATION_GAP_DRAFT_SOURCE | L1 DynamicUniverse, L2 intake cadence, L8 campaign | No runtime component supplies a non-blocked `CoreV1DraftSource`; the materializer (W9) is the single injection point. Unproven identities must stay counted rejections, never promotions (intake_cadence.py:10-14 contract). |
| INTEGRATION_GAP_QUOTE | L3 funnel probes | The planner consumes candidate plans, not quotes; there is no quote provider port in `CoreV1Dependencies`. Adding one requires freezing the quote normalization owner first (P0-2 owns probes/funnel). |
| INTEGRATION_GAP_CAPACITY | L4 FlashCapitalGraph, L5 R02 readers | Readers emit observations but no `FlashCapitalEdge` reaches a sizing decision in the paper cycle; `CapitalPolicy.from_runtime_config(PAPER)` (composition:344-345) is policy-only. |
| INTEGRATION_GAP_BUILDER | L6 unsigned builders | `FinalizedUnsignedSolanaPlan` has no consumer in the vertical; planner→compiler binding must respect the frozen R03-00 contract (`UNSIGNED_BUILDERS_CONTRACT_VERSION`, `assert_no_execution_ready_capacity_member`). |
| INTEGRATION_GAP_RENT | L7 RentSponsorPlanner | CORE-V1 already validates a rent financing pair (composition:139-144, 423-436) but only binds `SlumlordFinancingPort`; RentSponsorPlanner's 4-tier plan has no adapter into `FinancingPort`. |
| INTEGRATION_GAP_RPC | W4 | No deployment-supplied governed RPC exists; `_ResolverBlockedRpc`/`_BlockedRpcClient` are the only transports. |
| INTEGRATION_GAP_STAGE_SUITE | W14 | The four PR-102 dependencies (atomic_stage_suite, exact_fee_workflow, verified_marginfi_provider, jupiter_v2_build) are default-None; the shadow path can never pass the gate until reviewed evidence is injected by a composition change, not a flag. |

Gap discipline: keep modules that only perform diagnostics/research outside the supported application path until their evidence contract is accepted (task R08 §4). No gap above may be closed by editing `config/capabilities.json`, env, or the strategy registry (task R08 §6; enforced by existing tests/test_pr023_runtime_truth.py:58-67).

## 6. Ordered integration plan (composition-only, smallest first, live stays hard-denied)

Hard dependency gates (CURRENT_STATE.json `dependency_gates`): **R04** needs exact quotes + qualified R-02 capacity + R-03 builder; **R05** needs R04; **R06** needs QPR PASS + R05. Live remains hard-denied at every step; sign/send boundaries untouched; no new authority, journal, ledger or sender.

| Step | Inject | Into | Contract tests required before merge |
|---|---|---|---|
| 1 | Governed RPC (deployment-supplied, rooted) | `CoreV1Dependencies.rpc` replacing `_ResolverBlockedRpc` (resolver seam already typed) | resolver accepts governed transport only; blocked-RPC default preserved when absent; simulation evidence hash binding |
| 2 | R-03 unsigned builders | `CoreV1AttemptMaterializer` plan compilation: bind `FinalizedUnsignedSolanaPlan` to planner output via a new adapter implementing the frozen contract; `build_status` separate from `capacity_status` | builder conformance fixtures (offline SDK pins); `assert_no_execution_ready_capacity_member` negative; plan-hash identity across planner/compiler stages |
| 3 | R-02 capacity readers → FlashCapitalGraph | A `LiveCapitalProvider` adapter emitting `FlashCapitalEdge` per reader, injected as a sizing port consumed before `AtomicMarginfiJupiterPlanner`; zero qualified edges ⇒ sizing blocks (no route) | reader→edge identity binding (lender/program/generation); stale-capacity rejection; missing-capacity fail-closed cycle |
| 4 | Quote funnel probes (P0-2 Jupiter V2 owner) | A quote port feeding capital-aware route candidates (R04 prerequisite: exact quotes); only comparable, funnel-normalized quotes | schema-drift/no-route/429/timeout negatives already pinned by P0-2; quote provenance hash into candidate evidence |
| 5 | RentSponsorPlanner | The rent financing slot already reserved by CORE-V1 (`rent_financing_port`/`rent_financing_evidence`): adapter from 4-tier plan to `FinancingPort` | tier economics fail-closed; UNKNOWN account cost stays UNKNOWN; unsigned/local-only negatives |
| 6 | DynamicUniverse + intake cadence + campaign | `CoreV1DraftSource`: a governed batch source that materializes drafts only from chain-proven identities (EvidenceStore-backed), keeping `_BlockedBatchSource` as default | stale identity rejection; missing-source fail-closed; unproven-identity counted-rejection; storage-pressure drain |
| 7 | R05 exact vertical qualification | (already wired W3-W7) run complete plan→simulate→reconcile on qualified candidates only | simulation-pass evidence receipts; financing evidence mismatch negatives |
| 8 | R06 durable paper qualification | 24h paper campaign against QPR PASS gate; no new paper authority | QPR readiness + R05 prereqs; paper fail-closed invariants unchanged |

Steps 1-6 are independent composition seams; the PR order above respects the R04→R05→R06 gates (R04 = steps 2+3+4, R05 = step 7 after R04, R06 = step 8). Each step is one narrow PR with additive tests; none may weaken runtime admission, authority generation bindings, or the quarantine boundary.

## 7. Contract-test plan

True-today invariants are enforced in the new additive file `tests/test_r08_composition_invariants.py` (offline, `pytest.mark.unit`, no network, pytest-socket safe). They assert: composition-root import hygiene (no sender/signer/quarantined modules), research owners not bound into composition roots (guards the audit's headline), live hard-deny at the runtime-owner level, paper fail-closed for the generic profile + resolver, resolver blocked-RPC default, runtime-authority/ capabilities truth, and catalog rows not being live connectors.

Future assertions (proposed, deliberately NOT in the test suite until the corresponding integration step lands — aspirational tests for unwired features would fail today):

- Step 1: `resolve_installed_core_v1_dependencies` with a governed transport produces simulation-capable RPC while absent env stays blocked.
- Step 2/5: materialized attempts reference `FinalizedUnsignedSolanaPlan` canonical hash; rent plan tier binding matches `rent_financing_evidence`.
- Step 3: `FlashCapitalEdge` injection changes sizing decisions only for qualified edges; stale/mismatched generation blocks.
- Step 4: quote provenance hash is carried into candidate evidence end-to-end.
- Step 6: a non-blocked draft source materializes candidates only from `DynamicUniverse` promoted identities.
- Step 8: 24h paper qualification report is produced by the existing durable service without new authorities.

## 8. Verification receipts

- Boot trace: all file:line citations above were read from the worktree at base `e2b65c0c`.
- Import-graph audit: `grep -rln` over `src/**/*.py` for each owner (dynamic_universe, intake_cadence, din_discovery, funnel/probes, flash_capital_graph, unsigned_builders, rent_sponsor_planner, qualification_campaign, correlation_ledger, relation_generators, research_economic_graph, assets.resolution, ProviderGovernance, shadow_workers, market_scale_replay, exact_cpmm_capacity, non_monotonic_sizing, multihop_solver, bank_discovery, kamino/sui/jupiter_lend reader symbols).
- New contract tests: `venv python -m pytest tests/test_r08_composition_invariants.py -v` — see PR body for exact counts (recorded at commit time).
- No network calls, no capability/config changes, no `src/` modifications.

## Parallel-audit reconciliation (post-rebase note)

A parallel R08 lane landed as PR #624 (merged): `tasks/R08_COMPOSITION_AUDIT_2026-11-14.md` + `tests/test_r08_composition_contract.py`. The two audits are complementary, not duplicate owners: #624 records the runtime-truth snapshot and composition contract tests; this report adds the full 27-owner wired-vs-library injection matrix, the typed `INTEGRATION_GAP_*` set, the 8-step composition-only integration order, and `tests/test_r08_composition_invariants.py`. File paths and test module names are disjoint; both suites pass together offline (see PR body for the combined run).
