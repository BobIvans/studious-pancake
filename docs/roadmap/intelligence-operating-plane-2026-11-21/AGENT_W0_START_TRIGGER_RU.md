# CODING AGENT EXECUTION TRIGGER — FULL OCA + REPO KNOWLEDGE BOOTSTRAP
## Это задание запускает не только аудит, а первую работающую версию агрегатора знаний

**Repository:** `BobIvans/studious-pancake`  
**Design source:** PR #666, branch `codex/intelligence-operating-plane-design-2026-11-21`  
**Master docs:** `CODEX_START_HERE_RU.md`, `OPERATIONS_CONTEXT_AGGREGATOR_RU.md`, `REPO_KNOWLEDGE_GRAPH_RU.md`, `CHATGPT_CODING_AGENT_CONTEXT_WORKFLOW_RU.md`, `TOOL_ACCESS_PROFILES_RU.md`, `TOKEN_EFFICIENCY_PLAYBOOK_RU.md`, `REALTIME_OPERATION_DATA_PLANE_RU.md`, `WORK_PACKAGE_MATRIX.json`.  
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
- CodeGraphContext (CGC);
- Graphify;
- SCIP indexers for languages/builds that actually exist in this repository;
- Probe raw CLI/MCP for zero-index full-function extraction;
- Aider RepoMap/PageRank for query-time relevance ranking;
- grep-ast/TreeContext or Repomix only for scoped slicing / one-off signature digest (Repomix compression is experimental and strips implementation logic);
- SCIP/LSP only for languages with working indexers;
- Joern/CPG only as optional CFG/DFG/taint deep-analysis profile;
- Glean only as a deferred scale alternative.

Use 30–50 golden questions, including caller/callee paths, strategy/source/provider links, test impact, tool/MCP discovery, dead-code false positives and 500/1k/2k-token packs. Apply all applicable techniques from TOKEN_EFFICIENCY_PLAYBOOK_RU.md: stable T0 repo card, one-line T1 catalogues, lazy 1–3-hop graph traversal, query-time PageRank, scope-aware function extraction, exact token budgeting, blob-hash incremental caching and prompt-prefix caching only where the actual API supports it. Measure correctness, coverage, freshness, build/update time, p50/p95 latency, peak RAM, disk and token counts. Record versions, source URLs, license/SPDX, transitive dependencies, security status and exact install/self-check results.

Install candidates only in an isolated `uv tool`/pipx/temp environment. Never add them to bot runtime dependencies during evaluation. Graphify's official package is `graphifyy`; keep its optional model-backed docs/media semantic pass off. CGC's CLI/MCP includes management operations; do not expose its full tool catalog to the analyst. jCodeMunch is excluded unless commercial/revenue-supporting licensing is explicitly approved. Do not run remote Graphify Cloud or upload the repo.

### Track C — full repository tool/app/source inventory

Inventory the entire Git tree, not just Python imports:
- packages, lockfiles, SDKs, external APIs/RPCs, data providers, DEX/venue/lender adapters;
- strategies and strategy ideas in code, docs, roadmaps, configs, tests and PR references;
- CLI commands, scripts, GitHub Actions/workflows, MCP servers/tools, plugins, IDE/dev apps, Docker/infra;
- schemas, data contracts, config keys, external source links, tests and consumers.

Create explicit status labels ACTIVE / WIRED / QUALIFIED / DEV_ONLY / OPTIONAL / EXPERIMENTAL / DUPLICATE_CANDIDATE / UNREFERENCED_CANDIDATE / DEPRECATED / BLOCKED / UNKNOWN. Link every item to exact paths/symbols/tests and record version/license/owner/permissions/usage.

Do not delete anything. Zero static references is not proof of dead code; inspect dynamic imports, registries, reflection, config, CLI, CI, runtime and external consumers. Produce a prioritized cleanup list with blast radius and tests. Actual deletion must be a separate reviewed PR.

### Track D — context/retrieval design and golden corpus

Create 30–50 real questions from the repository and prepare deterministic expected evidence paths/symbols. Include questions a new strategy researcher must ask to avoid duplication. Define bounded graph query and token-pack measurements.

## 2. After parallel reports, BUILD the first working repo knowledge index (OCA-W0B)

Do not stop at W0. Use the W0/W0A evidence to choose the **smallest winning combination** and implement an additive vertical slice:

1. Reuse `src/intelligence` snapshots, manifests, source references, context packs, reports and benchmarks. Do not create a parallel repository snapshot system or a second semantic-memory database.
2. Create a rebuildable, repo-SHA-bound symbol/entity graph covering all source languages found plus deterministic inventories of docs, configs, tests, workflows, packages, scripts, CLI/MCP tools and external data sources.
3. Link StrategyIdea/StrategyVersion → entrypoint symbol → callers/callees → route/planner/compiler/simulator → config → source/provider/venue/flash-capital → tests → event/episode/evidence where the relationship is proven.
4. Preserve edge provenance: STATIC_EXTRACTED, COMPILER_RESOLVED, CANONICAL_REGISTRY, RUNTIME_OBSERVED, DOC_CLAIM, HUMAN_CONFIRMED or LLM_PROPOSED. Inferred, missing or ambiguous edges must never be upgraded to verified facts.
5. Provide compact one-line catalogues for every strategy, source, provider, tool/app, MCP server/tool, CLI command and protocol. Include status, exact symbol/file links, tests, consumers, evidence refs and UNKNOWN gaps.
6. Expose a small read-only query surface: search, symbol, callers, callees, path, impact, strategy explain/compare, source lineage, tool inventory and bounded context-pack build. Follow existing CLI conventions after verifying the current parser; do not invent duplicate registries.
7. Make incremental refresh by changed file hashes / Git tree diff; support add/delete/rename, stale-SHA rejection, branch isolation, deterministic output and coverage accounting.
8. Add tests for graph edges, source links, no dangling references, no secret values, rename/delete, stale index, branch isolation, unsupported parsers, token cap and deterministic rebuild.
9. Put bulky indexes/caches outside tracked source or in ignored build output. Commit schemas, reproducible commands, compact manifests, tests and an example report—not a huge opaque database.
10. If no external candidate beats the native implementation, implement the minimal missing Tree-sitter/SQLite/FTS/graph traversal layer in existing architecture. Do not force a third-party tool merely because it is popular.

**Do not build every tool together. Keep native Local Intelligence as orchestrator; adopt at most one persistent graph backend (CGC OR Graphify OR proven native graph), Probe as optional JIT extractor, SCIP/LSP for selected precision paths; defer Joern/Glean/embeddings/remote DB unless benchmarks prove need.

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
- Define bounded queues/backpressure, idempotent append/outbox, replay, loss counters, event-to-store latency and p50/p95/p99 overhead. No silent loss or unbounded queues.
- Build one read-only cross-store query facade and a portable export/replay bundle with manifest, JSONL event records, existing Parquet datasets where available, schema/tool versions, hashes and coverage/gap report.
- Prove from a real supported offline/paper/shadow vertical (not only unit fixtures) that an operation can be reconstructed after process restart with code/strategy/source/function/outcome references.

## 4. Continue into OCA operation/strategy correlation — do not leave it as a standalone code graph

After W0/W0A, execute each dependency-ready package in `WORK_PACKAGE_MATRIX.json`; independent work may run in parallel only with disjoint write scopes. Continue through W1–W11 where evidence and dependencies permit:

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
