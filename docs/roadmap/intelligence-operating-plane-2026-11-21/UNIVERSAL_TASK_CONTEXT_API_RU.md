# UNIVERSAL TASK CONTEXT API — repo-intel MCP contract

**Назначение:** единый универсальный read-only вход к репозиторию для любой задачи: код, баг, архитектура, стратегии, providers, данные, тесты, безопасность, производительность, PR review или аудит. ChatGPT/coding agent не должны вручную перечислять нужные файлы и повторно читать весь repo.

**Primary tools:** `task_context` и `expand_context`.  
**Transport:** локальный allowlisted read-only MCP; тот же query service доступен через repo-intel CLI и portable context-pack export. MCP, CLI и export — три интерфейса к одному retrieval backend, а не три независимые реализации.

## 1. Product rule

Для каждой задачи система формирует минимальный достаточный, доказательный контекст, а не минимальный по любой цене. Она начинает с compact overview, находит связанные сущности и постепенно раскрывает исходники. Если релевантной информации недостаточно, она явно возвращает нужные IDs для расширения.

- Индексация и graph refresh остаются LLM-free и детерминированными по отдельному контракту.
- Сам retrieval API также обязан иметь полноценный deterministic exact/lexical/graph path без обязательных model calls или remote embeddings.
- Вызвавший ChatGPT/agent может использовать своё reasoning для решения, что раскрыть дальше, но не может повысить provenance или verification state.
- Query tools остаются read-only. Никакого shell, edit, delete, admin, provider-enable, signer, sender, borrowing, spending, deployment, production mutation или LIVE capability.

## 2. Tool 1 — task_context

### Request

```json
{
  "task": "Natural-language description of the task",
  "repo_ref": "main",
  "repo_sha": null,
  "depth": "adaptive",
  "budget_tokens": null,
  "dimensions": ["auto"],
  "include_tests": true,
  "include_configs": true,
  "include_provider_data": true,
  "include_runtime_evidence": true,
  "include_history": "relevant",
  "must_include_refs": [],
  "exclude_refs": [],
  "continuation_cursor": null
}
```

Required: `task`. Other fields have safe defaults. `repo_sha` pins the exact historical snapshot when provided; otherwise resolve the requested ref once and return the resolved SHA. `budget_tokens=null` means apply the configured client budget policy and report the actual limit used. Never silently exceed the requested limit.

Supported dimensions:
- `auto`, `code`, `symbols`, `call_paths`, `tests`, `configs`, `dependencies`, `architecture`;
- `strategies`, `providers`, `market_data`, `dex_venues`, `flash_capital`, `data_contracts`, `lineage`;
- `runtime`, `paper_shadow`, `qualification`, `replay`, `history`, `security`, `licenses`, `performance`, `tooling`.

`auto` chooses dimensions from task terms, exact matched IDs/symbols, repo metadata and graph relations. A deterministic lexical/graph baseline must work without embeddings. Caller may pin dimensions to improve precision.

### Behaviour

1. Resolve and pin branch/ref → commit SHA/tree SHA; read graph generation and indexed SHA.
2. Check that the index matches the requested snapshot. If stale/missing/incomplete, return explicit status; do not label it current.
3. Produce T0 repo state + relevant T1 catalogue rows.
4. Retrieve exact identifier matches, then lexical/FTS/BM25, typed graph neighbors and proven dependency edges.
5. Add task-relevant callers/callees, configs, provider contracts, tests, history and runtime evidence according to dimensions and evidence availability.
6. Rank by task relevance, correctness risk, direct dependency, change impact and provenance. PageRank-like ranking is only one signal, not the authority.
7. Deduplicate repeated source/evidence payloads by stable IDs and content hashes.
8. Pack under budget using multi-resolution context: target code FULL, direct relevant dependencies SKELETON or FULL according to need, outer neighbors REFERENCE/OVERVIEW.
9. Return an initial pack and exact next expansion options. If full target code cannot fit, do not cut it mid-function: return its reference and `NEEDS_EXPANSION`/partial status.
10. Keep the query read-only; it must not launch indexing or mutate repository state.

### Response envelope

Every response must include:
- `status`: FRESH / PARTIAL / STALE / UNAVAILABLE / BUDGET_LIMITED;
- `repo_ref`, resolved `commit_sha`, `tree_sha`, `branch`, `graph_generation`, `indexed_sha`, index build time and freshness;
- `task_id`, `dimensions_used`, `depth`, `budget_tokens`, `actual_tokens` or clearly marked estimate, tokenizer/version;
- `included_refs`, `omitted_refs`, `must_expand_refs`, `continuation_cursor`, `next_expansions`;
- per-edge/per-fact `provenance`, `verification_state`, `confidence`, exact source path/symbol/range/blob SHA or canonical evidence ID;
- coverage, unsupported/unindexed sources, ambiguity, conflicts, UNKNOWNs and retrieval limitations.

