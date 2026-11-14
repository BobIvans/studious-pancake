# Arbitrage Map Atlas — стратегии, источники данных и интеграционные assignments

**Repository:** BobIvans/studious-pancake  
**Snapshot reviewed:** 2026-11-14, main 9f173d7632cb30190bb8d9174ceba6d116eaec70  
**Purpose:** дать coding agents максимально полную, но технически классифицированную карту arbitrage research и источников, чтобы подключать стратегии к существующему боту. Это расширение текущего Strategy Pack и MASTER/GPR/DV/R/F/F6, а не новая архитектура.

## 0. Главный принцип: карта возможностей ≠ разрешённый маршрут

Для каждой стратегии нужно отдельно доказать уровни:
1. DISCOVERED — источник сообщает, что актив/market/pool потенциально существует.
2. IDENTITY_VERIFIED — canonical chain + mint/coin/contract + representation + venue + pool/book identity подтверждены.
3. STATE_VERIFIED — точное состояние pool/book/reserve/claim/queue прочитано на согласованном slot/block/checkpoint.
4. QUOTE_VERIFIED — exact input amount, output, fee, impact, transfer/hook effects и freshness подтверждены.
5. CAPITAL_VERIFIED — конкретный flash provider/resource доказывает доступную сумму, fee, ограничения и same-transaction semantics.
6. BUILD_VERIFIED — protocol-conformant unsigned transaction/PTB/instruction sequence собран.
7. SIMULATION_VERIFIED — полная атомарная последовательность симулирована на согласованном state.
8. PAPER_QUALIFIED — существующий paper lifecycle накопил воспроизводимые receipts при пройденных campaign gates.
9. LIVE_AUTHORIZED — отдельная явная человеческая authority; не создаётся от документации, теста или paper PnL.

Ticker, TVL, subgraph row, token list, aggregator route, SDK example, test fixture или наличие adapter-класса не доказывают следующий уровень. UNKNOWN не равно нулю. Список рынка/strategy family не равен возможности совершить прибыльную сделку.

## 1. Что уже покрывает Strategy Pack — не переписывать

