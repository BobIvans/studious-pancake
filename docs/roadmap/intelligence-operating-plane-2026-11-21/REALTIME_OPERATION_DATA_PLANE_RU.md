# REALTIME_OPERATION_DATA_PLANE_RU
## Сбор данных flashloan-bot, event/work log, durable evidence и единый навигационный слой

**Назначение:** обеспечить непрерывную фиксацию фактически выполняемых paper/shadow/test процессов и значимых рыночных наблюдений; связать каждый этап решения с точной стратегией, версией кода, функциями, источниками, конфигурацией, тестами и результатом; дать ChatGPT и coding agents единый read-only путь поиска и replay.

**Важная граница:** этот документ не утверждает, что такое покрытие уже работает. На проверенном main имеются EventEnvelope/ObservabilityStore, AGG-02 raw journal, MarketObservation и MarketEpisode builders, но наличие схем/классов не доказывает, что runtime producers фактически публикуют события. W0 обязан это проверить. До подтверждения реальная полнота = UNKNOWN.

## 1. Что именно мы хотим записывать

Не путать три независимых потока:

1. **Repo change/work log:** commits, branches, worktrees, tasks, PRs, tests, graph delta, agent Work Result Receipts. Источник истины — Git/GitHub + task receipts.
2. **Market/data stream:** raw provider responses or decoded market updates, observations, source cursor, chain/block/slot, freshness, corrections, retractions, gaps and completeness. Источник истины — существующие source adapters, AGG-02 journal, MarketObservation/streams.
3. **Bot decision/operation trace:** конкретный цикл работы бота — discovery → observations → strategy evaluation → quote → flash-capital/lender feasibility → route → sizing → planning/compiler → simulation → reconciliation → paper outcome/rejection. Источник истины — EventEnvelope/ObservabilityStore плюс канонические domain owners.

Все три должны связываться через стабильные IDs, но не сливаться в одну неразличимую таблицу.

## 2. Уровни capture: сохранять все decision-relevant facts, не каждый технический шум

### 2.1 Обязательно сохранять (без sampling)

- каждый созданный/отброшенный candidate и причина;
- каждое решение стратегии: accept/reject, стратегия + версия, thresholds/features и time cutoff;
- каждое quote request/result/rejection/timeout/stale result, provider, venue/pool, request fingerprint, response hash и source observation refs;
- каждый значимый источник финансирования/flash lender: market/state snapshot ID, asset, amount, fee, repayment amount, capacity evidence, ограничения, provider generation, отказ/ошибка. Не заявлять доступность, если она не проверена на конкретном состоянии;
- каждый route/plan/sizing/compile decision, выбранные альтернативы и rejection reasons;
- каждый simulation start/result/revert/failure и относящиеся cost/compute/gas/priority/fee metrics;
- каждый paper/shadow lifecycle terminal outcome, reconciliation, evidence digest и отрицательные случаи;
- каждый provider health/quota/rate-limit/timeout/degradation event, влияющий на решение;
- cursor advances, reconnect epochs, source gaps, correction/retraction, watermark/completeness changes;
- события деградации telemetry, queue overflow, store/export failure и retention pressure.

### 2.2 Сохранять агрегированно или семплировать

Debug-level logs, повторяющиеся heartbeat, незначимые polling attempts и дублирующие transport messages можно агрегировать/семплировать с документированной политикой. Сохранять totals, samples, time range, source, sampling ratio/policy version и drop counters.

**Нельзя семплировать decision, rejection, raw evidence reference, gap, reconciliation или terminal outcome.** Если система не смогла надёжно записать обязательное событие, operation/episode помечается INCOMPLETE/UNOBSERVED и не считается qualified. Нельзя молча терять событие и продолжать отчёт как будто журнал полный.

### 2.3 Raw payload не дублировать в EventEnvelope

Полный RPC/quote/market payload сохраняется один раз у канонического raw-data owner (AGG-02/evidence archive), с SHA-256, byte size, schema/decoder version, source/provider, retrieval time и cursor/block identity. EventEnvelope и episode содержат stable ID/hash/ref. Чувствительные поля и секреты удаляются до persist.

## 3. Единый correlation contract: strategy → function → source → operation → result

Каждое decision-relevant событие должно получить или ссылаться на:

| Identity | Required data (where applicable) |
|---|---|
| Code | repo commit/tree SHA, producer version, stable code/logsite/symbol ID |
| Strategy | strategy_id, strategy_version, strategy config ID/hash |
| Run | runtime_id, environment (test/shadow/paper only), run_id/cycle_id, experiment_id |
| Trace | trace_id, span_id/parent_span_id, correlation_id |
| Candidate | candidate_id, logical_opportunity_id, plan_hash |
| Attempt | attempt_id, attempt_generation, aggregate sequence/idempotency key |
| Market | chain/genesis identity, block/slot/hash/finality, provider/source ID + generation |
| Observation | observation_id, raw_event_id, cursor key/offset/reconnect epoch, watermark, response/request hash |
| Strategy action | stage, action, reason_code, thresholds/features snapshot hash, decision cutoff |
| Flash finance | lender/provider ID, asset, amount, fee, repayment, capacity/source evidence refs |
| Execution simulation | route/plan ID, transaction/message hash, simulation ID/status, cost/latency metrics |
| Outcome | reconciliation ID, authoritative evidence refs/digests, terminal state, realized metrics only if authoritative |
| Resource conflict | canonical resource IDs or stable resource-set hash; lock/admission decision ref |

The exact field schema must be finalized after W0 producer/storage audit. Do not blindly expand EventEnvelope with duplicated IDs. Prefer first-class fields when query/index needs them, and structured attributes only for versioned domain-specific extensions. Preserve backwards compatibility and replay migrations.

## 4. Instrumentation approach

### 4.1 Reuse existing stores

- ObservabilityStore/EventEnvelope: operation transitions, decisions, lifecycle and trace metadata.
- AGG-02 DurableRawJournal: raw market/provider payload bytes, cursors, gaps, retention pins and verified replay/archive.
- MarketObservationV2/Market streams: normalized canonical market facts, generations, watermarks, corrections/retractions/completeness.
- MarketEpisode/episode_builder: point-in-time stage decisions, strategy/version, source refs, negative examples, replay pins and outcome.
- Existing strategy/source/provider/economics/planning/simulation/reconciliation owners: authoritative domain facts.

Do not create a second event DB or a generic time-series database by default. The unified layer is a graph/query projection over these owners.

### 4.2 Event producers must be wired into real supported runtime paths

After W0 verifies current runtime composition, add the smallest instrumented vertical, then extend by stage:
1. discovery cycle start/end and pair/source results;
2. observation received/validated/rejected and source completeness;
3. strategy evaluated/accepted/rejected + exact strategy ID/version/function/logsite;
4. quote/capital/lender query and exact response/rejection;
5. route/sizing/planner/compiler decisions;
6. sender-free simulation;
7. reconciliation and paper/shadow terminal outcome.

Emit at the stage boundary and at errors/decisions—not at every trivial helper call. The static graph already maps internal callers/callees; runtime logsite identifies which boundary actually executed. Stable code ID should bind to exact repo SHA and qualified symbol; ambiguous moves stay UNKNOWN/NEEDS_REVIEW.

### 4.3 Trace propagation

Use OpenTelemetry API/SDK where it provides value for traces across async tasks, provider adapters and subprocess/service boundaries. Propagate trace context and capture trace_id + span_id in structured logs/events. Keep EventEnvelope/ObservabilityStore as the durable operation ledger; do not create two competing log databases or assume OTel exporter alone is the authoritative financial event record.

The official OTel context-propagation model supports causal links across services and correlation of log records with trace/span IDs. Python logging integration has its own version-sensitive SDK/instrumentation setup; test the exact pinned versions and keep the application event contract independent of the exporter.

### 4.4 Runtime mode boundary

Initial operation capture covers only explicitly supported `test`, `shadow`, and `paper` environments. No signer, sender, transaction submission, borrowing, spending or LIVE switch is added. Current main's EventEnvelope enum is limited to test/shadow/paper. Do not misread event names such as submission/bundle as permission or evidence of live wiring.

## 5. Real-time meaning, delivery guarantees and health

“Real-time” must be measured, not claimed. Define per-stage:
- occurred_at and observed/received/persisted timestamps;
- event-to-store and event-to-query latency p50/p95/p99;
- queue depth/oldest age, retry count, append failure and outbox lag;
- provider lag and data freshness;
- cursor/watermark completeness, gaps, reconnect/replay lag;
- dropped/sampled counts by policy;
- persisted vs emitted event counts and unresolved correlations.

For critical facts use idempotent durable append/outbox and replay. For noncritical telemetry use bounded async batching with explicit overflow counters. On an observability failure emit/defer an observability-degraded state when possible; do not mark the affected operation/episode complete or qualified until recovered/reconciled. Avoid blocking the time-critical decision path on slow exports; durability and backpressure semantics must be tested under representative load.

No unbounded retries, unlimited queues or silent data truncation. Storage pressure must visibly pause/backpressure governed ingestion before deleting protected evidence.

## 6. Universal storage: one logical knowledge system, not one physical database

“Universally stored” means the operator/ChatGPT can query one stable ID and follow references across all canonical owners. It does **not** mean copying every datum into one giant database or Git repository.

