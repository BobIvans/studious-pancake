# TOKEN_EFFICIENCY_PLAYBOOK — практический SOTA-стек для Studious Pancake
## Что применять из списка, что скачать готовым, что не строить и как минимизировать токены

**Главный ответ:** не строить собственный parser/graph/context engine с нуля и не ставить все найденные приложения вместе. Быстрейший путь — сохранить Studious Local Intelligence V2 как orchestrator/контракт snapshot+packs, подключить 1 готовый persistent code-graph candidate, 1 лёгкий just-in-time extractor и при необходимости compiler-grade indexers. Затем написать только тонкий adapter, Web3-specific catalogue/evidence joins и тесты.

Цель — не минимальные токены любой ценой, а **минимальные токены при достаточной полноте, точности и проверяемости**. Слишком агрессивное удаление implementation bodies скрывает алгоритм, условия, пограничные случаи и ошибочные решения.

---

## 1. Финальная layered architecture

| Layer | Стратегия | Рекомендуемая реализация |
|---|---|---|
| L0 Snapshot identity | Привязать всё к точному Git tree/commit/blob SHA | Git itself + existing `repo_snapshot.py`; не добавлять вторую snapshot engine |
| L1 Inventory | Все файлы, языки, пакеты, scripts, tools, MCP, CI, configs, docs, strategy ideas, data sources | Existing repo manifest + deterministic inventory parsers |
| L2 Syntax/signatures | Извлекать imports, declarations, symbol IDs, signatures, file/byte ranges | Existing Python AST + Tree-sitter candidate (Graphify/CGC/Tree-sitter); bodies не передавать в LLM на этом этапе |
| L3 Semantic cross-file references | Exact definitions/references/implementations where compiler supports them | SCIP indexers / LSP selectively; don't claim compiler precision without successful index |
| L4 Call/dependency graph | Call/import/inheritance/caller/callee/impact paths | Pick one primary: CGC OR Graphify OR a measured native Tree-sitter graph |
| L5 Fast retrieval | Search full relevant function/class with hard token budget, no large pre-index required | Probe raw CLI/MCP; fallback grep-ast/TreeContext. No vector DB required initially |
| L6 Ranking | Select relevant graph nodes for current task | Personalized PageRank / Aider RepoMap-style relevance ranking as query-time algorithm, not another database |
| L7 Deep program analysis | CFG/DFG, control/data dependence, taint and source-to-sink paths | Optional Joern/CPG profile only for security/complex data-flow questions |
| L8 Web3 domain graph | Strategy/source/provider/venue/lender/pool/config/test links and lifecycle | Thin Studious-specific projection over existing canonical registries/contracts |
| L9 Runtime evidence | Market observations, events, attempts, simulation, reconciliation, paper outcomes | Existing EventEnvelope + AGG-02 + MarketObservation + MarketEpisode; read-only join |
| L10 Context assembly | Pack only the relevant subgraph and evidence under an actual budget | Extend existing `context_pack.py`; output IDs/links first, exact code/evidence on demand |
| L11 Handoff/cache | Worktree diff, context freshness, repeated stable prefix, per-SHA query/index cache | CI/local refresh + Work Result Receipt + stable prompt prefix where API supports it |

Do not collapse these layers into one massive GraphRAG or a prompt containing the whole map.

## 2. Which techniques from the original pasted file are required?

