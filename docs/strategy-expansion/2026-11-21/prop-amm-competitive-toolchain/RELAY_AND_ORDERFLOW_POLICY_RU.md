# Relay policy и легитимный order-flow design

## 1. Основная политика

Никакой stealth/camouflage реализации. Не рандомизировать размер или время, чтобы скрывать арбитражный интент от Prop AMM / solver. Не подменять CPI caller, не имитировать сторонний агрегатор, не обходить котировочные ограничения или risk filters.

Разрешённые формы order splitting:
- уменьшение price impact по измеренной amount-specific liquidity curve;
- распределение по реально независимым и доказанным route edges;
- соблюдение CU/account/packet limits;
- выполнение общей resource reservation и lender capacity constraints.

Если используется flashloan, все legs, repayment и output guard должны оставаться atomic в поддерживаемом transaction plan. Если route split выходит за границы атомарной flashloan-транзакции — reject; не разбивать заём на независимые сделки ради скорости/маскировки.

Time jitter разрешён только как внутренняя queue/load-control функция, чтобы избежать локального thundering herd и соблюсти provider quotas. Он не должен менять trade semantics или моделироваться как средство уклонения от чужой детекции.

## 2. Sender/relay facts

### Jito

- Jito ShredStream — market-data feed; official notice says it was sunset on 2026-09-05.
- Jito Block Engine / transaction send — separate product and remains part of submission architecture.
- Official docs describe bundle maximum five signed transactions, sequential and atomic all-or-nothing. Bundle ACK/bundle ID is transport information and not settlement.
- Current repo policy in docs/pr130_jito_mev_policy.md is stricter for first-production: one strategy tx, JITO_SINGLE/sendTransaction, optional bundleOnly revert-protection mode, one tip within that transaction, static non-ALT tip account, no standalone tip tx, no multi-tx bundle.
- Do not infer the Jito bundle min-tip floor as the universal sendTransaction min tip. Tip competition changes with slot demand; no fixed tip guarantees inclusion.

### Helius Sender

- SWQoS-only public minimum listed as 0.000005 SOL, best effort and below priority tip buffer.
- Sender Max minimum listed as 0.001 SOL and participates in higher-speed path/tip buffer.
- These are product tiers with different performance. They must be compared separately in a measured sender qualification, not treated as one low-cost channel.

### Astralane Iris

- Vendor markets region-aware/private routing and dynamic tip ceiling/clearing-price or rebate behavior. Record as vendor claims until reproduced with timestamped samples and invoice/on-chain reconciliation.
- iris-rs is a separate public beta client/repo under AGPL-3.0; license compatibility must be reviewed before reuse. Do not infer the vendor service license from the client repository license.
- Old pasted minimum of 0.00001 SOL and default TPS must be treated as unverified/stale until current signed plan and endpoint docs establish them.

### Syncro / P2P.org

- Current P2P product page and older help-center text show inconsistent public/secured per-landed transaction prices and tiers. Current product page (checked 2026-11-21) lists 0.0002 SOL public and 0.00015 SOL secured per landed transaction, plus a 1-week new-client trial; older help page lists other values. Treat pricing as contract-bound and obtain written confirmation before inclusion.
- “Pay per landed tx” in vendor terms is not a promise of payment only to the fastest relay when client fans out across competing vendors.

### DoubleZero / OrbitFlare / Triton / GetBlock / Helius / ValidatorsDAO

These are feed options, not transaction relay equivalents. Do not route a signed transaction through them merely because they deliver shreds or Geyser data. Feed subscription budgets and sender tips are distinct cost centers.

### Nozomi / BoltTx / Sanctum Gateway

No authoritative current public endpoint+pricing+billing contract was validated in this sweep. Keep them as UNVERIFIED candidate leads. No credentials, endpoints, rate constants, feature flags or relay clients should be added until vendor terms and semantics are reviewed.

## 3. Why the proposed pay-only-winner fan-out is not accepted

