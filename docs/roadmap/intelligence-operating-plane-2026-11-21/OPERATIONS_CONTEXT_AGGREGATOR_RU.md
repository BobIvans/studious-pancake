# Операционный агрегатор Web3/flashloan системы
## Спецификация runtime-корреляции, parallelism, storage и context packs

**Дата исследования:** 2026-11-21  
**Аудированный baseline:** main SHA ea204222df86a0697cc6bce0e9ec60f7db31ffd8  
**Текущая продуктовая граница:** sender-free paper/shadow; LIVE hard-denied. Архитектура может подготовить доказуемую операционную картину для будущего live-approved runtime, но этот проект не добавляет live execution.

---

# 1. Миссия

Создать Operations Context Aggregator (OCA) — систему, которая по любому запросу даёт компактную, проверяемую картину того, что происходило с ботом:

- какие market/source observations реально поступили;
- какой код, конфигурация и policy были активны;
- какие стратегии, adapters и providers рассматривались;
- какие quotes и альтернативы были получены;
- какие candidates были допущены или отвергнуты и почему;
- какие ресурсы, pools, accounts, reserves или nonce lanes пересекались;
- что было рассчитано, построено и симулировано;
- какие операции были отправлены, приняты, landed, reverted или expired — только при наличии соответствующих фактов;
- что показала независимая chain-проверка и reconciliation;
- какой результат был theoretical, quoted, simulated, paper или realized;
- какие данные, source pins, tests и code symbols подтверждают каждый вывод.

OCA соединяет bot facts + chain facts + code facts + strategy facts + research history. Это не просто dashboard/log search: это воспроизводимый evidence graph, из которого строится context pack для ChatGPT и coding agent.

## 1.1 Три типа истины нельзя смешивать

1. **Bot-reported fact** — событие, записанное самим ботом.
2. **External/chain-observed fact** — информация из независимого RPC/indexer/archive source с зафиксированными coverage и freshness.
3. **Reconciled fact** — вывод после сопоставления независимых источников и terminal state.

Например, submission accepted или bundle landed не означает автоматически, что сделка final/settled и прибыль получена. Landing, confirmation/finality, token balance deltas, repayment, fee settlement и realized PnL должны иметь отдельные evidence refs и reconciliation result.

---

# 2. Самое важное: у Studious уже есть операционный event foundation

Предыдущий план недооценил существующую основу. На audited main уже присутствуют следующие компоненты.

## 2.1 Event contract — src/observability/events.py

EventEnvelope уже несёт:
- event_id, schema_version;
- occurred_at_utc_ns, monotonic_ns, runtime_id, environment;
- trace_id, logical_opportunity_id, plan_hash;
- attempt_generation, attempt_id, message_hash;
- tx_signature, jito_bundle_id;
- event_type, aggregate_id, sequence_no, stage, outcome;
- reason_code, severity, correlation_id;
- provider_id, venue_id;
- attributes, evidence_ref;
- producer_code_version, config_checksum, contract_fixture_version;
- idempotency_key.

EventType включает opportunity detected, quote requested/received/rejected, route planned, feasibility rejected, transaction built, simulation started/completed/rejected, submission attempted/accepted, bundle landed/rejected/expired, transaction reverted, balance reconciled, attempt terminal, provider health/quota changes, observability degraded, evidence corrected и reconciliation completed.

Текущая модель Environment ограничена test/shadow/paper. Наличие event type для submission/bundle не доказывает, что поддерживаемый продукт имеет live submission. Не расширять environment до live и не подключать signer/sender в этом проекте.

EventEnvelope также:
- требует зарегистрированный reason code;
- валидирует структурированный PnL;
- запрещает realized_pnl вне reconciliation/terminal event types;
- очищает/redacts payload до вычисления digest.

## 2.2 Durable event store — src/observability/store.py

На audited main уже есть:
- SQLite WAL;
- schema migration/doctor;
- append event;
- immutable event log;
- per-aggregate sequence;
- idempotency;
- payload digest и tamper-evident chain;
- attempt_projection и opportunity_projection;
- evidence_blob;
- outbox;
- export_manifest;
- retention_ledger.

## 2.3 Authoritative schema — src/observability/authoritative_store_pr195.py

Есть отдельный authoritative schema/identity/epoch gate. Runtime не должен самовольно мигрировать неизвестную базу. Новые поля проходят через текущую схему миграций и совместимые readers/writers.

## 2.4 Replay, archive и operator truth

