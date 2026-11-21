# Tool Access Profiles — Studious Pancake
## Минимальный reproducible stack для code graph, Web3 research и операций

**Принцип:** один canonical Studious data plane + один проверенный derived code graph + точечный retrieval. Не устанавливать одновременно несколько memory/graph систем. Внешние инструменты — dev-only/read-only, пока не доказана необходимость их встраивания.

---

## 1. Profiles

| Profile | Разрешённые возможности | Запреты |
|---|---|---|
| LOCAL_CODE | Git, существующий `src/intelligence`, code graph CLI, AST/SCIP, tests, context pack | Нет RPC/keys/trading |
| STRATEGY_RESEARCH | LOCAL_CODE + bounded read-only SQD / небольшой Antseer subset | Нет submission/trading authority |
| OPERATIONS_READ | Read-only EventEnvelope/AGG-02/MarketObservation/MarketEpisode replay/export | Нет event mutation/retention deletion |
| CODING_WORKER | Один Task Packet, отдельный worktree, write только в scope задачи, tests, index refresh | Нет signer/sender/live/secret access |
| REVIEWER | Diff, graph impact, tests, evidence, work receipt, stale-index checks | Нет production mutation |
| HUMAN_OPERATOR | Health/readiness/reports и explicit approvals | Только человек даёт operational/merge approval |

MVP сейчас: LOCAL_CODE + CODING_WORKER + REVIEWER + OPERATIONS_READ. STRATEGY_RESEARCH добавляется только для задач, которым реально нужны внешние chain/analytics data.

## 2. Code-intelligence tools: verified candidate shortlist

### 2.1 Studious Local Intelligence V2 — canonical foundation

Всегда переиспользовать:
- `src/intelligence/repo_snapshot.py`, `repo_manifest.py`, `repo_source.py`, `repo_groups.py`, `repo_history.py`, `repo_coverage.py`;
- `context_pack.py`, `context_archive.py`, `context_recovery.py`, `context_benchmark.py`, `evidence_refs.py`;
- `episode_builder.py`, experiment/provider/strategy reports;
- existing sampling, rollups, Parquet compaction, retention, storage budget/pressure;
- `src/observability`, `src/agg02`, `src/market`, `src/market_data_evolution`.

First inspect real CLI/help/tests and actual coverage. Do not create Local Intelligence V3 or duplicate canonical registries. Native parser coverage is known to be incomplete beyond Python; W0 must establish current exact language/artifact coverage.

### 2.2 CodeGraphContext (CGC) — primary code-graph candidate

Upstream: https://github.com/CodeGraphContext/CodeGraphContext  
License: repository identifies MIT; separately audit transitive package/dependency licenses.

Useful because its CLI/MCP exposes callers, callees, call chains, imports, inheritance, variable use and dead-code candidates. Its current project description advertises 23 languages including Solidity and offers embedded graph DB options. It may be a faster way to get navigable function links than writing a graph engine from scratch.

Isolated developer install candidate:
```bash
uv tool install codegraphcontext
cgc index
cgc stats
cgc analyze callers <symbol>
cgc analyze calls <symbol>
cgc analyze chain <start> <end>
```

Check the exact current package command, Python compatibility, selected embedded backend, RAM/disk use and indexing correctness before relying on it. Do not add it to bot runtime dependencies. Its MCP catalog includes management/write operations; do not expose the whole server to ChatGPT. Prefer the CLI during indexing and a narrow read-only wrapper for queries.

### 2.3 Graphify — broad code + docs/config graph candidate

Upstream: https://github.com/Graphify-Labs/graphify  
The repository currently shows Apache-2.0 and MIT license files; inspect component-specific license/NOTICE before copying code.

Graphify uses local Tree-sitter parsing for code, supports about 40 languages, and can represent docs, SQL schemas, configs and other artifacts. It produces a graph with EXTRACTED vs INFERRED edges, query/path/explain, subsystem communities and a compact report. Its optional semantic pass for documents/media may call an LLM/backend: keep that disabled for the initial local-only bake-off.

