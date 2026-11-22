# Repo Intelligence + Web3 Strategy R&D — implementation blueprint

**Purpose:** превратить Studious Pancake в постоянно обновляемую, проверяемую базу знаний о самом репозитории и его Web3-стратегиях. Coding agent индексирует и связывает факты; ChatGPT получает компактные, адресные, доказуемые контекстные пакеты и может исследовать как весь проект концептуально, так и отдельную стратегию/функцию до уровня исходного кода.

**Operating mode:** WEB3_FIRST. Инфраструктура обслуживает разработку стратегий, источников, рынков, маршрутов, qualification и paper/shadow evidence. Это не самостоятельный мегапроект и не требование развернуть все перечисленные SOTA apps.

## 1. Итоговый продукт: что система должна уметь

После внедрения базового набора функций агент и ChatGPT должны отвечать с evidence refs на вопросы:

1. Какие идеи, семейства, версии и варианты стратегий уже были предложены, реализованы, проверены, отвергнуты или заблокированы?
2. Где каждая стратегия находится: source files, symbols, entrypoints, callers/callees, configs, protocols, venues, providers, lenders, planner/compiler/simulator и tests?
3. Какие идеи дублируют старые, какие являются вариантами, а какие действительно добавляют новую механику?
4. Какие функции и данные необходимы стратегии; какие provider capabilities подтверждены фактически, какие только заявлены, а какие UNKNOWN?
5. Какие тесты и qualification receipts подтверждают поведение; какие результаты отрицательные; почему стратегия или источник были заблокированы?
6. Как изменялись функции, контракты, настройки и результаты между repo SHAs и по времени операции?
7. Какие runtime callsites действительно исполнялись в paper/shadow, а какие лишь статически могут вызываться?
8. Как получить подробное объяснение подсистемы, не передавая модели весь репозиторий?

**Definition of done:** по любому вопросу агент находит релевантные идеи/стратегии, точные функции, тесты, данные и историю, выдаёт ответ с путями/symbol IDs/SHAs/evidence IDs и отмечает пробелы. Никакая LLM summary не является источником истины.

## 2. Архитектура: несколько слоёв, единые IDs, канонические владельцы

### Layer 0 — canonical source of truth

Переиспользовать текущие владельцы, не строить второй аналог:
- Git и GitHub — код, документы, configs, tests, commits, PRs, issues и reviews в пределах доступных прав.
- src/intelligence — SHA snapshots, manifests, source extraction, import graph, history, SQLite index, context packs, coverage, retention/recovery и reporting.
- src/strategy и существующие strategy/qualification modules — стратегия, её версии, admission и qualification.
- src/market/source_catalog.py — зарегистрированные market data sources и ограничения.
- src/external_contracts — provider/API contracts, pinned artifacts и их evidence.
- src/provider_governance — provider entitlements, quotas, admission, cooldowns и reservations.
- src/agg02 — raw provider payloads, cursors, gaps, journals и replay owners.
- src/market/observations.py и src/market/streams.py — normalized market facts, generations, watermarks, completeness, corrections/retractions и streams.
- src/observability — EventEnvelope, operation event store, export, integrity и replay.
- MarketEpisode/episode_builder и qualification owners — episode/outcome projections и quality evidence.

Graph, search indexes, labels, catalogue, embeddings и context packs — derived read models. Нельзя копировать raw market rows в graph DB или создавать второй provider/strategy/observation registry.

### Layer 1 — repository inventory and code intelligence

Индексировать весь Git tree, не только Python imports:
- source code и multi-language packages;
- strategy ideas, research notes, ADRs, roadmaps, docs;
- configs, schemas, lockfiles, dependencies и build targets;
- CLI, scripts, GitHub Actions, Docker/infra;
- tests, fixtures, coverage и benchmark assets;
- source/provider adapters, RPC/API methods, venue/DEX/lender integrations;
- PRs, issues, reviews, commits — только то, что доступно connector/token permissions.

Каждая запись должна иметь точный путь и SHA; для кода — blob hash, language/parser, symbol IDs и byte/line ranges. Неинвентаризированные/неподдерживаемые типы файлов отражаются в coverage report.

### Layer 2 — typed multi-layer knowledge graph

