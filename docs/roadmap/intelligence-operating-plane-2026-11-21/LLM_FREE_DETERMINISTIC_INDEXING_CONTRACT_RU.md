# LLM-FREE DETERMINISTIC INDEXING CONTRACT

**Статус:** обязательный контракт OCA-W0B; acceptance gate для первой полной индексации и каждого последующего обновления.  
**Назначение:** построить полную, воспроизводимую и автоматически обновляемую карту репозитория без LLM, model API, embeddings API или сетевого обращения к модели.  
**Область:** Git-код и все отслеживаемые артефакты, code/symbol graph, strategy/source/provider catalogues, labels, context-pack manifests и CI refresh.  
**Не является:** запретом использовать ChatGPT для последующего анализа готового индекса. LLM-assisted research — отдельный read-only слой и никогда не является источником истины.

## 1. Жёсткие гарантии

1. **Zero-LLM bootstrap.** Полная первичная сборка должна выполняться офлайн, без model credentials, model SDK, prompt, remote embedding, hosted semantic index или вызова LLM. CI доказывает это отдельным запуском с запрещённым egress/model endpoints и отсутствием model secrets.
2. **Deterministic output.** Для одного и того же Git tree SHA, dirty-worktree snapshot (если явно включён), pinned parser/grammar/resolver/normalizer versions, graph schema и ontology versions результат имеет одинаковые canonical node/edge/label records и checksum. Build timestamps, случайные ID и порядок файлов не влияют на graph content.
3. **No silent omissions.** Каждый tracked file и обнаруженный symbol получает индексный статус: INDEXED / PARTIAL / UNSUPPORTED / EXCLUDED_WITH_REASON / PARSE_ERROR / UNCLASSIFIED. Unsupported языки, бинарники, LFS pointers, generated/vendor assets и недоступная GitHub history учитываются в coverage report, а не исчезают.
4. **Explicit semantics only.** Семантические сведения о StrategyFamily/StrategyVersion/Provider/Venue/FlashCapitalSource берутся из существующих canonical registries, versioned manifests/contracts, проверяемых AST/code rules или human-confirmed facts. Name/path heuristics могут создавать только PROPOSED/UNCLASSIFIED candidate.
5. **No automatic verification.** UNKNOWN, AMBIGUOUS, UNRESOLVED, DOC_CLAIM и LLM_PROPOSED нельзя автоматически повышать до VERIFIED. Совпадение имени, документация, HTTP 200, наличие adapter или статический вызов не доказывают runtime usage, provider health, qualification или financial capability.
6. **Typed provenance.** Каждое ребро и label хранит source/evidence ref, repo SHA/blob hash или canonical owner ID, producer/parser/resolver/schema version, provenance, confidence/status и temporal fields, когда применимо.
7. **Deterministic incremental refresh.** Каждый commit обновляет граф по Git tree/blob diffs и dependency invalidation. Add/modify/delete/rename, submodules/LFS, parser/schema/ontology upgrades и branch changes обрабатываются явно. Stale-SHA или wrong-branch index не может быть использован как current.
8. **Full reconciliation.** Nightly или периодический полный rebuild сравнивает canonical checksums с incremental index для того же SHA и выявляет drift, missed triggers, stale labels и dangling edges.
9. **Static ≠ runtime.** CALLS_STATIC / CALLS_RESOLVED / READS / WRITES остаются статическими/компиляторными facts. EXECUTED_BY / OBSERVED_CALL / RUNTIME_OBSERVED создаются только по доказанным producer events/traces/coverage evidence.
10. **Read-only intelligence.** Indexer, graph query, context pack и analyst MCP не получают signing, sending, borrowing, spending, deployment, provider-enable, production-RPC mutation или LIVE capabilities.

## 2. Canonical deterministic build contract

### 2.1 Immutable inputs and cache keys

