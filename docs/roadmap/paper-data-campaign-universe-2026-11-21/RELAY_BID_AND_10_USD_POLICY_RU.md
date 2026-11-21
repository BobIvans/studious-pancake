# RELAY / BID / $10 COST POLICY — RESEARCH SPECIFICATION ONLY

## 1. Clarify what Jito is and is not

Jito ShredStream was sunset on 2026-09-05. That removed a low-latency data feed; it did **not** remove Jito Block Engine or Jito transaction submission. Shreds are data/ledger-propagation inputs, not a universal public mempool of pending user transactions. A shred source must be separately qualified for latency, completeness, loss/reordering, permissions and operator correlation.

Jito's bundle/auction path is one way to compete for block inclusion. It is not the only way. Distinguish:
- **Priority fee:** Solana transaction fee component based on requested compute-unit limit and CU price.
- **Jito tip:** an instruction in the strategy transaction/bundle that bids in Jito's auction.
- **SWQoS/staked connection:** provider-to-validator/RPC peering and forwarding path, not a generic “tip to enter block.”
- **Relay/sender:** the service transports the transaction; transport ACK/bundle id is not chain settlement.
- **Data feed:** shreds/account/slot stream; separate from transaction sender.

## 2. Provider candidate matrix (status is not activation)

| Candidate | Mechanism / public docs note | Campaign role now | Cautions / current qualification |
|---|---|---|---|
| Jito Block Engine / `sendTransaction` / `sendBundle` | Auction/tip path; bundle max five transactions, sequential atomic all-or-nothing; one transaction can use bundleOnly/revert protection | Benchmark candidate; no send in this pack | Jito tip does not prioritize non-Jito leaders; ACK or bundle status is not settlement; preserve `docs/pr130_jito_mev_policy.md` |
| Helius Sender | Sender Max path and SWQoS-only path; published SWQoS-only minimum tip is 0.000005 SOL; Sender Max minimum is 0.001 SOL | Cost-sensitive comparison candidate | Minimum is not a guaranteed inclusion price; low-tier SWQoS-only path is best-effort and does not receive priority-tip-buffer treatment |
| Astralane Iris | Advertises leader-aware/staked routing and dynamic clearing-tip ceiling/rebate | Comparison candidate | Treat ceiling/rebate and performance as vendor claims until measured by same workload and landed outcomes |
| bloXroute Trader API | Advertises multi-path broadcasting (RPC, block engines, staked connections, relays); current docs specify min tip | Comparison candidate | Provider-specific minimum/tip/region/terms; do not assume winner-only cost or universal leader coverage |
| 0slot | Publishes dedicated SWQoS tiers and tier-dependent TPS/tip schedule | Comparison candidate | Validate current tier, eligibility, rate quotas, region and commercial terms |
| Direct approved RPC/SWQoS | Baseline path; SWQoS needs validator/provider peering/trusted relationship | Baseline comparator only | A paid request or a public RPC URL is not SWQoS access |

All vendor values are dated observations from docs checked 2026-11-21; they expire. Refresh exact endpoint, region, plan, tip/minimum, quota, operator/correlation group and inclusion semantics during the later source intake. Don't transfer numbers into production config.

## 3. Dynamic bid model — design, not activation

The future bid model must jointly price:
- base fee per signature;
- priority fee = requested CU limit × CU price (with protocol scaling/rounding);
- relay/auction-specific tip (only where the chosen route uses it);
- lender fee and exact repayment;
- account/rent/setup, ATA or sponsor fees where legitimately required;
- source/data costs and compute;
- failed-attempt/revert cost and opportunity expiry.

For candidate size (x), use a conservative value cap:
[
B_{max}(x) = max(0,; 	ext{expected gross edge}
 - 	ext{swap fees}
 - 	ext{flash fee}
 - 	ext{base/priority fee}
 - 	ext{rent/setup}
 - 	ext{other known costs}
 - 	ext{minimum required net})
]
The sum of **priority fee + route-specific tip + any provider charges** must remain under this cap and the operator's remaining hard budget. Unknown costs imply no bid/route admission.

