# CODEX ASSIGNMENT — Dynamic Universe + Canonical Asset Registry

**Repository:** `BobIvans/studious-pancake`  
**Assignment date:** 2026-10-07  
**Status:** implementation assignment; read-only qualification first.

## Mission

Unify the canonical asset/mint/coin-type registry with the Dynamic Universe + Relation Generators + Correlation Ledger R&D and implement them as one evidence-driven subsystem. The goal is to stop growing the arbitrage universe by hand and instead let the repository resolve identities, discover live markets, generate economically meaningful relations, learn correlations/lead-lag, discover flash-capital capacity, and promote only verified opportunities into the existing executable graph.

## Non-negotiable prerequisite

Do **not** bypass the current QPR-01/QPR-02/QPR-03 stop/readiness boundary. If `READ_ONLY_REAL_DATA_CAMPAIGN_V1` is not yet `PASS`, do not enable later executable promotion. You may materialize the data models/adapters behind feature gates, but signer/sender/live-capital paths must remain unreachable. Discovery/API data is never executable truth.

## Source-of-truth order

1. This file is the single assignment for this wave.
2. **Part A** is the bootstrap asset identity registry. Its `HARD_BIND`/`VERIFY_STARTUP`/`RESOLVE_LIVE` semantics are authoritative.
3. **Part B** is the implementation architecture. When a static row conflicts with a live registry, preserve the row as historical evidence and resolve the runtime identity from the live authoritative source plus on-chain verification.
4. Existing canonical owners (`MarketObservationV2`, `ShadowMarketGraphIngest`, `UniversalArbitrageGraph`, bounded multihop solver, PR118 sizing, split-flow and cost ledger) must be reused rather than duplicated.

## Required implementation sequence

### GPR-01A — Canonical Asset Resolver
Implement `AssetIdentity`, resolution states, `AssetResolutionJob`, resolver provenance, startup verification and fail-closed ambiguity handling. `RESOLVE_LIVE` is a runtime workflow, not a TODO. Never bind by ticker alone.

### GPR-01B — Dynamic Universe
Ingest live registries/markets and maintain discovered assets, pools/books, lifecycle state, heat inputs and retirement/tombstone evidence. Initial lanes: Solana, Sui, plus TON read-only research lane.

### GPR-02 — Relation Generators
Generate direct-market, venue-fragmentation, direct-vs-synthetic, structural-parity/LST, stable/NAV, wrapper, oracle-market, flash-capital, cross-chain-basis and bounded-cycle candidate relations. Discovery relations must not enter the executable cycle solver until exact verification.

### GPR-03 — Correlation Ledger
Persist replayable observations and residual features, not only raw prices. Compute rolling residual correlation and lead/lag windows while preserving source, provider, correlation-group, market identity and slot/checkpoint provenance.

### GPR-04 — Flash Capital Graph
Discover live lender assets/capacity/fees dynamically (Project 0/marginfi + Kamino on Solana; NAVI/DeepBook/Scallop and qualified Sui providers). Never assume every registry asset is flash-borrowable. Feed capital constraints and fees into route sizing/economics.

### GPR-05 — Evidence-driven promotion + campaign handoff
Promote `DISCOVERY_ONLY -> IDENTIFIER_VERIFIED -> MARKET_VERIFIED -> RPC_EXACT -> PAPER_QUALIFIED` only with explicit evidence. Produce a campaign report of discovered assets/relations, unresolved identities, source disagreements, shared-liquidity aliases, profitable size bands, correlation findings and recommended next venue integrations.

### TON-RADAR-01 — parallel read-only lane
STON.fi REST may feed a broad TON universe; Omniston/swap.coffee/direct venues may enrich candidates. TON multi-contract routes must remain a separate execution class and must not be treated as Solana/Sui-style local atomic flash-loan routes until separately qualified.

## Acceptance criteria

- A new supported asset can appear from a live registry without a code release.
- Ticker collisions cannot silently create an `AssetIdentity`.
- Every executable graph edge traces back to exact market state and canonical identity evidence.
- A live registry change creates a new identity generation/evidence record rather than silently mutating history.
- Relation generators are bounded and deduplicated; they do not create N² polling loops.
- Shared underlying liquidity/providers are correlation-tagged and cannot masquerade as independent confirmations.
- Correlation Ledger can replay a candidate and explain which residual/lead-lag signal promoted it.
- Flash-capital fees/capacity are observed dynamically and included in exact economics.
- Signer/sender/live trading remain unreachable in this wave unless an existing later gate explicitly authorizes them.
- Tests and CI cover resolver ambiguity, schema drift, stale data, provider disagreement, duplicate markets, Token-2022/Move-type semantics, missing/negative evidence and replay determinism.

---

# PART A — FLASHLOAN ASSET MINT / COIN-TYPE REGISTRY

# STUDIOUS PANCAKE
FLASHLOAN ASSET MINT / COIN-TYPE REGISTRY

Solana + Sui · bootstrap registry for Dynamic Universe · 2026-10-07

Purpose. One canonical document containing the assets discussed today that are relevant to local flash-capital routes, structural arbitrage, direct/synthetic route generation, correlation signals, or event-driven discovery. It is intentionally stricter than a token-list: symbol-only binding is forbidden.

Status legend: HARD_BIND = identifier backed by current authoritative/protocol sources; VERIFY_STARTUP = store identifier but assert it on-chain at campaign startup; RESOLVE_LIVE = do not persist a guessed address, resolve from a live issuer/protocol registry then verify on-chain.

Scope boundary. TON assets are not included in this executable registry. TON remains a separate ResearchEconomicGraph domain until its asynchronous multi-contract execution is qualified separately. Cross-chain representations may appear here as signal/representation nodes, but a bridge is never treated as a LOCAL_ATOMIC flash-loan edge.

## 1. Solana registry

### 1.1 Settlement, stablecoins, yield and protocol-value assets

Core hubs and structural anchors. For Token-2022 assets the runtime must also assert token program/extensions, not only the mint.

