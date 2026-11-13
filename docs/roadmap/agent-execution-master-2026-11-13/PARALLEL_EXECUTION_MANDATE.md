# Parallel Master Execution Mandate — Studious Pancake

**Updated:** 2026-11-13  
**Repository:** `BobIvans/studious-pancake`  
**Audited main SHA:** `176f41378645f6f3b3fd95a59617633b5808acb4`  
**Purpose:** Give Codex CLI / GLM-5.3-Flash one broad project mission with parallel, isolated workstreams, while preserving the repository's existing technical knowledge, owners, evidence boundaries and merge gates.

> This document is an orchestration layer for the existing master handoff. It does not replace `AGENTS.md`, the P0 master, R-02/R-03 dossiers, GPR implementation reports, or provider-specific source pins.

---

## 1. Copy-ready master mission

Use this as the top-level instruction for a coding agent with a large aggregate token budget and parallel subagents/worktrees.

### Mission

Build and qualify the complete Studious Pancake research-to-paper system across Solana, Sui and TON, with an expandable EVM research lane. Maximize the **research universe and evidence coverage**, not the number of hardcoded pairs. Reuse and integrate what is already implemented. Complete the missing data, quote, state, capital, unsigned-builder, simulation, correlation, and paper-qualification work through bounded, reviewable PRs.

The agent is the **coordinator of parallel workstreams**, not a single-threaded implementer and not a permissionless merger. Run independent research, source-dossier acquisition, fixture creation, and non-overlapping code tasks concurrently using isolated worktrees/branches. Freeze shared contracts before parallel adapter implementation. Integrate only through reviewed PRs with exact base/head SHAs and test/evidence receipts.

### First action — repository intelligence, not coding

1. Fetch current `origin/main`; record exact SHA, worktree state, recent merged PRs, open PRs, CI and capability flags.
2. Read, in full and in this order:
   - root `AGENTS.md` and `CODEX_START_HERE.md`;
   - `docs/roadmap/agent-execution-master-2026-11-13/CODEX_START_HERE.md`;
   - `TASK_INDEX.md`;
   - this `PARALLEL_EXECUTION_MANDATE.md`;
   - P0 master handoff and P0-1/P0-2/P0-3 task texts;
   - R-02/R-03 master, acceptance matrix and offline SDK dossier;
   - GPR-01, GPR-02 and GPR-03 implementation/handoff/problem reports;
   - Dynamic Universe master and implementation report;
   - offline provider/source dossiers, manifests, license notes and verifiers.
3. Run the existing offline verifiers before using mirrored SDK/source references. Record actual commands and outcomes.
4. Build a machine-readable owner/status/dependency map. For every capability distinguish:
   - `IN_MAIN_VERIFIED`
   - `IMPLEMENTED_UNQUALIFIED`
   - `IMPLEMENTED_UNBOUND`
   - `OPEN_PR_NOT_IN_MAIN`
   - `FIXTURE_ONLY`
   - `STUB`
   - `PLANNED`
   - `BLOCKED`
   - `RETIRED`
5. Audit the latest code, not just the roadmap. Confirm each function, source adapter, decoder, builder and test really exists and is imported by the supported composition root before marking it integrated.
6. Produce a short `CURRENT_STATE.json` and owner matrix with exact paths, status, tests, source pins, real-capture evidence, blockers, dependency and responsible workstream. Do not start by recreating GPR-01.

### Parallel execution instruction

After the shared-owner audit, start as many independent workstreams as the environment can safely support:

- run source/documentation research, schema acquisition and fixture preparation in parallel;
- run independent code work in isolated worktrees/branches;
- never let two agents edit the same canonical owner at the same time;
- create one reviewable PR per coherent vertical or provider;
- expose a dependency/merge queue to the coordinator;
- rebase each child on the latest reviewed integration base before final integration;
- if a shared contract is missing, one owner implements/freezes it first; provider adapters then fan out in parallel;
- don't wait for one independent source family to finish before researching another.

“Do the whole strategy” means **all workstreams are active and progressing concurrently**, not one giant branch, one shared dirty worktree, skipped tests, or unreviewed merges. The coordinator must continuously resolve conflicts, keep evidence immutable and maintain a single source of truth.

---

## 2. Current verified repository baseline — do not duplicate these owners

This section records what was found in current `main` at the audited SHA. It is an initial baseline, not a substitute for rechecking the current checkout when execution begins.

