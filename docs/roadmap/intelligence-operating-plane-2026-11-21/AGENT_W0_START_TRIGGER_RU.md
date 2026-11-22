> **Новое решение владельца — 22.11.2026 (имеет приоритет над более ранними ограничениями ниже).**
>
> Пользователь поручил реализовать staged Repo Intelligence + Web3 Data Plane, включая LLM-FREE DETERMINISTIC INDEXING CONTRACT. Web3/flashloan remains the target domain, но инфраструктурная работа больше не ограничивается только экспериментальным A-helper: coding agent должен пройти W0/W0A/W0C, затем построить W0B, после чего закрывать зависимые C/E/F/B/H и S1–S6 по этапам. Это не разрешение запускать W0–W19 одновременно.
>
> **Execution waves:** (0) параллельные read-only audits W0, W0A, W0C; W0A включает предварительный path-level license/SBOM/security inventory, а отдельный OCA-W12 gate идёт после фиксации списка кандидатов; (1) обязательная реализация W0B с нулевой LLM-зависимостью и CI/nightly refresh; (2) typed temporal graph + provider contracts/quality/chain identity/strategy requirements; (3) runtime lineage/replay на фактических test/paper/shadow paths; (4) retrieval/context/MCP + verification; (5) масштабирование и внешние сервисы только при измеренном bottleneck. Все старые формулировки «только A», «B–H отложены» и «не начинать W0B после аудита» уступают этой новой инструкции.
>
> **Capability letters A–H (taxonomy retained; no new letters):**
>
> | Letter | Implementation capability | Priority/role |
> |---|---|---|
> | **A** | Whole-repo inventory, polyglot parser, SymbolGraph, calls/imports and exact source references | P0; first graph foundation |
> | **B** | Content-addressed incremental indexing, dependency invalidation, early cutoff and full reconciliation | Required for continuous refresh |
> | **C** | SHA-bound temporal provenance, valid/recorded time, as-of queries and version history | P0 foundation |
> | **D** | Isolated worktrees, leases, bounded sandbox, secret/network/resource separation and work receipts | Minimum safeguards immediately; stronger isolation before autonomy |
> | **E** | Exact/lexical/graph retrieval, T0–T4 context packs and read-only ChatGPT handoff | P0 |
> | **F** | Symbol-to-test evidence, impact analysis, invariant suites, flaky registry and failure shrinking | Critical tests P0; optimization after baseline |
> | **G** | Sparse checkout, multi-agent scheduling, large-repo storage/merge plumbing | Conditional on measured scale |
> | **H** | Token/cost telemetry, prompt-injection isolation, redaction, SBOM/license/security and resource governance | Cross-cutting P0 |
>
> **No-duplicate / current-state rule:** на момент обновления main = 0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54; PR #672–#676 открыты и имеют отдельных владельцев. #672 schema compatibility, #673 read-only metadata catalogue, #674 Debezium adoption gate, #675 NATS adoption gate и #676 OpenLineage projection нужно повторно проверить по latest head/CI и встроить/расширить, а не создавать дубликаты.
>
> Полный нормативный контракт: LLM_FREE_DETERMINISTIC_INDEXING_CONTRACT_RU.md. Он обязателен для OCA-W0B и любого scheduled/CI refresh.
>
# CODING AGENT EXECUTION TRIGGER — FULL OCA + REPO KNOWLEDGE BOOTSTRAP
## Это задание запускает не только аудит, а первую работающую версию агрегатора знаний

**Repository:** `BobIvans/studious-pancake`  
**Design source:** PR #666, branch `codex/intelligence-operating-plane-design-2026-11-21`  
**Master docs:** `LLM_FREE_DETERMINISTIC_INDEXING_CONTRACT_RU.md`, `CODEX_START_HERE_RU.md`, `OPERATIONS_CONTEXT_AGGREGATOR_RU.md`, `REPO_KNOWLEDGE_GRAPH_RU.md`, `CHATGPT_CODING_AGENT_CONTEXT_WORKFLOW_RU.md`, `TOOL_ACCESS_PROFILES_RU.md`, `TOKEN_EFFICIENCY_PLAYBOOK_RU.md`, `REALTIME_OPERATION_DATA_PLANE_RU.md`, `UNIVERSAL_KNOWLEDGE_DATA_PLANE_EXPANSION_RU.md`, `FUNCTION_AND_INFRASTRUCTURE_COVERAGE_RU.md`, `WORK_PACKAGE_MATRIX.json`.  
**Execution goal:** deliver a working, incremental, token-efficient, evidence-linked repository knowledge index and connect it to existing Web3 strategy/operations owners. **Do not stop after producing an audit report.**

---

## 0. Start safely and pin the actual repository state

1. Fetch origin and inspect latest `main` SHA, PR #666, all open PRs/branches, CI/checks, `AGENTS.md`, worktree status and existing ownership.
2. Read the design documents from PR #666 branch (do not assume they are already on main).
3. Create a new implementation branch and isolated worktree from the latest current `origin/main`; keep PR #666 as the design source. Never write to main or another agent's worktree.
4. Record base SHA, OS, Python/Node/Rust versions, installed tooling, exact commands and environment.
5. If main has moved since the design baseline, update every report to the actual SHA. Never treat stale documentation/indexes as current.

## 1. Run independent discovery tracks in parallel