Проверить и использовать:
- src/observability/replay.py — timeline по event/opportunity/attempt и verification;
- src/observability/integrity.py — digest-chain checks;
- src/observability/export.py и archive modules — immutable JSONL segments, manifests, checksums и remote archive acknowledgements;
- src/observability/cross_plane_pr196.py — объединение terminal truth из нескольких canonical planes;
- src/observability/health.py — health/readiness/status/metrics surfaces;
- src/operations/operator_readiness.py — evidence по trace stages, lifecycle recovery, redaction, backup/restore и блокерам.

**Следствие:** не создавать новый logging format, вторую observability DB или второй durable trace store. OCA строится как projection/reader над этим owner и AGG-02, а пробелы закрываются расширением контрактов после анализа backward compatibility.

---

# 3. Canonical data planes и их владельцы

Данные остаются в специализированных источниках истины. OCA связывает их идентификаторами.

| Plane | Canonical owner | Содержит | Не использовать для |
|---|---|---|---|
| Code/development | Git + src/intelligence | Git snapshots, hashes, AST, symbols, dependencies, tasks, context packs | Доказательство того, что код реально исполнялся |
| Operational events | src/observability | Decision/stage events, attempts, traces, reason codes, provider/venue, tx/bundle refs, lifecycle and replay | Chain finality без внешнего доказательства |
| Raw market/source evidence | src/agg02 + src/market | RawEventEnvelope, raw payload, source cursor, gaps, state frames, source lineage | Смысловая интерпретация стратегии |
| Market truth/evolution | src/market/observations.py + src/market_data_evolution | MarketObservationV2, generations, watermarks, normalized observations, as-of snapshots, episodes | Замена operational event log |
| Strategy/finance/venue | src/strategy, src/economics/flash_capital_graph, provider/source governance, resources | Strategy contracts, route graph, provider/source catalogue, capital edges, venue identity | Автоматическое подтверждение executable capability |
| Simulation/paper/reconciliation | src/execution, src/paper_shadow, observability cross-plane, production_qualification | Simulation evidence, lifecycle, terminal state, paper outcomes | Подмену chain settlement |
| Analytics/retention | src/intelligence, production_qualification, Parquet manifests | Rollups, reports, episodes, provider utility, retention receipts | Факты без provenance |

Operational lifecycle events и high-volume source observations — разные потоки с разной гранулярностью и retention. Их нужно связывать, не сваливая в одну широкую таблицу.

---

# 4. Операционная модель: от наблюдения до terminal evidence

OCA строит один immutable Operation/Episode view из этапов:

~~~text
SOURCE OBSERVATION
  source_id / provider_id / generation / cursor / block-slot / received_at
          |
          v
DISCOVERY / SIGNAL
  strategy_id / detector / market / asset / candidate_id
          |
          v
QUOTE FANOUT
  provider requests / quote results / rejected quotes / exact amounts / fees
          |
          v
CANDIDATE DECISION
  ranking / policy hash / thresholds / rejection reason / alternatives
          |
          v
RESOURCE & CAPITAL CHECK
  venue/pool/account locks / flash-capital edge / reservation / quota
          |
          v
SIZING -> PLANNER -> BUILDER
  exact amount points / unsigned plan / instruction/PTB/tx hash / build status
          |
          v
EXACT SIMULATION
  state identity / block-slot / compute / fees / revert / trace / output
          |
          v
PAPER OR APPROVED SUBMISSION BOUNDARY
  attempt / message hash / tx signature / bundle id / provider acknowledgement
          |
          v
CHAIN OBSERVATION
  transaction / logs / traces / account-state deltas / slot or block / finality
          |
          v
RECONCILIATION
  repayment / fees / token deltas / terminal state / confidence / evidence refs
          |
          v
STRATEGY EPISODE
  outcome / reason / PnL classification / resource cost / source coverage
~~~

Терминальные состояния должны различать:
- NO_CANDIDATE;
- REJECTED_PREQUOTE;
- QUOTE_UNAVAILABLE;
- QUOTE_STALE;
- CAPITAL_UNAVAILABLE;
- RESOURCE_CONFLICT;
- SIZING_REJECTED;
- BUILD_REJECTED;
- SIMULATION_REJECTED;
- PAPER_COMPLETED;
- SUBMISSION_UNKNOWN;
- CHAIN_OBSERVED;
- FINALITY_PENDING;
- RECONCILIATION_FAILED;
- RECONCILED_SUCCESS;
- RECONCILED_LOSS;
- EXPIRED;
- CENSORED / INSUFFICIENT_EVIDENCE.

Если текущие registries уже содержат equivalent reason codes — reuse them. Не вводить параллельную таксономию.

## 4.1 PnL — хранить несколько слоёв