| Asset | Canonical mint / Sui coin type | Status | Bot role | Primary source |
| --- | --- | --- | --- | --- |
| SOL (native) | No SPL mint; use WSOL for token edges | HARD_BIND | settlement | Native SOL |
| WSOL | So11111111111111111111111111111111111111112 | HARD_BIND | settlement / flash | Solana native-mint |
| USDC | EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v | HARD_BIND | settlement / flash | Solana/Circle |
| USDT | Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB | HARD_BIND | settlement / flash | Solana/Tether |
| USDG | 2u1tszSeqZ3qBWF3uNGPFc8TzMk2tdiwknnRMWGWjGWH | HARD_BIND | stable arb | Paxos / Token-2022 |
| PYUSD | 2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo | HARD_BIND | stable arb | PayPal/Paxos / Token-2022 |
| JupUSD | JuprjznTrTSp2UFa3ZBUFgwdAmtZCq4MQCwysN55USD | VERIFY_STARTUP | stable arb | Jupiter + RPC |
| USD1 | USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB | VERIFY_STARTUP | stable arb | issuer/Jupiter + RPC |
| CASH | CASHx9KJUStyftLFWGvEVf59SGeG9sh5FfcnZMVPCASH | VERIFY_STARTUP | stable arb | Solana token registry / Token-2022 |
| USDe | DEkqHyPN7GMRJ5cArtQFAWefqbZb33Hyf6s5iCwjEonT | VERIFY_STARTUP | synthetic stable | Ethena + RPC |
| sUSDe | Eh6XEPhSwoLv5wFApukmnaVSHQ6sAnoD9BmgmwQoN2sN | VERIFY_STARTUP | yield-share / NAV | Ethena + RPC |
| USDS | USDSwr9ApdHk5bvJKMjzff41FfuX8bSxdKcR81vTwcA | VERIFY_STARTUP | stable arb | Sky/Jupiter + RPC |
| sUSDS | RESOLVE_LIVE | RESOLVE_LIVE | yield-share / NAV | issuer + Jupiter verified list + RPC |
| USDY | A1KLoBrKBde8Ty9qtNQUtq3C2ortoC3u7twggz7sEto6 | VERIFY_STARTUP | yield-bearing / NAV | Ondo + RPC |
| FDUSD | 9zNQRsGLjNKwCUU5Gq5LR8beUCPzQMVMqKAi3SSZh54u | VERIFY_STARTUP | stable / cross-chain | First Digital + RPC |
| EURC | HzwqbKZw8HxMN6bF2yFZNrht3c2iXXzpKcFu7uBEDKtr | VERIFY_STARTUP | FX structural | Circle + RPC |
| syrupUSDC | AvZZF1YaZDziPY2RCK4oJrRVrbN3mTD9NL24hPeaZeUj | VERIFY_STARTUP | yield-bearing / NAV | Maple + RPC |
| hyUSD | RESOLVE_LIVE | RESOLVE_LIVE | protocol stable / invariant | Hylo SDK/IDL + RPC |
| xSOL | RESOLVE_LIVE | RESOLVE_LIVE | leveraged SOL / invariant | Hylo SDK/IDL + RPC |

### 1.2 SOL representations: LST / LRT / restaking

For long-tail LSTs, the preferred source of truth is the live Sanctum LST registry plus an RPC mint-account assertion. RESOLVE_LIVE is deliberate, not missing work.

| Asset | Canonical mint / Sui coin type | Status | Bot role | Primary source |
| --- | --- | --- | --- | --- |
| JitoSOL | J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn | HARD_BIND | LST fair-value | Jito |
| JupSOL | jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v | HARD_BIND | LST fair-value | Jupiter/Sanctum |
| mSOL | mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So | HARD_BIND | LST fair-value | Marinade |
| bSOL | bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1 | HARD_BIND | LST fair-value | Blaze/Sanctum |
| INF | 5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm | HARD_BIND | LST basket / NAV | Sanctum |
| PSOL | pSo1f9nQXWgXibFtKf7NWYxb5enAM4qfP6UJSiXRQfL | VERIFY_STARTUP | LST fair-value | Phantom + RPC |
| BNSOL | BNso1VUJnh4zcfpZa6986Ea66P6TCp59hvtNJ8b1X85 | HARD_BIND | CEX-LST fair-value | Binance |
| bbSOL | Bybit2vBJGhPF52GBdNaQfUJ6ZpThSgHBobjWZpLPb4B | HARD_BIND | CEX-LST fair-value | Bybit/Sanctum |
| hSOL | he1iusmfkpAdwvxLNGV8Y1iSbj4rUy6yMhEA3fotn9A | VERIFY_STARTUP | LST fair-value | Helius/Sanctum + RPC |
| dSOL | Dso1bDeDjCQxTrWHqUUi63oBvV7Mdm6WaobLbQ7gnPQ | VERIFY_STARTUP | LST fair-value | Drift/Sanctum + RPC |
| fwdSOL | cPQPBN7WubB3zyQDpzTK2ormx1BMdAym9xkrYUJsctm | VERIFY_STARTUP | LST structural | Sanctum live registry + RPC |
| dfdvSOL | sctmB7GPi5L2Q5G9tUSzXvhZ4YiDMEGcRov9KfArQpx | VERIFY_STARTUP | LST structural | Sanctum/DeFi Dev Corp + RPC |
| bpSOL | BPSoLzmLQn47EP5aa7jmFngRL8KC3TWAeAwXwZD8ip3P | VERIFY_STARTUP | CEX-LST structural | Sanctum live registry + RPC |
| bonkSOL | BonK1YhkXEGLZzwtcvRTip3gAL9nCeQD7ppZBLXhtTs | VERIFY_STARTUP | LST structural | Sanctum live registry + RPC |
| hubSOL | HUBsveNpjo5pWqNkH57QzxjQASdTVXcSK7bVKTSZtcSX | VERIFY_STARTUP | LST structural | SolanaHub/Sanctum + RPC |
| cgntSOL | CgnTSoL3DgY9SFHxcLj6CgCgKKoTBr6tp4CPAEWy25DE | VERIFY_STARTUP | LST structural | Cogent/Sanctum + RPC |
| vSOL | vSoLxydx6akxyMD9XEcPvGYNGq6Nn66oqVb3UkGkei7 | VERIFY_STARTUP | LST structural | Sanctum live registry + RPC |
| laineSOL | LAinEtNLgpmCP9Rvsf5Hn8W6EhNiKLZQti1xfWMLy6X | VERIFY_STARTUP | LST structural | Laine/Sanctum + RPC |
| sSOL | sSo14endRuUbvQaJS3dq36Q829a3A6BEfoeeRGJywEh | VERIFY_STARTUP | restaked SOL | Solayer + RPC |
| fragSOL | FRAGSEthVFL7fdqM8hxfxkfCZzUvmg21cqPJVvC1qdbo | VERIFY_STARTUP | restaked SOL / LRT | Fragmetric + RPC |
| fSOL (Fragmetric LST) | FRAGME9aN7qzxkHPmVP22tDhG87srsR9pr5SY9XdRd9R | VERIFY_STARTUP | LST structural | Fragmetric/Sanctum + RPC |
| gtSOL | gateMurAxe4YFoUR6J63gXGKtkbTfdkMdLjZrCmThFP | VERIFY_STARTUP | CEX-LST structural | Sanctum live registry + RPC |
| BulkSOL | BULKoNSGzxtCqzwTvg5hFJg8fx6dqZRScyXe5LYMfxrn | VERIFY_STARTUP | LST structural | Sanctum live registry + RPC |
| mpSOL | MpsoLp1YBDqeiuSrVrYH4DoAGJ3myAMmMy6crYNVSTo | VERIFY_STARTUP | LST structural | Sanctum live registry + RPC |
| definSOL | DEF1NXSZ8Th9n28hYBayrFtx9bj1EwwTiy3mhHEB9oyA | VERIFY_STARTUP | LST structural | issuer/Sanctum + RPC |
| rkuSOL | RESOLVE_LIVE | RESOLVE_LIVE | LST structural | Sanctum live registry + RPC |
| dzSOL | RESOLVE_LIVE | RESOLVE_LIVE | LST structural | Sanctum live registry + RPC |
| JSOL | RESOLVE_LIVE | RESOLVE_LIVE | LST structural | JPool/Sanctum + RPC |
| edgeSOL | RESOLVE_LIVE | RESOLVE_LIVE | long-tail LST | Sanctum live registry + RPC |
| haSOL | RESOLVE_LIVE | RESOLVE_LIVE | long-tail LST | Sanctum live registry + RPC |

