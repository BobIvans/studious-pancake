# Assignment — R-09 multichain market universe and data-feed expansion

Copy-ready trigger: Expand research data coverage beyond the initial Solana market-data P0 without inventing executable liquidity. Read the source catalog, current QPR/DIN/GPR owners, Dynamic Universe map, Sui/TON dossiers and current official docs. Maintain separate research, reference, exact state, quote and financing data classes. Implement or research one source family per focused task/PR.

## Work packages
### Sui
- DeepBook V3 orderbook/pools; Cetus, Aftermath, Scallop and other actively supported AMMs; NAVI is handled by R02-CAP-C as capital, not a swap-market source.
- Pin GraphQL/gRPC/Core endpoint, schema, checkpoint/object semantics, package IDs, full Move type and decimals.
- Distinguish shared object version/digest, pool state, orderbook depth, swap math, lending pool state and oracle/reference data.
- No legacy retired JSON-RPC fallback.

### TON
- Preserve existing STON asset/pool/stats radar and optional Omniston read-only enrichment.
- Verify current API, address formats, pool identities, fees, decimals and source limits.
- Keep TON as discovery/async research until an atomic borrow→swap→repay or equivalent financing path is proved. Do not infer atomic flash liquidity from routing APIs.

### EVM
- Pin chain IDs, deployed contract/program IDs, ABI/source code hashes and state-reading RPC.
- Research chain-specific pools: Uniswap V2/V3/V4, Curve, Balancer, PancakeSwap, Aerodrome/Velodrome and others from the current catalog.
- Exact state must match venue math (ticks, hooks, bins, stable invariant, fees, reorg/finality).
- Separate flash lender research from AMM venue research. Aave/Morpho/etc. financing uses the capital workstream and callback/receiver constraints.

### CEX and oracle/reference
- Public order books/trades require sequence numbers, snapshots, checksums, reconnect, gap recovery and exchange clock/freshness.
- Pyth and other oracle/reference feeds require authenticated source pins and staleness/confidence checks.
- DefiLlama, CoinGecko, analytics and TVL feeds remain REFERENCE_ONLY/SIGNAL_ONLY; do not convert them into executable quotes or flash capacity.

## Acceptance
Each source has a versioned dossier with official URL, package/schema/commit pins, license, quotas/auth, error behavior, normalization/identity rules, positive/negative fixtures, bounded live read receipts and offline replay. Missing contracts become BLOCKED. No source is enabled solely because it is listed in a catalog. Cross-chain/CEX paths remain signal-only unless exact settlement is proven.