Типы узлов минимум:
- Repo/Commit/Blob/File/Module/Package/Dependency/BuildTarget/Config/Schema/Test/Workflow/CLI/Tool;
- StrategyIdea/StrategyFamily/StrategyVersion/StrategyConfig/StrategyRequirement/Hypothesis/Experiment/Qualification;
- Chain/Protocol/Venue/Pool/Token/Asset/Market/FlashLender/Provider/Adapter/Endpoint/Stream/DataContract/Dataset/Observation;
- Run/Trace/Span/Event/Candidate/Decision/Quote/Simulation/Reconciliation/OperationEpisode/PaperOutcome/ShadowOutcome;
- PR/Issue/Review/ADR/WorkResultReceipt/LicenseRecord/CapabilityPolicy.

Связи минимум:
- code: DEFINES, IMPORTS, CALLS_STATIC, CALLS_RESOLVED, IMPLEMENTS, OVERRIDES, READS, WRITES, EMITS;
- strategy: IMPLEMENTED_BY, VARIANT_OF, EXTENDS, SUPERSEDES, REQUIRES_CAPABILITY, REQUIRES_PROVIDER, USES_SYMBOL, CONFIGURED_BY, TESTED_BY;
- data: PROVIDED_BY, FETCHED_THROUGH, NORMALIZED_BY, DERIVED_FROM, CONSUMED_BY, CORRECTS, RETRACTS, HAS_GAP, DISAGREES_WITH;
- runtime: EXECUTED_BY, OBSERVED_AT, DECIDED_ON, SIMULATED_BY, RECONCILED_TO, RESULTED_IN;
- engineering: CHANGED_BY, REVIEWED_IN, DOCUMENTED_IN, DECIDED_BY_ADR.

У каждого узла/ребра:
- repo SHA/blob hash или canonical owner ID;
- exact source/evidence ref;
- provenance: STATIC_EXTRACTED, COMPILER_RESOLVED, CANONICAL_REGISTRY, RUNTIME_OBSERVED, DOC_CLAIM, HUMAN_CONFIRMED или LLM_PROPOSED;
- confidence и verification state;
- parser/resolver/schema/ontology versions;
- valid-time и recorded-time где применимо.

AMBIGUOUS/UNRESOLVED/UNKNOWN — полноценные состояния. Совпадение имён не доказывает связь. CALLS_STATIC не равен RUNTIME_OBSERVED.

### Layer 3 — strategy knowledge registry

Для каждого найденного StrategyIdea и StrategyVersion собирать Strategy Card:
- stable ID, canonical family, name/aliases и variant lineage;
- problem/opportunity class, mechanism, assumptions, economic constraints и intended chains/venues;
- status: IDEA, RESEARCHED, PROPOSED, IMPLEMENTED, TESTED, PAPER, SHADOW, QUALIFIED, REJECTED, BLOCKED, SUPERSEDED или UNKNOWN;
- source evidence: docs, code, config, issue/PR/review/commit, authoring date и repo SHA;
- exact implementation symbols, call paths, adapters, strategy configs и tests;
- required market/provider/chain capabilities, replay/finality/quality requirements;
- experiments, fixtures, simulations, paper/shadow outcomes, negative results и qualification reasons;
- unresolved assumptions, blockers, missing tests и next evidence required.

**Novelty / duplicate analysis**
- Сопоставлять новую идею по механизму, входам, ограничениям, venue/chain, capital model, execution atomicity и outcome, а не только по названию.
- Возвращать POSSIBLE_DUPLICATE / RELATED_VARIANT / EXTENSION / DISTINCT_CANDIDATE / UNKNOWN с evidence.
- LLM может предложить связь, но не подтверждает её автоматически.
- Отрицательные результаты и отвергнутые идеи сохраняются; они предотвращают повторное исследование.
- Research universe остаётся максимально широким; flash-borrowability — отдельная capability, а не фильтр самого universe.

### Layer 4 — Web3 data and operational evidence

Реализовать WEB3-INFRA-S1..S6 из STRATEGIC_WEB3_INFRA_ASSIGNMENTS_RU.md:
- versioned provider adapter/data contracts;
- observed source mode, health, freshness, lag, gaps, reconnect and rate-limit evidence;
- chain-aware identity, block/transaction/log or chain-native coordinates, deployment identity, canonicality/finality;
- explicit correction/retraction/reorg handling, never silent history overwrite;
- StrategyDataRequirement and compatibility evaluation;
- lineage raw payload → normalized observation → episode/decision → quote/sizing/planner/compiler → simulation → reconciliation → paper/shadow outcome;
- cursor resume, backfill, deterministic replay and recovery receipts.

