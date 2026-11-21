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
