# Source matrix — GPR V2.1 / checked strategy 2026-10-06

Numerical limits are retained only where the prior R&D package pinned them. Sources newly added by the V2.1 attachment are marked with no invented quota; characterize them through ProviderProfile before high-frequency use.

| Source | Chain | Role | Known/public limit in current pack | Campaign policy | Phase |
|---|---|---|---|---|---|
| DEX Screener | multi | RADAR_INDEXER | 300 RPM pair/token endpoints | prefer batches | EXISTING_QPR03 |
| Meteora DLMM | Solana | HIGH_THROUGHPUT_RADAR | 30 RPS | conservative provider bucket | GPR-02 |
| Raydium | Solana | VENUE_INDEXER | no stable numeric limit pinned | bounded existing profile | EXISTING_QPR03/GPR-02 |
| GeckoTerminal | multi | RADAR_INDEXER | 30 calls/min | bounded reference | EXISTING_QPR03 |
| Manifest | Solana | CLOB_BOOK_RADAR | no numeric limit pinned by V2.1 attachment | bounded read-only profile; no uniform polling | GPR-02 |
| Jupiter metadata/routes | Solana | TOKEN_ROUTE_METADATA | Free general API previously pinned at 1 RPS | spend after cheap radar | GPR-02 |
| Jupiter JLP NAV | Solana | NAV_STRUCTURAL_ANCHOR | no separate numeric limit pinned | HOT JLP signal only | GPR-02 |
| 0x Solana | Solana | QUOTE_PREVIEW_B | approx. 5 RPS free/standard in prior pack | first quote validator | GPR-02 |
| Jupiter quote | Solana | QUOTE_PREVIEW_A_FINAL | 1 RPS general free API in prior pack | final/reference quote | GPR-02 |
| Sanctum | Solana | LST_STRUCTURAL_QUOTE | numeric limit not established | targeted LST only | GPR-02 |
| OpenOcean | Solana | QUOTE_PREVIEW_C | 2 RPS prior pack | optional/correlation-tagged | OPTIONAL |
| Vybe | Solana | PARSED_REFERENCE | 60 RPM / 25k credits prior pack | async/reference | OPTIONAL |
| Aftermath | Sui | ROUTER_RADAR | 1000 requests / 10 seconds prior pack | bounded engineering subcaps | GPR-03 |
| DeepBook | Sui | CLOB_BOOK_STATE | no numeric limit pinned by V2.1 attachment | use known pool IDs; checkpoint/object verification | GPR-03 |
| Cetus | Sui | DIRECT_VENUE_STATE | no numeric limit pinned | bounded provider profile | GPR-03 |
| Scallop | Sui | LST_LENDING_RATE_REFERENCE | no numeric limit pinned by V2.1 attachment | structural reference only until verified | GPR-03/GPR-05 |
| Pyth XAU/USD | multi | ORACLE_REFERENCE | keyed/plan-governed in existing repo policy | XAUM research trigger, not trade truth | GPR-03 |
| Sui gRPC/GraphQL | Sui | EXACT_STATE_TRANSPORT | provider-specific | fail closed/profile-specific | GPR-03 |
| STON.fi | TON | TON_RESEARCH_RADAR | no API rate limits in prior pack | self-imposed cap | GPR-08 |

## V2.1 radar order

### Solana
```text
Manifest books
+ DEX Screener batches
+ Meteora/Raydium indexed state
+ Jupiter token/route metadata
        ↓
ResearchEconomicGraph
        ↓
0x
        ↓
Jupiter
        ↓
Sanctum for LST
        ↓
QPR-02 exact state
```

### Sui
```text
DeepBook known pools/book state
+ Aftermath
+ Cetus
+ Scallop rates
+ cheap references
        ↓
ResearchEconomicGraph
        ↓
governed checkpoint/object verification
```

No RPC/state verification is spent uniformly over the full symbolic universe.

## Source/provenance targets from the V2.1 attachment

- Manifest market radar: https://app.manifest.trade/order
- Mysten DeepBook constants/pools: https://github.com/MystenLabs/ts-sdks/blob/main/packages/deepbook-v3/src/utils/constants.ts
- Scallop supported coins/rates context: https://github.com/scallop-io/scallop-skills/blob/master/references/supported-coins.md
- Sui bridge representations: https://docs.sui.io/onchain-finance/fungible-tokens/sui-bridging
- Paxos USDG: https://docs.paxos.com/guides/stablecoin/usdg/mainnet
- OKX xBTC research identity: current OKX xBTC deployment material
- JLP NAV/token identity: current Jupiter/JLP material