OpenLineage is an interoperable Run/Job/Dataset projection with Studious facets, not a replacement for EventEnvelope, AGG-02 or MarketObservation. DataHub-style catalogue is a projection, not a new facts store.

### Layer 5 — Retrieval and ChatGPT handoff

Provide a small stable read-only query surface. Recommended operations:
1. repo_overview — compact project map, SHA, coverage and freshness;
2. strategy_search — find ideas/families/versions by mechanism, chain, venue, capability or status;
3. strategy_explain — strategy card with exact implementation/test/evidence links;
4. symbol_context — exact symbol, full source body, callers/callees, dependencies and tests;
5. trace_operation — operation lineage, data provenance, gaps, replay and outcome;
6. strategy_compare — compare mechanisms, economics, versions, data requirements, tests, outcomes and negative evidence.
7. provider_search / provider_explain — source catalogues, adapters, contracts, capabilities, limits, health and observed source modes.
8. provider_trace — strategy → provider → adapter → endpoint/method → raw payload/cursor → normalized observation → consumers/tests.
9. flash_capital_trace — lender/capital capability → capacity/fee evidence → route/planner → simulation and blockers.
10. route_trace / operation_trace — static paths separately from runtime-observed lineage through paper/shadow results.
11. change_impact / test_impact — diff → symbols/config/contracts → affected strategies/providers/tests.
12. as_of — historical code, config, provider, strategy and evidence at repo SHA/operation time.
13. tool_inventory — MCP/CLI/apps/dependencies, versions, permissions, license and actual consumers.
14. build_context_pack — bounded export with selected depth, token budget, exact included/omitted refs and deterministic continuation cursor.

Return provenance and omissions explicitly. Keep analyst access read-only and separate from coding/admin tools.

## 3. Multi-resolution context: compress the map, not the evidence

Каждый pack обязан быть pinned to repo SHA and report exact token count (actual tokenizer if available; otherwise a clearly labelled estimate), included/omitted refs, coverage and continuation.

| Tier | Target | Contents |
|---|---:|---|
| T0 | 300–500 tokens | Repo card: current SHA, subsystems, strategy families, source/provider counts, major risks and coverage gaps |
| T1 | 1–3k tokens | Catalogues: strategies, providers, venues, tools, APIs, schemas, tests; one line per item + stable ID |
| T2 | 1–2k tokens initial slice | Task subgraph: directly relevant strategy, symbols, dependencies, configs, providers and tests; lazy 1–3 hop expansion |
| T3 | On demand | Exact full functions, schemas, configs, tests and evidence bodies; never summarise away target logic |
| T4 | As requested | Deep dossier: history, PR/issue discussions, negative evidence, alternatives, test outcomes, replay, confidence and unresolved questions |

Rules:
- target function and safety/economic logic are always FULL;
- direct dependencies may be SKELETON with exact symbol refs;
- outer graph neighbors may be REFERENCE/OVERVIEW;
- fetch full code/evidence by ID when analysis requires it;
- no truncation in the middle of critical code, exact decimal/unit logic, schemas or evidence chain;
- output includes explicit completeness state and omitted paths/IDs;
- compaction is not allowed to convert unknown into known or remove caveats.

Recommended retrieval order:
1. Exact strategy/symbol/contract IDs.
2. Lexical/BM25/FTS/trigram search.
3. Typed graph neighborhood and call/import paths.
4. Strategy relevance, config and test coverage.
5. Git churn/co-change and recent fixes.
6. Proven runtime frequency/stage outcomes (never inferred from static calls).
7. Semantic search only when exact/lexical/graph retrieval has a measured recall gap.

PageRank/Aider-style repo map is a ranking pattern, not a runtime dependency. Never rank purely by frequency: use task-conditioned relevance and strategy/data importance.

## 4. A–H: practical coding-agent assignments

A–H remain the capability taxonomy. The agent executes vertical slices in dependency order, not all letters as simultaneous PRs.

