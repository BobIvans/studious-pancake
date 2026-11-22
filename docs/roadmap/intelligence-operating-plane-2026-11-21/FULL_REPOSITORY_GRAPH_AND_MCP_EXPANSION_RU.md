# FULL REPOSITORY GRAPH + EXPANDED MCP QUERY SURFACE

**Status:** mandatory design addendum for PR #666; implementation is assigned to follow-on PRs.  
**Purpose:** close the gap between “every tracked file is inventoried” and “the whole repository is meaningfully searchable as a typed, evidence-linked knowledge graph”.  
**Primary owners:** OCA-W0B2, OCA-W4B, OCA-W11B; then existing OCA-W15/W16/W10/W2.  
**No new A–H letters:** these are completion tasks under A/B/C/E/F/H and the existing W0–W19 taxonomy.

## 1. What the current W0B/W4/W11 delivery does — and does not — mean

The current implementation PRs report a deterministic graph build on pinned main with 3,421 tracked files, 1,851 Python modules parsed, 26,772 nodes and 71,812 edges; W0B reports 39/42 golden-question recall and W4 reports 42/42 after directory-ref handling. These are useful measured results, not proof of universal structural coverage.

Code inspection of the implementation branches identifies these boundaries:

- W0B inventories tracked paths and has a Python stdlib-AST structural parser. Its current language classifier recognizes Python and text/config suffixes; other code languages are not yet structurally parsed by this backend.
- A file coverage row is not the same as a full symbol graph. Documentation/configuration files, scripts, workflows, schemas and non-Python code must have suitable searchable/structured representations and explicit coverage states.
- The current parser cache is keyed by blob and parser version, but the build still walks the inventory and rebuilds the graph edge set. This is parse memoization, not yet the full signature/body split + dependency invalidation + early-cutoff engine assigned to OCA-W16.
- W0B retrieval currently centres on exact refs, SQLite FTS/lexical ranking and graph neighbors. W4 improves deterministic routing and directory references. The current token counter is a labelled UTF-8 byte estimate, not a model tokenizer.
- W11 currently exposes three local stdio JSON-RPC tools: repo_overview, task_context and expand_context. The calls require a supplied repo SHA; the server is local code, not an automatically connected ChatGPT service.
- W13/W14 define provider/strategy capability registries, while W0C supplies source inventory. They are not yet proof that all strategy/provider entities and cross-layer relationships have been projected into one queryable temporal graph. W15/W2/W10 close those joins and runtime evidence paths.

Do not describe the current result as a fully polyglot, fully semantic, runtime-complete repository graph. Use exact coverage and evidence states.

## 2. Definition of “the entire repository is on the map”

The completion target has four distinct coverage layers. A single percentage must not hide gaps.

### 2.1 Complete Git-tree inventory — 100% path accounting

Every tracked Git path in the selected commit/tree must appear exactly once in the inventory or in an explicitly modelled submodule/LFS boundary. Each entry has:

- repository ID, commit SHA, tree SHA, path, Git object ID/mode, blob hash and byte size;
- detected language and artifact class;
- generated/vendor/binary/secret/LFS/submodule/symlink classification;
- parser/indexer version, coverage status and reason;
- source range or document anchor where available.

Required artifact classes: source code, docs/ADR/research, strategy cards/manifests, configs/feature flags, API/event schemas, lockfiles/dependency manifests, tests/fixtures/coverage, benchmarks, CLI/scripts, MCP/tools/plugins, CI/workflows, Docker/infra, generated/vendor assets and data fixtures.

No path may silently disappear. Minimum statuses: STRUCTURE_INDEXED, TEXT_INDEXED, METADATA_ONLY, PARTIAL, UNSUPPORTED, EXCLUDED_WITH_REASON, PARSE_ERROR, UNCLASSIFIED. These may map to existing schema enums, but the meaning must be explicit and versioned.

### 2.2 Structural code graph — all first-party code languages explicitly covered