| Area | Existing main owners / evidence | Correct next action |
|---|---|---|
| Coding-agent knowledge base | Root `AGENTS.md`, root `CODEX_START_HERE.md`, `docs/roadmap/agent-execution-master-2026-11-13/`, P0 master, R-02/R-03 dossiers | Extend these owners; do not create a second master architecture or duplicate task index |
| Asset / representation resolution | `src/assets/resolution/{resolver,chain_readers,evidence}.py`; GPR registry in `src/research_economic_graph/registry.py` | Audit integration and missing exact bindings; do not create another mint registry |
| GPR-01 research graph | `src/research_economic_graph/`: registry, models, graph, queue, verification, transformations; `GPR-01_IMPLEMENTATION.md` | Treat GPR-01 as published. Fix only demonstrated regressions or missing integrations |
| Solana radar / quote funnel | `src/solana_parallel_radar/`: radar, probes, funnel, structural, Token-2022, qualification, CLI, portable replay | Do not rewrite the GPR-02 owner. Reconcile Jupiter V2 migration and missing authenticated provider evidence |
| Sui shadow qualification | `src/gpr_sui_shadow/`: intake, campaign, BCS, source and verification owners; GPR-03 handoff/report | Remediate measured Sui blockers; do not create a second Sui data plane |
| Dynamic Universe | `src/discovery/dynamic_universe/`: universe, ingestors, campaign, promotion, TON radar | Integrate missing boot/polling/source paths using existing owners; verify source schemas and current capture |
| Relation generation / multihop | `src/strategy/relation_generators/`, `src/strategy/{market_graph_ingest,multihop_solver,arbitrage_graph}.py`, existing RouteGraph/PR118 owners | Extend and connect. Never create a second graph or solver |
| Correlation / retrospective data | Dynamic Universe implementation report, `src/market_data_evolution/`, `src/market/streams.py`, existing persistence/replay owners | Verify the actual current owner, application wiring, storage lifecycle and measurement coverage before adding anything |
| Flash capital | `src/economics/flash_capital_graph/graph.py`; `src/lending/{financing,jupiter_lend,kamino,slumlord}.py` and conformance owners | R-02 is still blocked at live capacity. Complete the real per-provider readers through the existing graph |
| Unsigned financing contracts | `src/lending/financing.py`, R-03 SDK dossier and `R03_SHADOW_BUILDERS.md` | Verify actual provider builder coverage; implement missing unsigned builders only |
| Slumlord | `src/lending/slumlord.py` already has pinned sender-free Borrow/Repay/CheckRepaid instruction construction and order validation | Reuse it. Implement missing RentSponsorPlanner integration; don't duplicate Slumlord adapter |
| TON | `src/discovery/dynamic_universe/ton_radar.py` already has bounded STON assets/pools/stats ingestion and optional injected Omniston enrichment | Verify current live schema and proxy access; add missing route/direct/state sources; keep research-only/async semantics |
| Offline docs / pins | PR #588 P0 knowledge base, #589 Raydium/Meteora reference snapshots, #586 focused R-02 SDK pack, #591 agent handoff, #592 crosslinks are merged | Verify hashes with existing no-network verifiers; acquire only genuinely missing current official contracts |

### Published campaign evidence and limitations

**GPR-01:** published implementation, 92 research identities, 14 initial campaign families, 9 DeepBook identifier refs and 4 transport transformations. Its reported publication verification was 226 offline tests plus type/format/lint checks. Do not re-run the whole GPR-01 project unless a regression is demonstrated.

**GPR-02 Solana:** implementation/handoff and three bounded public discovery campaign slices exist. The retained recent slice recorded 63 observations across 62 unique pools and coverage of all nine priority pairs. Three same-bank LST structural references were collected. However:
- zero authenticated 0x/Jupiter quotes were captured because required provider credentials/public 0x taker were not bound;
- no complete startup HARD_BOUND receipts or independent RPC quorum were produced;
- USDG/PYUSD Token-2022 extension semantics remain blocked from exact pool qualification;
- BNSOL had a same-epoch mint/pool supply mismatch;
- current JLP NAV was not proven;
- no quote disagreement, residual recurrence or profit was established.
The reported independent suite was 306 offline tests. The handoff and problem JSON are authoritative for details.