Current install:
```bash
uv tool install graphifyy
```
Official package name is `graphifyy` (two y's); CLI/skill command is `graphify`. Codex skill registration is a separate operation (for example `graphify install --platform codex`); do not run a setup wizard or modify client/repo configuration without reviewing its diff. Benchmark code-only locally first. Do not use Graphify Cloud or upload repository contents.

Do not depend on the old `uv tool install "graphifyy[mcp]"` instruction.

### 2.4 Tree-sitter + SQLite + Personalized PageRank — lightweight fallback

Tree-sitter supplies deterministic multi-language syntax trees; a small SQLite/FTS5 and adjacency projection can support compact search and traversal. Aider RepoMap demonstrates graph ranking and token-budgeted selection:
https://aider.chat/docs/repomap.html

Choose this route if it reuses existing code better or beats CGC/Graphify on measured setup cost, query correctness, incremental refresh and token efficiency. Implement only missing parts; do not rewrite existing snapshots/context packs.

### 2.5 SCIP and LSP / Serena — precision layer, not another memory system

- SCIP protocol/indexers: https://github.com/scip-code/scip. The ecosystem includes indexers for Python, TypeScript/JavaScript, Rust, Go, Java/Kotlin/Scala, C/C++ and others. Use only where actual project build/config supports compiler-grade references. Local SCIP indexes do not require deploying the Sourcegraph server.
- Serena: https://github.com/oraios/serena. LSP-backed semantic tools across 40+ languages are useful for on-demand definitions/references/implementations. Serena's main application is GPL-3.0-or-later (SolidLSP component has its own MIT license); do not vendor/bundle without reviewing implications. Treat it as a separate optional developer tool, not the persistent knowledge graph.

### 2.6 Probe — fast local just-in-time retrieval candidate

https://github.com/probelabs/probe  
Probe combines ripgrep-style search with Tree-sitter AST parsing, extracts complete functions/classes, supports token-capped results and can run locally/offline. Its raw MCP mode exposes search/query/extract/symbols; use only these read/query tools. Do not launch the built-in Probe Agent with edit/delegate/bash privileges for repository discovery. It is a retrieval layer, not persistent memory or a strategy/operations catalogue. The upstream repository lists Apache-2.0; audit package dependencies and pin exact versions.

### 2.7 ast-grep — structural pattern utility

https://github.com/ast-grep/ast-grep  
MIT-licensed Tree-sitter-based structural search/lint/codemod utility. Use for precise AST queries and scanner rules when needed; not a persistent knowledge graph and no need to install it if Tree-sitter queries already cover the requirement.

### 2.8 jCodeMunch — license gate

https://github.com/jgravelle/jcodemunch-mcp  
Do not use in a revenue-supporting commercial workflow until current licensing is reviewed and the needed paid rights are explicitly approved. Vendor token-saving figures are not transferable guarantees; compare on the same golden questions.

### 2.9 Decision rule

Run W0A on the exact same SHA and 30–50 golden questions. Compare:
- file/language/artifact coverage and unsupported formats;
- exact symbol definition, callers/callees, path and test links;
- EXTRACTED/COMPILER_RESOLVED vs inferred edges;
- precision/recall, stale detection, rename/delete correctness;
- cold build + incremental update time, p50/p95 query latency, RAM and disk;
- context tokens at 500/1k/2k budgets;
- license/SBOM/security, offline behavior and number of tools exposed to the model.

Adopt **one primary graph backend at most**. SCIP/LSP may add precision for selected language paths. Do not deploy Graphify + CGC + Serena + a vector DB by default.

## 3. Other evidence and data tools

### SQD Portal — bounded read-only on-chain evidence
https://portal.sqd.dev/mcp  
https://sqd.dev/learn/portal-mcp-server-setup/  
Use precise network + block/slot range + field filters + row cap + pagination. Persist query hash, network, window, cursor/page count, retrieval time and coverage. It supplements chain data; it is not automatically exact pool-state, quote, execution or settlement authority.

### Antseer — small analytics subset
https://antseer.ai/docs  
Its documentation describes 65 read-only tools across 12 domains with provenance and a way to restrict exposed tools. Expose only the few needed for one research task (target under 10), not all tools to every agent. Never treat analytics as executable quote, exact lending capacity, settlement/finality or trading authorization.

### DuckDB + Parquet
https://duckdb.org/docs/data/parquet  
Optional local analytics if existing reports cannot answer historical queries. Use projection/filter pushdown and existing ZSTD Parquet/AGG-02 retention owners. Do not add another server/database without measured need.

### Deferred

Mimir, growmos, Neo4j service, remote vector DB, ClickHouse, NATS, remote object storage and autonomous orchestrator are all **deferred** until golden retrieval / storage benchmarks prove a concrete gap. No two semantic-memory products in parallel.

## 4. Tool and app inventory

Inventory every package, SDK, script, binary, CLI command, MCP server/tool, GitHub Action, CI workflow, RPC/data provider, strategy adapter and developer application found in manifests, lock files, imports, config, docs and CI.

For each record: ID, version, source URL, license/SPDX, install method, owner, code entrypoint, used-by edges, tests, permissions, network access, secrets required (names only; never values), status, duplicate candidate, evidence refs.

Statuses: ACTIVE, DEV_ONLY, OPTIONAL, EXPERIMENTAL, DUPLICATE_CANDIDATE, UNREFERENCED_CANDIDATE, DEPRECATED, BLOCKED, UNKNOWN.

Static zero-reference is not enough to delete: inspect dynamic imports, registries, reflection, plugins, workflow triggers, CLI entrypoints, configuration and external consumers. Produce evidence-backed cleanup proposals; deletion must be a separate reviewed PR.

## 5. Reproducible install, MCP and permissions

- Install tools in isolated `uv tool` / pipx environments or a dedicated dev extra, never in production runtime by default.
- Pin exact versions/hashes; retain lock/SBOM/license/NOTICE and install/health-check scripts.
- Do not vendor third-party source unless exact component license is approved, copyright/SPDX is preserved and the copied code is independently tested.
- Do not modify user-global MCP/client settings. Commit only an example profile after review.
- Keep query facade read-only and allowlisted. Do not expose shell/write/index-delete/config-mutating tools to analyst/reviewer profiles.
- No credentials, private keys, seeds or secret values in Git, indexes, reports or context packs.
- External requests require bounded query windows, quotas, provenance and a declared use.

## 6. Context/token efficiency

- Always start from a 300–500 token repo card and one-line catalogues.
- Fetch only 1–3 graph hops relevant to the task; retrieve full function bodies/tests/evidence by ID.
- Suggested task pack: 1k–2k tokens by default; exact model tokenizer budget when available.
- Output paths, qualified symbol names, stable IDs and refs rather than repeated prose.
- Store large raw payloads once in canonical stores; summaries carry IDs/hashes and retrieve on demand.
- Indexing and deterministic labels must not call an LLM. Ambiguous semantic labels are PROPOSED/UNKNOWN until reviewed.

## 7. Access truth

A tool is not "available" because it is in this document. Record installed version, successful local self-check, connected client, granted capabilities and last health time for each actual agent environment. ChatGPT does not automatically receive the local index; provide the pinned context pack, authorized GitHub repository access or an explicitly configured local read-only MCP.
