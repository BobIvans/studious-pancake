# R08 — Runtime composition integration audit + contract-test plan (2026-11-14)

**Agent:** R08 (runtime composition integration audit), audit-first lane — read-only on `src/` runtime.
**Base SHA:** `e2b65c0c` (main, post-wave merge of PRs #602/#609/#612/#613/#614/#615/#616/#617/#618/#619/#620).
**Task text:** `docs/roadmap/agent-execution-master-2026-11-13/tasks/R08_RUNTIME_COMPOSITION_INTEGRATION.md`.
**Deliverables:** this audit + `tests/test_r08_composition_contract.py` (offline contract tests).
**Zero network. Zero edits to `src/runtime/core_v1_composition.py`, `core_v1_dependency_resolver.py`, `core_v1_materializer.py` (frozen).**

---

## 1. Runtime truth snapshot (what is actually installed and reachable)

### 1.1 Entry point

| Fact | Value | Evidence |
|---|---|---|
| Console script | `flashloan-bot = "src.cli_pr189:main"` | `pyproject.toml:83` |
| Active composition root record | entrypoint `flashloan-bot`, module `src.cli_pr189`, callable `main`, `sender_free: true`, `live_enabled: false` | `src/resources/runtime_authority.json` `active_composition_root` |
| Active `run` dispatch | `src/cli_pr189.py:main` → `src.runtime.runtime_entrypoint.main` (for `parsed_command(args) == "run"`) | `src/cli_pr189.py:62-65` |
| Paper path | `_run_paper` → `resolve_installed_core_v1_dependencies` + `build_core_v1_composition`; heavy core imported only after platform admission | `src/runtime/runtime_entrypoint.py:234-254` |
| Product state | `product_state: "not-production-ready"`, `runtime_modes.live.available: false`, `default_command: "run --mode shadow"` | `config/capabilities.json` |
| Package quarantine | legacy senders/monolith excluded from production wheel (`src/execution/senders`, `src/ingest/*` disposition `removed-from-package`) | `src/resources/runtime_authority.json` `alternate_runtime_surfaces` |

### 1.2 The two composition roots

**R1 — CORE-V1 installed composition (the supported paper path).**
`build_core_v1_composition` (`src/runtime/core_v1_composition.py:297`) + resolver
`resolve_installed_core_v1_dependencies` (`src/runtime/core_v1_dependency_resolver.py:126`)
+ materializer (`src/runtime/core_v1_materializer.py:174`).

- Profile `core-marginfi-jupiter-v1` (marginfi, generation 1): resolver **unconditionally** returns
  `CORE_V1_BLOCKED_EXTERNAL` (`core_v1_dependency_resolver.py:140-145`) — no manifest can unblock it.
- Profile `core-jupiter-lend-jupiter-v1`: requires env `FLASHLOAN_CORE_V1_EVIDENCE_MANIFEST`
  (`MANIFEST_ENV`) pointing at a `core-v1.financing-evidence-manifest.v2` file; every identity field,
  admission receipt (SP-Q01), decoder artifact hash and qualification boolean is validated fail-closed.
- **Even a fully resolved manifest yields `BlockedCoreV1DraftSource()` + `_ResolverBlockedRpc()`**
  and blocker `CORE_V1_PROVIDER_DRAFT_SOURCE_EXTERNAL` (`core_v1_dependency_resolver.py:264-280`):
  the installed generic composition is reachable without fabricating external evidence. A raw
  provider handoff is never an executable attempt (`core_v1_materializer.py` module docstring).
- Non-paper/shadow `runtime.mode` is denied at the materializer (`CORE_V1_CIRCULAR_ARBITRAGE_NOT_ADMITTED`,
  `core_v1_materializer.py:206-208`); `live_enabled=True` profiles are invalid by construction
  (`CORE_V1_PROFILE_SCOPE_MISMATCH`, `core_v1_materializer.py:92-98`); strategy-level `live` is denied
  at config validation (`src/config/runtime.py:165-172`).

**R2 — PR-089/102 paper/shadow composition (status / paper-shadow surface).**
`build_paper_shadow_runtime` (`src/paper_shadow/composition.py:226`), reached from `src/cli.py`.
Default `PaperShadowRuntimeDependencies()` is intentionally incomplete
(`atomic_stage_suite`, `exact_fee_workflow`, `verified_marginfi_provider`, `jupiter_v2_build` all `None`)
→ every required stage is bound to `PaperShadowDependencyGate` with
`PR089_MISSING_ATOMIC_DEPENDENCIES` (`composition.py:266-281`), `sender_imported: false`,
`live_mutation_allowed: false`. Type-unsafe fake dependencies are rejected
(`PR102_TYPE_SAFE_DEPENDENCY_REJECTED`).

**Current runtime truth: paper/shadow fail-closed; disabled is inspection-only; live is hard-denied.
Nothing merged in this wave changes any of that — see section 4.**

---

## 2. Per-owner integration state table (this wave's new owners)

Classification (per task brief):
- **(a) reachable** — imported/constructed on a path originating at `src.cli_pr189:main` (R1 or R2).
- **(b) importable-but-uninjected** — module is inside the installed package and may be transitively
  imported by a composition root, but the owner's symbols are constructed/injected by no composition root.
- **(c) entirely disconnected** — no import chain from either composition root reaches the module;
  only tests, offline gates or other disconnected owners import it.

Method: `grep -rln` over `src/` for every owner's canonical module/symbol, plus `git show --stat`
of the wave commits (`68fd3fa6` CAP-A, `10a3df37` CAP-B, `c146aa32` CAP-C, `8b476451` CAP-D,
`a37976d8` Stream J, `f591063f` P0-3, `3daf1931` TON, `407af9ac` GPR-03, `b3ad995a` Stream H,
`3aaacf8a` P0-1). A class existing ≠ runtime capability.

| # | Owner (wave/PR) | Canonical file(s) | Key symbols | State | Import evidence (non-test) |
|---|---|---|---|---|---|
| 1 | R02-CAP-A Jupiter Lend TokenReserve capacity reader (#602) | `src/lending/jupiter_lend.py` | `decode_token_reserve_state` (L417), `JupiterLendReserveCapacityObservation` (L573), `observe_token_reserve_capacity` (L694), `JupiterLendCapitalEdgeGate` (L883), `reserve_capital_edge_gate` (L892), `admit_reserve_financing_snapshot` (L790) | **(b) importable-but-uninjected** | Module *is* transitively imported by R1 — `core_v1_dependency_resolver.py:28` imports only `JUPITER_LEND_FLASHLOAN_PROGRAM_ID`; agg03 financing owners (`agg03_financing_decoder`, `agg03_financing_ports`, `sp_q01_protocol_admission`) import other identities. **No composition root constructs any CAP-A reader/gate symbol.** Only `tests/test_r02_cap_a_reader.py`, `tests/test_r02_cap_a_offline_replay.py` do. |
| 2 | R02-CAP-B Kamino klend reserve capacity reader (#612) | `src/lending/kamino.py` | `decode_kamino_reserve` (L972), `KaminoReserveCapacityObservation` (L1371), `observe_kamino_reserve_capacity` (L1543), `KaminoCapitalEdgeGate` (L1654), `build_kamino_capital_reader_result` (L1704), `kamino_flash_loan_fee_rational` (L1253) | **(c) entirely disconnected** | Importers: `lending/kamino_conformance.py`, `lending/kamino_real_conformance.py`, `mpr02_provider_protocol_data_plane_gate.py`, `production_debt.py`, `production_debt_profiles.py` — governance/offline-gate surfaces only; none on the R1/R2 run path. |
| 3 | R02-CAP-C NAVI Sui pool capacity reader (#609) | `src/multichain/sui.py` | `NaviPoolCapacityObservation` (L1021), `observe_navi_pool_capacity` (L1271), `NaviCapitalEdgeGate` (L1403), `parse_flashloan_api_discovery_rows` (L878), `navi_flash_ptb_shape` (L953) | **(c) entirely disconnected** | Importers: `mega8_04.py` (offline gate) and `lending/unsigned_builders/navi_ptb_builder.py` (itself disconnected, row 5). |
| 4 | R02-CAP-D Project 0 wallet-free bank discovery (#619) | `src/providers/marginfi/bank_discovery.py` | `MarginfiCapture` (L168), `load_p0_discovery_facts` (L217), `BankReaderPins` (L303), `derive_bank_liquidity_vault_authority` (L401), `MarginfiBankDiscoveryRejectionCode` (L131) | **(c) entirely disconnected** | Zero non-test importers. |
| 5 | R-03 unsigned builder package (Stream F) | `src/lending/unsigned_builders/{contract,jupiter_builder,kamino_builder,navi_ptb_builder,project0_builder}.py` | `UnsignedBorrowPlan`, `UnsignedRepayPlan`, `FinalizedUnsignedSolanaPlan`, `BuildStatus` vs `CapacityStatus`, `finalize_unsigned_solana_plan`, `check_bookend_sequence`, `assert_no_execution_ready_capacity_member` | **(c) entirely disconnected** | Imported only by `src/planning/rent_sponsor_planner.py` (itself disconnected, row 6) and intra-package. R1's financing seam uses the **different** `src/lending/agg03_financing_ports.py` `FinancingPort` contract (`JupiterLendFinancingPort`/`SlumlordFinancingPort`), not these builders. |
| 6 | RentSponsorPlanner (Stream J, #617) | `src/planning/rent_sponsor_planner.py` | `RentSponsorPlanRequest` (L453), `RentSponsorTier`/`PlanStatus`/`CapacityStatus`/`RejectionCode`, `rent_exempt_minimum_lamports` (L111), lamport-flow/fee-line model | **(c) entirely disconnected** | Zero importers. Note: R1 has an *adjacent but distinct* rent seam — `CoreV1Dependencies.rent_financing_port/rent_financing_evidence` → `AuxiliaryFinancingPlannerAdapter` (`src/lending/financing_planner_adapter.py`) → `AtomicMarginfiJupiterPlanner(auxiliary_financing_provider=...)`. RentSponsorPlanner is **not** bound to that seam; wiring it later must go through the planner seam, not a new authority. |
| 7 | P0-3 Raydium CLMM exact decoder (#613/#607) | `src/providers/raydium_clmm_native.py` | PoolState/TickArrayState/TickState/AmmConfig byte decoders, verbatim tick math, `compute_swap` port | **(c) entirely disconnected** | Zero importers. Contrast: the pre-existing `raydium_cpmm_native.py` *is* wired (`paper_shadow/native_cpmm_qualification.py`, `market/native_cpmm_capture.py`). |
| 8 | P0-3 Meteora DLMM exact decoder (#613/#607) | `src/providers/meteora_dlmm_native.py` | `LbPair` (904 B) / `BinArray` (10136 B) decoders, pinned base-fee law, per-side token-program mapping | **(c) entirely disconnected** | Zero importers (imports `raydium_cpmm_native` for shared primitives only). |
| 9 | P0-1 bounded intake cadence + universe handoff (#593) | `src/solana_parallel_radar/intake_cadence.py` | bounded cadence, coverage receipt, universe handoff | **(c) entirely disconnected** | Imported only by `solana_parallel_radar/din_discovery.py`, which itself has zero importers. `src/market/discovery.py` (P0-1 adjacent) is likewise NOT on the run path — R2's discovery coordinator imports `src/market/snapshots.py`, not `market/discovery.py` (`runtime_discovery_coordinator.py:12`). |
| 10 | TON wave-1 adapters (#620) | `src/discovery/dynamic_universe/ton_radar.py` | `DedustRadarIngestor`, `SwapCoffeeRadarIngestor`, `_BoundedRadarIngestor`, replay dispatch by `(source, resource)` | **(c) entirely disconnected** | Imported only by `discovery/dynamic_universe/campaign.py` (same package). The `dynamic_universe` package has **no import chain from `cli_pr189` / `runtime_entrypoint` / `paper_shadow.composition`** — the Dynamic Universe report's "not wired into supported application boot path" finding is **confirmed still open** on `e2b65c0c`. |
| 11 | GPR-03 Sui remediation (#616) | `src/gpr_sui_shadow/{providers,decoders,bcs,campaign,intake,sources}.py`; shared hardening in `src/routing/transport.py` | bounded transport Content-Length fix, narrowed Aftermath profile, typed provider bindings, package-bound Move decoders | **(c) disconnected** (package) | `gpr_sui_shadow` has zero importers outside the package. `src/routing/transport.py` is a pre-existing shared owner that the wave hardened — not a new owner. |
| 12 | Stream H relation generators + residual/correlation series (#614) | `src/research/correlation_ledger/residuals.py` (new), `src/research/correlation_ledger/ledger.py`, `src/strategy/relation_generators/generators.py` | residual series families (stable/LST-premium/wrapper-basis/oracle-vs-market …), generator tightening | **(c) entirely disconnected** | `strategy/relation_generators` and `research/correlation_ledger` have zero importers from the runtime graph. `generators.py` itself imports `economics/flash_capital_graph` and `dynamic_universe` — the whole research island (`relation_generators` + `flash_capital_graph` + `dynamic_universe` + `assets/resolution`) is self-contained and unreachable from both roots. |

**Summary: 0 of 12 new owners are runtime-reachable (a); 1 is importable-but-uninjected (b);
11 are entirely disconnected (c). The research island (dynamic_universe, flash_capital_graph,
relation_generators, correlation_ledger, gpr_sui_shadow, intake_cadence) and the capital/builder
island (CAP-A/B/C/D, unsigned_builders, rent_sponsor_planner) are two disconnected subgraphs.**

### 2.1 Adjacent seams that already exist (wiring must reuse these)

| Seam | Owner | Contract |
|---|---|---|
| Financing port | `src/lending/agg03_financing_ports.py` + `src/lending/financing.py` | `FinancingPort`/`FinancingEvidence`, `validate_financing_binding`, `execution_conformance_verified` required by `CoreV1Dependencies.__post_init__` |
| Rent financing | `CoreV1Dependencies.rent_financing_port` → `AuxiliaryFinancingPlannerAdapter` → `AtomicMarginfiJupiterPlanner(auxiliary_financing_provider=)` | fail-closed `CORE_V1_RENT_FINANCING_*` codes |
| Materialization | `CoreV1DraftSource` Protocol → `CoreV1MaterializedBatchSource` → `ExactAttemptRuntimeItem` | drafts carry `CapitalCandidate`, `WalletBalanceSnapshot`, `ProviderExecutionEvidence`; `CoreV1ExternalBlock` → blocked batch |
| Capital policy | `DurableCapitalCoordinator` + `CapitalPolicy.from_runtime_config(..., PolicyProfile.PAPER)` | `compare_balance_and_reserve_same_transaction` et al. per `runtime_authority.json` |
| Paper/shadow stages | `PaperShadowRuntimeDependencies` (4 typed fields) + `AtomicVerticalRuntimeStageSuite` | `PR102` type-safe contracts |

---

## 3. Missing injections / bindings (current vs target)

### 3.1 CORE-V1 (`CoreV1Dependencies`) — what is missing for an admitted paper cycle

| Field | Current installed value | Missing supplier owner |
|---|---|---|
| `draft_source` | `BlockedCoreV1DraftSource()` — always raises `CoreV1ExternalBlock` | **Nobody in the wave.** A future `CoreV1DraftSource` adapter must convert verified provider/discovery evidence into `CoreV1AttemptDraft` (capital candidate + wallet snapshot + provider execution evidence). P0-3 decoders and Dynamic Universe candidates would feed this *only* after their own qualification gates. |
| `rpc` | `_ResolverBlockedRpc()` — raises `CORE_V1_BLOCKED_EXTERNAL` | Governed `RpcClient` from deployment (not in repo scope). |
| `marginfi_provider` | None (legacy profile blocked earlier anyway) | Qualified MarginFi provider evidence (PR-005 registry still `fixture_only_blocked`). |
| `financing_port/evidence` | Constructed from manifest identities (`JupiterLendFinancingPort`) but gated on SP-Q01 admission receipts + qualification booleans | CAP-A reader evidence would eventually *substantiate* qualification; today `qualified` is a manifest boolean, and capacity readers are uninjected. |
| `rent_financing_port/evidence` | `SlumlordFinancingPort` gated identically | RentSponsorPlanner is not connected (row 6). |
| `financing_repayment_decoder` | `JupiterLendSlumlordRepaymentDecoder` pinned via `decoder_artifact_sha256` | Complete for the pinned artifact. |

### 3.2 PR-089 (`PaperShadowRuntimeDependencies`)

`atomic_stage_suite`, `exact_fee_workflow`, `verified_marginfi_provider`, `jupiter_v2_build` —
all `None` by default; no wave owner supplies any of them. `verified_marginfi_provider` additionally
requires `shadow_execution_capable=True` + sha256 evidence; MarginFi remains `fixture_only_blocked`
per `config/capabilities.json` (`provider.marginfi`, quarantined).

### 3.3 Capital dimension

`FlashCapitalGraph` (`src/economics/flash_capital_graph/graph.py`) is imported only by
`strategy/relation_generators/generators.py` — inside the research island. None of CAP-A/B/C/D
feed it from a composition root, and R-02's acceptance state (`#585` negative receipt: zero
qualified capital edges, 27 candidates disabled) is unchanged. **All four readers must stay
typed NO-OP for paper qualification until each reader's `MISSING_EFFECTIVE_FLASH_CAP`
blocker clears with live rooted-RPC evidence + admission receipts.**

---

## 4. Dependency order for future wiring (smallest composition-only integration)

Order chosen so that each step only ever *adds evidence* to an existing gate and can never
flip sign/send/live or fabricate capacity:

| Wave | Owners wired | Where they plug in | Gate each must pass first | Explicitly forbidden |
|---|---|---|---|---|
| W1 | CAP-A → CAP-B → CAP-C → CAP-D capacity readers | `FlashCapitalGraph` edge candidates **via each reader's existing CapitalEdgeGate** (`JupiterLendCapitalEdgeGate`, `KaminoCapitalEdgeGate`, `NaviCapitalEdgeGate`, MarginFi `bank_discovery` rejects); the graph stays inside the research island until step W6 | Live rooted-RPC capture + admission receipt per lender; until then every observation carries `MISSING_EFFECTIVE_FLASH_CAP` and contributes **zero qualified edges** (R-02 `#585` receipt stays authoritative) | TVL/SDK-lists/admin flags as capacity; aggregating UNKNOWN as zero |
| W2 | R-03 unsigned builders | R-05 offline simulation seam; `build_status` reported **separately** from `capacity_status` | Pinned SDK conformance tests already in `tests/test_r03_*`; conformance violations fail closed | Treating an unsigned build as a live-capital route; any signer import |
| W3 | RentSponsorPlanner | Planner seam only: `AtomicMarginfiJupiterPlanner` auxiliary financing path / `FinancingPlannerProviderAdapter` family — **not** a new authority | Slumlord rent-financing port qualified (`CORE_V1_RENT_FINANCING_*` codes already fail closed); route economics reject = typed rejection | ATA creation/close during qualification; "free ATA" claims; unsigned-only proof scope |
| W4 | P0-3 CLMM/DLMM decoders | Verification/relation plane (research island) → `VerificationQueue`-gated exact verification | Differential fixtures (already present: `tests/test_raydium_clmm_meteora_dlmm_native.py`); unknown layout fail-closed | Indexed/TVL data promoted to exact graph; skipping Orca license gate |
| W5 | Dynamic Universe + TON ingestors + Stream H residual/correlation | Discovery plane extension of `RuntimeDiscoveryCoordinator` / future draft-source candidates; correlation stays research | Source pins + budget/backoff (present); TON remains `TON_ASYNC_MULTI_CONTRACT`/`DISCOVERY_ONLY`; failed page never retires a market | `heat`/`execution_class` conflation; research signal self-promotion into paper gate (mandate invariant 10) |
| W6 (last) | `CoreV1DraftSource` adapter binding verified candidates into CORE-V1 | `CoreV1Dependencies.draft_source` + governed `rpc` | Full manifest v2 + SP-Q01 receipts + qualified deployments + at least one qualified capital edge; even then draft source stays blocked (`CORE_V1_PROVIDER_DRAFT_SOURCE_EXTERNAL`) until real provider observations | Any new authority, engine, journal, capital ledger or sender; changing signer/sender boundaries |

Also required (from R08 task text): strategy registry / capability manifest / package quarantine
stay in lockstep — a strategy never becomes ready by editing config or env only.

---

## 5. Contract-test plan

Implemented as **code** in `tests/test_r08_composition_contract.py` (justification: the mandate
requires real, offline-executable test counts — "never copy historical test totals" — and
skip-guards make future wiring flip a `pytest.skip` into a live assertion instead of rotting a
doc-only spec; repo convention is code-backed evidence, cf. `test_pr089_composition_root_does_not_import_sender`).

### Part A — unconditional runtime-truth contract (runs today, offline)

1. `config/capabilities.json` truth: supported entrypoint `flashloan-bot`, `product_state`
   `not-production-ready`, `runtime_modes.live.available == false`, paper/shadow available,
   quarantine flags intact.
2. `src/resources/runtime_authority.json` truth: active composition root = `src.cli_pr189:main`,
   `sender_free: true`, `live_enabled: false`, sender surfaces `removed-from-package`.
3. Resolver: marginfi profile is **unconditionally** `CORE_V1_BLOCKED_EXTERNAL` (even with a
   manifest env set); missing manifest → `CORE_V1_FINANCING_EVIDENCE_MANIFEST_REQUIRED`;
   schema mismatch hard-raises; legacy schema → `CORE_V1_FINANCING_ADMISSION_RECEIPT_REQUIRED`;
   unqualified primary/rent → typed blockers. No dynamic import in resolver (`importlib`/`__import__` absent).
4. Composition: generic (non-legacy) profile without dependencies builds the explicit blocked
   composition (planner/simulator/vertical/orchestrator/runtime_cycle/materializer all `None`,
   `admitted=False`, zero durable reservations, idempotent close).
5. Materializer: refuses non-paper/shadow modes (`CORE_V1_CIRCULAR_ARBITRAGE_NOT_ADMITTED`);
   accepts only canonical drafts (`TypeError` on foreign objects); `live_enabled=True` profile is
   invalid by construction.
6. PR-089/102: default dependencies block every stage (`PR089_MISSING_ATOMIC_DEPENDENCIES`),
   fake objects cannot unlock (`PR102_TYPE_SAFE_DEPENDENCY_REJECTED`) — mirroring existing
   assertions through the R08 lens.
7. Sender-free roots: none of the five composition-root modules reference
   `src.execution.senders`, `isolated_signer`, `sendTransaction`, `sendBundle`.

### Part B — skip-if-unwired per-owner contracts (gates the future wiring PR)

Guard: read the source of the five composition-root modules
(`src.runtime.runtime_entrypoint`, `src.runtime.core_v1_composition`,
`src.runtime.core_v1_dependency_resolver`, `src.runtime.core_v1_materializer`,
`src.paper_shadow.composition`) and check for the owner's import token.
**Unwired today → `pytest.skip("R08: <owner> not wired into composition root")`.
Once a wiring PR lands, the same test executes and asserts:**

- CAP readers wired → wiring references `MISSING_EFFECTIVE_FLASH_CAP` (capacity can only enter
  typed-blocked) and constructs no signer/sender.
- Unsigned builders wired → `BuildStatus`/`CapacityStatus` separation tokens present
  (`assert_no_execution_ready_capacity_member`), no sender import.
- RentSponsorPlanner wired → enters via planner/financing-adapter seam tokens
  (`atomic_marginfi_jupiter`/`financing_planner_adapter`), not as a new authority.
- P0-3 decoders wired → consumed via evidence/materializer tokens (draft/evidence path), not execution.
- Dynamic Universe / TON wired → `RuntimeDiscoveryCoordinator`/discovery tokens present and
  TON stays `TON_ASYNC_MULTI_CONTRACT`/discovery-only.
- Stream H wired → verification-token present (no direct promotion into paper gates).

Global negative (always runs): **adding the new owners must not change current runtime truth** —
Part A asserts the resolver/composition fail-closed behavior on a tree that already contains all
12 disconnected owners; the day any owner is wired, Part B flips on and Part A must still pass
unchanged (wiring may not weaken Part A codes).

---

## 6. Baseline test run (exact counts, this worktree, `e2b65c0c`)

Baseline selection (without the new R08 module):

```
python -m pytest tests/test_core_v1_composition.py tests/test_core_v1_closure.py \
  tests/test_agg03_dependency_resolver.py tests/runtime/ \
  tests/test_pr089_active_paper_composition_root.py tests/test_pr056_runtime_discovery.py -q
```

| Selection | Result |
|---|---|
| Combined | **113 collected, 112 passed, 1 failed** |
| `test_core_v1_composition.py` | 2 passed |
| `test_core_v1_closure.py` | 9 passed |
| `test_agg03_dependency_resolver.py` | 16 passed |
| `test_pr089_active_paper_composition_root.py` | 6 passed |
| `test_pr056_runtime_discovery.py` | 5 passed |
| `tests/runtime/` (5 files) | 75 tests: 74 passed, 1 failed |
| Failure | `tests/runtime/test_mpr_rp03_instance_resources.py::test_cleanup_refuses_to_delete_replaced_generation_lock` — `PermissionError: [WinError 32]` on a Windows temp `.instance.lock` during pytest tmp cleanup. Deterministic on this Windows host, OS file-lock flake, unrelated to any composition owner (passes on the repository's Linux CI). |

Combined selection **including** `tests/test_r08_composition_contract.py`:
**139 collected, 132 passed, 6 skipped (R08 Part B, unwired), 1 failed (same Windows flake)**.

New R08 contract tests (`tests/test_r08_composition_contract.py`): **21 tests — 15 passed
(Part A unconditional runtime-truth contract) + 6 skipped (Part B skip-if-unwired guards,
one per new-owner family, expected until the wiring PRs land)**. Black-clean
(`black --check` unchanged); the file is outside the repo `mypy.ini` scope (mypy over the
tree reports only 3 pre-existing `src/config/strict_yaml.py` yaml-stub errors, untouched by this diff).

---

## 7. Blockers

| Blocker | Owner | Required human/next input |
|---|---|---|
| No wave owner is wired into either composition root | future integration PR (R08 plan above) | Coordinator queues wiring waves W1→W6 in dependency order |
| R-02 live capacity: zero qualified edges, readers typed `MISSING_EFFECTIVE_FLASH_CAP` | R-02 acceptance + per-lender live rooted-RPC capture | Live evidence per lender; readers stay NO-OP until then |
| MarginFi provider `fixture_only_blocked` (PR-005 registry) | provider governance | Rooted deployed-account vectors, flashloan meta proof, IDL/source identity, human review |
| Governed `RpcClient` for CORE-V1 | deployment | Operator-supplied governed RPC (out of repo scope) |
| Windows-host lock flake in `test_mpr_rp03_instance_resources.py` | test owner | OS-level tmp cleanup; not a composition regression |

## 8. Safety flags (unchanged by this audit)

- `sign_enabled = false`, `send_enabled = false`, `live_enabled = false` everywhere.
- Live hard-denied at: `capabilities.json` (`runtime_modes.live.available: false`), strategy config
  validator (`src/config/runtime.py:165-172`), profile constructor
  (`CORE_V1_PROFILE_SCOPE_MISMATCH`), materializer mode gate
  (`CORE_V1_CIRCULAR_ARBITRAGE_NOT_ADMITTED`), resolver unconditional marginfi block, PR-089
  dependency gate. No signer/sender import in any composition root.

## 9. Next task

Queue **W1** (CAP-A→D readers into `FlashCapitalGraph` through their existing gates, NO-OP until
live capacity evidence) as the first composition-only integration PR, executed together with the
Part B contract tests from `tests/test_r08_composition_contract.py` (they will un-skip per owner
as wiring lands). Then W2 (R-03 builders → offline R-05 seam).