**GPR-03 Sui:** implementation/handoff exists and its independent suite reported 355 offline tests. The final retained diagnostic reported 46 index candidates / 33 relations, 99 lending/share references and 3 DeepBook book references. However:
- Sui GraphQL had a deployed Content-Length rejection;
- Aftermath responses exceeded the bounded profile;
- independent non-smoke checkpoint providers were not bound;
- reviewed Move identity/decimal/representation/depth/fee decoder contracts remained incomplete;
- no checkpoint object-state reads or complete HARD_BOUND receipts were produced;
- no verified anomaly or profit was established.
Sui remains read-only/shadow. Consult `GPR-03_IMPLEMENTATION.md` and `GPR-03_PROBLEMS.md`.

**Dynamic Universe:** the report says AssetResolver, dynamic Sanctum/DeepBook intake, relation generators, heat scheduling, Parquet residual/correlation storage, FlashCapitalGraph interfaces and TON-RADAR-01 were implemented as libraries/diagnostics. It also records that:
- the new subsystem was not wired into the supported application boot path;
- an earlier live diagnostic observed 245 Sanctum assets, 21 DeepBook coins and 24 markets, but Jupiter, Solana RPC and STON requests were proxy-denied;
- TON live schema could not be confirmed in that environment;
- lender SDK bridges/provider state were not configured.
Re-verify. Historical source counts are not current market coverage or proof of executable state.

**R-02/R-03 capital:** #584 R-01 is complete. #585 is the negative evidence receipt for R-02: zero qualified capital edges; partial Jupiter/Kamino/Sui reads did not prove capacity; 27 candidates remain disabled. #586 provides pinned offline SDK/layout references and an unsigned R-03 handoff; it is not a live reader or complete builder implementation. Current R-02 acceptance and #585 receipt govern.

**PR reconciliation:** #588, #589, #591 and #592 are merged. The old PR #590 P0 baseline branch was based on a historical main and has diverged behind current main; do **not** merge it as-is. Recreate/update its baseline only if the current main audit still needs that artifact. Do not remerge legacy GPR/QPR branches.

---

## 3. Canonical architecture — one system, several data/execution domains

Keep these planes separate but connected by immutable evidence:

```text
provider registries / DEXs / orderbooks / oracles / CEX references
                         ↓
                bounded data intake
                         ↓
               AssetIdentity / Resolver
                         ↓
                 Dynamic Universe
                         ↓
      ResearchEconomicGraph + relation generators
                         ↓
       residuals / correlation / lead-lag / heat
                         ↓
             bounded VerificationQueue
                         ↓
             exact chain-state verification
                         ↓
      quote race + unsigned transaction/PTB builders
                         ↓
                 FlashCapitalGraph
                         ↓
          PR118 amount grid + all-cost selector
                         ↓
            complete exact simulation/reconcile
                         ↓
             gated replayable PAPER campaign
                         ↓
            separate future authority review
```

Required invariants:

1. Economic asset is not the same as a chain representation. Native, wrapped, bridged, issuer-specific and yield-bearing versions remain distinct.
2. A discovered pool, API price, router quote or matching ticker is not executable truth.
3. `heat`, `execution_class` and `evidence_state` are separate; HOT never means executable.
4. Cross-chain CCTP/Wormhole/USDT0 edges are research/transport/rebalance relations, never assumed atomic trade edges.
5. TON uses its own asynchronous/multi-contract execution class; never assume Solana atomicity.
6. Flash-capital support is a separate graph dimension. The target asset need not itself be flash-borrowable if an eligible settlement asset can be borrowed and swapped; only exact evidence can establish this.
7. Aggregator diversity is not liquidity independence. Retain provider, operator, correlation group, underlying venues/pools and route fingerprint.
8. Unknown capacity, fee, decimals, token extensions, gas, rent, latency or setup cost is UNKNOWN, never zero.
9. All observations retain source generation, request/response hashes, timestamps, chain slot/checkpoint, negative evidence and deterministic replay identity.
10. No research signal can promote itself into `UniversalArbitrageGraph` or a paper/live gate.

---

## 4. Parallel workstream map

Start these streams as separate agents/worktrees from the same audited main or from a frozen shared-contract commit. Every stream owns its own branch, tests, report and PR.

### Stream A — P0-1: Solana data intake + Dynamic Universe completion

**Existing owners:** `src/market/discovery.py`, `src/solana_parallel_radar/radar.py`, `src/discovery/dynamic_universe/`, `src/assets/resolution/`, source governance/journal.

