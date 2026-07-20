# PR-032 — Capital-aware sizing and atomic reservations

This PR adds a fail-closed native SOL capital gate. It does **not** enable
live trading, does not submit transactions, and does not bypass the existing
PR-026 runtime defaults.

## Boundary

The new `src.economics.capital` module answers three questions before a
candidate can move toward planning/compilation:

1. Is the wallet SOL balance sufficient after subtracting protected reserve
   and active reservations?
2. Is the candidate still profitable after base network fee, priority fee,
   Jito tip, non-refunded rent, protocol fee, slippage and uncertainty
   buffers?
3. Can the candidate reserve the required worst-case wallet SOL atomically so
   another concurrent candidate cannot spend the same balance?

The module is intentionally side-effect free. A future planner/simulator must
provide the final `getFeeForMessage` result, rent/ATA estimates, repayment,
conservative `min_out`, and buffers.

## Native SOL accounting

The wallet pays at least:

- base transaction fee from Solana `getFeeForMessage`;
- priority fee;
- Jito tip when a Jito path is later selected;
- peak rent/ATA/wSOL lamports that may be temporarily locked;
- policy contingency buffer;
- a protected reserve that is never considered spendable.

`0.015 SOL` is therefore not treated as fully available capital. With the
default PR-026 reserve of `10_000_000` lamports, only `5_000_000` lamports are
available before active reservations and worst-case fees/rent.

## Profit model

PR-032 accepts native/wSOL-denominated conservative economics only:

```text
gross = guaranteed_min_out_lamports - flash_repayment_lamports

conservative_net =
  gross
  - protocol_fee_lamports
  - base_network_fee_lamports
  - priority_fee_lamports
  - jito_tip_lamports
  - rent_loss_lamports
  - slippage_buffer_lamports
  - uncertainty_buffer_lamports
```

The candidate is rejected unless `conservative_net` is positive and at least
`minimum_net_profit_lamports`.

Non-native settlement assets must be converted upstream using verified
oracle/conversion evidence before entering this gate. Unknown or uncertain
value is a normal `NO_TRADE` outcome.

## Reservation lifecycle

The in-process lifecycle is:

```text
evaluated -> reserved -> released
```

Durable persistence, startup recovery and cross-process fencing remain in
PR-041. The local ledger still enforces the PR-032 invariant that two
concurrent candidates cannot reserve the same available lamports inside one
runtime process.

## Stable no-trade reasons

Rejections are returned as stable `NoTradeReason` values, including:

- `insufficient_native_balance`;
- `priority_fee_exceeds_policy`;
- `jito_tip_exceeds_policy`;
- `peak_rent_exceeds_policy`;
- `flash_loan_size_exceeds_policy`;
- `non_positive_conservative_net_profit`;
- `below_minimum_net_profit`.

These reason codes are suitable for future paper/shadow journals and metrics.

## Validation

Added unit tests cover:

- `0.015 SOL` protected reserve behavior;
- positive reserve/release lifecycle;
- double-spend prevention across concurrent candidates;
- negative and below-threshold conservative net profit;
- policy caps for priority fee, Jito tip, peak rent and flash-loan size;
- integer-only money inputs and `getFeeForMessage` payload parsing.
