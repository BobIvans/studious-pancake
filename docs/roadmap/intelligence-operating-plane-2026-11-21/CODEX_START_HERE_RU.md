# Studious Intelligence & Strategy Operating Plane
## Архитектура и задание для coding agent — 2026-11-21

**Тип:** design + implementation handoff.  
**Репозиторий:** BobIvans/studious-pancake.  
**База аудита:** main = ea204222df86a0697cc6bce0e9ec60f7db31ffd8.  
**Режим:** read-only audit → additive integration → reviewable PRs.  
**Не является разрешением на live trading, подпись, отправку транзакций или изменение production authority.**

---

# 0. Цель

Построить над существующим Studious Pancake единый слой, который позволяет человеку, ChatGPT и coding agents получать точные, компактные и проверяемые сведения о:

1. стратегиях, их версиях, коде, зависимостях, сетях, рынках, DEX, lending/flash-capital sources и инструментах;
2. источниках данных, их контрактах, свежести, качестве, provenance, статусе допуска и потребителях;
3. runtime-пути от market observation до candidate, sizing, planning, compilation, simulation, reconciliation и paper outcome;
4. параллельных coding/research задачах, их владельцах, пересечениях файлов, блокерах, тестах и результатах;
5. данных, логах, причинах принятия/отклонения, исторических эпизодах и измеренных результатах;
6. изменениях всего этого во времени — с точными repo SHA, config hash, source generation, schema version и evidence refs.

Это не новый бот, не вторая memory database и не giant GraphRAG. Это **единый read-only intelligence/query plane над существующими владельцами истины**, с детерминированным индексированием, типизированным реестром связей, runtime ↔ code correlation и bounded context packs.

Система должна приносить пользу уже на этапе ChatGPT + coding agents. Позже можно открыть её через read-only MCP/API.

## Главный принцип

**Сначала reuse и reconciliation существующих owners. Затем — недостающие связи. Только потом — новые базы или сервисы.**

Не создавать вторые версии:
- market raw journal / market observations / stream truth;
- strategy registry или source catalog;
- capital reservation / lifecycle authority;
- planner / transaction builder / simulator / reconciliation / paper outcome;
- retention authority;
- code snapshot/context pack, если текущие модули покрывают требование.

Наличие класса или документа не доказывает, что capability подключена к поддерживаемому runtime. Разделять статусы IMPLEMENTED, WIRED, QUALIFIED, BLOCKED, UNKNOWN и подтверждать их тестами/receipts.

---

# 1. Какие функции получим и из каких блоков

| Функция | Существующие owners Studious | Дополняющие блоки | Что получаем |
|---|---|---|---|
| Карта репозитория | src/intelligence/repo_snapshot.py, repo_manifest.py, repo_source.py, repo_groups.py, repo_history.py, repo_coverage.py | Graphify как проверяемый polyglot/doc/config graph | Файлы, символы, импорты, зависимости, группы, тесты, конфиги и пробелы покрытия |
| Точное извлечение кода | src/intelligence/context_pack.py, context_benchmark.py, evidence_refs.py | jCodeMunch после коммерческой лицензии; Mimir outline/peek как benchmark | Нужные функции, классы, тесты и контракты вместо загрузки всего repo |
| Каталог стратегий | src/strategy/registry.py, strategy_contract.py, strategies.py, arbitrage_graph.py, multihop_solver.py; R10 inventory/replay | Versioned entity/label projection | Все стратегии, версии, lifecycle stage, сети, рынки, venues, financing, inputs, tests, owners и evidence |
| Каталог источников и tools | src/market/source_catalog.py, src/resources/market_source_catalog.json, QPR/DIN, docs/mechanism_discovery/, offline source manifests | SQD Portal, Antseer, official-doc/source registry | Что даёт каждый источник, где используется, статус допуска, версия, лицензия, freshness и ограничения |
| Цепочки зависимостей | repo_source/repo_groups, strategy graph owners | Graphify / Tree-sitter для непокрытых языков и артефактов | strategy → function → adapter → provider/source → protocol/venue → tests |
| Параллельная разработка | AGENTS.md, CODEX_START_HERE.md, master roadmap, worktree/task/owner maps, parallel PR workflows/tests | Git worktrees + единый coordinator/task manifest | Изоляция задач, ownership, зависимости, collision control, gates и PR |
| Параллельные candidate jobs | src/strategy/conflict_scheduler.py, shadow_workers.py, shadow_portfolio.py, opportunity identity/queue/ranker | Существующие bounded workers и resource sets | Параллельные discovery/simulation/replay без независимого управления signer/capital authority |
| Operations и trade lifecycle | src/paper_shadow/, src/planning/, src/execution/exact_simulation.py, src/runtime/, durability/authority/qualification owners | Существующий CLI/status/capabilities | Контроль candidate → sizing → planner → compiler → simulation → reconciliation → paper outcome |
| Лог → код → стратегия | src/strategy/market_graph_ingest.py, MarketObservationV2, MarketEpisode, experiment_manifest.py, evidence_refs.py | Stable Statement IDs/logsite IDs, logsite, optional OpenTelemetry | Детерминированная связь события с callsite, функцией, стратегией, commit и экспериментом |
| Trade/event retrospective | src/agg02/, src/market/observations.py, src/market_data_evolution/contracts.py, episode_builder.py, production_qualification.py | SQD для chain evidence; Antseer для supplemental analytics | Воспроизводимый episode с положительными и отрицательными решениями и итогом |
| Label / knowledge store | Existing strategy/source/provider/economic registries + src/intelligence | Materialized Entity & Label Registry; growmos/Mimir только при доказанном gap | Типизированные сущности/отношения с provenance, temporal scope и evidence refs |
| Контекстное сжатие | context_pack, repo_source, repo_groups, exact snapshots, byte ranges, benchmark | Graphify, jCodeMunch/Mimir, ctxgraph/NervaPack как benchmark candidates | Меньше токенов без потери первичных доказательств |
| Физическое хранение | DurableRawJournal, AnalyticalDatasetPublisher, DatasetReplayReader, sampling, rollups, Parquet compaction, retention/pressure manager | ZSTD Parquet; object storage позже | Hot/warm/cold retention с replay proof и byte accounting |
| Качество retrieval | context_benchmark, tests, source pins, coverage reports, replay receipts | Golden question set, graph/retrieval evaluation | Измеряемая precision/recall/coverage/freshness, а не субъективно «умный» индекс |
| Единый интерфейс для LLM | src/intelligence/cli.py + context pack/report bundle | Read-only studious-intel façade; MCP wrapper после стабилизации | Один вход для repo/strategy/source/trace/episode/pack |
| Governance и безопасность | AGENTS.md, capabilities, provider governance, QPR, secret filters, release/authority gates | Scope controls, read-only MCP, approval policy | LLM не может менять risk, provider admission, signer, retention или trade state |

---

# 2. Что уже есть в Studious Pancake

Аудит выполнен по GitHub main на SHA ea204222df86a0697cc6bce0e9ec60f7db31ffd8. В дереве было около 3,401 файлов: примерно 1,851 Python, 792 Markdown, 446 JSON и 145 YAML workflows. Это инвентаризация Git tree; содержимое всех файлов не было целиком прочитано.