Use subagents or separate read-only worktrees where available. Each track owns its own report file; do not let parallel workers edit the same source files.

### Track A — current canonical owners and actual runtime wiring (OCA-W0)

Inspect Local Intelligence V2, EventEnvelope producer → store → export → replay, AGG-02, MarketObservation, MarketEpisode, strategy/source/provider registries, conflict scheduler, tests and CLI. Prove what is actually called and persisted; fields/classes/docs alone are not proof. Deliver the W0 owner, event-correlation, CLI/test, coverage and gap reports defined in the matrix.

### Track B — polyglot code-intelligence / MCP tool bake-off (OCA-W0A)

On the same pinned clean SHA, benchmark in isolated temporary/dev tool environments:
- current Studious `repo_source.py` / `context_pack.py`;
- Tree-sitter-based candidate(s);
- DeusData/codebase-memory-mcp (C daemon + shared coordination daemon + docs/config/infrastructure graph);
- colbymchenry/codegraph (Rust daemon + SQLite/WAL + code graph + file watcher);
- sdsrss/code-graph-mcp (Rust + SQLite/FTS5 + BLAKE3 Merkle + multi-tier context);
- SylphxAI/repomap (Rust local graph + call paths/impact);
- CodeGraphContext (CGC);
- Graphify;
- ThinkyMiner/codeTree / agentic-codebase / Entire Graph / stakgraph / code-graph-rag only where a specific measured gap exists;
- SCIP indexers for languages/builds that actually exist in this repository;
- Probe raw CLI/MCP and mariusei/scantool for JIT function extraction; specifically test Scantool's Git-blob-SHA cache and FULL/SKELETON/REFERENCE levels;
- Aider RepoMap/PageRank for query-time relevance ranking;
- grep-ast/TreeContext or Repomix only for scoped slicing / one-off signature digest (Repomix compression is experimental and strips implementation logic);
- SCIP/LSP only for languages with working indexers;
- Joern/CPG only as optional CFG/DFG/taint deep-analysis profile;
- Glean only as a deferred scale alternative.

Use 30–50 golden questions, including caller/callee paths, strategy/source/provider links, test impact, tool/MCP discovery, dead-code false positives and 500/1k/2k-token packs. Benchmark C/Rust daemons against Graphify/CGC on the exact Studious SHA. Also benchmark MakerViking/mimir vs codician-team/growmos (and optionally TheWinci/mimirs, a different project) only as one optional semantic label/memory overlay; do not adopt both, and do not treat any as raw runtime fact store. Record exact upstream URL and project identity in the tool catalogue. Apply all applicable techniques from TOKEN_EFFICIENCY_PLAYBOOK_RU.md: stable T0 repo card, one-line T1 catalogues, lazy 1–3-hop graph traversal, query-time PageRank, scope-aware function extraction, exact token budgeting, blob-hash incremental caching and prompt-prefix caching only where the actual API supports it. Measure correctness, coverage, freshness, build/update time, p50/p95 latency, peak RAM, disk and token counts. Record versions, source URLs, license/SPDX, transitive dependencies, security status and exact install/self-check results.

Install candidates only in an isolated `uv tool`/pipx/temp environment. Never add them to bot runtime dependencies during evaluation. Graphify's official package is `graphifyy`; keep its optional model-backed docs/media semantic pass off. CGC's CLI/MCP includes management operations; do not expose its full tool catalog to the analyst. jCodeMunch is excluded unless commercial/revenue-supporting licensing is explicitly approved. Do not run remote Graphify Cloud or upload the repo.

### Track C — full repository tool/app/source inventory

Inventory the entire Git tree, not just Python imports:
- packages, lockfiles, SDKs, external APIs/RPCs, data providers, DEX/venue/lender adapters;
- strategies and strategy ideas in code, docs, roadmaps, configs, tests and PR references;
- CLI commands, scripts, GitHub Actions/workflows, MCP servers/tools, plugins, IDE/dev apps, Docker/infra;
- schemas, data contracts, config keys, external source links, tests and consumers.

Create explicit status labels ACTIVE / WIRED / QUALIFIED / DEV_ONLY / OPTIONAL / EXPERIMENTAL / DUPLICATE_CANDIDATE / UNREFERENCED_CANDIDATE / DEPRECATED / BLOCKED / UNKNOWN. Link every item to exact paths/symbols/tests and record version/license/owner/permissions/usage.

Do not delete anything. Zero static references is not proof of dead code; inspect dynamic imports, registries, reflection, config, CLI, CI, runtime and external consumers. Produce a prioritized cleanup list with blast radius and tests. Actual deletion must be a separate reviewed PR.

### Track E — deterministic provider/source and flash-loan path inventory (OCA-W0C)

This is a parallel read-only inventory, separate from the generic code/tool graph reports. Inspect the complete in-repo Web3 source universe and trace how each source could or demonstrably does feed the flashloan bot.