### 1.3 BTC/ETH/bridged assets and NAV tokens

| Asset | Canonical mint / Sui coin type | Status | Bot role | Primary source |
| --- | --- | --- | --- | --- |
| cbBTC | cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij | HARD_BIND | BTC wrapper parity | Coinbase |
| WBTC (Wormhole) | 3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh | VERIFY_STARTUP | BTC wrapper parity | Wormhole + RPC |
| xBTC (OKX) | CtzPWv73Sn1dMGVU3ZtLv9yWSyUAanBni19YWDaznnkn | HARD_BIND | BTC wrapper parity | OKX |
| tBTC | 6DNSN2BJsaPFdFFc1zP37kkeNe4Usc1Sqkzr9C9vPWcU | VERIFY_STARTUP | BTC wrapper parity | Threshold/current token list + RPC |
| ZEC (bridged) | A7bdiYdS5GjqGFtxf17ppRHtDKPkkRqbKtR27dxvQXaS | VERIFY_STARTUP | bridged reference / triangles | issuer/bridge + RPC |
| WETH (Wormhole ETH) | 7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs | VERIFY_STARTUP | ETH/SOL/reference | Wormhole + RPC |
| HYPE (Solana representation) | RESOLVE_LIVE | RESOLVE_LIVE | bridged/reference candidate | verified-token registry + issuer + RPC |
| TRX (Solana representation) | RESOLVE_LIVE | RESOLVE_LIVE | bridged/reference candidate | verified-token registry + bridge + RPC |
| JLP | 27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4 | HARD_BIND | NAV / basket arb | Jupiter |

### 1.4 Ecosystem and event-driven assets

| Asset | Canonical mint / Sui coin type | Status | Bot role | Primary source |
| --- | --- | --- | --- | --- |
| JUP | JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN | HARD_BIND | multi-venue | Jupiter |
| JTO | jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL | HARD_BIND | multi-venue / Jito triangle | Jito |
| RAY | 4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R | HARD_BIND | venue-token | Raydium |
| ORCA | orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE | HARD_BIND | venue-token | Orca |
| PYTH | HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3 | HARD_BIND | oracle/ecosystem | Pyth official |
| MET | METvsvVRapdj9cFLzq4Tr43xK4tAjQfwX76z3n6mWQL | VERIFY_STARTUP | venue-token | Meteora + RPC |
| BONK | DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 | HARD_BIND | EVENT | verified token + RPC |
| WIF | EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm | HARD_BIND | EVENT | verified token + RPC |
| POPCAT | 7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr | HARD_BIND | EVENT | verified token + RPC |
| RENDER | rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof | HARD_BIND | EVENT | Render + RPC |
| HNT | hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux | HARD_BIND | EVENT | Helium official |
| PUMP | pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn | HARD_BIND | EVENT / migration | Pump.fun |
| TRUMP | 6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN | VERIFY_STARTUP | EVENT | verified-token lookup + RPC |
| FARTCOIN | 9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump | VERIFY_STARTUP | EVENT | verified-token lookup + RPC |

### 1.5 RWA / xStocks reference assets discussed today

These are primarily signal/reference assets. Before execution, resolve through Backed/xStocks public metadata and verify Token-2022 authorities/current mint. Only SPYx is prefilled here.

| Asset | Canonical mint / Sui coin type | Status | Bot role | Primary source |
| --- | --- | --- | --- | --- |
| SPYx | XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W | VERIFY_STARTUP | RWA reference / EVENT | Backed/xStocks + authority check |
| NVDAx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| TSLAx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| GOOGLx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| QQQx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| MSTRx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| CRCLx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| GLDx (xStock gold ETF/tokenized security) | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| SPCX | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed/verified RWA registry + RPC |
| RBLXx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| DKNGx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |

## 2. Sui registry (full Move coin types)

On Sui, the canonical identity is the entire package::module::type string. Do not store only a package id or ticker.

### 2.1 Settlement, stablecoins and bridged representations

| Asset | Canonical mint / Sui coin type | Status | Bot role | Primary source |
| --- | --- | --- | --- | --- |
| SUI | 0x2::sui::SUI | HARD_BIND | native / flash | Mysten |
| USDC (native) | 0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7::usdc::USDC | HARD_BIND | settlement / flash | Circle/Mysten |
| wUSDC (Wormhole) | 0x5d4b302506645c37ff133b98c4b50a5ae14841659738d6d733d59d0d217a93bf::coin::COIN | HARD_BIND | representation parity | Scallop/Mysten |
| USDCsol (Wormhole Solana-origin) | 0xb231fcda8bbddb31f2ef02e6161444aec64a514e2c89279584ac9806ce9cf037::coin::COIN | VERIFY_STARTUP | representation / cross-chain | Sui bridge docs + RPC |
| wUSDT (Wormhole) | 0xc060006111016b8a020ad5b33834984a437aaa7d3c74c18e09a95d48aceab08c::coin::COIN | HARD_BIND | representation parity | Scallop/Mysten |
| sbUSDT (Sui Bridge) | 0x375f70cf2ae4c00bf37117d0c85a2c71545e6ee05c4a5c7d282cd66a4504b068::usdt::USDT | HARD_BIND | settlement / representation | Scallop/Mysten |
| FDUSD | 0xf16e6b723f242ec745dfd7634ad072c42d5c1d9ac9d62a39c381303eaa57693a::fdusd::FDUSD | HARD_BIND | stable / flash | First Digital/Scallop |
| USDY | 0x960b531667636f39e85867775f52f6b1f220a058c4de786905bdf761e06a56bb::usdy::USDY | HARD_BIND | yield / flash | Ondo/Scallop |
| mUSD | 0xe44df51c0b21a27ab915fa1fe2ca610cd3eaa6d9666fe5e62b988bf7f0bd8722::musd::MUSD | HARD_BIND | stable structural | Scallop |
| suiUSDe | 0x41d587e5336f1c86cad50d38a7136db99333bb9bda91cea4ba69115defeb1402::sui_usde::SUI_USDE | HARD_BIND | synthetic stable | Mysten/Scallop |
| USDsui | 0x44f838219cf67b058f3b37907b655f226153c18e33dfcd0da559a844fea9b1c1::usdsui::USDSUI | HARD_BIND | synthetic stable | Mysten/Scallop |
| AUSD | 0x2053d08c1e2bd02791056171aab0fd12bd7cd7efad2ab8f6b9c8902f14df2ff2::ausd::AUSD | VERIFY_STARTUP | stable / flash | DeepBook/NAVI + issuer revalidation |
| BUCK | 0xce7ff77a83ea0cb6fd39bd8748e2ec89a3f41e8efdc3f4eb123e0ca37b184db2::buck::BUCK | VERIFY_STARTUP | protocol stable | protocol registry + RPC |
| USDB | RESOLVE_LIVE | RESOLVE_LIVE | protocol stable / BUCK cross | issuer/protocol registry + Sui RPC |
| sUSDB | 0x38f61c75fa8407140294c84167dd57684580b55c3066883b48dedc344b1cde1e::susdb::SUSDB | VERIFY_STARTUP | yield-share | current Sui registry + RPC |

