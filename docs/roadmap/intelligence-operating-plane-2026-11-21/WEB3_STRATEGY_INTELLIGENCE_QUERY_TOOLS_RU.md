# WEB3 STRATEGY INTELLIGENCE — DOMAIN QUERY TOOLS + TOKEN-EFFICIENT DEEP RESEARCH

**Status:** mandatory implementation addendum to PR #666.  
**Goal:** let ChatGPT/coding agents discover, understand, compare and extend *all existing Web3 strategy candidates in this repository* without repeatedly reading the entire codebase or losing critical implementation/economic evidence.  
**Primary implementation package:** OCA-W4C, using the shared repo-intel query backend and MCP transport.  
**Canonical foundations:** OCA-W0C, existing strategy registries/implementations, OCA-W13 provider contracts, OCA-W14 strategy requirements, OCA-W15 temporal graph, OCA-W2 OperationEpisode and OCA-W10 runtime capture.  
**No new A–H letters and no duplicate canonical data stores.**

## 1. What the user should be able to ask

The interface must support questions such as:

- Show every discovered strategy family, version and implementation candidate in the repository, including incomplete, fixture-only, rejected, deprecated and documentation-only ideas.
- Find every flash-loan, flash-swap, atomic arbitrage, cross-venue, routing, liquidation, lending and other existing Web3 strategy candidate; do not assume the repository contains all of these families.
- Explain one strategy from entrypoint through exact functions, callers/callees, formulas, configs, data providers, flash-capital route, tests and qualification evidence.
- Compare all variants and show shared code vs genuinely distinct mechanisms.
- Which providers, RPCs, APIs, DEXs, pools, oracles and flash lenders are referenced, configured, capability-tested, captured or actually observed for each strategy?
- Which source methods are STREAMING, POLL_ONLY, ONE_SHOT or UNAVAILABLE? Which support historical backfill/replay, cursors, freshness/gap/correction handling?
- Which strategy requirements are compatible, partial, incompatible or unknown for each provider/capital source?
- Which strategy functions are covered by tests, and where are the missing tests or negative experiments?
- What changed in the last N commits/PRs that could affect sizing, fees, slippage, route construction, provider data or qualification?
- Is a proposed new strategy a DISTINCT_CANDIDATE, RELATED_VARIANT, EXTENSION or POSSIBLE_DUPLICATE, and which evidence supports that assessment?
- Can a selected paper/shadow operation be reconstructed at its historical code/config/schema/source versions? If runtime evidence is unavailable, say so.

## 2. Complete strategy discovery — do not read only the canonical registry

The strategy catalogue must be built from the union of permission-available evidence sources, then deduplicated into stable entities:

1. Canonical strategy registries, manifests, schemas and StrategyDataRequirement records.
2. First-party source symbols, classes, factories, planners, detectors, sizing/economics functions, route builders, compilers, simulations and strategy dispatch tables.
3. Configs, capability matrices, feature flags, environment-key names (never secret values), CLI options and deployment/runtime profiles.
4. Tests, fixtures, benchmarks, property tests, simulation datasets, paper/shadow receipts and qualification campaigns.
5. Documentation, architecture records, research notes, ADRs and roadmap proposals.
6. Git history and available GitHub PRs/issues/reviews/commits, treated as a separate permission-bounded historical evidence feed.

A candidate discovered only in docs is not silently a working strategy. A class name or file path is not proof of registration or execution. Every candidate keeps discovery provenance and a lifecycle/evidence state, for example:

- CANONICAL_REGISTERED
- IMPLEMENTED
- CONFIGURED
- TESTED
- QUALIFICATION_PENDING
- PAPER_SHADOW_OBSERVED
- FIXTURE_ONLY
- DOC_ONLY
- REJECTED
- DEPRECATED / SUPERSEDED
- UNCLASSIFIED / UNKNOWN

These states are evidence dimensions, not a single simplistic maturity score; one candidate may be IMPLEMENTED and TESTED while still not qualified.

### 2.1 Versioned Strategy Card

Each discovered StrategyIdea/Family/Version gets a deterministic, evidence-linked card:

- stable strategy/family/version IDs and aliases;
- discovery sources and exact repo SHA/blob/file/symbol ranges;
- mechanism category and explicit strategy metadata (no invented semantic label);
- entrypoints, implementation symbols, static call paths and unresolved/dynamic edges;
- exact formulas/algorithm sections and economic assumptions;
- capital model: flash-loan/flash-swap/lending/own capital/unknown;
- fees, interest, repayment semantics, amount limits and evidence source;
- chain, protocol, venue, DEX, pool, token and contract/program identities;
- StrategyDataRequirement, provider capabilities and source contracts;
- config keys, feature flags and version/checksum;
- test IDs, fixtures, benchmarks, coverage evidence and failures;
- simulation, paper/shadow, reconciliation and qualification evidence;
- negative results, rejected hypotheses, blockers and missing evidence;
- lifecycle states, temporal history, supersession/variant links;
- explicit unknowns and next useful expansion refs.

