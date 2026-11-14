# MASTER FLASHLOAN MARKET INTEGRATION + BUILD BIGGER UNIVERSE GRAPH
## Единое задание для Codex / coding agents — расширение исходного мастер-плана, а не замена

Repository: BobIvans/studious-pancake  
Primary mission: превратить накопленные market research, GPR, Dynamic Universe, direct DEX data, economic world graph, flash-capital sources и все strategy families в единый evidence-qualified flashloan / arbitrage research system с параллельной реализацией.

**Это продолжение первоначального MASTER FLASHLOAN MARKET INTEGRATION, а не отдельный урезанный strategy pack.** Сохраняй весь MASTER roadmap, PR ownership, P0 → Sui → CLOB → EVM → additional integrations. Новые архивные work packages дополняют этот план и должны быть сопоставлены с текущими owners; они не заменяют ранее назначенные задачи.

## 0. Единственный стартовый trigger

Ты — lead engineering orchestrator для BobIvans/studious-pancake. Выполни полный repo + archive + PR audit, затем реализуй весь незакрытый план через независимые, проверяемые work packages и PR.

### Прочитать до dispatch

1. AGENTS.md, root CODEX_START_HERE.md, docs/roadmap/agent-execution-master-2026-11-13/CODEX_START_HERE.md, MULTI_AGENT_EXECUTION_PLAN.md, PROJECT_KNOWLEDGE_BASE_MAP.md, TASK_INDEX.md.
2. docs/roadmap/STUDIOUS_PANCAKE_MASTER_CODEX_EXECUTION_2026-11-13/: CODEX_START_HERE.md, MASTER_EXECUTION_ROADMAP.md, CURRENT_REPO_OWNER_MAP.md, OWNER_INTERFACE_FREEZE.md, STRATEGY_UNIVERSE_ATLAS.md, STRATEGY_CROSSWALK.json, reports и existing task assignments.
3. This folder: MASTER_FLASHLOAN_MARKET_INTEGRATION_AND_BUILD_BIGGER_UNIVERSE_RU.md, BUILD_BIGGER_UNIVERSE_GRAPH_ARCHIVE_RECONCILIATION_RU.md, BUILD_BIGGER_UNIVERSE_GRAPH_WORKPACKAGES_V1.json, BUILD_BIGGER_UNIVERSE_GRAPH_ARCHIVE_MANIFEST_V1.json.
4. Strategy expansion: strategy gap analysis, catalog/execution classes, assignments, acceptance matrix, SX00 reconciliation and current strategy campaign.
5. R10 inventory/replay, R01–R14 handoffs, P0-1/2/3, GPR-01/02/03, R02 capacity, R03 builders, R04/05/06, R07/R08/R09/R10/R13/R14.
6. Current source code/tests for every proposed owner. Search latest merged PRs and open PRs first; read exact base/head diffs. Static archive statuses are historical, never current truth.

### Initial audit rule

Fetch the latest main SHA, latest branch protection/required checks where accessible, all open PRs, merged PR history, current worktree/branches and exact owner paths. Publish current-head truth before changing source. Do not dispatch from an old SHA or assume that a task in this document is still open.

At a prior verified snapshot:
- P0-1 #593, P0-2 #604, P0-3 #613 and R01 #584 were merged baselines.
- R02 CAP-A #602, CAP-B #612, CAP-C #609 and R03 #606 were merged as partial/offline readers/builders; effective live capital remained UNKNOWN.
- #614 added seven evidence-gated residual families; reuse its relation/correlation owners.
- #639 SX-00, #641 SX-01, #642 SX-09 and #643 SX-10/SX-11 were merged by the later audit. #645 SX-12 and #646 documentation expansion were open at the last checked snapshot.
These are historical checkpoints only. Re-fetch every PR before assigning or merging.

## 1. Preserve the original MASTER FLASHLOAN MARKET INTEGRATION scope

The master objective remains:

- Turn existing Web3 research, GPR, Dynamic Universe, direct DEX data, flash-capital graph and strategy families into a larger evidence-qualified flashloan arbitrage system.
- Reconcile every researched currency pair, asset identity, pool/market, strategy, economic relationship, lender and data provider against existing registries and canonical owners.
- Identify existing entries, genuinely new candidates, duplicates, stale IDs, missing pools, inaccessible sources, source-license/entitlement issues, blocked integrations and retired research.
- Maintain machine-readable pair delta, source coverage, strategy crosswalk, PR/dependency inventory and a truthful implementation/evidence status for each item.
- Preserve current owners. Do not create another asset registry, source catalog, market-state store, graph, journal, relation engine, solver, quote kernel, capital ledger, scheduler, simulation engine or release authority.
- For every market, prove actual market identity, pool/book ID, token order, pool version, state, executable depth, exact amount-in/output, fees, quote freshness and route compatibility.
- For every funding source, verify active deployment, actual available balance/capacity for this asset/amount, fee/premium, caller eligibility, callback/repayment semantics, caps and atomicity boundary.
- Simulate borrow + entire route + repay inside one transaction/PTB and one state generation before calling it locally atomic or paper qualified.
- Return actual PR links, changed files, tests, evidence receipts, current blockers and next dependency.