First, derive the actual language inventory from the pinned Git tree; do not assume a polyglot mix or claim support based on a dependency list. Then:

1. Keep existing Python AST extraction as the native Python path.
2. Add Tree-sitter grammar adapters for each first-party source language actually found and needed in this repository. Record grammar/runtime versions and query packs.
3. Import SCIP indexes where a compatible language indexer and reproducible build/index command actually exist. SCIP is an index format, not a magic parser; absent or failed indexers remain PARTIAL/UNSUPPORTED.
4. Use LSP/compiler-backed resolution selectively for languages where the repository's build environment can resolve dependencies and produce reproducible references.
5. Add declarations, types/interfaces, methods/functions, imports, callsites, implementations/overrides, config/schema references, test definitions and build-target/dependency relationships where the selected parser proves them.
6. Preserve exact file/byte ranges, qualified names, signatures and source slices for full expansion. Do not use line numbers alone as stable identity.
7. Dynamic dispatch, reflection, DI/plugin resolution, generated bindings and runtime monkey-patching remain AMBIGUOUS/UNRESOLVED unless compiler/runtime evidence resolves them.

Stable symbol/callsite identity must include repo namespace + language + normalized path + qualified syntactic scope + declaration/signature or callsite anchor + identity/schema version. Rename and source-line-shift tests are required. Parser/resolver output must be deterministic for the same SHA and pinned versions.

### 2.3 Text/config/test/operational asset graph

Non-code artifacts are not merely file blobs. Add bounded deterministic extractors:

- Markdown/docs: headings/anchors, front matter, code references, links, ADR and strategy references.
- Configs: key paths, feature flags, environment variable names, schema refs and consumer links; never index secret values.
- Schemas/API contracts: schema IDs/versions, fields, types, units, decimals, timestamp semantics and compatibility links.
- Tests: test IDs, fixtures, assertions, coverage contexts when available, and symbol-to-test mappings. Distinguish inferred TEST_CANDIDATE from measured TESTED_BY.
- Build/dependency files: package, module, dependency, build target, feature and lockfile relations.
- CI/workflows/scripts/MCP: command/tool names, trigger conditions, referenced code/configs and declared capabilities.
- Generated/vendor/binary/large files: classify and record provenance/exclusion policy; never silently ingest as first-party source.

Documentation mentions and path/name matches can create DOC_CLAIM or PROPOSED edges only. They cannot establish actual imports, runtime execution or provider usage.

### 2.4 Web3 domain graph and operational evidence

Reuse canonical owners; project evidence into a derived typed graph. Required node families:

- Code: Repository, Commit, Blob, File, Package, Module, Symbol, Type, Interface, Callsite, BuildTarget.
- Engineering: Test, Fixture, Benchmark, Workflow, PR, Issue, Review, ADR, WorkResultReceipt.
- Strategy: StrategyIdea, StrategyFamily, StrategyVersion, StrategyConfig, StrategyDataRequirement, Experiment, NegativeResult, Qualification.
- Market: Chain, Protocol, Venue, DEX, Pool, Token/Asset, Market, FlashLender/FlashCapitalSource.
- Data: Provider, Adapter, Endpoint, Stream, DataContract, SchemaVersion, Cursor, Watermark, Observation, Dataset, NormalizationRule, DataQualityEvidence, SourceDisagreement, SourceHealthEpisode.
- Runtime/outcome: Run, Trace, Span, Event, OperationEpisode, Candidate, Decision, Quote, Simulation, Reconciliation, PaperOutcome, ShadowOutcome.