Использовать существующие IDs и source archives:
- 25 historical STRAT-01…25 families, 33 direct venue families и 17 flash-funding candidates в BUILD_BIGGER_UNIVERSE_GRAPH_WORKPACKAGES_V1.json.
- 19 V3 route families; 64 V3 anomaly classes; 25 V4 detector templates; 36 V6 route hypotheses; 12 V6 conditional hyperedges; 4 V6 flash-funding primitive families — ARCHIVE_DETECTOR_TAXONOMY_CROSSWALK_V1.json (#654).
- GPR-01A…05, DV-00…08, original F-00…11 and V6 F6-00…08.
- EXP-01…10: residual opportunities; DBC/DAMM migration; CLMM/DLMM cliff; Token-2022 fees/hooks; liquidation forecasts; invariant anomaly; opportunity survival/crowding; intent/RFQ/CoW pilot; spot-perp/funding basis; Uniswap v4 hooks.
- SX-00…16 research/strategy lanes, R10-A…I, W6-00…11, S01–S07, OP/WG families.
- R02/R03/R04/R05/R06 and R13 quote/build work.
- #646 recovered original MASTER + Build Bigger Universe archive; #647 added Titan on frozen R13 kernel; #650 recovered exact archived pair/relationship seeds; #654 reconciled detector/anomaly/route taxonomy.

These are the research coverage baseline. Agents must reconcile each row to existing code, tests, source dossier and supported boot path; do not create a second catalog or duplicate archived IDs.

## 2. Full opportunity map — classify by economic/settlement class

### A. Same-chain atomic swap arbitrage

Best candidates for a flashloan-first route when the lender and all legs fit in one transaction/PTB:

- Cross-DEX two-leg: same canonical asset bought/sold across distinct underlying pools or a pool and a CLOB.
- Stablecoin triangle / bounded cycle; same chain, exact assets and exact per-leg amount quotes.
- Three-to-five-hop cycles; use exact sequential outputs and non-monotonic amount sizing, never multiplied mid-prices.
- Direct-vs-synthetic path; compare a direct market against a composed route with the same final canonical representation.
- Split-flow optimum; distribute exact input across independent venues where liquidity and settlement are independently proven.
- AMM-vs-CLOB and CLOB-vs-CLOB: full-fill/partial-fill, IOC/FOK, queue and settlement semantics are explicit; displayed depth is not guaranteed execution.
- Multi-pool and multi-token routes: Balancer/Curve/weighted/vault pools are one vector state/resource, not independent pairs.
- Route topology flips, aggregator path differences, shared-liquidity alias and router alias: discovery hypotheses only until underlying pool/book lineage proves independence.
- Lender-selection crossover: choose provider/asset/amount by current same-state capacity, fee, transaction limits, account setup and cost.
- Pool-specific custom accounting / fee paths: Uniswap v4 hooks, Pancake Infinity hooks, dynamic fees, transfer-fee tokens and other exact protocol math.
- DEX flash swap / pool-integrated flash liquidity where the pool contract provides a documented callback/repayment primitive.

### B. State and liquidity microstructure strategies

- CLMM tick-boundary and initialized-tick/bitmap liquidity cliffs.
- DLMM active-bin transitions, bin liquidity cliffs, bin-step and dynamic fee changes.
- Dynamic fee regime / fee-tier crossover.
- JIT LP, LVR, adverse selection, inventory skew and LP range lifecycle. These usually require inventory/LP rights and are not automatically flashloan arbitrage.
- CLOB spread, book imbalance, queue priority, IOC/FOK fill probability, maker rebates and partial-fill risk.
- AMM/CLOB hybrid markets and shared orderbook/AMM inventory.
- Own-transaction post-confirmation residual/leftover opportunities and opportunity-survival timing.
- Pool migration, launch curve graduation and migration-induced state reset.
- Hook-specific custom accounting, hook permission/bytecode and before/after-swap callbacks.

Use EXP-01…10 and SX-05/SX-06/SX-09/SX-10/SX-15 owners. LVR, queue advantage and auction/MEV ideas are research/market-structure classes, not permission to sandwich, frontrun, use private order flow or target another trader.

### C. Stablecoin, wrapper and redemption / rights strategies

- Stablecoin triangles and local PSM/mint/redeem windows.
- Issuer redemption, minting, buffer/queue/allowance/eligibility constraints.
- LST / LRT NAV and relative-value: protocol exchange rates, instant DEX exit, unbonding queues and redemption caps are different edge types.
- BTC wrapper parity: cbBTC/WBTC/xBTC/LBTC/stBTC and bridge/issuer representation identities must remain distinct.
- ERC-4626 vault-share NAV: totalAssets, convertToAssets, previewRedeem, maxRedeem, maxWithdraw, user limits and actual underlying liquidity.
- Pendle PT/YT: PT maturity, YT accrued yield, pre-maturity market sale and maturity redemption are different settlement classes.
- Morpho vault in-kind exit, vault share rates, redemption limits and withdrawal queues.
- Prediction-market complete sets / conditional claims / split-merge / resolution: outcome vectors and rights are hyperedges, not plain token swaps.
- Token-2022 transfer fees, withheld amounts, transfer hooks and authority/epoch changes.
- USUAL split/combine, USDB/BUCK flash mint, Ethena cooldown, EUR0 buffer, sUSDe/sfrxUSD/scrvUSD/other redeem paths only with exact caller-rights and queue state.

These can be atomic only when the actual protocol operation is immediate, permissionless for the caller, same-transaction composable and state proven. Otherwise classify CONDITIONAL_HYPEREDGE, HEDGED_NON_ATOMIC or SIGNAL_ONLY.

### D. Lending, liquidation, credit and oracle opportunities

- Atomic liquidation financed by a qualified flash provider, if target account eligibility, debt/collateral, oracle, close factor, bonus, keeper rights and exact seize/swap/repay sequence are proven.
- Liquidation cascade forecasts and bad-debt / collateral migration monitoring (monitor-only unless keeper route is independently qualified).
- OEV/SVR/oracle auction and permitted keeper participation; not generic stale-oracle exploitation.
- Lending-rate spread, refinance and cross-venue collateral migration; usually multi-period carry/interest-rate strategy, not one-transaction flash PnL.
- Interest-rate curve changes, utilization, borrow/supply asymmetry and withdrawal/debt ceilings.
- Flash capacity crossover: provider asset coverage, effective cap, current fee, rounding, gas/rent/ATA/coin-object costs and resource contention.
- Flash mint vs flash loan selection: mint/burn semantics, issuer rights, protocol fee, caps and supply/burn postconditions.

Relevant owners: FlashCapitalGraph, R02 readers, R03 unsigned builders, SX-02/SX-04/SX-08/SX-12, EXP-05, R04/R05.

### E. Launch, migration and event-driven strategies

- Pump.fun bonding curve and PumpSwap graduation/migration.
- Meteora DBC → DAMM and Raydium/Meteora post-migration pool identity.
- Liquidity seeding, pool initialization, bin/tick distribution changes, token mint/authority/Token-2022 extensions and first-market discovery.
- New pool and market launch radar; pair/identity verification; source coverage and event time.
- Memecoin/event tokens and long-tail markets as radar/research first, not automatically live execution.
- Protocol upgrades, pool/hook/fee changes, oracle configuration changes and invariant anomalies.

All new-asset routes require canonical mint/coin identity, freeze/mint authorities, transfer restrictions, token program/version, exact venue state, supported quote/build path and negative/rug/risk tests. Radar is not execution authorization.

### F. Auction, intent, RFQ and solver strategies

- CoW batch auction / solver competition and surplus residual.
- RFQ and quote streaming; quote TTL, signer/taker, partial-fill and settlement semantics.
- JupiterZ/RFQ vs on-chain router routes; distinguish opaque order, signed intent and executable instructions.
- UniswapX / Dutch-order / intent settlement and solver competition.
- Blockspace / permitted backrun economics and own-order execution; model builder/validator payments and inclusion probability.
- Auction fee/allocation mechanism research and MEV internalization where permissioned.

A solver quote or auction result is not necessarily composable with a flashloan. Validate order rights, TTL, signature, allowed taker/solver, callback/settlement and partial fill.

### G. External-reference, derivatives and inventory strategies

- CEX↔DEX price basis and lead/lag.
- Spot↔perpetual/futures basis, mark/index/oracle dislocation and funding-rate regime.
- Perp liquidation cascades, open interest, funding, insurance fund and market-depth signals.
- Options/volatility or maturity basis when a venue's public market data and hedging support exist.
- Cross-chain flow-triggered local market scan; bridge inflow/outflow, CCTP, OFT, sequencer and finality changes are signals.
- Bridge/chain basis and rebalancing inventory; prefunded capital, finality, bridge limits and stranded inventory make this non-atomic.
- Funding/carry and inventory market making; capital lock, hedge venue, borrow cost, inventory and drawdown dominate.

These are SIGNAL_ONLY or HEDGED_NON_ATOMIC unless separately prefunded and risk-qualified. A flash loan cannot be held across a CEX settlement, bridge finality or funding interval.

### H. Public participant / market ecology intelligence

Public protocol activity and market episodes can reveal recurring strategy archetypes: arbitrage, LP lifecycle, liquidation/repay, market making, borrow/refinance, launch/migration, solver/auction and cross-venue inventory. Reuse MarketEpisode, raw journal, episode_builder, decision dataset, causal replay and W6-01…11. Preserve failed/reverted/no-fill attempts, transfer vs PnL, inventory/liabilities, fees/costs and censored histories. Public chain IDs remain pseudonymous technical identifiers; no real-world identity resolution, doxxing, private orderflow or automatic wallet-copy trading. Model outputs are hypotheses requiring independent quote/state/capacity/simulation evidence.

## 3. Data-source architecture — roles and order of trust

Use separate source planes:
1. Raw chain state / realtime feeds: chain RPC, WebSocket, Yellowstone/Geyser, Sui gRPC, checkpoints, EVM RPC/logs/traces.
2. Protocol state decoders: official program/contract/package SDK, IDL/ABI, generated types and versioned layouts.
3. Direct venue state: pool reserves, ticks, bitmaps, bins, active liquidity, orderbook levels, queue sequence, hook state, vault state, multi-token balances.
4. Quote / route services: amount-specific quotes, routes and instruction builders. They are comparison/route providers, not independent pool liquidity.
5. Lending / flash-capital state: lender banks/reserves/vault/pools, fee/caps/availability/borrow limits/repayment semantics.
6. Oracle / reference prices: Chainlink/Pyth/Switchboard and protocol oracle state. Record update time, confidence, heartbeat/deviation and decimals.
7. CEX / derivatives feeds: public WebSocket orderbooks, trades, funding, open interest, mark/index, liquidation events. Signal/hedged inventory only.
8. Indexers / analytics / discovery: The Graph/Substreams, Dune/DefiLlama/CoinGecko/GeckoTerminal etc. Discovery/backfill/analytics only unless reconciled to raw canonical chain state.
9. Bridge / issuer / claim sources: protocol message/attestation state, redemption queue, maxRedeem/maxWithdraw, rate and caller permission.
10. Market episode / outcome sources: public on-chain transaction/event histories, protocol events, CEX public fills/books and our own shadow/paper receipts.

### Trust and source independence rules

- An aggregator and its underlying DEX pool are correlated views, not independent liquidity.
- Two indexers indexing the same chain event stream are not independent confirmations by themselves.
- Group evidence by operator, RPC backend, upstream indexer, quote engine and underlying pool.
- Preserve source timestamp, arrival timestamp, slot/block/checkpoint, parent/finality, write-version/sequence, correction/retraction, gap and reconnect markers.
- Processed slot is not final; do not combine state from incompatible slots or object versions in one route.
- Preserve raw response/account/object hashes and local replay fixtures.
- Version, license, API auth, quotas, retention, commercial limits and costs are part of the technical contract.
- A source list is not a live subscription. Prove connection, freshness, gap-detection and installed-application consumption.

## 4. Chain and data-source matrix

| Chain / domain | Raw / index source | Direct state / market | Aggregator / quote / event | Main strategy use |
|---|---|---|---|---|
| Solana | Official RPC/WebSocket; Solana Geyser; Yellowstone/Dragon's Mouth; existing Helius/Triton configs | Orca Whirlpools, Raydium CPMM/CLMM, Meteora DLMM/DAMM/DBC, Manifest, Phoenix, OpenBook, PumpSwap | Jupiter Swap API V2, 0x Solana, Titan, OpenOcean, OKX DEX, Rango; Helius event/index endpoints | 2–5 hop, CLOB/AMM, LST/stables, migration, liquidations, capital |
| Sui | Official gRPC, GraphQL RPC, checkpoint store/archive, custom indexer | DeepBook V3, Cetus, Aftermath, Bluefin, Turbos, FlowX | Aftermath/Cetus aggregator, 7K, OKX DEX, Rango | USDC/SUI hub cycles, BTC wrappers, LST, CLOB/CLMM, NAVI/DeepBook flash paths |
| EVM | Archive/full-node RPC, WebSocket logs, traces, own Substreams/Subgraph/Firehose index | Uniswap V2/V3/V4, Curve, Balancer (status caveat below), Pancake V2/V3/Infinity, Aerodrome/Velodrome, LFJ, Pharaoh, Maverick, DODO, Sushi, Camelot/Ramses and chain-specific AMMs | 0x, 1inch, Odos, ParaSwap, Kyber, CoW API, Uniswap routing/quote surfaces | Stable/FX, PT/YT, vault NAV, multi-token pools, flash loans, liquidations, intent/solver |
| TON | Official TON nodes/APIs and indexed events; keep current local TON radar sources | STON.fi, DeDust, Tonco | Protocol API / indexer discovery; no generic atomic flashloans assumed | Radar and event/data layer; do not assume same-transaction flashloan arbitrage |
| Cosmos / Osmosis | Full node, indexer, events, IBC packet/finality evidence | Osmosis pools and orderbook/route modules where deployed | Osmosis route/query endpoints | Research and chain-local atomicity only when proven; IBC flows are delayed signal |
| CEX / Perps | Public REST + WebSocket feeds and sequence-aware books | Binance, Coinbase, Kraken, OKX, Bybit, Hyperliquid, Drift/Jupiter Perps where available | Venue-specific market-data endpoints | CEX lead/lag, spot-perp basis, funding, market making; not flashloan legs |

### Official documentation starting references

These official primary references were checked during the 2026-11-14 research pass. Agents must pin exact revision, API generation, license and request schema into local source dossiers; a URL is not a pinned SDK.

- Solana Geyser plugin interface: https://github.com/solana-labs/solana/blob/master/docs/src/validator/geyser.md
- Solana account WebSocket subscription: https://solana.com/docs/rpc/websocket/accountsubscribe
- Triton Yellowstone / Dragon's Mouth streaming: https://www.triton.one/chains/solana
- Sui data access methods: https://docs.sui.io/develop/accessing-data/
- Sui GraphQL RPC and JSON-RPC migration: https://www.docs.sui.io/develop/accessing-data/graphql/graphql-rpc
- Jupiter Swap API V2 overview: https://github.com/jup-ag/docs/blob/main/swap/index.mdx
- 0x Solana Swap API: https://docs.0x.org/solana/solana-swap-api/introduction
- 0x Solana instruction endpoint: https://docs.0x.org/api-reference/solana-swap-ap-is/swap/instructions
- Orca Whirlpools SDK: https://orca-so.github.io/whirlpools/ts/
- DeepBook V3 flash loans: https://www.docs.sui.io/onchain-finance/deepbook/deepbookv3-sdk/flash-loans
- NAVI flash loans: https://sdk.naviprotocol.io/lending/flashloan
- Bucket SDK technical resources: https://docs.bucketprotocol.io/developer-and-security/technical-resources
- Project 0 flash loans: https://docs.marginfi.com/guides/flashloans
- Aave V3 flash loans: https://www.aave.com/docs/aave-v3/guides/flash-loans
- Morpho Blue flash loans: https://docs.morpho.org/learn/concepts/flashloans/
- DODO flash loans: https://docs.dodoex.io/en/developer/contracts/dodo-v1-v2/guides/flash-loan
- ERC-3156 standard: https://eips.ethereum.org/EIPS/eip-3156
- Uniswap v4 hooks: https://developers.uniswap.org/docs/get-started/concepts/hooks
- Uniswap subgraphs v2/v3/v4: https://developers.uniswap.org/docs/ecosystem/subgraphs/overview
- PancakeSwap Infinity developer overview: https://developer.pancakeswap.finance/contracts/infinity/overview
- Balancer winddown BIP-928: https://forum.balancer.fi/t/bip-928-orderly-winddown-of-balancer-and-distribution-of-the-treasury/7107
- Chainlink Data Feeds and freshness: https://docs.chain.link/data-feeds/overview
- Pyth API: https://docs.pyth.network/api-reference
- The Graph Substreams: https://thegraph.com/docs/en/substreams/overview/
- CoW Protocol API: https://docs.cow.fi/cow-protocol/integrate/api
- Binance public market data: https://github.com/binance/binance-spot-api-docs
- Coinbase Advanced Trade WebSocket: https://help.coinbase.com/en/developer-platform/websocket-feeds/advanced-trade
- Hyperliquid info API: https://hyperliquid.gitbook.io/Hyperliquid-docs/for-developers/api/info-endpoint
- DefiLlama API: https://api-docs.defillama.com/
- CoinGecko public API limits: https://support.coingecko.com/articles/5125303456-what-is-the-rate-limit-for-coingecko-api-public-plan

## 5. Current source-status caveats discovered

### Balancer — do not treat as an ordinary active venue

Balancer governance approved BIP-928. Most pools moved to withdrawals-only on 2026-10-30; qualifying partner-requested V3 pools may remain live until 2026-11-30, after which the V3 Vault is paused. Therefore:
- Mark generic Balancer V1/V2/most V3 pools WITHDRAWALS_ONLY / not active arbitrage venues.
- Permit an explicit per-pool exception only if it is on the official partner extension list and current on-chain swap state confirms it is active.
- Keep withdraw/exit/recovery monitoring as a separate risk/ops task.
- Do not use historic Balancer volume, TVL or subgraph records as proof of current swap availability.

### DefiLlama / CoinGecko — API entitlement drift

- DefiLlama's free yield /pools and /chart/{pool} endpoints stopped on 2026-11-13; same data now requires API plan at /yields/v1/pools and /yields/v1/chart/{pool}. Other free endpoints may remain usable; verify each endpoint independently.
- CoinGecko public API limit is documented as 5–15 calls/minute depending on global load; GeckoTerminal on-chain DEX data is now accessible through CoinGecko Pro for higher-rate usage.
- These services remain useful for discovery and historical research, not direct live execution state.

### Sui transport

Sui Foundation mainnet JSON-RPC has been disabled; new integrations must use gRPC / GraphQL RPC and archival/indexing services. Do not add a JSON-RPC fallback to new Sui readers/builders.

### CEX feeds

CEX WebSocket books and trades are venue-specific, sequenced external observations. They can be lead/lag, basis, hedge or market-making signals. They are not atomic on-chain swap legs, and a public market-data feed says nothing about the bot's authenticated execution account or available inventory.

## 6. Required strategy ↔ data dependencies

| Strategy family | Minimum data required | Critical failure/blocker |
|---|---|---|
| 2-hop / 3–5-hop cycles | Canonical identities, direct pool/book state, exact amount quotes for every leg, independent resource lineage, flash capacity | stale/mixed state, quote scaling, same-pool alias, missing repayment |
| Split-flow / direct-vs-synthetic | Exact per-venue quotes at each candidate amount, shared-liquidity graph | double-counting pools and nonlinear slippage |
| AMM↔CLOB / CLOB↔CLOB | L2 order book, sequence, market lot/tick, IOC/FOK/partial-fill, fees and settlement | displayed depth is not guaranteed fill |
| Stable triangle / PSM | Pool state, issuer/PSM cap, min lot, fee, rate, caller rights | redemption pause/queue, offchain eligibility |
| LST/LRT NAV | Onchain rate/index, DEX quotes, queue/capacity, redemption rights, cooldown | fair value not immediately redeemable |
| BTC wrapper parity | exact representation identity, bridge/issuer trust, venue state, redemption rights | wrappers not fungible, non-atomic bridge risk |
| ERC-4626/vault NAV | convert/preview/maxRedeem/maxWithdraw, vault assets and user limits, exact token quote | max exit is user-specific, preview is not capacity across holders |
| Pendle PT/YT | market expiry, SY/PT/YT rates, implied yield, pool state, redemption rules | maturity and cooldown are delayed claims |
| Liquidation/OEV | borrower positions, collateral/debt, oracle price + timestamp, close factor/bonus, keeper/auction rights, flash capital | no keeper rights, stale oracle, capacity or same-tx constraints |
| JIT/LVR / market-making | exact tick/bin/book state, trade flow, inventory, fees/rebates, fill probability | inventory/adverse selection; not free flash PnL |
| Launch/migration | program events, mint authorities/extensions, DBC/curve state, migration destination, new pool state | identity collisions, malicious token, no exact post-migration pool |
| Intent/RFQ/CoW | quote stream, signed order semantics, TTL, solver auction, partial fills, settlement and fee | quote ≠ instruction; no guarantee selected/filled |
| CEX lead/lag / perps basis | sequenced books/trades, mark/index/oracle, funding/OI, latency and inventory | hedged/non-atomic, funding/custody/transfer risk |
| Cross-chain flow/rebalance | bridge message/attestation, finality, chain state, inventory, transfer limits | asynchronous; not a single flashloan transaction |
| Participant learning | public transaction episodes, realized + unrealized position, fees/transfers/liabilities, failed attempts and censoring | survivorship, missing history, false attribution |

## 7. Broad universe tiers — preserve discovery, focus compute not research

Keep the research universe broad. Separate:
- DISCOVERY_UNIVERSE: all canonical assets, pools, venues, claims, protocol events and source profiles under research.
- CANDIDATE_UNIVERSE: canonical identities and direct markets that pass basic risk/quality filters.
- HOT_UNIVERSE: rolling markets with fresh state/quotes and active strategy demand. A rolling 120–160 hot pair target is an optional scheduling/compute heuristic, not a maximum research universe or fixed cap.
- EXECUTION_UNIVERSE: only same-chain/same-transaction routes whose identity, state, quote, capital, builder, simulation and admission gates all pass.
- REFERENCE_UNIVERSE: CEX/oracle/bridge/macro/other-chain feeds used to prioritize a local scan or hedge; cannot be silently inserted as local atomic liquidity.

Every asset record keeps chain, canonical mint/coin/contract, representation kind, underlying claim/issuer, decimals, token program/extensions, freeze/mint authorities and source provenance. Do not deduplicate by ticker or symbol.

## 8. Definition of complete strategy wiring

A strategy row is only WIRED_SHADOW when:
- discovery trigger is connected to a live or explicitly replay-labelled source;
- identity resolver, direct state and exact quote owners are connected;
- execution class and dependencies are explicit;
- flash-capital reader and builder are attached when it is local atomic;
- exact amount sizing and full route simulation use the same state generation;
- existing application/strategy consumer receives the candidate;
- resource conflicts use the existing AGG-05 / portfolio owner;
- paper/shadow receipts record no-trade/negative/rejected outcomes;
- installed package/capability manifest contains the strategy;
- deterministic replay and tests prove the path is reachable.

Otherwise use LIBRARY_ONLY, RESEARCH_ONLY, SIGNAL_ONLY, FIXTURE_ONLY, BLOCKED_SOURCE, BLOCKED_CAPACITY, BLOCKED_BUILDER, BLOCKED_SIMULATION or NOT_IN_RUNTIME. No agent may flip a family to READY because code compiles.

## 9. Reference implementation owners to reuse

- Asset identity + universe: AssetResolver, DynamicUniverse, canonical mint/coin/contract identities.
- Market state / observation / replay: src/market/observations.py, src/market/streams.py, src/agg02/, src/market_data_evolution/.
- Graph / candidate topology: src/strategy/arbitrage_graph.py, src/strategy/multihop_solver.py, existing relation_generators, ResearchEconomicGraph, FlashCapitalGraph.
- Direct venues: src/direct_venue/, existing Raydium/Meteora exact decoders and CPMM/CLMM math; Orca stays behind its current license/source gate.
- Quote/build: frozen R13-K kernel, src/solana_parallel_radar/, src/gpr_sui_shadow/, existing QuoteProvider / TransactionBuilder contracts and PR-647 Titan adapter.
- Capital: R02 readers, provider catalog, FlashCapitalGraph, R03 financing ports.
- Sizing/economics: PR118 nonlinear sizing, fee/rent/transfer-tax/hook ledger, existing cost selector.
- Conflict/resource scheduling: AGG-05 src/strategy/conflict_scheduler.py; SX-12 portfolio optimizer after its merge.
- Strategy contract: SX-01 StrategyContractV1; do not add a parallel schema.
- Simulation / paper: ExactSimulationFinalizer, atomic planner, QPR/DIN, existing sender-free paper lifecycle and campaign readiness gates.

## 10. Final rule

Maximize breadth of research, markets, venues, data sources and strategy hypotheses. Minimize duplicate architecture and unsafe execution assumptions. The bot should explain why every strategy fired, why every route was rejected, which exact state and source produced the estimate, what capacity and costs were available, and whether the path is research, shadow, paper-qualified or separately authorized.