# PR-010 canonical feasibility engine

Verified on 2026-07-19 against official docs:

- Solana fees: base fee plus optional prioritization fee; priority fee is `ceil(compute_unit_price * compute_unit_limit / 1,000,000)` lamports and the protocol fact remains 5,000 lamports per signature for base fee references: https://solana.com/docs/core/fees
- `getFeeForMessage`: returns the lamports a cluster would charge for the serialized legacy or v0 message; result value is `u64 | null`, so `null` is unknown/fail-closed: https://solana.com/docs/rpc/http/getfeeformessage
- `getMinimumBalanceForRentExemption`: rent exemption is parameterized by account data length and returns the minimum lamports for that account size: https://solana.com/docs/rpc/http/getminimumbalanceforrentexemption
- Associated Token Accounts: ATA derivation includes wallet owner, mint, and Token or Token-2022 program; the created account is still owned by the selected token program: https://solana.com/docs/tokens/basics/create-token-account
- Token-2022 transfer fees: transfers include an expected fee for the mint's transfer-fee configuration and Token-2022 program: https://solana.com/docs/tokens/extensions/transfer-fees
- Jito: bundles currently enforce a 1000 lamport minimum tip, but that is not a landing guarantee: https://docs.jito.wtf/lowlatencytxnsend/

## Canonical capital formula

```text
wallet_spendable_lamports = wallet_balance_lamports
                           - protected_reserve_lamports
                           - outstanding_attempt_budget_lamports

current_success_debit_cap = base_fee_lamports
                          + priority_fee_cap_lamports
                          + exactly_one_tip_lamports
                          + new_account_rent_lamports
                          + temporary_wsol_funding_lamports
                          + other_native_debit_cap_lamports

future_failure_budget = remaining_allowed_failure_attempts
                      * failed_attempt_charge_cap_lamports

required_operational_lamports = current_success_debit_cap
                              + future_failure_budget
```

The capital gate approves only when `required_operational_lamports <= wallet_spendable_lamports`. Flash-loan principal is never deducted from wallet SOL.

## Canonical guaranteed-profit formula

```text
guaranteed_route_surplus = guaranteed_min_final_output
                         - exact_required_repayment
                         - non_embedded_token_costs

converted_native_costs = convert_cost_up(
    base_fee + priority_fee_cap + exactly_one_tip + non_refundable_native_costs,
    fresh SOL/settlement rational conversion
)

guaranteed_net_profit = guaranteed_route_surplus
                      - converted_native_costs
                      - profit_safety_buffer
```

The economic gate requires both `guaranteed_net_profit >= min_absolute_net_profit` and integer ROI bps `>= min_net_profit_bps`.

## Gate order and result semantics

`TradeFeasibilityEngine.evaluate` is deterministic for identical snapshots, policy, and clock. It checks completeness/freshness, provider capacity, route guarantees, exact repayment, compiler transaction diagnostics, wallet operational SOL, then guaranteed profit/ROI. PR-010 exposes `feasible_for_next_stage` for pre-simulation approval; it does not expose a live `should_submit` permission.

## 0.015 SOL example

For `wallet_balance=15_000_000`, `protected_reserve=5_000_000`, `outstanding=1_000_000`, `base=5_000`, `priority=1_000`, `tip=1_000`, no new ATA rent, and one future failure at `6_000`, spendable is `9_000_000`, current success debit is `7_000`, future failure budget is `6_000`, and required operational SOL is `13_000`, leaving `8_987_000` lamports. This is only a fixture; it is not a universal live-safe reserve.

## Optimal sizing

`OptimalTradeSizer` intersects provider, route, and risk bounds; evaluates a bounded integer coarse grid plus optional seeds through the same engine; and chooses maximum guaranteed net profit. Ties prefer smaller principal, then smaller native debit, then lower price impact. `max_evaluations` is enforced as a hard quota.