Relationships must distinguish at least:
- Code: DEFINES, IMPORTS, CALLS_STATIC, CALLS_RESOLVED, IMPLEMENTS, OVERRIDES, READS, WRITES, EMITS, TEST_CANDIDATE, TESTED_BY, CONFIGURED_BY.
- Strategy: STRATEGY_HAS_VERSION, STRATEGY_USES_SYMBOL, STRATEGY_REQUIRES_CAPABILITY, STRATEGY_REQUIRES_PROVIDER, EXTENDS_STRATEGY, RELATED_VARIANT, SUPERSEDES_STRATEGY.
- Data: PROVIDED_BY, FETCHED_THROUGH, NORMALIZED_BY, DERIVED_FROM, CONSUMED_BY, HAS_GAP, CORRECTS, RETRACTS, DISAGREES_WITH.
- Runtime/outcome: EXECUTED_BY, OBSERVED_AT, DECIDED_ON, TRIGGERED, SIMULATED_BY, RECONCILED_TO, RESULTED_IN.
- Engineering: CHANGED_BY, REVIEWED_IN, DOCUMENTED_IN, DECIDED_BY_ADR, VERIFIED_BY.

Every edge/fact carries exact source/evidence reference, repo SHA/blob or canonical owner ID, producer/parser/resolver/schema/ontology version, provenance, confidence, verification state and temporal fields where applicable. Keep REFERENCED_BY, DECLARED_CAPABILITY, CONFIGURED_FOR, STATIC_ONLY and RUNTIME_OBSERVED distinct. An adapter existing in source is not proof of provider health, use, capacity or live capability.

GitHub PR/issue/review history is a separate permission-bounded evidence feed with its own cursor and retrieval timestamp; it is not silently represented as part of a Git tree SHA. Runtime lineage only becomes available when actual producers exist (OCA-W10), and cross-store bitemporal joins require OCA-W2/OCA-W15.

## 3. Expanded read-only MCP/query contract

Keep one query backend. Do not create separate graph/search logic in CLI, MCP and export. Keep the current three tools and add bounded composite query operations:

1. **repo_overview** — resolve a requested ref (default main) once, return commit/tree SHA, graph generation, freshness, per-language/per-artifact coverage, unsupported/excluded counts, domain-store inventory and known limitations.
2. **task_context** — natural-language task → adaptive task-conditioned evidence pack across code, strategies, providers, data contracts, tests, runtime, history and governance.
3. **expand_context** — exact full source/evidence by stable refs, dimensions and same-SHA cursor.
4. **graph_query** — typed node/edge query with entity/relation filters, exact IDs, attributes, bounded 0–N hop traversal, direction and pagination.
5. **symbol_search** — exact/prefix/substring/fuzzy identifier search with language/path scope and resolution status; exact matches rank ahead of fuzzy.
6. **trace_path** — bounded evidence-backed path between symbols, strategy, provider, dataset, observation or operation IDs; return path alternatives and unresolved hops rather than inventing links.
7. **domain_catalog** — one parameterized catalogue operation for strategies/families/versions, providers/adapters, chains/protocols/DEX/venues/pools/tokens, flash lenders, schemas and capabilities.
8. **impact_query** — changed symbol/config/provider/schema → downstream callers, tests, strategies, consumers and requalification candidates. Static dependency impact must not be labelled runtime impact.
9. **history_query** — relevant commits/PRs/issues/reviews/ADRs and as-of history, with permission/cursor/freshness metadata.

All nine remain read-only, bounded and allowlisted. No shell, arbitrary subprocess, edit/delete, admin, signer/sender, borrowing/spending, deployment, provider-enable or LIVE capability. Large results must paginate/continue with deterministic cursors. Tool-call batching is allowed only within bounded limits.

### 3.1 Freshness and ergonomics

- Inputs accept either an explicit repo_sha or repo_ref; when repo_ref is used, resolve it once and return the exact SHA/tree SHA.
- A query never silently triggers an index write. If the matching index is missing or stale, return UNAVAILABLE/STALE plus a clear build/fallback instruction.
- Every response includes requested/resolved/indexed SHA, tree SHA, graph generation, schema/ontology/parser versions, freshness, coverage, included/omitted refs, provenance/verification/confidence, token count or labelled estimate, and continuation cursor.
- A new ChatGPT conversation does not inherit local disk or an MCP connection automatically. Provide a client setup file, minimal stdio config example, health-check, tools/list smoke test and an explicit “connected vs merely installed” diagnostic. Do not change user-global MCP settings or credentials.
- The local MCP server remains stdio/read-only. If a remote host is ever proposed, it requires a separate authentication, network threat-model, tenancy and secret-handling review; do not expose an unauthenticated server.

