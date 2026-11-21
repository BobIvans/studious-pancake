# Repo Knowledge Graph: полная карта Studious Pancake без гигантского prompt
## Polyglot symbols, strategies, tools, sources, operations и evidence — один связанный индекс

**Цель:** ChatGPT и coding agents должны уметь за минуты понять, какие идеи, стратегии, данные, приложения и функции уже существуют, как они связаны, что реально работает, что только описано, что не используется и где лежат первичные доказательства.

**Это не ещё одна canonical database и не попытка загрузить весь репозиторий в LLM.** Это versioned, rebuildable read-only projection над текущими владельцами истины и внешними code-intelligence tools.

---

## 1. Архитектура: один каталог связей, несколько владельцев фактов

| Layer | Canonical owner / tool | Результат |
|---|---|---|
| Exact repo snapshot | Git + `src/intelligence/repo_snapshot.py`, manifest/history/coverage | Точный SHA, blob hashes, изменения, исключения |
| Native intelligence | Весь существующий `src/intelligence/` и `context_pack.py` | Существующие snapshots, AST, groups, packs, reports, archive и benchmarks |
| Polyglot code graph | Benchmark Tree-sitter / CodeGraphContext / Graphify; принять только лучший проверенный вариант | Файлы, symbols, imports, calls, inheritance, references, paths |
| Compiler-exact edges | SCIP indexers и/или LSP, только для нужных языков | Definitions, references, implementations и call hierarchy с compiler/language-server evidence |
| Docs/config/tool inventory | Deterministic parsers + Graphify code-only graph where useful | ADR/RFC, roadmap, Markdown links, JSON/YAML/TOML keys, workflows, dependency pins, CLI/MCP manifests |
| Strategy/source catalogue | Existing strategy registry/contracts, source catalog, QPR/DIN, provider governance, economics owners | Идея → стратегия → entrypoint → source/provider/venue/capital → config → tests |
| Operations/evidence | Existing EventEnvelope/ObservabilityStore + AGG-02 + MarketObservation + MarketEpisode | Факт выполнения, cursor/gap, decision, simulation, reconciliation, outcome |
| Context retrieval | Existing context packs + a small read-only query facade | Только нужная подгруппа узлов под точный byte/token budget |

Не заменять существующие truth owners графовой БД. Допустим только **derived cache/index**, который можно полностью перестроить из Git SHA и canonical data references.

## 2. Что именно должно индексироваться

Индекс — полный inventory Git tree, а не только Python-файлы:

- source: modules, packages, functions, methods, classes, signatures, imports, call/reference edges, inheritance, public APIs;
- strategy: идея из документа, strategy ID, версия, implementation status, entrypoints, planner/compiler/simulator path, economics/flash-capital dependencies, network/venue/pool, tests, runtime episodes;
- data sources/providers: source IDs, adapters, schemas, networks, fields, cursors, freshness, quality, quotas, provenance, consumers and qualification;
- tools/apps: Python/Node/Rust packages, CLI entrypoints, scripts, MCP servers and tools, plugins, GitHub Actions, build/test tools, Docker/infra, SDKs, RPC/data vendors;
- config: TOML/YAML/JSON/ENV-key names, schemas, defaults, feature flags, dependency and lock files; never index secret values;
- docs: Markdown/RST/TXT, ADR/RFC, roadmap, issue/PR references, design claims and direct links to files/symbols;
- tests: test symbols, fixtures, contracts, replay scenarios, coverage and owning implementation;
- runtime evidence: event types/reason codes/trace IDs/attempt IDs, observation IDs, episode IDs and evidence refs, linked to exact producer symbols where proven;
- Git history: introduced/changed/deleted/superseded symbols and the PR/commit that changed them.

**Охват и пробелы обязательны.** Каждый file type/parser получает SUPPORTED, PARTIAL, UNSUPPORTED или EXCLUDED_WITH_REASON. Не делать вид, что binary fixtures, dynamic imports, generated files или external services полностью поняты статическим индексом.

## 3. Knowledge graph contract

### Node types

`RepoSnapshot`, `File`, `Module`, `Symbol`, `Test`, `StrategyIdea`, `StrategyVersion`, `Config`, `DataSource`, `Provider`, `Venue`, `Protocol`, `FlashCapitalSource`, `Tool`, `McpServer`, `McpTool`, `CliCommand`, `Dependency`, `EventType`, `ReasonCode`, `OperationEpisode`, `Observation`, `Experiment`, `Evidence`, `Task`, `Worktree`, `Commit`, `PullRequest`.

### Edge types

`DEFINES`, `CALLS`, `REFERENCES`, `IMPORTS`, `IMPLEMENTS`, `TESTED_BY`, `CONFIGURED_BY`, `USES_STRATEGY`, `CONSUMES_SOURCE`, `PROVIDES_DATA_TO`, `ROUTES_THROUGH`, `FUNDED_BY`, `PRODUCES_EVENT`, `CORRELATES_WITH`, `OBSERVED_IN`, `FEEDS`, `REPLAYS_AS`, `REJECTS_WITH`, `DEPENDS_ON`, `CONFLICTS_WITH`, `DOCUMENTED_BY`, `INTRODUCED_BY`, `SUPERSEDES`, `POTENTIALLY_UNUSED`.