На одном attempt могут существовать:
- theoretical_pnl — оценка модели;
- quoted_pnl — расчёт из quote;
- simulated_pnl — результат exact simulation;
- paper_pnl — результат paper execution;
- realized_pnl — только после доказанной reconciliation/settlement.

Каждый amount:
- целое число base units;
- mint/asset identity + chain;
- unit/decimals;
- fee components и источник курса, если нужен numeraire conversion;
- evidence digest и time/slot;
- status и uncertainty.

Не конвертировать суммы в float и не смешивать native token, USD estimate и realized token balances. Успешный API response не равен успешной сделке.

---

# 5. Correlation contract: связываем операцию, стратегию и код

## 5.1 Уже существующие identifiers

Переиспользовать:
- trace_id;
- logical_opportunity_id;
- aggregate_id + sequence_no;
- attempt_id + attempt_generation;
- plan_hash;
- event_id + idempotency_key;
- tx_signature;
- jito_bundle_id;
- provider_id + venue_id;
- evidence_ref digest;
- producer_code_version;
- config_checksum;
- contract_fixture_version;
- observation_id / source cursor / response hash;
- experiment_id / candidate_id / episode_id.

## 5.2 Недостающие или не гарантированные поля — аудитировать

На первом audit определить, передаются ли через producers/attributes и сохраняются ли end-to-end:
- canonical strategy_id and strategy_version;
- code commit SHA отдельно от человекочитаемой producer version;
- qualified symbol/function identity;
- stable logsite_id / statement_id;
- source observation IDs и market-data generation;
- chain ID/genesis/network identity;
- source block/slot/checkpoint и finality level;
- pool/program/contract identity и account read/write sets;
- request fingerprint, quote generation, quote expiry и exact input/output;
- resource/conflict keys и reservation receipt;
- route legs, underlying venues и shared liquidity identity;
- config bundle hash и policy version;
- available_at отдельно от recorded_at.

Не добавлять дублирующие поля до W0. Сначала создать EVENT_SCHEMA_GAP_MATRIX.json, затем выбрать существующие поля, типизированные v2 fields или строго namespaced attributes. Для decision-critical IDs предпочитать validated typed fields, а не произвольные strings.

## 5.3 Stable code callsites

Для важных decisions/operations создать stable logsite/statement ID:
- quote accepted/rejected;
- strategy candidate accepted/rejected;
- capital/capacity rejected;
- conflict scheduler rejected/admitted;
- route selected;
- size point selected;
- plan/build failed/completed;
- simulation completed/rejected;
- submission/landed/expired/reverted;
- reconciliation completed/failed.

Реализовать static scanner для Python log/event producers, затем расширять по реально используемым языкам. Mapping хранит:
- logsite_id;
- repo path;
- qualified symbol;
- event type;
- normalized callsite signature;
- first-seen commit;
- source hash/range;
- current/historical aliases;
- mapping status: DETERMINISTIC, REVIEWED, INFERRED, UNKNOWN.

ID не должен зависеть только от line number или полного текста сообщения. Rename/move не переписывает историческую атрибуцию. Неоднозначный move требует review.

Для legacy logs без IDs:
1. structured fields и stack trace;
2. deterministic mapping по parser/index и repo SHA;
3. logsite как optional offline helper для поддерживаемых logging frameworks;
4. template similarity только как INFERRED, не exact proof.

## 5.4 OpenTelemetry — complement, not replacement

OpenTelemetry может стандартизовать trace/span context и добавлять TraceId/SpanId к log records. Но EventEnvelope уже имеет собственный trace_id, aggregate/opportunity и attempt identity.

Поэтому:
- не добавлять OTel ради самого названия;
- использовать его, если async/multiprocess/provider calls действительно теряют causal context;
- адаптер сохраняет существующие IDs и связывает OTel trace/span;
- не дублировать event log;
- не захватывать prompt, private RPC credentials, wallet secrets и full raw transactions в span attributes по умолчанию.

