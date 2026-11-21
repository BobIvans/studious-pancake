# Prop AMM: инструментальный стек и стратегия flashloan bot

## 1. Sight — low-latency market observation

### Источники-кандидаты

- **LocalShred Lite / DedicatedNodes:** первый бесплатный экспериментальный feed-кандидат. Зафиксировать, что провайдер рекламирует Lite как baseline уровня прежнего Jito ShredStream. Не переносить показатели платной LocalShred или bare-metal Amsterdam/Rotterdam на бесплатный Lite.
- **DoubleZero Edge:** multicast raw shreds через частную сеть. Рассматривать только как платный/тестовый feed с metro/seat economics, IP/route requirements, multicast/GRE setup и отсутствием retransmission; потери и полноту измерять.
- **OrbitFlare ShredStream:** UDP raw shreds, публично перечислены 8 регионов и $500/$1,000 monthly tiers. Trial и actual SLA должны быть письменно подтверждены.
- **Triton:** отделять Yellowstone/Geyser gRPC от raw shred streaming. На текущей странице raw shred streaming указан как платный продукт.
- **Helius:** LaserStream WebSocket/gRPC и raw Shredstream — разные products/tiers. Free RPC plan не означает бесплатные raw shreds. Preprocessed Transactions stream не следует считать полным аналогом raw feed: доступные поля/метаданные ограничены конкретным продуктом.
- **GetBlock:** raw shreds публично предлагаются как платный продукт; источники GetBlock дают разные trial details — before trial request obtain current written quote.
- **ValidatorsDAO / solana-stream и ERPC Stream SDK:** использовать как software/client option при pinning exact SDK version. UDP shreds и Geyser/gRPC могут различаться по completeness, order, commitment и replay. Ветка repo с v5 workspace dependencies не должна смешиваться с pasted text's v4 speed claims.
- **Supanode / self-hosted validator relay:** не runtime dependency на данном этапе; Supanode terms не подтверждены, self-host требует отдельной инфраструктурной оценки.

### Что измерять

Сравнивать не просто packet arrival, а timestamp-to-usable-state:
- time from provider receipt to decoded transaction/event;
- source slot, shred/FEC index, completeness, retransmit/reordering/drop rates;
- slot/root/fork changes and rollback correctness;
- age of every account needed for quote;
- independent operator / correlation-group identity;
- region, network RTT, CPU parse time, queue backlog;
- replay determinism and gap alarms.

Не заявлять «раньше конкурентов» по одной средней latency. P50/P95/P99, gap rate, state freshness, fork handling и useful-event lead time считаются по одному и тому же набору finalized/usable references.

## 2. Detection — parser and anomaly prioritization

### Reuse-first

- Подать события через существующий source catalog/governance, transport, observation schemas, market-state generation и replay pipeline.
- 0xfnzero/sol-parser-sdk — optional parser implementation candidate. На GitHub виден MIT, v0.11.0; versioned dependencies включают Solana SDK 4.0.1/Client 4.2.2 и Yellowstone 13.5.x. Репозиторий должен проверить совместимость с собственным Python/installed runtime and the canonical source path before accepting it. Its 10–20 μs claim is a local benchmark for selected handlers, not an end-to-end Solana lead.
- solana-arb-executor — MIT Claude/Codex execution-codegen skill and patterns; not a compiled arb executor library. Extract only reviewed dry-run risk-gate ideas if relevant; never install as runtime bot.
- The repository named solana-arb-framework by ototech7 is explicitly educational/not production and not Prop AMM coverage. Another same-name result is a Python mainnet-oriented bot with wallet/API credentials and live loop; do not import or run.
- KADES / CADES may be external anomaly hints only when a public API/schema, terms, retention, and measurable precision/recall are supplied. Never make it a source of truth, execution authority, pool identity, or quote.
- “Capture OS/Capture Engine” is not yet resolved to a canonical project. Use the repository’s existing capture stack, not an invented duplicate.

### Anomaly model

An anomaly signal is an analysis priority, not a trade instruction. It must include source provenance, observation generation, scope, confidence, timestamp, and expiry. It can schedule deeper quote/simulation for a pool, but it cannot bypass exact state, amount-specific quote, capital capacity, risk, or human authority.

## 3. Microscope — pmm-sim and SVM testing

### pmm-sim integration

Use LimeChain/pmm-sim as an isolated tool/test harness, not as a production runtime dependency initially. It documents:
- single route simulation;
- multi/nested route simulation;
- direct non-CPI swap for some Prop AMMs;
- benchmark mode.