Обязательные входы:
- repository ID + Git commit SHA + Git tree SHA; для dirty worktree — отдельный явно созданный content manifest и его hash;
- submodule commit IDs, LFS pointer/object status и доступность объектов;
- parser, grammar, language resolver, SCIP importer, normalization rules, graph schema, label ontology и pack schema versions;
- indexer build/version и deterministic configuration;
- branch/ref identity, чтобы не смешивать параллельные worktrees.

Базовые cache keys:
- parse: (blob_sha, language, parser_version, grammar_version, parser_config);
- symbols/edges: (blob_sha, parser_key, resolver_version, schema_version);
- graph snapshot: (tree_sha, indexer_version, graph_schema, ontology_version, canonical_owner_generation);
- context result: (repo_sha, graph_generation, query_hash, pack_schema, tokenizer_version, token_budget).

Git tree/blob hashes — первичный content-addressed механизм. Не вводить второй Merkle tree, snapshot owner или path-only cache без измеренного пробела.

### 2.2 Полная инвентаризация

Индексировать и учитывать coverage:
- source code всех найденных языков, modules/packages, types/interfaces/classes/functions/methods, callsites, imports, declarations, build targets;
- documentation, ADR, research notes, roadmaps, strategy cards/manifests;
- configs, feature flags, schemas, lockfiles, dependency manifests, units/decimals/time semantics (секретные значения запрещены);
- tests, fixtures, property/mutation tests, benchmark and coverage contexts;
- CLI commands, scripts, MCP servers/tools, plugins, GitHub Actions, workflows, Docker/infra;
- external data source/provider/adapter/API/RPC/DEX/venue/lender references and consumers;
- GitHub Issues, PRs, reviews, commits and releases as a separate permission-bounded evidence feed with its own source cursor/retrieval time. GitHub history is not silently presented as part of a Git tree SHA.

Для каждого файла — path, blob SHA, language/artifact type, parser/coverage status, byte/line ranges and reason for exclusion. Для symbol — stable symbol ID, qualified name, signature, enclosing scope, source range and parser/resolution status.

### 2.3 Symbol and edge resolution

- Использовать native Python AST там, где это уже владелец, Tree-sitter для polyglot syntax, SCIP/LSP only for languages with working indexers/builds, и language-specific resolver only where precision is measured.
- Emit explicit relation classes: DEFINES, IMPORTS, CALLS_STATIC, CALLS_RESOLVED, IMPLEMENTS, OVERRIDES, READS, WRITES, EMITS, TESTED_BY, CONFIGURED_BY.
- Для каждого callsite записывать resolution method: lexical, AST, import resolver, compiler/SCIP/LSP, explicit registry or unresolved.
- Overloads, dynamic dispatch, reflection, dependency injection, plugin registries and runtime monkey-patching stay AMBIGUOUS/UNRESOLVED until evidence resolves them. Same-name matching alone never emits verified CALLS_RESOLVED.
- Stable identity includes repository namespace, language, qualified symbol path and identity evidence. Rename/move continuity can be proposed using Git similarity/blob and symbol fingerprint; ambiguous moves create a relation candidate, not silent identity rewrite.

### 2.4 Deterministic strategy and provider metadata

Use canonical existing owners before adding new registries. A new explicit metadata record may be added only through a versioned schema with owner, status and evidence:
- StrategyIdea / StrategyFamily / StrategyVersion / StrategyConfig / StrategyDataRequirement;
- Provider / Adapter / ProviderCapability / DataContract / Endpoint / Stream;
- Chain / Protocol / Venue / Pool / Token / ContractDeployment / FlashCapitalSource;
- Hypothesis / Experiment / Qualification / NegativeResult / PaperOutcome / ShadowOutcome.

Rule-based extraction can propose candidates from file paths, symbol names, decorators, manifests and explicit registration calls, but those candidates remain UNCLASSIFIED/PROPOSED unless linked to canonical metadata. Every explicit rule has a rule ID/version and reproducible evidence.

## 3. Web3 and flash-loan source trace contract

The graph must be able to represent and query this chain without assuming every edge is already proven:

StrategyIdea/Version
→ entrypoint and exact symbols
→ static/resolved callers and route/planner/compiler/simulator
→ StrategyConfig + StrategyDataRequirement
→ Provider/Adapter/Endpoint/Stream + DataContract
→ raw payload + cursor/watermark + source health
→ normalized MarketObservation + EntityIdentity
→ candidate/decision/rejection + MarketEpisode
→ flash-capital/lender capability and capacity evidence
→ quote + fee/slippage/size calculation
→ route + planner + compiler
→ sender-free simulation
→ reconciliation
→ paper/shadow outcome + qualification/negative evidence

For each provider/adapter contract capture:
- provider_id, adapter_id/version, owner and enabled/disabled status;
- network/chain identity, venue/protocol, deployment identity, endpoint/method/stream (never secret-bearing URLs or credentials);
- supported methods, pagination/cursors, historical/replay capability, request cadence/quota/rate-limit policy;
- declared and **observed** modes STREAMING / POLL_ONLY / ONE_SHOT / UNAVAILABLE;
- DataContract/schema ID/version, required fields, units, decimals, nullability, rounding and timestamp semantics;
- cursor, watermark, event time, ingest time, recorded time;
- measured freshness, lag, coverage, gaps, reconnects, outage/health episodes and source disagreement;
- raw payload ID/ref/hash, normalization version, dedupe key, correction/retraction/reorg behavior and replay receipt.

Required domain nodes/evidence:
- ProviderCapability, DataContract, SourceHealthEpisode, EntityIdentity, NormalizationRule, DataQualityEvidence, SourceDisagreement, DataLineageEdge;
- chain identity includes network discriminator/genesis where available; chain-native block/slot, block hash, transaction/signature, transaction index, EVM log index or chain-native instruction/event coordinates, program/contract deployment/version and canonicality/finality;
- reorg/fork/correction/retraction is a new linked fact with explicit invalidation/replay, never silent history overwrite;
- StrategyDataRequirement declares capabilities and policy; CompatibilityEvaluator returns COMPATIBLE / PARTIAL / INCOMPATIBLE / UNKNOWN with reason codes and evidence. Adapter present ≠ capability observed ≠ strategy qualified ≠ live authority.

Missing joins remain MISSING/UNKNOWN. A static function path does not prove it fed a given paper/shadow decision. Runtime links require real event producer, stable callsite, trace/span or equivalent evidence and IDs from canonical owners.

## 4. Required repository-native capabilities

Build these functions in the repo using existing owners; external project names below are candidate implementations/patterns, not mandatory dependencies.