## 4. SOTA function selection — adopt capabilities, not a pile of applications

The following functions are the intended design baseline. Existing native owners remain authoritative; external tools are benchmark candidates, not mandatory installs.

| Function to implement | Reference pattern | Decision |
|---|---|---|
| Polyglot syntax + symbol extraction | Tree-sitter | Core parser adapter for detected first-party languages |
| Compiler-grade definitions/references | SCIP/LSP | Selective, only for buildable languages with reproducible indexers |
| Query-conditioned graph ranking | Aider RepoMap / personalized PageRank | Implement as ranking logic, not another graph store |
| Exact enclosing-scope extraction | grep-ast / TreeContext / Probe-style JIT | Use exact AST byte ranges; target function stays FULL |
| Structural audit rules/transforms | ast-grep | Optional rule engine for targeted audits, never the sole index |
| Fast lexical retrieval | SQLite FTS/BM25 first | Native baseline; benchmark Tantivy/Zoekt only when measured scale requires |
| Content-addressed incremental inputs | Git blob/tree hashes + signature/body split | Core; no second Merkle store without measured need |
| Early cutoff/cancellation | Salsa/Buck2 DICE/CocoIndex patterns | Implement minimal native dependency engine; benchmark alternatives only if bottleneck |
| Test/change impact | coverage contexts + dependency graph + Nx-style affected analysis | Core evidence layer; safety/invariant tests remain mandatory |
| Deep dataflow/taint | Joern/CPG, Infer | On-demand profile for security/dataflow questions, not universal indexing |
| Large-scale fact/graph backend | Glean / LadybugDB | Conditional bake-off only after SQLite/current graph query limits are measured |
| Lineage | OpenLineage facets | Reuse as compatible run/job/dataset vocabulary; canonical event/observation stores remain owners |
| Data catalogue | DataHub | Conditional future UI/catalogue; does not replace source registry or adapters |
| Schema compatibility | Apicurio model, Git schemas + CI first | Service only if multi-team schema registry need is proven |
| Event transport / CDC / durable workflow | NATS JetStream / Debezium / Temporal | Separate adoption gates; never replace AGG-02, MarketObservation or EventEnvelope |
| Token/output efficiency | actual tokenizer, loss-aware packer, RTK-style log trimming | Core measurement; logs may be compressed, critical source/evidence may not |
| Security/supply chain | gitleaks, Syft, ScanCode, cargo-deny where applicable | CI governance; audit actual licences, tool capabilities, transitive dependencies and paths |

Do not install all candidates. Do not make archived GitHub Stack Graphs, unverified MCPs, unlicensed tools or high-cost graph databases critical dependencies. Glean and LadybugDB solve different problems and are benchmarked separately only if required.

## 5. Token-efficient context rules

The goal is maximum task-relevant evidence per token, not minimum output size.