Keep the original high-level dependency progression: MASTER-00 → P0 market intake/state → Sui → CLOB → one EVM pilot → additional economic-market integrations. Do not rebuild P0-1/P0-2/P0-3/R01 baselines already merged; finish their residual qualification and connect their evidence to downstream work.

## 2. Build Bigger Universe Graph archive reconciliation

The 2026-10-03 to 2026-10-08 archive sequence is part of the project requirements:
- OCC_STRATEGY_MASTER (earlier user-idea and strategy source archive).
- Universal Market Graph R&D.
- Maximum Direct Data Graph.
- Maximum Direct Data Graph V3 and prior-chat strategy delta.
- Market Universe V3 and its high-value family/route additions.
- Economic World Graph V4 and Opportunity Atlas.
- Flashloan Source Expansion V4.1.
- Four-Document Deep Market Atlas V5.
- Flashloan Deep Pair Research V6.
- Direct Venue Audit and Dynamic Universe / Relation Generators / Correlation Ledger specification.

The machine-readable counts are historical versioned snapshots, NOT current active markets:
- V1/first graph: 519 symbolic pair seeds; 65-source catalog; 33 direct venue families; 17 lender/funding candidates.
- V3: 1,147 symbolic market candidates (693 previous + 454 new); 162 new high-value family seeds; 34 route templates; 86 source profiles; 14 direct family implementations with 22 source variants recorded as offline prototype/unqualified.
- V4: 838 symbolic pairs with canonical_count=0; plus 175 new symbolic pairs; world graph snapshot 2,998 nodes and 11,523 edges, all research-only with no execution permission.
- V6: another 175 new pair hypotheses; 12 conditional protocol hyperedges; 4 detailed flash-funding eligibility families and a 14-source budget/deprecation list.
- V3 prior-chat map: 25 distinct strategy mechanisms. V4 direct venue catalog: 33 families. V4.1/V6 add lender, route, protocol rights and atomicity refinements.

Never sum these version counts as unique markets. Keep original candidate IDs and archive provenance; preserve distinct chain representations and ticker collisions. Do not treat a pair hypothesis, official documentation, TVL, an indexed listing or an API route as a canonical market, live pool, executable quote or available flash capital.

## 3. Canonical Dynamic Universe / GPR architecture

Use existing code owners, extending gaps rather than creating parallel systems:
- Asset identity/resolution: src/assets/resolution and current seed registries.
- Dynamic Universe: src/discovery/dynamic_universe and existing ingestors/universe.
- Market state: MarketObservationV2, direct venue evidence, ShadowMarketGraphIngest and current QPR/DIN admission.
- Relationship generation: src/strategy/relation_generators.
- Heat and quota scheduler: the existing heat/ingestion scheduler.
- Correlation/residual learning: src/research/correlation_ledger and #614.
- Economic world / transformation relations: existing src/research_economic_graph, src/strategy_evolution and conditional-claim/rights owners.
- Exact arbitrage topology: UniversalArbitrageGraph, src/strategy/arbitrage_graph.py, multihop_solver and exact venue evaluator owners.
- Amount sizing: PR118 src/economics/non_monotonic_sizing.py.
- Joint split-flow/resource closure: src/economics/split_flow.py, cpmm_split_replay and shared state/resource owners.
- Flash funding: src/economics/flash_capital_graph and R02 reader owners.
- Quote race and pool dedup: R13-K src/execution/quote_build_kernel.py.
- Unsigned builders and transaction/PTB planning: R03 existing builder contracts and planner.
- Exact simulation/paper: existing sender-free simulator, qualification, replay and QPR/DIN owners.

Required entity model:
AssetIdentity (chain + canonical mint/full Move type/jetton master + token program/package + decimals + authorities/extensions + representation + verification/evidence generation);
EconomicAsset (underlying economic exposure, not assumed fungible with its representations);
Representation (native/wrapped/bridge/LST/LRT/yield-share/LP/NAV/event/RWA);
VenueIdentity (program/factory/deployment + version + market/pool/book + fee tier/hook);
MarketIdentity (exact ordered assets + underlying liquidity resource + state generation);
StructuralAnchor (issuer redemption, staking exchange rate, vault NAV, oracle/reference, funding/rate/maturity);
FlashCapitalEdge (chain/provider/asset/amount-specific effective capacity/fee/callback/constraints/observation/evidence);
TransportEdge (bridge/IBC/CCTP/USDT0/OFT/TON transfer; signal or inventory/rebalance only unless proven otherwise);
Transformation/ConditionalHyperedge (input/output vectors, rights, caller eligibility, fees, state postconditions, timing and atomicity class).

Identity states are versioned: UNRESOLVED → CANDIDATE → IDENTIFIER_VERIFIED → MARKET_VERIFIED → STATE_VERIFIED → QUOTE_VERIFIED → CAPITAL_VERIFIED → PAPER_QUALIFIED. A registry candidate or symbol does not jump stages. Preserve ambiguous candidates, rejected alternatives and negative evidence.

## 4. Relation generators and strategy graph