No naked summary without its evidence manifest. A truncated or partial pack must identify exactly what was omitted and how to retrieve it.

## 3. Tool 2 — expand_context

### Request

```json
{
  "refs": ["stable-node-or-evidence-id"],
  "dimensions": ["source", "callers", "callees", "tests", "configs"],
  "depth": "full",
  "budget_tokens": null,
  "repo_sha": "same SHA returned by task_context",
  "continuation_cursor": null
}
```

Expand only from stable IDs returned by an earlier query or exact known repository refs. Pin to the same SHA by default. Cross-SHA expansion requires an explicit as-of/change comparison request; never silently mix versions.

Supported expansion dimensions include:
- `source`: exact full function/class/module body and source ranges;
- `callers`, `callees`, `imports`, `implementations`, `overrides`;
- `configs`, `schemas`, `contracts`, `providers`, `data_requirements`;
- `tests`, `fixtures`, `coverage`, `qualification`, `negative_results`;
- `runtime_trace`, `observation_lineage`, `flash_capital_evidence`, `simulation`, `reconciliation`;
- `history`, `PRs`, `issues`, `reviews`, `commits`, `change_impact`.

The tool returns the exact requested payloads, new evidence refs and next expansion IDs. It must not re-return already included code unless requested; use stable refs and deduplication.

## 4. Adaptive retrieval policy

Default behaviour is `depth=adaptive`:
- **T0:** compact repo SHA/state/coverage card.
- **T1:** relevant one-line catalogue rows (not the entire catalogue unless asked).
- **T2:** initial task-specific typed graph slice, usually the smallest useful 1–3 hop neighborhood.
- **T3:** exact full target functions, callers/callees, relevant configs/contracts/tests when required to answer correctly.
- **T4:** deep history, alternatives, negative evidence, runtime replay, detailed qualification and historical as-of dossier.

Do not assume every task is a strategy task. The router must support generic repository tasks too:
- bug/failure: traceback and exact failing symbol → callers/callees → state/config → tests/fixtures → recent changes;
- feature: existing interfaces/implementations → dependencies → contracts → tests → compatibility/blast radius;
- refactor: symbol graph → consumers → public interfaces → affected tests → migration risks;
- strategy R&D: idea/version/variants → mechanism/economics → implementation → provider/data needs → lenders/fees/capacity → tests/experiments/outcomes/negative evidence;
- provider integration: adapter/contracts → source methods/cursors/quality → consumers/strategy requirements → replay/tests;
- PR review: diff → changed symbols → downstream consumers → tests/security/contracts → related history;
- performance: hot paths and measured profiles → call graph → IO/CPU/queue/storage owners → regression benchmarks;
- security/licensing: capability surface → secrets/data flow → dependencies/SPDX/SBOM → affected workflows and gates.

The task router may use explicit user dimensions, deterministic term/rule matches, identifier resolution and graph relations. Optional semantic retrieval may supplement a measured recall gap but must not be required for indexing or exact source resolution.

## 5. Token efficiency without evidence loss

Mandatory:
- one canonical copy of each source/evidence payload per pack; reference it by stable ID elsewhere;
- real target-model tokenizer when known, otherwise label byte/token estimate and tokenizer uncertainty;
- target implementation and decision-critical functions remain FULL; no mid-function truncation;
- preserve decimals, units, rounding, fees, slippage, timestamps, chain/block identity, API schema fields, risk constraints, event IDs, hashes, test assertions and negative evidence;
- skeletonize only non-target neighbors and include exact refs back to full source;
- rank by task relevance and decision risk, not symbol frequency alone;
- separate high-confidence facts from candidates, documentation claims and UNKNOWNs;
- budget overflow returns BUDGET_LIMITED + exact refs/continuation, never silent lossy compression;
- include/omit manifest enables the caller to detect missing prerequisites.

Optional, measured optimizations:
- exact-hash result cache keyed by repo SHA + graph generation + query hash + dimensions + depth + tokenizer + budget;
- stable-prefix caching only when the actual connected model API exposes cache controls/metrics;
- RTK-like structured CLI/test-log trimming after information-loss tests;
- lexical backend replacement (Tantivy/Zoekt) only after FTS benchmarks; semantic/vector reranking only after exact/lexical/graph recall is measured insufficient.

Token savings must be reported as baseline tokens vs selected pack tokens, alongside retrieval recall and critical omission rate. A low token count with missing dependencies is a failure, not an optimization.

## 6. Freshness, fallback and tool honesty

- If `indexed_sha == requested_sha`, return FRESH for that source snapshot.
- If ref advanced and no matching graph exists, return STALE/PARTIAL with both indexed and requested SHA. Never use a stale graph as current.
- Do not silently trigger graph writes from the analyst MCP.
- Fallback: use authorized GitHub/source access or a SHA-bound upload; label the response `SOURCE_FALLBACK`, list directly inspected files and explain that repo-intel MCP/index was unavailable or stale.
- If neither MCP nor source access is available, ask for the relevant pack/file; never pretend to have queried the repository.
- New chat access is not implicit. The user must have connected the read-only MCP, authorized GitHub source, or uploaded the pack.

