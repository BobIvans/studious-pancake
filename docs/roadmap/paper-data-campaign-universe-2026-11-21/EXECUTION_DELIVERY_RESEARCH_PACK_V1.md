# EXECUTION DELIVERY RESEARCH PACK — JITO AND ALTERNATIVES (RESEARCH ONLY)

**Status: all providers `RESEARCH_ONLY_DISABLED`. Role: `transaction_delivery` research, zero submission.** This pack enables **no submission, no tip, no transport/adapter code**, and does not activate any provider. It exists so a future, separately authorized benchmark compares providers on **identical offline/historical benchmark evidence** — never on vendor marketing.

Vendor values below are dated observations from official docs checked **2026-11-21**; **they expire**. Refresh exact endpoint, region, plan, tip/minimum, quota, operator/correlation group and inclusion semantics during later source intake. Do not transfer these numbers into production config.

## 1. Provider matrix (status is not activation)

| Provider | Mechanism / published-doc notes (checked 2026-11-21) | Cautions / qualification state |
|---|---|---|
| `jito_block_engine` | Auction/tip path via `sendTransaction` / `sendBundle`; bundle max 5 transactions, sequential atomic all-or-nothing; one transaction can use bundleOnly/revert protection | Jito tip does not prioritize non-Jito leaders; ACK or bundle status is **not** settlement; preserve `docs/pr130_jito_mev_policy.md`; ShredStream was sunset 2026-09-05 — a **data-feed change**, not Block-Engine removal |
| `helius_sender` | Sender Max path and SWQoS-only path; published SWQoS-only minimum tip **0.000005 SOL**; Sender Max minimum **0.001 SOL** | Minimum is not a guaranteed inclusion price; low-tier SWQoS-only is best-effort and does not receive priority-tip-buffer treatment |
| `astralane_iris` | Advertises leader-aware/staked routing and dynamic clearing-tip ceiling/rebate | **`VENDOR_CLAIM_UNVERIFIED`** until measured by the same workload and landed outcomes; no repo pin exists |
| `bloxroute_trader_api` | Advertises multi-path broadcasting (RPC, block engines, staked connections, relays); current docs specify min tip | Provider-specific minimum/tip/region/terms; do not assume winner-only cost or universal leader coverage |
| `0slot` | Publishes dedicated SWQoS tiers and tier-dependent TPS/tip schedule | Validate current tier, eligibility, rate quotas, region and commercial terms; no repo pin exists |
| `direct_governed_rpc_swqos` | Baseline path; SWQoS needs validator/provider peering/trusted relationship | Baseline comparator only; a paid request or a public RPC URL is not SWQoS access |

Existing policy owners to preserve: `src/submission/jito_mev_policy.py`, `docs/pr130_jito_mev_policy.md`, MPR-04 isolated-signer boundary (`docs/mpr04_isolated_signer_jito_canary_boundary.md`). First-live policy (PR130): exactly one strategy transaction, Jito single-transaction path, one tip in the same transaction, static non-ALT tip account, no standalone tip transaction, no multi-transaction bundle for first live. Bundle ACK/status is not settlement proof.

## 2. Benchmark methodology (future, separately gated)

All five providers are measured with **identical offline/historical benchmark attempts**:

- Same candidate transaction corpus (replayed historical slots/state; no live submission).
- Metrics per provider: inclusion rate, landing latency distribution, effective tip distribution, ACK-to-settlement delta, failure modes (drop, silent loss, duplicate landing, replacement behavior).
- Always record operator/correlation group and independence from other measured providers.
- A relay ACK, RPC signature receipt, Jito bundle id or "accepted" response is never counted as a landing; landings are confirmed only from ledger reconciliation.
- Never assume tips are winner-only, relays are equivalent, or Jito is the only block-inclusion path.

## 3. Escalation ladder (each step is a separate, human-authorized PR)

1. **Offline bid replay** — pure local computation against pinned historical data (safe under this pack's constraints).
2. **Provider delivery telemetry with signing/submission still disabled** — latency/availability/endpoint probes, no transaction content.
3. **Only a distinct, human-authorized, budgeted canary may submit** — under PR130 first-live policy, MPR-04 signer isolation, and a separate cost policy (see `RELAY_COST_POLICY_SPEC_V1.md`).

## 4. Retry / fan-out invariants (binding for any future implementation)

- **Do not implement "resend with a higher tip until success."**
- Re-sending the same still-valid signed bytes is the same transaction/signature and can be safe with **bounded retries/backoff**.
- Changing tip or compute price changes the message and signature: the prior version may still land and the replacement becomes a **second executable attempt**. New attempts must wait for conclusive settlement/expiry or use an explicit on-chain idempotency/nonce/slot guard, and re-evaluate the route against fresh state.
- Multi-relay fan-out is not automatically free; one transaction can pay more than one relay-specific tip, and separate transaction variants have distinct signatures/landings and duplication risk. Never assume "we pay only the winner" without provider contracts and measured ledger reconciliation.
- Do not hardcode 70/30 or a fixed percentage split; one provider's tip is not automatically understood by another.
- Zero default live tips; no signer/sender/relay activation under this PR.