Work:
- complete bounded, cursor-aware DEX Screener, Raydium, Meteora and Manifest discovery;
- integrate Sanctum's live LST registry and identity-aware mint resolution;
- keep GeckoTerminal BLOCKED until the current official schema/rate/access pin is reviewed;
- per-source pagination, byte/row bounds, 429/backoff, negative evidence, complete-snapshot retirement;
- ensure a failed or partial page never retires a market;
- source coverage/status reports and configurable hot universe based on measured coverage;
- solve the documented application boot-path/continuous cadence gap only through the supported composition root.
Do not hand indexed prices/TVL to the exact graph.

### Stream B — P0-2 / GPR-02 follow-through: Solana comparable quote race

**Existing owner:** `src/solana_parallel_radar/probes.py`, `funnel.py`, `cli.py`, `portable.py`, provider governance.

Work:
- reconcile the current pinned Jupiter V2 contract, current code, read-only V1 diagnostic/quarantine and production V2 contract; migrate the existing owner, never add a second Jupiter adapter;
- preserve the 0x `POST /solana/swap-instructions` public-taker requirement and the pinned `ZEROX_API_KEY` name;
- bind the same canonical token pair, exact base-unit amount, taker mode, slippage and time/freshness window;
- retain route programs/underlying venue and pool IDs, fees, raw response hashes, negative results and correlation;
- add missing response fixtures and schema-drift/no-route/429/timeout cases;
- use 0x + Jupiter as the first quote race; add Titan/OKX/OpenOcean/Rango only after current official request/build contracts are pinned and their overlap is recorded;
- do not compare unverified quotes as executable profit; never extrapolate quotes across sizes.
No signer, sender or submission.

### Stream C — P0-3: exact direct-state venue coverage

**Existing owners:** canonical Raydium CPMM native decoder, provider governance, rooted RPC/quorum, market observations and exact graph.

Work:
- audit/fix the current program-ID/dispatcher defects documented in P0 baseline if still present on current main;
- complete exact Raydium CLMM and Meteora DLMM state/math using pinned compliant SDK/IDL sources;
- preserve complete tick/bin/bitmap/oracle dependencies and coherent slots;
- keep Orca BLOCKED pending current license review; do not copy custom-licensed source;
- owner/program, mint/vault, token-program, decimals, fee, rounding and state freshness proof for each supported version;
- positive and negative differential fixtures.
No indexed-data promotion; unknown layouts fail closed.

### Stream D — GPR-03 Sui remediation

**Existing owners:** `src/gpr_sui_shadow/`, Sui transport, DeepBook pool refs and AssetIdentity.

Work:
- reproduce/fix the measured GraphQL Content-Length rejection without weakening transport bounds;
- narrow Aftermath requests and respect response cap;
- qualify two independent, non-smoke gRPC/GraphQL providers and checkpoint consistency;
- exact Move type, package/object versions, decimals, depth, fee and pool binding;
- add/read DeepBook, Cetus, Aftermath and Scallop source lanes; retain NAVI's off-chain asset list as discovery only until matching on-chain resource proof exists;
- complete read-only qualification receipts and a bounded repeated capture/replay.
No legacy Sui JSON-RPC; no live PTB executor, signing or sending.

### Stream E — R-02 Live Capital Readers (four independent reader tasks)

Use four isolated worktrees/PRs where practical:

- **CAP-A Jupiter Lend:** exact TokenReserve PDA/layout, reserve, mint, vault, token program, borrower/limit state, fee/cap and independent rooted RPC proof.
- **CAP-B Kamino:** pinned generated Reserve/LendingMarket/LastUpdate/config decoder, actual available liquidity, fee rational/rounding, caps, oracle, vault and coherent rooted state.
- **CAP-C NAVI:** current modular SDK/package/config, exact shared pool objects, coin type/decimals, checkpoint, fee and effective capacity; API `getAllFlashLoanAssets` is discovery, not on-chain capacity.
- **CAP-D Project 0:** wallet-free bank discovery first; optional scan of an existing public authority/account only if the operator separately supplies it. Never create an account.

All four feed the existing `FlashCapitalGraph`. Emit a positive edge only if resource-level capacity, effective fee, constraints, independent evidence and replay are complete. Current baseline: zero qualified edges; 27 catalog candidates remain disabled. Do not claim R-02 PASS from admin flags, TVL, documentation, an SDK list or a program account.

