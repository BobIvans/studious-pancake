# Arbitrage Map — data-source integration assignments

Эти задания переводят стратегический каталог в конкретную программу подключения данных к существующему боту. Они расширяют P0/GPR/DV/R13/R02/R03 и не дублируют их.

## DS-00 — source audit, manifests and current entitlement truth
- Read ARBITRAGE_MAP_STRATEGY_AND_DATA_SOURCE_ATLAS_RU.md, ARBITRAGE_DATA_SOURCE_CATALOG_V1.json, current AGENTS.md, root/master trigger, P0 baseline, source ledger, P0/SX/MASTER crosswalk and all open PRs.
- For every endpoint/provider capture canonical docs URL, exact SDK/API version, retrieval UTC, git commit/blob or package integrity hash, license/data rights, auth, quotas/rate limits, request/response schema, units/decimals, timestamp semantics, freshness, historical retention, correction/reorg behavior, cost/plan expiry, failure modes and local parser fixtures.
- Classify provider as raw state, direct venue, quote router, oracle, CEX reference, lender, bridge/claim, indexer or analytics.
- Do not copy code under proprietary or custom license; mark BLOCKED_LICENSE and describe independent reimplementation only if permitted.
- Re-check changing endpoints/limits (current DefiLlama free-yield cutoff 2026-11-13, CoinGecko public limits and GeckoTerminal Pro access).
- Output a versioned source ledger and CI schema/provenance verifier; do not make a new source registry if one already owns this contract.