## 2.1 Local Intelligence V2 уже реализован как кодовый контур

В src/intelligence/ находятся:

- repo_snapshot.py — exact pinned Git snapshot, resumable inventory, secret/path exclusions, round-trip verification;
- repo_manifest.py — project/part manifest;
- repo_source.py — Python AST symbols/imports, byte offsets, source hashes; непокрытые языки явно помечаются;
- repo_groups.py — SCC и logical segments, связь с tests/contracts;
- repo_history.py, repo_coverage.py — delta, affected dependents, coverage gaps;
- context_pack.py — bounded packs: WHOLE_REPO, WHOLE_REPO_INDEXED, INTERCONNECTED_FILES, RUNTIME_PATH, TEST_IMPACT, TECH_DEBT, DELTA;
- context_archive.py, context_recovery.py, context_benchmark.py;
- episode_builder.py, evidence_refs.py, experiment_manifest.py;
- provider_utility.py, strategy_report.py, reports.py;
- sampling.py, rollups.py, parquet_compaction.py, retention_policy.py, storage_budget.py, pressure_manager.py, prune.py;
- laya_triage.py, laya_cache.py, triage_loop.py.

Сопутствующие handoff docs уже есть:
- CODEX_LOCAL_INTELLIGENCE_V2_START_HERE.md;
- CODEX_STORAGE_PRESSURE_START_HERE.md;
- docs/strategy/local-intelligence-v2/MASTER_CONTEXT_RU.md;
- STORAGE_RETENTION_RU.md;
- RETROSPECTIVE_DATA_CONTRACT_RU.md;
- FUNCTION_BACKLOG.json;
- CLI_AND_REPORTS_RU.md;
- PR_ROADMAP_RU.md.

**Не переписывать этот контур.** Сначала сверить backlog, реальный код, тесты, CLI и runtime wiring. Задача — закрыть интеграционные пробелы и связать владельцев, а не сделать Local Intelligence V3.

## 2.2 Канонические рыночные owners

Обязательно повторно использовать:

1. src/agg02/storage.py:
   DurableRawJournal, JournalCursor, GapRecord, AnalyticalDatasetPublisher, DatasetReplayReader, retention pins и verified payload archive.

2. src/agg02/contracts.py:
   RawEventEnvelope, StateRecord, StateFrame, availability/cursor lineage.

3. src/market/observations.py:
   MarketObservationV2, ObservationGeneration, SourceCursor, watermarks, completeness, correction/retraction и gap semantics.

4. src/market/streams.py:
   durable cursors, reconnect epochs и gap-aware observation publication.

5. src/market_data_evolution/contracts.py:
   RawObservation, NormalizedObservation, MarketEpisode, ReplayManifest, QualificationEvidence, ModelCandidate, RetentionReport, as-of selection и state materialization.

6. src/production_qualification.py:
   funnel, campaign qualification, baseline comparison, delay stress и dashboard helpers.

7. src/strategy/market_graph_ingest.py:
   source traces с observation ID, cursor, response hash и request fingerprint.

8. src/intelligence/episode_builder.py:
   stage binding с MarketEpisode; этапы PRE_QUOTE, QUOTE, SIZING, PLANNER, COMPILER, SIMULATION, RECONCILIATION, PAPER_OUTCOME; linking negative examples.

**Не создавать вторую raw market DB и второе понятие MarketEpisode.** Новые хранилища допустимы как аналитические проекции, а не конкурирующая истина.

## 2.3 Strategy/scheduling/execution owners

Перед любым изменением читать актуальные версии:
- src/strategy/registry.py, interfaces.py, strategy_contract.py, strategies.py;
- src/strategy/opportunity_identity.py, queue.py, ranker.py, tracker.py, runtime.py;
- src/strategy/arbitrage_graph.py, multihop_solver.py, market_graph_ingest.py;
- src/strategy/conflict_scheduler.py, shadow_workers.py, shadow_portfolio.py;
- src/assets/resolution/, src/discovery/dynamic_universe/;
- src/research_economic_graph/, src/research/correlation_ledger/;
- src/economics/flash_capital_graph/;
- src/planning/, src/execution/exact_simulation.py, src/paper_shadow/;
- src/runtime/core_v1_composition.py и durable authority/reservation owners.

ConflictAwareScheduler — sender-free admission scheduler для parallel discovery/simulation jobs: resource sets, deadlines, worker fences, deduplication/conflict rejection и reservation port. shadow_workers — bounded offline replay; worker не резервирует ресурсы и не получает execution authority. shadow_portfolio переиспользует существующий portfolio optimizer.

Эти блоки подходят для параллельной оценки и симуляции. Это не разрешение на параллельную live submission.

## 2.4 Реальная граница продукта

README на audited main явно говорит:
- текущий repo пока не является production-ready end-to-end arbitrage bot;
- поддерживаемая composition — sender-free paper/shadow;
- live hard-denied;
- часть strategy/adapter/build paths требует evidence и остаётся blocked/fixture-only;
- наличие legacy code не доказывает поддерживаемую runtime capability.

Это ограничение распространяется на все work packages. Не добавлять live path, signer authority, submission, borrowing, account creation, provider enabling или deployment.

## 2.5 Старый AI_TRADING_SYSTEM.md

Корневой AI_TRADING_SYSTEM.md описывает прежнюю/aspirational схему ArbitrageScorer → PriorityQueue → DataCollector → AI Analyzer и старые примерные показатели. Не считать его runtime truth или доказательством текущих capabilities. Сверять его с актуальными strategy, decision, qualification и paper owners.

---

# 3. Целевая архитектура

Сохранить два самостоятельных data planes и один тонкий join/query plane. Не создавать один гигантский текстовый корпус.

~~~text
CODING / RESEARCH PLANE
Git HEAD + worktrees + task/owner map + ADRs + manifests
        |
        v
Exact repo snapshot / manifest
        |
        +--> Python AST / symbols / imports / SCC / logical groups
        |
        +--> Graphify evaluation as optional polyglot/doc/config sidecar
        |
        v
Code / config / test relation index
        |
        v
Bounded context pack builder
        |
        +--> ChatGPT / coding agents / optional read-only MCP


MARKET / RUNTIME PLANE
QPR/DIN admitted sources + current provider/market owners
        |
        v
AGG-02 DurableRawJournal + cursors + gaps
        |
        v
MarketObservationV2 + source generation + watermarks
        |
        v
Existing discovery / graph / candidate / conflict scheduler
        |
        v
quote -> sizing -> planner -> compiler -> simulation
        |
        v
reconciliation -> durable paper outcome -> MarketEpisode
        |
        v
rollups / provider utility / strategy comparison / reports
        |
        v
Parquet + ZSTD archive


DETERMINISTIC JOIN / QUERY PLANE
repo_sha | config_sha | strategy_id | experiment_id | symbol_id
logsite_id | trace_id | observation_id | candidate_id | episode_id
        |
        v
Versioned Entity & Label Projection + Evidence References
        |
        v
Read-only Studious Intelligence Facade
repo map | strategy explain | source lineage | trade trace
episode compare | test impact | bounded context pack
~~~

