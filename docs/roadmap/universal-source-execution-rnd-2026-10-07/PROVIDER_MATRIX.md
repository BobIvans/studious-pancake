# Provider Matrix

## Solana — quote/build lanes

| Provider | Role | Free/default known limit | Build artifact | Signing | Correlation |
|---|---|---:|---|---|---|
| Jupiter | reference/meta-router | Free general 1 RPS; execute/submit have separate higher buckets | build/tx endpoints | local/client | JUPITER |
| 0x Solana | primary alternate router | ~5 RPS Free | serialized instructions + ALTs | local/client | ZEROX |
| Titan | meta-aggregator | Sandbox 1 RPS / 2.5M credits | instructions + ready transaction | local/client | TITAN_META |
| OpenOcean Solana | meta comparator | 2 RPS default | swap transaction body | local/client | JUPITER+TITAN |
| OKX DEX | alternate aggregator | Trial 1 RPS, review up to 5 RPS / 60d | swap transaction data | local/client | OKX_AGG |
| Rango | universal route/builder | free B2B with default unpublished limits | Solana transaction object | local/client | RANGO_META |

Important:
- Jupiter general quote/build is the 1 RPS bottleneck; do not use it as the scheduler clock.
- Jupiter Free execute and submit endpoints have separate 50 RPS buckets, so landing is not the same bottleneck as quote/build.
- Titan route evidence is valuable because it compares providers and can stream when higher access is available.
- OpenOcean is useful for a provider race but is explicitly correlated with Jupiter/Titan.

## Solana — cheap radar/context

- DEX Screener
- GeckoTerminal
- Meteora indexed APIs
- Raydium API v3
- Manifest books/markets
- Sanctum LST registry / quote paths
- Jupiter token/route metadata
- Vybe
- Birdeye
- OKX Market API
- Pyth
- optional Switchboard
- public CEX orderbook streams (Binance/Coinbase/Kraken/Bybit) as non-atomic lead/lag references
- CoinGecko / DefiLlama as slow reference layers

## Sui — quote/PTB builders

| Provider | Role | Default limit | Build artifact | Special |
|---|---|---:|---|---|
| Aftermath Router | SOR | 1000 requests / 10s | Transaction; can add route into existing Transaction | broad Sui router |
| Cetus Aggregator | multi-DEX SOR | not pinned | compose into existing PTB; unsigned tx API; sponsored tx | many DEXs, sponsor can pay gas |
| 7K MetaAg / Bluefin7K | meta-provider aggregation | not pinned | buildTx / Transaction | FlowX+Cetus+Bluefin providers |
| FlowX MetaAggregator | meta aggregator | not pinned | quote + transaction builder | Cetus/Bluefin/Aftermath/FlowX |
| OKX DEX Sui | aggregator | tier-dependent | swap transaction data | same provider family as OKX |
| Rango | universal builder | free B2B default limits | unsignedPtbBase64 | Solana+Sui+TON support |
| DeepBook direct | CLOB exact/build | chain state | native Transaction builders | direct exact venue |

Caveat:
7K's current SDK notes that some optional Cetus/Pyth/DeepBook-driven routes may still depend on legacy JSON-RPC in that provider integration. Do not reintroduce a legacy JSON-RPC dependency into our exact Sui path; fail closed or exclude affected provider routes.

## Sui — radar/context

- DeepBook pool/book registry
- Aftermath pools/router
- Cetus pools/router
- Scallop rates/assets
- NAVI flash asset/capacity discovery
- 7K supported exchanges
- FlowX supported exchanges
- Bluefin/Bluefin7K markets
- Pyth oracle references
- Sui gRPC / GraphQL exact state

## TON

Research plane:
- STON.fi REST all assets/pools/stats
- Omniston
- swap.coffee
- DeDust
- Tonco
- TON Center
- TonAPI
- Rango TON transaction messages as optional universal builder

TON does not inherit Solana LOCAL_ATOMIC semantics.

## Direct-execution / capital sources

### Solana
- Project 0 / P0 flash loans: 0 protocol fee; direct transaction bookends.
- Kamino KLend flash borrow/repay: reserve-specific config and capacity.
- Slumlord: zero-fee SOL rent flash financing only.

### Sui
- NAVI flash assets: discover live `max`, `flashloanFee`, `coinType`.
- DeepBook V3 pool flash loans.
- Scallop flash loans: 0.1% fee.