### 2.2 BTC / ETH / SOL representations

| Asset | Canonical mint / Sui coin type | Status | Bot role | Primary source |
| --- | --- | --- | --- | --- |
| xBTC | 0x876a4b7bce8aeaef60464c11f4026903e9afacab79b9b142686158aa86560b50::xbtc::XBTC | HARD_BIND | BTC wrapper / flash | OKX/Scallop |
| wBTC (Wormhole) | 0x027792d9fed7f9844eb4839566001bb6f6cb4804f66aa2da6fe1ee242d896881::coin::COIN | HARD_BIND | BTC representation | Scallop |
| sbwBTC (Sui Bridge) | 0xaafb102dd0902f5055cadecd687fb5b71ca82ef0e0285d90afde828ec58ca96b::btc::BTC | HARD_BIND | BTC representation | Scallop |
| zwBTC / LZWBTC | 0x0041f9f9344cac094454cd574e333c4fdb132d7bcc9379bcd4aab485b2a63942::wbtc::WBTC | HARD_BIND | BTC representation | Scallop/Mysten |
| LBTC | 0x3e8e9423d80e1774a7ca128fccd8bf5f1f7753be658c5e645929037f7c819040::lbtc::LBTC | VERIFY_STARTUP | BTC representation | issuer + RPC |
| tBTC | RESOLVE_LIVE | RESOLVE_LIVE | BTC representation | Threshold/Sui registry + RPC |
| SVBTC | RESOLVE_LIVE | RESOLVE_LIVE | BTC representation | issuer + Sui RPC |
| wETH (Wormhole) | 0xaf8cd5edc19c4512f4259f0bee101a40d41ebed738ade5874359610ef8eeced5::coin::COIN | HARD_BIND | ETH representation / flash | Scallop |
| BETH / sbETH (Sui Bridge) | 0xd0e89b2af5e4910726fbcd8b8dd37bb79b29e5f83f7491bca830e94f7f226d29::eth::ETH | HARD_BIND | ETH representation | Scallop |
| wSOL (Wormhole) | 0xb7844e289a8410e50fb3ca48d69eb9cf29e27d223ef90353fe1bd8e27ff8f3f8::coin::COIN | HARD_BIND | SOL representation / flash | Scallop/Sui bridge |

### 2.3 SUI LST cluster

| Asset | Canonical mint / Sui coin type | Status | Bot role | Primary source |
| --- | --- | --- | --- | --- |
| sSUI | 0x83556891f4a0f233ce7b05cfe7f957d4020492a34f5405b2cb9377d060bef4bf::spring_sui::SPRING_SUI | HARD_BIND | SUI LST | Suilend/SpringSui |
| afSUI | 0xf325ce1300e8dac124071d3152c5c5ee6174914f8bc2161e88329cf579246efc::afsui::AFSUI | HARD_BIND | SUI LST | Aftermath/Scallop |
| haSUI | 0xbde4ba4c2e274a60ce15c1cfff9e5c42e41654ac8b6d906a57efa4bd3c29f47d::hasui::HASUI | HARD_BIND | SUI LST | Haedal/Scallop |
| vSUI | 0x549e8b69270defbfafd4f94e17ec44cdbdd99820b33bda2278dea3b9a32d3f55::cert::CERT | HARD_BIND | SUI LST / flash | Scallop |
| scaSUI | 0xda008a552a2d6a9566fa6204255d55ab32ce00f23e307145dec2644cf83336b2::sca_sui::SCA_SUI | HARD_BIND | SUI LST | Scallop |
| stSUI | RESOLVE_LIVE | RESOLVE_LIVE | SUI LST / flash | NAVI current registry + issuer + RPC |
| eSUI | RESOLVE_LIVE | RESOLVE_LIVE | SUI LST | issuer + Sui RPC |

### 2.4 Ecosystem, venue, event and commodity-reference assets

| Asset | Canonical mint / Sui coin type | Status | Bot role | Primary source |
| --- | --- | --- | --- | --- |
| DEEP | 0xdeeb7a4662eec9f2f3def03fb937a663dddaa2e215b8078a284d026b7946c270::deep::DEEP | HARD_BIND | DeepBook / multi-venue | Mysten |
| WAL | 0x356a26eb9e012a68958082340d4c4116e7f55615cf27affcff209cf0ae544f59::wal::WAL | HARD_BIND | ecosystem / multi-venue | Scallop/Mysten |
| SCA | 0x7016aae72cfc67f2fadf55769c0a7dd54291a583b63051a5ed71081cce836ac6::sca::SCA | HARD_BIND | Scallop ecosystem | Scallop |
| NAVX | 0xa99b8952d4f7d947ea77fe0ecdcc9e5fc0bcab2841d6e2a5aa00c3044e5544b5::navx::NAVX | VERIFY_STARTUP | NAVI ecosystem | NAVI + RPC |
| CETUS | 0x06864a6f921804860930db6ddbe2e16acdf8504495ea7481637a1c8b9a8fe54b::cetus::CETUS | HARD_BIND | venue-token | Scallop/Cetus |
| NS | 0x5145494a5f5100e645e4b0aa950fa6b68f614e8c59e17bc5ded3495123a79178::ns::NS | HARD_BIND | ecosystem / CLOB | Scallop/Mysten |
| SEND | 0xb45fcfcc2cc07ce0702cc2d229621e046c906ef14d9b25e8e4d25f6e8763fef7::send::SEND | VERIFY_STARTUP | ecosystem / CLOB | DeepBook + RPC |
| IKA | 0x7262fb2f7a3a14c888c438a3cd9b912469a58cf60f367352c46584262e8299aa::ika::IKA | VERIFY_STARTUP | ecosystem / CLOB | DeepBook + RPC |
| ALKIMI | 0x1a8f4bc33f8ef7fbc851f156857aa65d397a6a6fd27a7ac2ca717b51f2fd9489::alkimi::ALKIMI | VERIFY_STARTUP | ecosystem / CLOB | DeepBook + RPC |
| BLUE | 0xe1b45a0e641b9955a20aa0ad1c1f4ad86aad8afb07296d4085e349a50e90bdca::blue::BLUE | VERIFY_STARTUP | Bluefin ecosystem | DeepBook/Bluefin + RPC |
| HAEDAL | 0x3a304c7feba2d819ea57c3542d68439ca2c386ba02159c740f7b406e592c62ea::haedal::HAEDAL | HARD_BIND | Haedal ecosystem | Scallop |
| wWAL | 0xb1b0650a8862e30e3f604fd6c5838bc25464b8d3d827fbd58af7cb9685b832bf::wwal::WWAL | HARD_BIND | WAL representation | Scallop |
| haWAL | 0x8b4d553839b219c3fd47608a0cc3d5fcc572cb25d41b7df3833208586a8d2470::hawal::HAWAL | HARD_BIND | WAL liquid-staking | Scallop |
| TYPUS | 0xf82dc05634970553615eef6112a1ac4fb7bf10272bf6cbe0f80ef44a6c489385::typus::TYPUS | VERIFY_STARTUP | CLOB/ecosystem | DeepBook + RPC |
| DRF | 0x294de7579d55c110a00a7c4946e09a1b5cbeca2592fbb83fd7bfacba3cfeaf0e::drf::DRF | VERIFY_STARTUP | CLOB/ecosystem | DeepBook + RPC |
| FUD | 0x76cb819b01abed502bee8a702b4c2d547532c12f25001c9dea795a5e631c26f1::fud::FUD | HARD_BIND | EVENT | Scallop |
| BLUB | 0xfa7ac3951fdca92c5200d468d31a365eb03b2be9936fde615e69f0c1274ad3a0::BLUB::BLUB | HARD_BIND | EVENT | Scallop |
| LOFI | 0xf22da9a24ad027cccb5f2d496cbe91de953d363513db08a3a734d361c7c17503::LOFI::LOFI | HARD_BIND | EVENT | Scallop |
| TRUTH | RESOLVE_LIVE | RESOLVE_LIVE | ecosystem / event candidate | verified Sui registry + venue + RPC |
| XAUm | 0x9d297676e7a4b771ab023291377b2adfaa4938fb9080b8d12430e4b108b836a9::xaum::XAUM | HARD_BIND | gold/oracle structural | Scallop + oracle |
| XAGm | RESOLVE_LIVE | RESOLVE_LIVE | silver/oracle structural | issuer/Bluefin + RPC |