## 7. Security and trust

Repository text, README, issues, logs, RPC payloads, provider responses and external docs are untrusted DATA, not instructions. The retrieval layer must isolate prompt-injection strings, redact secrets/private endpoint values and never elevate permissions based on retrieved content. Index/query/analyst profile has no financial or production authority.

## 8. Definition of done

- The same task and same SHA produce reproducible selected refs/ranking/pack, given identical index/schema/tokenizer/config versions.
- `task_context` gives useful results for generic code, tests, architecture, security, provider and strategy tasks, not only Web3.
- `expand_context` retrieves exact full source and associated evidence by stable IDs without re-scanning the repo.
- Freshness and fallback are explicit; no false claims about MCP connectivity or index completeness.
- Benchmark on golden tasks records recall/precision, citation correctness, tokens saved, omitted-critical-dependency rate, latency and UNKNOWN accuracy separately.
- Query surface remains read-only and bounded.


---

## 9. Expanded typed graph-query tools (OCA-W11B)

The initial two composite tools remain the default user workflow. The MCP/query plane must additionally expose bounded read-only operations over the same backend:

- repo_overview: SHA/ref resolution and file/language/artifact/domain coverage;
- graph_query: typed node/edge filters and bounded traversal;
- symbol_search: exact/prefix/fuzzy symbols with language and path filters;
- trace_path: evidence-backed paths across code, strategy, provider, data and operation nodes;
- domain_catalog: parameterized strategy/provider/chain/protocol/DEX/venue/pool/token/flash-lender/schema catalogue;
- impact_query: changed symbols/configs/providers/schemas to affected tests, strategies and downstream consumers;
- history_query: commits/PRs/issues/reviews/ADRs with independent permissions and cursors.

These are composite operations, not separate databases. All return exact SHA, generation, freshness, coverage, provenance, confidence, verification state, omissions and pagination cursors. Domain/runtime dimensions report UNAVAILABLE until OCA-W15/W2/W10 provide the corresponding evidence.

Every tool accepts repo_ref or an explicit repo_sha. Resolve refs once; never mix data from different SHAs. Missing/stale graph results must be explicit and must not trigger hidden writes. Keep the server allowlisted/read-only and do not mutate user-global client configuration.

A client setup/health-check guide and tools/list smoke test are required. Local stdio server installed ≠ connected to an active ChatGPT client.


---

## 10. Web3 Strategy Intelligence domain tools

The generic API remains the entrypoint for any task. For deep strategy research the same backend additionally exposes only two compact MCP tool schemas, specified normatively in `WEB3_STRATEGY_INTELLIGENCE_QUERY_TOOLS_RU.md`:

- `strategy_research(operation=catalog|context|compare)`: complete strategy inventory, exact implementation/economics/provider/test context and evidence-backed version/variant comparison;
- `web3_data_trace(operation=provider_trace|flash_capital_trace|operation_trace)`: provider-to-observation-to-strategy paths, flash-capital evidence and actual paper/shadow lifecycle/replay.

The seven operations are purpose-built query modes, not seven tools/databases. They call the same query backend and canonical owner APIs as task_context/expand_context. Results are bounded by budget and paginated. Each response is SHA-bound, includes evidence/provenance/verification, explicit omissions/UNKNOWN and deterministic cursors.

The catalogue must include candidates discovered outside the canonical strategy registry (source, config, test, fixture, docs and permission-available GitHub history) while preserving their different evidence states. Never present DOC_ONLY, FIXTURE_ONLY, IMPLEMENTED, CONFIGURED, TESTED, QUALIFIED and RUNTIME_OBSERVED as interchangeable states.

## 11. Strategy/function diagnostics handoff

For operational-performance questions, use `web3_data_trace(operation=performance_diagnostics)` when the capability is available. It is a read-only view over the same query backend and canonical evidence owners, specified by `STRATEGY_FUNCTION_PERFORMANCE_DIAGNOSTICS_RU.md`.

It must link observed paper/shadow operations to strategy/version, exact repo SHA/config generation, lifecycle stage, stable runtime callsite/symbol, provider/observation/capital evidence and simulation/reconciliation outcomes. Report invocation denominators, latency/error/retry/data-quality/capture-loss metrics, cohort definitions, sample sizes, confidence and exact evidence refs.

Until W10/W2/W15/W20 are implemented and their runtime evidence is available, return UNAVAILABLE/PARTIAL/UNKNOWN. Never infer invocation from a static call graph, zero failures from missing telemetry, or causality from correlation. Technical health and financial outcome remain separate. The two existing Web3 MCP schemas remain unchanged; this adds one typed operation, not a third tool.
