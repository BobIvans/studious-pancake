# RELAY COST POLICY SPECIFICATION — FUTURE / NOT ACTIVATED

**Status: research specification only.** This policy governs nothing until a separate, human-authorized canary PR exists; `future_canary_enabled` stays `false` and the first data campaign requires **zero** transaction-fee/tip budget.

## 1. Cost components — every row starts UNKNOWN

| Component | Definition | Initial state | Promoted only by |
|---|---|---|---|
| `base_fee` | Per-signature Solana base fee | UNKNOWN | measured/pinned evidence |
| `priority_fee` | Requested CU limit × CU price (with protocol scaling/rounding) | UNKNOWN | measured/pinned evidence |
| `relay_auction_tip` | Relay/auction-specific tip instruction, only where the chosen route uses it | UNKNOWN | measured/pinned evidence |
| `lender_fee` | Flash-lender fee + exact repayment | UNKNOWN | measured/pinned evidence |
| `rent_setup` | Account/rent/ATA/sponsor setup costs where legitimately required | UNKNOWN | measured/pinned evidence |
| `provider_cost` | Source/data/compute provider charges | UNKNOWN | measured/pinned evidence |
| `failed_attempt_cost` | Failed/revert attempt fees + opportunity expiry | UNKNOWN | measured/pinned evidence |

**Invariant: UNKNOWN cost blocks positive net result and route admission.** A candidate with any UNKNOWN component cannot be admitted; unknown is never zero. (A "free" documented flashloan is not a qualified zero-cost edge.)

Future bid cap (design, not activation, from pack §3): `B_max(x) = max(0, expected_gross_edge − swap_fees − flash_fee − base/priority_fee − rent/setup − other_known_costs − minimum_required_net)`; priority fee + route-specific tip + provider charges must stay under this cap and the operator's remaining hard budget. Do not hardcode 70/30 or any fixed split.

## 2. $10 semantics

`future_canary_total_execution_cost_usd_max: 10` in the campaign manifest is:

- an **aggregate future canary execution-cost ceiling**, not $10 per attempt;
- **not spend authorization** and not permission for CAPTURE_ONLY;
- not proof that the loan principal or the lender is free;
- expected to cover all realized flashloan fees, base/priority fees, route-specific tips, provider charges and failed-transaction costs, metered via a trusted USD price source (stale/unavailable source ⇒ block new bids).

This does **not** mean "spend $10 to discover a strategy": the first data campaign runs with zero transaction-fee or tip budget (`external_data_spend_usd_max: 0`, free-tier operator-approved only).

## 3. Retry policy

- Same-signature bounded retries with backoff only (same signed bytes, same transaction).
- **No tip-escalation ladder**: never resend with a higher tip until success. A tip change produces a new message+signature and a second executable attempt; it requires conclusive settlement/expiry or an explicit on-chain idempotency/nonce/slot guard plus fresh-state route re-evaluation.
- Failed transactions are accounted in the actual ledger; an unlanded transaction is not free.

## 4. Activation separation

Any future canary is a distinct, separately approved, budgeted PR with: hard aggregate cap (USD 10 equivalent across all execution-cost categories), no bid unless remaining balance after maximum exposure is sufficient, per-attempt cap derived from expected all-in net after offline replay, daily/provider sublimits, max physical attempts, max cost per unique opportunity, emergency stop, and PR130 first-live policy (one strategy transaction, one tip in the same transaction, static non-ALT tip account, no standalone tip transaction, no multi-transaction bundle). Until then: `future_canary_enabled: false`, zero default live tips, no signer/sender/relay activation.