A future policy may use fresh Jito tip-floor quantiles plus observed leader coverage/auction outcomes; priority fee should use current local fee estimates and exact CU budget. Do not hardcode 70/30 or a fixed percentage split. Different delivery services use different incentives; one provider's tip is not automatically understood by another.

## 4. Retry and fan-out invariants

**Do not implement “resend with a higher tip until success.”**
- Re-sending the same still-valid signed bytes is the same transaction/signature and can be safe with bounded retries/backoff.
- Changing tip or compute price changes the message and signature. The prior version may still land; the replacement can then be a second executable attempt. New attempts must wait for conclusive settlement/expiry or use an explicit on-chain idempotency/nonce/slot guard and re-evaluate the route against fresh state.
- A relay ACK, RPC signature receipt, Jito bundle id, or “accepted” response is not a finalized landing.
- Multi-relay fan-out is not automatically free. If relay-specific tip instructions are embedded in one transaction, the transaction can pay more than one tip; if separate transaction variants are created, each has distinct signature/landing and duplication risk. Never assume “we pay only the winner” without provider contracts and measured ledger reconciliation.
- Preserve first-live policy from `docs/pr130_jito_mev_policy.md`: exactly one strategy transaction, Jito single-transaction path, one tip in the same transaction, static non-ALT tip account, no standalone tip transaction, no multi-transaction bundle for first live. Bundle ACK/status is not settlement proof.
- First future experiment should be an offline bid replay; second is provider delivery telemetry with signing/submission still disabled; only a distinct, human-authorized, budgeted canary may submit.

## 5. $10 user budget — proposed hard envelope

Treat $10 as an **aggregate future canary execution-cost ceiling**, not $10 per attempt and not as proof that the loan principal or the lender is free. The $10 must cover all realized flashloan fees, base/priority fees, route-specific tips, provider charges and failed transaction costs. Keep external data subscriptions and storage/RPC spend in a separate, explicit budget; first capture is no-subscription / operator-approved free-tier only.

Proposed controls for a future, separately approved canary:
- hard campaign cap: USD 10 equivalent across all execution-cost categories;
- no bid is permitted unless remaining balance after maximum exposure is sufficient;
- per-attempt cap is derived from expected all-in net and set by operator after offline replay (not preset in this pack);
- daily and provider-specific sublimits, max physical attempts, max cost per unique opportunity and emergency stop;
- fetch USD conversion from a trusted current price source for budget metering; if unavailable/stale, block new bids;
- account for failed transactions and fees in actual ledger; do not assume an unlanded transaction is free;
- zero default live tips and no signer/sender/relay activation under this PR.

This does **not** mean spend $10 to discover a strategy. The first data campaign should require no transaction-fee or tip budget.

## 6. Data-feed candidates — separate from senders

- Yellowstone gRPC / accountSubscribe / standard WebSocket sources: potentially enough for first market-state campaign; measure slot/notification gap and rooted catch-up.
- Helius LaserStream: optional low-latency account/transaction stream; verify plan/limits and source/operator independence.
- DoubleZero Edge: Jito's recommended ShredStream successor candidate with trial; commercial pricing varies by IP/region after trial. Optional, not a prerequisite for data-only capture.
- LocalShred Lite: third-party free-tier claim, not yet verified in-repo; intake as `VENDOR_CLAIM_UNVERIFIED`, measure packet gap/reordering, slot coverage, latency and replayability. Don't rely on the pasted 100–500ms or “same speed” claim.
- OrbitFlare: the user-provided historical note's free trial/pricing claims need a fresh official source/terms check before it enters the active shortlist; keep as research candidate pending intake.
- Never call a shred feed “mempool” or assume it gives intent for every unconfirmed swap.

## 7. Safety

No signing, transaction creation for submission, sending, borrowing, tip payment, retry escalation, fanout or canary in this assignment. A future signer remains isolated under MPR-04 and PR-130. Live remains hard denied.