Inventory:
- RPC providers, indexers, APIs, WebSocket subscriptions, pollers, one-shot captures, archive/history sources, DEX/AMM/aggregator quote APIs, pool-state readers, oracles, token metadata, bridge/chain feeds, flash lenders/capital sources and SDK/IDL sources;
- every adapter, endpoint/method, pagination/cursor, rate/quota policy, schema/normalizer, source catalogue entry, provider governance gate, data contract, cache and consumer;
- source → adapter → raw payload/cursor → normalized observation/stream → strategy requirements → candidates/decisions → quote/sizing/planner/compiler/simulation → reconciliation → paper/shadow outcome, recording each link as PROVEN / STATIC_ONLY / DOC_CLAIM / MISSING / UNKNOWN;
- exact chain/deployment identity, block/slot/hash, tx/signature/log or chain-native index, decimals/units/timestamp semantics, freshness, lag, coverage, gaps, corrections/reorg and replay;
- source permission/entitlement, disabled/enabled state, actual mode STREAMING/POLL_ONLY/ONE_SHOT/UNAVAILABLE and measured evidence. Do not perform network probes or enable providers during inventory.

Deliver:
- SOURCE_PROVIDER_CATALOGUE.jsonl;
- STRATEGY_PROVIDER_TRACE_MATRIX.json;
- SOURCE_CAPABILITY_GAP_REPORT_RU.md;
- FLASHLOAN_DATA_PATHS.md with exact files/symbols/callers/configs/tests and explicit unproven stages;
- evidence manifest with main SHA, source blob hashes, contract/normalizer versions and inaccessible-history gaps.

Acceptance: every source found in registries, code, docs, configs, tests and open PRs is accounted for; duplicate aliases resolve to canonical EntityIdentity or remain candidates; declared capabilities are distinct from observed capabilities; no static path is represented as runtime usage; unknown freshness/quality/replay/capacity is not invented; no credentials or private endpoint values are exported. Use existing src/market/source_catalog.py, src/external_contracts, src/provider_governance, AGG-02 and MarketObservation owners; do not create duplicate provider registries in this audit.

### Track D — context/retrieval design and golden corpus

Create 30–50 real questions from the repository and prepare deterministic expected evidence paths/symbols. Include questions a new strategy researcher must ask to avoid duplication. Define bounded graph query and token-pack measurements.

## 2. After parallel reports, BUILD the first working repo knowledge index (OCA-W0B; LLM-FREE gate mandatory)

Do not stop at W0. Use W0/W0A/W0C/W12 evidence to choose the **smallest winning combination** and implement an additive vertical slice. Before coding, read and satisfy LLM_FREE_DETERMINISTIC_INDEXING_CONTRACT_RU.md; the first build and refresh path must not invoke a model:

1. Reuse `src/intelligence` snapshots, manifests, source references, context packs, reports and benchmarks. Do not create a parallel repository snapshot system or a second semantic-memory database.
2. Create a rebuildable, repo-SHA-bound symbol/entity graph covering all source languages found plus deterministic inventories of docs, configs, tests, workflows, packages, scripts, CLI/MCP tools and external data sources.
3. Link StrategyIdea/StrategyVersion → entrypoint symbol → callers/callees → route/planner/compiler/simulator → config → source/provider/venue/flash-capital → tests → event/episode/evidence where the relationship is proven.
4. Preserve edge provenance: STATIC_EXTRACTED, COMPILER_RESOLVED, CANONICAL_REGISTRY, RUNTIME_OBSERVED, DOC_CLAIM, HUMAN_CONFIRMED or LLM_PROPOSED. Inferred, missing or ambiguous edges must never be upgraded to verified facts.
5. Provide compact one-line catalogues for every strategy, source, provider, tool/app, MCP server/tool, CLI command and protocol. Include status, exact symbol/file links, tests, consumers, evidence refs and UNKNOWN gaps.
6. Expose a small read-only query surface: search, symbol, callers, callees, path, impact, strategy explain/compare, source lineage, tool inventory and bounded context-pack build. Follow existing CLI conventions after verifying the current parser; do not invent duplicate registries.
7. Make incremental refresh by Git blob/tree hashes (not mtime alone); support add/delete/rename, stale-SHA rejection, branch isolation, deterministic output, dependency-aware invalidation, parser/schema version cache keys and coverage accounting. Record valid-from/valid-to repo SHA, recorded-at and source event time for temporal/as-of queries.
8. Add tests for graph edges, source links, no dangling references, no secret values, rename/delete, stale index, branch isolation, unsupported parsers, token cap and deterministic rebuild. Add temporal/as-of queries, ontology/schema migration, label drift revalidation, static-vs-runtime edge separation, daemon concurrency and indexing resource budgets.
9. Put bulky indexes/caches outside tracked source or in ignored build output. Commit schemas, reproducible commands, compact manifests, tests and an example report—not a huge opaque database.
10. If no external candidate beats the native implementation, implement the minimal missing Tree-sitter/SQLite/FTS/graph traversal layer in existing architecture. Do not force a third-party tool merely because it is popular.
11. Create a versioned label store for StrategyIdea/StrategyVersion/ArbitrageFamily/DataSource/Provider/Venue/Pool/Protocol/FlashCapitalSource/Tool/Capability/RiskCheck/ExecutionStage/ResourceSet. Each label carries ontology version, evidence refs, source blob/repo SHA, provenance, confidence, valid-time/recorded-time and status (PROPOSED/VERIFIED/STALE/NEEDS_REVIEW/RETIRED). Revalidate on source/config/registry changes; LLM suggestion is never auto-verified.
12. Add temporal graph lookup as-of repo SHA and operation event time; old episodes must resolve the code/config/strategy labels actually active then.
13. Control index CPU/RAM/IO, single writer, debounced queues and cancellation so repo graph refresh cannot starve market capture or paper/shadow operations.
14. Support multi-repo identity namespace in schema, but do not ingest more repos until actual shared dependencies/cross-repo services are discovered.