Implement/reconcile these bounded relation families using exact identities and provenance:
1. DIRECT_MARKET — exact live A/B pool or book.
2. VENUE_FRAGMENTATION — same A/B on distinct underlying pools; compare exact size-conditioned VWAP/fees/depth.
3. SYNTHETIC_CROSS — A/HUB/B through real legs; hubs include USDC, USDT, SOL, SUI and only where chain-local, TON/GRAM as research-domain hubs.
4. STRUCTURAL_PARITY — two proven distinct representations of the same underlying, with conversion and trust-root costs.
5. LST_FAIR_VALUE — DEX price vs protocol exchange rate and immediately executable exit; cooldown is not instant exit.
6. NAV_BASIS — LP/basket/vault/token market price vs live redeemable NAV.
7. STABLE_RESIDUAL — stable token vs issuer/redemption/market anchor; do not force all dollar units equal.
8. ORACLE_MARKET — external reference vs executable market; oracle itself is never an executable swap quote.
9. FLASH_CAPITAL — verified lender asset/capacity/fee/constraints linked to amount/route.
10. CROSS_CHAIN_BASIS — reference and rebalance cost, explicitly non-atomic.
11. BOUNDED_CYCLE — only exact verified directed edges, bounded 2–5 hops.
12. DIRECT_SYNTHETIC_RESIDUAL — direct A/B vs verified A/H/B route.
13. DEPTH_SHOCK / LIQUIDITY_CLIFF — exact consumed depth, ticks, bins, orderbook levels.
14. FLOW_TO_LOCAL_DISLOCATION — public CCTP/USDT0/OFT/bridge flow as event/heat trigger only; verify actual local state change and control windows.
15. MULTISURFACE_FAIR_VALUE — combine issuer anchor, oracle/reference, CEX reference, AMM size curve, CLOB VWAP and historic residual without treating sources as independent liquidity.
16. RATE/NAV/MATURITY — ERC-4626, staking, Pendle, rate provider and redemption surface with time/rights.
17. CAPITAL_VS_DEPTH — compare current lender capacity to exact local executable depth; do not use TVL.
18. ROUTE_TOPOLOGY_CHANGE — route/pool identity hash, state generation and alias changes.
19. PROTOCOL_STATE_REGIME — pause/freeze/authority/config/fee/upgrade/liquidity/migration transitions.

A ResearchRelation or symbolic route never becomes a DirectedQuoteEdge without current independent evidence. Do not materialize N×N global pair loops. Materialize evidence-backed local neighbors; use bounded SCC/DFS and explicit budgets.

## 5. The 25 archived prior-chat strategy families — preserve all

All 25 were explicitly RESEARCH_ONLY and execute=false in the V3 archive. Each must have an owner, exact source/state requirements and honest class/status:
1. Multi-DEX 2-hop fragmentation: independent pools, current exact state and independent RPC quorum.
2. Market 3–5-hop: closed same-chain routes using canonical multihop + PR118.
3. AMM vs CLOB: Phoenix/OpenBook vs Orca, DeepBook vs Cetus, Kuru vs Uniswap; full fill/IOC or explicit partial/revert semantics.
4. LST fair value: JitoSOL/JupSOL/INF/mSOL vs SOL; instantaneous exit only; exchange rate + fee + exit time.
5. SOL pool migration/bin shocks: PumpSwap/Raydium/Meteora bins; event-driven not assumed low-latency.
6. ERC-4626 vault NAV: sUSDe/USDe, sfrxUSD/frxUSD, mETH/cmETH; convert/preview/maxWithdraw and actual redeemability.
7. Pendle PT/YT near maturity: price/discount/expiry/exit; maturity payoff is not a flashloan exit.
8. Stablecoin PSM/mint/redeem: issuer, min lot, fees, caller permissions, asynchronous redemption classification.
9. RWA corporate-action/reference: only where not excluded by operator policy; no tokenized-equity execution, no issuer redemption assumptions.
10. Gold wrapper/reference: XAUT0/XAUm vs XAU reference; reference-only across domains unless an exact local pool exists.
11. BTC wrapper parity: cbBTC/WBTC/xBTC/tBTC/cirBTC/UBTC; issuer/bridge trust root and exact representation.
12. Interchain-flow-triggered local flash: bridge flow heats local market scan; no cross-chain atomic cycle.
13. Morpho zero-fee vs Aave premium: amount/state-specific source selection; Morpho singleton token balance and Aave reserve/premium.
14. EulerSwap lending-aware depth: exact SDK/vault/reserve state; no generalization to standard AMM.
15. Uniswap V4 flash accounting: PoolId/PoolKey/hooks and transient accounting; flash accounting is not proof of free external capital.
16. Balancer V3 flash accounting: Vault/hook/accounting and deployment-specific callback.
17. DODO DVM/DPP flash loan: exact active deployment, source callback, pool fees and repayment.
18. ERC-3156 generic lender: maxFlashLoan, flashFee and onFlashLoan, only verified implementations and callback security.
19. Ekubo/Starknet: Cairo state, exact math and atomic receipt; separate VM, no EVM ABI assumptions.
20. Prediction complete sets: complementary positions, split/merge, ERC1155 settlement and resolution rights.
21. CoW/intent/solver residual: signed intent, TTL, solver auction/permission, partial fills; mostly EVM non-atomic to other domains.
22. Lending looping/carry: multi-period supply/borrow yield with capital, rate, withdrawal and liquidation risk; not instant flash PnL.
23. Liquidations/OEV: protocol callback rights, eligibility, oracle update timing, keeper competition; separate qualified strategy lane.
24. CEX lead/lag: reference signal only unless separately permitted account/hedge execution is modeled.
25. Cross-chain rebalancing inventory: prefunded capital, queue/finality/bridge fee/stranding; not flash-circular.