Numerical thresholds and economic values must come from exact code/config/contracts/tests or authoritative qualification evidence. Never fill missing fees, decimals, slippage, capacity, freshness or profitability with plausible values.

## 3. Six domain operations exposed through two bounded read-only Web3 MCP tools

Keep the existing generic MCP interface and add only **two** domain-specialized MCP tool schemas to limit permanent tool-description/token overhead. Each schema selects a typed operation. The six operations below all call the **same** query backend and canonical owner APIs; they do not create six engines or six databases.

### 3.1 strategy_research — operation `catalog`

**Purpose:** enumerate the full discovered strategy universe compactly, with stable pagination.

Inputs: repo_ref/repo_sha, optional query/family/chain/protocol/venue/status filters, include_candidate_classes, page_size, cursor.

Returns: total discovered count, page rows with Strategy Card summaries, canonical/implementation/config/test/runtime states, provider and capital-source refs, coverage counts, UNKNOWNs, exact refs and cursor. A request for "all" must page through every row; never silently return only top-N.

### 3.2 strategy_research — operation `context`

**Purpose:** explain one or several strategies deeply while preserving exact source.

Inputs: strategy_refs, repo_sha, dimensions, depth, budget_tokens, optional max_hops.

Supported dimensions: source, entrypoints, callers, callees, formulas, economics, fees, slippage, sizing, configs, providers, data_contracts, chains, venues, pools, flash_capital, tests, fixtures, qualification, negative_results, simulation, paper_shadow, history, change_impact.

Returns: T0–T4 evidence pack with exact implementation function bodies on demand, source ranges, call paths, shared component refs, data requirements, provider/capital trace, tests, evidence, omissions and deterministic continuation.

### 3.3 strategy_research — operation `compare`

**Purpose:** compare versions/families/new proposals without duplicating existing strategies.

Inputs: strategy_refs or a proposal description, repo_sha, comparison dimensions and budget.

Returns: common vs unique symbols, algorithm/economic differences, capital requirements, data/provider capabilities, config differences, tests/outcomes and missing evidence. Include a novelty relation only as evidence-backed candidate classification: DISTINCT_CANDIDATE / RELATED_VARIANT / EXTENSION / POSSIBLE_DUPLICATE / UNKNOWN. An LLM may draft an explanation, but may not turn a proposal into a canonical verified fact.

### 3.4 web3_data_trace — operation `provider_trace`

**Purpose:** map the actual source/data path for a strategy or provider.

Inputs: strategy_refs and/or provider_refs, repo_sha, requested dimensions, budget and cursor.

Returns: provider → adapter/method/endpoint/stream → schema/DataContract → raw payload/cursor → normalization → MarketObservation/dataset → strategy consumer, with declared-vs-tested-vs-enabled-vs-captured-vs-runtime-observed states clearly separated. Include source modes, freshness/lag/coverage/gaps/rate limits/replay/reorg/correction evidence only where supported. Use existing canonical source, provider-governance, AGG-02 and MarketObservation owners.

### 3.5 web3_data_trace — operation `flash_capital_trace`

**Purpose:** explain flash-capital routes independently from ordinary market liquidity.

Inputs: strategy_refs and/or lender_refs, chain/protocol/asset filters, repo_sha, dimensions and budget.

Returns: lender/program/market identity, adapter/SDK/IDL/instruction path, supported assets and methods, fee/interest/repayment semantics, amount/capacity evidence, availability constraints, atomicity/route integration, tests, simulation and qualification references. Every field carries source and verification status. An advertised market liquidity value is not flash-borrow capacity; an adapter or SDK is not executable lender support.

### 3.6 web3_data_trace — operation `operation_trace`

**Purpose:** reconstruct an observed paper/shadow operation across the supported lifecycle.

Inputs: operation/candidate/episode/trace ID, or bounded strategy/time filter, repo_sha/data snapshot, requested stages, budget and cursor.

Returns: discovery → source observations → strategy decision/rejection → quote → capital selection → sizing/fees/slippage → route/planner/compiler → sender-free simulation → reconciliation → durable paper/shadow outcome, including event IDs, callsite IDs, source hashes, config/schema/code versions, gaps and replay state.

Until OCA-W10 real producers and OCA-W2/W15 joins exist, the tool must return UNAVAILABLE/PARTIAL with the exact missing producer/join. It must never synthesize runtime execution from static call graph edges.

## 4. Token-efficient strategy research — complete catalogue, selective source expansion

The target is maximum decision-relevant evidence per token, not smallest text at any cost.

### T0–T4 research workflow