**Do not build every tool together. Keep native Local Intelligence as orchestrator; adopt at most one persistent graph backend (CBM OR CodeGraph OR Graphify OR CGC OR another measured winner), one JIT extractor only if useful (Scantool OR Probe), SCIP/LSP for selected precision paths, and at most one semantic memory overlay (Mimir OR growmos OR none). Joern/CPG, Glean, embeddings and remote DB remain optional until benchmarks prove need. Install all candidates in isolated HOME/client configs; inspect generated MCP/AGENTS/hooks diff and turn telemetry/cloud features off.

Required first tangible artifact:** one command/entrypoint produces (a) a 300–500-token repo card, (b) a compact one-line catalogue of all discovered strategies/tools/sources/providers, (c) a searchable graph with exact symbol links and callers/callees, and (d) a bounded task context pack with freshness/coverage gaps.

## 3. Wire real runtime data capture — do not confuse a code map with a running bot work log

Read `REALTIME_OPERATION_DATA_PLANE_RU.md` and execute OCA-W10 and OCA-W11. This is a mandatory part of done, not optional documentation.

Current baseline warning from source inspection: EventEnvelope/ObservabilityStore exist, but make_event() search only found its definition plus tests; current make_event() defaults to test-runtime/test and unknown producer/config provenance. RuntimeDiscoveryCoordinator returns a bounded report; native_cpmm_capture.py documents a one-shot capture with no subscriptions. Do not claim end-to-end live runtime event coverage until W0 proves real producers. Verify these findings on latest main before relying on them.

Required work:
- Instrument actual supported test/paper/shadow decision paths after W0 identifies them; do not just add an unused EventEmitter class or synthetic fixture producer.
- Capture discovery/observation, strategy accept/reject, provider quote, flash lender/capital evidence, route/sizing/planning/compiler, sender-free simulation, reconciliation and terminal paper/shadow result with timestamps/reason codes/IDs.
- Join strategy_id/version, repo SHA, config hash/generation, stable callsite/symbol ID, trace/span, candidate/opportunity/attempt, provider/source, observation ID/cursor/generation, flash-capital source and outcome where applicable; unknown remains explicit.
- Keep canonical raw payloads in AGG-02/evidence owners, operation transitions in ObservabilityStore, observations in MarketObservation, episodes in MarketEpisode. Link by stable IDs/hashes; do not duplicate raw payloads into a new DB.
- All decision/rejection/gap/correction/reconciliation/terminal events are non-sampleable. If durable capture fails, emit an explicit degraded/incomplete state and prevent episode qualification until recovery/replay. Sampling is permitted only for noisy non-decision debug/heartbeat logs with counters and policy version.
- Use OpenTelemetry trace context/span IDs if useful for async/service causality; it supplements, not replaces, EventEnvelope and canonical stores.
- Prove continuous bounded capture while the supported paper/shadow runtime is running. Distinguish STREAMING vs POLL_ONLY vs ONE_SHOT source capabilities, cadence, freshness and coverage; do not call one-shot capture real-time streaming.
- Run a bounded long-running soak, restart/reconnect/backfill/checkpoint tests; report p50/p95/p99 ingest-to-store lag, queue depth, drop counts and provider freshness.
- Define bounded queues/backpressure, idempotent append/outbox, replay, loss counters, event-to-store latency and p50/p95/p99 overhead. No silent loss or unbounded queues.
- Build one read-only cross-store query facade and a portable export/replay bundle with manifest, JSONL event records, existing Parquet datasets where available, schema/tool versions, hashes and coverage/gap report.
- Expose a narrow local MCP profile/server with composite bounded tools (repo overview, strategy inventory/explain/compare, source/provider lineage, symbol/call path, operation trace and context pack). No shell/edit/delete/admin/market-write tools. Provide exact client config, connection self-check and portable context-pack path.
- Prove from a real supported offline/paper/shadow vertical (not only unit fixtures) that an operation can be reconstructed after process restart with code/strategy/source/function/outcome references.

## 4. Continue into OCA operation/strategy correlation — do not leave it as a standalone code graph

After W0/W0A, execute each dependency-ready package in `WORK_PACKAGE_MATRIX.json`; independent work may run in parallel only with disjoint write scopes. Continue through W1–W19 where evidence and dependencies permit:

- bind real EventEnvelope producers and events to strategy/config/repo SHA/code symbols using exact values and stable callsites;
- complete OCA-W10 runtime instrumentation and OCA-W11 universal read-only query/export/replay before claiming operational knowledge coverage;
- correlate existing observations/cursors/gaps → candidate/decision → simulation → reconciliation → paper outcome using canonical stores;
- implement OperationEpisode only as a read-only deterministic projection if current owners do not already provide it;
- reuse existing conflict scheduler/resource reservation owners for pool/account/nonce/lender/capital/provider conflicts;
- produce strategy/source/provider/tool coverage, duplicate and outcome reports;
- integrate bounded SQD/Antseer only where required, with provenance/pagination/quotas;
- decide storage expansion only after measurements. Do not add ClickHouse, NATS, vector DB or object storage by default.