| Original technique | Decision | Correct application |
|---|---|---|
| Tree-sitter `tags.scm` / AST symbol extraction | **YES — core** | Definitions, signatures, imports, call candidates, byte ranges. Preserve parser/language and relation confidence. Keep source bodies accessible. |
| 95–99% compression | **NOT A GUARANTEE** | May occur on some signature-only files, but loses implementation logic. Treat signatures as navigation index, not replacement for source/evidence. Measure on this repo. |
| Personalized PageRank | **YES — ranking** | Relevance/centrality ranking based on active query, changed files, mentioned symbols and dependencies. Aider's implementation is a useful reference; no need to run Aider as a separate database. |
| Binary search to fit token budget | **YES — packing method** | Select ranked records until exact tokenizer budget; also account for tool-output JSON/schema overhead. Implement/borrow small algorithm, test hard upper bound. |
| LSP / SCIP | **YES — selectively** | Compiler-grade definitions/references/implementations when compatible indexers/builds work. SCIP is a format/protocol; it does not magically produce exact indexes without a working language indexer. |
| MCP code graph server | **YES — narrow read-only surface** | Search, symbol, callers, callees, path, impact and pack query. Do not expose server administration/edit/delete/shell tools to analyst. |
| Lazy/on-demand traversal | **YES — essential** | Start with repo card + one-line strategy/tool catalogue; query 1–3 graph hops; fetch body/tests/events only when needed. |
| grep-ast / TreeContext scope elision | **YES — retrieval feature** | Return target function plus enclosing context; collapse unrelated siblings. Probe can be primary extractor; avoid running redundant extractors in every request. |
| Code Property Graph / CFG / DFG | **OPTIONAL DEEP PROFILE** | Needed for control/data-flow, taint, complex source→sink/security analysis; not mandatory for everyday symbol navigation. Use Joern/CPG benchmark when real questions need it. |
| Glean | **DEFER** | Powerful fact-collection/query system but higher adoption/maintenance cost. Consider if multiple repositories, language-specific indexers and query volume justify it. SCIP can be consumed without deploying Glean. |
| Prompt caching | **YES WHEN API SUPPORTS IT** | Keep static system/developer/tool schema prefix byte-for-byte stable; put dynamic repo SHA, task and result later. Cache reduces repeated computation/cost, not the amount of code needed to answer. ChatGPT UI/new chats do not expose a repo-controlled cache guarantee. |
| Tree-sitter + SQLite + cache | **YES AS FALLBACK / ADAPTER** | Only if existing Local Intelligence + chosen graph tool cannot meet requirements. Use Git blob/tree hashes and changed-file diff; no separate Merkle-tree framework at first. |
| Graph-RAG + vector embeddings | **SELECTIVE, NOT DEFAULT** | Start with lexical/BM25 + graph + metadata. Add embeddings only for concept-level search across large research/docs corpus after measured recall gap. Do not vectorize all raw source code by default. |

## 3. Tool shortlist — install for an isolated bake-off, not all in production

### A. Native Studious Local Intelligence V2 — keep as orchestrator

It already owns exact snapshots, Python AST source records, repo manifests/groups/history/coverage, context packs, archive/recovery, evidence references, benchmarks and data retention/reporting. It is repo-specific and should remain the stable interface.

First measure real CLI/test status and uncovered languages. Do not rewrite it or assume every documented feature is wired.

### B. CodeGraphContext (CGC) — first persistent call-graph candidate

https://github.com/CodeGraphContext/CodeGraphContext  
MIT main repository (verify transitive dependencies). Current documentation advertises Tree-sitter + optional SCIP, CLI/MCP/HTTP queries, callers/callees/call chains/imports/inheritance and 23 languages, with an embedded graph backend.

Why test it first: close match for exact function/call relationships, a local index and query API. Its current README also advertises `cgc watch` live file watching, which may provide a developer-worktree refresh loop. Treat that watcher as a convenience only: GitHub push/PR/main CI and nightly deterministic validation remain the authoritative freshness checks. Its own docs describe the graph as Tree-sitter/SCIP-derived; Tree-sitter-only resolution is syntactic and may misresolve same-name/dynamic calls. Treat any advertised call accuracy as a vendor benchmark, not a Studious result. Check current docs/version and unsupported config languages before adoption.

Use CLI/indexer first. Do not enable every MCP/admin operation. It is one candidate for the single primary persistent code graph.

### C. Graphify — broad graph candidate for code + docs/configs