## DS-01 — chain raw intake and canonical state snapshots
- **Solana:** reuse current safe indexed intake/P0-1, official RPC/WebSocket, approved Yellowstone/Geyser (Triton Dragon's Mouth or another entitled provider) and existing Helius/Triton configs. Capture account owner/data, write version, transaction, slot status, parent, block time, fork/finality, gaps/reconnect/cursor.
- **Sui:** gRPC + GraphQL RPC + checkpoint/archive. Migrate all new code away from disabled mainnet JSON-RPC. Record checkpoint, object version/digest, owner/shared state and type/package.
- **EVM:** logs, state calls, traces, archive data and block hash/parent/finality on each chain; an indexer is not a substitute for coherent eth_call state.
- **TON/Cosmos:** retain current TON radar and Cosmos/Osmosis research. Implement data/indexing first; do not infer flash atomics from messaging/IBC semantics.
- Extend existing source journal and replay only. No duplicate chain DB.

## DS-02 — canonical asset / pool / book / representation identity
- Map the full 33 archived venue families and all current direct venue pilots.
- Use chain + canonical mint/coin/contract + token program/extension + issuer/underlying claim + pool ID / PoolId / market address / book sequence; do not join by ticker.
- For v4/hooked pools include hook address, permission bits, code hash and custom accounting model. For multi-token pools preserve vector state.
- For LST/LRT/vault/PT/bridge assets retain different redemption/claim/representation identities and right constraints.
- Preserve all 519/1,147/838/175 historical pair hypotheses as archive hypotheses; row-level archive materialization/PAIR-00 is not replaced by a summary list.

## DS-03 — direct venue state and exact quote engine coverage
- **Solana:** Orca Whirlpools, Raydium CPMM/CLMM, Meteora DLMM/DAMM/DBC, Manifest/Phoenix/OpenBook/PumpSwap. Use source-pinned SDK/IDL and exact tick/bin/book math; respect current Orca license/source gate.
- **Sui:** DeepBook V3, Cetus, Aftermath, Bluefin, Turbos and FlowX: current package IDs, full Move types, shared/owned objects and checkpoint. Separate orderbook vs pool.
- **EVM:** Uniswap V2/V3/V4, Curve pool variants, Balancer, Pancake V2/V3/Infinity, Aerodrome/Velodrome, LFJ, Pharaoh, Maverick, DODO, Sushi and chain-specific venues. Model each invariant separately; never route unverified v4 hook/CLMM/DLMM pool through CPMM.
- Special case: generic Balancer is withdrawal-only after BIP-928; individual V3 partner exceptions must be verified per pool and onchain until 2026-11-30. Exclude non-exception active swap markets.
- Every direct quote must be exact-in/out in base units, with full state generation, fee/rounding, input consumed, output, impact, price limit, transfer tax/hook, and negative/boundary fixtures.

## DS-04 — quote provider race and composable unsigned builds
- Reuse P0-2 Jupiter V2 + 0x baseline, frozen R13-K kernel and PR-647 Titan adapter. Add OpenOcean, OKX DEX, Rango and other providers only as one pinned adapter at a time.
- Sui: Aftermath, Cetus Aggregator, 7K/Bluefin7K, FlowX, OKX/Rango and direct DeepBook; distinguish quote-only from composable PTB commands.
- EVM: 0x, 1inch, Odos, ParaSwap, Kyber and CoW quote/order API; distinguish quote from intent/order from instruction/transaction.
- Preserve losing quotes, same base-unit amount, timestamps, raw hashes, taker/payer, fee schedule, route venues/pools and provider correlation group.
- Do not count two routers quoting the same underlying pool as independent markets. Re-quote every PR118 amount candidate; never scale snapshots linearly.
- A built transaction remains unsigned and provider-specific; R03/R05 own conformance and simulation.

## DS-05 — CEX / perps / market microstructure reference feeds
- Public feeds: Binance Spot WebSocket/REST; Coinbase Advanced Trade and Exchange WebSocket; Kraken WebSocket v2; OKX/Bybit public market data; Hyperliquid info/WebSocket; Drift and Jupiter Perps public market state where documented.
- Ingest L2 snapshots + incremental updates, sequence IDs, checksums where available, trades, product/contract metadata, tick/lot/price limits, funding, open interest, mark/index/oracle, liquidation and market status.
- Maintain clock skew and event-time/arrival-time; detect sequence gaps and resnapshot.
- Strategy classes: CEX↔DEX basis/lead-lag, spot-perp/futures funding, orderbook/market-making and inventory hedges. They stay SIGNAL_ONLY / HEDGED_NON_ATOMIC unless separately prefunded and risk-qualified; do not pretend a CEX book is a flashloan DEX leg.

## DS-06 — oracle, stablecoin, issuer and redemption state
- Oracle candidates: Pyth, Chainlink, Switchboard and other protocol-integrated feeds. Preserve confidence intervals, exponent/decimals, publish/update time, heartbeat/deviation, stale/invalid/paused status and market-hours metadata.
- Stablecoin / issuer: PSM and direct mint/redeem caps, min/max lots, fee, collateral status, caller allowlist, buffer balance, redemption delay and queue.
- LST/LRT/vault: exchange rate/index, total assets, maxRedeem/maxWithdraw, queue/cooldown, share math and caller-specific rights.
- Pendle: SY/PT/YT markets, maturity timestamp, market state and redemption semantics.
- Oracle/reference data is guard/anchor/trigger, not executable liquidity; independent source correlation must be explicit.

## DS-07 — lending, liquidation and flash-capital evidence
- Reuse R02 readers / R03 builders / FlashCapitalGraph. Expand only one protocol per provider evidence set.
- Solana: Project 0, Kamino, Jupiter Lend; MarginFi only per user priority and exact current bank/account constraints. Sui: NAVI, DeepBook V3, Scallop, Bucket flash mint/loan, Cetus/Suilend candidates. EVM: Aave V3, Morpho Blue, DODO, Uniswap V2 flash swaps, Balancer only per winddown/remaining active pool, and any ERC-3156 lender discovered in official source.
- Lending state: reserve/pool/vault, canonical mint/type, owner/package/deployment, fee/rounding, max amount, effective available capacity, pause/borrow flags, liabilities, caps, health/oracle requirements and coherent slot/checkpoint.
- Liquidation state: borrower debt/collateral, eligibility, close factor, bonus, keeper/caller permissions, oracle update and transaction budget.
- A protocol’s flashloan documentation or SDK method is not live capacity. Keep all unqualified providers disabled.

## DS-08 — bridges, cross-chain flow and external settlement
- CCTP, Wormhole, LayerZero/OFT, Stargate, Across, deBridge and native chain messaging where current official docs support them.
- Record source/destination chain, nonce/message/attestation ID, status, token representation mapping, fee, finality, delay/retry, replay protection, caps and liquidity.
- Use flows as local scan triggers, bridge-basis/rebalance data and inventory/risk constraints. A cross-chain message/transfer is asynchronous and cannot be placed inside a normal same-chain flashloan loop.
- Keep TON/Sui/EVM future chains in data-first mode until local chain execution/capital path independently qualified.

## DS-09 — launch, migration, pool events and long-tail discovery
- Pump.fun/PumpSwap and Solana token creation/migration; Meteora DBC/DAMM; Raydium pool migration; Sui new package/pool events; EVM factory/PoolManager/launchpad events.
- Discover new assets and pools, but run canonical identity, mint/authority/token extension, source trust, liquidity, anti-rug/negative tests and exact pool-state checks before adding execution candidates.
- Memecoin and event-universe scans remain radar/shadow-first; no automatic live enablement.

## DS-10 — indexers, analytics, historical corpora and market ecology
- The Graph Subgraphs/Substreams, protocol-specific official indexers, Dune, DefiLlama, CoinGecko/GeckoTerminal, provider archives and public chain explorers can enrich history/discovery and generate candidate lists.
- All analytics outputs must be reconciled to raw chain state and canonical pool identities before use in execution.
- Respect changed public API terms/quotas. As of 2026-11-13 DefiLlama free yield pools/chart endpoints require an API plan; CoinGecko public API is low-rate and GeckoTerminal on-chain data now uses Pro for higher-rate access.
- Reuse current MarketEpisode/raw journal/decision dataset, replay, participant intelligence and W6 ecology assignments. Keep missing history censored, not zero.

## DS-11 — unified strategy/source wire-up and coverage tests

For each canonical strategy row, produce a traceable row:
strategy_id -> discovery_source -> canonical_identity -> direct_state -> quote_source(s) -> capital_source (if local atomic) -> builder -> exact simulation -> paper consumer -> replay receipt.

- Add explicit no-trade and source-gap status. A provider outage or no quote is not an empty successful universe.
- Generate a coverage matrix that proves which strategies can receive data in the installed supported package and which remain library-only/blocked.
- Use existing R08 application composition, SX/EXP/W6 crosswalk, SX-01 StrategyContractV1, AGG-05 and R04/R05/R06. Do not make another registry, source plane, queue, graph or runtime.
- Preserve all existing pair/venue/source IDs; new sources get unique IDs and a reviewable source dossier.
- A PR can merge as an adapter/source research package while execution_permission=NONE; execution enablement is a separate evidence-gated change.

## Parallel agent split

Independent workers may research separate chains/providers in isolated worktrees, but:
- one owner for current P0-1 Solana intake;
- one owner for P0-2 Jupiter/0x quote baseline and shared quote schema;
- one owner for P0-3 exact DEX state;
- one owner per R02/R03 provider reader/builder;
- one coordinator for shared AssetResolver/DynamicUniverse/graph/FlashCapitalGraph/PR118/AGG-05 and source dashboards.

Freeze interface contracts before merging multiple adapters. The broad source map is not an instruction to implement every vendor in one PR.

## Completion criteria

The Strategy Pack is complete when every historical archive item and newly accepted source/strategy has: one stable ID, one canonical owner, primary source pins, strategy/execution class, chain and atomicity semantics, exact data requirements, license/quota/cost status, negative fixtures, dependency graph and a truthful status. The bot is wired only to the level demonstrated by code, installed package reachability and replay receipts.