## 3. Runtime binding rules for the flashloan bot

Never bind by ticker: The registry key should be chain + canonical_id. Symbols are display metadata only.

Startup assertions: For every HARD_BIND and VERIFY_STARTUP asset: fetch mint/coin metadata, decimals, owner/program/type and current chain existence; fail closed on mismatch.

RESOLVE_LIVE: Resolve from live issuer/protocol registry, record source URL + response hash + observed_at + slot/checkpoint, then verify on-chain before graph promotion.

Flash-capital != asset-list: An asset in this registry is not automatically flash-borrowable. Query Project0/Kamino on Solana and NAVI/DeepBook/Cetus/Scallop on Sui for live capacity and fee.

Structural assets: LST/LRT/yield/share/wrapper tokens enter the research graph with an anchor (exchange rate, NAV, redemption or underlying reference).

Discovery-only boundary: No indexer/router/reference observation becomes an executable edge until exact chain-state verification produces the canonical market observation.

## 4. Mandatory RESOLVE_LIVE queue

27 entries are intentionally left without a hardcoded address. The bot should resolve these dynamically rather than inherit a stale or ambiguous mint.

### 4.1 Resolve before executable promotion

| Asset | Canonical mint / Sui coin type | Status | Bot role | Primary source |
| --- | --- | --- | --- | --- |
| sUSDS | RESOLVE_LIVE | RESOLVE_LIVE | yield-share / NAV | issuer + Jupiter verified list + RPC |
| hyUSD | RESOLVE_LIVE | RESOLVE_LIVE | protocol stable / invariant | Hylo SDK/IDL + RPC |
| xSOL | RESOLVE_LIVE | RESOLVE_LIVE | leveraged SOL / invariant | Hylo SDK/IDL + RPC |
| rkuSOL | RESOLVE_LIVE | RESOLVE_LIVE | LST structural | Sanctum live registry + RPC |
| dzSOL | RESOLVE_LIVE | RESOLVE_LIVE | LST structural | Sanctum live registry + RPC |
| JSOL | RESOLVE_LIVE | RESOLVE_LIVE | LST structural | JPool/Sanctum + RPC |
| edgeSOL | RESOLVE_LIVE | RESOLVE_LIVE | long-tail LST | Sanctum live registry + RPC |
| haSOL | RESOLVE_LIVE | RESOLVE_LIVE | long-tail LST | Sanctum live registry + RPC |
| HYPE (Solana representation) | RESOLVE_LIVE | RESOLVE_LIVE | bridged/reference candidate | verified-token registry + issuer + RPC |
| TRX (Solana representation) | RESOLVE_LIVE | RESOLVE_LIVE | bridged/reference candidate | verified-token registry + bridge + RPC |
| NVDAx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| TSLAx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| GOOGLx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| QQQx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| MSTRx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| CRCLx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| GLDx (xStock gold ETF/tokenized security) | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| SPCX | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed/verified RWA registry + RPC |
| RBLXx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| DKNGx | RESOLVE_LIVE | RESOLVE_LIVE | RWA reference / EVENT | Backed xStocks public API + RPC |
| USDB | RESOLVE_LIVE | RESOLVE_LIVE | protocol stable / BUCK cross | issuer/protocol registry + Sui RPC |
| tBTC | RESOLVE_LIVE | RESOLVE_LIVE | BTC representation | Threshold/Sui registry + RPC |
| SVBTC | RESOLVE_LIVE | RESOLVE_LIVE | BTC representation | issuer + Sui RPC |
| stSUI | RESOLVE_LIVE | RESOLVE_LIVE | SUI LST / flash | NAVI current registry + issuer + RPC |
| eSUI | RESOLVE_LIVE | RESOLVE_LIVE | SUI LST | issuer + Sui RPC |
| TRUTH | RESOLVE_LIVE | RESOLVE_LIVE | ecosystem / event candidate | verified Sui registry + venue + RPC |
| XAGm | RESOLVE_LIVE | RESOLVE_LIVE | silver/oracle structural | issuer/Bluefin + RPC |

## 5. Source-of-truth registry endpoints / references

Solana core token documentation: https://solana.com/docs/payments/how-payments-work

Pyth token addresses: https://docs.pyth.network/pyth-token/pyth-token-addresses

Sanctum live LST list: https://github.com/igneous-labs/sanctum-lst-list

Jito / JitoSOL: https://www.jito.network/

Backed / xStocks public API: https://api.backed.fi/api-docs/

Sui / Mysten DeepBook constants: https://github.com/MystenLabs/ts-sdks/tree/main/packages/deepbook-v3

Scallop supported coins: https://github.com/scallop-io/scallop-skills/blob/master/references/supported-coins.md

Sui bridge assets: https://docs.sui.io/onchain-finance/fungible-tokens/sui-bridging

---

# PART B — DYNAMIC UNIVERSE + RELATION GENERATORS + CORRELATION LEDGER R&D

STUDIOUS PANCAKE

DYNAMIC UNIVERSE + RELATION GENERATORS + CORRELATION LEDGER

R&D implementation specification for Solana + Sui, with TON read-only research lane

Goal: turn the current mint/coin-type registry into a self-expanding evidence graph that resolves live asset identities, discovers markets, generates economically meaningful relations, learns recurring correlations, and promotes only RPC-verified candidates into the existing executable arbitrage graph.

| Decision | R&D conclusion |
| --- | --- |
| Existing registry audit | 163 table rows; 61 HARD_BIND; 48 VERIFY_STARTUP; 54 RESOLVE_LIVE. Rows include intentional duplicates across strategy/representation sections. |
| Core correction | The previous registry is a bootstrap, not a claim that every asset discussed today is permanently resolved. TON was intentionally excluded from LOCAL_ATOMIC execution. |
| Resolution principle | RESOLVE_LIVE becomes an executable workflow: discover candidate ID → verify issuer/protocol registry → verify on-chain type/program/decimals → record evidence → only then bind. |
| Safety boundary | Discovery data never creates executable graph edges by itself. Only exact verified MarketObservationV2 / chain-equivalent observations may enter the execution solver. |