| Capability to implement | Native starting point / candidate pattern | Required result |
|---|---|---|
| Repo snapshot and file inventory | Existing src/intelligence, Git tree/blob | SHA-bound all-artifact manifest and coverage |
| Polyglot parsing and symbol IDs | Tree-sitter; native AST; SCIP/LSP by supported language | Syntax/symbol graph with per-language resolution tier |
| Structural source retrieval | AST enclosing-scope extraction, grep-ast/TreeContext; ast-grep audit rules | Exact full function + direct callers/callees/test context |
| Query-time repo map | Aider RepoMap/PageRank pattern | Task-personalized ranked graph slice under budget |
| Lexical retrieval | SQLite FTS5/BM25/trigram baseline; Tantivy/Zoekt only at scale | Fast exact identifier/text search |
| Persistent graph facts | Existing SQLite/native graph first; benchmark code-graph-mcp/CodeGraph/Graphify/CGC | Zero or one chosen graph backend; exact provenance |
| Incremental engine | Git hashes + dependency DAG + signature/body split + early cutoff; Salsa/Buck2 DICE/CocoIndex ideas | Recompute only affected derived nodes; full reconciliation |
| Temporal history | Git SHAs + bitemporal valid/recorded times; CRG/jj as reference | As-of code/config/strategy/data query |
| Provider and schema catalogues | Existing source catalog/external contracts/provider governance; OpenLineage facets | Versioned adapters/contracts, health and lineage |
| Metadata catalog UI/query | Native read-only query; DataHub as future candidate | Owners, dataset metadata, lineage without duplicate fact store |
| Schema registry | Schemas in Git + CI; Apicurio only for independent publishers | Compatibility, migration and consumer requalification gates |
| Event transport / CDC | Current journals/stores; NATS / Debezium only for proven transport/DB CDC gap | Bounded delivery/replay or DB change stream only when needed |
| Durable long-running workflow | Current receipts/checkpoints/replay; Temporal only if recovery tests fail | Resumable workflow with idempotency and receipts |
| Runtime evidence and trace | EventEnvelope/Observability + OpenTelemetry concepts; pprof/Parca for optional sampling | Proven callsite-to-operation evidence, no static/runtime conflation |
| Analytics and archive | Existing Parquet/DuckDB; ClickHouse/Iceberg/lakeFS/Lance only by volume/SLA gate | Costed retention, reproducible query and restore |
| Test impact and correctness | pytest-cov contexts, affected-tests/testmon, Hypothesis, mutmut, ddmin/HDD | Symbol→test mapping, invariant suite, failure minimization |
| Security and supply chain | cargo-deny, Syft, ScanCode, gitleaks, path-level audit | SBOM/license/advisory/secret gates and audit receipts |
| Sandbox and agent isolation | Git worktrees, leases, process/container limits; Wasmtime/Firecracker only as needed | Scoped execution, no inherited runtime secrets or finance capability |
| Context and token efficiency | T0–T4 packs, real tokenizer, exact-hash cache, RTK-style CLI trim only after loss tests | Max context utility without lossy source/evidence compression |

**Explicit conditional tools:** OpenLineage is a portable Run/Job/Dataset contract and facets, not a replacement for EventEnvelope/AGG-02/MarketObservation. DataHub is a metadata catalogue/ingestion platform, not a DEX/RPC provider implementation. Apicurio is a hosted schema/API registry, not a replacement for versioned schemas in Git. NATS JetStream is optional event delivery/retention/replay, not the canonical fact database. Debezium is database CDC, not blockchain RPC ingestion. Temporal is durable workflow orchestration, not automatically required when receipts/checkpoints work.

For all candidates: pin commit/tag, exact license paths and transitive SBOM; inspect install hooks, MCP/CLI permissions, telemetry, network, generated files and update behavior in isolated HOME. A feature claim or README is not acceptance evidence. Same-SHA/golden-query benchmark required. Zero adoption is a valid result.

## 5. Incremental refresh, CI and reconciliation

Required update flow:
1. Receive commit/PR event or explicit local refresh; resolve exact repo tree SHA and branch/worktree identity.
2. Compare Git tree/blob manifest: added, changed, deleted, renamed, mode changes, submodule/LFS changes.
3. Reuse parse cache for unchanged content; invalidate changed parser/resolver/schema generations.
4. Update file/symbol inventories; recompute affected signatures, import/call/implementation/config/test/source edges.
5. Propagate dependency invalidation through reverse DAG; early-cutoff when output hash is unchanged.
6. Revalidate labels and downstream StrategyDataRequirement/consumer links; stale facts become STALE/NEEDS_REVIEW, never auto-VERIFIED.
7. Run deterministic integrity checks and generate compact index delta + WorkResultReceipt.
8. Publish SHA-bound artifact/cache and PR comment/report; branch indexes never contaminate main.
9. On merge to main publish the new main generation; scheduled full rebuild compares canonical checksums with incremental output.
10. Preserve previous graph generations for history/as-of queries and rollback; no silent deletion of evidence.