## 3.1 Code plane

Local Intelligence V2 остаётся authority для exact Git snapshots, hashes, current Python AST, groups и context packs.

Polyglot расширение — sidecar/provider interface. Graphify можно проверить на exact pinned SHA: он заявляет local tree-sitter parsing примерно 40 языков и поддержку docs, SQL schemas и configs. Не подключать его к trading runtime. Импортировать его полезные узлы/рёбра только если precision/coverage заметно лучше текущего индекса и provenance сохраняется.

Текущий repo_source явно ограничен Python AST. Это настоящий coverage gap: непокрытые языки и типы файлов должны отражаться в report, а не исчезать из обзора.

## 3.2 Market plane

AGG-02 и MarketObservation остаются источником истины для raw observations, cursors, gaps, correction/retraction и replay.

Для каждого ценного episode сохранять:
- observation refs и source/provider generation;
- timestamps и availability time;
- block/slot/checkpoint, если он реально известен;
- quote, sizing и нормализованные economics;
- selected и rejected alternatives;
- stage decisions и reason codes;
- simulation/reconciliation;
- paper outcome;
- точные repo/config/strategy/experiment identities.

Сохранять отрицательные случаи: quiet windows, detector rejection, stale quote, source disagreement, sizing/builder rejection, simulation/reconciliation failure и неудачные candidates — по действующей deterministic sampling/pinning policy.

## 3.3 Join/query plane и Label Registry

Join plane — это versioned materialized projection из canonical owners, а не новая система хранения истины.

Типы сущностей:
- RepositorySnapshot, File, Symbol, Test, Contract, Config;
- Strategy, StrategyVersion, StrategyExperiment;
- Chain, Venue, Protocol, Asset, FlashCapitalSource;
- DataSource, Provider, Adapter, Tool, Dependency;
- MarketObservation, Opportunity, Candidate, Simulation;
- ExecutionAttempt, TransactionReceipt, PaperOutcome, MarketEpisode;
- LogSite, RuntimeTrace, Decision, FailureClass, Task, Worktree, PullRequest.

Типы отношений:
- CONTAINS, DEFINES, CALLS, IMPORTS, TESTED_BY, CONFIGURED_BY;
- IMPLEMENTS_STRATEGY, USES_SOURCE, USES_PROVIDER, USES_VENUE, USES_CAPITAL;
- EMITS_LOGSITE, OBSERVED_BY, PRODUCED_CANDIDATE, SIMULATED_AS;
- RECONCILED_AS, RESULTED_IN, REJECTED_BY, DEPENDS_ON, SUPERSEDES;
- OWNED_BY_TASK, CHANGES_FILE, VALIDATED_BY.

Каждый node/edge должен хранить:
- стабильный ID и тип;
- canonical owner/source path;
- repo SHA и source/file hash там, где применимо;
- schema version;
- valid-time / snapshot identity и recorded_at;
- evidence refs;
- derivation: deterministic, manually declared, external source или model-suggested;
- status: verified / provisional / stale / missing / conflicted.

Model-suggested relation нельзя выдавать за verified. Inferred graph edges не становятся разрешением или capability truth.

### Identity rules

- ID namespace-scoped и детерминированный по canonical identity, а не display name.
- Asset identity включает chain/genesis/program/contract identity; одинаковый ticker не означает один актив.
- Provider отдельно от aggregator route и underlying venue/pool.
- Несколько aggregator quotes не доказывают независимую ликвидность.
- Docs alias не заменяет runtime strategy ID.
- Unknown identity остаётся UNKNOWN, а не нулём или догадкой.

### Label taxonomy

Начальный закрытый словарь:
- stage: DISCOVERY, QUOTE, SIZING, PLANNER, COMPILER, SIMULATION, RECONCILIATION, PAPER_OUTCOME;
- status: IMPLEMENTED, WIRED, QUALIFIED, BLOCKED, UNKNOWN;
- relation class: LOCAL_ATOMIC, CONDITIONAL_HYPEREDGE, HEDGED_NON_ATOMIC, SIGNAL_ONLY, EXCLUDED;
- failure: STALE_DATA, SOURCE_GAP, INSUFFICIENT_LIQUIDITY, CAPACITY_REJECTED, BUILDER_REJECTED, SIMULATION_REVERT, NOT_RECONCILED;
- evidence: SOURCE_PINNED, REPLAY_VERIFIED, PAPER_OBSERVED, HUMAN_REVIEWED.

Registry содержит taxonomy, aliases, schema version и ссылки на owners. Strategy/source/capability facts продолжают жить в их canonical owners.

---

# 4. Детерминированная корреляция runtime ↔ code

Это обязательная часть. Связь нельзя строить только по тексту лога или номеру строки.

## 4.1 Event envelope

Для decision-affecting и stage-transition events проверить/дополнить typed envelope. Сначала переиспользовать RawEventEnvelope, MarketObservationV2, decision dataset и MarketEpisode.

~~~json
{
  "event_id": "stable-event-id",
  "event_type": "strategy.candidate.rejected",
  "run_id": "run-id",
  "trace_id": "trace-id-or-null",
  "span_id": "span-id-or-null",
  "logsite_id": "stable-logsite-id-or-null",
  "symbol_id": "qualified-symbol-id-or-null",
  "strategy_id": "canonical-strategy-id-or-null",
  "strategy_version": "strategy-version-or-null",
  "repo_sha": "exact-commit",
  "config_hash": "canonical-config-hash",
  "experiment_id": "experiment-id-or-null",
  "candidate_id": "candidate-id-or-null",
  "observation_refs": [],
  "stage": "SIMULATION",
  "action": "REJECT",
  "reason_code": "STALE_QUOTE",
  "available_at": "source-availability-time",
  "recorded_at": "system-recording-time",
  "chain_id": 0,
  "block_or_slot": null,
  "generation_id": "provider-and-policy-generation",
  "payload_hash": "sha256"
}
~~~

Это концептуальный контракт, а не требование копировать все поля в новый класс. Не выдумывать отсутствующие timestamps, block/slot, provider facts или output amounts.

## 4.2 Stable Statement / LogSite IDs

1. Создать static AST scanner для logging calls и structured event emitters. Начать с Python.
2. Добавить explicit stable logsite_id/statement_id к high-value business events: candidate accepted/rejected, route selected, capacity rejected, build failed, simulation result, reconciliation result, paper outcome, provider failure.
3. Хранить mapping ID → repo-relative path, qualified symbol, normalized callsite signature, event type, first-seen commit и current source span.
4. Для legacy logs дать provisional ID, но collision/ambiguous move переводить в NEEDS_REVIEW. Line number — только навигация, не identity.
5. Эмитировать repo_sha, strategy_id, experiment_id, trace_id, candidate_id и stage там, где они реально доступны.
6. Correlator по logsite_id + repo_sha находит exact snapshot, symbol, strategy и tests.
7. При удалении/перемещении callsite сохранять историю; SUPERSEDES/alias связь добавлять только при детерминированном совпадении или review.

Для старых логов без ID:
- сначала structured fields и stack traces;
- затем проверить logsite на реальных обезличенных логах;
- normalized log-template matching разрешить только как более слабый fallback;
- маркировать INFERRED, хранить основание/уверенность, не представлять как точную source proof.

