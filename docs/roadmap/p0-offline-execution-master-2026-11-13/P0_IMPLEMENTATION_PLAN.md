# P0 and whole-project implementation plan — parallel work, gated integration

**Updated:** 2026-11-13  
**Latest audited main at preparation:** \`176f41378645f6f3b3fd95a59617633b5808acb4\` (historical; fetch again before work).  
**Scope:** entire Studious Pancake project. This plan supersedes the stale sequential P0-0 → P0-1 → P0-2 → P0-3 workflow draft in the prior open PR #590.

## 1. Operating model: parallel workstreams, not one mega-PR

One lead/orchestrator maintains the baseline, owner map, dependency DAG, interface contracts, PR dashboard and final integration decisions. Independent worker agents operate in separate Git worktrees/branches and submit focused PRs to current \`main\`.

**Start all independent research and implementation lanes concurrently.** Dependencies control integration and promotion, not whether an independent agent may investigate or build offline fixtures. Work on shared canonical files is serialized behind a single owner/interface freeze.

Parallel tasks:
- Market P0: P0-1 intake, P0-2 quotes, P0-3 direct state.
- Capital P0: R02-CAP-A Jupiter, CAP-B Kamino, CAP-C NAVI, CAP-D Project 0 bank-only.
- Financing builder: R03-00 common unsigned contract; provider builder work can implement offline fixtures in isolated branches once contract is frozen.
- Strategy/research: audit and extend the existing graph/relation/strategy owners; build strategy datasets and deterministic offline evaluation.
- Multichain/source research: Sui, TON and EVM market data, CEX/oracle/reference feeds, provider/source contract acquisition. Discovery remains distinct from exact executable state.
- Platform/reproducibility: local Windows/WSL test environment, offline verifiers, deterministic replay, CI and package smoke.
- Documentation/knowledge: refresh only versioned official-source dossiers that have real contract drift; maintain the machine-readable owner/status matrix.

Dependency-gated integrations:
- R04 capital-aware route selection requires amount-specific quotes/verified market state plus the relevant R-02 capacity and R-03 build contracts.
- R05 complete atomic simulation requires R04 candidates and provider-specific current state/build proof.
- R06 paper qualification requires existing QPR/campaign readiness PASS, exact simulation and durable replay.
- R07 provider implementation can be researched in parallel; a provider cannot be admitted into a qualified route until its own R-02/R-03/R-05 proofs pass.
- Supported application boot-path wiring must reuse canonical owners and preserve all runtime capability gates; perform only after explicit composition contract and dependency proof.

"Run all at once" means parallelize independent work packages, not merge every branch simultaneously or bypass the gates above.

## 2. Project end-to-end target

The intended research-to-paper pipeline is:

\`\`\`text
governed sources / RPC / streams
  → indexed discovery + event capture
  → canonical chain / mint / coin / pool identity
  → Dynamic Universe + ResearchEconomicGraph
  → exact market state + amount-specific venue quotes
  → UniversalArbitrageGraph + relation/correlation analysis
  → route search (direct / fragmented / synthetic / bounded cycles / LST / stable / wrappers)
  → FlashCapitalGraph (separate funding-resource dimension)
  → nonlinear amount sizing + all-in economic cost model
  → protocol-specific unsigned borrow / swap / repay plan
  → exact sender-free full transaction / PTB simulation
  → reconciliation + durable paper receipt + deterministic replay
  → qualification review and separately authorized promotion decision
\`\`\`

This is a target architecture, not a claim that the current supported runtime already wires every box end to end. Check current owners, dependencies and capability gates before every change.

### Preserve the maximum research universe

Research assets are not limited to assets a lender can flash-borrow. A route may borrow USDC/SOL/SUI and trade any verified target asset on its legs. Preserve Solana, Sui, TON, EVM and new chain research, stables, LSTs, BTC wrappers, long-tail assets, memes/event tokens, RWA references, cross-chain signals and CEX/oracle observations. Categorize sources by evidentiary role; do not let reference/signal data become an executable quote or local atomic route by implication.

## 3. Track ownership and work packages

### Track A — Solana market-data P0 (three independent agents)

**P0-1 — Safe indexed intake → Dynamic Universe**
- Extend existing \`src/solana_parallel_radar/\`, \`src/qualification_campaign/\`, \`src/discovery/dynamic_universe/\`, \`src/assets/resolution/\`, \`src/research_economic_graph/\`.
- Finish bounded source pagination/polling, quotas, partial snapshot safety, complete-snapshot lifecycle, mint/token-program/Token-2022 identity, alias/shared-liquidity groups, replay and coverage reports.
- DEX Screener, Raydium, Meteora, Manifest, Sanctum and any other source only when current schemas/access/limits are pinned. GeckoTerminal remains BLOCKED until current official schema/access contract is verified.
- Indexed rows stay DISCOVERY_ONLY. No fabricated 120–160 market target; measure coverage and budgets first.

**P0-2 — Jupiter Swap V2 + 0x comparable quote capture**
- Migrate the existing governed GPR-02 quote owner; do not add a parallel quote adapter.
- Pin current API contracts, credentials by secret reference, request/response schema, rate limits and errors.
- Same canonical mints, exact same base-unit input amount, explicit public-taker mode, freshness bounds, route-leg provenance and correlation groups.
- Do not invent a slot for providers that do not return one. Quote capture does not build, sign or send a transaction.

**P0-3 — Exact venue state**
- Retain \`src/providers/raydium_cpmm_native.py\` as canonical CPMM owner.
- Add Raydium CLMM and Meteora DLMM exact state only with complete dependencies (ticks/bitmap or bins/bitmap/oracle/fees), integer math and amount-specific depth.
- Orca remains BLOCKED_LICENSE_REVIEW until legal use is explicitly resolved. Do not copy or vendor restricted/custom licensed code.
- Indexed TVL, total vault balances and spot price never equal reachable executable depth.

P0-1/2/3 work may run in parallel after the lead publishes a shared identity/evidence contract. Their final data-plane integration is reviewed together.

### Track B — Flash-capital R-02 (four independent readers)

R-01 is COMPLETE (#584). R-02 remains BLOCKED based on #585: Jupiter admin and Kamino program account reads plus Sui checkpoint do not prove resource-level borrowing capacity; zero qualified edges; 27 catalog candidates disabled. #586's offline SDK source pack is merged.

- **R02-CAP-A Jupiter Lend:** TokenReserve PDA/layout; reserve, mint, vault, applicable borrower state and limits; current fee/rounding/effective borrow capacity at one rooted/finalized slot; independent provider proof.
- **R02-CAP-B Kamino:** full pinned Reserve and LendingMarket decode; last update/status; supply vault, mint/token program, fee scale/rounding, caps and actual flash eligibility. Prefix-only probe is not a full decoder.
- **R02-CAP-C NAVI:** modular SDK source; current deployed package/config/pool/shared objects; exact coin type/decimals/fee/cap at a real checkpoint via governed Sui gRPC/GraphQL. SDK API asset list is discovery, not on-chain capacity. No legacy Sui JSON-RPC fallback.
- **R02-CAP-D Project 0:** wallet-free bank discovery first; existing public authority/account is optional. Never create a Marginfi/P0 account or position. Bank capability and user eligibility must remain separate.

Every reader may return BLOCKED; never make a positive FlashCapitalEdge without resource-level capacity, fee, identity, freshness and independent provenance. R02 A/B/C/D may be developed concurrently in separate worktrees, but share RPC operator budgets and source governance.

### Track C — R-03 unsigned protocol builders

Freeze one shared contract first. Reuse \`FinancingEvidence\`, existing financing ports, \`UnsignedExecutionPlan\`/planner contracts, instruction firewall, Sui PTB validation and exact simulation owners.
- R03-A Jupiter borrow/payback unsigned instructions.
- R03-B Kamino borrow/repay with exact absolute instruction index and fee semantics.
- R03-C NAVI v1/v2 PTB with correct receipt/hot-potato discharge, coin type and object versions.
- R03-D Project 0 direct begin/end bracket, conditional on a pre-existing account and current SDK.
R03 offline work may proceed while R02 readers are blocked; build status must be separate from capacity status. No signer, sender, account setup or live capital admission.

### Track D — Graph, strategies and research intelligence

Audit and reuse:
- \`src/discovery/dynamic_universe/\` and \`src/assets/resolution/\` for canonical identities/lifecycle.
- \`src/research_economic_graph/\`, \`src/strategy/relation_generators/\`, \`src/strategy/arbitrage_graph.py\`, \`src/strategy/multihop_solver.py\` and existing correlation ledger for candidate topology, correlations and bounded cycles.
- Existing strategies and status matrix for circular arbitrage, LST depeg/unstake, liquidation, Pump migration, orderbook/AMM and future strategy families.

Research/implementation families:
1. Direct same-chain market arbitrage and venue fragmentation.
2. Direct vs synthetic/wrapped representation paths.
3. Bounded 2–5 hop cycles with exact per-amount re-quotes; topology alone is not an exact paper candidate.
4. Stablecoin triangles and depeg/residual recovery.
5. LST mint/redeem/unstake, exchange-rate/oracle residuals and pool fragmentation.
6. BTC wrapper / bridged representation differences.
7. Event/meme/new-token radar as discovery-only until exact token/pool checks pass.
8. Cross-chain basis, bridge-basis and CEX lead/lag as signal/research classes; do not describe them as local atomic flashloan routes.
9. Liquidation/funding/carry/oracle strategies only where protocol state, risk math and execution owners exist.

Keep research generation, exact execution feasibility, risk filters and after-cost ranking separate. Build deterministic replay datasets, explainable baselines and regime/lead-lag experiments. ML scores remain advisory until validated out-of-sample; no training leakage or synthetic success.

### Track E — Multichain and source expansion

- **Sui:** DeepBook, Cetus, Aftermath, Scallop, Bucket and additional DEX/lending sources; exact Move type, package IDs, object versions/digests, checkpoint, fee/capacity and PTB semantics. Sui intake research can proceed in parallel with NAVI R02, but market-state and lending-capacity evidence remain distinct.
- **TON:** preserve existing STON/Omniston radar and TON research graph; verify current APIs and market state. TON remains discovery/async until an atomic borrow→swap→repay primitive and contract semantics are proven.
- **EVM:** research Aave, Morpho, Balancer, DODO, Euler, Silo, Uniswap/Pancake flash mechanisms and concrete ERC-3156 lenders. A protocol model is not a deployed receiver/executor. Need per-chain deployment/ABI/code hash, callbacks, reserves, fees, gas and atomic repayment.
- **CEX:** public order-book/trade streams (e.g. Binance, Bybit, Coinbase) with snapshot/delta sequence, checksum, reconnect and gap recovery. CEX inventory/settlement is not a same-chain flashloan atomic route.
- **Oracles/reference:** Pyth and other approved feeds; DefiLlama, CoinGecko and analytics only as their contract/limits allow. Label REFERENCE_ONLY or SIGNAL_ONLY unless exact executable semantics are independently proven.
- **Source registry:** audit the 37-source market catalog and 27-provider financing catalog. Classify by family, evidence role, independence/correlation group, plan/credential/quota, license, current pin, implementation owner and enabled state. Do not enable every catalog row.

### Track F — R-04 to R-07 route qualification

**R04:** compare (route, settlement asset, lender resource, amount) combinations, refresh capacity, re-quote every amount, use PR118 nonlinear sizing and shared resource locks, include all-in costs.  
**R05:** complete unsigned transaction/PTB, exact account/object state, provider-specific borrow/repay ordering, fee rounding, compute/gas/rent/ATA/receiver costs and message binding; sender-free simulation only.  
**R06:** run the existing durable paper service only when QPR and campaign readiness gates return the required PASS. A 24-hour run is a measurement window, not profitability or production certification.  
**R07:** add one independent lender per PR from the 27-provider backlog; prove incremental capital resource and do not double count aggregators/wrappers. Research dossiers may be prepared concurrently.

### Track G — Runtime, platform, release and knowledge base

- Audit actual supported entrypoint from README, \`config/capabilities.json\`, \`src/resources/runtime_authority.json\` and active composition root before any boot-path edits.
- Runtime truth currently says safe sender-free disabled/shadow/paper boundaries; live is hard-denied, sender package quarantined, MarginFi/Kamino not production-qualified. Do not contradict this without accepted evidence PRs.
- Verify whether current Windows 11 checkout has WSL; prior P0 baseline found \`fcntl\` and \`os.getuid\` platform blockers and selected WSL-first, but local installation must be checked.
- Run full verifier, platform tests, package/wheel smoke, dependency/static/security gates and CI. Do not silently weaken hash pins, sockets-off tests or capability gates to make Windows/CI green.
- Keep offline docs versioned, licensed, hash-pinned and replayable. Do not turn the repo into a large unreviewed mirror of copyrighted sources.

## 4. Interface freeze and PR ownership policy

Before fan-out, the lead creates a short owner matrix with canonical files and interface boundaries. Example:
- Source intake: market discovery/radar/Dynamic Universe owners.
- Canonical identity: AssetResolver + chain readers.
- Quote: existing governed quote model and GPR-02 owner.
- Exact pool state: native CPMM owner plus CLMM/DLMM new sibling adapters.
- Lender capacity: FlashCapitalGraph reader contract and one protocol-specific implementation per PR.
- Unsigned build: one shared plan contract, then one protocol-specific builder.
- Route/sizing: UniversalArbitrageGraph + multihop solver + PR118 sizing.
- Simulation/paper: ExactSimulationFinalizer + existing paper lifecycle.
- Authority: QPR/DIN/campaign and unified runtime authority only.

Rules:
1. One canonical owner per responsibility. A worker may not create a parallel registry/graph/quote model/journal/authority because the existing owner is inconvenient.
2. No two agents edit the same canonical owner at once. If shared changes are needed, one agent owns the interface PR; others write tests/fixtures against the frozen contract.
3. Each worker starts from latest main in a separate worktree, fetches again before PR creation, rebases/merges only its own safe branch, and targets main.
4. Each PR is narrow, reviewable and includes a task ID, owner matrix, docs pins, tests, offline replay, status receipt and blockers. No giant agent dump.
5. Lead reviews overlaps, CI and evidence; only accepted PRs are merged. The lead does not auto-merge unfinished/failed tasks.

## 5. Global proof vocabulary

Use precise states: \`IN_MAIN_VERIFIED\`, \`IMPLEMENTED_UNQUALIFIED\`, \`OPEN_PR_NOT_IN_MAIN\`, \`IMPLEMENTED_UNBOUND\`, \`FIXTURE_ONLY\`, \`STUB\`, \`PLANNED\`, \`LIVE_READ_PROVEN\`, \`RPC_EXACT\`, \`BUILT_OFFLINE_UNQUALIFIED\`, \`SIMULATION_PASS\`, \`PAPER_QUALIFIED\`, \`BLOCKED\`, \`RETIRED\`.

Every PASS identifies exact commit/config/source generation, external source version, deployed program/package identity, raw evidence hashes, slot/checkpoint, test command/results and deterministic replay. Offline source hash verification is provenance, not live chain proof. HTTP 200 is not schema, market, quote or liquidity qualification.

## 6. Mandatory offline and repository verification

Run all current local source-pack verifiers before using vendored references:
\`\`\`bash
python docs/roadmap/r01-r02-live-capital-readers-2026-10-08/offline/verify_bundle.py
python docs/roadmap/r02-capacity-recovery-2026-10-08/offline/verify_offline.py
python docs/integrations/offline/solana-p0/verify_offline_bundle.py
\`\`\`
Run focused tests per owner with network sockets disabled; separately label bounded live capture tests. Finally run:
\`\`\`bash
python scripts/verify_repo.py
\`\`\`
Record real counts, skipped/deselected tests, platform and commit. Do not copy historical #585/#588/#589/P0-0 test totals as current results.

## 7. Safety and exit policy

Keep \`sign_enabled=false\`, \`send_enabled=false\`, \`live_enabled=false\`, all unqualified providers disabled. No wallet keys/seeds, account/ATA/obligation/position creation, signing, transaction submission, flash borrowing, spending, receiver deployment or production promotion. All transaction and PTB outputs remain unsigned/inert. Unknown costs, fees, deployed versions and capacities remain UNKNOWN. No env flag, fixture, model decision or agent token budget can bypass authority gates.

Project-wide research and offline implementation may proceed in parallel now. Live capital qualification, full route simulation, paper qualification and any production capability only move when their exact dependency gates pass.