Do not merge these into only ten EXP labels. The SX and EXP packages are extra implementation layers; this 25-family set remains part of the canonical strategy map.

## 6. Ten V4 economic-world intelligence extensions

Retain and assign measurable outcomes:
- Multisurface fair-value graph: issuer/reference + CEX mid + AMM amount curve + orderbook VWAP + oracle quality + historic basis.
- Liquidity-vs-capital imbalance: compare live lender capacity against executable depth and state changes per block.
- Rate/NAV knowledge: ERC-4626 convertToAssets/previewRedeem/maxWithdraw, LST rates and redemption cooldown.
- Maturity surface: PT maturity strip, spot market, yield curve and time-to-redemption; delayed maturity never becomes same-tx funding.
- Real market session/corporate-action calendars for permitted reference assets; exclude tokenized-equity trading and unauthorized issuer routes.
- Cross-issuer stablecoin peg: cluster by issuer, reserve, redemption and chain; do not assume USD par or identical risk.
- Multi-venue causal fragmentation: distinguish pool uniqueness from multiple aggregators and source correlation.
- Flow-to-local-dislocation: CCTP/USDT0/OFT/bridge flow followed by verified local reserve/price movement, with controls and no causal claim from correlation alone.
- Spot-vs-perp leading indicators: funding/open interest/book skew as signal; perp/spot hedge inventory remains a separate risk domain.
- Protocol-state regime switches: pause/freeze, dynamic fee, hook/config/upgrade, new pool, migration, collateral/supply and exit queues.

## 7. Direct venue coverage: 33 archived families

Treat these as target coverage inventory, not 33 currently active adapters:
1 Uniswap V2; 2 Uniswap V3; 3 Uniswap V4 Hooks; 4 Curve StableSwap/NG; 5 Balancer V2/V3; 6 PancakeSwap V2; 7 PancakeSwap V3; 8 Pancake Infinity; 9 Aerodrome/Velodrome; 10 LFJ Liquidity Book; 11 Pharaoh DLMM; 12 Kuru hybrid CLOB/AMM; 13 Kodiak/BEX; 14 Shadow/Metropolis; 15 Sushi; 16 Ekubo (Cairo/Starknet); 17 Orca Whirlpools; 18 Meteora DLMM; 19 Raydium CLMM; 20 Raydium CPMM; 21 Meteora DAMM/DBC; 22 Manifest; 23 Phoenix; 24 OpenBook; 25 PumpSwap; 26 DeepBook V3; 27 Cetus; 28 Aftermath Pools; 29 Bluefin AMM/CLOB; 30 Osmosis; 31 STON.fi; 32 DeDust; 33 Tonco.

Every family requires its own chain/deployment/program/version, source/license, market/pool/book identity, token order, fee model, exact quote algorithm and boundary tests. Examples: V2 integer reserves/fee; V3 sqrtPrice/tick bitmap; V4 per PoolKey/hook bytecode/permission bits/callbacks/custom accounting; Curve rates/metapools; Balancer Vault and rate providers; stable/volatile invariants; bin/CLMM crossing; CLOB sequence/lot/IOC/partial fills; Sui object/checkpoint and PTB. A venue name is never one generic quote formula.

## 8. Flash funding inventory: 17 historical candidate families

1 Morpho Blue; 2 Bend/Morpho fork; 3 Aave V3; 4 Yei; 5 Project 0; 6 Kamino; 7 Marginfi; 8 Scallop; 9 NAVI; 10 DeepBook; 11 Cetus; 12 Suilend; 13 Ekubo; 14 Uniswap V2 flash swap; 15 Balancer Vault; 16 Osmosis (no verified lender in the archive); 17 TON (no general atomic flash assumption).

This is a research candidate inventory, not a provider enablement list. User priority remains Project 0 + Kamino on Solana and NAVI/DeepBook/Sui candidates where qualified; do not require account creation or paid account setup for optional providers. Marginfi is not a default and must remain deprioritized/blocked unless its security/economic/user gate is resolved. EVM sources require exact deployment, callback, live token balance/reserve, fee, caller and same-domain simulation. Morpho singleton balance is not the same as Vault deposits. DEX flash swap/flash accounting is not identical to a generic lender. A route may borrow a hub asset without the target pair asset itself being flash-loanable, but exact route, fees and repayment must still close.

## 9. Original GPR packages — execute or reconcile one by one