CI jobs:
- push/PR: changed-file incremental build, deterministic output checks, dangling-reference checks, schema/ontology validation, secret scan, source/evidence link integrity and context pack token ceiling;
- merge to main: canonical refresh or verified artifact generation at exact head SHA;
- nightly: complete rebuild, checksum equality, stale/missing trigger detection, parser coverage drift and label revalidation report;
- parser/grammar/resolver/schema/ontology version change: invalidate relevant caches and rebuild affected scope;
- resource governor: single writer, lock/lease, queue coalescing, cancellation and CPU/RAM/IO/disk/WAL limits; index jobs yield to market ingestion and paper/shadow work.

## 6. Mandatory acceptance gate

OCA-W0B cannot be marked DONE unless all items pass or have a specifically approved BLOCKED_WITH_EVIDENCE exception:

- [ ] Build works with no LLM package call, no model API credentials and no model network access.
- [ ] Two clean builds at same inputs/versions produce byte-identical canonical graph manifests and checksums.
- [ ] Same-SHA rebuild after cache deletion matches incremental graph checksums.
- [ ] Every tracked file is represented by a coverage status; unsupported/excluded/error paths have reason codes.
- [ ] Every parsed symbol has a stable ID, source hash and exact byte/line range; parser errors are visible.
- [ ] Add / modify / delete / rename / case-only rename tests pass; no ghost nodes or dangling edges remain.
- [ ] Parser, grammar, resolver, schema, ontology and normalization version changes invalidate affected caches.
- [ ] Stale SHA, dirty tree, wrong branch and mixed worktree index are rejected or explicitly namespaced.
- [ ] Static, compiler-resolved, canonical-registry, doc-claim, human-confirmed and runtime-observed edges are separated.
- [ ] Unknown / ambiguous / unresolved labels cannot be promoted by scoring or name matching.
- [ ] Strategy and provider catalogue entries resolve to canonical IDs or remain PROPOSED/UNCLASSIFIED.
- [ ] CI push/PR refresh works; main merge refresh is pinned; nightly full-vs-incremental reconciliation reports drift.
- [ ] Critical decision, correction, gap, replay and paper/shadow outcome events are not sampleable or silently dropped.
- [ ] No secret values, credentials, keys, seeds, private endpoints or sensitive payloads are written to graph/packs/logs.
- [ ] Read-only query/MCP profile exposes no shell, edit, delete, admin, signer, sender, provider-enable or LIVE capability.
- [ ] Context pack enforces actual tokenizer budget (or labelled byte estimate), lists omissions, includes stable refs and fetches exact target code FULL.
- [ ] 30–50 golden Web3 questions are benchmarked; report strategy recall, symbol/call/test precision, provider trace coverage, UNKNOWN accuracy, critical omission rate, tokens, latency and freshness separately.
- [ ] Index CPU/RAM/IO/queue ceilings do not starve provider capture, paper/shadow or recovery owners.

No blended score can hide failure of one critical invariant. No unsupported language or inaccessible GitHub source is described as fully indexed.

## 7. Delivery order and PR discipline

**Wave 0 — parallel read-only reports:** OCA-W0 owner/runtime audit, OCA-W0A tool bake-off (including a preliminary read-only path-level license/SBOM/security inventory), and OCA-W0C provider/source/strategy trace inventory. Separate worktrees and disjoint report paths only. The dedicated OCA-W12 gate/remediation follows once the candidate inventory is pinned.

**Wave 1 — first implementation:** OCA-W0B deterministic index + graph + labels + compact catalogue + read-only CLI + CI/nightly + SHA-bound pack. Implement native minimal capability first; adopt only measured candidate winners.

**Wave 2 — typed temporal and domain data plane:** OCA-W1/W2/W3, WEB3-INFRA-S1..S4 and OCA-W13/W14/W15. Serialize writes to canonical owners; independent reports/PRs only when paths are disjoint.

**Wave 3 — real operation lineage and recovery:** OCA-W10/W11 and WEB3-INFRA-S5/S6; instrument actual supported test/paper/shadow producer paths, prove capture/restart/backfill/replay and expose a bounded read-only facade.