logsite — early 0.x кандидат, заявляет поддержку Python/Java/Go и нескольких logging frameworks/log stores. Это может ускорить ретроспективный анализ, но не заменяет stable IDs в ключевых событиях и market observation lineage.

## 4.3 OpenTelemetry

Использовать trace/span IDs для runtime causal context, если текущей instrumentation недостаточно. Не путать:
- trace_id/span_id — один runtime путь;
- logsite_id — исходный statement, выпустивший запись;
- symbol_id — функция/метод;
- strategy_id — бизнес-стратегия;
- candidate_id/episode_id — рыночная возможность.

Добавлять OTel там, где это закрывает доказанный gap; не строить второй observability stack.

---

# 5. Политика по внешним инструментам

## 5.1 Использовать как основу

- Existing Local Intelligence V2 — база repo snapshot, AST, packs, reports, retention и triage.
- Git worktrees + current task/owner/PR process — модель параллельной разработки.
- AGG-02 + MarketObservation + MarketEpisode + Parquet/ZSTD — рыночная truth/replay foundation.
- Versioned Entity/Label projection + deterministic correlator — главный недостающий join layer.
- Existing CLI — расширять только после аудита фактического parser/API.

## 5.2 Проверить как ограниченные эксперименты

| Инструмент | Что может дать | Правило решения |
|---|---|---|
| Graphify | Polyglot tree-sitter graph, docs/config/SQL relations, graph queries | Запустить на pinned repo SHA; сравнить coverage, edge precision, incremental refresh, RAM/disk и context-pack quality; держать sidecar |
| jCodeMunch MCP | Symbol-level retrieval с точными source slices | Текущая dual-use license требует paid license для commercial/revenue-supporting use. Не использовать в таком workflow без согласованной лицензии |
| logsite | Поиск источника production errors/logs/tests | Проверить на реальных sanitized Python logs; early 0.x, diagnostic helper, не обязательный runtime dependency |
| SQD Portal MCP | Query raw/decoded on-chain rows, traces, logs and network data | Research/evidence adapter; production ingest только через текущие source governance/schema/provenance/quota/replay owners |
| Antseer MCP | Supplemental on-chain analytics, flows, safety, token/wallet context | Optional advisory source; сохранять provider timestamp/provenance; не заменять exact chain state или quote truth |
| Mimir | Hybrid BM25/vector search, code/docs/memory graph, symbol navigation | Benchmark only, если exact retrieval/context packs не проходят golden questions. README указывает O(n) vector scan по RAM/time; измерить на реальном объёме |
| growmos | Provenance-carrying semantic graph для docs, ADRs, READMEs и agent sessions | Benchmark only при реальной multi-agent memory gap. По умолчанию не индексирует raw source code; не использовать как market store |
| ctxgraph / NervaPack | Альтернативные compact context/graph capsules | Только benchmark; доказать token savings и сохранение evidence на фиксированных вопросах |
| codingest / synaptiq / code-graph-rag / graphize / SocratiCode | Revision-aware, polyglot, multi-repo graph/index варианты | Не устанавливать пачкой. Выбрать одного challenger под измеренный gap |
| ClickHouse | High-volume analytical event/log queries | Отложить. AGG-02 + Parquet остаются canonical. Добавить только после измеренного throughput/query bottleneck; это будет analytical projection |
| NATS JetStream | Durable event distribution между независимыми consumers | Отложить, пока существующий journal/cursors покрывают deployment |
| S3/object storage | Remote cold archive | Отложить до подтверждённой потребности backup/remote retention |
| TerminusDB / temporal KG | Versioned knowledge graph/schema history | Не внедрять сейчас; начать с versioned JSON schema, Git migrations и existing as-of contracts |
| Langfuse / Jaeger MCP / extra agent observability | LLM/distributed trace inspection | Опционально после появления trace IDs и подтверждённого gap |

Версии, лицензии, цены и доступность инструментов перепроверять во время внедрения. Не превращать найденные сегодня сведения в бессрочную истину.

## 5.3 Не делать в MVP

- Не ставить Mimir и growmos одновременно.
- Не ставить Graphify + codingest + code-graph-rag + jCodeMunch как обязательные overlapping indexes.
- Не добавлять ClickHouse как вторую canonical raw DB.
- Не связывать Antseer/SQD напрямую с production trade decisions.
- Не давать Laya/LLM право на физическое удаление, admission, live execution или promotion.
- Не вводить Kubernetes, distributed queues и autonomous-agent runtime без измеренной необходимости.
- Не использовать Repomix как persistent index; оставить только для ad hoc portable snapshot.
- Не менять стратегическую экономику или execution logic этой кампанией.

---

# 6. Хранение и сжатие

## 6.1 Три разных вида оптимизации

**Context/token reduction:** извлекать только нужные symbols, tests, manifests и evidence. Это основной источник экономии LLM-контекста.

**Index reduction:** хранить компактные metadata/hashes; не embedding-овать каждый log/event. Embeddings опциональны и пересобираемы.

**Physical retention:** исходные evidence и raw payload сохраняются по policy; удаление допустимо только после deterministic receipt и replay proof.

Context pack никогда не должен становиться единственной копией исходного evidence.

## 6.2 Hot / warm / cold на текущих owners

- Hot/raw: AGG-02 journal с bounded retention, cursors, gaps, generations и candidate pins.
- Normalized/replay: MarketObservation/dataset owners и verified Parquet partitions.
- Episodes/evidence: MarketEpisode, qualification receipts, experiment manifests, high-value negative examples и terminal paper outcomes.
- Rollups: 1m/5m/1h и provider/strategy utility, с derivation version и source time range.
- Code snapshots/index: exact Git SHA + manifest + hashes + structural index + packs.
- Cold archive: Parquet/ZSTD; remote object store только после измеренной необходимости.

Сохранить существующую retention policy:
- никаких oldest-N/fixed-percentage deletes;
- защищать pinned evidence, active experiment refs, gaps, corrections, retractions, replay mismatch, unique anomalies, schema drift и terminal outcomes;
- сначала compact в Parquet, проверить checksums/ranges/replay, создать retention receipt и только потом рассматривать eligible raw expiry;
- при critical pressure и недостатке безопасного reclaim останавливать admission новой collection, а не удалять защищённые данные.

## 6.3 Формат context pack

Каждый pack содержит:
- goal и retrieval mode;
- exact repo SHA, branch и snapshot identity;
- pack schema/version и byte/token budget;
- included/excluded evidence refs и причину включения;
- file hashes, source ranges и symbol IDs;
- strategy/source/provider relations;
- tests и точные команды проверки;
- связанные episodes/decision records, если они нужны;
- непокрытые, неизвестные и неоднозначные области.

Приоритет включения:
1. точный вопрос и целевая сущность;
2. canonical strategy/source/config manifests;
3. точные symbols/callsites/contracts;
4. связанные tests/fixtures и runtime composition;
5. связанные stage decisions/episodes и negative examples;
6. ADR, source dossiers и docs;
7. дополнительное соседство графа пока позволяет budget.

