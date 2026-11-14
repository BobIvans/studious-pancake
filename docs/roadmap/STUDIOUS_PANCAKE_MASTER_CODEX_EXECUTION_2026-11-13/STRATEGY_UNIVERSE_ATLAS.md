# Broad strategy universe — what was explored, what exists, what remains

This is a crosswalk, not an assertion that the strategies are executable. Use the companion JSON to map each family to canonical source owners and missing proof.

## A. Core local arbitrage
1. Two-leg exact market arbitrage across independent venues.
2. Venue fragmentation, route overlap and aggregator quote discrepancy, with underlying pool de-duplication.
3. Bounded 2–5 hop cycles; exact amount-specific quote for every leg and every candidate size.
4. Direct vs synthetic/wrapped paths and stablecoin triangles.
5. Liquidity-fragmented route graphs and non-linear capacity/size windows.
**Repo:** `src/strategy/relation_generators/`, `src/strategy/arbitrage_graph.py`, `src/strategy/multihop_solver.py`, `src/economics/non_monotonic_sizing.py`, `src/strategy/strategies.py`. Current circular detector is two-leg; multihop solver returns a shortlist until exact evaluation.

## B. Stablecoin and issuer economics
6. USD stable peg deviations, same-chain triangles, cross-venue residuals.
7. Issuer PSM, mint/burn, redemption and buffer-liquidity paths.
8. USDT0 local market triangles where bridge flow is signal only.
9. EUR0/EURC/FX same-unit or cross-currency residuals.
10. USD0/bUSD0/rt-bUSD0 split/combine and maturity rights; sUSD0/sEUR0 share conversions; FRAX/frxUSD/sfrxUSD exits where maxRedeem/allowance/issuer eligibility/USTB liquidity is proven.
**Repo:** `src/strategies/stable_peg/`, relation generators, `src/strategy_evolution/rights_lifecycle.py`, `primary_market.py`, existing hyperedge/economic graph concepts. Missing: protocol/issuer rights, current maturity, exit fees/caps and same-transaction proof. Not every redemption is atomic.

## C. Staking, LST/LRT and NAV
11. SOL vs JitoSOL/JupSOL/mSOL/INF/BNSOL/hSOL and Sui afSUI/haSUI/vSUI/scaSUI/sSUI.
12. HYPE/kHYPE/vkHYPE, ETH mETH/cmETH/wstETH/cbETH and other share relationships.
13. Instant exit vs queued/cooldown/epoch redemption, slashing/validator state, basket NAV, share exchange rate vs spot pool residual.
**Repo:** Sanctum ingestor/Dynamic Universe, `src/strategy_evolution/stake_queue.py`, relation generators. Existing LST strategy classes in `src/strategy/strategies.py` are shells/disabled. Need current issuer semantics and exact exitability.

## D. Wrappers, bridge and cross-chain
14. BTC representation parity (cbBTC/WBTC/xBTC/tBTC/cirBTC/kBTC/bridged wrappers).
15. USDT0 OFT, CCTP, Wormhole and IBC flow-driven local imbalance.
16. Cross-chain inventory/rebalance spread, settlement delay and risk.
**Repo:** AssetResolver identity/origin/bridge fields, Dynamic Universe, CorrelationLedger, interchain relation seeds, R09 data feeds. Bridge and async multi-chain transfer is NOT a local atomic flashloan leg. A bridge may be a lead/lag feature only.

## E. CLOB / AMM / microstructure
17. Phoenix, OpenBook V2, Manifest, DeepBook and Kuru orderbook vs AMM cross-venue.
18. Depth/imbalance/VWAP, maker/taker and IOC, price-time priority, tick/lot, sequence/checksum/gap recovery, fill probability and adverse selection.
19. Raydium CLMM, Orca Whirlpools, Meteora DLMM, Uniswap V3/V4, Pancake Infinity, Aerodrome Slipstream custom fee/hooks and active tick/bin state.
**Repo:** `src/providers/orderbook/`, `src/direct_venue/mpr2617.py`, `super03.py`, `src/direct_venue/cpmm_math.py`, native Raydium CPMM owner, market graph ingress. Orderbook/AMM strategy is disabled until verified subscriptions. Full depth/quote/atomic composition remains unqualified in many venues.

## F. Vault, yield and maturity
20. ERC-4626 vault NAV/share price, previewRedeem/maxRedeem/maxWithdraw, withdrawal queues and fee changes.
21. Pendle PT/YT, maturity basis, implied yield and pre-maturity unwind vs face value on maturity.
22. Stable/yield spread (USDe/sUSDe, USDY, sUSDai, sfrxUSD/frxUSD, scrvUSD/crvUSD) with different units and time horizons.
**Repo:** strategy evolution `primary_market.py`, `rights_lifecycle.py`, `incentive_epoch.py`; exact route needs current contract state and rights. Delayed maturity/cooldown is not immediate settlement.

## G. Lending, credit and capital events
23. Liquidation windows, health factor and oracle/state transitions.
24. Lending utilization/capacity changes, flash capital fee/capacity pivots and provider selection.
25. Funding, basis/carry, rate regime and cross-protocol collateral/liquidity stress.
**Repo:** `src/liquidation/`, `src/lending_indexer/`, `src/economics/flash_capital_graph/`, `src/strategy_evolution/solvency_event.py`, `incentive_epoch.py`. Liquidation strategy is shadow-only. Funding/carry across time is a separate economic PnL family, not instant-flash profit.

## H. Events, governance and blockspace
26. New market/token launch, migration, liquidity graduation/retention, dynamic fee/bin and event-window anomaly.
27. Governance votes/proposals, incentive emissions, epochs, queue changes, staking rights and primary-market lifecycle.
28. Blockspace/priority fee/tip/MEV opportunity costs and congestion option.
29. Intent/solver/RFQ residuals and quote TTL / private flow where permitted.
**Repo:** Pump migration shell, `src/strategy_evolution/governance_transition.py`, `incentive_epoch.py`, `blockspace_option.py`, `intent_rescue.py`, `residual_discovery.py`, `primary_market.py`. Mostly research-only; require event source freshness and rights proof.

## I. Reference-only and excluded
30. CEX-DEX lead/lag, orderbook and trade-flow correlation; oracle-vs-DEX residuals; FX/gold, macro/session and RWA corporate-action signals.
31. Cross-chain bridge issuance/flow analytics, token unlock schedules and external reference NAVs.
These are reference/signal features, not executable pool edges unless a separate exact same-domain market leg exists. Robinhood Stock Tokens and tokenized equities are explicitly excluded by user policy.

## Strategy research protocol
Each candidate needs: hypothesis and null; economic relation type; canonical identities; chain-locality/atomic class; exact market dependencies; source owner; amount/size grid; capacity; fees and all-in costs; rights/cooldown/maturity; route conflicts/correlation groups; failure modes; time-aware train/holdout plan; replay; false-positive and no-trade metrics. An anomaly or ML score cannot bypass identity, market, capital or simulation gates.