No — not literally every ticker ever mentioned during today's exploration was hard-bound, and that is the correct outcome. The previous document intentionally mixed three states: HARD_BIND, VERIFY_STARTUP and RESOLVE_LIVE. It also kept TON outside the Solana/Sui LOCAL_ATOMIC registry. The new architecture closes the gap without guessing addresses.

- HARD_BIND: seed identifier is authoritative enough to store, but startup still asserts the live account/type before campaign use.

- VERIFY_STARTUP: identifier is known, but program/type/decimals/authority/market status must be re-asserted every campaign generation.

- RESOLVE_LIVE: identifier is intentionally absent. A resolver must fetch it from a live protocol/issuer registry and prove it on-chain before any graph promotion.

- DISCOVERY_ONLY symbols may exist in research observations, but ticker alone is never AssetIdentity.

Long-tail LSTs, new bridged representations, newly listed event tokens and protocol migrations change faster than code releases. A static “complete list” becomes stale. The bot therefore needs a small immutable seed registry plus live resolvers with provenance. This turns unresolved entries from a documentation weakness into a maintained runtime capability.

FREE / CHEAP SOURCES

Solana: Jupiter Tokens/VRFD, Sanctum LST registry, Manifest/Raydium/Meteora/Orca discovery

Sui: DeepBook coin+pool registry, NAVI flash-asset discovery, Aftermath/Cetus/Scallop, gRPC/GraphQL

TON: STON.fi no-limit DEX REST, Omniston, swap.coffee, DeDust

|

v

AssetResolutionQueue

|

Canonical AssetIdentity

|

MarketDiscovery

|

Dynamic Universe

|

RelationGenerators

|

ResearchEconomicGraph

|

CandidateScore + HeatScheduler

|

VerificationRequest / RPC quorum

|

exact MarketObservationV2-equivalent

|

UniversalArbitrageGraph + 2-5 hop solver

|

FlashCapitalGraph + nonlinear sizing

|

PAPER receipt

| Field | Contract |
| --- | --- |
| asset_id | Stable internal UUID/slug. Never use symbol as primary key. |
| chain | solana \| sui \| ton \| future_domain |
| symbol | Display only; collisions allowed. |
| canonical_identifier | Solana mint / Sui full Move coin type / TON jetton master. |
| economic_underlying | USD, SOL, SUI, BTC, ETH, XAU, protocol NAV, etc. |
| representation_kind | native, wrapped, bridge, LST, LRT, stable, yield-share, LP/NAV, event token. |
| program_or_package | SPL Token / Token-2022 / Sui package::module / TON code family. |
| decimals | Proven on-chain, never inferred from ticker. |
| verification_state | UNRESOLVED → CANDIDATE → IDENTIFIER_VERIFIED → STATE_VERIFIED → MARKET_VERIFIED. |
| resolver_generation | Resolver version + campaign SHA/config digest. |
| evidence_refs | Raw registry response hashes + on-chain proof + timestamps. |

| Step | Source | Requirement |
| --- | --- | --- |
| 1 | Seed registry | Use existing HARD_BIND / VERIFY_STARTUP identifier when present. |
| 2 | Protocol registry | LST: Sanctum live registry; protocol-native assets: issuer/official SDK or registry. |
| 3 | Jupiter Tokens / VRFD | Search by symbol/name/mint; require matching id, metadata, verification/audit signals; never accept the first ticker match blindly. |
| 4 | On-chain mint assertion | getAccountInfo/getTokenSupply equivalent: owner program, decimals, mint/freeze authorities, Token-2022 extensions, supply. |
| 5 | Market corroboration | At least one real pool/book/router route with consistent mint; DEX Screener/venue registries are corroboration, not identity authority. |
| 6 | Bind | Persist canonical identifier + evidence hash; promote only within the exact campaign generation. |

Current external support: Jupiter Tokens API V2 exposes token search, metadata and verification status; Sanctum currently exposes a large live Solana LST catalogue. These should be resolver adapters, not manually copied lists.

| Step | Source | Requirement |
| --- | --- | --- |
| 1 | Seed / DeepBook registry | Use complete Move coin type, not package-only id. |
| 2 | Protocol registry | NAVI, Scallop, Aftermath, issuer SDK/config or DeepBook coin map. |
| 3 | Sui chain data | Use gRPC/GraphQL/Core APIs; legacy JSON-RPC must not be a new dependency. |
| 4 | Type verification | Confirm package::module::type exists, decimals/metadata, relevant package/version and market references. |
| 5 | Bind | Persist full type + checkpoint/source evidence. |

Important 2026 runtime rule: Sui Foundation mainnet JSON-RPC was disabled for live mainnet access; implement gRPC or GraphQL/Core paths from the start.

| Step | Source | Requirement |
| --- | --- | --- |
| 1 | STON.fi DEX API | No published DEX API rate limit; ingest all STON assets/pools/stats as cheap research candidates. |
| 2 | Omniston | Cross-DEX/RFQ quote layer; protocol routes can include STON.fi, DeDust, TonCo and resolvers. |
| 3 | Direct venues | DeDust / STON / Tonco state and route evidence. |
| 4 | Chain truth | TON Center / TonAPI / liteserver proof for jetton master, wallet/code and transaction evidence. |
| 5 | Execution classification | Keep TON_ASYNC_MULTI_CONTRACT / LOCAL_MULTI_MESSAGE separate from Solana/Sui LOCAL_ATOMIC until explicitly qualified. |

UNRESOLVED

-> candidate IDs from live registry

-> CANDIDATE_SET

-> zero candidates: NEGATIVE_EVIDENCE / retry backoff

-> >1 plausible candidate: AMBIGUOUS / fail closed

-> exactly one candidate

-> on-chain type/program/decimals verification

-> protocol/issuer corroboration

-> IDENTIFIER_VERIFIED

-> market/route corroboration

-> MARKET_VERIFIED

-> bind to campaign_generation

A symbol collision is a normal output, not an exception. The system should preserve all candidates and the rejection reasons so retrospective analysis can explain why a token was not promoted.

The Dynamic Universe is not a token list. It is a set of versioned assets, markets, representations, economic anchors and financing edges that can be discovered and retired automatically.

| Entity | Meaning |
| --- | --- |
| AssetIdentity | Canonical on-chain asset identity. |
| EconomicAsset | Shared underlying identity, e.g. USD, BTC, SOL, SUI, XAU. |
| Representation | Native/wrapped/bridge/LST/LRT/yield-share token. |
| VenueIdentity | Program/protocol + market/pool/book id + fee tier. |
| MarketIdentity | Exact A/B venue market; includes pool/book address. |
| StructuralAnchor | Redemption, staking exchange rate, NAV, oracle/reference. |
| FlashCapitalEdge | Provider + asset + live capacity + live fee + constraints. |
| TransportEdge | Bridge/rebalance relation; signal/rebalance only unless separately qualified. |