### Provenance on every node/edge

Every relation must carry:
- `evidence_kind`: STATIC_EXTRACTED | COMPILER_RESOLVED | CANONICAL_REGISTRY | RUNTIME_OBSERVED | DOC_CLAIM | HUMAN_CONFIRMED | LLM_PROPOSED;
- exact `repo_sha`, path, symbol/qualified name, line span or byte range, source blob hash;
- parser/indexer name + version and extraction timestamp;
- `status`: PRESENT | PARTIAL | MISSING | UNKNOWN, with reason;
- optional external source URL, retrieval time, version/license and content hash.

Do not collapse these classes. A call edge inferred by Tree-sitter is not compiler proof; a roadmap sentence is not a wired implementation; an LLM label is never VERIFIED until reviewed. If no evidence exists, return UNKNOWN.

### Stable identities

Use deterministic IDs based on entity kind + canonical namespace/path + qualified symbol/signature. Keep content hash and repo SHA separately. Line numbers are locators, not identities. For a rename/move, store an alias/supersedes edge with before/after SHAs; ambiguous matches become NEEDS_REVIEW.

## 4. Compact retrieval, not full-context dumping

The index may contain millions of facts. LLM context should contain only a ranked answer slice:

| Tier | Target size | Contents |
|---|---:|---|
| T0 Repo card | 300–500 tokens | Repo SHA, subsystem map, core owners, index freshness, major gaps |
| T1 Catalogue | One compact line per strategy/source/provider/tool | IDs + status + symbol/file links + dependencies + tests + evidence pointers |
| T2 Task subgraph | Default 1k–2k tokens, configurable | 1–3 graph hops, exact signatures, important callers/callees, config, tests, linked docs |
| T3 Evidence fetch | On demand | Exact code ranges, full docs, log/event/observation payload by ID |

Rank by query relevance + dependency/call graph importance + runtime evidence recency, then pack to an actual model tokenizer budget when available. Otherwise report a conservative byte estimate. Return continuation cursors rather than silently truncating. Never put the whole graph into a system prompt.

### One-line strategy record contract

```text
STRAT <id> | status=<IDEA/IMPLEMENTED/WIRED/QUALIFIED/BLOCKED/RETIRED/UNKNOWN> |
entry=<file::qualified_symbol> | path=<caller→callee IDs> | config=<IDs> |
sources=<source/provider IDs> | venues=<IDs> | capital=<IDs> |
tests=<test IDs> | episodes=<evidence IDs> | gaps=<UNKNOWN fields>
```

Produce equivalent compact rows for every `SOURCE`, `PROVIDER`, `TOOL`, `MCP`, `CLI`, `CONFIG` and `PROTOCOL`. The row must link to graph nodes; do not stuff code bodies into it.

## 5. Tool bake-off: choose a minimal stack, don't install everything

| Candidate | Best use | Decision for Studious |
|---|---|---|
| Native Local Intelligence V2 | Exact snapshots, current Python AST, bounded packs, existing retention and reports | Always keep; extend instead of rewriting |
| Tree-sitter | Fast deterministic multi-language syntax extraction | Base parser candidate; benchmark actual language and grammar coverage |
| CodeGraphContext (CGC) | CLI/MCP call graph: callers, callees, chains, imports, inheritance; supports Solidity and broad languages | Top candidate for code graph; MIT main project; test embedded DB footprint, indexing accuracy, MCP tool count and transitive licenses |
| Graphify | Tree-sitter graph across ~40 languages; communities, paths, explain/query; can connect docs, SQL schemas, configs and PDF/media | Top candidate for wider repo knowledge map; run code-only/local first. Docs/media semantic pass may invoke a model; disable unless explicitly approved |
| Probe | Local AST-aware search, complete function/class extraction, token-capped output, raw read-only MCP search/query/extract/symbols; zero-index setup | Strong low-cost just-in-time retrieval candidate; not a persistent knowledge graph. Do not enable its built-in edit/delegate/bash agent |
| ast-grep | Fast Tree-sitter structural pattern search/lint/codemod | Optional surgical query/scanner; useful for exact patterns, not a persistent repository knowledge graph |
| SCIP | Standard symbol/reference index format with language-specific indexers | Add for exact references where the language/build supports it; no Sourcegraph server is required just to create/consume local index files |
| Serena / LSP | On-demand go-to-definition, references, implementations and symbol operations over 40+ LSP language backends | Optional query layer, not the persistent repository graph. Main Serena application is GPL-3.0-or-later; do not vendor/bundle before license review |
| Aider RepoMap / Personalized PageRank | Rank important symbols/files into a small context budget | Benchmark ranking idea or reusable algorithm; not a second canonical index |
| jCodeMunch | Symbol-level retrieval | Exclude from commercial/revenue-supporting use until its current license is reviewed and paid rights are approved |

