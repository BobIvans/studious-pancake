# Параллельная идентификация возможностей и атомарное исполнение flashloan

## 1. Не плодить второй детектор

Одна каноническая market-data/source-generation шина и один event/capture owner. Новые инструменты должны быть дополнительными adapters/strategy evaluators к существующей системе, а не параллельными системами, которые независимо считают одни и те же аномалии.

- Источник/парсер публикует canonical observations.
- Внешний KADES/CADES hint (если когда-нибудь пройдёт проверку) может только поднять приоритет анализа.
- Уже существующий SX-18 (#657) владеет multi-strategy runtime fanout/composition. Использовать его StrategyRegistry / OpportunityConsumer / existing cancellation/deadline/backpressure design; не создавать второй orchestrator.
- R13 владеет quote normalization; reuse the same amount/token/time/source-generation semantics.
- pmm-sim, Jupiter V2 and direct instruction builder are candidate evaluators / simulation routes, not three detectors.

## 2. Parallel candidate evaluation

На одном frozen market generation G:
1. Canonical source adapters publish state and event observations with full provenance.
2. Existing StrategyRegistry fans out N registered strategy evaluators on a bounded worker pool.
3. Each evaluator receives an immutable snapshot and the same source-generation identifier.
4. Evaluators produce candidate records or typed rejection; none builds/signs/sends from discovery callback.
5. Normalize and deduplicate candidates by canonical route identity and full underlying pool lineage.
6. Rank on exact amount-specific all-in net outcome, state freshness, probability of completion and cost/risk budget.
7. Simulate Top-K with pmm-sim and/or repository exact-simulation owner in parallel, with deterministic timeout/cancellation and no external state mutation.
8. The existing SX-12 portfolio optimizer / ConflictScheduler selects a compatible portfolio, reserving shared resources once.
9. For each accepted candidate produce one self-contained atomic flashloan transaction plan.

Candidate identity must bind:
- cluster/genesis and source generation;
- exact input/output mint, token program, decimals and Token-2022 extensions;
- raw integer input amount;
- ordered route legs with program id, pool id, direction and account lineage;
- every state dependency and slot/hash;
- lender/reserve/resource id, borrowing amount and fee;
- min-out/post-balance/repayment guard contract;
- quote expiry, build hash, simulated message hash.

Two candidates that share an underlying pool/tick-array/bin-array/orderbook, lender reserve, writable token account, fee payer or writable oracle/account are not independent merely because they have different strategy IDs. Jupiter route aliases and direct paths that traverse the same pool must deduplicate as correlated exposures.

## 3. Selecting multiple opportunities safely

Parallel search and simulation are allowed for candidates with the same immutable evidence generation.

Parallel execution means several distinct, individually profitable and independently repayable transactions may be scheduled concurrently only when:
- every candidate is independently complete and self-contained;
- all flashloan borrow/swap/output-check/repay instructions fit in its own single transaction;
- exact resource lock sets are compatible (no write-write or read-write collision);
- lender capacity is valid for all accepted notional simultaneously;
- wallet/fee-payer balances and daily budget cover all selected transactions and failure fees;
- each candidate has its own expiry, reservation, intent, simulation receipt, transaction message hash and finality record;
- source state is revalidated immediately before construction/signing.

Use existing ConflictScheduler and SX-12 optimizer. The scheduler should build a conflict graph over actual read/write account sets and choose only a compatible set. Read/read overlap may be compatible; any write/read or write/write conflict must be serialized or rejected/requoted. Include shared fee payer and shared borrower/ATA accounts in lock sets. If a single fee payer or lender vault makes all trades conflict, concurrency correctly remains one; do not fake concurrency by splitting a large route into fragmented independent signatures.

Do not create wallets or ATAs as an optimization. Use only already approved identities/accounts. If no independent fee payers, token accounts and lender capacity exist, run strategy evaluation in parallel but execute sequentially.

## 4. Flashloan atomicity

For every candidate, the supported transaction plan is:

borrow(amount) -> swap leg(s) -> same-transaction output/balance invariant -> repay(amount + exact fee) -> retain profit

The output invariant must cover:
- exact base-unit balances, decimals and Token-2022 transfer fees/hooks;
- explicit venue min_amount_out, where semantics are correct;
- otherwise a verified same-transaction post-balance check;
- lender repayment and fee at the exact pinned state/rule;
- positive residual profit after every protocol/aggregator/transfer/provider/network/rent/priority/tip/failure cost.

If a route is split over separate transactions and requires all pieces to succeed for repayment/profit, reject it under the current first-production contract. Solana single transactions are atomic but failed transactions still incur fees; the current network documents packet/message limits and recent-blockhash expiry, so the builder must measure the actual serialized transaction and lifetime. Official transaction docs: https://solana.com/docs/core/transactions.

Jito bundles can support up to five ordered atomic transactions as a Jito-specific product, but repository PR130 currently limits the first-production route to one strategy transaction via JITO_SINGLE. Do not silently replace this rule with a multi-transaction bundle.

## 5. Signing boundary — no private key in the bot or Codex

The strategy/runtime produces a fully formed unsigned transaction and an immutable sign request. It does not load secret keys.

Each sign request binds:
- exact serialized message hash and transaction signature domain;
- route/candidate id and source/config generations;
- exact wallet/fee-payer and lender/resource reservation;
- input amount, max notional, min expected net, max all-in cost;
- recent blockhash/last-valid slot or durable nonce;
- expiry and one-time intent id;
- simulation and economic-reconciliation receipts;
- emergency-stop status and operator policy hash.

MPR-04 isolated signer is the only future signing route. It must persist a durable intent before submission, reject duplicate/stale hashes and bind final human/second-person approval to exactly the same message hash and policy. Signing permission is per transaction, not a global ENABLE_LIVE toggle. The runtime must not be able to read private key bytes. The signer must never sign a message different from the approved hash.

## 6. Parallel submission — clarify two different meanings

Allowed design target: dispatch multiple different, independent and independently repayable trade transactions concurrently once their account/resource write sets are disjoint and all signer/live gates pass. Each opportunity has one canonical signed transaction and one configured delivery lane.

Not accepted: send provider-specific signed variants of the same opportunity to every relay and assume only the winner is charged. Provider billing and tip semantics are not identical; a changed tip instruction changes the message and signature. Same-signature dedupe on chain does not prove vendor billing. This remains disabled.

Current first-production send policy remains PR130: one strategy transaction, JITO_SINGLE / sendTransaction, one tip inside that same tx, no standalone tip tx, no multi-tx bundle, no ACK-as-settlement. Jito docs: https://docs.jito.wtf/lowlatencytxnsend/.

## 7. Bounded concurrency, backpressure and stop rules

- Default execution concurrency 1; discovery/simulation concurrency may be greater and must be bounded.
- Raise execution concurrency only after disjoint-lock tests, lender multi-borrow capacity proof, signer idempotency tests, durable finality receipts, installed MPR-05 soak and explicit separate operator authorization.
- Never dispatch all Top-K candidates. Only the selected compatible portfolio may proceed.
- Stop a route if source generation changes, quote expires, state gap/reorg occurs, exact account owner/layout mismatches, simulation diverges, lender capacity changes, shared lock is unavailable, cost cap would be crossed, or finality is unknown.
- After send, no retry with a newly signed message until the prior attempt is finalized/expired and route revalidated. Same signed bytes may only be retried under a bounded, idempotent provider contract and current PR130/MPR04.
- Keep all send/sign/borrow/live flags false in this agent task. Implement simulation and fake-signer conformance only.

## 8. Required tests

- N independent evaluators run in parallel on same immutable snapshot and output stable sorted results.
- One evaluator crash/timeout does not cancel unrelated evaluators; global generation drift invalidates all dependent candidates.
- Duplicate routes via Jupiter alias and direct DEX deduplicate by pool lineage.
- Different strategy IDs sharing pool accounts collapse into conflict.
- Read/read resources may run together; read/write and write/write conflict; shared fee payer and lender reserve block parallel dispatch.
- Portfolio optimizer never selects overlapping writes or exceeds total lender capacity/budget.
- Each candidate transaction independently repays its flashloan in the same transaction.
- Multi-part route requiring separate transactions is rejected unless an independently approved future bundle policy exists.
- Expired blockhash/quote or stale state refuses sign request.
- Fake signer refuses wrong message hash, duplicate intent, expired approval and mismatched config/source generation.
- Crash after intent but before submit does not permit a second send.
- Jito/provider ACK and bundle id never close an economic outcome; finality + balance/repayment reconciliation required.
- Parallel send is of distinct transactions only; a single trade's alternate tip/signature variants are rejected.
- Failure fees and partial portfolio outcomes are attributed to each route; never report aggregate "all succeeded" when one route failed.


## 9. Relay tip recipient is fixed at signing

A transaction with a Jito tip transfer remains a transaction that pays the Jito tip account even if another relay forwards the same bytes. Putting Jito, Helius, Astralane, Syncro and bloXroute transfers into one transaction pays all of them if it lands. Creating a separate signed tip variant per provider creates distinct independently executable transactions and risks duplicate flashloan routes. Therefore provider fan-out is not a conditional winner-payment mechanism.

Prefer one provider per signed transaction and use that provider's own internal multipath where it is part of the product (Helius Sender Max, Syncro, bloXroute). The provider tip table and rebate notes are in RELAY_PROVIDER_TIP_PROFILES_V1.json. Current bot policy remains PR130 JITO_SINGLE only.
