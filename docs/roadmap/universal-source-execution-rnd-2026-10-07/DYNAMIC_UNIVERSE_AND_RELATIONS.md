# Dynamic Universe + Relationship Generators

## Do not hardcode the maximum universe

Target:
- ~80–100 economic assets initially
- ~120–160 chain representations
- ~150–200 structural templates
- hundreds of live direct markets
- thousands of bounded 3–5 hop candidates
- only ~30–40 HOT expensive-verification relations at a time

## Live registry ingestion

### Solana
- Sanctum all-LST registry
- Manifest live markets
- Raydium pools
- Meteora pools
- Orca pools
- Jupiter/Titan/0x route metadata
- Token/RWA/event registries

### Sui
- DeepBook current pool registry
- Cetus aggregator provider/market universe
- Aftermath supported coins/routes
- 7K / Bluefin7K providers
- FlowX providers
- NAVI flash assets
- Scallop supported assets
- Bluefin markets

### TON
- STON all assets
- STON all pools
- Omniston routes
- swap.coffee routes/pools
- DeDust markets
- Tonco
- chain truth

## Generator A — Direct market

If a real pool/book/route exists:
`DIRECT_MARKET(A,B)`

## Generator B — Synthetic cross

If:
- A/HUB exists
- B/HUB exists

materialize:
`A/B_SYNTHETIC_VIA_HUB`

Hubs:
- Solana: SOL, USDC, USDT
- Sui: SUI, USDC
- TON: TON, USDT, GRAM when market evidence exists

## Generator C — Structural parity

Same economic underlying:
- stable issuer/redemption
- LST underlying/exchange rate
- BTC representations
- bridge representations
- tokenized commodity/equity vs external reference
- NAV/share token

## Generator D — Cycles

Enumerate bounded verified 3–5 edge cycles.

Never generate a cycle merely from ticker equivalence.

## Generator E — Capital edges

Join FlashCapitalGraph capacity/cost to executable route candidates.

## Generator F — Representation / bridge signals

Create research-only cross-chain basis edges.

## Generator G — Venue divergence

Same representation + amount across multiple executable venues/builders.

## Priority clusters from the attached strategy

### Solana
- stable/yield: USDC, USDT, USDG, PYUSD, JupUSD, USD1, CASH, USDe, sUSDe, USDS, sUSDS, USDY, FDUSD, syrupUSDC, EURC, hyUSD
- SOL/LST/LRT: core + dynamic Sanctum registry
- BTC: cbBTC, WBTC, xBTC, tBTC
- NAV: JLP
- dynamic high-volume discoveries such as ZEC, WETH and event tokens
- RWA/xStocks as reference-linked EVENT relations

### Sui
- native/bridge stable representations
- SUI LSTs
- BTC/ETH/SOL representations
- DeepBook/Cetus/Bluefin ecosystem markets
- XAUM/XAGM oracle-linked assets
- broader Scallop/NAVI supported assets

### TON
Use all real STON pools as cheap research relations; apply higher heat to core stable/LST/GRAM/gold routes.

## No fixed-pair polling architecture

Scheduler works from:
- heat
- provider quota
- recurrence
- liquidity/depth
- anomaly strength
- source freshness
- verification cost
- capital availability