Сырые массивные логи не класть целиком. Возвращать IDs и bounded excerpts; отдельной командой получать точный payload по ссылке.

## 6.4 Retrieval benchmark

Сделать frozen set минимум из 30 реалистичных вопросов:
- все стратегии, использующие заданный financing source;
- функции и тесты конкретной стратегии;
- кто использует provider/source/venue и каков evidence status;
- какой logsite выпустил событие;
- какие источники и state были доступны при решении candidate X;
- сравнение стратегий на одинаковых episodes;
- impact изменения shared adapter;
- unindexed languages, missing graph edges и stale source pins.

Метрики:
- exact-answer precision/recall;
- полнота evidence citations;
- обнаружение UNKNOWN/unsupported;
- retrieval latency;
- bytes/tokens per pack;
- index build/update time;
- CPU/RAM/disk;
- false-edge rate;
- stale-index rate после commit/branch change.

Меньший pack не лучше, если он потерял test или rejection reason, объясняющий проблему.

---

# 7. Параллельная разработка и trading/replay

## 7.1 Текущий этап: ChatGPT + coding agents

Автономный agent orchestrator не нужен. Использовать текущую worktree/PR модель.

Каждая задача получает:
- task_id;
- одного owner/agent и один worktree/branch;
- exact base SHA;
- разрешённые файлы и shared owners;
- зависимости и predecessor tasks;
- context-pack request/path;
- acceptance tests и evidence requirement;
- status/blocker/review state.

Coordinator:
- обновляет main SHA, PR и checks перед dispatch;
- замораживает interfaces перед параллельной реализацией;
- запрещает overlapping write ownership;
- использует один canonical task/status board;
- сериализует shared-owner edits;
- проверяет каждую задачу на актуальном main;
- требует human approval для implementation PR merge согласно AGENTS.md.

Не создавать новую task DB, если master roadmap/status JSON/parallel PR queue покрывают функцию. Расширять существующий canonical owner.

## 7.2 Что можно запускать параллельно

- provider/source research и qualification;
- discovery и candidate generation;
- независимые exact route calculations;
- offline replay и fork simulation;
- shadow ranking и portfolio comparison;
- reports.

Централизованные ресурсы остаются у существующих authorities:
- opportunity/resource conflict decision;
- capital и quota reservation;
- lifecycle/finality;
- signer/submission authority (сейчас вне поддерживаемой sender-free MVP composition);
- promotion/risk policy.

Одна и та же opportunity, pool, lender reserve, account, nonce или underlying liquidity не должны учитываться дважды только потому, что их вернули разные adapters/strategies.

## 7.3 Operations report

Показывать:
- текущий runtime/product mode и capability truth;
- source health/freshness/gaps/cursor/reconnect/quota;
- active strategy/experiment и exact code/config generation;
- candidate funnel и reason codes;
- conflict scheduler state и rejected conflicts;
- simulation/reconciliation/paper outcomes;
- provider utility и unique candidate contribution;
- retained/compacted/pinned data и disk forecast;
- test/release/PR status;
- unresolved blockers с evidence refs.

Process liveness не выдавать за trading readiness.

---

# 8. План внедрения для coding agent

Это integration/qualification campaign, не greenfield rewrite. Работать reviewable checkpoints. Начать только с W0. Не запускать W1-W6, пока audit не покажет точные gaps.

## W0 — Baseline и owner audit (P0, обязательно)

1. Прочитать AGENTS.md, CODEX_START_HERE.md, Local Intelligence V2 docs и master knowledge map.
2. Fetch latest main, PR/workflows/checks и записать текущий SHA. SHA в этой спецификации — audit baseline, не предполагаемая актуальная база.
3. Прочитать все owners и tests из раздела 2.
4. Запустить current repo/CLI status и целевые intelligence/scheduler/market tests; указать exact command/platform/pass/fail/skip.
5. Сопоставить FUNCTION_BACKLOG.json и PR roadmap с фактическими модулями, tests и runtime/CLI wiring.
6. Создать machine-readable integration matrix со статусами EXISTS_TESTED, EXISTS_UNVERIFIED, PARTIAL, MISSING, DUPLICATE_RISK, BLOCKED.
7. В W0 не создавать сервисы/базы.

Deliverables:
- AUDIT_CURRENT_OWNERS_RU.md;
- INTEGRATION_MATRIX.json;
- current CLI/coverage/test report;
- prioritized gaps с owner и evidence.

Acceptance:
- каждый proposed block связан с current owner или явно отмечен missing;
- duplicate authority нет;
- README product truth сохранён;
- все выводы ссылаются на current SHA, paths и tests.

## W1 — Canonical registry и typed relation projection (P0)

Только после W0. Реализовать derived projection, а не replacement source of truth.

Покрыть:
- strategy/strategy version;
- code file/symbol/test/contract/config;
- data source/provider/adapter/tool/dependency;
- chain/asset/protocol/venue/flash-capital source;
- runtime event/candidate/episode/experiment.

Требования:
- stable namespaced IDs;
- typed entity/relation schema;
- aliases и controlled labels;
- canonical owner/source для каждого поля;
- schema version/migrations;
- repo SHA/config hash/evidence refs;
- valid-time и recorded-time там, где доступны;
- verified/provisional/stale/unknown/conflicted;
- deterministic rebuild из existing owners;
- unreviewed LLM-inferred relation не может стать verified.

Выбрать generated SQLite/JSONL/index только после аудита текущей persistence model.

Acceptance:
- любую strategy/source node можно проследить до canonical source;
- schema validation ловит duplicate/missing IDs и dangling edges;
- unknown entities видны;
- projection diff двух repo SHA детерминирован.

## W2 — Polyglot/code retrieval benchmark (P1)

1. Измерить текущий language coverage repo_source.
2. Зафиксировать baseline exact retrieval на golden questions.
3. Запустить Graphify на pinned snapshot как isolated sidecar.
4. Сравнить symbols/edges, docs/config/SQL coverage, refresh time, RAM/disk и query precision.
5. jCodeMunch тестировать только при согласованной лицензии для revenue-supporting use.
6. Выбрать: расширять repo_source через Tree-sitter, импортировать Graphify или оставить текущий parser. Решение должно быть воспроизводимо.

Acceptance:
- indexing не меняет исходный source tree;
- exact commit binding и source hashes сохраняются;
- unsupported formats видны;
- измерены build/update cost и retrieval quality.

## W3 — Deterministic logsite/decision correlation (P1)

1. Инвентаризировать structured logs и decision/event emitters.
2. Инвентаризировать stage transitions и reason-code producers.
3. Определить logsite/Statement ID schema и mapping manifest.
4. Сначала добавить IDs в одну high-value vertical: candidate decision → simulation → reconciliation → paper outcome.
5. Реализовать correlator logsite_id + repo SHA → exact file/symbol/function/strategy/test.
6. Использовать существующие observation/episode/evidence refs.
7. Проверить logsite на sanitized legacy logs, зафиксировать coverage и limitations.
8. Trace/span IDs добавлять только при недостатке текущей async correlation.