https://github.com/Graphify-Labs/graphify  
Current docs describe local Tree-sitter code extraction (about 40 languages), call/import/inheritance edges and explicit EXTRACTED versus INFERRED provenance. It also connects docs, SQL schemas and configs. Code-only parsing is local/no-LLM; docs/media semantic extraction may call a model/backend and stays OFF initially.

Why test: better fit than a code-only symbol server when roadmaps, ADRs, configs, schemas and architecture notes are part of the knowledge base. It may be the single primary graph if its function-call graph passes exactness tests.

Official package in current docs: `graphifyy`. Keep installation isolated, pin the version, inspect setup changes and run code-only on the same SHA.

### D. Probe — immediate JIT extraction candidate

https://github.com/probelabs/probe  
Current README describes no-index Tree-sitter structural search, full function/class extraction, boolean/BM25 ranking, token caps and raw MCP mode. Useful for fast targeted code retrieval with little setup.

Use raw MCP/CLI `search/query/extract` only. Do not start the built-in autonomous agent/edit/delegate/bash mode for read-only indexing. Probe is not the persistent repo graph and does not map strategy outcomes/data providers by itself.

### E. SCIP / LSP — exactness for relevant languages

https://scip-code.org/  
SCIP standardizes symbol definitions/references/implementations, but each language needs a working indexer and suitable build/config. Add only where it gives better accuracy than Tree-sitter and has reproducible CI commands. LSP can be kept as a developer-time query layer if compiler indexes aren't feasible.

Serena's main app is GPL-3.0-or-later; SolidLSP component is MIT. Do not bundle the complete Serena app without license review. Direct language servers/SCIP indexers may be simpler for the required languages.

### F. Aider RepoMap + grep-ast — borrow ranking/slicing ideas

https://github.com/Aider-AI/aider  
https://github.com/Aider-AI/grep-ast

Aider RepoMap ranks important definitions/dependencies into a token-limited map; it is primarily a file-dependency/tag relevance map, not guaranteed compiler-exact call graph. Use its ranking strategy as a reference. grep-ast returns matches with enclosing AST context; use as fallback if Probe's extraction isn't adequate. Do not load Aider solely to get another copy of the graph.

### G. Repomix / Gitingest — export tools, not the knowledge system

https://github.com/yamadashy/repomix  
https://github.com/cyclotruc/gitingest

Useful to produce a one-off repo snapshot/prompt file or fallback export. Repomix's Tree-sitter `--compress` removes method bodies, loops and conditions; its docs call compression experimental. Therefore it is useful for architecture overview only, never the only evidence for strategy logic. Do not use a giant repo pack as routine context.

### H. Joern / Code Property Graph — advanced optional track

https://github.com/joernio/joern  
Joern provides layered code-property graphs, control/data-flow queries and taint analysis for multiple languages. This is a valuable deeper-analysis tool for protocol adapters, untrusted-input flow, transaction construction and security-critical logic. Its Scala/CPG toolchain adds operational complexity; run only as a targeted optional profile after defining actual queries. Not required for first general repo map.

### I. Glean — enterprise-scale alternative, defer

https://github.com/facebookincubator/Glean  
BSD-licensed source-code fact collection/query system with Angle. It is designed for large-scale code facts; upstream support is strongest for selected languages and SCIP/LSIF ingestion. Powerful but not the fastest default for this single repo when existing Local Intelligence and simpler local graph tools suffice.

### J. Exclude or defer candidates

- GitNexus: current upstream license surfaced as PolyForm Noncommercial 1.0.0; do not use for a revenue-generating flashloan workflow without commercial license. Its `analyze` may also install skills/hooks and modify agent files; even where an index-only flag exists, evaluate only in scratch branch and inspect diff.
- jCodeMunch: previously identified commercial licensing restriction; exclude pending explicit license approval.
- Mimir/growmos/CodeGraphRAG/codeTree/codeprysm/infiniloom/Agentic Codebase/repomap alternatives: do not install as a bundle. Add an individual candidate only when it fills a measured gap and its license/health can be verified.
- Neo4j server, remote vector DB, ClickHouse, NATS, remote graph gateway: not needed for first local index.

