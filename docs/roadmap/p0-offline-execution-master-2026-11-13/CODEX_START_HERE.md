# P0 Master Handoff — Offline-First Execution Plan

**Repository:** `BobIvans/studious-pancake`  
**Created:** 2026-11-13  
**Base expected at this handoff:** `main` at merge #591 (`f2339abd035c46f23aeea13a77b0885b606914e9`). This is historical; fetch and record the latest SHA before work.  
**Purpose:** one durable entry point for Codex or another coding agent to execute the remaining P0 work without depending on chat history or ad-hoc internet browsing.


## User-clarified primary P0 scope — three independent work packages

The immediate P0 target is the three market-data tasks listed below. Each has a standalone Codex prompt and a provider-technical dossier; do not combine them into one oversized coding session:

1. **P0-1 — Safe Solana indexed intake → Dynamic Universe:** [task](tasks/P0-1_SOLANA_INTAKE_DYNAMIC_UNIVERSE.md), [offline source discovery notes](../../integrations/offline/solana-p0/SOLANA_DISCOVERY_SOURCES.md).
2. **P0-2 — Jupiter V2 + 0x comparable quote capture:** [task](tasks/P0-2_JUPITER_0X_QUOTES.md), [Jupiter OpenAPI + V2 notes](../../integrations/offline/solana-p0/JUPITER_SWAP_V2.md), [0x contract extract](../../integrations/offline/solana-p0/ZEROX_SOLANA_SWAP.md).
3. **P0-3 — Raydium/Orca/Meteora direct-state verification:** [task](tasks/P0-3_DIRECT_STATE_VERIFICATION.md), [venue decoder reference](../../integrations/offline/solana-p0/DIRECT_STATE_RAYDIUM_ORCA_METEORA.md).

Common offline technical baseline: [pinned Raydium/Meteora source snapshots](../../integrations/offline/solana-p0/vendor-reference/README.md), [source blob manifest](../../integrations/offline/solana-p0/VENDOR_SOURCE_MANIFEST.json), [Solana P0 dossier index](../../integrations/offline/solana-p0/README.md), [source manifest](../../integrations/offline/solana-p0/SOURCE_MANIFEST.json), [Solana RPC account-state reference](../../integrations/offline/solana-p0/SOLANA_RPC_STATE.md), [offline verifier](../../integrations/offline/solana-p0/verify_offline_bundle.py).

