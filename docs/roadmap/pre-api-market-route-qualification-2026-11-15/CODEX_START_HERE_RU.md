# CODEx START HERE — Pre-API market → exact route → paper qualification closure

**Branch:** codex/pre-api-market-route-qualification-2026-11-15  
**Base observed during PR creation:** main `9f173d7632cb30190bb8d9174ceba6d116eaec70` (refresh before execution)  
**Scope:** one implementation vertical; strategy expansion remains paused. This PR starts as a draft assignment PR. Codex must commit implementation and tests to this same branch before merge.

## Goal

Finish the existing R10-1 integration gap and make one deterministic route-evaluation path work end-to-end:

`canonical market identity → consistent state → route topology → exact sequential amount evaluation → pool/lineage dedup → non-monotonic size grid → all-in economics → capital/builder/simulation gates → durable sender-free paper evidence`.

Do not add new strategy families. Do not turn on external API requests in this PR. The result should be a reproducible code substrate ready for a later controlled read-only API-capture PR, not a profitability claim or live-ready bot.

## 1. Reconfirm state and avoid duplicate work

1. Read `AGENTS.md`, root `CODEX_START_HERE.md`, `docs/roadmap/agent-execution-master-2026-11-13/CODEX_START_HERE.md`, `PROJECT_KNOWLEDGE_BASE_MAP.md`, `TASK_INDEX.md` and `MULTI_AGENT_EXECUTION_PLAN.md`.
2. Refresh main SHA/tree, open PRs, checks/branch protection, #593/#604/#613/#638/#640/#641/#642/#643/#654, open #649/#655/#657, active branches and worktrees.
3. Search for an equivalent R10-1 / CPMM cycle binding in every active branch/worktree. At PR creation no branch/PR named R10-1 cycle binding was found; that is not a substitute for rechecking.
4. Never reset, stash, delete or force-overwrite another agent's unfinished work. If an equivalent owner exists, stop and report owner overlap; do not create a duplicate.
5. Keep the pause: no SX/EXP/W6 revival, no new strategy registration, no work on unrelated open PRs.

Read at minimum:
- `docs/roadmap/STUDIOUS_PANCAKE_MASTER_CODEX_EXECUTION_2026-11-13/STRATEGY_UNIVERSE_ATLAS.md`
- `docs/roadmap/STUDIOUS_PANCAKE_MASTER_CODEX_EXECUTION_2026-11-13/CURRENT_REPO_OWNER_MAP.md`
- `docs/roadmap/STUDIOUS_PANCAKE_MASTER_CODEX_EXECUTION_2026-11-13/MASTER00_IMPLEMENTATION_MATRIX.json`
- `docs/roadmap/agent-execution-master-2026-11-13/reports/R08_RUNTIME_COMPOSITION_AUDIT_2026-11-14.md`
- `docs/roadmap/agent-execution-master-2026-11-13/reports/R13_QUOTE_BUILD_RACE_AUDIT_2026-11-14.md`
- R04, R05, R06 tasks; R10 strategy inventory; P0-1/2/3 reports; GPR-02 handoff.

## 2. Strategy and route priority

The highest-ROI path is **local same-chain closed-cycle swap arbitrage**, because one common exact route path covers many currency pairs and topologies. A flashloan is a funding primitive, not a standalone strategy.

Initial supported route shapes:
- Two-leg `A → B → A`: reuse current two-leg detector; legs must use distinct proven physical liquidity resources.
- Three-leg triangle `A → B → C → A`: connect existing graph topology to exact CPMM route evaluation.
- Four-leg cycle `A → B → C → D → A`: same exact evaluation constraints.
- Existing 2–5 hop solver remains a topology shortlist. Do not promote an unsupported 5-hop route or any route with a non-exact leg.

Use canonical asset identity (chain/genesis + mint/contract + token program + decimals), not tickers. Final asset must be the exact starting canonical asset. Same chain, same supported observation generation, fresh state, valid slots and quote expiry. No bridge, cooldown, queue, maturity or delayed settlement in a local atomic route.

Next venue breadth (not this PR): Raydium CLMM after tick/bitmap state and exact evaluator parity; Meteora DLMM after direction-specific bin arrays and pinned SDK fee/rounding parity; Orderbook/AMM after verified subscriptions, sequence/depth and fill semantics. Split-flow comes only after single-route exact capacity works. LST/issuer/liquidation/cross-chain routes remain later research because they need additional rights, settlement and capital proofs.

## 3. Reuse these canonical owners — no parallel systems