If a missing field/callsite cannot be proven, record MISSING/UNKNOWN and create the smallest scoped follow-up. Do not fabricate event joins or perform a broad logging rewrite.

## 5. Wire index freshness into every future change

Implement the least invasive reliable path:
- local command/hook or agent post-commit refresh for the active worktree;
- CI on push/PR and merge to main to verify head-SHA freshness, deterministic incremental index update, schema, dangling edges, secret exclusion and token-pack budgets;
- scheduled nightly full rebuild to compare checksums against incremental index, detect drift and report parser/tool/schema version changes;
- keep generated index as downloadable SHA-bound CI artifact/cache, not large binary Git commits;
- Work Result Receipt includes base/head SHA, index generation, graph delta, affected strategies/sources/tools/tests, test counts and artifact hashes;
- branch/worktree indexes are isolated; PR review includes index diff and impacted dependencies.
Indexing and deterministic labels run without an LLM. Ambiguous semantic labels remain PROPOSED/UNKNOWN.

## 6. ChatGPT handoff for new strategy sessions

Generate a current `CHATGPT_CONTEXT_PACK.md` (bounded, exact SHA, compact rows and evidence links) plus the reusable `CHATGPT_NEW_CHAT_STRATEGY_STARTER_RU.md`. A new chat must be able to ask the index for all existing strategy ideas and compare novelty before suggesting another implementation. Do not claim ChatGPT automatically has local disk access; document exact transfer path (pack artifact/upload, authorized GitHub access or approved read-only local MCP).

## 7. Deliverables

At minimum, produce the OCA-W0 reports plus:
- polyglot/tool benchmark and golden question set;
- strategy/source/provider/tool/app catalogues with provenance;
- repo graph schema, index generator/importer, CLI/query surface and tests;
- compact repo card and one-line strategy/source/tool maps;
- first bounded context pack with exact SHA, token count and continuation;
- working GitHub Actions CI wiring for push/PR/main merge plus scheduled nightly full consistency check (if repository policy/permissions block it, document the exact blocker and do not claim automatic refresh);
- unused/duplicate/deprecation candidate list (no deletion);
- allowlisted read-only local MCP profile/server and client connection/health-check instructions;
- portable `CHATGPT_CONTEXT_PACK.md` plus reproducible full evidence bundle import/export/replay guide;
- Work Result Receipt and a follow-up dependency graph.

Every report records exact base/head SHA, commands, versions, source blob hashes, pass/fail/skip counts, artifact hashes and UNKNOWN/NOT_OBSERVED/BLOCKED separately.

## 8. Safety, permissions and merge

- No transactions, RPC broadcast, signing, submission, borrowing, spending, deployment, account creation or live trading.
- LIVE remains hard-denied. Do not change strategy admission, provider approval, risk, capital, nonce or signer authority.
- No production credentials, keys, seeds or secret values in repo/index/packs.
- No destructive pruning, event deletion or automatic cleanup.
- Do not vendor third-party code without exact license/SPDX/NOTICE and security review.
- Query surface for ChatGPT/analysts is read-only; coding writes stay in isolated worktrees.
- Open a reviewable implementation PR against current main and link PR #666. Keep changes scoped and include tests. **Do not merge; human approval is mandatory.**

## Definition of done

The next ChatGPT/coding-agent session can retrieve a compact, up-to-date map of existing strategy ideas, exact functions and call chains, providers/data sources/tools, configs/tests, observed operations and unknowns—without re-reading the entire repository or reimplementing an existing idea. The index refreshes against new commits and reports its own coverage and staleness. It is a durable external knowledge system, not a claim of unlimited model memory.

**Do the work now. Do not return only a plan. If a dependency or permission blocks part of the scope, still deliver the working safe subset and document the blocker precisely.**


## 9. Expanded universal data-intelligence and governance execution (OCA-W12–W19)

Read UNIVERSAL_KNOWLEDGE_DATA_PLANE_EXPANSION_RU.md before dispatching the expanded work. It is the normative expansion for provider contracts, StrategyDataRequirement, typed temporal graph, incremental computation, agent access, license/SBOM governance and conditional infrastructure candidates. WORK_PACKAGE_MATRIX.json is the machine-readable task/dependency/write-scope authority.

**Observed repository snapshot at this design update:** main was 0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54 (2026-11-21); PR #666 was still based on ea204222df86a0697cc6bce0e9ec60f7db31ffd8. This is not permission to use a stale base. Before any implementation, fetch main again and create new isolated worktrees/branches from the exact latest SHA. Keep PR #666 as design/handoff only.

### W0A mandatory candidate wave

Add these explicit same-SHA profiles to the existing bake-off:
- Main graph contender: sdsrss/code-graph-mcp — https://github.com/sdsrss/code-graph-mcp
- Independent AST/symbol navigation: defendend/Claude-ast-index-search — https://github.com/defendend/Claude-ast-index-search
- Cross-language resolver precision: aimasteracc/tree-sitter-analyzer — https://github.com/aimasteracc/tree-sitter-analyzer
- Retrieval/risk/co-change: iliaal/codesage — https://github.com/iliaal/codesage
- Temporal Git graph: n24q02m/crg — https://github.com/n24q02m/crg
- Conditional graph storage: facebookincubator/Glean — https://github.com/facebookincubator/Glean; LadybugDB/ladybug — https://github.com/LadybugDB/ladybug
- Structural audit/slicing: ast-grep — https://github.com/ast-grep/ast-grep; Aider/grep-ast — https://github.com/Aider-AI/grep-ast
- Output compression/serialization: rtk-ai/rtk — https://github.com/rtk-ai/rtk; dweve-ai/hedl — https://github.com/dweve-ai/hedl
- RCA: sebdenes/code-graph-rca — https://github.com/sebdenes/code-graph-rca