| Adapter | Primary source | Produces |
| --- | --- | --- |
| SolanaTokenResolver | Jupiter Tokens/VRFD + issuer registries | identity |
| SanctumLstIngestor | All current Sanctum LSTs | LST identities + exchange-rate/route anchors |
| SolanaVenueDiscovery | Manifest, Meteora, Raydium, Orca, DEX Screener | pools/books + liquidity/volume |
| Project0CapitalIngestor | P0 live banks | flash-capital candidate edges |
| KaminoCapitalIngestor | KLend live reserves | flash-capital candidate edges |
| SuiCoinResolver | DeepBook/protocol registries + gRPC/GraphQL | Move coin identities |
| DeepBookIngestor | mainnet coins + pools/books | CLOB markets |
| NaviCapitalIngestor | getAllFlashLoanAssets() | live max + flash fee + coin type |
| SuiVenueDiscovery | Aftermath/Cetus/Scallop/Bluefin | AMM/router/lending relations |
| StonRadarIngestor | STON all assets/pools/stats | TON research market firehose |
| OmnistonIngestor | RFQ/aggregated routes | TON cross-DEX route evidence |

DISCOVERED -> CHEAP_WATCH

if liquidity/depth/volume/structural-anchor evidence passes -> COLD/WARM

if anomaly recurrence + independent venues + verification success -> HOT

if event-triggered only -> EVENT

if source disappears / identity changes / market dies -> RETIRED

HOT is a runtime state, not a permanent label in documentation.

| Generator | Precondition | Output / rule |
| --- | --- | --- |
| DIRECT_MARKET | Real A/B pool/book exists | Create venue-specific directed research edges. |
| VENUE_FRAGMENTATION | Same A/B on 2+ venues | Compare amount-specific executable VWAP, fees, depth, freshness. |
| SYNTHETIC_CROSS | A/H and B/H exist | Compare direct A/B to A→H→B; hubs: USDC, USDT, SOL, SUI, TON, GRAM. |
| STRUCTURAL_PARITY | Same economic underlying | Wrapper/bridge/native parity after conversion costs. |
| LST_FAIR_VALUE | LST + protocol rate/instant exit | DEX(LST/SOL) vs exchange rate/unstake route. |
| NAV_BASIS | NAV/LP/basket token | Market price vs current protocol NAV and redeemability. |
| STABLE_RESIDUAL | Stable asset + USD anchor | Peg residual with issuer/redemption semantics. |
| ORACLE_MARKET | Oracle/reference + executable market | Market residual vs Pyth/issuer/CEX reference. |
| FLASH_CAPITAL | Provider supports asset | Borrow-capacity/fee edge into route solver. |
| CROSS_CHAIN_BASIS | Equivalent assets across chains | Signal after estimated rebalance cost; never assumed atomic. |
| BOUNDED_CYCLE | 3-5 RPC-verified exact edges | Enumerate executable cycles only after state verification. |

for each hub H in {USDC, USDT, SOL, SUI, TON, GRAM}:

if market(A,H) and market(B,H):

emit SYNTHETIC(A,B,via=H)

if direct(A,B):

emit DIRECT_SYNTHETIC_RESIDUAL(A,B,via=H)

Do not materialize N x N pairs globally.

Materialize only relations supported by live evidence.

Research graph may contain discovery-only edges.

Executable solver MUST receive only:

state_verified == true

identifier_verified == true

timestamp/slot/checkpoint coherent

costs available

shared-liquidity alias constraints known

Then search bounded cycles length 3..5.

The Correlation Ledger stores normalized residuals and lead/lag evidence rather than trying to learn from raw nominal prices. This is critical: USDC and PYUSD are both near $1, but the useful signal is their deviation from their structural anchors and from each other.

| Feature | Definition |
| --- | --- |
| stable_residual | executable_price - USD/redemption anchor |
| lst_premium | DEX LST/SOL - protocol exchange rate / instant-exit value |
| wrapper_basis | wrapper/USD - underlying reference/USD |
| venue_residual | VWAP_venue_A(amount) - VWAP_venue_B(amount) |
| direct_synthetic_residual | direct A/B - synthetic A/H/B |
| nav_basis | market token value - current protocol NAV |
| chain_basis | chain A price - chain B price - estimated rebalance cost |
| route_topology_change | route/pool composition hash changed |
| depth_shock | change in executable depth at 10/50/100 bps |
| flash_capacity_change | live max borrow and fee regime change |

For each normalized feature pair X,Y:

windows = 100ms, 500ms, 1s, 5s, 30s, 5m

compute rolling correlation and lagged predictive residuals

store regime + sample count + confidence + source correlation penalties

Examples:

DeepBook move -> Cetus lag?

Manifest book -> Meteora lag?

BTC reference -> cbBTC/WBTC/XBTC basis widening?

Solana xBTC -> Sui XBTC lag?

CEX impulse -> Solana/Sui wrapper residual?

The ledger ranks recurring lead/lag patterns for candidate generation. It must not assume causality. Every learned signal remains DISCOVERY_ONLY until an exact current executable path is independently verified.

| Data tier | Retention | Policy |
| --- | --- | --- |
| Raw provider envelopes | 7 days default; 30 days optional | Compressed append-only files; full request/response hash + provenance. |
| Normalized observations | 30 days | Parquet partitioned by chain/date/source/market. |
| 1s/10s/1m aggregates | long-term | Compact statistics for correlations and regime analysis. |
| Anomaly windows | retain long-term | Full-fidelity ±5 min around candidates, failures and route changes. |
| Receipts / proofs | retain indefinitely | Campaign identity, state proof, costs, verdict, negative evidence. |

Suggested local stack: Parquet for durable append-only observations + DuckDB for analysis. SQLite may hold small canonical registries/status, but should not become the high-volume time-series store.

The asset registry and flash-loan registry are separate. An asset may be tradable but not directly flash-borrowable. The route solver can still borrow a hub asset (e.g. USDC/SOL/SUI) and swap into the target route.

| Provider | Domain | Runtime rule |
| --- | --- | --- |
| Project 0 / marginfi | Solana | Load live banks; flashloan wraps arbitrary instructions atomically. Do not assume every discovered asset has a bank. |
| Kamino KLend | Solana | Discover live reserves and flash-loan config/fee per reserve. |
| NAVI | Sui | Use getAllFlashLoanAssets(); read current coinType, max and flashloanFee dynamically. |
| DeepBook | Sui | Pool/orderbook-local flash liquidity where supported; pair closely with CLOB execution. |
| Scallop / other Sui lenders | Sui | Optional fallback capital lane; compare fee/capacity before using. |
| TON | TON | Do not treat as LOCAL_ATOMIC flash-capital until TON-specific execution semantics are separately proven. |

FlashCapitalEdge {

chain

provider

asset_id

max_amount_live

fee_rate_live

atomicity_class

constraints

observed_at

slot_or_checkpoint

evidence_refs

}

heat_score =

executable_depth

+ independent_venue_count

+ structural_anchor_strength

+ normalized_divergence

+ route_topology_change

+ volume_acceleration

+ anomaly_recurrence

+ verification_success_rate

+ flash_capacity_score

- staleness_penalty

- source_correlation_penalty

- shared_liquidity_penalty

- failure_rate