### K. New persistent local graph daemons — add to same-SHA bake-off

These are important candidates from the latest research wave. None is accepted until tested against Studious's actual Python/JSON/YAML/TOML/docs/workflow/SQL mix, plus installed tooling and build environments.

| Candidate | What current upstream says | Fit / cautions |
|---|---|---|
| **DeusData/codebase-memory-mcp (CBM)** — https://github.com/DeusData/codebase-memory-mcp | Native C backend; 17 MCP tools; 164 vendored Tree-sitter grammars; local persistent graph across code/docs/config/infrastructure; Hybrid LSP refines calls for supported languages; one shared coordination daemon across multiple agent clients; MIT | **Top candidate to test first.** Closest to C daemon + multi-agent shared graph + docs/config/infra. Hybrid LSP only covers selected languages; its own README distinguishes syntax-only base from per-language type resolution. Installer enables hooks and writes client/agent integration files by default: evaluate in isolated HOME/client config and review every diff; do not silently mutate user-global configs. |
| **colbymchenry/codegraph** — https://github.com/colbymchenry/codegraph | Native Rust engine, self-contained client binaries, SQLite/WAL graph, file watcher/debounce, MCP and CLI, 38-ish language coverage claims with language-by-language support table, dynamic-dispatch/framework edges, impact analysis; MIT; telemetry has explicit opt-out | **Top Rust daemon competitor.** Good candidate for call-flow/source retrieval and warm shared index. Turn telemetry off for proprietary code. Installer can write MCP and AGENTS/CLAUDE instructions; use isolated profile and inspect diff. Check platform/WAL/WSL behavior and exact language support. |
| **SylphxAI/repomap** — https://github.com/SylphxAI/repomap | Rust binary, local graph, search/call paths/impact, BM25/local embeddings, MCP and graph UI, per-file cached incremental updates, read-only; MIT | Lightweight candidate with a narrow read-only surface. Smaller project/activity and language coverage must be measured on Studious; its own benchmark is not a Studious guarantee. |
| **sdsrss/code-graph-mcp** — https://github.com/sdsrss/code-graph-mcp | Rust + embedded SQLite/FTS5 + optional sqlite-vec, BLAKE3 Merkle change detection + watcher, recursive caller/callee traversal, L0–L3 context tiers, 19 language labels with materially different depth tiers; MIT | **Strong token/incremental candidate.** Verify full-depth vs smoke/limited parsing for the exact repo file types. Its published sub-millisecond query and ~28 ms no-op numbers are measured on its own 283-file repository; do not project them to Studious. |
| **ThinkyMiner/codeTree** — https://github.com/ThinkyMiner/codeTree | Python MCP, SQLite graph, Tree-sitter, 23 tools, ~11 languages, change-impact and dataflow/taint queries; MIT | Candidate for data-flow/taint and Python-friendly setup; compare its MCP surface and parser coverage. Do not add as a second graph unless it wins the bake-off. |
| **agentralabs/agentic-codebase** — https://github.com/agentralabs/agentic-codebase | Rust semantic graph compiled to portable `.acb` binary; SQLite-backed query, CLI and MCP; MIT; supports Python/Rust/TS/JS/Go/C++/Java/C# | Test as a **portable graph artifact / distribution format**, not necessarily as primary live watcher. Inspect binary schema evolution, dynamic/runtime limits and whether its benchmark represents real repo queries. |
| **entireio/entire-graph** — https://github.com/entireio/entire-graph | Local Tree-sitter map, 36 semantic-parsed languages plus inventory-only file types, diff/impact/export and token budgets; MIT; requires Entire CLI and does not expose its own MCP server or background daemon | Potential PR/change-impact side tool, not the primary ChatGPT MCP graph. Run only if Entire CLI fits the agent workflow; no claim of background refresh. |
| **mariusei/scantool** — https://github.com/mariusei/scantool | On-demand Tree-sitter, no persistent graph; parse cache keyed by Git blob ID, multi-resolution function skeletons, exact focus by symbol/ref and explicit coverage line; MIT | **Strong JIT complement** to one persistent graph. Useful for historical refs and avoiding repeated parse cost without storing a second graph. Benchmark its skeleton fidelity on strategy code and tests. |
| **achatainga/mcp-code-context** — https://github.com/achatainga/mcp-code-context | WASM Tree-sitter + SQLite MCP, multi-resolution AST read and surgical symbol write; MIT; current README says 5 principal languages and a 2,000-file cap | Read-only extraction can be tested as a narrow alternative, but do not expose write/rename/remove tools to analyst agents. Regex cross-file rename and no automatic syntax validation make its editing surface inappropriate as a default code writer. |
| **vitali87/code-graph-rag** — https://github.com/vitali87/code-graph-rag | Tree-sitter + optional compiler frontends (libclang/go/types/Roslyn/javac/Jedi) + embedded SQLite graph; runtime traces can enrich graph where supplied; MIT | Optional advanced comparison for compiler/runtime edges. Its natural-language query/edit workflow uses model reasoning; separate that from deterministic indexing. Runtime tracing is only available if instrumentation really emits traces. |
| **stakwork/stakgraph** — https://github.com/stakwork/stakgraph | Rust Tree-sitter + LSP graph, in-memory or Neo4j backend, MCP, vector search and optional LLM agents; multi-repo endpoint/request links | Defer unless cross-repo services/route links become a measured requirement. Neo4j + embeddings + agents adds more moving parts than needed for the first local index. |