### Stream F — R-03 unsigned builder adapters

Freeze/reuse `src/lending/financing.py` and existing exact transaction/PTB owners. Build source-pinned unsigned borrow/repay instructions separately for:
- Jupiter Lend;
- Kamino;
- NAVI PTB v1/v2 as dictated by verified deployed config and hot-potato receipt semantics;
- conditional Project 0 only with a bound existing account and current SDK.

R-03 offline builder conformance can proceed while R-02 reader work is blocked. Keep `build_status` separate from `capacity_status`; an unsigned builder is not a qualified live-capital route. No signer, sender or account creation.

### Stream G — Multi-provider quote/build expansion (Solana + Sui)

Build on existing quote/financing contracts rather than creating a duplicate transaction kernel.

Solana candidates:
- 0x;
- Titan;
- Jupiter;
- OKX DEX;
- OpenOcean;
- Rango.

Sui candidates:
- Aftermath;
- Cetus Aggregator;
- 7K/Bluefin7K;
- FlowX;
- OKX DEX;
- Rango;
- direct DeepBook.

Requirements:
- first verify official APIs/SDK versions, auth, rate quotas, fee fields and build output;
- record whether each returns economic quote, instructions, serialized unsigned transaction, composable Sui Transaction/PTB or merely a route reference;
- preserve underlying DEX pools and provider correlation;
- compare 0x/Titan/Jupiter in Solana and Aftermath/Cetus/7K/FlowX in Sui only when amount/identity/time semantics match;
- OpenOcean/aggregators sharing Jupiter/Titan or the same underlying pool do not count as independent liquidity;
- private keys remain local; qualification has `sign_enabled=false`.
Never assume API limit values from old notes; update profiles from current official docs and observed 429/latency.

### Stream H — Dynamic universe / structural relationships / correlation

Reuse the existing Dynamic Universe, relation generators, CorrelationLedger, Parquet/retention, graph and PR118 owners.

Expand live registries rather than hardcoding all pairs:
- all valid Sanctum LSTs and discovered Solana venue pools;
- DeepBook/Cetus/Aftermath/NAVI/Scallop/Bluefin/FlowX assets and markets;
- all STON assets/pools and external TON routes;
- later EVM assets/protocols and public CEX/orderbook references.

Generators:
- direct market from an observed pool/book;
- synthetic A/HUB/B only when both real legs exist;
- structural parity only with proven common underlying and representation;
- bounded cycles (3–5 edges) only after each relevant edge meets its own state/quote proof;
- capital edges joined after lender qualification;
- cross-chain basis as research/rebalance only.

Compute residual series, not raw nominal price correlations:
- stable/redemption residual;
- LST premium vs protocol exchange/instant exit rate;
- wrapper basis vs underlying reference;
- JLP/NAV basis;
- AMM-vs-CLOB exact-size VWAP residual;
- direct-vs-synthetic route residual;
- chain basis minus rebalance cost;
- oracle-vs-market residual.
Lead/lag windows may include 100ms/500ms/1s/5s/30s/5m only when source and chain timestamps can be aligned. Correlation never proves causation or execution.

### Stream I — TON-RADAR-01 / TON data universe

**Existing owner:** `src/discovery/dynamic_universe/ton_radar.py`.

Use:
- STON.fi REST assets/pools/stats as broad cheap research ingestion;
- Omniston as a TON cross-DEX/RFQ aggregation view;
- swap.coffee as a second route/pool view;
- DeDust and Tonco direct views;
- TON Center and TonAPI for chain/indexed state;
- Rango TON messages as optional builder/reference only after source pins.

The current owner already has bounded STON assets/pools/stats polling and optional injected Omniston enrichment. Complete current official schema/source pins, test live endpoint behavior under the approved proxy, add missing provider adapters only when justified, and add independent direct-pool/state comparisons. A “no published rate limit” statement is not an unlimited polling license: retain self-imposed per-source budgets and backoff.

TON remains `TON_ASYNC_MULTI_CONTRACT` / research-only unless a separately verified settlement design proves otherwise. Do not reuse Solana-style atomic flash-loan assumptions or assume that a TON quote aggregator is the whole TON data universe.

### Stream J — Slumlord / RentSponsorPlanner

**Existing owner:** `src/lending/slumlord.py` already builds and validates sender-free Slumlord instructions.

Implement the missing route-level rent planning integration without duplicating the Slumlord adapter:

1. reuse a qualified existing token account;
2. use provider sponsorship/payer when available and verified (e.g. 0x sponsor or Titan payer);
3. use Slumlord only for eligible ephemeral temporary accounts that become zero and can be closed before same-transaction Slumlord repayment/check;
4. use ordinary persistent funding for final output accounts that must remain open;
5. reject the route if account/rent/fee/byte/CU economics fail.

Slumlord is rent financing, not trading capital and not a universal free-ATA primitive. Network/priority fees remain independently funded. Do not actually create/close an ATA or submit a transaction during qualification. Prove order/close/rent arithmetic through unsigned plans and local simulation fixtures only.

### Stream K — R-04/R-05/R-06 integration and paper qualification

These depend on exact market quotes/state, at least one qualified R-02 reader and its matching R-03 builder:
- R-04 select route + settlement asset + lender + amount using PR118 and full costs;
- R-05 assemble and simulate complete unsigned Solana transaction or Sui PTB against current coherent state; enforce all lender-specific bookends, token/object semantics and exact repayment;
- R-06 run replayable sender-free paper qualification only when entry gates pass.

If prerequisites are absent, produce typed blockers and continue independent source work. Do not invent fills, fees or capacity. Do not start a 24-hour paper window if readiness is BLOCKED.

### Stream L — broader provider expansion / EVM / R-07

Reassess the 27-candidate catalog and current provider knowledge base; select each new source/provider only for incremental information or executable opportunities. Include Morpho Blue/Aave V3 and other EVM protocols as a separate chain domain with pinned deployments and local/fork simulation, not as Solana/Sui edges. One provider per bounded PR, with licenses, source pins, capacity/fees, execution semantics and all-in setup cost. Do not enable every catalog entry.

---

## 5. Dependency-aware concurrency plan

The coordinator should start the following concurrently after the initial baseline:

### Wave 0 — one coordinator task
- current main/PR/CI audit;
- offline bundle verification;
- current owner/status matrix;
- source/documentation gaps and environment access probe;
- freeze shared interfaces and branch naming policy.

### Wave 1 — parallel research and isolated implementation
Start independent worktrees for A, B, C, D, E(A-D), F(offline contracts), G(source dossier/adapter prototypes), H, I, J(offline integration planning). Each worktree must record exact base SHA and owned paths.

### Wave 2 — integration after shared contracts
- unify quote/build normalization through existing owner contracts;
- merge separate chain/source PRs only after their independent tests and handoff receipts pass;
- reconcile Dynamic Universe -> graph -> VerificationQueue without duplicating GPR-01;
- integrate live capital readers with FlashCapitalGraph only after exact resource proof;
- integrate RentSponsorPlanner with unsigned plan builder only after route instruction composition is stable.

### Wave 3 — route and execution qualification
- R-04 capital-aware route selection after relevant quote/state + lender/builder gates;
- R-05 full unsigned transaction/PTB simulation;
- R-06 gated paper campaign.

### Wave 4 — broaden
- R-07 remaining providers, new asset classes, EVM expansion and further correlation families based on observed evidence.

Parallel work can continue on a blocked stream's documentation, schemas, fixtures and independent venues. A blocked dependency blocks only promotion of routes that require it; it must not stop unrelated research.

---

## 6. Source universe to research and qualify

This is a **discovery checklist**, not a claim that every API is implemented, available for free or ready for production. Reconcile against `src/resources/market_source_catalog.json`, `config/qualification/din00-source-status.json`, source dossiers and current official docs.

### Solana
- Radar/index: DEX Screener, Raydium, Meteora DLMM/DAMM, Manifest, Sanctum, GeckoTerminal (blocked until docs/schema pin), Vybe, Birdeye, CoinGecko/DefiLlama as reference.
- Route/quote/build: Jupiter V2, 0x, Titan, OKX DEX, OpenOcean, Rango.
- State/market structure: Solana independent RPC providers, Raydium CPMM/CLMM, Meteora DLMM, Manifest CLOB, Orca only if licensing clears, Pyth/Switchboard references, public Binance/Coinbase/Kraken/Bybit orderbooks as non-atomic lead/lag references.
- Assets/relations: stables and yield-bearing stables, all verified Sanctum LSTs, restaking/LRT, BTC wrappers, JLP/NAV, newly discovered liquid/event tokens, tokenized securities/RWAs as a separate market-hours/reference class.