| Letter | Assignment | Priority | Main outputs |
|---|---|---|---|
| **A** | Repo-wide inventory, parser and SymbolGraph | P0 | Whole-tree catalogue, AST/symbol/call/import graph, stable IDs, confidence states, source-linked search |
| **B** | Incremental indexing and computation | P1 | Git blob/tree keyed cache, signature/body split, dependency invalidation, early cutoff, full reconciliation |
| **C** | Temporal provenance and versioned knowledge | P0 foundation | SHA-bound nodes/edges, valid/recorded time, strategy history, schema/ontology migrations, as-of queries |
| **D** | Agent-safe execution and mutation | P1; minimal controls P0 | Isolated worktrees, lease/scope, no-secret sandbox, resource/network limits, WorkResultReceipt |
| **E** | Retrieval, context packs and ChatGPT interface | P0 | Hybrid exact/lexical/graph search, T0–T4 packs, token budgets, read-only MCP/export and strategy explain |
| **F** | Verification and test economics | P1; critical gates P0 | Symbol→tests, impact analysis, coverage contexts, always-run safety suite, flaky registry and failure shrinking |
| **G** | Huge-repo and multi-agent plumbing | P2 | Sparse checkout/partial clone, watchers, partitioned scheduling, multi-client index and merge train only if needed |
| **H** | Token/security/license/resource governance | Cross-cutting P0 | Secret/prompt-injection controls, capability registry, token/cost telemetry, SBOM/license, resource governor and audit |

**Recommended implementation order**
- H0 + C0: minimum secret/access/provenance/receipt guardrails before external tooling or agent writes.
- A: inventory + native graph foundation.
- E: useful query/context/ChatGPT pack over A; measure retrieval and token saving on real Web3 tasks.
- Web3 S1–S6: provider contracts, quality, chain identity, strategy requirements, lineage and replay.
- F: close the loop from symbols and changes to tests and verified outcomes; mandatory tests remain mandatory.
- B: incremental refresh after a deterministic full build exists.
- D: strengthen task sandbox/isolation before increasing agent write autonomy.
- G: scale only when measured repo size/concurrency makes current design inadequate.
- H1: expand security/license/token/resource governance continuously.

A/C/E/H are the highest immediate leverage for a usable repository knowledge product. S1–S6 are the high-leverage domain layer for Web3 correctness. B/F/D make the product dependable. G and specialist infrastructure are scale-dependent.

## 5. SOTA functions and candidate technologies — use ideas, not a stack collection