1. Store signatures/declarations separately from function bodies; hash imports, declarations, signatures, bodies and generated artefacts independently.
2. Search in this order: exact ID/symbol → exact path → lexical/FTS/BM25 → typed graph neighborhood → test/change/co-change signals → proven runtime evidence → semantic/vector fallback only after a measured recall gap.
3. Use task-conditioned PageRank/relevance ranking with strategy, provider, changed-file and risk signals. Raw call frequency alone must not dominate.
4. Return the target implementation FULL, including exact source range. Direct dependencies may be FULL or SKELETON according to decision relevance; farther neighbors may be REFERENCE/OVERVIEW with stable refs.
5. Use structural scope extraction, not arbitrary character truncation. Keep financial formulas, integer/decimal arithmetic, fees, slippage, units, rounding, time/block semantics, risk limits, IDs, contracts, assertions and negative evidence intact.
6. Use model-specific tokenizer profiles when supported by the client. Otherwise return a conservative byte estimate and label it. A number called “tokens” must not be silently estimated as bytes/4.
7. Return actual/estimated input budget, used budget, per-ref cost, included/omitted manifest and deterministic continuation. If a target body does not fit, return NEEDS_EXPANSION; never cut it mid-function.
8. Compress repeated CLI/build/test output with structured summaries only after proving error/span/assertion preservation. Do not lossy-compress source code, API payloads or financial evidence.
9. Cache only by exact SHA + graph generation + query + dimensions + depth + tokenizer + budget + schema versions. Never serve a cached pack across a branch/SHA/schema change.
10. Measure tokens saved together with recall@K, citation correctness, critical omission rate, latency and task completion. Lower token count alone is not success.

## 6. True continuous indexing and incremental computation

Separate four capabilities:

- **Inventory refresh:** discover every Git tree addition/modification/deletion/rename/submodule/LFS change.
- **Parse cache:** reuse language parse output keyed by blob + parser + grammar + config versions.
- **Graph delta:** recompute only changed signatures/declarations/imports/calls and dependent relations; propagate invalidation through dependency edges, then early-cutoff when canonical output is unchanged.
- **Publication/reconciliation:** publish immutable SHA-bound manifest/artifact to a retention-controlled location, promote only a verified generation, retain previous generations, and periodically compare a clean full rebuild against the incremental result.

Current W0B parse memoization is a good start but does not satisfy Graph delta by itself. OCA-W16 must implement the latter with cancellation, resource budgets, one-writer/atomic promotion, crash recovery, branch isolation and full-vs-incremental parity tests. CI workflow success without a retained/published index artifact is not proof that the MCP host has a current index. The local updater and MCP reader must agree on repo SHA/generation and never expose a half-written build.

## 7. Acceptance gates and work sequencing

### OCA-W0B2 — complete repository coverage / polyglot graph

Depends on W0B and uses W0A/W0C audit evidence. Deliver a language/artifact coverage matrix, polyglot parser adapters, text/config/test/workflow structural extractors, stable cross-language IDs, explicit gaps, tests and a new receipt.

Acceptance:
- 100% of tracked tree paths accounted for exactly once (including reason-coded exclusions).
- 100% of first-party code files classified by language and parser capability.
- Every first-party code language has STRUCTURE_INDEXED or an explicit UNSUPPORTED/PARTIAL decision with owner, reason and remediation; no silent fallback to “other”.
- All strategy/provider/source catalogues from W0C/W13/W14 are represented as explicit registry-backed nodes or referenced as unavailable with exact reason.
- Cross-file static edges are evidence-bearing; dynamic/unresolved links remain unresolved.
- README/docs/config/schema/workflow/test/build assets are searchable and linked to exact anchors/keys/tests where extractors can prove the relation.
- Same-SHA deterministic build, clean-vs-incremental parity, rename/delete and parser-upgrade invalidation pass.
- Golden corpus expands beyond Python-only cases to every detected first-party language and every important asset class.

### OCA-W4B — tokenizer-accurate, loss-aware retrieval

Depends on W0B2 and existing W4. Deliver actual tokenizer adapter(s), task-conditioned ranker, scope extraction, per-ref cost accounting and omission audit.

Acceptance:
- True tokenizer used when model/client profile is configured; byte estimate remains an explicitly labelled fallback.
- At least one Web3 strategy task and generic coding/security/test tasks show lower context tokens than whole-source retrieval without loss of required symbols/tests/evidence.
- Critical omission rate is zero on the required golden set; report precision/recall, token reduction, latency and citation correctness.
- Target-function source is always full or explicitly listed for expansion; no mid-body truncation.

### OCA-W11B — expanded universal MCP/query surface and client handoff

Depends on W0B2/W4/W11; domain joins expand as W15/W2/W10 become available. Implement the nine tools in section 3 over the same backend, with repo_ref auto-resolution, explicit SHA pinning, filters, pagination and health/freshness.

