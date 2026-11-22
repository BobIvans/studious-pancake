# Function and Infrastructure Coverage Crosswalk — PR #666
## Проверка полноты исходного обсуждения «Структура инструментов системы»

**Repository:** BobIvans/studious-pancake  
**Design PR:** #666  
**Snapshot:** main 0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54; PR head b919b62244bfea19702265ac830bb247c8c0c0fc.  
**Назначение:** отделить задокументированный scope от существующих основ репозитория и от функций, которые ещё требуется реализовать. Это crosswalk покрытия, а не заявление о завершённой реализации.

## 1. Статусы

- **EXISTS_BASELINE** — соответствующий source owner/file/workflow существует в current main; это не доказывает полноту и end-to-end wiring.
- **DESIGNED_IN_666** — требование, контракт, work package или acceptance criteria описаны в PR #666.
- **IMPLEMENTATION_REQUIRED** — в этой проверке не найдено доказательств реализованной сквозной функции; требуется код и тесты.
- **CONDITIONAL_CANDIDATE** — кандидат для сравнения, не одобренная зависимость.
- **LICENSE_BLOCKED / REVIEW_REQUIRED** — внедрение запрещено до проверки точного компонента, пути, лицензии и entitlement.

Наличие класса, документа или каталога не доказывает реальный production producer, непрерывный stream, runtime call, qualification либо восстановление. OCA-W0 обязан проверить действительные call paths и тесты.

## 2. Покрытие исходных девяти дисциплин

| Дисциплина | Обязательные функции | Основа, обнаруженная в current main | Покрытие PR #666 | Что ещё реализовать |
|---|---|---|---|---|
| A. Agent access & policy facade | Typed capabilities, progressive discovery, read-only MCP, sandboxed execution, policy enforcement | AGENTS.md, Git worktree правила, GitHub workflows и Local Intelligence; полный ограниченный read-only MCP facade не подтверждён | W17, expansion §8 | Allowlisted query facade, capability policy, network/secret isolation, admin separation, leases, receipts |
| B. Context & retrieval plane | Repo map, AST scope, symbol search, graph traversal, BM25/vector/hybrid, runtime/task-conditioned ranking, token budgets, compact serialization | src/intelligence repo_snapshot/repo_manifest/repo_source/repo_groups/context_pack/context_benchmark/evidence_refs | W0A/W0B/W4/W7/W16; token playbook | Multi-language graph/JIT retrieval, edge quality, runtime/task-conditioned PageRank, measured semantic fallback, exact tokenizer budgets and omission-loss tests |
| C. Knowledge graph & temporal index | SCIP IDs, AST symbols, call/import/type/dataflow/route/event edges, commit history, valid-time, provenance, confidence, schema versions | repo_history/repo_coverage, AGG-02 graph and domain owners; no src/intelligence/repo_graph or temporal ontology implementation found | W0B/W1/W2/W3/W15 | Derived typed multi-layer graph, stable IDs, parser/resolver plugins, unresolved states, edge provenance, bitemporal/as-of query and migrations |
| D. Incremental computation | Signature/body split, Merkle/blob hashes, dependency invalidation, early cutoff, cancellation, branch snapshots, incremental re-index/re-test | Git SHA/snapshot foundations; complete dependency-aware incremental engine not found | W0B/W16 | Content-addressed artifacts, dependency graph, early cutoff, cancellation, branch isolation, resource budgets and full-vs-incremental reconciliation |
| E. Code & strategy plane | Strategy registry/versions, planners, compilers, tests, contracts, PR/issue decisions, isolated worktrees | Existing strategy/execution owners, tests, GitHub/PR history, manifests and reports; preserve canonical financial owners | W0/W0B/W3/W5/W14/W15 | Link ideas→versions→symbols→config→requirements→tests→qualification evidence; no duplicate planner/compiler/capital owner |
| F. External data plane | Provider catalogue, contracts, cursors, ingestion, normalization, lineage, freshness, gaps, correction/retraction/reorg | src/market/source_catalog, observations, streams; src/agg02/storage | W0/W1/W6/W13/W14/W15 | Generic versioned adapter contracts, capability proof, entity identity, schema compatibility, health episodes, source disagreement, replay, reorg/correction receipts |
| G. Runtime evidence plane | Events, traces, operations, observations, episodes, simulation, paper/shadow outcomes, replay | src/observability/events/store/export/replay, src/intelligence/episode_builder; actual producer-to-store coverage still requires audit | W0/W2/W3/W10/W11/W15 | Prove producers; instrument supported paper/shadow routes; correlate IDs/SHA/config/callsites; soak, reconnect, no-loss/gap accounting and as-of replay |
| H. Durable storage & history | SQLite/WAL, Parquet, DuckDB, retention, immutable archives, snapshots, export/import | AGG-02 storage, observability archive/export/replay, Local Intelligence retention/Parquet/compaction modules | W0/W2/W9/W11/W15/W19 | Verify ownership boundaries; portable manifests, restore/replay certification, temporal projections and measured scale gates |
| I. Quality, security, governance & economics | License/SBOM, supply chain, secret redaction, provenance, tests, benchmarks, token/cost accounting, restore verification, human approval | Redaction, evidence refs, retention and existing workflows; new path-level SBOM/license CI gate not found | W7/W12/W17/W18/W19 | Implement path-level license/SBOM/advisory/secret gates, model/data licensing, cost telemetry, coverage-driven test mapping, recovery certification and receipts |

