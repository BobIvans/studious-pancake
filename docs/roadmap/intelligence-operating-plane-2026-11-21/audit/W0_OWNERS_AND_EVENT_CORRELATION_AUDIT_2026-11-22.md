# OCA-W0 — Current owners and event-correlation audit

- **Date:** 2026-11-22
- **Lane:** OCA-W0 (WORK_PACKAGE_MATRIX.json, PR #666 head `6214202b9604766b5483be4607db9bc7f5fc61e3`)
- **Base main SHA:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`
- **Branch:** `codex/oca-w0-owners-audit-2026-11-22`
- **Mode:** AUDIT_ONLY — read-only inspection; no code, config or canonical-owner changes.
- **Scope guard:** this PR writes only `docs/roadmap/intelligence-operating-plane-2026-11-21/audit/`. PR #666's own files are not edited. Open PRs #672–#676 write scopes are disjoint from this lane (verified 2026-11-22; see §7).
- **Interpreter/commands:** Python 3.13.15 (`.venv`); evidence greps run with `grep -rn` over `src/` on the pinned checkout; test baseline collected with `pytest --collect-only -q --disable-socket --allow-unix-socket`.

## 1. Purpose

Establish the current canonical-owner inventory and the real state of the operation-event correlation chain before W0B builds the deterministic repo graph. Every capability claim below is traced to files/tests on the pinned SHA. Statuses use the repo evidence vocabulary; `UNKNOWN` is never zero.

## 2. Canonical-owner inventory (P0 owners)

| # | Owner | Files | Key symbols | Tests | Status |
|---|---|---|---|---|---|
| 1 | AGG-02 raw payload journal | `src/agg02/storage.py` (+ `capital.py`, `composition.py`, `contracts.py`, `graph.py`, `historical_membership.py`, `source_budget.py`, `transaction_formats.py`) | `DurableRawJournal`, `JournalReceipt`, `JournalCursor`, `GapRecord`, `DatasetManifest`, `AnalyticalDatasetPublisher`, `DatasetReplayReader` | `tests/test_agg02_market_data_capital.py` | IN_MAIN_VERIFIED |
| 2 | MarketObservation (normalized facts) | `src/market/observations.py` | `MarketObservationV2`, `ObservationGeneration`, `SourceCursor`, `ObservationWatermark`, `CompletenessPolicy`, `MarketSnapshotSource`, `RecordedSnapshotSource` | `tests/market_data_evolution/test_market_data_evolution.py` | IN_MAIN_VERIFIED |
| 3 | ObservabilityStore / EventEnvelope | `src/observability/store.py`, `src/observability/events.py`, `src/observability/authoritative_store_pr195.py` | `ObservabilityStore`, `EventEnvelope`, `make_event`, `AuthoritativeObservabilityStore` | `tests/observability/*`, `tests/test_pr132_observability_integrity.py`, `tests/test_pr167_observability_governance.py`, `tests/test_pr195_authoritative_observability_store.py`, `tests/test_pr198_immutable_observability_export.py`, `tests/test_pr201_observability_readiness.py`, `tests/test_pr046_canary_observability.py` | IN_MAIN_VERIFIED (store/export/replay) — **producer chain MISSING** (§4) |
| 4 | MarketEpisode | `src/market_data_evolution/contracts.py` | `MarketEpisode` (alt record `MarketEpisodeRecord` in `src/mechanism_discovery/pr356_contracts.py`) | `tests/market_data_evolution/` | IN_MAIN_VERIFIED |
| 5 | External contracts / provider governance | `src/external_contracts/registry.py` (+ `admission.py`, `conformance.py`, `drift.py`, `models.py`, `policy.py`, `updater.py`, `provider_protocol_b1.py`, `cli.py`, `cli_pr189.py`), `src/provider_governance/` | `ExternalContractRegistry`, `ProviderEntitlement`, `AdmissionRequest` | `tests/external_contracts/` | IN_MAIN_VERIFIED |
| 6 | AssetResolver | `src/assets/resolution/resolver.py` | `AssetResolver` (Protocol) | `tests/test_dynamic_asset_resolution.py` | IN_MAIN_VERIFIED |
| 7 | DynamicUniverse | `src/discovery/dynamic_universe/universe.py` (+ `ton_radar.py`) | `DynamicUniverse` | `tests/test_dynamic_universe.py`, `tests/test_ton_radar_dynamic_universe.py` | IN_MAIN_VERIFIED |
| 8 | ResearchEconomicGraph | `src/research_economic_graph/graph.py` | `ResearchEconomicGraph`, `SolanaResearchAdapter` | `tests/test_gpr01_research_economic_graph.py` | IN_MAIN_VERIFIED |
| 9 | UniversalArbitrageGraph | `src/strategy/arbitrage_graph.py` | `UniversalArbitrageGraph`, `AssetNode` | `tests/test_shadow_arbitrage_graph.py` | IN_MAIN_VERIFIED |
| 10 | CorrelationLedger | `src/research/correlation_ledger/ledger.py` | `CorrelationLedger` | `tests/test_dynamic_correlation_ledger.py` | IN_MAIN_VERIFIED |
| 11 | FlashCapitalGraph | `src/economics/flash_capital_graph/graph.py` | `FlashCapitalGraph`, `FlashCapitalEdge`, `LiveCapitalProvider` | `tests/test_dynamic_flash_capital.py` | IN_MAIN_VERIFIED |
| 12 | Strategy registries | `src/strategy/registry.py`, `src/strategy/strategy_contract.py`, `src/inventory/research.py`, `src/research/pr357_contracts.py`, `src/mechanism_discovery/pr356_contracts.py`, `src/release_gate/pr353_strategy_closure.py` | `StrategyRegistry`, `StrategyContractV1`, `StrategyFamily`, `StrategyEvidenceCard` | `tests/strategy_evolution/`, `tests/research/`, `tests/mechanism_discovery/`, `tests/test_agg13_inventory_platform.py` | IN_MAIN_VERIFIED. No `StrategyIdea`/`StrategyVersion` classes exist anywhere (grep, 0a0c8ad9) — W0B labels join via these registries, not new classes |
| 13 | Market source catalog | `src/market/source_catalog.py`, `src/resources/market_source_catalog.json` | source catalog rows (37 catalog candidates; rows are not active connectors) | covered by market-data gates | IN_MAIN_VERIFIED |
| 14 | Runtime composition/authority | `src/runtime/core_v1_composition.py`, `src/runtime/core_v1_dependency_resolver.py`, `src/durability/unified_authority_pr02.py`, `src/economics/durable_reservations.py` | runtime composition + capital authority | focused gates | IN_MAIN_VERIFIED |
| 15 | Repo-intel primitives (CTX-01/CTX-02) | `src/intelligence/` (31 flat modules) | `repo_snapshot.py`, `repo_source.py`, `repo_groups.py`, `repo_manifest.py`, `repo_coverage.py`, `repo_history.py`, `context_pack.py`, `context_archive.py`, `context_benchmark.py`, `common.py`, `cli.py` | `tests/intelligence/` | IN_MAIN_VERIFIED. **Does not yet contain:** `repo_graph/`, `provider_contracts/`, `strategy_requirements/`, `temporal_ontology/`, `incremental_engine/`, `agent_access/`, `verification/`, `universal_data_plane/`, `logsites/`, `operation_context/` (grep: zero matches, 0a0c8ad9) |
| 16 | Authority/owner map | `src/authority_map.py` + `scripts/validate_authority_map.py` | machine-readable authority and queue contract (verify_repo gate) | gate script | IN_MAIN_VERIFIED |

There is no `src/ownership/` package and no `CanonicalOwner` class; the string field `canonical_owner` appears only in `src/strategy/conflict_scheduler.py:182`, `src/release_gate/pr353_strategy_closure.py:81/156`, and `src/canonical_readiness.py:475/503`. The doc-level owner index (`PROJECT_KNOWLEDGE_BASE_MAP.md`) and `src/authority_map.py` are the closest registries; W0B must join canonical labels through them, not invent a second owner registry.

## 3. Cross-owner join matrix

Statuses: PRESENT (working join with evidence), PARTIAL (join exists with a documented gap), MISSING (no join), UNKNOWN (not verifiable from this audit's evidence set).

| Join | Status | Evidence / notes |
|---|---|---|
| AGG-02 → MarketObservation | PARTIAL | `src/intelligence/episode_builder.py` consumes `MarketObservationV2`+`MarketEpisode`; `AnalyticalDatasetPublisher`/`DatasetReplayReader` publish/replay exact projections. Cursor→watermark promotion path is owned by `src/market/observations.py` (`SourceCursor`, `ObservationWatermark`) |
| MarketObservation → MarketEpisode | PRESENT | `MarketEpisode` builder contract in `src/market_data_evolution/contracts.py`; point-in-time stage features in `episode_builder.py` |
| Strategy → Provider/data requirements | PARTIAL | `StrategyContractV1` typed contract exists; no `StrategyDataRequirement`/CompatibilityEvaluator (W14 scope). `provider_contracts` appears only as dict keys in `src/policy_admission_pr147.py`, `src/pr198_sender_free_qualification_v3.py`, `src/release_gate/production_paper_qualification.py`, `src/release/rollback.py` |
| Provider catalog → adapters | PARTIAL | `src/market/source_catalog.py` + 37-row JSON catalog; rows are catalog entries, not active connectors; adapters live under `src/providers/`, `src/lending/`, `src/gpr_sui_shadow/` with per-provider gates |
| Providers → flash capital capacity | PARTIAL | `FlashCapitalGraph` reader contracts (Project0/Kamino/NAVI/DeepBook/Scallop); per TASK_INDEX all effective capacity remains UNKNOWN until governed live evidence |
| Decisions → outcomes (operation events) | MISSING | see §4: no production event producer; `ObservabilityStore` has no wired producer callsite |
| EventEnvelope → correlation across owners | MISSING | `correlation_id`/`trace_id` fields exist on the envelope; with zero producers, no cross-owner operation correlation is observable today |
| Strategy → tests | PARTIAL | `repo_groups.attach_tests_and_contracts` attaches tests by import graph; no stable symbol/callsite IDs (W3) |
| Repo snapshot → context packs | PRESENT | `repo_snapshot.start_snapshot` → `context_pack.build_context_pack` (modes WHOLE_REPO_INDEXED/INTERCONNECTED_FILES/RUNTIME_PATH/TEST_IMPACT/TECH_DEBT/DELTA, budget + continuation) |
| Graph derivation → canonical registries | MISSING | no derived symbol graph exists yet; W0B creates it as a derived read-only view |

## 4. EventEnvelope trace (producer → store → export → replay)

Evidence gathered on the pinned SHA with `grep -rn ... src/ --include="*.py"`:

- `make_event(` — **zero non-definition callsites**. The only occurrence is the definition body itself, `src/observability/events.py:43–46`.
- Defaults at `src/observability/events.py:46`: `runtime_id="test-runtime"`, `producer_code_version="unknown"`, `config_checksum="unknown"` — every hypothetically-produced event would carry test-runtime/unknown provenance.
- `EventEnvelope(` — direct construction found only at `src/observability/cross_plane_pr196/reconciler.py:412` (cross-plane reconciler projection, not a runtime producer).
- `RawEventEnvelope(` — `src/data_plane/external_datasets.py:173`, `src/research/pr358_integrated.py:97` (distinct type; external-dataset ingest evidence, not operation events).
- `ObservabilityStore(` / `AuthoritativeObservabilityStore(` — instantiated only in `src/observability/authoritative_store_pr195.py:41,51,75` and the replay CLI `src/observability/replay.py:131`.
- Read side exists: `archive_claims.py`, `archive_verify.py`, `export.py`, `metrics.py`, `replay.py`.

**Conclusion:** the chain producer→store→export→replay is store-complete and read-complete but **producer-MISSING**. No verified production producer callsite exists on 0a0c8ad9. A real-time operation work log cannot be claimed today; this is the recorded blocker for OCA-W2 (OperationEpisode projection) and OCA-W10 (runtime capture), and the runtime dimension of `task_context` must report `UNAVAILABLE` until W10 wires producers. Static graph edges stay `CALLS_STATIC`; no `RUNTIME_OBSERVED` claims are possible.

## 5. CLI / test baseline (exact receipts, 2026-11-22)

- CLI planes (`src/intelligence/cli.py`): `campaign run`; `repo scan|status|benchmark|coverage|export|delta|archive|backup|restore`; `storage status|forecast|retention-dry-run|compact|prune|rollups|pressure`; `report build|bundle|compare`; `laya triage-observations|triage-episodes|score-repo`. Repo-scan SQLite index: `<snapshot>/index.sqlite`.
- Other console entry points relevant to owners: `flashloan-contracts` (`src.external_contracts.cli_pr189:main`), `flashloan-connections` (`src.provider_governance.cli:main`), `flashloan-bot`, `flashloan-checks`, `flashloan-release-evidence`, `flashloan-external-resources`, `flashloan-bot-healthcheck`.
- Test baseline: `pytest --collect-only` over `tests/observability`, `tests/test_pr195_authoritative_observability_store.py`, `tests/intelligence` → **64 tests collected** (Python 3.13.15, markers `not live and not manual`, socket-disabled).
- Repo-wide gate: `scripts/verify_repo.py` (pip check → quality_gate → authority-map validation → package smoke → 29 lane verifiers → 22 focused pytest files → full offline suite → clean-tree check). No numeric test-count gate.

## 6. Gap priority report (feeds W0B/W1/W3/W10)

| P | Gap | Owner lane | Note |
|---|---|---|---|
| P0 | No production EventEnvelope producer callsite; test-runtime/unknown provenance defaults | W10 (after W1/W3) | blocks operation correlation, W2 projection, runtime dimension of context API |
| P0 | No deterministic repo graph / stable symbol IDs / task_context–expand_context | W0B | extend CTX primitives; no second snapshot owner |
| P1 | No canonical-owner registry module (owner map is doc-level + `authority_map.py`) | W0B labels | join via `authority_map.py` + canonical registries |
| P1 | `repo_source.analyze_source` lacks qualified names, enclosing scope, call edges, resolution statuses | W0B | stdlib-AST only; other languages stay UNSUPPORTED-with-reason |
| P1 | No golden-question retrieval benchmark corpus | W0A | `benchmarks/intelligence/` is new |
| P1 | No stable callsite/logsite IDs | W3 | rename-safe IDs; no LLM in hot path |
| P2 | No `StrategyDataRequirement`/CompatibilityEvaluator | W14 | UNKNOWN must not reach QUALIFIED |
| P2 | `provider_contracts` only as string keys; no ProviderCapabilityRegistry/DataContract | W13 | coordinate with open PR #672 schema gate |
| P2 | No typed temporal ontology / bitemporal as-of queries | W15 | depends on W1/W2/W3/W13/W14 |
| P2 | No unified cross-store read-only facade/MCP | W11 | reuse; #673 data-catalog projection is an open overlapping lane — reconcile before merging W11 |

## 7. Open-PR reconciliation receipts (verified 2026-11-22)

| PR | Title | Head | Base | State | Overlap with this lane |
|---|---|---|---|---|---|
| #666 | intelligence operating plane design (renewed) | `6214202b` | `0a0c8ad9` | OPEN draft, docs-only (16 files under `docs/roadmap/intelligence-operating-plane-2026-11-21/`) | design source; this PR only adds new files under `audit/` — no file overlap |
| #672 | schema version compatibility gate | `55d2ae37` | `0a0c8ad9` | OPEN | writes `src/contracts/registry.py` — disjoint |
| #673 | read-only DataHub-style metadata catalogue | `7e124696` | `0a0c8ad9` | OPEN | writes `src/intelligence/data_catalog.py` + `src/resources/schema_registry.json` — disjoint from W0 docs; W0B/W11 must reuse its catalogue, not duplicate |
| #674 | Debezium CDC adoption gate | `5f3d09cc` | `0a0c8ad9` | OPEN, docs-only | disjoint (`docs/architecture/debezium-cdc-adoption.md`) |
| #675 | NATS JetStream adoption gate | `4cf2afc4` | `0a0c8ad9` | OPEN, docs-only | disjoint (`docs/architecture/nats-jetstream-adoption.md`) |
| #676 | OpenLineage RunEvent projection | `a83a6b5a` | `0a0c8ad9` | OPEN draft | writes `src/intelligence/openlineage.py` + `src/resources/schema_registry.json` (shared with #673 — flag for conflict resolution) — disjoint from W0 docs |

No duplicate-owner risk introduced by this lane. Machine-readable matrices: `W0_OWNER_INVENTORY.json` (same directory).

## 8. What this audit does NOT claim

- No live/RPC/runtime evidence of any kind; all statuses are static-source facts on the pinned SHA.
- No test execution results beyond collection counts; fixture evidence never substitutes for live evidence.
- No scope changes to canonical owners; W0 is read-only by design.