**Important scope boundary:** the separate R-02/R-03 flash-capital readers and unsigned builders remain a distinct capital workstream. R-01 is complete (#584); the broad 27-provider offline dossier is now in main through #591, and the focused R-02 SDK source kit is in main through #586. The old draft #583 is closed/superseded. Market-data P0 completion alone does not qualify a flashloan route or capital provider. Use `docs/roadmap/agent-execution-master-2026-11-13/CODEX_START_HERE.md` as the current cross-project handoff.

Next-phase prompts are collected in [P1/P2 after P0](tasks/P1_P2_AFTER_P0.md). Do not begin them until the three P0 exit gates have evidence.

## 0. Start here — rules for the agent

1. Read this file completely, then read every linked in-repository owner listed in §2 before editing code.
2. Fetch current `main`; record exact base SHA and working-tree status. Never assume the base SHA above is still current.
3. R-01 is complete (#584); #586 is merged, and #583 is closed/superseded by #591. Read the merged offline dossiers in main; do not treat these PRs as open work. Inspect only genuinely open newer PRs for unique changes. Never re-merge old GPR/QPR branches.
4. Build a machine-readable P0 inventory with one row per deliverable: owner, status, exact files/tests, external source contract, credentials, docs-pin status, evidence path, blocker, dependency and acceptance command. Use only these states: `IN_MAIN_VERIFIED`, `IMPLEMENTED_UNQUALIFIED`, `OPEN_PR_NOT_IN_MAIN`, `IMPLEMENTED_UNBOUND`, `FIXTURE_ONLY`, `STUB`, `PLANNED`, `BLOCKED`, `RETIRED`.
5. **Do not restart completed work.** Reuse canonical owners and their contracts. If two owners conflict, stop and write a reconciliation note; do not silently create a third owner.
6. Preserve all current source governance, admission, quota/backoff, provider identity, evidence journal, replay, QPR gates, identity fail-closed rules and runtime capability gates.
7. No private keys, seed phrases, wallet signing, transaction submission, flash borrowing, account creation, funds spending, live execution or production promotion. No environment flag may bypass a gate. All external transaction instructions/build payloads are inert evidence only.
8. Do not claim an integration is complete because a class, endpoint URL, fixture, HTTP 200 or API key exists. Distinguish implementation, authenticated real capture, replayable evidence, exact state verification and qualification.
9. No merge without explicit human approval. Produce reviewable PRs with links and exact SHAs.

## 1. Offline-first documentation policy (mandatory)

The objective is that **implementation, code review, unit/integration tests, replay and architectural decisions can run offline** after the source dossier has been prepared. An offline coding agent must not guess external contracts.

### 1.1 Documentation dossier for every P0 external dependency

For each API, RPC, SDK, program, IDL, package, decoder or protocol contract, create a versioned dossier under:

`docs/integrations/offline/<provider>/<version-or-retrieval-date>/`

Each dossier must contain, where applicable:

- `README.md`: what the provider does in this P0, owner module, exact scope and known limitations.
- `SOURCE_MANIFEST.json`: canonical official URL, page/title, retrieval timestamp UTC, provider/API version, package name/version, git commit/tag, content SHA-256, license, retrieval method and whether the snapshot is complete.
- `*.md` or `*.html`: locally retained official documentation, not merely a link or a model-written summary.
- `openapi.json`, GraphQL schema/query, IDL, protobuf, SDK type declarations or ABI: exact machine-readable contract when published.
- `fixtures/positive`, `fixtures/negative`, `fixtures/schema-drift`: redacted, minimal response samples with provenance. Never store credentials, private data or unredacted wallet-specific responses.
- `DECISIONS.md`: request construction, auth headers, rate limits, pagination, amount units, decimals, fees, freshness, error semantics, retry policy, chain/program identity and unresolved questions.
- `VERIFY.md`: offline commands that verify hashes, schemas and fixtures.

Pin package artifacts or source commits where licensing permits. Record transitive SDK versions and runtime constraints. A docs URL alone is NOT an offline dossier. A SHA of a locally generated summary is NOT a source pin.

### 1.2 Two execution modes — do not confuse them

**OFFLINE_BUILD mode:** no network calls. The agent uses only checked-in dossiers, pinned SDK source/artifacts, fixtures and repository code. It can implement adapters, decoders, normalization, tests, replay and reports. If the official contract is absent or incomplete, mark that item `BLOCKED_MISSING_PIN`; do not infer field names, account layouts, fee semantics or endpoint behavior.

**BOUNDED_LIVE_CAPTURE mode:** network access is intentionally required to call the provider/RPC with the user's locally configured credentials and bounded quotas. It is not possible to prove a real live API connection, current pool state, current lending capacity or a live quote while fully offline. Live capture must be a separate explicit command, have a request budget and preserve raw response hashes, timestamps, source generation and negative results. Never let live capture trigger signing, sending, borrowing or account creation.

Before coding, audit all existing documentation pins. If they are missing/stale, prepare a **documentation acquisition manifest** listing exact URLs, packages and versions needed. If the agent environment has no network, stop and report the manifest for a one-time online retrieval step. Once retrieved and committed, resume offline. Never pretend this acquisition occurred.

### 1.3 Offline reproducibility gates

- Tests must run with sockets disabled except separately marked manual/live tests.
- Every adapter must have deterministic fixture replay and negative/error fixtures.
- Verify each source dossier SHA-256 before use.
- No test may silently fall back from live failure to fixture success.
- Every evidence record identifies `LIVE_CAPTURE`, `FIXTURE`, `REPLAY` or `SYNTHETIC_TEST`.
- No fixture can qualify a live source or an executable market edge.
- A docs/SDK version change creates a new immutable dossier generation; never overwrite historical pins.

## 2. Canonical context to read before execution

Read these files from current `main` completely, not from an old branch:

1. `README.md` — current product/runtime truth and quarantine boundary.
2. `AGENTS.md` if present; `pyproject.toml`, dependency locks, `config/capabilities.json`.
3. `docs/roadmap/dynamic-universe-master-2026-10-07/CODEX_START_HERE.md`.
4. `docs/roadmap/dynamic-universe-master-2026-10-07/IMPLEMENTATION_REPORT.md`.
5. `docs/roadmap/gpr-parallel-radar-rnd-2026-10-06/CODEX_START_HERE.md` and its source matrix, acceptance tests, architecture contract and master context.
6. `docs/roadmap/prequal-rnd-2026-10-06/CODEX_START_HERE.md`, `package/18_CODEX_START_HERE.md`, `package/01_MASTER_CONTEXT_RU.md`, source plugin architecture, PR sequence and acceptance gates.
7. `docs/verification/r02-2026-10-08/README.md`, `CAPTURE.json`, `RECEIPT.json`, `offline/` bundle and its verifier.
8. `config/qualification/din00-source-status.json`, `src/resources/market_source_catalog.json`, current source governance and evidence/replay owners.
9. Existing QPR/GPR implementation owners and tests; read the merged broad provider dossier and focused R-02 SDK pack directly from main.
10. Current `src/solana_parallel_radar/`, `src/discovery/dynamic_universe/`, `src/assets/resolution/`, `src/research_economic_graph/`, `src/economics/flash_capital_graph/`, `src/qualification_campaign/`, paper/shadow composition root and exact simulation owners.

Do not assume the README's older or newer statements are automatically consistent with a research report. Reconcile them against code, tests, package boundary and current commit. Record discrepancies.

## 3. P0 work breakdown and dependency order

**Parallel execution update (2026-11-13):** P0-1, P0-2 and P0-3 are independent work packages and may be researched/implemented concurrently in separate worktrees after the coordinator freezes their shared identity/evidence interfaces. Their integration and final market-data exit gate remain joint. Do not serialize unrelated P0 lanes just because the earlier draft described a sequential PR order.

This is a dependency graph, not permission to mark every item complete. First verify what is already in current `main`.

### P0-0 — Baseline and branch/PR reconciliation

- Verify current `main` SHA, clean state, CI and package/runtime capability matrix.
- Verify the #591 master handoff, the merged #586 SDK pack, #588/#589 market-data dossiers and current open PRs. Do not re-import #583/#586 content or merge legacy branches.
- Treat #583 as closed/superseded and #586 as merged. Their useful documentation is in main; verify exact file paths and hashes.
- Produce `P0_BASELINE.json` and a concise reconciliation report.
- Do not cherry-pick or merge without a conflict analysis and reviewable PR.

Acceptance: a reproducible inventory, exact main SHA, exact PR heads, explicit no-duplicate plan and no weakened gates.

### P0-1 — Solana + Sui safe market intake and Dynamic Universe handoff

- Reuse existing AssetIdentity/Representation Registry, RESOLVE_LIVE, Dynamic Universe, source governance, bounded collectors, journal, ResearchEconomicGraph, relation generators, VerificationQueue and replay.
- Finish the safe indexed intake handoff: discover candidates from approved sources; canonicalize full mint/coin type, token program/Move type and decimals; preserve provenance and lifecycle; detect duplicates, aliases and shared underlying liquidity; reject ticker-only identity.
- Solana sources to reconcile: DEX Screener, Raydium, Meteora, Manifest, Sanctum and GeckoTerminal where its contract is pinned. Treat indexed pool lists as discovery only.
- Sui sources to reconcile: DeepBook, Cetus, Scallop, Aftermath and Sui GraphQL/gRPC/Core. Fix only against pinned current schemas; retain checkpoint/object/package provenance.
- Implement bounded scheduling, pagination, backoff, quotas, freshness and complete-snapshot retirement semantics. Never retire pools from partial/truncated/failed responses.
- Hand off only identity-verified candidates into the research graph. Do not write executable edges from indexed discovery.
- Target a configurable rolling universe (initial research target 120–160 hot pairs only if measured source coverage and budgets support it); do not fabricate coverage or force a fixed pair count.

Acceptance: real bounded capture receipts per source where credentials/network allow; deterministic offline replay; identity and lifecycle tests; no ticker-only binding; explicit source coverage and blockers. The existing Dynamic Universe report says first diagnostics captured 245 Sanctum assets, 21 DeepBook coins and 24 DeepBook markets, but Jupiter/RPC/STON were denied by that environment and the subsystem was not wired into the supported application boot path. Re-verify before relying on those historical counts.

### P0-2 — Real comparable Jupiter + 0x Solana quote capture

- Inspect `src/solana_parallel_radar/probes.py`, `cli.py`, existing provider profiles and the current quote normalizer. Do not assume legacy `src/ingest/*` adapters are supported runtime owners; README places legacy ingest in quarantine.
- Verify current official Jupiter Swap API V2 contract and 0x Solana Swap API contract against locally pinned official docs and schemas. The prior audit found a legacy Jupiter `/swap/v1/quote` probe; verify whether it still exists in current main and migrate only the governed owner to the pinned current contract.
- Keep credential names consistent with actual code/config. Previously identified names: `JUPITER_API_KEY`, `ZEROX_API_KEY`. Verify before changing.
- Use a configured public Solana taker address only where required. Never request or store a private key or seed phrase.
- Capture comparable quotes for the same canonical mint pair, exact input base-unit amount, taker and time window. Resolve decimals from verified identity; never assume an arbitrary amount is 1 token. Record output/minimum output, route/provider metadata, fees where documented, slot/context where available, timestamp, response hash and request parameters with secrets redacted.
- Returned instructions/build payloads are inert evidence. Do not compile, sign or send them in this P0.
- Preserve rate limits, no-route and negative results, 401/403, 429, timeouts, malformed/schema-drift payloads and provider disagreement.
- Add deterministic replay. A successful HTTP status alone is not a qualified quote.

Acceptance: two real provider captures (when keys and network are supplied), same-pair/same-size comparison, secret-redacted evidence, offline replay and explicit unsupported-route/error tests. Keep the live capture command separately opt-in and bounded.

### P0-3 — Exact direct pool-state verification

- Audit existing Raydium CPMM decoder and determine exact supported account/program versions.
- Scope Orca Whirlpools, Meteora DLMM and Raydium CLMM only when official IDL/SDK/account layouts and math are pinned.
- Verify owner/program IDs, mint/vault relationships, decimals, reserves/ticks/bins, fees, slot coherence and shared-liquidity aliases.
- Sui exact pool/object state requires checkpoint and package/version binding; indexed discovery is not exact state.
- No decoder may claim support for an unknown program version or infer layout from a ticker/pool label.

Acceptance: offline fixture decoding and negative fixtures for wrong owner, version, mint, truncation and stale slot/checkpoint; live RPC capture is a separate bounded qualification.

### Separate capital workstream — R-01 complete; R-02 live capital readers remain BLOCKED (not one of the three market-data P0 tasks above)

- Do not rerun R-01. Read the current master at `docs/roadmap/agent-execution-master-2026-11-13/` plus the merged R-02 source dossier and #586 SDK pack.
- R-02 target readers: Project 0, Jupiter Lend, Kamino, NAVI. #585 remains the actual negative receipt: zero qualified capital edges; Jupiter admin/Kamino program observations and a Sui checkpoint did not establish reserve/pool capacity; 27 catalog candidates remain disabled.
- Do not invent account layouts. Pin exact SDK/package versions, IDLs/decoders, program/deployment IDs, reserve/pool resource bindings, mint/decimal bindings, authority/owner checks and independent rooted source requirements.
- For Project 0, only inspect already-existing public account and authority addresses supplied by the user or authoritative public registry. No account initialization or wallet-specific transaction.
- Derive capacity, borrow limits, fee, reserve liquidity, freshness, oracle state, account/ATA setup costs and upfront cost only from authoritative evidence. Unknown means UNKNOWN, never zero.
- Keep all 27 research candidates disabled unless separately qualified and explicitly authorized. No live capital activation.

Acceptance: four readers only count as qualified if each has pinned decoder + real rooted state evidence + replay + independent consistency checks + explicit capacity/fee/cost semantics. A program account existing or an admin fee field alone is not reserve capacity.

### Separate capital workstream — Protocol-specific builders (R-03) and capital-aware paper path

- R-03 shared contract-only and SDK-conformant unsigned builders may proceed offline while R-02 is blocked, as specified in the merged #586 handoff. Live-capital-backed promotion and exact route qualification remain blocked until the matching R-02 provider proof passes.
- Reuse existing QuoteProvider, TransactionBuilder, UnsignedExecutionPlan, ProviderCorrelation, BuildEvidence, RentSponsorPlanner contracts where present; audit current main before creating any new contract.
- Validate borrow/repay pairing, atomicity, account metas, versioned transaction constraints, rent/setup costs and provider-specific fees.
- Keep signer and sender absent/unreachable. Builders must produce unsigned plans only.
- Connect qualified quote + exact market state + observed capital + PR118 amount grids/cost ledger + canonical simulation/reconciliation owners. Do not invent synthetic fills.
- A route is paper-qualified only after exact-size quote, coherent state, all costs, sender-free simulation and durable replayable receipt.

Acceptance: end-to-end sender-free paper evidence for a supported route, or explicit blocker receipt. No live promotion.

### P0 market-data exit gate — the three user-clarified P0 tasks

P0 market-data is complete only when:
1. P0-1 has a durable, refreshable Solana candidate pool universe and verified identity handoff with provenance and lifecycle semantics.
2. P0-2 has real, comparable Jupiter V2 and 0x quotes for the same mint pair, base-unit input size and time window, with retained raw evidence and deterministic replay.
3. P0-3 has exact-state readers for each venue/version claimed as supported, using pool + dependent tick/bin accounts and amount-specific venue math.
4. All offline tests/replays, CI, capability and quarantine gates pass.
5. Any unavailable source or unlicensed venue remains explicitly BLOCKED/unsupported, never false PASS.
6. No signer/sender/live transaction, flash borrowing or production promotion has been enabled.

The separate capital workstream (R-01/R-02/R-03) remains required before a route can be claimed as flashloan-qualified; its status is not made green by these market-data deliverables.

A blocked provider does not necessarily block all research progress, but it must remain excluded from any route whose correctness depends on it.

## 4. Official source dossier acquisition list

This is a checklist, not a claim that the files have already been downloaded. Codex must resolve the exact currently supported endpoint/version and record it in each dossier.

### Solana discovery / pool state
- Read the checked-in P0 dossiers first: `docs/integrations/offline/solana-p0/README.md`, `SOURCE_MANIFEST.json`, `SOLANA_DISCOVERY_SOURCES.md` and `SOLANA_RPC_STATE.md`.
- Current discovery references include DEX Screener, Raydium API V3, Meteora DLMM Data API, GeckoTerminal V2, Manifest and Sanctum; the dossier distinguishes raw mirror, source pin and extract-only status.
- Solana RPC JSON-RPC official method reference and account response schema.
- Raydium official API documentation, program/IDL/SDK source and CPMM/CLMM account layouts.
- Meteora DLMM official SDK/IDL and bin/fee/account layout documentation.
- Orca Whirlpools official SDK/IDL and tick-array/pool account layout documentation.
- DEX Screener API reference and rate-limit policy.
- GeckoTerminal API reference and rate-limit policy.
- Sanctum LST registry/API schema and on-chain mint verification contract.
- Manifest official API/SDK/program docs where used.

### Sui discovery / exact state
- Sui official gRPC, GraphQL and Core API schemas, checkpoint/finality semantics.
- DeepBook V3 official SDK, package version, pool/level-2 schema and fee semantics.
- Cetus official SDK/CLMM contracts and pool/object schemas.
- Aftermath router/API/SDK exact version and quote response contract.
- Scallop docs/SDK only for the specific rate or lending observations actually used; do not confuse lending data with swap quotes.

### Quotes
- Jupiter Swap API V2 OpenAPI 3.0.3 is mirrored in `docs/integrations/offline/solana-p0/JUPITER_SWAP_V2.openapi.yaml`; read `JUPITER_SWAP_V2.md`.
- 0x Solana Swap API request/response contract extract is checked in at `ZEROX_SOLANA_SWAP.md`; exact current docs page is pinned by URL and retrieval date in `SOURCE_MANIFEST.json`.

### Flash capital / builders
- Project 0 official SDK/package, source commit, IDL/program deployment and account layout.
- Jupiter Lend official SDK/IDL/program and reserve/cap/fee layout.
- Kamino official SDK package and exact version, lending market/reserve layouts and deployed program provenance.
- NAVI official modular SDK/package and exact version, pool/resource and decimal semantics.
- Solana/Sui transaction construction and simulation official SDK docs needed by unsigned builders.

Do not bundle every vendor's entire website. Capture only the authoritative pages, schemas, SDK source/artifacts and versioned dependencies required by the implemented path. Include licensing notices. If an official source cannot be captured, record the exact blocker and stop that adapter.

## 5. Agent execution strategy and deliverables

Do not attempt to hold the whole repository in one prompt. Use the whole-project multi-agent orchestration docs at docs/roadmap/agent-execution-master-2026-11-13/. The P0 work is one track in that project-wide parallel plan. Use durable handoffs:

- `P0_BASELINE.json` — current SHA, open PR heads, inventory, test commands.
- `P0_DOCS_MANIFEST.json` — provider docs and SDK pin completeness.
- `P0_IMPLEMENTATION_PLAN.md` — dependency graph and bounded PR sequence.
- One PR per coherent vertical (P0-1 intake, P0-2 quotes, P0-3 direct state, P0-4 capital readers, P0-5 builders/paper integration). Split further if reviewable scope requires it.
- Each PR updates its `REPORT.md`, machine-readable status receipt and next-agent handoff.
- At every stop, record exact changed files, tests run, tests not run, evidence hashes, live requests attempted, blockers, next task and exact next command.
- Keep prompts short: tell the agent to read this file and the active stage file. The repository is the persistent memory.

Parallelize all independent project work immediately: P0-1/2/3; R02-CAP-A/B/C/D; R03-00 offline contract work; strategy/graph research; Sui/TON/EVM source research; CEX/oracle feed dossiers; platform/CI and runtime composition audits. Use separate worktrees, one task owner per PR and a shared interface freeze where necessary. R-01 is already complete (#584); do not redo it. R-02 reader implementations are independent; R-03 unsigned contract/build work may proceed offline, while live-capital association waits for the corresponding R-02 proof. R04/R05/R06 and provider promotion remain dependency-gated. The whole-project launch matrix is authoritative in MULTI_AGENT_EXECUTION_PLAN.md.

## 6. Human inputs and secret handling

The human operator may need to create provider developer accounts and locally supply API keys, RPC URLs or public taker/account addresses. The agent must:
- list exact variable names, provider, purpose, whether required, free-tier/quota and a local validation command;
- never ask the user to paste a secret into chat, issue, PR or source file;
- never print credentials or auth headers;
- distinguish public address from private key;
- not assume a free tier is permanent or that a key is enabled for every endpoint;
- not create accounts, pay fees, initialize token accounts or spend funds.

The user already has a local Windows 11 + PowerShell + CPython 3.13 environment and a project `.venv`. Test commands in the runbook must work on Windows or explicitly document WSL/Linux-only requirements. Do not claim platform support merely because package installation succeeded.

## 7. Final status format

Every stage report must use:

| Field | Required content |
|---|---|
| Status | one of the explicit states in §0 |
| Main SHA | exact SHA |
| PR | URL, head SHA, base SHA, merged/open |
| Docs | dossier paths, source versions, SHA-256, missing pins |
| Credentials | variable names only; never values |
| Real capture | request count, provider, timestamp, outcome, evidence path |
| Replay | exact offline command and result |
| Tests | exact commands, pass/fail/skipped |
| Safety | signer/sender/live flags and proof they remain disabled |
| Blockers | exact missing inputs and owner |
| Next | one bounded task and copy-ready command |

Never describe a stage as “done” without evidence. Never equate a large token context window with repository understanding, verified docs, successful tool execution or unlimited agent usage.