## 3. Further functions that must be covered explicitly

### Retrieval and code intelligence
- Separate signature/declaration index from full-body index. FULL/SKELETON/REFERENCE/OVERVIEW slices must never hide target implementation.
- Exact symbol IDs and compiler-backed SCIP/LSP references are per-language. Syntactic call candidates, compiler-resolved calls and runtime-observed calls are separate.
- Task-conditioned ranking combines exact identifiers, lexical relevance, graph neighborhood, Git churn/co-change, task/strategy relevance and runtime evidence. Runtime frequency must not dominate automatically.
- Trigram/FTS/BM25 comes before semantic/vector fallback; embeddings only after a measured recall gap.
- CodeSplitter/AST-aware chunking, enclosing-scope retrieval, multi-LSP warm pools and parser coverage are techniques to benchmark, not mandatory services.
- Generated/vendored classification (GitHub Linguist or equivalent) scopes and labels code; it must not drive automatic deletion.
- Dead-code/unused-export tools (Knip, ts-prune) produce review candidates only.

### Build and repository scale
- Sparse checkout/partial clone, blob-hash memoization, Watchman/debounce, graph-partitioned scheduling, branch snapshots and multi-agent leases.
- Merge train/speculative batching only if concurrent PR volume justifies it.
- AST-aware diff/merge is a targeted refactor aid. Git remains canonical VCS unless a jj comparison shows a measured advantage.
- Parser grammar, resolver, ontology, schema, normalizer and generated artifact versions are part of cache keys.

### Data and strategy evolution
- Entity resolution across chain, contract deployment, pool, token, venue and market.
- Schema evolution detects changed decimals, units, timestamps, null semantics, pagination and API fields; determines affected adapters/datasets/strategies and requests requalification.
- Source disagreement, freshness, coverage and health have explicit evidence. Declared capability is not observed capability.
- Strategy requirements are versioned independently from provider implementation. Compatibility does not imply economic qualification or execution authority.
- OperationEpisode links observation → normalization → decision/rejection → quote → capital evidence → route/sizing → planner/compiler → simulation → reconciliation → paper/shadow outcome only where joins are evidenced.

### Verification and security
- Test selection uses test coverage contexts and graph impact; critical safety/smoke/invariant/protocol/strategy suites always run.
- Failure shrinking (ddmin/HDD/Hypothesis), targeted mutation testing, flaky test registry, AST structural rules and API/schema breaking-change gates.
- Prompt-injection isolation for README/issues/logs/provider payloads; PII/secret redaction before model context.
- Separate read-only analyst MCP from administrative/index-management tools; stable tool list per authorized profile, bounded continuation and audit receipts.
- Restore/replay is tested in a clean environment; retention pins protect evidence from automatic pruning.

### Conditional infrastructure
- LangGraph is a candidate for stateful agent reasoning, not a second durable workflow owner. Compare with Temporal only if workflow durability needs are demonstrated.
- OpenLineage supplies lineage vocabulary; it does not replace EventEnvelope, AGG-02 or MarketObservation.
- NATS JetStream is transport/replay infrastructure, not canonical fact storage.
- Debezium is database CDC, not a DEX/RPC adapter.
- DataHub is a catalogue candidate; connector support must be proved per real source.
- Apicurio is a schema-registry candidate; Git + CI is the initial default.
- DuckDB/Parquet are analytics/portable storage; ClickHouse/Iceberg/lakeFS/Lance are scale-gated.
- Qdrant/DiskANN/ColBERT are retrieval specialists only after measured ANN/semantic bottlenecks.
- Firecracker/Wasmtime are sandbox candidates after process/container isolation is assessed.
- CRDT/cr-sqlite is unnecessary absent real multi-writer conflict evidence.

## 4. Additional upstream watchlist from the original discussion