| Tier | Policy |
| --- | --- |
| HOT | Continuous/event-driven cheap observation; expensive quotes only after anomaly trigger. |
| WARM | Frequent cheap observation; candidate promotion on score threshold. |
| COLD | Batch/indexed discovery only. |
| EVENT | No constant expensive polling; wake on pool creation, graduation, liquidity shock, route change, news/reference impulse. |

Two APIs are not independent evidence if they route through the same underlying pool. Every quote/market observation therefore needs pool/program IDs where possible plus a correlation_group.

Example:

Jupiter route -> Meteora pool P

OpenOcean route -> Jupiter/Titan -> same Meteora pool P

Do NOT count this as two independent markets.

Deduplicate economic exposure by underlying resource identity.

| Gate | Meaning |
| --- | --- |
| G0 DISCOVERY_ONLY | Ticker/market observation may be stored; no executable claims. |
| G1 IDENTIFIER_VERIFIED | Canonical mint/coin type proven with registry + chain evidence. |
| G2 MARKET_VERIFIED | Venue/pool/book identity and token ordering proven. |
| G3 STATE_VERIFIED | Slot/checkpoint coherent exact state from required verifier(s). |
| G4 QUOTE_VERIFIED | Local/venue-specific amount quote reconciles with current state. |
| G5 CAPITAL_VERIFIED | Flash/prefund capital capacity + fee known for this size. |
| G6 PAPER_QUALIFIED | Exact costs/sizing pass; durable receipt emitted. |

- Resolver returned 0 candidates or multiple plausible mints/types.

- Registry and on-chain decimals/program disagree.

- Pool disappeared before verification.

- Quote route changed between observation and verification.

- RPC/gRPC providers disagree on state generation.

- Rate-limit or timeout creates a blind window.

- Shared-liquidity alias collapses apparently independent quotes.

- Flash capacity or fee changed and eliminated profitability.

- Token-2022 / bridge / transfer semantics invalidate naive amount math.

The scheduler should maximize cheap data and reserve limited quote/RPC budget for candidates. It should learn observed provider limits rather than depend only on documentation.

priority 0: no-limit / batch / local registries

STON DEX REST, protocol registries, DeepBook pool map, Sanctum LST list

priority 1: high-throughput indexed/routing sources

DEX Screener batch, Aftermath, venue indexed APIs

priority 2: candidate quotes

Jupiter / Titan / 0x / Omniston / other routers

priority 3: exact chain verification

independent Solana RPCs, Sui gRPC/GraphQL providers, TON chain sources

| PR | Scope | Stop condition / deliverable |
| --- | --- | --- |
| GPR-01A | Canonical Asset Resolver | Implement state machine + per-chain resolver interface + evidence receipts. Reuse existing mint registry as bootstrap. |
| GPR-01B | Dynamic Universe Ingestors | Sanctum, Jupiter Tokens, Solana venue discovery, DeepBook, NAVI, STON/Omniston research lane. |
| GPR-02A | Relation Generators | DIRECT, VENUE, SYNTHETIC, STRUCTURAL, LST, NAV, ORACLE, CROSS_CHAIN signal. |
| GPR-02B | Dynamic Heat Scheduler | HOT/WARM/COLD/EVENT from live evidence; quota-aware scheduling. |
| GPR-03 | Correlation Ledger | Residual features, lead/lag windows, regime persistence, anomaly replay. |
| GPR-04 | FlashCapitalGraph | Project0/Kamino + NAVI/DeepBook/Scallop adapters; live fee/capacity. |
| GPR-05 | Read-only campaign | Run real-data campaign; measure false positives, resolver ambiguity, source aliasing and storage footprint. |
| TON-RADAR-01 | Parallel research-only lane | STON no-limit crawler + Omniston; no Solana/Sui-style atomic execution claims. |

| Area | Pass condition |
| --- | --- |
| Asset resolution | A new LST/bridge token can be discovered and canonicalized without a code change; ambiguous symbols fail closed. |
| Dynamic markets | A newly listed pool/book appears as a ResearchRelation automatically and can retire automatically. |
| No false execution | DISCOVERY_ONLY data can never enter UniversalArbitrageGraph as an exact edge. |
| Correlation provenance | Every correlation sample is traceable to exact normalized observations and source generations. |
| Flash-capital truth | Every paper candidate records live provider, capacity, fee and atomicity class. |
| Replay | A candidate can be reconstructed from persisted evidence without relying on mutable external API state. |
| Quota resilience | Provider rate-limit/timeout windows are preserved as negative evidence; scheduler degrades gracefully. |
| Safety | Signer/sender/submission remain unreachable in this R&D phase. |

Build the next wave around the existing QPR evidence model and existing graph owners.

Do NOT create a second arbitrage engine.

Required new owners:

src/assets/resolution/*

src/discovery/dynamic_universe/*

src/strategy/relation_generators/*

src/research/correlation_ledger/*

src/economics/flash_capital_graph/*

Reuse:

MarketObservationV2

ShadowMarketGraphIngest

UniversalArbitrageGraph

multihop_solver

nonlinear sizing

split_flow

exact cost ledger

Critical invariant:

ResearchRelation != DirectedQuoteEdge.

Only exact verified state may cross the promotion boundary.

interface AssetResolver {

discover(query, context) -> CandidateAsset[]

verify(candidate, chain_state) -> AssetResolutionReceipt

}

interface UniverseIngestor {

poll(cursor, budget) -> DiscoveryEnvelope[]

}

interface RelationGenerator {

generate(assets, markets, anchors) -> ResearchRelation[]

}

interface CorrelationLedger {

append(normalized_observation)

features(market_or_relation, window)

lead_lag(a, b, windows)

}

interface FlashCapitalProvider {

discover_assets() -> FlashCapitalEdge[]

refresh(asset_id, amount_hint) -> FlashCapitalEdge

}

| Source | Use |
| --- | --- |
| Jupiter Tokens / VRFD | Token search, metadata and verification signals for Solana token discovery. |
| Sanctum Explore | Live Solana LST catalogue; currently a very large dynamic LST universe. |
| Project 0 / marginfi docs | Atomic Solana flashloan primitive and live bank-oriented SDK. |
| Kamino KLend interface | Reserve-level flash borrow/repay primitive; discover current reserve config/fee. |
| Mysten DeepBook SDK | Current Sui mainnet coin/pool registry and exact market identifiers. |
| Sui docs | Use gRPC/GraphQL/Core; do not build new JSON-RPC dependency. |
| NAVI flash-loan SDK | Live discovery of flash-loan assets, max amount and fee. |
| STON.fi DEX API | No published rate limit; STON-only assets/pools/stats research firehose. |
| Omniston | TON cross-DEX/RFQ aggregation; external DEX route evidence. |

Proceed. The previous mint registry should remain the bootstrap input, not the final universe. `DYNAMIC_UNIVERSE + RELATION_GENERATORS + CORRELATION_LEDGER` is the mechanism that makes unresolved assets maintainable, expands markets without manual PRs, and turns today's research into a self-updating qualification system. The highest-value implementation order is AssetResolver → DynamicUniverse → RelationGenerators/Heat → CorrelationLedger → FlashCapitalGraph → real read-only campaign.