Acceptance:
- нет LLM в hot correlation path;
- mapping воспроизводим с exact repo SHA;
- ambiguous/missing → UNKNOWN/NEEDS_REVIEW;
- stage events имеют candidate/strategy/experiment/code/source refs там, где они доступны;
- отсутствующие факты не выдумываются;
- line number не является stable identity.

## W4 — Read-only query façade и context packs (P1)

Расширить существующий src/intelligence/cli.py только после проверки реального parser и тестов. Предлагаемый command surface, адаптируемый к текущим convention:

~~~text
python -m src.intelligence.cli repo map
python -m src.intelligence.cli strategy list
python -m src.intelligence.cli strategy explain <strategy_id>
python -m src.intelligence.cli strategy compare <strategy_a> <strategy_b>
python -m src.intelligence.cli source list [--strategy <id>]
python -m src.intelligence.cli source lineage <source_id>
python -m src.intelligence.cli code symbol <symbol_id>
python -m src.intelligence.cli code impact <path-or-symbol>
python -m src.intelligence.cli trace <trace_id-or-logsite_id>
python -m src.intelligence.cli episode show <episode_id>
python -m src.intelligence.cli episode compare <experiment_a> <experiment_b>
python -m src.intelligence.cli pack build --goal "<question>" --budget-bytes <n>
~~~

Все команды read-only, bounded, evidence-backed. Не добавлять RPC/signing/submission функции.

Pack acceptance:
- exact main SHA, manifest ID и pack schema;
- included/excluded evidence и причины;
- precise source links и reason codes;
- byte/token budget honored;
- continuation/resume;
- отсутствие secrets/private keys/account materials;
- одинаковый pack для одинаковых snapshot/query parameters.

После стабилизации CLI можно добавить local stdio MCP wrapper, если он реально улучшает coding-agent workflow. Remote MCP без auth/scope/audit не создавать.

## W5 — Retrospective strategy/provider reports (P1)

Reuse MarketEpisode, production_qualification, provider_utility, reports и experiment manifests.

Сравнение стратегий:
- одна и та же frozen episode set/time window;
- одинаковая source availability и evidence quality;
- explicit strategy/config/repo versions;
- equal/normalized provider/compute budget;
- point-in-time features без future leakage;
- positive и negative outcomes;
- exact evidence refs для метрик.

Добавлять только недостающие метрики: unique provider candidate contribution, stale quote/slot skew, source disagreement, latency budget, conflict rejection, disk cost per useful episode и estimated-vs-realized economics, только где есть реальные paper evidence.

Acceptance:
- synthetic outcome не выдаётся за actual;
- отсутствующее = UNKNOWN/NOT_OBSERVED;
- baseline/challenger dataset frozen/verifiable;
- rejection reasons и negative examples включены.

## W6 — Storage scale gate (P2, conditional)

1. Измерить AGG-02/SQLite/WAL/Parquet/context-index bytes и ingest/query throughput.
2. Проверить retention/compaction replay verification и recovery.
3. Выполнить representative sustained load/soak.
4. Только затем решать, нужен ли ClickHouse или remote object storage.
5. ClickHouse, если появится, — аналитическая проекция по canonical event IDs/receipts, не конкурентный raw journal.

Acceptance:
- byte budget/forecast measured;
- compaction/replay exact;
- pinned evidence сохраняется;
- crash/recovery tests проходят;
- если ClickHouse не нужен, записать measured NOT_REQUIRED_YET.

---

# 9. Тесты и review contract

Минимум проверить актуальность и запустить (если пути не изменились):
- make verify;
- make test или targeted offline tests;
- Local Intelligence V2 / AGG-10 intelligence tests;
- tests/test_agg05_conflict_scheduler.py;
- tests/test_shadow_workers.py;
- tests/test_shadow_replay.py;
- tests/test_mpr042_market_truth.py;
- tests/test_agg02_market_data_capital.py;
- strategy inventory/replay и paper-shadow/reconciliation tests;
- новые registry/correlation/context-pack tests.

Обязательные негативные кейсы:
- dirty worktree и mismatch SHA;
- rename/move source callsite и stable logsite identity;
- unsupported language/parser;
- duplicate/ambiguous symbols и aliases;
- stale index/branch switch;
- source cursor gap/reconnect/correction/retraction;
- duplicate event/idempotency;
- schema migration/old snapshots;
- context budget/continuation;
- secret exclusion/path traversal/symlink;
- evidence pins блокируют deletion;
- LLM-suggested edges не становятся verified;
- parallel task file collision/worker fencing;
- query tools не получают live/signer/sender authority.

Не заявлять тесты, которые не запускались. Всегда записывать точные pass/fail/skip и команды.

---

# 10. Governance invariants

1. Ни private keys, seed phrases, production credentials, ни sensitive account data не попадают в context packs, memory, logs или Git.
2. Query façade read-only.
3. Laya/LLM может rank/summarize/request review, но не authorize trade, provider admission, deletion, promotion или merge.
4. Любое добавление provider/source проходит действующие governance/evidence gates.
5. Strategy/execution status grounding берётся из canonical owners.
6. В этой кампании нет live transaction build/sign/send/borrow/spend/deploy.
7. LIVE остаётся hard-denied.
8. Для implementation PR merge требуется human approval согласно AGENTS.md.
9. Для внешних sources сохранять source pin, license, retrieval time и legal-use status.
10. Generated indexes rebuildable; не коммитить huge binary indexes и secret-bearing snapshots.
11. Отсутствующий факт — UNKNOWN, не ноль.
12. Сохранять negative evidence, source gaps, corrections, retractions и replay mismatches.

---

# 11. Финальная проверка полезности для ChatGPT

Один bounded query/context pack должен позволять ответить с точными evidence refs:

1. Перечислить стратегии и разделить implemented/wired/qualified/blocked/unknown.
2. Для strategy показать entrypoints, функции, dependencies, configs, chains, venues, flash-capital sources, providers и tests.
3. Для source/provider/tool показать назначение, потребителей, admission status, schema/version, limits, provenance и freshness.
4. Показать call graph и change impact, включая owning tests.
5. Восстановить source observations/data quality на момент candidate decision.
6. Связать structured logsite/Statement ID с exact repo SHA, function, strategy, experiment и stage.
7. Показать stage decisions, thresholds, reason codes, alternatives и simulation/reconciliation/paper outcome.
8. Сравнить strategy A/B на одних frozen episodes и разделить simulation metrics от actual outcomes.
9. Объяснить, что retained/compacted/pinned/expired и почему.
10. Показать неиндексированные, не наблюдавшиеся, unsupported и unavailable области.

Успех — evidence-backed retrieval с низкой стоимостью контекста и честными gaps, а не просто большой graph/vector index.

---

# 12. Самое первое действие coding agent

**Запустить W0 и W0A параллельно.** W0 проверяет canonical owners/runtime wiring; W0A независимо сравнивает Tree-sitter, CodeGraphContext, Graphify, SCIP/LSP и текущий native index на одном SHA. Не начинать изменения event schema до W0 evidence, но **не останавливаться после аудита**: затем выполнить W0B и все dependency-ready work packages. Сначала reuse; потом только доказанные additive gaps.