- Discovery/governance: `src/qualification_campaign/`, `src/provider_governance/`, `src/solana_parallel_radar/`, `src/discovery/dynamic_universe/`, `src/market/`.
- Identity: `src/assets/resolution/` and canonical mint registry.
- Relations/graph/topology: `src/strategy/relation_generators/`, `src/strategy/market_graph_ingest.py`, `src/strategy/arbitrage_graph.py`, `src/strategy/multihop_solver.py`, `src/strategy/detectors.py`.
- Exact venue: `src/providers/raydium_cpmm_native.py`, `src/market/native_cpmm_capture.py`, `src/strategy/exact_cpmm_capacity.py`.
- Sizing: `src/economics/non_monotonic_sizing.py` (PR118).
- Quote lineage/build: `src/execution/quote_build_kernel.py` (R13-K `PoolIdentityDeduplicator`).
- Capital/build/simulation: current `src/economics/flash_capital_graph/`, `src/lending/unsigned_builders/`, `src/execution/exact_simulation.py`.
- Paper/evidence/runtime: current `src/paper_shadow/`, qualification campaign/journal, `src/runtime/`.

The implementation matrix already identifies R10-1 as: bind CPMM graph cycle candidates → exact route plan → per-amount exact evaluation → PR118 ledger. Implement the narrow planned `src/strategy/cpmm_cycle_binding.py` only if no equivalent owner exists on current main; otherwise extend the current canonical owner. Do not create another graph, solver, quote kernel, registry, source store, capital graph, journal or paper runtime.

## 4. Required implementation

### A. Exact CPMM cycle binding
- Connect `QualifiedCpmmState` and existing route enumeration to `evaluate_exact_cpmm_route`.
- Retain the two-leg detector contract; bind existing three-/four-pool CPMM cycle path to exact evidence using current route/evaluation types where possible.
- For each next leg, input = previous leg's conservative guaranteed output in raw base units. No quote scaling.
- Enforce exact start/end mint, canonical asset identity, route expiry/freshness, same observation generation, bounded slot skew, supported fee/rounding model, unique physical pool/resource and route budgets.
- Unsupported venue/state must produce typed blocked/unqualified reason, never heuristic promotion.

### B. Bounded multihop topology
- Solver shortlist/marginal rates are topology only, not exact output or profit.
- Exact promotion only if every route leg has a supported amount-specific exact evaluator at the same valid state generation.
- In this PR, CPMM is the exact venue target. CLMM, DLMM and orderbook stay blocked/unqualified until their evidence is complete.

### C. Pool identity and provider overlap
- Invoke R13-K `PoolIdentityDeduplicator` before candidate promotion and before counting independent venue/liquidity evidence.
- Detect exact underlying pool IDs, route lineage and correlation groups; apply transitive clustering.
- If pool identities/lineage are absent, independence is UNKNOWN and must not be assumed.
- Jupiter and 0x exposing the same underlying pool is one physical resource, not independent liquidity.

### D. Per-size sizing and net economics
- Reuse PR118 amount-grid and non-monotonic sizing owners.
- Every grid point gets a fresh exact sequential route evaluation. Never scale a quote/fee/capacity from another amount.
- Record per-leg DEX fees, supported dynamic fees, Token-2022 transfer fees/hooks, lender premium/rounding/repayment only when lender-qualified, network/base/compute/priority cost, tip only if enabled, rent/ATA/setup costs if applicable, and safety buffer.
- Store each cost in its native denomination; conversion into route numeraire needs explicit conservative price evidence. Unknown cost or conversion blocks net-positive status; unknown is never zero.
- Separate gross spread, lender repayment, non-refundable expenses, refundable deposits/rent, and conservative net. Preserve non-monotonicity; no monotonic binary-search assumption.

### E. Evidence and paper seam
- Reuse existing native CPMM qualification, Opportunity/evidence, durable journal and paper lifecycle.
- Market candidates may be counted without a qualified lender, but they must remain distinct from flashloan-eligible candidates.
- `PAPER_COMPLETE` requires actual R02 capacity + R03 builder + R04 economics/route + R05 full simulation + R06 campaign gates. If blocked, preserve the candidate with precise reason (e.g. `NO_QUALIFIED_LENDER_EDGE`, `BUILDER_UNQUALIFIED`, `SIMULATION_SOURCE_BLOCKED`, `QPR_NOT_READY`).
- No fake paper fills. No signer, sender, wallet/ATA/account creation, borrowing, transaction send or runtime authority changes. Live/sign/send remain false/hard-denied.