- GPR-01A Canonical Asset Resolver: versioned per-chain identity state machine, startup verification, provenance, ambiguity and negative evidence.
- GPR-01B Dynamic Universe Ingestors: live asset/venue registries and pool/book discovery; Solana, Sui; TON read-only lane.
- GPR-02A Relation Generators: direct, venue, synthetic, structural/LST/NAV/stable/oracle/cross-chain and bounded cycle relations.
- GPR-02B Dynamic Heat Scheduler: HOT/WARM/COLD/EVENT, budget-aware; heat schedules observation only, not permission.
- GPR-03 Correlation Ledger: residual features, lead/lag windows, regime persistence, time alignment, source correlation and replay.
- GPR-04 FlashCapitalGraph: Project 0/Kamino; NAVI/DeepBook/Scallop and future qualified sources; amount-specific capacity, fee, constraints and evidence.
- GPR-05 Read-only campaign: run real-data read-only qualification, measure ambiguity, false positives, source aliasing, exact quotes, data/RPC cost, negative evidence and paper readiness.
- TON-RADAR-01: STON/DeDust/Tonco/Omniston discovery/quotes as an isolated async research domain; no inherited Solana/Sui atomicity.

These are original tasks from the earlier GPR assignment. Crosswalk them to current owners and status; do not create a new GPR runtime.

## 10. Direct venue audit / implementation tasks DV-00…DV-08

- DV-00 Capability truth: actual implementation vs docs/fixture/offline/qualified; no status by PR title.
- DV-01 Solana Raydium CPMM: pinned program/layout, pool/vault/token identities, rooted state quorum, exact math, fee and amount vectors.
- DV-02 Solana Orca/Meteora/Raydium CLMM/DLMM: complete tick/bin arrays, dynamic fee, Token-2022, partial-consumed input and exact evaluator binding.
- DV-03 Solana CLOB: populated Manifest/Phoenix/OpenBook markets, sequence/depth/lot/IOC/partial-fill and shared-liquidity identities.
- DV-04 Sui: gRPC/GraphQL/Core, DeepBook/Cetus/Aftermath object versions/checkpoints, exact state and PTB dry-run; same-pool funding/trade contention.
- DV-05 First EVM pilot: select ONE chain after read-only discovery; V2/V3/Curve exact reads plus Morpho/Aave effective balance; callback/fork simulation and verified chain/deployment ID.
- DV-06 Complex EVM: Balancer, Aerodrome/Velodrome, Pancake V2/V3/Infinity, Uniswap V4 and other hooks as separate conformance tasks; no generic V3 math fallback.
- DV-07 Observer-only domains: Osmosis and TON readers; protocol limits/license/rate/backoff and async settlement classification.
- DV-08 Read-only qualification campaign: fixed 24/72-hour observed workloads; pool identity, amount quotes, capacity reads, complete route simulation/paper receipts, net costs, freshness, RPC cost and false positives.

P0-1/P0-2/P0-3 already merged are the base for DV-01/02; do not open duplicate implementations. Focus on remaining graph/evaluator/paper integration and residual proofs.

## 11. Original sequential PR program F-00…F-11 and V6 F6-00…F6-08

F-00 compatibility audit and official SDK/version/source/license snapshot.
F-01 Solana direct quotes: Orca, Meteora, Raydium; stable and LST pilots.
F-02 Solana CLOB: Manifest, Phoenix, OpenBook; depth and lot math.
F-03 Sui gRPC/GraphQL + DeepBook/Cetus exact quotes and same-checkpoint replay.
F-04 Sui DeepBook/native PTB flash capacity; verify hot-potato borrow/return, shared pool impact and dry-run.
F-05 EVM V2/V3/Curve + Morpho/Aave, one chosen chain and real token balance, exact quote, block-pinned simulation.
F-06 additional EVM venue/funding adapters only after pilot; include Balancer, Aerodrome, Pancake and source-specific flash providers.
F-07 source/identity expansion and market families; no guessed addresses or registry-only identity.
F-08 EVM V4/Infinity/Velodrome/Balancer SDK gaps, hook allowlist and exact custom fee simulation.
F-09 structural NAV: LST/LRT/Pendle/ERC-4626; classify delayed redemption/maturity non-atomic.
F-10 Cosmos Osmosis and TON STON/DeDust radar, read-only and async.
F-11 72h paper campaign, source ablation, exact net PnL/costs, false positives and regression; no signing or broadcast.

V6 follow-up:
- F6-00 source admission, duplicate/provenance and stale registry/deprecation audit.
- F6-01 Sui AUSD/WAL/NS full Move identity, DeepBook pool/object proof and exact quote.
- F6-02 Frax/USUAL/Curve savings-vault operations and conversion rights.
- F6-03 Euro FX / EUR0 / EURe / EURC exact local pools; FX oracle is reference only.
- F6-04 Solana dynamic LST registry and valuation anchors; refresh stale Sanctum sources.
- F6-05 funding eligibility and amount/constraint quotes; no capacity from docs.
- F6-06 Pendle market inventory/PT/YT/SY maturity and exit; no waiting-to-maturity flash route.
- F6-07 cross-chain/issuer lag correlation with no-flow controls; no causal claim.
- F6-08 replay/qualification with positive, negative, stale, partial and rejected evidence.

## 12. Original 19 route templates — discovery hypotheses only