**Selection update:** primary graph bake-off must now include at least CBM, colbymchenry/codegraph, Graphify, CGC and one compact Rust graph (repomap or code-graph-mcp) on exactly the same SHA/question set. Probe or Scantool may complement the chosen primary graph as JIT extraction because they address a different layer. Do not run all graph MCP servers concurrently in an agent's normal tool list.

### L. Multi-resolution AST context is mandatory

Adopt explicit retrieval tiers rather than one generic "compact" mode:
- `FULL`: target function/class body and directly relevant tests/config/evidence, never lossy.
- `SKELETON`: directly related callers/callees/dependencies with signatures, docstrings, type contracts, key branches/calls/returns as safely extracted.
- `REFERENCE`: outer neighborhood with IDs, qualified names, hashes and links only.
- `OVERVIEW`: modules/directories/communities and short purpose lines.

For a task, return target node as FULL, immediate dependency ring as SKELETON and wider graph as REFERENCE. A context budget may demote non-target neighbors, but must never silently skeletonize the target implementation required to reason about its algorithm. Provide `expand(node_id, level=FULL)` or equivalent with exact source SHA/range. Keep a coverage/exclusions trailer in every answer; Scantool is a useful example of blob-SHA cache + explicit coverage counts.

### M. Continuous graph and label-store evolution — requirements beyond parsing

A growing repository needs more than file watching:

1. **Content-addressed incremental cache:** key parse output by (Git blob SHA, parser/grammar version, parser config); key graph output by (repo tree SHA, graph schema version, backend version). Reuse unchanged blobs across branches/worktrees. Never use mtime alone as truth.
2. **Dependency-aware invalidation:** changed signature/type/config/schema invalidates dependent call/reference/test/context nodes; body-only changes update the target and behavior fingerprint. Recompute PageRank/community clusters only for affected components or scheduled full refresh.
3. **Temporal/bitemporal provenance:** every node/edge/label has `valid_from_sha`, `valid_to_sha` (or active range), `recorded_at`, source-data time, parser/schema version and provenance. Support `as_of(repo_sha, event_time)` so an old paper/shadow attempt is explained using the exact code/config/strategy labels active then, not today's code.
4. **Schema evolution:** version graph schema and label ontology; migrations are deterministic, reversible where possible, tested on prior snapshots, and preserve old event/edge provenance. Never silently reinterpret historical labels after a schema change.
5. **Label store lifecycle:** typed labels (strategy, provider, venue, source, protocol, risk check, execution stage, capability, tool) carry `label_id`, ontology_version, source evidence, source SHA/hash, author (rule/human/LLM), confidence/evidence kind, approval status, valid time and review trigger. Statuses PROPOSED, VERIFIED, STALE, NEEDS_REVIEW, RETIRED. Revalidate labels when source symbols/config/registry entries change. LLM labels never become VERIFIED without review.
6. **Runtime-vs-static edge separation:** keep `STATIC_CALLS`, `COMPILER_RESOLVED_CALLS`, `RUNTIME_OBSERVED_CALLS` distinct. Dynamic traces add observed edges with repo SHA, trace/span/logsite, time window and sampling/coverage; they do not overwrite static edges.
7. **Cross-repo federation:** namespace node IDs by repository identity + commit/ref; link package dependencies, HTTP routes, schemas, shared SDKs and submodules. Start with this repo; add neighbouring repositories only when actual consumers/dependencies are discovered.
8. **Tool/MCP capability registry:** record tool server + method + read/write/network/secret capabilities, version, license, owner, health, required auth and source. Query facade returns only allowlisted read tools to analysts; write-capable tools are a separate human-approved profile.
9. **Resource budgets:** background indexing has CPU/RAM/IO quotas, debounced/coalesced change queues, a single writer per index, cancellation/restart, queue depth and stale-index alarms. Never let full index rebuild contend with the bot's market collection/operation capture path.
10. **Data quality SLO:** track parser coverage, unresolved/dangling links, stale age, label drift, runtime producer/stage coverage, event loss/gaps, index build/query p50/p95/p99, disk growth and token cost. A green process exit is not proof of complete coverage.

These requirements must be represented in W0B/W1/W7/W10/W11 acceptance and in CI reports, not left as future prose only.

### N. Storage policy for a continuously growing repository

- Source of truth remains Git and canonical runtime stores; the graph contains IDs, edges, signatures, ranges, hashes and compact metadata, not redundant copies of every source file and raw event.
- Deduplicate by content hash; retain blobs once per canonical owner, not once per strategy label or graph edge.
- Hot: SQLite graph/index and recent query projections. Warm: bounded per-SHA snapshots/caches and active episodes. Cold: existing Parquet + ZSTD/archive owners with checksums, schema version, row counts, time/slot ranges and replay manifests.
- Keep full payloads only when they are decision-relevant or required by source contract/retention policy. All decision facts, rejections, gaps, corrections and terminal outcomes remain; repetitive debug can be sampled with explicit counts/policy.
- Define byte budgets, index growth/day, compression ratio, page-cache/WAL/checkpoint behavior, backup/restore and disk-pressure admission. Pressure blocks new governed ingestion before pinned evidence is deleted.
- Portable export includes graph schema + compact index manifests + Git commit + JSONL operation events + existing Parquet datasets + hashes and replay receipts. Do not dump giant binary DB into Git.

## 4. The actual retrieval algorithm

For every user task, build packs in stages:

### T0 — repo card (target 300–500 tokens)
`repo_sha, index_generation, main subsystems, canonical owners, active strategy count, data/provider/tool counts, coverage gaps, stale warnings`.

### T1 — one-line domain catalogue (only relevant rows)
`STRAT id | status | entrypoint | source/provider/venue/capital IDs | tests | outcome refs | gaps`.

Same row format for source/provider/protocol/venue/tool/MCP/CLI/config. Index all rows locally; send only relevant rows in the first pack. Offer a compact full catalogue as a separate request.

