# Universal Knowledge + Data Intelligence Plane — расширение PR #666
## Контрактная архитектура, кандидаты upstream, стратегия интеграции и execution gates

**Repository:** BobIvans/studious-pancake  
**Design PR:** [#666](https://github.com/BobIvans/studious-pancake/pull/666)  
**Prepared:** 2026-11-21  
**Observed current main SHA at preparation:** 0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54  
**Design branch baseline:** ea204222df86a0697cc6bce0e9ec60f7db31ffd8

Это расширение дополняет OCA-W0–W11. Оно не создаёт новую конкурирующую платформу и не отменяет существующих canonical owners. Цель — превратить Local Intelligence/OCA в сменную, проверяемую, многоуровневую knowledge-and-evidence platform для растущего числа языков, стратегий, провайдеров, сетей, market datasets и агентов.

## 1. Непереговорные архитектурные правила

1. **Функции обязательны, конкретные зависимости — нет.** Внедрять нужные возможности, а не устанавливать все перечисленные проекты одновременно.
2. **Один canonical owner на каждый факт.** Git владеет кодом и историей; AGG-02 — исходными provider payloads/cursors/gaps; MarketObservation — нормализованными market facts; EventEnvelope/ObservabilityStore — операционными событиями; MarketEpisode — point-in-time episodes/outcomes; стратегии и их qualification остаются у существующих strategy/governance owners. Graph, embeddings, data catalog и context packs — производные read models, не новые владельцы истины.
3. **Сменные backend adapters.** Parser, graph store, lexical index, vector index, workflow engine, provider adapter и export backend подключаются через versioned interfaces. Core не содержит ветвлений вида provider == X.
4. **Неизвестное остаётся UNKNOWN.** Не выводить runtime execution из AST; не выводить live streaming из разового poll; не выводить capability из названия класса, документации или HTTP 200; не выводить экономическую пригодность из TVL, популярности или benchmark автора.
5. **Provenance на каждом факте и ребре.** Хранить источник, точную версию/commit/blob, время получения, parser/normalizer/schema/ontology versions, confidence и verification state.
6. **Read-only intelligence plane.** Индексатор, retrieval, MCP и agent query facade не получают signing, sender, RPC mutation, borrowing, spending, deploy или LIVE authority.
7. **Human-controlled mutations.** Агенту разрешается писать только в выделенный task worktree/scope. Merge, лицензии, strategy admission и operational promotion требуют предусмотренного review/approval.
8. **Масштабирование по измеренному bottleneck.** Glean/LadybugDB, NATS, Temporal, DataHub, ClickHouse, vector DB и object lake — conditional candidates, а не обязательные сервисы MVP.

## 2. Upstream index: кандидаты по функциям

Ссылки ниже — исходные проекты для audit/bake-off, а не автоматическое разрешение vendoring или runtime adoption. В W0A агент обязан закрепить конкретный commit/tag, retrieval timestamp, SPDX/лицензию каждого используемого компонента и транзитивные зависимости, поддерживаемые языки, security posture, installation side effects и воспроизводимые команды. Не переносить feature claims или benchmark числа из README в наши метрики без локального измерения.

### 2.1 Code graph, symbol resolution, navigation and retrieval

| Проект | Роль, которую проверяем | Правило для Studious |
|---|---|---|
| [sdsrss/code-graph-mcp](https://github.com/sdsrss/code-graph-mcp) | Rust + Tree-sitter, SQLite/FTS5, incremental/Merkle updates, call graph, route tracing, bounded context | Main graph contender. Проверить license файла, tool allowlist, ветвления, rename/branch switch, C++/Python/Rust точность, freshness и response truncation. Никогда не принимать одноимённые calls как resolved без evidence. |
| [defendend/Claude-ast-index-search](https://github.com/defendend/Claude-ast-index-search) | ast-index: symbol/reference/import/dependency navigation, opt-in graph build, Git hotspots, compact slices | Отдельный high-priority competitor для навигации. README указывает MIT; graph создаётся отдельной командой и не гарантированно следует за обычным rebuild/update. Проверять stale graph. |
| [aimasteracc/tree-sitter-analyzer](https://github.com/aimasteracc/tree-sitter-analyzer) | Cross-language-safe Tree-sitter resolver, family-gated edges, JSON verdict envelopes, impact and test selection | Независимый precision/adversarial benchmark. README указывает MIT. Pipeline registration языка не считается доказательством cross-file edge. Проверить все unresolved/ambiguous cases. |
| [iliaal/codesage](https://github.com/iliaal/codesage) | Structural graph + lexical/semantic retrieval, risk/co-change signals and context bundles | Retrieval/risk candidate. README указывает MIT и 9 языков; опубликованный малый benchmark не экстраполировать. Embedding/reranking — только after lexical/graph measured gap. |
| [n24q02m/crg](https://github.com/n24q02m/crg) | Temporal code graph, commit as-of, diff, graph review context | Temporal benchmark. v2.0 README описывает valid_from_sha/valid_to_sha на nodes/edges; README указывает Apache-2.0. Это история Git-графа, а не bitemporal runtime/market truth. |
| [CodeGraphContext](https://github.com/CodeGraphContext/CodeGraphContext) | Persistent code graph, callers/callees/call chains, CLI/MCP, Tree-sitter/SCIP | Сравнить на том же SHA с нативным индексом и C/Rust daemons. Проверить MCP admin commands и embedded store. |
| [Graphify](https://github.com/Graphify-Labs/graphify) | Code + docs/config/schema graph, extracted vs inferred edges | Проверять code-only path первым; все LLM/media/cloud features выключены. Путь каждого файла и plugin/license проверять отдельно. |
| [DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp) | Shared multi-agent graph daemon, code/docs/config/infrastructure graph | Сравнить lifecycle/concurrency и installer side effects. Устанавливать только в изолированный HOME. |
| [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph) | Rust graph daemon, SQLite/WAL, watcher, MCP/CLI | Сравнить branch/worktree isolation, telemetry opt-out, platform/WAL и разрешение динамических вызовов. |
| [SylphxAI/repomap](https://github.com/SylphxAI/repomap) | Lightweight local graph, calls/paths/impact, search | Дополнительный лёгкий graph candidate; не принимать собственный benchmark за наш. |
| [facebookincubator/Glean](https://github.com/facebookincubator/Glean) | Fact store/query engine for large code graphs; Angle; SCIP/LSIF ingestion | High-scale candidate only after multi-repo/scale need. Текущий README описывает native coverage C/C++, Hack, Haskell, JavaScript/Flow и Python; прочие языки зависят от SCIP/LSIF. BSD license в upstream README. |
| [LadybugDB/ladybug](https://github.com/LadybugDB/ladybug) | Embedded property graph, Cypher, full-text/vector retrieval, columnar storage | Graph-storage bake-off only. Current LICENSE says MIT; formerly known as Kuzu. Не менять SQLite/WAL owner без benchmark на реальном графе и recovery test. |

Дополнительные независимые primitives:

- [Tree-sitter](https://github.com/tree-sitter/tree-sitter) — parsing/queries and grammar integration; grammar version pinned per language.
- [SCIP](https://github.com/sourcegraph/scip) и [SCIP specification](https://scip-code.org/) — stable cross-tool symbol identity/index format; индексатор нужен отдельно для каждого языка/build.
- [rust-analyzer](https://github.com/rust-lang/rust-analyzer) — Rust semantic/FST navigation reference and indexer.
- [GitHub Stack Graphs](https://github.com/github/stack-graphs) — partial path resolution/stitching algorithm reference only. Upstream repo was archived 2025-09-09; do not make it a critical live dependency.
- [Aider](https://github.com/Aider-AI/aider) — RepoMap/PageRank ranking algorithm reference, not canonical graph store.
- [grep-ast](https://github.com/Aider-AI/grep-ast) — enclosing AST scope retrieval.
- [ast-grep](https://github.com/ast-grep/ast-grep) — structural search, executable audit rules and AST rewrite; repository license MIT.
- [Zoekt](https://github.com/sourcegraph/zoekt) — fast trigram/lexical code search.
- [Tantivy](https://github.com/quickwit-oss/tantivy) — embedded Rust lexical index candidate.
- [Microsoft GraphRAG](https://github.com/microsoft/graphrag) — hierarchical knowledge summaries for large corpora; not default code graph.
- [Joern](https://github.com/joernio/joern) — optional CPG/CFG/DFG/taint profile.
- [Facebook Infer](https://github.com/facebook/infer) — targeted static analysis profile.
- [Halo code-graph-rca](https://github.com/sebdenes/code-graph-rca) — git-aware root-cause/change-neighborhood benchmark.

### 2.2 Incremental computation, invalidation and large-repository operations

| Upstream | What to borrow/test | Adoption boundary |
|---|---|---|
| [Salsa](https://github.com/salsa-rs/salsa) | Memoized incremental queries, backdating/early cutoff, stable item interfaces | Compare if native incremental engine becomes too complex. |
| [Buck2](https://github.com/facebook/buck2) | DICE dependency graph, cancellation, shared/distributed computation | Design reference; do not deploy the full build system to gain incremental graph updates. |
| [CocoIndex](https://github.com/cocoindex-io/cocoindex) | Content-addressed incremental ETL and change propagation | Compare against a minimal native dependency engine on provider/schema changes. |
| [Nx](https://github.com/nrwl/nx) | Changed-project/dependency graph and affected task selection | Reuse ideas for package/test blast radius. |
| [Turborepo](https://github.com/vercel/turborepo) | Git/content input hashes and cache correctness | Borrow input-hash and cache-key principles; avoid path-only cache. |
| [Watchman](https://github.com/facebook/watchman) | Filesystem change notification/coalescing | Optimization only; Git SHA reconciliation remains authoritative. |
| [BLAKE3](https://github.com/BLAKE3-team/BLAKE3) | Fast blob/tree content hashes | Hashes must include parser/schema/tool versions where result semantics depend on them. |

Required native semantics: separate FileSignatureIndex and FileBodyIndex; hash signatures, declarations, imports, bodies and generated artifacts separately; content-address cached artifacts; propagate dependency invalidation; stop downstream recomputation when output hash is unchanged; provide cancellation, priority scheduling, resource budgets, branch snapshots and periodic full-vs-incremental reconciliation.

### 2.3 Data lineage, schemas, provider catalogue and durable workflows

| Upstream | Function | Studious integration rule |
|---|---|---|
| [OpenLineage](https://github.com/OpenLineage/OpenLineage) | Run → Job → Dataset lineage and extensible facets | Borrow event/facet model and add chain, market, provider, observation and episode facets. Not a replacement for EventEnvelope/AGG-02. |
| [DataHub](https://github.com/datahub-project/datahub) | Data catalogue, metadata ownership, lineage and ingestion connectors | Future catalog candidate. Connector count does not prove support for a specific DEX/RPC source. |
| [Apicurio Registry](https://github.com/Apicurio/apicurio-registry) | Versioned schemas and compatibility checks | Start with versioned schemas in Git + CI; deploy registry only when multi-producer schema governance requires it. |
| [NATS Server / JetStream](https://github.com/nats-io/nats-server) | Durable event delivery, retention, replay, fanout | Optional multi-process event transport; not canonical storage and not a reason to replace current journals. |
| [Debezium](https://github.com/debezium/debezium) | Database change-data capture with offsets | Use only for actual cross-database CDC need; not a DEX/RPC adapter. |
| [Temporal](https://github.com/temporalio/temporal) | Durable resumable workflow execution, retries and replay | MIT upstream. Evaluate when current task/event lifecycle cannot meet measured reliability needs; do not run both Temporal and LangGraph as competing orchestration owners. |
| [OpenTelemetry](https://github.com/open-telemetry/opentelemetry-specification) | Trace/span context and instrumentation conventions | Trace context supplements EventEnvelope; canonical event ledger remains authoritative. |

### 2.4 Storage, history, branching and analytics

- [DuckDB](https://github.com/duckdb/duckdb) + [Apache Parquet](https://github.com/apache/parquet-format): local analytical queries and columnar archives.
- [ClickHouse](https://github.com/ClickHouse/ClickHouse): conditional high-throughput analytics after measured ingest/query threshold.
- [Apache Iceberg](https://github.com/apache/iceberg): table snapshots/schema evolution only if an actual data lake is justified.
- [lakeFS](https://github.com/treeverse/lakeFS): object-store branching/versioning if cold data lake becomes a separate owner.
- [Lance](https://github.com/lancedb/lance): versioned vector/columnar datasets when vector retrieval justifies it.
- [Dolt](https://github.com/dolthub/dolt): SQL data versioning/diff/merge benchmark; do not introduce a second operational SQL owner casually.
- [cr-sqlite](https://github.com/vlcn-io/cr-sqlite): multi-writer column/row replication experiment. Upstream license is reported as MIT; support/activity/compatibility are separate gates. Not banned by license alone, not a foundation by default.
- SQLite [Session Extension](https://www.sqlite.org/sessionintro.html): changesets/diffs/patches and conflict callbacks for specific local synchronization use cases.
- [jj](https://github.com/jj-vcs/jj): operation log, undo and first-class conflict model; compare with Git worktree + leases before adopting another VCS workflow.

SQLite/WAL remains the initial local transaction owner where it already exists. Parquet/DuckDB are analytical/read-only projections; no copy of raw canonical market/event records into graph/vector stores.

### 2.5 Verification, runtime evidence, test economics and contracts

- [pytest-testmon](https://github.com/tarpas/pytest-testmon): Python change-based test selection candidate.
- [pytest-cov](https://github.com/pytest-dev/pytest-cov): coverage contexts and test-to-code mapping.
- [Hypothesis](https://github.com/HypothesisWorks/hypothesis): generative/property tests for invariants and adapters.
- [mutmut](https://github.com/boxed/mutmut): targeted mutation testing for high-risk parsers, contracts and guards.
- [Parca](https://github.com/parca-dev/parca) and [pprof](https://github.com/google/pprof): runtime sampling/profiling evidence.
- [Knip](https://github.com/webpro/knip) and [ts-prune](https://github.com/nadeesha/ts-prune): JS/TS unused export/dead dependency candidates; never auto-delete.
- [Buf](https://github.com/bufbuild/buf), [oasdiff](https://github.com/Tufin/oasdiff), [AsyncAPI](https://github.com/asyncapi/spec): schema/API/contract breaking-change gates.
- [ddmin / Delta Debugging reference](https://www.st.cs.uni-saarland.de/dd/) and Hypothesis shrinking: reduce reproducible failing inputs; preserve original failure/evidence.
- Existing tests map symbols/callsites to coverage contexts; critical smoke, safety, invariant, protocol and strategy regression tests always run irrespective of impact selection. Flaky tests are tracked with owner, last pass, pass-rate and failure evidence.

### 2.6 Agent access, isolation, output budgets and security

- [Firecracker](https://github.com/firecracker-microvm/firecracker): stronger isolation for untrusted execution if process/container sandbox is insufficient.
- [Wasmtime](https://github.com/bytecodealliance/wasmtime): capability-oriented WebAssembly sandbox runtime; Wizer development has moved into Wasmtime and must not be treated as a separate maintained dependency without new verification.
- [jj](https://github.com/jj-vcs/jj) and Git worktrees: isolated task branches, operation receipts and conflict recovery.
- [RTK](https://github.com/rtk-ai/rtk): CLI output compression candidate for test/build/git/search outputs. Measure real tokenizer tokens and critical-information loss; byte-based estimates and vendor percentages are not acceptance evidence.
- [HEDL](https://github.com/dweve-ai/hedl): optional context-pack serialization experiment only. Do not change canonical JSON/SQLite/Parquet schemas; evaluate semantic recovery of edges, nulls, versions, provenance and ambiguity.
- [Qdrant](https://github.com/qdrant/qdrant), [DiskANN](https://github.com/microsoft/DiskANN), [ColBERT](https://github.com/stanford-futuredata/ColBERT): specialist vector/ANN/late-interaction candidates only after lexical/graph recall tests expose a real gap.

### 2.7 License, SBOM, secret scanning and supply chain

- [cargo-deny](https://github.com/EmbarkStudios/cargo-deny): Rust license, advisory, source and duplicate dependency policy.
- [Syft](https://github.com/anchore/syft): SBOM generation for source trees, archives and containers.
- [ScanCode Toolkit](https://github.com/nexB/scancode-toolkit): file/package license and copyright inventory, including mixed-license directories.
- [gitleaks](https://github.com/gitleaks/gitleaks): secret scanning.
- Add SPDX/NOTICE checks, dependency provenance, pinned source commits, checksum/signature verification and model/rules/dataset license inventory. No scanner alone is a legal approval.

## 3. License corrections and hard review cases

This is a policy checklist, not legal advice. Re-verify the exact component/path, version, distribution mode and transitive dependencies before adoption.

| Component | Required interpretation | Studious decision |
|---|---|---|
| Elastic License 2.0 / Icemage | ELv2 is not a blanket non-commercial license: commercial use is allowed subject to restrictions including hosted/managed service, license-key circumvention and preserving notices. Icemage's source-availability/auditability is a separate issue from ELv2 itself. | Do not label ELv2 “non-commercial”. Do not make a closed/source-unavailable component a critical unauditable backend. Require exact upstream URL, terms, binary/source provenance and exit plan. |
| [GitNexus](https://github.com/abhigyanpatwari/GitNexus) | Repository has been identified as PolyForm Noncommercial 1.0.0; popularity/stars do not change license scope. | Exclude from commercial product absent a separate commercial grant. Do not copy code/rules/assets into core. Re-check license at pinned commit. |
| [CodeQL CLI binaries](https://github.com/github/codeql-cli-binaries) vs [CodeQL query/language repo](https://github.com/github/codeql) | The CLI/engine is separately licensed from the OSS codeql repository. Terms restrict private/closed-source automated analysis without the applicable paid GitHub Advanced Security entitlement. | Do not infer CLI rights from MIT license on github/codeql. W0A must record exact entitlement and execution context; otherwise do not use for private repo CI. |
| [GitHub Stack Graphs](https://github.com/github/stack-graphs) | Upstream archived 2025-09-09; source carried MIT/Apache-2.0 dual license. | Algorithm reference only, not critical live dependency. |
| [libgit2](https://github.com/libgit2/libgit2) | GPL-2.0 with special Linking Exception permits linking from proprietary applications under the exception; modifications to libgit2 itself remain GPL-governed. | Do not classify as a simple GPL prohibition. Preserve notices and assess modifications/distribution. |
| [Sapling](https://github.com/facebook/sapling) | Main project GPL-2.0; subdirectories may have distinct terms. | Prefer Git CLI/worktree or a separately reviewed permissive Git library for proprietary core. Never infer all subdirectory terms from root or vice versa. |
| [universal-ctags](https://github.com/universal-ctags/ctags) / [code-maat](https://github.com/adamtornhill/code-maat) | Their referenced licenses are GPL-family (ctags GPL-2.0; code-maat GPL-3.0). | Prefer reimplementing required algorithms with Tree-sitter/Git API; do not vendor/translate code without legal review. |
| [Tabby](https://github.com/TabbyML/tabby) | Main code advertises Apache-2.0, while ee/ is separately governed by Enterprise License. | Apply path-level allow/deny and package inventory. |
| [Semgrep](https://github.com/semgrep/semgrep) | Engine, Community rules, proprietary Pro rules and dataflow packages do not automatically share one license. | Audit engine, each ruleset and each dataflow bundle separately; do not copy proprietary rules into repo. |
| [cr-sqlite](https://github.com/vlcn-io/cr-sqlite) | MIT licensing does not prove current maintenance, compatibility or operational suitability. | Keep eligible for evaluation; support status is independent from license status. |
| Subprocess integration | A CLI boundary is not a universal GPL/compliance exemption. Relationship depends on actual combined work, protocols/data exchange, patching, packaging and distribution. | Every external executable gets a record of launch method, process boundaries, IPC/protocol, files exchanged, patches, distribution/installation and notice obligations. Escalate legal ambiguity. |

### Mandatory license record

Every dependency, plugin, rule pack, model, embedding, dataset and external executable has: exact name/version/commit/blob; source URL and retrieval time; SPDX expression and license files; path-level exceptions; transitive SBOM; origin/checksum/signature; patches; build/runtime mode; distribution and hosted-service model; notices; security advisories; reviewer; decision; expiry/revalidation trigger.

## 4. Versioned provider and external-data plane

Each provider uses a versioned adapter contract; adding a source must not require editing individual strategy implementations.

### ProviderAdapterContract

Required fields:

- provider_id, adapter_id, adapter_version;
- chain_id/network identity, venue, protocol, endpoint/stream class (endpoint secrets are never serialized);
- supported methods, market/entity coverage, historical/replay capability, request quotas, concurrency and allowed cadence;
- observed mode: STREAMING, POLL_ONLY, ONE_SHOT or UNAVAILABLE (declared capability is not proof of observed mode);
- DataContract schema_id/schema_version, units, decimals, timestamp semantics, null/zero semantics and normalization version;
- cursor, watermark, event_time, ingest_time and recorded_at;
- freshness, lag, coverage, gap intervals, reconnect count, rate-limit/backoff state and provider health;
- raw payload reference + hash, dedup key, correction/retraction/reorg semantics;
- backfill/replay/restore capabilities and latest successful verification receipt.

### Required entities

- ProviderCapability — chain/market/method/history/frequency support.
- DataContract — schema, required fields, units, decimals, time semantics and compatibility.
- SourceHealthEpisode — outage, stale feed, incomplete coverage, reconnect or rate-limit episode.
- EntityIdentity — canonical chain, token, contract, pool, venue and market identity.
- NormalizationRule — raw-to-normalized transformation with version and tests.
- DataQualityEvidence — freshness, coverage, gaps, outliers, replay and consistency evidence.
- SourceDisagreement — conflicting independent source values and resolution status.
- DataLineageEdge — upstream payload → adapter → normalization → observation/dataset → strategy/episode.
- SchemaChangeEvent — provider API/schema/semantics change with affected consumers.
- Correction/Retract/Reorg receipt — explicit invalidation of facts previously treated as canonical.

### Blockchain identity and reorg correctness

An address alone is not an entity identity. For chain-backed facts, capture at minimum chain/network identity, block number, block hash, transaction hash, tx/log index, contract deployment/version and canonicality/finality. Reorgs create explicit correction/retraction and replay work; do not silently overwrite history. Keep event time separate from ingest/recorded time. Do not conflate a finalized block with a merely observed head.

## 5. Strategy Data Contract and compatibility gate

Each StrategyVersion declares requirements, not hard-coded dependencies on one provider.

StrategyDataRequirement contains:

- strategy_family, strategy_id/version, contract_version and owning code SHA;
- required capabilities (for example pool state, executable quote, historical replay, flash capital evidence, chain finality);
- supported chain/protocol/venue/asset/entity families;
- max observation age, min source coverage, min independent source count, replay/gap/correction requirements where justified;
- freshness/stale-data policy, disagreement policy, correction/reorg response and missing-data behavior;
- required fields/units/decimals/clock semantics;
- offline/paper/shadow qualification mode and operational constraints;
- tests, golden datasets, qualification evidence and last review.

ProviderCapabilityRegistry + StrategyRequirementRegistry + CompatibilityEvaluator return COMPATIBLE, PARTIAL, INCOMPATIBLE or UNKNOWN with evidence refs and exact reasons. A strategy must not become QUALIFIED merely because an adapter exists. Thresholds are strategy/test-derived; never invent one universal freshness or coverage number. A provider outage/schema drift should identify affected adapters, datasets and strategies, then block/requalify only those consumers under explicit policy.

## 6. Unified typed temporal knowledge graph

Do not build one untyped graph. Use layers with shared IDs and explicit cross-layer edges:

- Code: Repository, Commit, Blob, File, Module, Symbol, Callsite, Type, Interface.
- Build/config: Package, Dependency, BuildTarget, Config, Environment, FeatureFlag.
- Strategy: StrategyFamily, StrategyVersion, StrategyConfig, StrategyRequirement, StrategyIdea.
- Market/domain: Chain, Protocol, Venue, Pool, Token, Asset, Market, FlashLender.
- Data: Provider, Adapter, Endpoint, Stream, DataContract, Observation, Dataset, Transformation.
- Runtime: Run, Trace, Span, Event, Candidate, Decision, OperationEpisode.
- Outcome: Quote, Simulation, Reconciliation, PaperOutcome, ShadowOutcome, QualificationEvidence.
- Engineering/governance: Test, PR, Issue, Review, ADR, WorkResultReceipt, LicenseRecord, CapabilityPolicy, SchemaVersion.

Relation families include DEFINES, CALLS_STATIC, CALLS_RESOLVED, IMPORTS, IMPLEMENTS, OVERRIDES, READS, WRITES, EMITS; STRATEGY_USES_SYMBOL, STRATEGY_REQUIRES_PROVIDER, STRATEGY_REQUIRES_CAPABILITY, STRATEGY_CONFIGURED_BY, EXTENDS_STRATEGY, SUPERSEDES_STRATEGY; PROVIDED_BY, FETCHED_THROUGH, NORMALIZED_BY, DERIVED_FROM, CONSUMED_BY, CORRECTS, RETRACTS, HAS_GAP; EXECUTED_BY, OBSERVED_AT, DECIDED_ON, TRIGGERED, SIMULATED_BY, RECONCILED_TO, RESULTED_IN; TESTED_BY, CHANGED_BY, REVIEWED_IN and DOCUMENTED_IN.

Every node/edge carries evidence_ref, source_id, provenance, resolver/producer version, confidence, verification_state, schema_version and ontology_version. Static call candidates, compiler-resolved calls and actual runtime-observed calls are different edge types. Unresolved/ambiguous edges remain explicit.

Temporal record fields: valid_from/valid_to, recorded_at, source_event_time, repo_sha/blob_hash, strategy/config generation and schema/ontology version. Support as-of repo SHA and as-of operation time; the query must reconstruct which code, provider contract, schema and qualification state were actually valid when an episode occurred.

## 7. Incremental computation and resource governor

Required behavior:

1. Separate signature/declaration/import index from body/content index.
2. Use Git tree/blob hashes, not mtime as identity. Include parser, grammar, resolver, ontology, schema and normalizer version in cache keys.
3. Cache each derived artifact against exact input hashes; track dependency graph and invalidate only descendants whose inputs changed.
4. Early-cutoff when recomputed output hash is unchanged.
5. Support add/delete/rename, merge/rebase, force-push, branch switch, branch snapshots and independent worktree generation IDs.
6. Coalesce watcher events; allow cancellation, priorities, backpressure and single-writer/lease rules.
7. Resource budgets for CPU, RAM, disk, IO, WAL, queue depth and time; indexing must not starve decision-relevant market capture or paper/shadow runtime.
8. Nightly/full periodic reconciliation compares incremental result with clean rebuild and emits drift receipts.
9. Preserve exact coverage and unsupported-language reasons; never silently drop parse failures.
10. Re-index/re-test only affected downstream nodes where confidence is sufficient; always run critical safety/invariant suites.

## 8. Agent access, worktree isolation and query facade

### Minimal stable read-only MCP/query surface

Prefer six composite operations, with progressive disclosure and bounded cursors:

1. repo_overview — repo card, coverage, freshness and high-level catalogue.
2. strategy_search — strategy families/versions/requirements/qualification.
3. strategy_explain — exact implementation path, config, sources, tests and evidence.
4. symbol_context — definition/body on demand, direct callers/callees/types and confidence.
5. trace_operation — observation → decision → quote/capital → route/size → simulation → reconciliation → outcome.
6. build_context_pack — task-specific, token-bounded evidence pack with continuation.

Each operation carries repo/data generation, freshness, completeness, next_cursor/truncation, provenance and UNKNOWN gaps. Server's exposed tool list remains stable and allowlisted by caller policy. Admin/index rebuild/write/delete/shell/secret/network/market mutation tools stay on a separate administrative plane and are not offered to analysts.

### Task isolation and audit

- One task = unique ID, owner, base SHA, write scope, worktree, lease TTL and resource budget.
- Leases prevent overlapping writers; use separate task worktrees, patch applicability checks and expected base SHA.
- Sandboxed tests/builds have bounded CPU/RAM/disk/time and no bot runtime credentials, keys, signer, provider admin credentials or transaction submission.
- Network is deny-by-default; approved read-only hosts/endpoints are explicit per profile.
- WorkResultReceipt records agent/worker, task ID, base/head SHA, touched paths/symbols, intended scope, tests/commands, actual counts, artifact hashes, failures, unresolved risks, approvals and rollback checkpoint.
- All tool invocations and mutations are auditable. External README/log/provider payloads are untrusted data; isolate prompt injection and redact secrets before model context.
- Human approval is required for merge, production settings, strategy qualification and any expansion of capability.

## 9. Verification, test economics, storage and recovery

- Changed files → changed symbols → dependency/call graph → tests selected from actual coverage contexts and dependency edges.
- Preserve mandatory safety, smoke, invariants, protocol and strategy regression tests regardless of selection.
- Track flaky tests, owner, history, last confirmed pass and quarantined reason. Quarantine never means silently ignored forever.
- Apply ddmin/Hypothesis shrinking to reproducible failing examples; store original and minimized hashes.
- Mutation testing is targeted to high-risk guards, units/decimals, stale-data and correction semantics.
- AST-aware refactor/audit rules run as deterministic CI gates; automatic deletion remains prohibited.
- Metrics remain separate: graph symbol/edge precision and recall; ambiguity/unresolved rates; stale edge rate; incremental invalidation/cache hit/full-vs-incremental consistency; retrieval recall@K/precision@K; exact tokenizer tokens and omitted evidence; provider freshness/coverage/lag/gaps/disagreement; runtime event loss/correlation; strategy qualification accuracy; P50/P95/P99 latency; CPU/RAM/IO/WAL/disk; SBOM/license coverage.
- Backup/restore/replay must be certified on a clean environment. Immutable archive manifests, checksums, schema/tool versions and retained evidence pins are required. No model-driven deletion of evidence.
- Scale gates: NATS/Temporal/DataHub/Apicurio/ClickHouse/Iceberg/lakeFS/Lance/Qdrant/DiskANN/ColBERT are only adopted after a measured multi-process, schema, throughput, retention or retrieval bottleneck.

## 10. Expanded work package map

Existing OCA-W0–W11 remain intact. Add:
- OCA-W12 — license/SBOM/supply-chain gate.
- OCA-W13 — generic provider catalog and adapter/data contracts.
- OCA-W14 — per-strategy data requirements and compatibility qualification.
- OCA-W15 — typed temporal ontology, evidence edges and schema migration.
- OCA-W16 — incremental computation, invalidation and resource governor.
- OCA-W17 — secure agent access, worktree leases, receipts and read-only MCP facade.
- OCA-W18 — coverage-driven verification, retrieval correctness and test economics.
- OCA-W19 — conditional lineage/schema-registry/event-transport/durable-workflow bake-off (OpenLineage, Apicurio, DataHub, NATS, Debezium, Temporal).

Work packages have exclusive write scopes in WORK_PACKAGE_MATRIX.json. Independent audit/design tasks may run concurrently in separate worktrees; changes to shared canonical owners are serialized by one interface owner. Implementation PRs are small, current-main-based and reviewable. PR #666 is the design/handoff source, not a blanket permission to implement everything in one giant patch.

### Recommended dependency order

1. OCA-W0 + W0A + inventory/owner audit; validate exact upstream links and actual canonical owners.
2. W12 supply-chain baseline can start once source inventory is pinned; W13 data contracts follow owner audit/W1.
3. W14 follows W13 and existing strategy conflict/qualification owners.
4. W15 integrates W1/W2/W3 with W13/W14; only then attach stable cross-layer relationships.
5. W16 builds on the selected W0B graph and W15 stable inputs.
6. W17 uses W11's query plane plus W12 governance; implement separate read-only/admin capabilities.
7. W18 extends W7 golden retrieval and W15 evidence graph with coverage/test mapping.
8. W19 is conditional after W13/W15 and workload measurements; choose none if native contracts/journals suffice.

## 11. Acceptance questions and quality gates

The implementation is not complete until the system can answer with exact evidence IDs and historical state:

- Find every flash-loan/flash-swap strategy family and variant, with code/config/tests and qualification status.
- Show which provider/adapters actually feed a given strategy and whether each is STREAMING, POLL_ONLY, ONE_SHOT or UNAVAILABLE.
- Identify historical replay, freshness, gaps, correction and reorg support per source.
- Show which functions changed strategy sizing/route/planner behavior across the last N commits.
- Map each critical callsite to tests/coverage; show unresolved/ambiguous code edges separately.
- Explain whether a rejected candidate failed because of data gaps, provider disagreement, missing capability or economic constraints.
- Reproduce one paper/shadow episode using the exact repo SHA, config generation, schemas, provider observations, code symbols and captured outcome.
- Show how a provider API/schema/decimal/timestamp change propagates to adapters, datasets, strategies and requalification.
- Restore an export on a clean machine and reproduce the same evidence query/replay checksums.
- Prove no intelligence tool can sign, submit, borrow, spend or turn on LIVE.

No single “graph quality” score hides these dimensions. Report coverage, accuracy, freshness, completeness, safety and cost separately.

## 12. Source verification notes as of 2026-11-21

Current upstream pages consulted for a small subset confirm: ast-index identifies MIT; Tree-sitter Analyzer identifies MIT and distinguishes language pipeline registration from proved cross-file bindings; CodeSage identifies MIT but reports a small corpus benchmark; CRG v2.0 documents SHA-validity columns and Apache-2.0; Stack Graphs is archived since 2025-09-09; Glean identifies BSD and limited native language support plus SCIP/LSIF; LadybugDB LICENSE identifies MIT; libgit2 documents GPL-2.0 with Linking Exception; CodeQL CLI is separately licensed from the MIT github/codeql source; Elastic License 2.0 permits use subject to the listed limits. These are lead checks only, not a complete legal or supply-chain audit. Recheck each exact pinned tree in W0A/W12 before use.

**Implementation decision:** preserve the architecture and contracts above, benchmark alternatives, then adopt the smallest set of auditable components that measurably improves Studious Pancake. Do not trade away evidence correctness, financial safety or source auditability for fewer tokens or a larger tool catalog.