Keep the archived route IDs and validate every leg:
1 Solana USDC→USDG→USDT→USDC.
2 Solana USDC→SOL→JitoSOL→USDC.
3 Solana USDC→SOL→JupSOL→USDC.
4 Sui USDC→SUI→DEEP→USDC.
5 Sui USDC→wUSDT→sbUSDT→USDC.
6 Ethereum USDC→USD0→USDC (Curve vs Uniswap).
7 Ethereum USD0→bUSD0→USD0 (venue A vs B).
8 Plasma USDT0→USDe→USDT0 (Fluid vs Curve).
9 HyperEVM USDC→USDT0→WHYPE→USDC.
10 Monad USDC→WETH→MON→USDC.
11 Monad USDC→cbBTC→WBTC→MON→USDC.
12 X Layer USDC→USDG→USDT0→USDC.
13 Ink USDT0→USDG→kBTC→USDT0.
14 Arc USDC→WETH→cirBTC→USDC.
15 Mantle WETH→mETH→cmETH→WETH.
16 Unichain USDC→HYPE→USDC (v3 vs v4).
17 Avalanche USDC→WAVAX→WETH→USDC.
18 Sei USDC→USDT0→WSEI→USDC.
19 Berachain USDC.e→BUSD→WBERA→USDC.e.

Any route can be removed as stale/non-existent without losing the research hypothesis; preserve its original ID and negative evidence. Never hardcode old candidate routes as live execution plans.

## 13. Economic-world graph / conditional hyperedges

V4 contains 2,998 nodes and 11,523 archived symbolic relations, all research-only. V6 documents 12 conditional protocol hyperedges, including:
- USUAL USD0 ↔ bUSD0 + rt-bUSD0 split, then combine/early-exit (conditional rights).
- USUAL EURC → EUR0 swap buffer; may be T+0 with buffer or T+1..T+5, never assume atomic.
- USUAL sUSD0/sEUR0 ERC-4626 share redemption.
- FRAX frxUSD direct redeem-only route to USDC with caller/maxRedeem/USTB liquidity checks.
- FRAX sfrxUSD → frxUSD.
- Curve scrvUSD → crvUSD.
- Ethena sUSDe cooldown exit (days, reference/non-atomic).
- Pendle PT-USDG time-locked maturity.
- CCTP cross-chain USDC transfer.
- USDT0 OFT cross-chain transfer.

Preserve input/output asset vectors, conversion rates, fee/rights, eligibility, delays, settlement class, and resource locks. Use existing economic graph/rights/conditional-claim owners; don't flatten hyperedges into arbitrary pair edges or treat a conversion formula as permission.

## 14. Additional evidence/strategy topics discovered in V3/V4/V6

- PSM/issuer and redemption windows; issuer-specific buffers and min lots.
- ERC-4626 vault rates, share ownership, preview/redeem/withdraw caps and fees.
- Pendle PT/YT/SY maturity surface; PT before maturity is a market sale, not par redemption.
- Stablecoin cross-issuer, cross-chain and representation-basis clusters; USDC native/bridged, USDT0, wUSDC, USDG, PYUSD, USD1, USDe, USDS, EURC, EUR0, EURe, USD0, USDT.
- LST/LRT/restaking and instant exit vs queue; delayed unstake is non-atomic.
- BTC wrapper trust-root, bridge and issuer parity; symbols do not imply fungibility.
- Gold/XAU reference (XAUm, XAUT0) as reference-only unless local executable pools verified.
- Multitoken Balancer/Curve/Aftermath pools: generated directed pairs share one resource; avoid reserve double-use.
- Oracle/rate-provider staleness and pool dynamic fee changes.
- CLOB/AMM full-fill/partial-fill/cancel/IOC semantics.
- Interchain flow triggers for local-market scans; control groups required.
- Funding regime crossover: source selection changes with exact capacity, fee, gas, route, account/ALT/packet/writable limits.
- Protocol invariant/anomaly/market regime change; source lifecycle and deprecation.

## 15. Source plane, quota and entitlement requirements

The archive lists 65 sources initially and 86 source profiles in V3, plus a V6 budget/deprecation delta. Treat those counts as snapshots, not a current approved source list. Maintain one source-profile owner and record:
- official source URL, documentation/revision/commit/hash, license and redistribution terms;
- endpoint role (registry, indexer, reference, quote candidate, state reader, exact verifier, builder, flash funding);
- public/authenticated/paid access, operator/account, rate limits and quota units, 429 Retry-After/backoff;
- source freshness, schema version/drift, cursor/pagination, coverage and blind windows;
- correlated operator/data/pool lineage; two APIs on one operator or same pool are not independent;
- cost/RPC budget, failure and negative evidence, ToS and user data rights.

Discovery tier priorities: no/low-cost public registry and batch indexers first; higher-rate providers for candidates; aggregator/quote APIs only for exact amount candidates; independent RPC/gRPC/GraphQL state verification last. Current official docs and limits must be re-verified before coding; old free/quota claims expire.

## 16. Parallel implementation and dependency graph

One coordinator owns MASTER-00, final crosswalk, task DAG, shared interface freeze and status dashboard. Other workers operate in isolated worktrees, one bounded task and one PR each. 4–8 workers is a soft target only where repo/runner limits allow; never create two concurrent owners for one shared path.