| Data | Canonical durable storage | Universal index links |
|---|---|---|
| Source code/docs/config/tests/tool manifests | Git at exact SHA + generated graph cache | file/symbol/test/config/tool nodes |
| Raw provider/market data | AGG-02 journal + verified archives/Parquet projections where enabled | raw_event_id, source, chain, cursor, response hash |
| Normalized observations | MarketObservation/source owners | observation_id, generation, watermarks, corrections |
| Operation events | ObservabilityStore + immutable export/archive | event_id, trace, opportunity, attempt, stage |
| Episode / strategy experiment | MarketEpisode + experiment/evidence manifests | episode_id, strategy_id/version, raw refs, outcomes |
| Agent/code work | GitHub Issues/PR/commit + Work Result Receipt | task/worktree/commit/PR IDs |
| Derived graph/index | Rebuildable local/CI artifact keyed by repo SHA + schema/tool versions | stable entity/symbol IDs and provenance |

Provide portable export bundles where useful: versioned manifest + JSONL events + Parquet raw/normalized data + checksums + schema/tool versions + replay instructions. Do not place high-volume binary data, credentials or secrets into Git. Provide a read-only query façade that follows refs to the canonical store and returns bounded evidence packs.

## 7. Retention, compression, replay and recovery

- Keep decision-relevant raw evidence at least until all dependent episodes/experiments/PR audits are unpinned and retention policy permits expiry.
- Compress cold/warm analytical partitions with ZSTD Parquet where supported; preserve original payload hashes, record counts, min/max times/slots, schema version, source cursor ranges and archive checksum.
- Keep hot indexes for recent event queries, not duplicate copies of every raw payload.
- Retention pins must block deletion; compaction must preserve reversible replay with receipts.
- Track bytes ingested, bytes compressed, compression ratio, query/replay latency, archive verification, pin counts and retention pressure.
- Add backup/restore and rebuild-from-source manifests tests. Restore must reproduce the same checksums/projections for pinned snapshots.
- Never equate compressed bytes with lossless coverage unless replay/hash verification passes.
- Unknown/corrected/retracted/gapped data remains represented.

## 8. Continuous evolution

Repository knowledge graph refresh triggers:
- local coding-agent post-task/commit refresh;
- GitHub CI on push and pull request (including graph freshness and impact diff);
- refresh after merge to main;
- parser/tool/schema version update invalidates affected indexes;
- scheduled full consistency rebuild (e.g. nightly) compares deterministic output to incremental index;
- manual full rebuild command for recovery.

Runtime operation projections refresh when new durable events/observations/episode receipts arrive. The repo map and operation map have separate generations and both are included in any context pack. Reject stale combinations.

Daily/CI quality report includes parser coverage, index age, unresolved/dangling edges, event producer coverage, telemetry lag/drop counters, unmatched event↔source↔strategy↔code joins, store health, archive verification, bytes/p95 latency, golden-question retrieval accuracy.

## 9. Acceptance: tests that prove the end-to-end system

1. Start a supported offline/paper-shadow fixture and execute one bounded opportunity cycle.
2. Assert exact ordered durable events for each observed decision stage, with no missing decision/rejection/terminal events.
3. Assert every event has exact strategy ID/version, repo SHA, config identity, callsite/symbol ID (or explicit UNKNOWN), trace/attempt/opportunity IDs and source/observation refs where applicable.
4. Assert raw payload is stored once; event/episode references resolve to matching hashes and cursor ranges.
5. Reconstruct the full operation trace from stores after process restart.
6. Replay the episode and reproduce the same terminal classification and evidence digest.
7. Simulate provider timeout, stream reconnect, source gap, correction/retraction, outbox outage, append failure, queue overflow and disk pressure; prove explicit degraded/incomplete state and recovery.
8. Assert no private key, token, URL credential, seed, account secret or unredacted sensitive payload enters logs/index/packs.
9. Assert no external transaction/signing/borrow/send path can be invoked by the tests.
10. Measure event capture overhead and p50/p95/p99 latency/throughput under representative load.
11. Prove data can be exported to a portable bundle and imported/replayed on a clean environment with matching hashes.
12. Prove a context pack can answer: “What did strategy X do at time T, which exact functions ran, which source/lender evidence was used, why accepted/rejected, and what was the paper/shadow result?” with exact links and explicit unknowns.

## 10. Definition of done

A fresh checkout plus the portable data bundle (or approved connected data stores) is enough for an authorized ChatGPT/coding agent to navigate:
- the exact version of every strategy and relevant function chain;
- the data/provider/venue/flash-capital sources consumed at decision time;
- the work log of each paper/shadow attempt and its reason codes;
- source data IDs/hashes/cursors and operation timelines;
- tests, config, repo commit and evidence supporting each conclusion;
- gaps, corrections, failures, dropped events and unknown relationships.

The system does not claim literal unlimited retention or that all market data exists. It reports exact coverage and gaps. “Full bot capture” means all presently supported paper/shadow execution paths have been inventoried and instrumented, not merely one test fixture or demonstration strategy. No strategy becomes qualified based on incomplete telemetry. This is an implementation target; current functionality must be established by W0 and end-to-end tests.