Acceptance:
- MCP tools/list proves only the approved read-only surface.
- Unit/integration tests prove each tool maps to the same backend and returns provenance + omissions.
- Test code, docs, config, provider, strategy, test-impact, history and path-trace queries.
- A clean environment can run the server against a populated SHA-bound index using documented stdio config; tools/list and one real task_context call pass.
- Document and verify how a supported client actually connects. “Server exists” is not “ChatGPT is connected”.
- No client-global config writes, credentials copying, network exposure or financial authority.

### Existing dependency lanes remain mandatory, not duplicated

- OCA-W13/W14: provider capability contracts and strategy data requirements.
- OCA-W15: typed temporal ontology, provenance, multi-layer joins and migrations.
- OCA-W16: true incremental graph deltas, dependency invalidation and resource governor.
- OCA-W2/W3/W10: OperationEpisode, stable callsites and actual supported paper/shadow producers.
- OCA-W7/W18: golden benchmark, symbol-to-test evidence and test economics.
- OCA-W12: license/SBOM/secrets/supply-chain governance.
- OCA-W19: conditional external systems adoption.

Execution rule: reconcile current PRs #680–#690, their actual bases/heads/diffs/checks, and correct cumulative/stacked PR relationships first. Then execute W0B2 → W4B → W11B in separate bounded worktrees/PRs. Continue dependency-ready W15/W16/W2/W10/W7/W12 only after owner and base-SHA checks. No automatic merge.

## 8. Universal completion statement

A successful build may say **INVENTORY_COMPLETE** only when every tracked path has a coverage record. It may say **STRUCTURAL_GRAPH_COMPLETE** only when every first-party source language is structurally indexed or an explicitly approved gap is recorded. It may say **DOMAIN_GRAPH_COMPLETE** only for the strategy/provider/domain dimensions actually represented with evidence. It may say **RUNTIME_LINEAGE_COMPLETE** only for supported execution paths whose real producers, recovery and replay have been tested.

Never use one unqualified “100% repository graph complete” badge to conceal a missing language parser, missing provider join or absent runtime producer.

## Operational visibility extension — strategy/function performance diagnostics (2026-11-22)

A complete source/symbol inventory is not an operational performance model. The graph may catalogue every discovered function, but only runtime producers and trace evidence can establish which functions actually ran. Keep STATIC_EXTRACTED/COMPILER_RESOLVED call edges separate from RUNTIME_OBSERVED invocations.

OCA-W20 and `STRATEGY_FUNCTION_PERFORMANCE_DIAGNOSTICS_RU.md` add a derived read-only diagnostic plane over the canonical W10/W2/W15 evidence. It connects strategy/version → operation/episode → lifecycle stage → stable callsite/symbol → inputs/outputs/contracts → provider/observation/capital → measured function/stage health → simulation/reconciliation outcome.

The diagnostic view must show actual call counts/denominators, latency quantiles, errors/retries/timeouts, queue/backpressure, data-quality/freshness/gaps and durable-capture loss, alongside separately typed financial outcomes. It compares only compatible strategy/config/provider/chain/venue/regime cohorts, exposes sample size and missing coverage, and links each anomaly to exact events and source refs.

Do not claim every function is runtime-observed just because every path is inventoried. Do not rank a function as poor from a low sample or missing telemetry. Do not label a function as the cause of negative PnL based on correlation; distinguish OBSERVED_ANOMALY, ASSOCIATED_STAGE, ROOT_CAUSE_HYPOTHESIS and controlled causal evidence.

Expose `performance_diagnostics` as the seventh typed operation inside the existing `web3_data_trace` MCP schema. No third MCP schema, duplicate event store, raw market DB, automated remediation or LIVE authority is introduced. The capability remains UNAVAILABLE/PARTIAL until W10, W2, W15 and W20 have real producer, join, replay and end-to-end test receipts.