См. [OpenTelemetry log correlation](https://opentelemetry.io/docs/specs/otel/logs/) и [context propagation](https://opentelemetry.io/docs/concepts/context-propagation/).

---

# 6. Strategy, provider, source and tool registry

OCA должен отвечать не только «что случилось», но и «какая стратегия, код и источники породили результат».

## 6.1 Strategy entity

Каждая стратегия проецируется из canonical strategy contracts/registry, R10 inventory, strategy manifests и capability/qualification owners.

Минимальные поля:
- strategy_id, strategy_version, aliases;
- implementation symbols/files;
- supported/research-only chains and market classes;
- venue/pool/program types;
- data/source dependencies;
- quote providers and adapter versions;
- flash-capital dependencies and evidence status;
- planner/builder/simulator dependencies;
- config/policy hashes;
- lifecycle class: LOCAL_ATOMIC / CONDITIONAL_HYPEREDGE / HEDGED_NON_ATOMIC / SIGNAL_ONLY / EXCLUDED;
- capability status: IMPLEMENTED / WIRED / QUALIFIED / BLOCKED / UNKNOWN;
- test/fixture/replay references;
- owner/task/PR and change history.

## 6.2 Provider/source/tool entity

Хранить:
- canonical provider/source/tool ID;
- chain/vm and data domains;
- API/SDK version, deployment pin, retrieval date and license;
- source owner and adapter code symbol;
- auth/secret reference ID only, never credential value;
- quotas, rate-limit policy, timeout/retry budget;
- data types, freshness, coverage and pagination;
- provenance and raw response hash;
- consuming strategies/detectors/reports/tests;
- admission status and why.

Source catalog row ≠ active connector. API 200 ≠ data quality. Quote ≠ executable transaction. Read-only analytics ≠ exact market state.

## 6.3 Relation projection

Строить edges:
- Strategy USES Source / Provider / Venue / Capital;
- Adapter IMPLEMENTS ProviderContract;
- Function CALLS Function;
- CodeSymbol EMITS LogSite;
- Strategy DECIDES Candidate;
- Candidate USES Observation / Quote / Route;
- Attempt BUILT_FROM Plan;
- Simulation VALIDATES Plan;
- Transaction SETTLES Attempt;
- Episode SUMMARIZES StageEvents;
- Test VALIDATES Symbol / Contract / Strategy.

Каждый edge несёт:
- source owner + evidence ref;
- repo SHA/config/source generation;
- schema version;
- derivation method;
- timestamp;
- confidence/status;
- valid time и recorded time там, где есть.

Docs declarations, static code calls, runtime events и model suggestions должны оставаться различимыми.

---

# 7. Parallel execution architecture for flashloan strategies

Параллелить можно поисковые и вычислительные jobs, но не любую state transition. Flash-loan cycle — атомарное обязательство конкретного lender/protocol: borrow → callback/swaps → repayment amount+fee в требуемой transaction/operation. Конкретные правила определяет protocol contract.

## 7.1 Четыре очереди, а не один global queue

1. DISCOVERY_QUEUE — независимые scans assets/pools/routes/providers.
2. QUOTE_QUEUE — bounded fan-out к providers с quota/rate/circuit budgets.
3. SIMULATION_QUEUE — параллельные exact offline/sender-free simulations на immutable state frames.
4. EXECUTION_ADMISSION_QUEUE — централизованный authority/lock/nonce/resource admission перед execution-capable operation; сейчас gated и не открывает live.

Нельзя создавать worker, который сам выбирает capital reservation, меняет global state, подписывает и отправляет транзакции вне canonical authority.

## 7.2 Что можно распараллеливать

- поиск различных markets/assets;
- quote requests разным providers, если quota позволяет;
- amount/route evaluations на одном immutable snapshot;
- exact simulation различных candidate plans;
- retrospective replay и strategy analysis;
- report generation.

Что требует serialization/conflict admission:
- один writable pool/account/reserve/nonce;
- одна opportunity, capital reservation или общий risk budget;
- shared ATA/account lifecycle;
- same sender EOA nonce lane;
- shared mutable state/cache/decision generation;
- mutable source state между sizing/build/simulation.

## 7.3 Resource conflict graph

Для каждой opportunity строить ResourceSet:
- chain/network;
- source state snapshot identity;
- read/write accounts (Solana);
- pools/programs/market IDs;
- lender reserve/flash source;
- sender/account/nonce lane (EVM);
- token accounts/ATAs or shared position;
- provider quota/rate budget;
- shared capital/risk budget;
- expiry/deadline.

Параллелить без блокировки можно только если immutable inputs и resource constraints доказывают независимость. Shared writable resource означает conflict, а не вторую независимую opportunity.

### Solana

Account metadata в instruction указывает read/write доступ и используется валидаторами для определения, какие транзакции могут выполняться параллельно. Jito документирует, что bundles с пересекающимися lock patterns (w,w), (r,w), (w,r) попадают в один local auction; непересекающиеся patterns могут участвовать отдельно. В low-latency документации описаны parallel auctions на 50ms ticks. Bundle API гарантирует до пяти транзакций в bundle, последовательно и атомарно; это не означает, что конфликтующие стратегии могут игнорировать account locks.

Engineering implication:
- извлекать exact account metas/read-write sets из построенных instructions;
- ключ конфликтов: chain + account pubkey + access mode + snapshot generation;
- моделировать underlying pools, даже если разные aggregators вернули маршрут;
- хранить CU cost/lock pattern/tip metadata только когда источник это сообщает;
- route calculations параллельны, но state-mutating plans проходят existing ConflictAwareScheduler/resource authority;
- разные route labels не доказывают independent liquidity.

Ссылки: [Solana account metadata](https://solana.com/docs/core/instructions/instruction-structure), [Jito auction/lock patterns](https://docs.jito.wtf/lowlatencytxnsend/), [Jito bundles](https://docs.jito.wtf/bundles/).

### EVM

У EOA sequential transaction nonce; только одна transaction с конкретным nonce может быть выполнена этим account. Параллельные отправки с одного sender требуют явного nonce ownership/lanes или сериализации. Независимые contract/pool state могут конфликтовать даже при разных nonce.

Engineering implication:
- research/quote/simulation параллельны;
- builder output и sender/nonce ownership остаются за одной canonical authority;
- per-strategy nonce managers не создавать;
- same pool/reserve/state key включать в resource conflict graph;
- account abstraction/keyed nonce применять только если выбранная сеть и account contract это реально поддерживают и имеется audited owner.

Ссылки: [Ethereum account nonce](https://ethereum.org/developers/docs/accounts/), [ERC-4337 keyed nonce model](https://eips.ethereum.org/EIPS/eip-4337), [Flashbots bundle semantics](https://docs.flashbots.net/flashbots-auction/advanced/understanding-bundles).

### Flash-loan atomicity

ERC-3156 требует, чтобы lender в конце flashLoan call получил principal + fee либо операция revert. Aave V3 аналогично требует возврата principal + premium к концу transaction для repay path. Это атомарное intra-transaction обязательство, не разрешение разнести цикл flash loan между независимыми worker transactions.

Ссылки: [EIP-3156](https://eips.ethereum.org/EIPS/eip-3156), [Aave V3 flash loans](https://aave.com/docs/aave-v3/guides/flash-loans).

## 7.4 Переиспользуемые блоки Studious

- src/strategy/conflict_scheduler.py — центральный sender-free conflict admission и reservation port;
- src/strategy/shadow_workers.py — bounded offline replay workers;
- src/strategy/shadow_portfolio.py + existing portfolio optimizer;
- src/strategy/opportunity_identity.py — idempotent opportunity identity;
- provider quota/governance owners;
- durable lifecycle/capital reservations;
- existing runtime composition root.

Не добавлять второй task queue, reservation authority, nonce manager, signer, sender или portfolio solver без подтверждённого W0 gap.

---

# 8. Operation context pack — что должен получать ChatGPT

Для стратегии, opportunity, incident, provider или time window OCA создаёт один bounded pack.

## 8.1 Envelope

~~~json
{
  "pack_schema": "studious.operation-context.v1",
  "pack_id": "deterministic-id",
  "query": "explain failed candidate for strategy X",
  "generated_at": "UTC timestamp",
  "repo": {
    "repository": "BobIvans/studious-pancake",
    "commit_sha": "exact SHA",
    "dirty_state": "CLEAN | DIRTY | UNKNOWN"
  },
  "scope": {
    "strategy_ids": [],
    "opportunity_ids": [],
    "attempt_ids": [],
    "episode_ids": [],
    "time_window": {},
    "chains": []
  },
  "budget": {
    "max_bytes": 0,
    "max_tokens": 0,
    "actual_bytes": 0,
    "tokenizer_id": "named tokenizer or UNKNOWN"
  },
  "sections": [],
  "coverage": {
    "complete": false,
    "missing": [],
    "unknown": [],
    "stale": [],
    "conflicts": []
  },
  "evidence_manifest": []
}
~~~

## 8.2 Содержимое пакета — progressive disclosure

1. SUMMARY — что произошло, что известно и что осталось неизвестным.
2. STRATEGY — contract/version/implementation/dependencies/capability state.
3. OPERATION_TIMELINE — ordered events by aggregate/sequence, reason codes, stage outcomes.
4. MARKET_CONTEXT — observations, timestamps, cursors, slot/block, gap/correction state, quote/route snapshots.
5. PROVIDER_COMPARISON — все candidates, включая losing/rejected providers; fee/unit normalization, latency, freshness, quota, source quality.
6. RESOURCE_CONFLICTS — shared pools/accounts/reserves/nonce lanes and scheduler decisions.
7. EXECUTION_EVIDENCE — plan/transaction/bundle hashes, simulation, RPC evidence, chain status, reconciliation.
8. ECONOMICS — theoretical/quoted/simulated/paper/realized measures separately.
9. CODE_CONTEXT — exact functions/callsites, relevant tests, config/schema/policy and commit diff.
10. HISTORY — comparable prior episodes and controlled baseline/challenger.
11. NEGATIVE_EVIDENCE — rejection reason, missing data, incomplete sources, replay/coverage conflicts.
12. MANIFEST — hashes, schema versions, provenance and continuation pointers.

Raw payloads refer by IDs/digests and are fetched on demand. Include only the exact bounded slice needed for the question.

## 8.3 Evidence reference

Каждый факт должен иметь:
- owner type + owner ID;
- source artifact/path or store table/partition;
- event_id / observation_id / tx_signature / bundle_id;
- content hash;
- exact repo SHA/schema version;
- source time and ingest time;
- source coverage/finality;
- derivation status: raw / normalized / inferred / reconciled;
- fetchable URI or local locator.

Нельзя ссылаться только на LLM summary, если исходный evidence доступен.

---

# 9. Data compression, aggregation and storage

Не смешивать три разные задачи.

## 9.1 LLM context compression — отбирать, а не терять факты

Основные методы:
- symbol-level retrieval и точные byte-range slices;
- dependency/callgraph traversal от query seed;
- добавление связанных tests/contracts/configs;
- operation/trace retrieval по IDs;
- группировка event timeline по aggregate/stage/reason;
- rollups для повторяющихся наблюдений;
- полный raw payload только для anomaly/high-value window;
- точный tokenizer budget для выбранной модели, если он известен.

Context pack — это view, а не единственная копия доказательства. Исходный код и raw evidence остаются вне prompt.

## 9.2 Index compression

Хранить compact, rebuildable metadata:
- file/symbol IDs, names, signatures, byte ranges, hashes;
- imports/calls/dependency edges;
- source/strategy/entity IDs и typed labels;
- не embedding-овать каждый raw event/poll;
- embeddings опционально для docs, ADRs, semantic research notes и компактных episode summaries;
- cache по content hash + model version;
- не коммитить huge binary graph/index в Git.

Graphify — кандидат для polyglot deterministic AST и code/doc/config graph. Его README описывает local tree-sitter parsing примерно 40 языков, incremental update, graph queries и optional LLM semantic extraction для части non-code материалов. Code-only graph можно использовать без LLM backend. Проверить против current Python-only repo_source и сохранить unsupported coverage явно: [Graphify](https://github.com/Graphify-Labs/graphify).

jCodeMunch даёт symbol-level retrieval, но его dual-use license требует paid license для коммерческого и revenue-supporting internal use. Не делать его mandatory dependency до одобрения лицензии. Его заявленный token-saving benchmark — vendor-maintained 15-lookup comparison; воспроизвести на этом repo, а не переносить цифру автоматически: [README](https://github.com/jgravelle/jcodemunch-mcp), [LICENSE](https://github.com/jgravelle/jcodemunch-mcp/blob/main/LICENSE).

## 9.3 Raw/normalized data retention

Переиспользовать существующий pipeline:
- AGG-02 raw journal/cursor/gap;
- MarketObservation и normalized state;
- immutable observation/episode receipts;
- verified ZSTD Parquet compaction;
- rollups и retention policy;
- evidence pins и experiment refs.

Parquet — columnar format с compressed pages; ZSTD поддерживается форматом. DuckDB может читать Parquet с projection/filter pushdown, загружая только требуемые колонки. Это даёт локальную историю без обязательной второй database: [Apache Parquet compression](https://parquet.apache.org/docs/file-format/data-pages/compression/), [DuckDB Parquet queries](https://duckdb.org/docs/data/parquet).

ClickHouse не добавлять по умолчанию. Провести 24h/7d representative ingest+query+replay soak и записать:
- raw events/s, bytes/s;
- SQLite WAL growth;
- export/compaction duration;
- query p50/p95;
- replay time;
- CPU/RAM/disk;
- retention eligible/pinned bytes;
- projection/index build time.

Только измеренный bottleneck может оправдать аналитический read-model. Canonical event IDs, hashes и receipts всё равно должны вести к существующим owners.

## 9.4 Никакой потери важных Web3 фактов

Protected:
- candidate windows;
- source gaps/reconnects/corrections/retractions;
- provider disagreement;
- first occurrence/new failure class;
- simulation/reconciliation failure;
- terminal paper/reconciliation evidence;
- active experiment refs;
- manual pins;
- unique anomalies и schema drift.

Repeated ordinary polls:
- dedupe exact payload hash;
- keep first/last/count/timing and periodic baseline;
- emit deltas on material change;
- preserve cursors/watermarks for coverage reconstruction;
- retain full raw slice around pinned candidate/episode.

Laya/LLM может предложить review/extend retention, но не разрешать irreversible deletion. Existing storage pressure manager остаётся единственным исполнителем retention policy.

---

# 10. External Web3 evidence providers

## 10.1 SQD Portal MCP

Использовать как read-only historical/external evidence и cross-check source coverage. Официальная документация SQD описывает query endpoint для raw/decoded EVM, Solana, Bitcoin, Hyperliquid и Substrate data. MCP выдаёт bounded previews with pagination; широкие окна могут быть capped. Поэтому запросы должны задавать узкие block/slot windows, минимальные поля, filters и cursor pagination. Он не подписывает и не отправляет транзакции: [SQD Portal MCP setup](https://sqd.dev/learn/portal-mcp-server-setup/), [server repo](https://github.com/subsquid-labs/portal-mcp-server).

Правила интеграции:
- explicit bounded queries;
- сохранять network, block/slot window, cursor, page count, coverage, freshness, query hash и retrieval timestamp;
- никогда не передавать unlimited rows в LLM;
- в OCA сохранять selected facts + raw references/exports;
- не заменять protocol-specific exact state или final settlement proof.

## 10.2 Antseer MCP

Полезен как supplemental read-only context: on-chain flows, market/derivatives analytics, wallets, token/protocol metrics. Текущая документация заявляет 65 tools в 12 domains, provenance на data points и возможность expose subset tools через URL query. Для single-purpose agent документация рекомендует менее 10 tools. Поэтому не открывать все 65 инструментов каждому coding agent: создать узкий analyst profile под текущий вопрос. [Antseer docs](https://antseer.ai/docs).

Antseer analytics — не доказательство exact pool state, executable quote, transaction result или strategy capability.

---

# 11. Operations cockpit and reports

Строить views из canonical projections, не вводить новую event DB ради UI.

## 11.1 Run overview

- runtime/product mode;
- active code/config/policy generation;
- strategy enablement state;
- provider/market source health and freshness;
- stream cursor/gap/reconnect status;
- candidate and rejection funnel;
- active quote fanout and quota budget;
- conflict scheduler and queue backlog;
- simulation/reconciliation/paper statuses;
- resource usage and storage pressure;
- blockers and last evidence receipt.

## 11.2 Strategy performance

Для каждой strategy/version:
- observations → signals → candidates → quotes → admitted → simulations → paper attempts → reconciled outcomes;
- conversion rate by stage;
- rejection/failure reasons;
- net economics by PnL evidence class;
- provider unique contribution and overlap;
- venue/pool concentration and shared-liquidity conflicts;
- stale-data and latency stress;
- resource cost per qualified episode;
- comparable strategy/control/ablation results.

Сравнение — на frozen episodes, одинаковой source availability, time range and declared budget. Учитывать lookahead leakage. Missing values оставлять UNKNOWN/NOT_OBSERVED.

## 11.3 Provider quality

- request count and physical attempts;
- p50/p95 latency;
- timeout, 429, stale, malformed and schema-drift rates;
- unique candidate contribution;
- shared underlying venue overlap;
- quote/buildability/simulation conversion;
- quota per useful candidate;
- source coverage/finality and last update;
- exact version/license/admission state.

## 11.4 Incident / operation trace

Для одного attempt:
- event timeline and sequence;
- code/config/strategy generation;
- provider responses and rejection reasons;
- exact route/size/state snapshot;
- account/pool lock conflicts;
- plan/build/simulation receipts;
- tx/bundle identity and external status;
- reconciliation/final outcome;
- source completeness and unresolved discrepancies.

---

# 12. SLO, cost and quality measurements

Цели для измерения, не performance claims:

| Area | Metric |
|---|---|
| Correlation | % terminal attempts with strategy, opportunity, repo SHA, config hash and evidence refs |
| Runtime trace | % decision stages with ordered event IDs and stable reason codes |
| Callsite | % high-value events deterministically mapped to symbol/logsite |
| Strategy coverage | % runtime registrations connected to contract, sources, tests and state |
| Source coverage | % observations with source generation, timestamp, cursor/slot and schema |
| Data quality | gaps, corrections, stale quotes, provider disagreement and unknown coverage |
| Retrieval | exact-answer precision/recall on frozen questions |
| Context economy | bytes/tokens per pack vs full source/event baseline |
| Storage | bytes/day, compression ratio, retention ratio, replayability, time-to-budget |
| Parallelism | useful jobs/sec, conflict rejection, duplicate work, stale snapshot rejection |
| Analysis | time to explain one failed candidate from context pack |
| Reliability | replay divergence, missing refs, unverified terminal states |

Golden set: 30–50 realistic questions over frozen repo snapshot and fixed paper/shadow operation fixtures. Measure each pack, not a vendor benchmark.

---

# 13. Ограничения и unresolved risks

1. EventEnvelope/ObservabilityStore существуют, но по аудированному main GitHub code search нашёл make_event() только как definition и в tests; production callsites не подтверждены. make_event() по умолчанию использует test-runtime/test и unknown provenance. Это НЕ доказательство реального runtime capture. W0 обязан повторно подтвердить на актуальном SHA. strategy_id/version, repo SHA, stable callsite/logsite, observation refs, trace/span and resource access sets требуют producer-to-store проверки.
2. Current Environment enum не включает LIVE. Эта работа не должна подразумевать или включать live mode.
3. Current repo_source покрывает Python AST; multi-language и richer config/doc relations не гарантированы.
4. Static callgraph не доказывает dynamic imports, reflection, runtime plugin loading или все provider calls. Нужны runtime IDs и tests.
5. Внутренне полный trace может не иметь полной external chain coverage/finality. Сохранять coverage/finality state.
6. Bundle accepted/landed не равен fully reconciled trade.
7. Model summary — не evidence. Все derived views содержат provenance.
8. Strategy labels могут устареть после refactor/config changes. Пересобирать из canonical manifests, сохранять version history.
9. Слишком много MCP tools увеличивает cost выбора и контекста. Нужны несколько composite query tools и explicit tool profiles.
10. Vendor versions, licenses, coverage, API quota меняются; pin and re-audit at install time.
11. ZIP репозитория не содержит runtime events, если operation export/evidence bundle не приложен отдельно.
12. Наличие EventEnvelope types, SQLite store и replay tests не гарантирует, что production runtime вызывает make_event() и append(). Runtime telemetry должна быть отдельным implementation work package с end-to-end fixture/runtime test.
13. Текущий native_cpmm_capture.py описан как one-shot capture без subscriptions; RuntimeDiscoveryCoordinator возвращает bounded report. Нельзя заявлять continuous market stream без отдельного источника и подтверждённого subscription/collector path.
12. Automatic indexing не отправляет данные в ChatGPT. Оно готовит локальный pack; доставка требует explicit upload или authenticated read-only connector/MCP session.

---

# 14. Порядок реализации

Не начинать с graph database, ClickHouse или autonomous agents.

1. **W0 + W0A:** current owner/runtime audit in parallel with same-SHA polyglot/tool bake-off.
2. **W0B:** first working repo knowledge graph, all strategy/tool/source inventories, bounded context packs and incremental refresh.
3. **W1 correlation completeness:** EVENT_CORRELATION_MATRIX.json — какие IDs/fields emitted, persisted, replayable and mapped to code.
4. **W2 OperationEpisode projection:** deterministic view combining existing durable records + raw observation refs + strategy identity + code/config generation + terminal evidence. No new raw database.
5. **W3 stable callsite IDs:** static scanner and logsite registry for high-value producers; add IDs only in focused, tested vertical.
6. **W10 runtime instrumentation:** wire actual supported test/paper/shadow producers into durable event capture, trace context, strategy→function→source→outcome. This is mandatory; a schema/test-only implementation does not count.
7. **W11 universal query/export/replay:** one read-only façade across code graph, ObservabilityStore, AGG-02, MarketObservation, MarketEpisode and work receipts; portable checksummed evidence bundle.
8. **W4 context-pack API:** query one opportunity/strategy/provider/time window and return bounded pack + evidence manifest including runtime event lineage.
9. **W5 strategy conflict/admission report:** connect current ConflictAwareScheduler/resource sets to strategy/episode reports; no second scheduler.
10. **W6 source query adapters:** optional bounded SQD/Antseer read-only profiles under source governance.
11. **W7 retrieval/compression benchmark:** Graphify sidecar and target-model token measurements before choosing external index.
12. **W8 operations cockpit and review workflow:** CLI/report bundle first; MCP after query contract stabilizes.
13. **W9 storage scale gate:** measure 24h/7d load before considering ClickHouse/NATS/remote object storage.

Every step requires exact current main SHA, focused worktree/PR, positive and negative tests, evidence artifacts and human review. Completion cannot be declared until W0B + W10 + W11 work on a real supported test/paper/shadow vertical and preserve a replayable operation after process restart.