### T2 — task graph slice (target 1,000–2,000 tokens)
Search terms/BM25 + active files/mentioned symbols + graph expansion 1–3 hops + PageRank/call centrality + ownership/test impact. Include signatures and exact file/symbol IDs, but not all function bodies.

### T3 — evidence payload (fetch only what the answer requires)
Exact function body, relevant config ranges, tests, docs, event payload, market observation, episode, raw response hash and replay refs. Use scope-aware AST slicing (Probe/grep-ast) and only expand sibling nodes when needed.

### T4 — continuation / deep audit
If evidence is insufficient, retrieve the next relevant slice by cursor. Never silently truncate or pretend the pack is exhaustive.

Budget must be an actual model-token count where the target tokenizer is available; otherwise state BYTE_ESTIMATE, not TOKEN_COUNT. Keep evidence IDs and citations even when summaries are compressed. The answer must say which parts of the repo were not indexed.

## 5. Query-time ranking and selection

Rank candidate nodes using a deterministic weighted score, tunable by task:
- explicit user mentions / changed symbols / active task paths;
- direct callers/callees and 1–3-hop neighbourhood;
- dependency centrality/PageRank;
- owning tests/contracts/configs;
- canonical strategy/provider/source links;
- runtime evidence relevance and recency (only where timestamps and repo/data generation align);
- negative/contradictory/unknown evidence, not only positive hits.

Use deterministic BM25/lexical search + graph traversal first. Embeddings can supplement docs/research semantic discovery, but must never determine exact code links or override source evidence. LLM can propose semantic tags; they remain PROPOSED until reviewed.

Use a hard pack budget with binary-search/greedy-fit over ranked records. Never compress away identity, version, hashes, test status, safety constraints or uncertainty.

## 6. Incremental index and caching

- Git commit/tree/blob hashes already provide content-addressed identity. Re-index only added/changed files and affected dependency nodes; process renames/deletes explicitly. Do not add custom Merkle infrastructure until Git diff proves insufficient.
- Cache parse results by (blob hash, parser/version/config); graph result by (repo SHA, graph schema, tool versions); context query result by (repo SHA, data generation, query hash, pack schema, budget).
- Never reuse a result across different branch SHA or data generation. Dirty worktree => explicit DIRTY_SNAPSHOT or index from a hashed working-tree snapshot.
- Keep a stable system/developer preamble and stable tool schemas. Put dynamic SHA/query/evidence after that prefix. Use provider prompt caching only when the runtime/API supports it; verify cache-read metrics. Prompt caching saves repeated processing/cost, not context length, and ChatGPT UI does not promise user-controlled prefix caching.
- Avoid timestamps/random IDs inside reusable prefix. Keep generated T0 card outside the stable prefix if it changes frequently.

## 7. Exact all-repo inventory and safe cleanup

Build deterministic inventory for every Git-tracked artifact and accessible project knowledge source, not only imports. Include archived/closed records where visible and mark inaccessible sources UNKNOWN. Specifically cover:
- GitHub Issues/PRs/reviews/commit history/release notes for strategy hypotheses, rejected alternatives and superseded plans;
- local repo content and accessible MCP/app config manifests.

Also build deterministic inventory for:
- packages/dependencies and versions/locks/licenses;
- import and call graph, scripts, executable/entrypoint files;
- CLI commands and scheduled jobs;
- MCP servers and tools, plugins and connection manifests;
- GitHub Actions, workflows, container/infra and build/test commands;
- data/RPC vendors, endpoints, networks, provider limits and actual consumers;
- strategy ideas in code/docs/roadmaps/tests plus accessible GitHub Issues, PR descriptions/diffs/review comments, commit messages and release notes (where API permissions allow);
- configs/schema keys (names + defaults only; never secret values);
- runtime capability/event/episode evidence.