**Wave 4 — retrieval and scale improvements:** OCA-W4/W7/W18/OCA-W16; T0–T4 packs, symbol-to-test impact, incremental invalidation, retrieval benchmark and resource governor. G/S9 storage/transport/sandbox upgrades remain evidence-gated.

One work package = one owner + isolated worktree + declared write scope + reviewable PR. Do not duplicate open #672–#676. Do not start every package concurrently. No automatic merge, provider enablement, qualification, financial permission or production promotion.

## 8. ChatGPT consumption contract

The indexer is LLM-free; the query result is prepared for LLM analysis. The model receives only explicitly requested, SHA-bound evidence. It must be able to ask for more context using stable IDs, without rerunning the complete repository scan.

Expected query operations:
- repo_overview: SHA, coverage, freshness, subsystem map, key risks.
- strategy_search: ideas/families/versions/aliases/status/variants/negative results.
- strategy_explain / strategy_compare: mechanism, economics, implementation, tests, configs, qualification and evidence gaps.
- provider_search / provider_explain: provider, chain, protocol, methods, endpoint class, source mode, contracts, quality and limits.
- provider_trace: strategy → provider → adapter → endpoint/method → raw payload/cursor → normalized observation → consumers/tests.
- flash_capital_trace: lender/provider → capability → capacity/fee evidence → route/planner use → simulation and blockers.
- symbol_context: exact full symbol, callers/callees/imports/configs/tests and resolution provenance.
- route_trace: strategy → quote/sizing → planner/compiler → simulation → reconciliation → paper/shadow result.
- operation_trace: runtime-observed event/trace/episode chain, gaps, replay and outcome.
- change_impact / test_impact: changed symbols/config/contracts → affected strategies/providers/tests.
- as_of: reproduce the code/config/provider/strategy/evidence view at a historical repo SHA or operation time.
- tool_inventory: MCP/CLI/apps/dependencies, versions, permissions, license and actual consumers.
- build_context_pack: T0–T4 depth, target token budget, exact included refs, explicit omissions and deterministic continuation cursor.

Each response returns repo SHA, graph generation, exact source/evidence refs, provenance, confidence/status, coverage, omissions and next expansion IDs. The ChatGPT analyst profile is read-only. A new chat receives the data through authorized GitHub access, an approved local read-only MCP connection, or an explicitly uploaded context pack; no implicit local-disk access is assumed.


## 9. Universal adaptive task context API

The generic interface contract is specified in `UNIVERSAL_TASK_CONTEXT_API_RU.md`. This is a mandatory reusable capability for all repository tasks, not a strategy-only helper.

OCA-W0B must deliver the minimal native query service and CLI support for:
- `task_context(task, repo_ref, repo_sha?, depth=adaptive, budget_tokens?, dimensions=auto)`: resolve the exact snapshot, check index freshness, return the smallest sufficient T0–T2 slice and exact next expansions;
- `expand_context(refs, dimensions, depth, budget_tokens?, repo_sha)`: fetch exact source/tests/configs/contracts/providers/history/runtime evidence by stable IDs without repeating the full scan.

OCA-W4 hardens adaptive ranking, progressive disclosure, tokenizer fitting, continuation, multi-resolution contexts and evidence-completeness evaluation. OCA-W11 exposes the same shared query service through the allowlisted local read-only MCP. CLI, MCP and portable export must call one backend; they must not implement separate retrieval logic.

The initial retrieval route is exact IDs/symbols → lexical/FTS → typed graph → tests/config/contracts/change-impact → proven runtime evidence → optional semantic fallback only when a measured recall gap remains. Every response includes requested/indexed SHA, graph generation, freshness, actual tokens or labelled estimate, included/omitted refs, provenance and deterministic continuation cursor.

Default `adaptive` depth means T0 overview + relevant T1 catalogue + bounded T2 task subgraph; T3 exact target code and dependencies are fetched as required, and T4 deep history/replay is available on demand. Never truncate critical target code mid-function. Budget overflow is explicit and recoverable through `expand_context`, not silent loss.