Retain existing candidates (DeusData/codebase-memory-mcp, colbymchenry/codegraph, CodeGraphContext, Graphify, SylphxAI/repomap, Probe, Scantool, SCIP/LSP, Joern and current native Local Intelligence). Evaluate candidates in isolated HOME/client profiles; inspect install hooks, skills, MCP tools, telemetry, network access and AGENTS/config diffs. Use one pinned commit and the same 30–50 golden questions. Select zero/one persistent graph engine, at most one useful JIT extractor and no more than one measured semantic overlay. Popularity and README claims are not acceptance evidence.

### New packages

- **OCA-W12:** path-level license/SBOM/security governance; audit nested directories, rulesets, dataflow packages, models, embeddings, datasets and subprocess-distributed executables. Apply the corrected licensing matrix in the expansion document. A subprocess is not a blanket GPL exemption.
- **OCA-W13:** generic ProviderCapabilityRegistry + versioned ProviderAdapterContract + DataContract; cursors/watermarks, event/ingest time, freshness, lag, coverage, gaps, quotas, corrections/retractions, replay and explicit STREAMING/POLL_ONLY/ONE_SHOT/UNAVAILABLE.
- **OCA-W14:** StrategyDataRequirement and CompatibilityEvaluator; strategies require capabilities/contracts, not a provider implementation; adapter presence never equals strategy qualification.
- **OCA-W15:** multi-layer typed temporal graph with stable IDs, edge provenance, valid-time/recorded-time, schema/ontology versions, correction/reorg events and as-of repo/operation queries.
- **OCA-W16:** signature/body index split, Git blob/tree content addressing, dependency invalidation, early cutoff, cancellation, priorities, branch snapshots, full-vs-incremental reconciliation and resource governor.
- **OCA-W17:** typed agent capability policies, separate analyst/admin surfaces, stable bounded read-only MCP facade, worktree/lease/task isolation, sandbox limits, secret/prompt-injection protection and WorkResultReceipt.
- **OCA-W18:** symbol/callsite-to-test coverage, affected test selection, always-run critical suites, flaky registry, failure shrinking, targeted mutation tests and retrieval/evidence correctness metrics.
- **OCA-W19:** conditional OpenLineage/DataHub/Apicurio/NATS/Debezium/Temporal integration bake-off. Adopt none unless current owners demonstrably fail a measured requirement.

Follow package dependencies and exclusive write scopes exactly. W12 and W0B can proceed after the source/tool inventory is pinned; W13 follows OCA-W1; W14 follows W13 and the existing conflict/qualification owners; W15 follows W1/W2/W3 and W13/W14; W16–W19 start only when their declared dependencies are satisfied. Shared canonical owners remain serialized.

### Expanded invariant

No new provider is enabled; no new source is treated as streaming without continuous capture evidence; no strategy is qualified by adapter presence; no graph edge is upgraded from static/inferred to runtime-observed without event evidence; no data correction/reorg silently overwrites history; no index job may starve paper/shadow capture; no new MCP query path grants signing, submission, borrowing, spending, LIVE or production mutation authority.

 
## 10. Strategic Web3 infrastructure assignments (domain-first)

For the domain-critical infrastructure backlog, read `STRATEGIC_WEB3_INFRA_ASSIGNMENTS_RU.md` as the assignment-level specification and `WORK_PACKAGE_MATRIX.json` as the machine-readable dependency map.

The sequence is WEB3-INFRA-S0..S9:
- S0 current owner/open-PR reconciliation;
- S1 versioned provider adapters + DataContracts;
- S2 provider health, freshness, gaps, quality and disagreement;
- S3 chain identity, canonicality/finality and reorg-safe corrections;
- S4 per-StrategyVersion StrategyDataRequirement + CompatibilityEvaluator;
- S5 evidence lineage from raw observation through paper/shadow outcome;
- S6 cursor backfill, deterministic replay and recovery certification;
- S7 read-only catalogue/query projection;
- S8 schema, test, security, SBOM and resource guardrails;
- S9 conditional infrastructure bake-off (OpenLineage/Apicurio/DataHub/NATS/Debezium/Temporal/Glean/LadybugDB/search/vector/sandbox/storage candidates only on measured need).

**Dispatch policy:** WEB3_FIRST_BACKLOG; no automatic dispatch. Reconcile open #672–#676 before creating overlaps. Reuse canonical owners in market/source, external contracts, provider governance, AGG-02, MarketObservation, Observability and strategy qualification. The new catalogue/lineage/graph remains a read-only derived view. See the assignment document for task scope, deliverables, acceptance and explicit no-duplicate rules.

This task sequence is deliberately focused on Web3 correctness and evidence quality, not a broad platform rewrite. It does not change the A–H order or authorize live financial operations.

 
## Repo Intelligence + Strategy R&D master blueprint (authoritative implementation scope)