A single signed transaction has one fixed message. If it contains a Jito tip transfer to a Jito tip account and is forwarded to Helius/Astralane, the Jito tip instruction remains embedded; it does not become that other vendor’s native tip. A provider may charge separately, include its own fee, offer a refund/rebate, or have conditions not visible in the signed transaction. An identical signature can be deduplicated by chain execution, but that fact does not settle vendor billing.

To send provider-specific tips, the transaction message changes, producing different signatures and independently executable variants. Both variants may land unless there is a proven on-chain idempotency guard or a previous variant is provably expired/settled. Therefore no tip escalation or re-sign-and-fanout loop.

Future multi-relay work requires:
1. exact official per-product terms and current signed plan;
2. identical byte/signature forwarding test;
3. clear fee payer and provider tip/billing semantics;
4. landed vs failed vs duplicate billing experiment with invoices;
5. signature and durable intent dedupe;
6. expiry/replacement and finality handling;
7. total cost measured including failed tx fees, priority fee, tips and off-chain charges;
8. RISK / MPR-04 approval and separate PR.

Until then: keep PR130 canonical Jito path and keep other sender adapters disabled.

## 4. Safe bid policy

Any future offline bid evaluator must calculate:
- gross expected route edge distribution and probability of staleness;
- probability of landing conditional on slot/leader/relay and current bid;
- transaction base fee and compute-unit priority fee;
- one chosen relay/provider charge and embedded tip;
- lender fee, rent/setup, protocol, aggregator, transfer and Token-2022 fees;
- failed transaction/revert costs;
- net expected value and worst-case all-in loss.

Bound by route edge and operator max-cost config. Never use unbounded increase/re-sign/retry loops. Resending identical still-valid bytes is one signature but still must respect bounded rate limits and expiration. A replacement with a changed tip is a new independently executable transaction and needs a settled/expired predecessor or a same-transaction idempotency guard.

## 5. Current default

No send or provider access is enabled by this pack. Data capture requires its own authorized source manifest; paper requires campaign authority and R06/QPR; sign/send requires isolated signer MPR04 and current live boundaries. $10 ceiling from PR #664 is a proposed future aggregate canary budget and is disabled, not an allowance for current feed subscriptions or per-attempt tips.


## 6. Current official provider tip matrix (supersedes conflicting older example figures above)

Current reviewed documentation distinguishes these endpoint/product floors:

| Provider / product | Minimum on-chain tip | What it means |
|---|---:|---|
| Jito bundle | 1,000 lamports (0.000001 SOL) | Bundle consideration floor; not a competitive bid. PR130 JITO_SINGLE policy governs this repo. |
| Helius SWQoS-only | 5,000 lamports (0.000005 SOL) | One SWQoS path; best effort below 0.001 SOL and outside the priority tip buffer. |
| Helius Sender Max | 1,000,000 lamports (0.001 SOL) | Internal multipath Sender service plus priority tip buffer/auction. |
| Astralane Iris | 10,000 lamports (0.00001 SOL) | Official translated endpoint document; confirm account plan. |
| Astralane sendPaladin | 100,000 lamports (0.0001 SOL) plus documented CU price floor | Distinct method; do not conflate with Iris. |
| Syncro public | 200,000 lamports (0.0002 SOL) | Current P2P docs; built-in multi-channel delivery. |
| Syncro private | 150,000 lamports (0.00015 SOL) | Current P2P docs; API-key endpoint and built-in multi-channel delivery. |
| bloXroute Trader API | 1,000,000 lamports (0.001 SOL) | Required on-chain transfer to bloXroute wallet; internal multi-path broadcast and retry-until-land/expiry. |
| 0slot | UNKNOWN | No current authoritative minimum/tip billing terms verified in this audit. |
| Sanctum / BoltTx / Nozomi | UNKNOWN | Do not put guessed amounts into config; require current official endpoint and billing terms. |