| Capability | Preferred starting point | Candidate/reference | Adoption rule |
|---|---|---|---|
| Whole-tree/SHA snapshot | Existing Local Intelligence V2 | Git tree/blob addressing | Reuse existing owner |
| AST / incremental syntax | Native parser baseline + Tree-sitter | Tree-sitter Analyzer for precision benchmark | Use parser coverage/results, not grammar count |
| Compiler-level symbols | SCIP/LSP | language-specific SCIP indexers | Only for languages/builds actually supported |
| Repo map ranking | Native query-time ranker | Aider RepoMap/PageRank pattern | Copy algorithmic ideas; no dependency required |
| Scope-aware context | AST exact slicing | grep-ast / TreeContext | Keep exact source bytes and ranges |
| Structural audit/rewrite | Reviewed rules | ast-grep | Audit rules before transformations |
| Lexical search | SQLite FTS/BM25/trigram baseline | Zoekt/Tantivy | Replace only if measured search bottleneck |
| Persistent graph | Derived native graph over canonical stores | code-graph-mcp / codegraph / Graphify / CGC benchmark | Select zero or one; no automatic adoption |
| Large-scale graph facts | Existing graph baseline | Glean / LadybugDB | Only if scale/query benchmark fails |
| Incremental computation | Git hashes + dependency DAG + early cutoff | Salsa / Buck2 DICE / CocoIndex patterns | Build smallest native mechanism first |
| Runtime weighting | Proven operation telemetry | pprof / Parca, code-maat co-change concepts | Never confuse static call with observed execution |
| Test impact | Coverage contexts + dependency graph | pytest-cov contexts / pytest-testmon | Optimize selection; never skip mandatory safety tests |
| CLI token trimming | Structured compact reports | RTK | Benchmark loss; do not compress source or financial facts |
| Temporal history | Git SHAs + immutable evidence refs | CRG / jj / SQLite Session patterns | Keep one owner; no CRDT by default |
| Schema compatibility | Git schemas + CI gate (#672) | Apicurio Registry | External registry only for independent runtime publishers |
| Lineage | Native evidence + OpenLineage projection (#676) | Marquez | Projection never replaces canonical events |
| Metadata catalogue | Read-only projection (#673) | DataHub | Deploy DataHub only for measured multi-team/catalogue need |
| Event transport | Existing journal/queues | NATS JetStream (#675 adoption gate) | Only for measured multi-process fanout/backpressure |
| CDC | Existing canonical DB interfaces | Debezium (#674 adoption gate) | Only for actual DB-to-DB CDC |
| Durable workflow | Existing receipts/checkpoint/replay | Temporal | Only if retry/recovery tests show current workflow gap |
| Analytics | Existing Parquet/DuckDB owners where present | ClickHouse/Iceberg/lakeFS/Lance | Measure volume/concurrency/retention first |
| Supply chain | CI license/security checks | cargo-deny, Syft, ScanCode, gitleaks | Path-level audit; scanners are not legal approval |
| Sandbox | Isolated worktree/process/container | Wasmtime/Firecracker | Stronger isolation when threat/resource model requires it |

External candidates are pinned to exact tag/commit/license before evaluation. A README feature claim is not acceptance evidence. The agent must inspect installer side effects, MCP tools, hooks, telemetry, network and generated configuration in an isolated HOME. One persistent graph maximum; at most one complementary JIT extractor; no more than one semantic overlay (zero is valid).

## 6. Golden Web3 questions and acceptance corpus

Build a versioned golden question set with expected paths, symbol IDs, tests and evidence refs. At minimum:
- Find every flash-loan, flash-swap and flash-capital strategy variant; separate implemented, fixture-only, paper/shadow and unknown.
- Find all implementations of a selected strategy family, compare mechanism and identify duplicates/extensions.
- Which providers and exact methods feed this strategy? Which are STREAMING, POLL_ONLY, ONE_SHOT or UNAVAILABLE with evidence?
- Which functions calculate sizing, fees, slippage, route constraints and final profitability?
- Which tests cover each decision-relevant callsite? Which mandatory tests always run?
- Which changes in the last N commits/PRs altered this strategy, provider, schema or execution path?
- Which observations were stale, incomplete, corrected, retracted or affected by a reorg?
- Which strategy rejections are explained by missing data/provider health versus economic constraints?
- Can a paper/shadow episode be reconstructed on its original code SHA, config, provider evidence, schema and normalization version?
- Which earlier experiments/ideas were rejected and why; what evidence is missing before retry?
- What is the smallest exact context pack required to implement a new variant safely?

Score separately: strategy/idea recall, exact symbol recall, call-edge precision, test-link precision, provider-lineage coverage, evidence correctness, UNKNOWN accuracy, context tokens, omitted-critical-dependency rate, latency and freshness. A single blended graph score is prohibited.

## 7. Work packages, dependency map and delivery cadence

This blueprint maps onto existing OCA-W0..W19 and WEB3-INFRA-S0..S9 rather than creating a competing second backlog:
- owner audit / active PR reconciliation → OCA-W0 / S0;
- repo inventory, candidate bake-off and graph → OCA-W0A/W0B / A;
- provenance, correlation and temporal identity → OCA-W1/W2/W3/W15 / C;
- provider contract/health/chain/strategy fit → W13/W14 / S1–S4;
- runtime lineage/replay → W10/W11 / S5–S6;
- bounded query/context/ChatGPT → W4/W7/W11 / E;
- incremental compute → W16 / B;
- test economics → W18 / F;
- agent policy/sandbox → W17 / D;
- licensing and supply chain → W12 / H;
- conditional external infrastructure → W19 / G/S9.

No broad infrastructure swarm. One owner and one write scope per PR. Independent work only where files/owners are disjoint. Every implementation PR must include base/head SHAs, exact changed paths, tests, offline replay, benchmark receipts, test counts, coverage, license/source pins, risks and unresolved UNKNOWN. Do not merge implementation PRs without human approval.

## 8. How ChatGPT receives the knowledge

Do not claim ChatGPT automatically remembers or has unrestricted access to the local repo. Use one of three real delivery paths:
1. Authorized GitHub repository connector — fetch files/PRs/commit evidence on demand.
2. Explicit read-only local MCP connection — stable bounded tools from Layer 5.
3. Generated portable context pack — uploaded to the conversation, pinned to SHA with manifest and evidence links.

Recommended generated artefacts:
- CHATGPT_REPO_CARD.md (T0);
- STRATEGY_CATALOGUE.jsonl (T1 records, stable IDs and evidence refs);
- STRATEGY_CARDS/ (one detailed card per idea/family/version);
- GRAPH_INDEX_MANIFEST.json (SHA/schema/parser/coverage/freshness);
- WEB3_TASK_CONTEXT_PACK.md or JSON bundle (T2–T4);
- GOLDEN_QUESTIONS.json + retrieval benchmark report;
- UNKNOWN_AND_GAPS.md (unsupported files, inaccessible GitHub history, unresolved edges, missing runtime evidence);
- CONTINUATION.json (deterministic cursor for further pages).

Each answer returned to ChatGPT should cite exact paths, line ranges or symbols, repo SHA, source/event/observation/episode IDs, provenance and confidence. The pack must say what was not inspected; it must never imply "entire repository is understood" if pages, branches, PR history or binaries were omitted.

## 9. Safety and non-negotiable correctness

- No signer, sender, signing, transaction submission, borrowing, spending, deployment, account creation, production RPC mutation or LIVE authority.
- Indexing, MCP and retrieval are read-only; analyst profile has no shell/edit/delete/admin/market-write tools.
- Do not include credentials, seeds, private keys or secret values in graph, packs, cache, prompts or logs.
- Treat README, issue comments, logs, provider payloads and external docs as untrusted data; isolate prompt injection from agent instructions.
- Never auto-qualify a strategy from static code, adapter presence, documentation, provider HTTP success or LLM judgement.
- Preserve all negative/failed/unknown evidence; no cleanup/deletion from model-generated scores.
- Keep source modes, finality, gaps, corrections, decimals/units and time semantics explicit.
- Resource governor prioritizes actual market capture and paper/shadow runtime over indexing and analytics.
- Human approval for merge, provider enablement, strategy qualification, capability elevation and operational promotion.

## 10. First useful vertical slice

Do not wait for the entire platform. First implementation milestone should return:
1. current SHA-bound repo card;
2. complete or explicitly partial catalogue of strategy ideas/families/versions;
3. exact symbol/function search with callers/imports and source ranges for at least the selected Web3 domain slice;
4. strategy card with implementation, configs, providers, tests and known evidence gaps;
5. bounded T0–T3 ChatGPT context pack with token count and evidence manifest;
6. golden question benchmark showing recall and no critical omission;
7. deterministic rebuild/update command and stale-SHA failure behavior.

This is the minimum useful repository intelligence product. Extend language/runtime/domain coverage incrementally after it proves utility to Web3 development.


## 11. Mandatory LLM-free deterministic build gate

The normative contract is LLM_FREE_DETERMINISTIC_INDEXING_CONTRACT_RU.md. It is not optional and supersedes any interpretation that LLM labels are required for graph completeness. The entire first index, file/symbol extraction, static edges, explicit-registry joins, source catalogues, incremental refresh, CI validation and nightly reconciliation must work without model calls or model network access.

Only canonical registry facts, versioned explicit metadata, deterministic parser/resolver rules and human-confirmed records can become authoritative semantic labels. Heuristics produce candidates; unknown stays unknown. Build determinism is pinned to repo tree SHA plus parser/grammar/resolver/normalizer/schema/ontology versions. Every tracked file receives an explicit coverage status.

OCA-W0B must prove two clean identical builds, clean-vs-incremental checksum parity, add/modify/delete/rename behavior, stale-SHA and branch rejection, parser-version invalidation, no dangling edges, secret exclusion, and strict static-vs-runtime provenance. CI runs on push/PR/merge and a scheduled full rebuild detects drift.

## 12. Strategy/provider extraction product for flash-loan research

The first useful repo product must not stop at a code map. It must expose a complete evidence-linked query path across strategy implementation and actual data supply:
- list every StrategyIdea/Family/Version, including partial, rejected, blocked, fixture-only, paper and shadow evidence;
- list every provider/source/adapter/API/RPC/DEX/oracle/indexer/flash-lender SDK and its exact methods, contracts, consumers and tests;
- trace strategy → required capability → provider/adapter → raw data/cursor → normalizer/observation → candidate/decision → flash-capital proof → quote/fees/sizing → route/planner/compiler → simulation → reconciliation → paper/shadow outcome;
- return PROVEN / STATIC_ONLY / DOC_CLAIM / MISSING / UNKNOWN rather than implying an end-to-end trace where producers are not wired;
- retrieve exact full source bodies, configs, fixtures, contract/IDL/schema evidence and tests by stable symbol/evidence IDs on demand;
- include PR/issue/review/commit history where GitHub permissions allow, while explicitly recording inaccessible ranges.

The analyst interface should offer strategy_search, strategy_explain, strategy_compare, provider_search, provider_explain, provider_trace, flash_capital_trace, symbol_context, route_trace, operation_trace, change_impact, test_impact, as_of, tool_inventory and build_context_pack. This is the required interface contract; implementation may map it to existing CLI conventions rather than creating a new service for every method.

## 13. SOTA capability selection: implement functions, not a pile of apps

The repository must own the capabilities listed in the LLM-free contract: polyglot AST/symbol inventory, scoped extraction, typed graph/provenance, exact lexical + graph retrieval, incremental invalidation, temporal/as-of evidence, provider/data contracts, quality/reorg/replay semantics, test impact, token-aware packs, secure read-only access and CI reconciliation.

Candidates are function-specific:
- Tree-sitter + selected SCIP/LSP indexers for syntax and cross-file precision;
- ast-grep and grep-ast/TreeContext for structural rules and exact enclosing scopes;
- Aider/PageRank for task-conditioned repo map ranking;
- SQLite FTS5/BM25/trigram first; Tantivy/Zoekt only if measured scale requires it;
- one graph backend at most (native first; code-graph-mcp/CodeGraph/CGC/Graphify bake-off; Glean/LadybugDB only for scale/query gaps);
- Git blob/tree hashes + dependency DAG + early cutoff first; Salsa/Buck2 DICE/CocoIndex patterns only if needed;
- OpenLineage facets over EventEnvelope/AGG-02/MarketObservation; DataHub/Apicurio/NATS/Debezium/Temporal only at their documented adoption gates;
- pytest coverage contexts, test impact, Hypothesis/mutation/failure shrinking for verification;
- cargo-deny/Syft/ScanCode/gitleaks for supply chain; process/worktree sandbox first, Wasmtime/Firecracker only for stronger isolation;
- Parquet/DuckDB first, with ClickHouse/Iceberg/lakeFS/Lance behind measured storage gates.

No external candidate is installed because it is listed. Pin commit/version/license, inspect permissions/network/telemetry/installer side effects, run same-SHA golden benchmarks and keep rollback. Zero adoption is valid.


## 14. Universal task-context interface for every repository task

Implement `task_context` and `expand_context` as the two generic entrypoints over the single read-only query backend. The detailed request/response schemas, routing, freshness, fallback, security and acceptance rules are normative in `UNIVERSAL_TASK_CONTEXT_API_RU.md`.

- `task_context(task, depth="adaptive", budget_tokens=?, dimensions="auto", repo_ref="main", repo_sha=?)` starts from the user's natural-language task, pins an exact repository snapshot, checks graph freshness, and retrieves relevant nodes and evidence.
- `expand_context(refs, dimensions, depth="full", budget_tokens=?, repo_sha)` retrieves exact source and further dependencies by stable IDs from the first response. It must not rescan or resend unrelated repository content.
- Use one backend from CLI, MCP and portable exports. The MCP exposes these as bounded read-only composite tools. Existing specialized operations (strategy/provider/trace/test/history queries) remain internal query functions called by the router, rather than forcing the user/model to choose a long tool list.
- Adaptive retrieval works for every task category: bug fix, feature, refactor, architecture, test failure, performance, security/license audit, provider integration, strategy R&D and PR review.
- Use exact symbol/ID matching, lexical retrieval, typed graph traversal, dependency/test/config/contract/change signals and proven runtime evidence. Semantic/vector search is optional fallback after measured recall gap.
- Return a SHA-bound evidence pack with freshness state, graph generation, dimensions, depth, tokenizer and token count, included/omitted refs, unknowns, confidence/provenance and deterministic continuation.
- A stale/unavailable index is never presented as current. Fall back to authorized GitHub/source or an uploaded pack and state the limitation.
- Compression deduplicates and summarizes only surrounding context. Target logic, direct required dependencies, financial calculations, decimal/unit/time semantics, contracts, tests and evidence must remain full or be retrievable exactly by ID without omission.

This is the universal interface: a new task should require only its natural-language description. The router, not the user, discovers what repo context is relevant.