Первый отчёт обязан ответить:
- Какие Local Intelligence V2 backlog items реально реализованы и протестированы на текущем main?
- Что есть в коде, но не wired в CLI/runtime?
- Какие языки/типы файлов не индексируются?
- Какие strategy/source/provider registries canonical, а какие только docs/catalogues?
- Какие execution stages имеют durable event IDs и reason codes?
- Какие logsites уже можно детерминированно связать с symbols?
- Какие поля уже соединяют repo SHA/config SHA/strategy/experiment/candidate/episode?
- Какой наименьший additive change закроет самый ценный gap?

После этого coordinator выдаёт W1/W2/W3 как отдельные work packages по разным owners. Merge — только после exact-head tests/evidence review и человеческого approval.


---

# 13. Расширение scope: Operations Context Aggregator + ChatGPT/Coding Agent MVP

Эта спецификация теперь включает не только code graph/context retrieval, но и полноценный **Operations Context Aggregator (OCA)** для связывания runtime facts с Web3 market evidence, стратегиями, кодом и историческими результатами.

Обязательные документы читать в таком порядке:

1. Этот файл — master entrypoint и ограничения.
2. [OPERATIONS_CONTEXT_AGGREGATOR_RU.md](OPERATIONS_CONTEXT_AGGREGATOR_RU.md) — operation event model, data planes, code/runtime correlation, flashloan parallelism/resource conflicts, source adapters, compression/storage, reports и OCA work order.
3. [CHATGPT_CODING_AGENT_CONTEXT_WORKFLOW_RU.md](CHATGPT_CODING_AGENT_CONTEXT_WORKFLOW_RU.md) — MVP для текущей стадии ChatGPT + coding agents, Task Packet, Work Result Receipt, Git worktree workflow, zero-LLM indexing и способы передачи context pack в ChatGPT.
4. [TOOL_ACCESS_PROFILES_RU.md](TOOL_ACCESS_PROFILES_RU.md) — local tools, optional MCP profiles, license/data-residency restrictions, narrow tool surfaces and reproducible installation.

## 13.1 Важное новое обнаружение: существующий EventEnvelope — центральный operation fact

На audited main уже есть EventEnvelope в src/observability/events.py и durable store в src/observability/store.py. Использовать его, не создавать второй event schema/store.

Он уже включает trace_id, logical_opportunity_id, plan_hash, attempt_id/generation, tx_signature, jito_bundle_id, stage, outcome, reason_code, provider_id, venue_id, evidence_ref, producer_code_version, config_checksum и idempotency_key. Также существуют append-only event log, tamper-evident chain, attempt/opportunity projections, replay/export/archive, authoritative schema и operator-readiness owners.

Критический audit gap: проверить, как фактически заполняются и сохраняются strategy_id/version, exact repo SHA, config generation, source observation IDs, chain/block/slot identity, resource lock sets и stable code callsite. Не предполагать, что field присутствует в dataclass — проверить реальные producers и serialized rows.

Текущая Environment model test/shadow/paper; LIVE остаётся hard-denied. Event types с submission/bundle названиями не являются разрешением на live submission.

## 13.2 Первый coding-agent stage — W0 + parallel code-intelligence bake-off

W0 теперь обязан:
- проверить actual EventEnvelope producers и полный путь до ObservabilityStore/export/replay;
- проверить соединение operations events с AGG-02/MarketObservation/MarketEpisode;
- определить наличие strategy/source/provider/config/repo identity в реальных event rows;
- проверить logsite/symbol mapping (если отсутствует — зафиксировать gap);
- прочитать src/strategy/conflict_scheduler.py, shadow_workers.py, shadow_portfolio.py и доказать текущие boundaries для параллельной работы;
- сверить Local Intelligence V2 CLI и текущие команды на свежем main;
- установить coverage по языкам и типам артефактов;
- сформировать EVENT_CORRELATION_MATRIX.json и INTEGRATION_MATRIX.json;
- вернуть exact SHA, команды, pass/fail/skip и evidence refs.

Не менять event schemas до отчёта W0. При этом W0A идёт параллельно, а W0B (первая рабочая repo knowledge graph) запускается после W0 и W0A. Дальше агент продолжает dependency-ready packages без отдельного ожидания пользователя; merge остаётся только human-approved.

## 13.3 Новая implementation sequence

Подробные acceptance criteria находятся в Operations Aggregator document. Упорядочить work packages так:

- W0 — current owner/event correlation audit;
- W0A — parallel tool/polyglot index bake-off (same SHA, golden questions, licenses, latency, RAM/disk, token budgets);
- W0B — first working repo-wide knowledge graph, compact strategy/tool/source catalogues, read-only queries and context packs;
- W1 — correlation completeness matrix and exact join contract;
- W2 — deterministic OperationEpisode projection over existing owners;
- W3 — stable logsite/Statement IDs for one high-value vertical;
- W4 — bounded operation/strategy context pack CLI/API;
- W5 — strategy/resource conflict and parallel admission reports;
- W6 — bounded SQD/Antseer read-only evidence profiles;
- W7 — golden retrieval/token-efficiency benchmark across selected indexes and packs;
- W8 — operations cockpit, report bundles and reviewer workflow;
- W9 — measured storage scale gate; ClickHouse/NATS/remote archive only if measured need;
- W10 — mandatory runtime capture: wire real supported test/paper/shadow producers to durable correlated events, source evidence, trace/callsite and terminal outcomes;
- W11 — mandatory universal read-only query/export/replay across code graph, operational events, raw/normalized market data, episodes and work receipts.

## 13.4 Режим разработки, пока нет автономных AI agents

Использовать ChatGPT как стратег/архитектор/reviewer, coding agents — как исполнителей отдельных Task Packets. Каждая задача содержит exact base SHA, allowed read/write paths, single owner/worktree, acceptance tests and context-pack manifest. Каждый coding agent возвращает Work Result Receipt с head SHA, changed files, test counts, artifact hashes, blocker list and index freshness.

Не строить автономный swarm сейчас. Сначала сделать надёжными task packets, worktree ownership, deterministic code index, operation context packs и receipts. Это даст immediate value уже для одного ChatGPT + одного coding agent и масштабируется до нескольких coding agents.

## 13.5 Автоматический проход через индекс и labels

Новый код должен индексироваться автоматически через local CLI/hooks и authoritative CI on push/PR:
- Git SHA + file hashes;
- AST/symbols/dependencies;
- deterministic labels из canonical registries/manifests;
- tests/configs/owner links;
- coverage/stale-index report.

Это работает без LLM. Semantic labels, intent и ambiguous strategy mapping остаются PROPOSED/UNKNOWN до human review или LLM-assisted suggestion. Runtime OperationEnvelope дополняет статический индекс фактическими событиями; OCA связывает эти два потока.

Важно: автоматическая индексация не отправляет данные в ChatGPT сама по себе. ChatGPT получает их по explicit context-pack upload, GitHub connector/repository access или явно подключённому local read-only MCP.

## 13.6 Parallel strategy execution — ресурсная, а не label-based параллельность

Parallelism строить по ResourceSet и immutable state snapshot, не только по strategy_id:
- Solana writable account/pool locks;
- EVM sender nonce lane;
- shared lender reserves/capital;
- shared venue/pool liquidity;
- account/ATA lifecycle;
- provider quota/rate budgets;
- global risk/capital budgets.

