# CODEX START HERE — Broad Market Universe + Data Capture → Paper Qualification

**Repository:** BobIvans/studious-pancake  
**Assignment branch:** codex/paper-data-campaign-universe-relay-budget-2026-11-21  
**Main SHA at pack creation:** 3030fc720c707c994f9d7a21d50e1d181a60b8c9  
**Pack date:** 2026-11-21

## 0. Exact purpose

Prepare the broadest useful **local-atomic market universe** for the Solana-first flashloan bot and create the evidence, source, replay, provider and campaign tasks required to start a controlled read-only market-data campaign, then progress through the existing R02→R06 paper qualification gates.

This is a campaign-preparation/task-pack PR, not activation. The first allowed run is data-only, sender-free and read-only. It does not send transactions, sign, borrow, pay tips, create accounts, claim a profitable opportunity, or qualify a route.

Keep these phases distinct:

1. **CAPTURE_ONLY / market-data observation:** universe discovery, identity resolution, market observations, rooted-state collection where separately authorized, exact quote/replay evidence, rejected candidates and negative evidence.
2. **Exact route qualification:** only after source/market proof; R04/R02/R03/R05 requirements remain independent.
3. **Installed sender-free paper qualification:** only through existing R06/QPR/canonical installed paper owner after its exact PASS, never through a new parallel loop.

A data-only campaign may gather useful evidence while paper gates remain blocked. It must never be reported as `PAPER_QUALIFIED`.

## 1. Current main / PR facts and lane boundaries

Verified at pack creation:
- PR #658 merged.
- PR #659 merged (R10-1 CPMM route binding).
- PR #663 merged on 2026-11-20 as R08-step1 governed-RPC composition seam.
- Current main is `3030fc720c707c994f9d7a21d50e1d181a60b8c9`.
- PR #660 remains open and draft for Raydium CLMM / Meteora DLMM; its GitHub branch still points to the original docs-only assignment commit `8e4a1b9eccaca3ce66374719f792a26666a11492`. User-reported local execution may not yet be published to GitHub. Do not overwrite or duplicate #660; refresh its actual head and changed paths before any implementation.
- Other open lanes at audit time: #649 Curve LLAMMA, #655 MarginFi R10-2 bridge, #657 SX-18/W6-12 docs. Check their current heads/status before dispatch and avoid path overlap.

### R08-step1 precision

Reuse `src/runtime/core_v1_dependency_resolver.py` and the R08-step1 `governed_rpc_transport` injection for the CORE-V1 simulation dependency when that composition is used. It accepts a deployment-supplied transport only when a matching manifest-pinned `GovernedRpcDescriptor` is supplied; missing either side stays blocked. The resolver creates no network transport itself.

**Do not misinterpret R08-step1 as a generic market-data account reader, a new RPC provider, or a campaign authorization.** For observation/account collection, reuse the existing governed provider plane, QPR/DIN/provider profiles, quota owners and durable source journal. The data campaign needs its own source profile and operator-approved capture manifest. Simulation RPC identity and capture-source identity must both be traced, not conflated.

## 2. Mandatory preflight and files to reconcile

Read current main (not only this pack), AGENTS.md, root CODEX_START_HERE.md, PROJECT_KNOWLEDGE_BASE_MAP.md, TASK_INDEX.md, MULTI_AGENT_EXECUTION_PLAN.md, PR list, branches, worktrees and codeowners. Then reconcile:

- `docs/roadmap/agent-execution-master-2026-11-13/tasks/R06_PAPER_QUALIFICATION.md`
- `docs/roadmap/agent-execution-master-2026-11-13/tasks/R02_CAPITAL_READERS.md`, `R03_UNSIGNED_BUILDERS.md`, `R07_PROVIDER_EXPANSION.md`, `R13_MULTIPROVIDER_QUOTES_AND_BUILDS.md`
- `docs/roadmap/prequal-rnd-2026-10-06/package/04_CAMPAIGN_START_GATE_RU.md`, `11_SOURCE_PLUGIN_ARCHITECTURE_RU.md`, `data/campaign_manifest.example.json`, `data/known_source_candidates.csv`, `data/free_source_slots.csv`
- `docs/strategy-expansion/2026-11-14/MASTER_FLASHLOAN_MARKET_INTEGRATION_AND_BUILD_BIGGER_UNIVERSE_RU.md`
- `STRATEGY_UNIVERSE_ATLAS.md`, `R10_STRATEGY_INVENTORY_2026-11-14.md`, `STRATEGY_GAP_ANALYSIS_RU.md`, `STRATEGY_RESEARCH_CROSSWALK_AND_NEW_GAPS_RU.md`, SX assignments, GPR/DV work packages
- `docs/pr130_jito_mev_policy.md`, `docs/mpr04_isolated_signer_jito_canary_boundary.md`, R08-step1 report and R08 composition audit
- Current `src/market/source_catalog.py`, `src/market/discovery.py`, `src/market/observations.py`, `src/market/streams.py`, `src/strategy/market_graph_ingest.py`, `src/strategy/arbitrage_graph.py`, `src/strategy/relation_generators/`, `src/economics/flash_capital_graph/`, `src/qualification_campaign/`, `src/provider_governance/`, `src/data_plane/`, `src/paper_shadow/`, `src/lending/`, `src/runtime/core_v1_dependency_resolver.py`.