For each item capture `id, kind, version, license, install_source, owner, entrypoint, used_by, permissions, external_network, secret_names_only, tests, last_observed, status, duplicate_candidate, evidence_refs`.

A repo cannot discover all applications installed on a developer's Windows machine merely by reading Git. If machine inventory is desired, run a separate user-approved read-only inventory of PATH/known package managers/MCP configs; report only app names/versions and redact credentials. Do not scrape secrets or silently modify global configuration.

Never auto-delete. Dynamic imports, reflection, plugin registries, config and external consumers can hide usage; output candidates with evidence and blast radius for a separate reviewed PR.

## 8. W0A bake-off must measure, not assume

Run native Local Intelligence, DeusData/codebase-memory-mcp (C daemon), colbymchenry/codegraph (Rust daemon), CGC, Graphify, and one compact Rust graph (repomap or sdsrss/code-graph-mcp) on one clean exact SHA; add SCIP for languages with viable indexers. Benchmark Scantool or Probe as the JIT extractor. Optional codeTree, agentic-codebase, Entire Graph and code-graph-rag are evaluated only for specific gaps. Joern is a separate optional deep-analysis benchmark. Repomix/grep-ast only benchmark packing/slicing. Glean is a deferred architecture option.

Golden questions (30–50) must test:
1. strategy idea → exact code entrypoint and all known variants;
2. calls/callers/callees and exact paths across files;
3. strategy → provider/source/venue/pool/lender/capital;
4. source adapter → consumers → tests/contracts;
5. event producer → EventEnvelope field → store/export/replay;
6. observation → candidate → simulation → reconciliation → paper episode;
7. tool/app/MCP/CLI → entrypoint → permissions → consumers;
8. config key → schema/default/feature gates;
9. git diff → impacted symbols/tests/strategies/docs;
10. potential unused/duplicate candidate with dynamic registration false-positive cases;
11. context answer under 500/1k/2k tokens without losing exact refs.

Measure:
- answer and edge precision/recall against manually verified expected refs;
- parser/file coverage and unsupported formats;
- caller/callee correctness by language and dynamic/overloaded cases;
- build and incremental refresh time;
- stale index and branch isolation;
- p50/p95 query latency, RAM and disk;
- actual token count, answer utility and source-link correctness;
- licensing, transitive dependency/SBOM/security, offline/privacy and install side effects.

Adopt one primary persistent graph only if its measured value beats current native baseline. Probe may complement it as a fast body retriever because it serves a different layer.

## 10. First practical implementation order

1. Preserve native Local Intelligence as repo snapshot/pack/retention orchestrator.
2. In parallel benchmark CBM C daemon, CodeGraph Rust daemon, CGC, Graphify and one compact Rust graph on identical questions/SHA; record install/config side effects and licenses.
3. Benchmark Scantool and Probe as JIT extractors with blob-SHA reuse and explicit coverage; choose one or prove both serve distinct needs.
4. Add SCIP/LSP only for repo languages where a working indexer produces measured higher precision.
5. Apply FULL/SKELETON/REFERENCE/OVERVIEW retrieval, query-time PageRank, lazy 1–3-hop expansion and hard model-token budgeting.
6. Add Web3 strategy/source/provider/runtime graph adapter, temporal labels and bitemporal evidence joins over canonical owners.
7. Add CI + nightly rebuild, dependency-aware incremental refresh, label drift checks, cache invalidation and portable context/evidence receipts.
8. Add resource budgets, graph-quality SLOs, schema/label ontology migration tests and cross-repo federation only when required.
9. Only then consider Joern/Glean/embeddings/remote data stores if measured use cases require them.

**Success condition:** coding agent and ChatGPT can answer “what already exists, which exact function implements it, who calls it, what source/config/provider it uses, which tests and runtime evidence support it, and what's missing?” with a small pack, exact links and explicit unknowns. No indexing tool alone can guarantee that; the Web3 domain mapping and event correlation are the Studious-specific integration work.
