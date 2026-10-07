# MASTER CONTEXT

## Why this package exists

The attached strategy expands the research universe dramatically:
- dynamic Solana stable/LST/BTC/RWA markets;
- dynamic Sui stable/BTC/LST/representation markets;
- TON all-pools/all-assets ingestion;
- flash-capital sources;
- cross-chain representation residuals;
- lead/lag and structural correlations.

The correct implementation is not hundreds of polling loops.

Use the GPR-01 graph as the shared semantic layer and add live discovery/quote/build/capital adapters around it.

## Core split

### Data plane
Cheap, high-throughput, indexed, CLOB, oracle and registry sources.

### Quote plane
Amount-specific router quotes.

### Build plane
Unsigned transaction/instruction/PTB construction.

### Exact plane
Independent chain-state verification.

### Capital plane
Flash-capital availability/cost + Solana rent financing.

### Sign plane
Local only. Disabled during qualification.

### Send plane
Separate authority; not added by this R&D.

## Provider independence

Do not equate API diversity with liquidity independence.

Examples:
- OpenOcean Solana is correlated with Jupiter + Titan.
- Titan is itself a meta-aggregator.
- 7K/FlowX/Cetus/Aftermath may overlap underlying Sui venues.
- Rango can route through underlying providers.

Store:
`provider`, `operator`, `correlation_group`, `underlying_venues[]`, `route_hash`, `pool_ids[]`.

## Net quote ranking

Do not select merely max outAmount.

Rank:
```text
expected_out
- router/provider fees
- LP fees
- priority/gas cost
- rent/ATA cost or rent-financing overhead
- flash-capital fee
- expected landing cost
- expected failure penalty
```

Qualification should retain every losing quote as evidence.

## Dynamic-universe principle

Registries create candidate nodes:
- Sanctum LST registry
- Manifest markets
- Raydium/Meteora/Orca pools
- DeepBook pools
- Aftermath/Cetus/7K/FlowX supported coins/routes
- NAVI/Scallop lending/flash assets
- STON assets/pools
- Omniston/swap.coffee/DeDust/Tonco routes

The graph materializes relationships only when evidence exists.