Before implementation, read [REPO_INTELLIGENCE_AND_STRATEGY_RND_BLUEPRINT_RU.md](https://github.com/BobIvans/studious-pancake/blob/codex/intelligence-operating-plane-design-2026-11-21/docs/roadmap/intelligence-operating-plane-2026-11-21/REPO_INTELLIGENCE_AND_STRATEGY_RND_BLUEPRINT_RU.md). This is the top-level target product and acceptance definition for PR #666.

The product is **not a graph database demo**. It is a SHA-bound repository and strategy knowledge system that lets a coding agent and ChatGPT discover existing ideas/versions, compare novelty, navigate exact symbols/call paths, inspect providers/configs/tests, understand runtime evidence and retrieve compact deep context with citations.

Implement the A–H capabilities through existing OCA-W0..W19 and WEB3-INFRA-S0..S9 packages; do not create duplicate work-package families:
- A: whole-repo inventory, parser and typed SymbolGraph.
- B: content-addressed incremental index and dependency invalidation.
- C: temporal/provenance-aware strategy and code history.
- D: isolated agent tasks/worktrees and bounded sandbox.
- E: retrieval, T0–T4 context packs and ChatGPT read-only handoff.
- F: symbol-to-test/verification/evidence coverage.
- G: scale plumbing only when measured.
- H: secret, prompt-injection, licensing, SBOM, token and resource governance.

First useful vertical slice must deliver: SHA-bound repo card; strategy idea/family/version catalogue with duplicate/variant links and negative evidence; exact symbol/caller/test lookup; one detailed Web3 strategy card; bounded T0–T3 ChatGPT context pack with evidence manifest and actual/estimated token count; golden-question recall/omission benchmark; deterministic rebuild and stale-SHA rejection.

**Critical distinction:** compression applies to repository navigation and non-target context. Exact target functions, strategy economics, safety gates, decimal/unit/time semantics, schema, test assertions and evidence refs are never lossy-compressed. Every pack reports omitted items and UNKNOWN gaps. No answer may claim complete repository coverage beyond the indexed paths, branches and permissions actually verified.

Use existing canonical owners in src/intelligence, src/strategy, src/market/source_catalog, src/external_contracts, src/provider_governance, src/agg02, src/observability and qualification modules. Graph, labels, catalogue and embeddings are derived read models, never duplicate facts stores.

Use upstreams as function references or isolated benchmark candidates: Tree-sitter, SCIP/LSP where available, Aider RepoMap/PageRank pattern, grep-ast/TreeContext, ast-grep, SQLite FTS/BM25, and one code-graph contender. RTK-like output trimming, Salsa/Buck2/CocoIndex, Zoekt/Tantivy, Glean/LadybugDB, Temporal, NATS, Debezium, DataHub and Apicurio remain conditional by measured need. Do not install everything.

Execution priority remains WEB3_FIRST. Start with current owner/PR reconciliation, then one vertical slice. Do not start all OCA or A–H packages in parallel. Re-fetch current main and inspect open PRs/checks before every assignment. #666 is the design source, not an implementation branch; implementation must start on latest main. Human review/approval is required for merge.

**Precedence rule:** this WEB3_FIRST single-vertical-slice scope supersedes any earlier broad wording in this trigger such as executing all OCA-W1..W19 packages automatically. W1..W19 and WEB3-INFRA-S1..S9 remain the dependency-mapped backlog. The agent must not start every package in parallel or expand scope after the first deliverable without a new explicit instruction.


## 11. Universal task_context / expand_context — mandatory for every repo task

Implement the contract in `UNIVERSAL_TASK_CONTEXT_API_RU.md`. The user or ChatGPT should be able to submit only a natural-language task; the retrieval router chooses the necessary code, symbols, dependencies, tests, configs, providers, runtime evidence, history and governance dimensions.

Required generic read-only entrypoints:
- `task_context(task, depth="adaptive", dimensions="auto", budget_tokens=?, repo_ref/repo_sha=?)`;
- `expand_context(refs, dimensions, depth="full", budget_tokens=?, repo_sha)`.

W0B delivers the minimal native query service/CLI implementation together with graph/index creation. W4 completes adaptive routing, ranking, multi-resolution and token-budget quality. W11 exposes the same backend via read-only MCP. Do not create three independent implementations.

Any task type must work: bug, feature, refactor, architecture, tests, performance, security, licensing, provider integration, strategy R&D or PR review. Every result must confirm index freshness, pin SHA, list evidence/omissions and allow exact expansion by IDs. If MCP is absent/stale, use authorized GitHub/source fallback and disclose it. Never claim to have used an unconnected MCP.


---

## 13. 2026-11-22 addendum — complete-repository graph coverage + expanded MCP tools

Read **FULL_REPOSITORY_GRAPH_AND_MCP_EXPANSION_RU.md** as a mandatory scope extension. This addendum corrects an important ambiguity: W0B currently accounts for all tracked paths, but structural AST coverage is currently Python-focused; a file inventory is not the same as a complete polyglot symbol/data graph.

**New assignments:**
- **OCA-W0B2:** complete Git-tree inventory + polyglot structural graph; Tree-sitter adapters for detected first-party languages; SCIP/LSP only where real indexers/builds work; deterministic docs/config/schema/test/workflow extractors; stable symbol/callsite IDs; explicit per-language coverage and no silent omissions.
- **OCA-W4B:** model-tokenizer-aware, loss-aware context retrieval; task-conditioned PageRank; AST scope extraction; signature/body separation; per-ref token accounting; exact continuation and critical-omission tests.
- **OCA-W11B:** expand the same read-only MCP backend with repo_overview, task_context, expand_context, graph_query, symbol_search, trace_path, domain_catalog, impact_query and history_query. Resolve repo_ref to exact SHA, pin every result and keep all tools read-only.
- Continue the already assigned OCA-W13/W14/W15/W16/W2/W3/W10/W7/W12/W18 work; do not duplicate those owners.

**Execution order:** first reconcile #680–#690 (actual PR bases, cumulative diffs, heads and CI), then W0B2 → W4B → W11B as bounded implementation PRs. Keep PR stacks truthful: each dependent PR should target its actual parent branch or be rebased to main after the parent is merged. Do not create multiple PRs all targeting main while each silently contains its parent's whole diff. Do not merge automatically.

**Definition of done:** inventory coverage, structural code coverage, domain graph coverage and runtime lineage coverage are reported separately. Never call the graph “complete” merely because every path has an inventory row. Full requirements and acceptance are in FULL_REPOSITORY_GRAPH_AND_MCP_EXPANSION_RU.md.

---

## 14. Web3 Strategy Intelligence — dedicated token-efficient research tools

Read `WEB3_STRATEGY_INTELLIGENCE_QUERY_TOOLS_RU.md`. The generic repo graph is not enough by itself for high-quality strategy R&D: implement a derived evidence-linked Strategy Card/catalogue and seven bounded domain query operations exposed through only two compact MCP tools over the **same** read-only query backend:

- `strategy_catalog` — enumerate every discovered registered/unregistered/incomplete/rejected/fixture/doc-only candidate with cursor pagination.
- `strategy_context` — retrieve full strategy implementation/economics/config/provider/test/qualification context by stable refs.
- `strategy_compare` — compare variants, shared/unique code, economic assumptions and evidence-backed novelty class.
- `provider_trace` — trace provider → adapter/method/schema → raw/cursor → normalization → observation → strategy consumer; separate declared/configured/tested/captured/runtime-observed.
- `flash_capital_trace` — trace lender/program/SDK/IDL/method, supported assets, fees/repayment/capacity evidence and strategy integration; never confuse market liquidity with borrow capacity.
- `operation_trace` — query real paper/shadow lifecycle and replay; return UNAVAILABLE/PARTIAL until W10/W2/W15 evidence exists.

**Package OCA-W4C** depends on W0B2/W4B/W11B/W13/W14/W15/W20 and the W0C inventory. It must reuse existing strategy/provider/capital/observation owners. Do not create separate canonical strategy, provider or raw-market stores. operation_trace remains capability-gated on W10/W2/W15; performance_diagnostics additionally requires W20.

**Strategy token workflow:** T0 repo/coverage card → T1 complete paginated strategy catalogue → T2 family/strategy evidence subgraph → T3 exact FULL target functions/configs/contracts/tests → T4 selected history/negative experiments/runtime replay. Deduplicate shared source refs once across variants, use AST scope extraction, task-conditioned ranking and real tokenizer profiles where supported. Do not truncate target functions or compress financial semantics.

**Acceptance:** complete candidate discovery coverage across registries/source/configs/tests/docs/history; explicit lifecycle/evidence states; Web3 golden corpus; zero critical omissions and zero fabricated runtime/provider/qualification facts; measured token reduction + recall/citation/latency; exact refs and same-SHA continuation.

Do not proceed by installing every SOTA tool. Adopt useful functions (Tree-sitter/SCIP, Aider-style ranking, grep-ast scope extraction, tokenizer-aware pack fitting and loss-aware log trimming) in the existing architecture; external products remain benchmark-only unless a measured gap justifies them.

## 15. Strategy/function performance diagnostics — required operational layer

Read `STRATEGY_FUNCTION_PERFORMANCE_DIAGNOSTICS_RU.md` and implement OCA-W20 only after its matrix dependencies are satisfied.

The target is not merely a graph of all functions. Prove the runtime chain from strategy/version to operation/episode, lifecycle stage, stable callsite/symbol, provider/observation/capital inputs, function/stage metrics and authoritative simulation/reconciliation outcome. Use W10 actual producers, W2 deterministic episodes, W15 temporal joins and W18 coverage/fault-injection verification. Keep technical health metrics distinct from financial outcomes.

Required output: invocation counts with denominators; success/error/retry/timeout rates; latency quantiles; queue/backpressure and capture-loss metrics; data freshness/gaps/contract failures; stage conversion/rejection reasons; cohort-aware baseline comparisons; exact evidence refs; sample size and confidence; explicit UNKNOWN/uncovered paths.

Never infer runtime calls from static CALLS edges, treat missing telemetry as zero errors, compare incompatible market/config cohorts, or claim causality from correlation. Use controlled replay/fault injection for causal evidence. Expose `performance_diagnostics` as the seventh operation inside existing `web3_data_trace`; retain the two-schema MCP budget. No automated remediation, strategy/config mutation or LIVE authority.

Execution order after dependencies: W10 + W2 → W15 + W18 → W20 → W4C completion (W4C now depends on W20). Reconcile exact PR ancestry/base and canonical ownership before dispatch. Attach runtime coverage, replay, fault-injection, false-attribution and performance receipts. No automatic merge.