Recommended lanes after the current-main audit:
- Worker A: GPR-01A resolver/state machine and archive identity/duplicate policy.
- Worker B: GPR-01B low-cost Solana/Sui ingestors and source freshness/deprecation fixes.
- Worker C: GPR-02A relation families / exact resource provenance.
- Worker D: GPR-02B heat/quota scheduler and negative evidence.
- Worker E: GPR-03 correlation residual/lead-lag and replay.
- Worker F: GPR-04 Project0/Kamino/Sui capital eligibility using R02; live capacity user-gated.
- Worker G: direct venue DV lane, starting with the next unowned exact evaluator or CLOB subscription task; coordinate P0-3/R07 owners.
- Worker H: one EVM pilot source/state/flash proof, only after current-main review and no shared-owner overlap.
TON-RADAR-01 is a separate research-only worktree. GPR-05 is coordinated by the lead after the read-only data plane is stable. SX/EXP/W6 work runs in parallel only where no overlap exists.

Shared files and owners (strategies.py, capabilities, Dynamic Universe interfaces, AssetResolver, graph, quote kernel, FlashCapitalGraph, scheduler, exact simulation, status/dashboard, format/verify manifests) must have one serialized integrator. Do not stack workers on obsolete base commits. Rebase before PR review.

Dependency edges:
MASTER-00 → owner/interface map → GPR-01A/01B → GPR-02A/02B → GPR-03 + GPR-04 → exact MarketObservation/venue evaluators → bounded cycles/PR118/split-flow → R04 selector → R05 unsigned transaction/PTB build + same-state simulation → R06 paper qualification. GPR-05 read-only campaign consumes the verified stages. EVM expansion is a separate gated path after one EVM pilot; TON remains separate asynchronous research.

## 17. Global invariants and user constraints

- Solana and Sui are the first two local-atomic domains; no more than one additional EVM chain pilot in the first expansion wave. Expand to other chains only after measured capability and ownership.
- Project 0 and Kamino are the Solana priority funding paths. NAVI/DeepBook and other Sui providers are evaluated through their own live state/protocol semantics. Marginfi is not mandatory and not a default; do not create accounts or require paid account setup.
- No Robinhood Stock Tokens, tokenized equities or xStocks trading. Historical market seeds containing them must be marked EXCLUDED and preserved only as source-history, not executable candidates.
- No private keys, wallet/account/ATA/obligation/position creation, signing, broadcasting, submission, borrowing, spending, deployment, provider activation, live trading or production promotion.
- No sandwich, frontrun, user-targeting or unauthorized private orderflow. Permitted backrun research follows #643's policy gate only.
- Bridges/CCTP/OFT/IBC/TON async, CEX settlement, delayed withdrawals/unstaking, Pendle maturity and multi-period funding are non-atomic inventory/reference/signal strategies unless exact same-transaction closure is proven.
- UNKNOWN is not zero. TVL, listed assets, source claims, API routes, doc-described primitives, SDK availability and offline instruction builds are not live capacity.
- Every amount requires fresh exact quote; never scale a quote or infer profit from marginal rate.
- Pool aliasing, shared lender balances, shared collateral, bins/ticks, CLOB depth, account locks and quotas cannot be double-counted.

## 18. PR acceptance and completion

Every PR:
- one owner/task, current base/head SHA, current ancestry and changed-path overlap audit;
- source URL, pinned revision/commit/blob hash, schema/IDL/ABI, license/ToS and retrieved date;
- chain/deployment identity and exact asset/market/pool/resource identity;
- falsifiable hypothesis, null/control, execution/settlement class and explicit rights;
- exact same-generation state, exact amount quote, fees, available capital, callback/repayment and all-in cost;
- positive, negative, stale, ambiguous, partial, rejected and no-trade fixtures; replayable evidence hashes;
- tests actually run, skipped/not-run explained, type/format/security/CI result; no historical test counts passed off as current;
- blocker IDs, rollback, next dependency and PR URL.

Definition of complete: every archive family/market/source/strategy has a truthful owner and disposition; selected work is merged or evidence-backed BLOCKED/RESEARCH_ONLY/EXCLUDED; market discovery feeds the supported shadow graph without bypassing verification; strategy candidates reach the existing paper pipeline when gates pass; shared-resource parallel portfolio scheduling is deterministic; final crosswalk/dashboard matches latest main. A merged strategy heading or symbolic pair list is not implementation, profitability or production readiness.

## 19. Owner-authorized autonomous engineering scope

The repository owner explicitly grants the coding agent autonomous repository-engineering authority for this defined Studious Pancake campaign, including implementation, review, creation and merge of its in-scope PRs. The user's direct instruction in the ChatGPT conversation on 2026-11-14 (requesting full agent authority to execute and merge) is the explicit human approval required by AGENTS.md rule 11 for this campaign. This delegated approval is limited to the strategy / Build Bigger Universe / flashloan engineering assignments and PRs produced by them; it is not a blanket approval for unrelated PRs or external financial actions:
- Read the complete repository, source, tests, history, PR diffs, archived ZIP lineage and current project documentation; search official protocol documentation and source repositories.
- Perform source/version/license/entitlement research, inspect SDK/IDL/ABI/deployments, and update the knowledge base and machine-readable crosswalk.
- Create isolated branches/worktrees, write and refactor production/research code, tests, fixtures, docs and bounded CI tooling; run local tests, type/format/security/repository checks.
- Split work across independent agents/worktrees where the execution environment supports it, coordinate shared owners, create focused PRs, rebase to current main, resolve conflicts in its own PR branches and continue independent work when another lane is blocked.
- Merge its own PRs only after the current required checks are green, tests and source/license evidence are reviewed, there are no unresolved owner overlaps/conflicts, the PR is mergeable and branch protection permits the merge. It may not bypass required checks, fake statuses or force-push main.
- Maintain a current PR/task/evidence ledger and keep working through all unblocked work packages rather than stopping after writing assignments.

