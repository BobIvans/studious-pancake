# CorrelationLedger

## Goal

Learn market structure from retained observations, not just current spreads.

Do **not** correlate raw prices for assets that share a $1 or underlying anchor.

## Residual series

### Stable
`stable_residual = executable_price - structural_redemption_anchor`

### LST
`lst_premium = executable_LST_per_native - protocol_exchange_rate`

### Wrapper
`wrapper_basis = executable_wrapper_USD - underlying_reference_USD`

### NAV/share
`nav_basis = market_share_price - reconstructed_NAV`

### Venue
`venue_residual = executable_VWAP_A - executable_VWAP_B`

### Direct/synthetic
`direct_synthetic_residual = direct(A/B) - synthetic(A/HUB,B/HUB)`

### Cross-chain
`chain_basis = local_price_A - local_price_B - estimated_rebalance_cost`

### Oracle
`oracle_market_basis = executable_market - oracle_reference`

## Lead / lag

Evaluate event-time cross correlations at bounded windows:
- 100 ms
- 500 ms
- 1 s
- 5 s
- 30 s
- 5 min

Only compare after correcting for:
- provider timestamp semantics
- receive latency
- chain slot/checkpoint time
- stale/lagged indexer data

## Example hypotheses

- Manifest CLOB leads AMM residuals.
- CEX BTC impulse precedes Solana/Sui wrapper basis changes.
- Solana xBTC leads or lags Sui XBTC.
- DeepBook leads Cetus/Aftermath on some pairs.
- stable residual clusters widen together under market stress.
- LST premium regimes correlate across Solana and Sui.

## Storage

Use compact rolling aggregates:
- raw HOT observations retained short horizon
- downsample WARM/COLD
- preserve anomalies, route changes and exact-verification snapshots long term

Do not store every unchanged quote forever.

## Outputs

- pairwise residual correlation
- lead/lag score
- regime labels
- source lead probability
- anomaly recurrence
- false-positive rate after exact verification

These are research scheduling signals, never standalone execution authority.