Current upstream references:
- CGC: https://github.com/CodeGraphContext/CodeGraphContext
- Graphify: https://github.com/Graphify-Labs/graphify
- SCIP: https://github.com/scip-code/scip
- Serena: https://github.com/oraios/serena
- Aider RepoMap: https://aider.chat/docs/repomap.html
- Tree-sitter: https://github.com/tree-sitter/tree-sitter

Important install corrections:
- Graphify's current official PyPI package is `graphifyy` (two y's), installed separately with `uv tool install graphifyy`; its Codex skill setup is a separate action. Do not rely on the old `graphifyy[mcp]` command. Do not let the install wizard silently change repo/client config without review.
- CGC's package/CLI is `codegraphcontext` / `cgc`; install it only in an isolated developer tool environment, not the bot runtime.
- Check the exact version, package lock, all transitive dependency licenses, security advisories and OS/Python compatibility before adopting either.
- Graphify's repository currently contains Apache-2.0 and MIT license files; inspect which component is used before copying code. CGC's main repository identifies MIT; inspect transitive packages separately.
- Never use remote Graphify Cloud or send repository contents to a third party for this task.

### Candidate benchmark

Run candidates on the **same clean pinned SHA** and a fixed golden set (30–50 questions), including:
1. strategy list/status and duplicate strategy idea detection;
2. exact strategy entrypoint → callers/callees → planner/compiler/simulator;
3. strategy → config → provider/source/venue/flash-capital dependencies;
4. source adapter → consumer → tests → evidence contract;
5. MCP/CLI tool → implementation symbol → permissions → tests;
6. event producer → event field → ObservabilityStore/export/replay;
7. observation → candidate → episode → reconciliation outcome;
8. changed function → impacted callers/tests/docs/configs;
9. dead-code candidate and dynamic-registration false-positive checks;
10. compact answer under 500 / 1,000 / 2,000 tokens.

Measure exact source-link correctness, edge precision/recall, file/parser coverage, incremental update correctness, stale-index detection, build time, p50/p95 query latency, peak RAM, disk bytes, pack token count and unsupported/unknown rates. Use identical questions and output budgets. No vendor benchmark claims substitute for local results.

## 6. Index lifecycle and automation

1. On clean clone, build an index bound to exact Git tree SHA and tool versions.
2. On commit/branch switch/PR, hash changed files and re-index only affected files and dependent graph nodes; handle deletions/renames explicitly.
3. CI validates index freshness, source refs, no dangling edges, no secrets, schema compatibility, and emits a compact artifact/summary.
4. Coding agent refreshes the index after implementation and includes the graph delta + test impact in WORK_RESULT.
5. ChatGPT requests/upload the exact context pack for the active SHA. A local index does **not** automatically appear in a new ChatGPT chat.
6. Generated DBs/caches stay outside tracked source (or in a clearly ignored build cache). Commit schemas, tool lock, reproducible commands, compact manifests and tests—not huge opaque index binaries or raw runtime payloads.

Refresh must be deterministic and idempotent. If index SHA differs from checked-out code, fail closed with STALE_INDEX. Keep branch-specific indexes isolated to avoid mixing worktrees.

## 7. Tool/app inventory and safe cleanup

Build a searchable inventory across package manifests, lock files, imports, entrypoints, scripts, workflows, Docker, MCP configs, SDKs, RPC providers, strategy adapters and docs. For each item record:
`tool_id, name, kind, version, license, install_source, used_by, entrypoints, permissions, network_access, secrets_required, tests, owner, status, duplicate_of, evidence_refs`.

Allowed status: ACTIVE, DEV_ONLY, OPTIONAL, EXPERIMENTAL, DUPLICATE_CANDIDATE, UNREFERENCED_CANDIDATE, DEPRECATED, BLOCKED, UNKNOWN.

Identify dead/duplicate apps and functions, but **never auto-delete**. Static zero-reference does not prove unused: inspect dynamic imports, registries, reflection, plugins, workflow invocations, runtime config, CLI entrypoints and external consumers. Produce deletion recommendations with evidence and blast radius; actual removal goes through a separate reviewed PR and full tests.

Do not copy whole third-party projects or paste functions into `src/` just to get started. Prefer isolated pinned CLI/MCP tools + a thin adapter. Copy a minimal code fragment only when integration is impossible, the exact source/license permits it, SPDX/copyright/NOTICE are preserved, security is reviewed, and the copied code has an owner and tests.

## 8. Completion criteria

A useful first increment is working only when:
- one command builds/refreshes the map from an exact Git SHA;
- a compact T0/T1 overview lists all discovered strategies, tools/apps, providers, sources and subsystems with exact links;
- a query returns symbol definition, callers/callees, short path, dependencies and owning tests;
- source/config/doc/tool links are connected where explicitly evidenced;
- every relation shows provenance/epistemic status;
- stale indexes and unsupported formats are visible;
- new commits/PRs produce an incremental index diff automatically in local workflow/CI;
- context packs obey a hard token/byte budget and can continue by cursor;
- tests prove reproducibility, secret exclusion, no cross-branch contamination and no invented relationships.

The full runtime/strategy correlation remains layered on the existing OCA work packages; the code graph alone does not prove a strategy was executed or profitable.