Supported venues/versions shown in its README include HumidiFi swap v1/v2/v3, SolFiV2, ObricV2, ZeroFi, TesseraV, GoonFi and BisonFi. Exact program deployment, instruction and state layout must still be pinned independently.

Before use:
1. pin repository commit and license file;
2. resolve its mutable magnus git branch to immutable commit;
3. isolate Cargo workspace because pmm-sim uses Edition 2024, LiteSVM 0.10 and Solana SDK 3.0 dependencies;
4. materialize deterministic account snapshots with slot/generation/source hashes;
5. build a venue/version support table and reject unsupported variants;
6. compare simulator outputs with independent official/reference vectors and current exact quote math;
7. preserve every negative/revert/unsupported route.

Do not assume spoof CPI caller behavior is a valid or permitted production route. Any CPI caller mutation is excluded from strategy execution. The test harness may only assess explicitly documented instruction semantics with authentic caller identity.

### SVM roles

- **LiteSVM:** in-process SVM for deterministic program/instruction tests.
- **Mollusk:** focused instruction test and CU measurement harness.
- **Pinocchio:** low-level, zero-copy/no-std Rust library for writing Solana programs with lower overhead; not an off-chain router and not a guaranteed “84% CU savings” tool. Consider only if a measured on-chain program/CU/size bottleneck justifies a separate reviewed program PR.

None of these produces live market data or guarantees current venue solver quotes.

## 4. Router — Jupiter V2 plus direct instruction construction

### Jupiter Swap API V2

- Pin API version and exact endpoint contract in source manifest.
- Use /order or the documented quote/order path for current routed benchmark observations. Keep provider, quote time, context slot, route plan, mint identities, amount and raw response hash.
- Use /build when custom composition needs raw instructions. It returns components for caller-owned transaction assembly; caller must validate setup/swap/cleanup instructions, address lookup tables, compute budget, account metas, min-out, token-program compatibility and transaction size.
- Keyless rate limits are low; production API key and rate terms are separate evidence. Do not scrape or rotate credentials.

### 1000xsh/swaps

The MIT crate 0.1.1 is a direct DEX swap instruction builder: caller fetches required accounts, decodes a snapshot, supplies amount_in/min_amount_out, and builds an instruction view. It is **not** a quoting engine.

Use it only after:
- immutable revision pin;
- exact program id, pool identity, account layout and venue revision verification;
- Rust edition / SDK / type compatibility check;
- per-venue instruction conformance;
- Token-2022 and extension tests;
- output floor or a verified outer balance/repayment assertion.

Important venue-specific caveats in upstream notes:
- HumidiFi ignores min_amount_out; direct route must be BLOCKED unless a same-transaction post-balance guard guarantees minimum proceeds and flashloan repayment.
- Tessera V1 top-level direct path may fail; upstream notes recommend Jupiter wrapper path for the shown case. No generic direct support assumption.
- SolFi V2 is oracle/slot-sensitive; compare exact slot and context.
- Obric uses a specific Swap2 layout; never copy stale layout assumptions.

### Amount-specific comparison

For every candidate amount, compare:
- exact same input token/program and raw amount;
- same output mint/program and quote context;
- exact source state generation and slot;
- all pool dependencies and route lineage;
- protocol + aggregator + transfer + lender fees;
- input/output decimals and Token-2022 fees/hooks;
- CU, accounts, packet size and lookup tables;
- minimum output and same-tx repayment;
- output after all costs and reserve conflicts.

Do not extrapolate one size’s quote to another size. Preserve the whole size surface and rejected size boundaries.

## 5. Order construction and flashloan strategy

The objective is not merely “positive displayed spread”. It is a complete, replayable, amount-specific atomic plan:

borrow amount
→ route legs (possibly split across genuinely independent pools for price impact/capacity)
→ verified final output
→ lender repayment + fee
→ residual net profit after all costs
→ durable receipt/economic reconciliation in paper.

If legs cannot be made atomic under one supported transaction, the plan is not a flashloan route and must be rejected or classified as a different fully collateralized strategy. No cross-tx optimistic repayment.

Splitting is legitimate only when measured pool capacity, slippage/price impact, route constraints, CU/account limits, or shared resource conflict justify it. Reserve the same pools/ticks/bins/orderbook depth/lender resource/provider quota once through existing conflict/reservation owners. Never split to disguise intent, avoid venue detection, or mimic retail noise.

## 6. Delivery and feedback

The delivery plan and prohibitions are specified in RELAY_AND_ORDERFLOW_POLICY_RU.md. A provider ACK is not landing; landing is not final settlement. Reconcile finalized signature, actual balance delta, repayment, rent, fees, tip and all provider charges before calling any opportunity successful.