This grants broad repository engineering autonomy, **not unrestricted infrastructure or financial authority**. It does not grant access to secrets/private keys, creation or use of wallets/accounts/ATAs/obligations/positions, signing, broadcasting, submitting, borrowing, spending, deploying, provider activation, live market interaction, QPR/DIN override or production promotion. Use only already-approved read-only sources and public evidence. When a credential, paid access, operator approval, private account address or user authorization is required, report the exact missing item as BLOCKED and continue independent work.

No agent may enable live capabilities by editing environment flags, config, feature flags or CI policy. A coding agent may prepare unsigned plans and sender-free simulations only under the existing project's authorization/evidence gates. Production/live execution remains a separate explicit operator decision after paper qualification and all security/economic gates.


### 2.1 Exact relationship data recovered from original embedded input

The first graph ZIP's embedded \`inputs/03__Вставленный текст(20261006-034611).txt\` has been parsed into a machine-readable archival dataset:
- \`BUILD_BIGGER_UNIVERSE_GRAPH_ARCHIVE_CANDIDATES_2026-10-06.json.gz\`
- SHA-256 of the decompressed JSON: \`8f8d958d9d45636c8275d8fcbd13273a8eeb60a1da65b7efdfcca903ebcd5467\`
- SHA-256 of the gzip payload: \`6dbcb44fdb9ec74b623836f055978628ed865b756edf9d43dc85ddca74489aee\`

Dataset rows: 83 consolidated Solana relationships (#1–83), 14 documented triangular routes, 12 Sui relationships (#205–216), all 100 new relationships (#225–324), and 4 unnumbered dynamic EVENT patterns. Source refs, original anomaly class, historical tier and abbreviated mint candidates are preserved. All rows default to HISTORICAL_DISCOVERY_ONLY / execution_permission=NONE.

Important integrity issue: although the source title says relationships #1–224, the embedded input contains only 83 consolidated Solana rows plus Sui #205–216; TON #185–204 is intentionally excluded, and #217–224 are absent. No missing IDs are invented. #293 is a methodology/detector row, not an asset pair; #249/#270/#282 and other rows include basket/NAV/event watches, not necessarily pools. The agent must preserve these distinctions.

To inspect locally:
\`\`\`powershell
python -c "import gzip,pathlib; p=pathlib.Path('docs/strategy-expansion/2026-11-14/BUILD_BIGGER_UNIVERSE_GRAPH_ARCHIVE_CANDIDATES_2026-10-06.json.gz'); pathlib.Path(str(p)[:-3]).write_bytes(gzip.decompress(p.read_bytes()))"
\`\`\`
The resulting JSON is a historical seed list, not an authoritative registry. Re-resolve all canonical mints/types, current market/pool/book identity, state, exact quotes and capacity before promotion. Historical HOT/WARM/RSRCH/EVENT labels are not current heat scores.



## 21. Broad arbitrage strategy and data-source integration map

The broad strategy atlas is now paired with an explicit data-source map. Read these canonical addenda:
- ARBITRAGE_MAP_STRATEGY_AND_DATA_SOURCE_ATLAS_RU.md
- ARBITRAGE_DATA_SOURCE_CATALOG_V1.json
- ARBITRAGE_MAP_DATA_SOURCE_ASSIGNMENTS_RU.md
- CODEX_ARBITRAGE_MAP_START_HERE.md

They map the existing 25 STRAT families, 33 direct venues, 17 flash funding candidates, 19 route templates, 64 V3 anomaly IDs, 25 V4 detectors, 36 V6 route hypotheses and 12 conditional hyperedges to source roles and integration requirements. DS-00…DS-11 extends the same work already assigned under P0/GPR/DV/R02/R03/R13/R10/SX/EXP/W6.

The data layers are deliberately separate: raw chain intake, protocol decoder, direct pool/book state, aggregator quote/build, lending capacity, oracle reference, CEX/perps market data, indexer/analytics, bridge/claim status and market-episode outcomes. A quote router is not an independent pool; a CEX quote is not on-chain settlement; a bridge is not same-transaction liquidity; an oracle is not tradable depth.

**Current external-source caveats:** BIP-928 moved most Balancer pools to withdrawals-only on 2026-10-30, with only explicit partner-requested V3 exceptions potentially active until 2026-11-30. DefiLlama's free yield pool/chart endpoints ended on 2026-11-13. CoinGecko public rate limits are low and GeckoTerminal higher-rate DEX data now requires Pro. Sui mainnet JSON-RPC is disabled; use gRPC/GraphQL/checkpoints. Refresh these conditions before adapter work.

The goal is maximum research breadth and correct source wiring, not a ticker-only list. Every strategy must traverse the current canonical AssetResolver/DynamicUniverse → graph/relation → exact state/quote → financing/capital → unsigned builder → PR118/cost reconciliation → R04/R05 → paper/replay owners. SIGNAL_ONLY and HEDGED_NON_ATOMIC lanes remain useful but must not be mislabelled as flashloan-circular.