Provider references:
- Jito: https://docs.jito.wtf/lowlatencytxnsend/
- Helius: https://www.helius.dev/sender
- Astralane Iris: https://astralane.gitbook.io/docs/mandarin-docs/huan-ying-lai-dao-astralane/duan-dian-he-pei-zhi
- Astralane tip rebate: https://astralane.gitbook.io/docs/low-latency/submit-transactions/tip-refunds
- Syncro: https://docs.p2p.org/docs/syncro-sender-pricing-rate-limits
- Syncro multipath/retry: https://docs.p2p.org/docs/syncro-sender-optimizing-performance
- bloXroute: https://docs.bloxroute.com/solana/trader-api/introduction/tip-and-tipping-addresses and https://docs.bloxroute.com/solana/trader-api/quick-start/transaction-submission

Important provider semantics:
- Helius says Sender has no credits and payment is through its SOL tip; Sender Max routes internally across high-speed paths.
- Syncro says a single sendTransaction already routes through multiple channels; do not client-retry to simulate its internal paths.
- bloXroute says Trader API broadcasts through multiple paths and retries until land or expiry; repeated client resubmission is not required.
- Astralane rebate eligibility varies with whether the transaction is shared with other RPCs/landing services; direct-only submission can qualify for higher rebates.
- Minimum tips are floors, not competitive bids or inclusion guarantees.
- Save exact public pricing and rebate/tip rules with provider product tier and retrieval date. No 0slot amount is inferred.

## 7. Relay tip transfer is not winner-aware

The tip destination and amount are part of the signed transaction message:
1. One transaction with one provider tip: if it lands, the fixed tip goes to that account regardless of which relay forwarded the bytes.
2. One transaction with tip transfers to every provider: if it succeeds, every tip instruction executes. You pay all tips, not only the provider that forwarded it.
3. One signed transaction fanned out to several providers: the same signature is deduplicated on-chain, so the trade should execute once. But its embedded tip still goes to the fixed recipient; off-chain provider billing/eligibility may be separate. Do not assume non-winning relays are free.
4. Different signed variants with a different tip for each provider have different signatures. More than one can land and execute the same arbitrage/flashloan flow, potentially causing duplicate trades and multiple tip transfers.
5. There is no generic Solana instruction that asks which off-chain relay delivered the transaction and pays only that relay. A winning-relay-only rule would require a documented provider-side rebate/billing feature, not a normal SystemProgram transfer.

## 8. Provider-native multipath versus cross-provider fan-out

- Provider-native multipath: one request to Helius Sender Max, Syncro or bloXroute is internally propagated over that vendor's own pathways. This is one vendor endpoint contract and one tip profile.
- Cross-provider fan-out: the bot submits the same signed bytes to Jito, Helius, Astralane, Syncro and bloXroute. The tip recipient does not switch based on which path wins; billing and rebate eligibility differ. Astralane explicitly says sending the same transaction to other RPCs/landing services can reduce its higher rebate tier.
- bloXroute's Global plus closest-region parallel recommendation is a provider-specific regional submission pattern inside bloXroute. It is not evidence that cross-vendor fan-out incurs charges only once.

## 9. Current bot policy

- Preserve PR130 first-production path: JITO_SINGLE, one strategy transaction, one in-transaction Jito tip, non-ALT tip account, no standalone tip, no multi-transaction bundle.
- Keep one provider profile per signed transaction.
- For future provider selection, measure each provider independently using controlled harmless test transactions or separately approved canaries, not alternate signatures of one live flashloan.
- Use provider-specific all-in cost, landing probability, p50/p95/p99 time, expiry, retry, failure fee, rebate/refund and finality evidence.
- For each independent opportunity in a conflict-free portfolio, one provider may be selected per transaction. Different independent transactions can later be dispatched concurrently after signer/portfolio/resource gates pass.
- Do not place all provider tip transfers inside each flashloan transaction.

Full machine-readable profile: RELAY_PROVIDER_TIP_PROFILES_V1.json. Unknown means BLOCKED, never zero.