### Sui
- Radar/state/quotes: DeepBook, Aftermath, Cetus, Scallop, NAVI, Bluefin/7K, FlowX, OKX, Rango.
- Exact transport: independent Sui gRPC/GraphQL providers with checkpoint/object-version provenance; no new legacy JSON-RPC dependency.
- Capital: NAVI, DeepBook, Scallop only after current resource/cap/fee evidence.
- Assets/relations: native vs bridged stables, BTC/ETH/SOL representations, all verified Sui LSTs, DEEP/WAL/ecosystem, XAUm/XAGm oracle-linked research, RWA where supported.

### TON
- STON all assets/pools/stats; Omniston; swap.coffee; DeDust; Tonco; TON Center; TonAPI; optional Rango.
- Core relationships may include TON/USDT, staking derivatives, USDe/USDT, GRAM-hub routes, gold/RWA, governance/event assets and newly discovered pools. All market relations are dynamically generated from real pool evidence; no manual all-pairs polling.

### EVM/future
- Morpho Blue, Aave V3, Balancer, Curve, Uniswap and other reviewed capital/venue candidates from the provider catalog.
- Keep chain IDs, deployed contracts, callbacks, receiver code, pool balances and gas/settlement semantics separate. No EVM adapter may be enabled by a docs-only claim.

### Cross-chain economic links
Research underlying families such as USDC, USDT, SOL, BTC, USDY, FDUSD, USDe, tokenized gold and other verified assets across Solana/Sui/TON. Record bridge/CCTP/USDT0 costs, latency, finality and inventory effects. Cross-chain output remains basis/rebalance research, not a chain-local atomic edge.

---

## 7. Offline technical knowledge base — mandatory for every new source

The repository already contains the offline master and pinned docs. Extend it rather than rebuilding it.

For each newly used external API/SDK/program/IDL:
- official canonical URL and retrieval timestamp UTC;
- exact API/package/SDK version, commit/tag and blob SHA;
- license and reuse restrictions;
- complete request/response schema, unit/decimal/fee semantics;
- pagination, auth, quota, retry/429, freshness and error semantics;
- relevant program/package IDs, object/account layout, state version and rounding;
- redacted positive, negative and schema-drift fixtures;
- immutable source manifest plus zero-network verifier;
- clear flags: RAW_OFFICIAL_SNAPSHOT, OFFICIAL_CONTRACT_EXTRACT_ONLY, SOURCE_PIN_ONLY, DOCS_REFERENCE_ONLY, BLOCKED_MISSING_PIN.

A URL or model summary alone is not an offline technical dossier. Never pretend a source was fetched if network/tool access is missing. If the environment has internet, verify current official facts and archive them. If not, produce an exact acquisition manifest and mark that source blocked pending retrieval.

### Verify agent tool access at the beginning

GLM-5.3-Flash does not acquire Internet just because the model name includes Flash or the token quota is large. The actual agent host must expose browser/search/MCP/network tools.

Prove the environment by:
1. fetching one current official Jupiter/0x page;
2. fetching one current official Sui gRPC/GraphQL page;
3. fetching one current official STON/Omniston page;
4. recording exact URLs, retrieval time and response hash;
5. confirming it can read the repository and run shell/git/test commands.

If any capability is absent, report `TOOL_ACCESS_MISSING` and do not invent live research or provider behavior. GLM context length and total coding-token quota are not the same thing; use retrieval and compact owner maps rather than attempting to stuff the whole repository into one prompt.

---

## 8. Source code, tests, evidence and PR rules

### Worktree/branch discipline
- One isolated worktree per coding subagent or non-overlapping task.
- Every branch is based on the exact current/reviewed base SHA.
- Shared contracts have one owner and a frozen commit.
- Never parallel-edit a canonical file.
- If a merge conflict occurs, stop and let the coordinator reconcile; never force-push over another agent's work.
- Each implementation PR has a single coherent owner boundary, not one mega-PR across all domains.
- The coordinator may keep many PRs open concurrently, but must integrate them in dependency order.

### Every PR must contain
- exact base/head SHA and worktree state;
- changed file list and owner-reuse matrix;
- source manifest and license/provenance pins;
- tests run, tests not run and exact commands;
- socket-disabled offline replay;
- positive and negative evidence;
- bounded live capture details where explicitly run;
- credentials **names only** (never values);
- provider limits as observed/pinned, not assumed;
- exact blockers and next task;
- safety flags showing signer/sender/submission/live capital/production promotion still false.