- **T0 — repository card:** exact main SHA/tree, total path/language coverage, strategy/source/provider counts, freshness and known limitations.
- **T1 — complete compact strategy catalogue:** every discovered strategy candidate, one bounded row per entity, paginated; no implementation bodies yet.
- **T2 — family/strategy subgraph:** versions, entrypoints, relevant symbols, providers, data/capital requirements, config and test refs; deduplicated shared dependencies.
- **T3 — exact implementation:** full target functions/classes, decorators/annotations, relevant enclosing scope, direct callers/callees, configs, API contracts and tests. The target algorithm and all financial semantics remain FULL.
- **T4 — deep dossier:** history, PR/review decisions, negative experiments, runtime episodes, replay, qualification and source disagreement; retrieve only for selected strategies or explicit broad audit.

### Required optimization functions

1. **Complete inventory first:** precompute the catalogue and strategy-family map once for the pinned SHA; do not rediscover all strategies for every task.
2. **Stable IDs and deduplication:** return shared functions, configs, contracts, tests and provider evidence once, then reference them from multiple strategy cards.
3. **Signature/body split:** index signatures, imports, declarations and dependency hashes separately from bodies; exact bodies are fetched by stable ref.
4. **AST-aware extraction:** fetch exact enclosing function/class and byte ranges; do not use arbitrary line/character truncation.
5. **Task-conditioned ranking:** rank by exact strategy/provider mentions, dependency distance, changed symbols, data requirements, risk/decision relevance and proven runtime evidence. PageRank is one signal, never a substitute for evidence.
6. **Multi-resolution context:** target logic FULL; direct dependencies FULL or SKELETON based on need; more distant context REFERENCE/OVERVIEW with exact refs.
7. **Actual token accounting:** use the configured target model tokenizer when available; otherwise clearly label byte/token estimate and its uncertainty. Include per-ref cost and tool-output/schema overhead.
8. **Pack fitting and continuation:** hard budget, deduplicated evidence, include/omit manifest, stable cursor. Never cut a target function mid-body; return NEEDS_EXPANSION instead.
9. **Cache:** strategy catalogues and packs keyed by repo SHA + graph generation + source data generation + ontology/schema + query + dimensions + tokenizer + budget. Invalidate on relevant changes.
10. **Loss-aware output trimming:** RTK-style command/test-log summaries may be benchmarked, but preserve errors, spans, assertion messages, transaction IDs, numeric fields and evidence references.
11. **Optional semantic retrieval:** only if exact/lexical/typed-graph retrieval has a measured strategy-concept recall gap; embeddings/LLM labels are not required for indexing.
12. **Negative evidence preservation:** deduplicate payloads, not the existence of separate experiments/rejections; negative results can distinguish two apparently similar strategy variants.

### Non-compressible information

Never lossy-compress or omit from a requested exact analysis: integer/decimal arithmetic, units and decimals, rounding, fee/interest/repayment formulas, slippage, route ordering, amount limits, token and chain identity, program/contract IDs, block/time semantics, schema fields, risk gates, assertions, transaction/message construction, simulation results, reconciliation, negative evidence or provenance.

## 5. Strategy-specific benchmark and quality gates

Extend the existing generic 42-question corpus with a stratified Web3 set covering:

- full strategy-family/version discovery and unregistered candidates;
- flashloan/flashswap/capital source paths;
- strategy → exact function/call path → provider/data contract → tests;
- provider capability and replay/freshness questions;
- fee/interest/repayment/sizing/slippage semantics;
- duplicate/variant/extension analysis;
- config and schema change-impact;
- failed/rejected/negative experiments;
- paper/shadow runtime trace and UNKNOWN handling.

Acceptance must report separately:
- candidate discovery coverage against canonical registries, W0C inventory, source/config/test/docs/history discoveries;
- strategy card evidence completeness and stale refs;
- exact symbol/source citation precision;
- golden-query recall/precision and critical omission rate;
- token count vs full-source baseline, using the configured target tokenizer or labelled estimator;
- P50/P95 latency, cache hit rate and expansion calls;
- false runtime/provider/qualification claims (target zero);
- unresolved/unsupported/UNKNOWN counts.

A complete catalogue is not the same as complete semantic understanding. Every candidate must expose what is known, what is only a documentary or static claim, and what evidence is still missing. No token-saving target may override critical omission or correctness gates.

## 6. Boundaries and implementation order

- OCA-W0C supplies discovery inventory and initial strategy/provider trace evidence; W13 owns provider capability contracts; W14 owns StrategyDataRequirement; W15 owns typed temporal joins; W2/W10 own operation/runtime evidence. This package consumes and queries those owners; it does not duplicate them.
- OCA-W0B2 supplies complete structural indexing; W4B supplies tokenizer-aware context selection; W11B supplies the shared generic query/MCP backend.
- **OCA-W4C** adds strategy cards, dedicated Web3 query tools, strategy comparison and domain-aware pack benchmarks on the shared backend.
- operation_trace is available only to the extent W10/W2/W15 have verified producers and joins.
- Keep all tools read-only and bounded. No signer, sender, borrowing, spending, deployment, provider enablement, production mutation or LIVE authority.
- Reconcile PR #680–#690 before implementation; use one owner/worktree/PR per task. Do not duplicate overlapping open work or misrepresent stacked PR ancestry.