| Upstream/reference | Coverage state | Rule |
|---|---|---|
| [GitHub Linguist](https://github.com/github-linguist/linguist) | Added as optional inventory primitive | Generated/vendor/language classification; verify license before vendoring |
| [Semgrep](https://github.com/semgrep/semgrep) | License caveat documented; runtime/rules bake-off conditional | Engine, Community rules, Pro rules and dataflow packages are separately reviewed |
| [universal-ctags](https://github.com/universal-ctags/ctags) | Reference only / license review required | Do not vendor GPL-family code into proprietary core without legal review |
| [code-maat](https://github.com/adamtornhill/code-maat) | Co-change algorithm reference only / license review required | Reimplement required algorithm independently unless licensing is approved |
| [stirelli/codegraph](https://github.com/stirelli/codegraph) | Low-priority NOT_VERIFIED candidate | Evaluate only if selected bake-off leaves a measured gap |
| [AI Token Optimizer VS Code](https://github.com/sbaala/ai-token-optimize-vscode) | Integration reference, not an indexer | Inspect individual components; bundle-level claims are not component evidence |
| SOTA-skills | NOT_VERIFIED; exact upstream identity/commit must be resolved by agent | Review individual audit/build skills; do not import or execute an unknown bundle wholesale |
| CodeSplitter / AST-aware chunking | Capability requirement; exact candidate unresolved | Compare against full-source evidence and exact token budgets |
| Sparse checkout / partial clone | Native Git capability | Use when measured repository scale warrants it |
| Multi-LSP warm pools | Capability requirement | Add only if multi-language LSP startup is a measured latency bottleneck |
| ddmin/HDD | Algorithm requirement | Preserve original/minimized inputs, hashes and reproduction instructions |

Other candidates already linked in the expansion doc include code-graph-mcp, ast-index, Tree-sitter Analyzer, CodeSage, CRG, Glean, LadybugDB, RTK, HEDL, ast-grep, code-graph-rca, Salsa, Buck2, CocoIndex, Nx, Turborepo, Watchman, OpenLineage, DataHub, Apicurio, NATS, Debezium, Temporal, DuckDB, Parquet, ClickHouse, Iceberg, lakeFS, Lance, Dolt, cr-sqlite, jj, Firecracker, Wasmtime, Parca, pprof, pytest-testmon, pytest-cov, Hypothesis, mutmut, Buf, oasdiff, AsyncAPI, Joern, Infer, Knip, ts-prune, cargo-deny, Syft, ScanCode and gitleaks.

## 5. Current-main implementation spot-check

The current main directory listing at the snapshot SHA showed:

- src/intelligence: repo snapshot/manifest/source/groups/history/coverage, context pack/archive/recovery/benchmark, evidence refs, episode builder, retention, Parquet compaction, storage budget/pressure and reports.
- src/agg02: contracts, graph and storage modules.
- src/market: source catalogue, observations, streams, snapshots, discovery and native CPMM capture.
- src/observability: events, store, export, replay, archives, health, integrity and redaction.
- .github/workflows: local-intelligence-v2.yml and many domain workflows.

The same-main code search returned no matches for ProviderCapabilityRegistry, StrategyDataRequirement, WorkResultReceipt, repo_graph, temporal_ontology, runtime_capture or repo-intelligence-index. This is a bounded search observation, not proof that equivalent behavior does not exist under another name. OCA-W0 must inspect implementations and actual callers before creating anything.

## 6. What PR #666 does and does not claim

- PR #666 contains design/handoff documents and a machine-readable package matrix. Its changed files are documentation; it does **not** implement the new code graph, provider registry, temporal ontology, generic adapter runtime, incremental engine, MCP server or W12–W19 CI gates.
- Existing main modules listed above must be reused and tested. New packages add contracts and integrations only where owner audit proves them absent.
- Every capability ends in one of: IMPLEMENTED_AND_TESTED, EXISTS_AND_VERIFIED, CONDITIONAL_NOT_REQUIRED, BLOCKED_WITH_EVIDENCE or UNKNOWN. Documentation alone cannot mark a package complete.
- New implementation PRs are based on freshly fetched current main, each with disjoint write scope, pinned upstream sources, positive/negative tests, actual test counts and evidence receipts.
- No provider enablement, signer/sender, transaction authority, borrowing, spending, production mutation or LIVE permission is included.

## 7. Final completeness rule

The original task is satisfied only when this function matrix has been walked line-by-line against source code, actual callsites, schemas, CI and tests; every row has proof or a scoped follow-up implementation package; and the system passes retrieval, data-quality, replay/restore, licensing, sandbox, runtime-capture and safety gates. A comprehensive plan is not an implemented system.