### Merge discipline
- Documentation/source-reference PRs may merge only after reviewing diff, SHA pins, legal provenance, current base and no duplicate content.
- Implementation PRs are never merged automatically. The coordinator queues them for human review/approval.
- Do not remerge QPR/GPR/legacy branches that are already represented in main.
- Refresh or supersede stale PRs. In particular, do not merge a baseline/branch whose base is materially behind current main without recreating its report against the latest SHA.

### Test discipline
- run the full repository verifier at the correct integration gates;
- run targeted per-workstream suites in each worktree;
- run socket-disabled offline tests/replay;
- run mypy/format/lint/security/dependency/package gates as prescribed by the repo;
- never copy historical test totals into a current report;
- don't switch off a failing test, relax a hash check or weaken an admission gate to get a green run.

---

## 9. Safety and authority boundaries

Until separately authorized after qualification:
- `sign_enabled=false`
- `send_enabled=false`
- no private keys/seed phrases in source, logs, PRs, API calls or model context;
- no account/ATA/position/obligation creation;
- no real borrowing, transaction submission, spending or deployment;
- no production promotion;
- no live provider enabled simply because it exists in a catalog.

Unsigned transaction/PTB construction and local simulation can be implemented as offline evidence. Provider APIs never receive a private key. Local signing is a separate later authority decision; this mandate does not authorize it.

---

## 10. Global exit criteria

The project does not become complete because a large amount of code or tokens were consumed.

A research/qualification stage is complete only when:
1. all claimed sources have current pinned contracts and a tested adapter or an explicit blocker;
2. the maximum discoverable universe is populated from verified registries/real market data, with no forced pair count;
3. direct/synthetic/parity/cycle relations retain exact representation identity, provenance and correlation;
4. Solana/Sui/TON chain-specific state and execution semantics remain distinct;
5. quotes are amount-specific and comparable; losing quotes are retained as evidence;
6. live capital readers prove real resource capacity, effective fee and constraints, or remain blocked;
7. unsigned builders prove provider SDK conformance and exact borrow/repay/PTB ordering;
8. rent/ATA plan captures provider sponsorship, Slumlord ephemeral rent and persistent account costs without false “free ATA” claims;
9. complete exact transaction/PTB simulation reconciles all state and costs;
10. paper qualification uses real retained evidence, deterministic replay and current QPR/campaign gates;
11. all safety/quarantine/authority gates remain unchanged.

At every stop, produce a **Project Execution Dashboard** with workstream status, current branch/PR/head, completed evidence, current blocker, dependency, agent/worktree owner and next action. Keep research, implementation and qualification statuses separate.

---

## 11. Coordinator completion/report format

Return one concise executive summary plus machine-readable `PARALLEL_EXECUTION_STATUS.json` with:

| Field | Required |
|---|---|
| Current main | exact SHA, date, worktree state |
| PR reconciliation | each relevant PR: merged/open/superseded, base/head, unique paths |
| Knowledge base | offline verifiers, missing pins, source versions/licenses |
| Workstreams | status, owner branch/worktree, changed paths, tests, exact evidence |
| Live observations | provider, time, attempts, outcome, raw hash, slot/checkpoint |
| Capital | each lender status; never aggregate UNKNOWN as zero |
| Builders | each provider's unsigned conformance status, separate from capital |
| Execution | simulation/paper status, separate from signing authority |
| Blockers | exact typed cause, owner and required human input |
| Next | one integration order and copy-ready next command |

Use exact statuses. Do not say “all complete” if one provider/state/evidence gate is blocked.

---

## 12. Final instruction

**Use the available coding budget to make broad parallel progress across the whole strategy. Do not shrink the objective to UXE-00 or a single provider. Do not rebuild already implemented GPR-01/GPR-02/GPR-03/Dynamic Universe/Slumlord owners. Start by proving the current main state, then launch non-overlapping research and implementation workstreams concurrently. Integrate them through frozen contracts, exact evidence, isolated PRs and sequential promotion gates.**

The target is a self-updating multi-chain market/economic graph with multiple independent quote/build sources, exact market verification, flash-capital selection, rent-aware Solana transaction planning, Sui PTB qualification, TON research, correlation/lead-lag learning and a safe paper campaign — not one giant unreviewable code drop.