The existing source registry, R06 campaign contract, R08 RPC seam, campaign manifest schema and market graph are the authorities. This pack adds no second source catalog, runtime, paper runner, scheduler, capital graph, quote engine, journal or transport.

## 3. Expected deliverables

1. Machine-readable crosswalk of every strategy/market/source family to one owner, status, execution class, current blocker, data needs, and next bounded task.
2. Source-ready dossier matrix covering discovery, indexed metadata, aggregators, direct exact-state RPC, streams, oracles/reference, flash lenders and transaction-delivery providers.
3. Campaign manifest that is `CAPTURE_ONLY` by default and binds exact main SHA, runtime authority, policy/config generation, source generations, budgets, operator/correlation groups and retention.
4. A read-only data-capture and replay runbook with candidate universe, pair/address rules, account dependency closure, slot/freshness/quorum rules, quotas, negative evidence and stopping conditions.
5. An execution-delivery research pack that compares Jito and alternatives using the same benchmark attempts, without enabling any submission or tip.
6. A future cost-policy specification that separates base fee, priority fee, relay/auction tip, lender fee, rent/setup, provider cost and failed-attempt cost.
7. Deterministic replay and coverage reports with all fixture/replay counts separate from live-capture counts.
8. A PR/task DAG assigning one bounded implementation/qualification PR per missing owner. Do not solve all strategy families in one PR.

## 4. First campaign target: wide but tiered market universe

Use exact canonical identity: Solana genesis + mint + token program + decimals + relevant extension state. Ticker/symbol is display-only. Universe starts from all permitted current discovery data, but capture and deeper state reads use ranked quotas.

Priority tiers:
- **Tier A — local atomic core:** Solana CPMM, Raydium CLMM, Meteora DLMM, direct Prop AMM candidates only when official/deployed instruction/account semantics are independently verified; Jupiter/0x as route comparators, not independent liquidity.
- **Tier B — same-chain residuals:** stablecoin triangles/peg dislocations; SOL↔LST spot-pool residuals (JitoSOL, mSOL, JupSOL etc. only by exact mint/pool); PumpSwap/DBC→DAMM migration and post-event dislocation as discovery/residual signals until post-state exact quote.
- **Tier C — orderbook/AMM:** Phoenix/OpenBook/Manifest and future venues only after verified subscriptions, sequence/recovery, exact L2 depth, lot/tick, IOC/partial fills and account readiness.
- **Tier D — credit/solvency:** liquidation/health-factor and collateral unwind monitoring; a downstream/conditional family, not a free immediate route until exact rights, unwind and lender eligibility are proven.
- **Tier E — expansion:** Sui DeepBook/Cetus/NAVI with Sui checkpoint/object identity and PTB-specific local atomicity; one EVM pilot after Solana/Sui data gates, not a simultaneous multi-chain rollout.
- **Research/reference only:** CEX-DEX/oracle lead-lag, cross-chain/bridge, funding/basis/carry, vault maturity, redemption queues and prediction complete sets. These can enrich signals but do not become a Solana flashloan leg.

## 5. Funding and execution scope

For Solana funding, compare Project 0, Kamino and Jupiter Lend first; assess Save/Solend only if exact current flash-borrow support and resource identity are proven. MarginFi remains a separately gated/deprioritized lane until its current safety/economic gates pass. For Sui, assess NAVI and DeepBook through their distinct PTB/hot-potato and checkpoint contracts. One lender implementation/reader per PR; aggregators/wrappers are not independent capital.

A “free” documented flashloan is not a qualified zero-cost edge. Read current deployed fee, capacity, repayment, caller eligibility, account/setup, rent, program identity, slot, debt/cap state and independent provenance. UNKNOWN remains UNKNOWN.

Transaction delivery is *future* execution infrastructure, not market-data capture. Compare Jito, Helius Sender, Astralane, bloXroute and 0slot as separate mechanisms. Never assume all accept the same bid, all reach the same leaders, fan-out costs nothing, or the relay with an ACK settled the transaction.

## 6. Do not activate

No provider activation, no credential probing, no paid upgrade, no subscription, no API writes, no account/ATA/position creation, no wallet/key, no signer, no transaction build for submission, no signing, no sending, no borrowing, no tips, no spend, no live mode, no production promotion. Keep `live_enabled=false`, `sign_enabled=false`, `send_enabled=false`, `borrowing_enabled=false`, and `relay_submission_enabled=false`.

## 7. Acceptance

The PR is complete when the source/strategy crosswalk matches current main, the data-only campaign manifest and runbook validate against existing schemas/gates, each source has a truthful status, every strategy has one owner/disposition, no path duplicates #660 or open SX/R02/R03/R07/R13 tasks, offline replay and negative evidence are deterministic, and the exact R06/QPR/R08 dependencies plus human gates are listed. No campaign may be started merely because this documentation PR is merged.
