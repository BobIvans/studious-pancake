# PR-353 anomaly taxonomy

Every coverage cell records all six axes below; unknown values remain explicit.

- **domain:** price, liquidity/depth, flow/order, volatility, oracle,
  credit/health, funding/OI, queue/latency, governance, incentives, solvency,
  claims/rights, bridge/finality, blockspace/DA, operational.
- **shape:** point, contextual, collective, regime shift, change point,
  seasonality break, lead-lag, graph motif, cross-venue residual, cross-chain
  residual.
- **horizon:** sub-slot/block, seconds, minutes, epoch, settlement window,
  multi-day.
- **state:** observed, reproducible, explained, hypothesis, falsified,
  paper-positive, shadow-qualified.
- **tradability:** informational only, hedgeable, inventory-bound,
  primary-market-only, non-transferable, prohibited.
- **evidence quality:** finalized/rooted, provisional, stale, contradicted,
  missing.

Coverage is not universal anomaly detection. Unknown and blind-spot cells are
first-class outputs.