Discovery, quote fanout, independent sizing and sender-free simulations can run in parallel. Conflicting mutable resource operations pass through existing conflict scheduler and canonical reservation authorities. No new signer/sender/live authority.

## 13.7 Tool access

Coding agent должен иметь reproducible local tools (Git, current CLI, tests, optional Graphify) и narrow read-only MCP profiles (SQD/Antseer only for research tasks). Не загружать весь 65-tool Antseer catalog в каждый context; не требовать коммерческий jCodeMunch license без approval; не добавлять ClickHouse до benchmark. Tool connection считается доступной только после успешного self-check конкретного агента/клиента.



# 14. Repo Knowledge Graph — обязателен для каждой будущей strategy/code задачи

Новый документ [REPO_KNOWLEDGE_GRAPH_RU.md](REPO_KNOWLEDGE_GRAPH_RU.md) задаёт полный contract индекса:
- все source files + docs + roadmaps + configs + schemas + tests + workflows + packages + CLI/MCP/apps + RPC/data tools;
- StrategyIdea/StrategyVersion → exact symbols/callers/callees → configs → source/provider/venue/flash-capital → tests → runtime episodes/evidence;
- Tool/App inventory с versions, license, owners, permissions, consumers, duplicate/unreferenced candidates;
- provenance каждого edge: STATIC_EXTRACTED / COMPILER_RESOLVED / CANONICAL_REGISTRY / RUNTIME_OBSERVED / DOC_CLAIM / HUMAN_CONFIRMED / LLM_PROPOSED;
- incremental refresh по Git SHA/blob hashes, stale-index rejection, branch isolation;
- T0 repo card ~300–500 tokens, one-line catalogues, T2 task subgraph ~1–2k tokens, exact evidence retrieval by ID.

### 14.1 Tool selection policy

Native Local Intelligence V2 остаётся canonical base. На одном SHA выполнить bake-off:
- CodeGraphContext — code callers/callees/paths, MIT main project, isolated developer tool;
- Graphify — wider Tree-sitter graph and docs/config nodes; current PyPI package `graphifyy`, semantic model pass off;
- SCIP/LSP — precision for only supported language/build paths;
- Aider RepoMap/PageRank — relevance ranking for token budget.
Выбрать максимум один primary external graph backend. Не ставить всё одновременно, не копировать чужие функции без exact license/source attribution, не добавлять runtime dependencies ради developer index.

Serena main app имеет GPL-3.0-or-later; jCodeMunch остаётся license-gated. Проверять транзитивные лицензии, SBOM и security.

### 14.2 Полный execution trigger

[AGENT_W0_START_TRIGGER_RU.md](AGENT_W0_START_TRIGGER_RU.md) теперь запускает весь bootstrap:
1. W0 + W0A — независимые audit/tool-evaluation tracks параллельно;
2. W0B — работающий graph/index, compact catalogs, query facade и context packs;
3. W1–W9 — по dependency graph, параллельно только при disjoint write scopes;
4. incremental refresh + CI, Work Result Receipt и strategy-session pack;
5. tool/app cleanup inventory без автоматического удаления.

**Нельзя остановиться после W0 и вернуть только отчёт/план.** Требуется первая работающая, тестируемая версия; если часть blocked, сделать safe subset и выдать точный blocker. **Нельзя объявлять цель достигнутой без W0B + W10 + W11:** карта кода без реальной записи paper/shadow работы и единого cross-store retrieval — только половина системы.

### 14.3 Новый стратегический чат

Использовать [CHATGPT_NEW_CHAT_STRATEGY_STARTER_RU.md](CHATGPT_NEW_CHAT_STRATEGY_STARTER_RU.md). Перед новой Web3/flashloan гипотезой ChatGPT обязан запросить latest SHA-bound pack, сравнить существующие идеи/символы/источники/tests/outcomes и выдать DUPLICATE / EXTENSION / NOVEL с точными ссылками. Новая сессия не получает локальный индекс автоматически: pack нужно загрузить, открыть через GitHub или read-only MCP.


# 15. Full token efficiency — apply methods, not every application

Detailed execution contract: [TOKEN_EFFICIENCY_PLAYBOOK_RU.md](TOKEN_EFFICIENCY_PLAYBOOK_RU.md).

Mandatory techniques:
- Tree-sitter/native AST signatures and imports for zero-LLM local structure extraction;
- actual compiler/language-server references via SCIP/LSP where supported;
- one persistent graph (CGC OR Graphify OR proven native implementation), not multiple parallel stores;
- query-time relevance/PageRank ranking and strict budget packing;
- lazy 1–3-hop graph traversal rather than injecting full maps;
- scope-aware exact function extraction via Probe or grep-ast;
- Git blob/tree hashes + incremental affected-node refresh;
- stable tool definitions/prompt prefix where the provider exposes prompt caching; no ChatGPT cache guarantee;
- deterministic BM25/lexical + graph search first; embeddings only after measured semantic-recall gap;
- optional Joern CPG for CFG/DFG/taint only when deep data-flow/security questions justify it.

Do not count signature-only compression as complete understanding. The model must retrieve actual function bodies, configs, tests and evidence when logic matters. Do not claim fixed 95–99% compression across all code. Exact output token counts require the target model tokenizer; otherwise label byte estimates.

Preferred speed path: existing Local Intelligence orchestrator + Probe JIT extraction + one selected persistent graph + SCIP where useful + thin Studious-specific strategy/source/operation joins. Repo-specific domain and runtime mapping cannot be solved by downloading a generic code mapper alone.


# 16. Runtime data capture is a separate mandatory deliverable

[REALTIME_OPERATION_DATA_PLANE_RU.md](REALTIME_OPERATION_DATA_PLANE_RU.md) defines how the running bot's decision-relevant data becomes durable evidence:
- strategy decisions/rejections, quote and flash-lender inputs, route/sizing/planning/compiler, simulation, reconciliation and terminal paper/shadow outcomes;
- exact repo/config/strategy/source/observation/candidate/attempt/callsite/trace identities;
- raw payload stored once by AGG-02/evidence owners; operation events in ObservabilityStore; observations and episodes in their existing owners;
- no silent drops, gaps/backpressure and incomplete states; replayable portable exports;
- one read-only query plane over multiple canonical physical stores.

**Important source audit finding:** on the audited main, EventEnvelope and ObservabilityStore exist, but GitHub code search found `make_event()` definition and tests, not a verified production callsite. `make_event()` defaults to test-runtime/test and unknown provenance. `RuntimeDiscoveryCoordinator` returns a bounded report; `native_cpmm_capture.py` documents one-shot capture without subscriptions. Re-verify on the latest main in W0, and do not call this live event capture until an actual runtime vertical writes durable correlated events.

The work package matrix now includes:
- OCA-W10 — instrument the actual supported paper/shadow runtime path and prove durable strategy-to-function event capture;
- OCA-W11 — unify read-only query/export/replay across code, observations, raw market events, operation events, episodes and agent work receipts.

A repo code graph without OCA-W10/W11 is **not** the complete user objective.