### F. Deterministic offline end-to-end replay
Add a single replay through discovery fixture → identity → route → exact evaluation → size grid → economics → evidence report. Mark all inputs and counts as fixture/replay, not live data.

Test: positive two-leg; positive 3-pool triangle; positive 4-pool cycle; gross positive but net negative; marginal shortlist rejected by exact evaluator; non-monotonic optimum; stale/expired/mixed generation/slot skew; wrong mint/program/decimals; non-closed path; same-pool alias across aggregators; unknown lineage; unsupported CLMM/DLMM/orderbook; missing tick/bin; unknown cost denomination; lender absent/stale/insufficient; missing builder; simulation blocked; deterministic replay digest. Verify no signer/sender/live capability is introduced.

## 5. Metrics (no single misleading “success rate”)

Produce stage counters and reasons:
`discovered_market_count`, `identity_verified_market_count`, `rooted_state_count`, `topology_route_count`, `unique_semantic_route_count`, `aliased_or_correlated_route_count`, `exact_quote_route_count`, `exact_qualified_route_count`, `net_positive_route_count`, `size_grid_evaluated_count`, `capital_eligible_count`, `builder_eligible_count`, `simulation_pass_count`, `paper_attempt_count`, `paper_complete_count`, `paper_rejected_count`.

Also report by hop count/venue/provider/asset: rejection reasons; quote latency and age; slot skew; stale-state rate; replay divergence; gross edge; fee and network breakdown; lender fee; conservative net distribution by amount; unique physical pools; provider-overlap cluster count.

Define separate ratios:
- exact qualification = exact-qualified / topology shortlist (not ground-truth precision);
- economic survival = net-positive / exact-qualified;
- capital eligibility = capital-eligible / net-positive;
- simulation pass = pass / attempts actually simulated;
- paper completion = complete / actual paper attempts.
Fixture/replay and live-source records must never be mixed. Later live-execution success requires landed/finalized tx + token-delta reconciliation + realized fees.

Preserve negative/no-trade observations to prevent survivor bias.

## 6. Next API capture order (prepare only; DO NOT call APIs in this PR)

1. DEX Screener discovery → exact canonical identity; indexed liquidity is not executable depth.
2. Raydium API V3 metadata/config; Meteora Data API as supplemental discovery; then on-chain state read.
3. Jupiter V2 `/swap/v2/order` quote-only first, no taker for initial read-only probe; same raw input sizes and bounded time skew.
4. 0x Solana `/solana/swap-instructions` after API key/taker/schema/header verification; instructions remain inert evidence.
5. Independent Solana RPC sources; read pool/vault/mint/tick/bin accounts in a common `getMultipleAccounts` context and record slot/provenance/quorum.
6. Raydium CPMM exact evaluator first; CLMM/DLMM later after their full state and exact math/fee parity.

Docs to re-pin immediately before the next campaign:
- https://solana.com/docs/rpc/http/getmultipleaccounts
- https://developers.jup.ag/docs/swap
- https://developers.jup.ag/docs/api-reference/swap/order
- https://docs.0x.org/solana/solana-swap-api/introduction
- https://docs.dexscreener.com/api/reference
- https://api-v3.raydium.io/docs/
- https://docs.meteora.ag/developer-guides/dlmm/sdk

Validate exact quotas, auth, version, headers, OpenAPI schema, licensing and retention. The 0x general docs' `0x-version` header requirement must be reconciled with the specific Solana endpoint contract; do not guess. Never commit or print credential values.

## 7. Exit criteria and PR deliverables

One end-to-end deterministic replay passes from existing input owners through exact route + dedup + size grid + cost + durable evidence, with typed negatives and deterministic digest. Include exact test commands/results, before/after owner map, files changed, route support matrix, R10-1/MASTER00 status update, API preflight list and explicit R02/R03/R04/R05/R06 blockers. No claim of live market observation or profitability.

This only makes the code substrate ready for a **separate controlled read-only API capture PR**. It does not make the system live-ready.

## 8. Hard prohibitions
No strategy expansion; no duplicate global subsystem; no symbols-as-identity, TVL-as-depth, marginal-rate-as-profit, quote extrapolation, unknown-cost-as-zero, same-pool double counting, async/cross-chain leg in a local atomic route, secrets, wallet/account creation, signing, sending, borrowing, spending, deployment, live provider activation, live-mode enablement or production promotion. Do not merge until tests/checks, source/license provenance, owner-overlap audit, resolved review threads, clean rebase, mergeability and branch protection all pass.
