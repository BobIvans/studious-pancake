# Strategic Web3 Infrastructure — assignments для coding agents

**Назначение:** зафиксировать небольшие, проверяемые инфраструктурные задания, которые непосредственно повышают надёжность Web3-разработки и paper/shadow evidence. Это не план установки всех перечисленных технологий и не команда запускать всю инфраструктурную кампанию параллельно с Web3.

**Operating mode:** WEB3_FIRST. Один assignment → один owner → один ограниченный PR. Перед каждым заданием — актуальный main SHA, открытые PR, CI, AGENTS.md, канонические владельцы и точная write-scope проверка. Human approval обязателен для merge. Ни одно задание не добавляет LIVE, signer, submit, borrowing, spending, deployment или production mutation authority.

## 1. Что уже есть и что нельзя дублировать

На проверенном main (SHA `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`) уже есть следующие владельцы:

| Факт / capability | Canonical owner для повторного использования |
|---|---|
| Реестр источников рынка и их ограничения | `src/market/source_catalog.py` |
| Версионированные внешние контракты и hash-pinned artifacts | `src/external_contracts/registry.py`, `src/external_contracts/models.py`, `src/resources/external_contracts.json` |
| Provider entitlement, quotas, admission, cooldown и resource reservations | `src/provider_governance/` |
| Raw payloads, source cursors, gaps и replay journal | `src/agg02/` |
| Нормализованные market observations, generations, watermarks, completeness, corrections/retractions | `src/market/observations.py` |
| Streams и ingestion owners | `src/market/streams.py` и существующие provider adapters |
| Operation events, provenance, redaction, store/export/replay | `src/observability/` |
| Strategy identity, conflict/admission и qualification | существующие `src/strategy/`, `src/qualification_campaign/`, `src/production_qualification.py` |
| Episode projection и intelligence context | `src/intelligence/episode_builder.py`, `src/intelligence/` |

Новый graph/catalogue/lineage слой — производный read model. Он не становится вторым владельцем raw payload, market observation, provider quota, strategy qualification или runtime event.

### Открытые PR, которые сначала надо reconcile

Состояние при обновлении этого handoff: все перечисленные PR открыты и не merged; #676 — Draft. Перед каждым действием агент обязан перепроверить status, checks, diff и изменения main.

| PR | Текущий предмет | Что делать, а не дублировать |
|---|---|---|
| [#672](https://github.com/BobIvans/studious-pancake/pull/672) | Schema version compatibility gate в `src/contracts` | Проверить owner integration, backward/forward fixtures и CI; дальнейшие schema tasks расширяют этот registry, не создают новый. |
| [#673](https://github.com/BobIvans/studious-pancake/pull/673) | DataHub-style read-only metadata catalogue | Использовать как catalogue projection над каноническими владельцами; не запускать DataHub server и не копировать raw rows. |
| [#674](https://github.com/BobIvans/studious-pancake/pull/674) | Debezium CDC adoption decision | Это decision gate, не CDC implementation и не замена DEX/RPC adapters. |
| [#675](https://github.com/BobIvans/studious-pancake/pull/675) | NATS JetStream adoption decision | Это adoption gate, не разрешение заменить canonical journal или внедрить брокер. |
| [#676](https://github.com/BobIvans/studious-pancake/pull/676) | OpenLineage RunEvent projection + Studious facets | Проверить schema/fixture/provenance; это projection, не доказательство наличия реальных production producers и не замена EventEnvelope. |

Открытые PR не считаются принятыми возможностями. Их код нельзя импортировать как merged API, пока агент не проверил актуальное состояние. Не создавать второй PR с тем же файлом/функцией, если корректнее продолжить существующую ветку или дождаться её review.

## 2. Порядок заданий

Задания намеренно разбиты по смыслу. S0 — обязательная координация. S1–S6 — наиболее важная Web3 data/evidence основа. S7–S8 закрывают эксплуатационные и quality gaps. S9 — условные технологии, только при измеренной необходимости.

### WEB3-INFRA-S0 — Canonical owner / active PR reconciliation

**Priority:** P0 · **Mode:** AUDIT_ONLY · **Maps to:** OCA-W0, existing PRs #672–#676.

**Задача агента**
- Обновить main SHA, open PR/branch/check inventory и source tree.
- Пройти реальные producer → adapter → raw journal → observation → strategy decision → simulation/reconciliation → paper/shadow outcome callsites.
- Для каждого capability зафиксировать: IMPLEMENTED_AND_TESTED / EXISTS_AND_VERIFIED / PARTIAL / CONDITIONAL_NOT_REQUIRED / BLOCKED_WITH_EVIDENCE / UNKNOWN.
- Свести #672–#676 с существующими registry/store owners и выявить конфликты write scopes.

**Deliverables**
- owner/callsite matrix с точными путями, symbol IDs и tests;
- PR overlap and dependency matrix;
- отсутствующие поля/переходы с приоритетом по Web3 impact.

**Acceptance**
- Никакая функция не засчитывается как существующая только по README, schema или классу без проверки реального callsite и test.
- Каждый canonical owner указан ровно один раз.
- Нет дублирующего registry/store и нет утверждений, что open PR уже merged.
- Никакие runtime credentials/secret values не попадают в отчёт.

### WEB3-INFRA-S1 — Versioned Provider Adapter + Data Contracts

**Priority:** P0 · **Maps to:** OCA-W13 · **Depends on:** S0.

**Задача агента**
Создать единый versioned contract для каждого внешнего DEX/RPC/market/lending/flash-capital provider, используя существующие owners. Новый adapter должен подключаться через capability contract, а не через `if provider == X` в стратегиях.

**Обязательные поля**
- `provider_id`, `adapter_id`, `adapter_version`;
- chain/network identity, venue, protocol, endpoint/stream (секреты и credential URLs не сохранять);
- поддерживаемые методы/операции, pagination, rate/quota/cadence limits;
- declared и observed source modes: `STREAMING`, `POLL_ONLY`, `ONE_SHOT`, `UNAVAILABLE`;
- `schema_id` / schema version; required fields, units, decimals, nullability и timestamp semantics;
- cursor, watermark, event time, ingest time, recorded time;
- freshness, lag, coverage, gap/reconnect state и rate-limit evidence;
- raw payload ID/reference/hash, normalization version;
- deduplication key, correction/retraction/reorg semantics, backfill и replay support.

**Deliverables**
- adapter/data contract schema и compatibility tests;
- provider capability records с declared-vs-observed разделением;
- один offline vertical slice на существующем adapter, без расширения financial authority.

**Acceptance**
- Новый provider можно зарегистрировать без переписывания strategy business logic.
- Наличие adapter/API документации/HTTP 200 не доказывает capability или data freshness.
- Contract version, schema, source mode, limits, cursor semantics и unsupported methods видны явно.
- Невалидные decimals/units/timestamps/cursors/schema versions отвергаются.
- Provider остаётся disabled, пока его собственные entitlement, source-quality и strategy gates не выполнены.

### WEB3-INFRA-S2 — Provider health, data quality and source disagreement

**Priority:** P0 · **Maps to:** OCA-W13 + OCA-W10 · **Depends on:** S1.

**Задача агента**
Сделать качество источника самостоятельным evidence, а не булевым `healthy`.

**Сущности / поведение**
- `SourceHealthEpisode`: outage, stale, degraded, partial coverage, reconnect, cooldown/rate-limit episode, recovery.
- `DataQualityEvidence`: freshness, lag, coverage, gap intervals, completeness, provenance, sample window, measured time.
- `SourceDisagreement`: независимые conflicting values с source IDs, timestamps, units, state identity и evidence refs.
- `NormalizationRule`: explicit mapping raw → normalized, decimals/units/rounding/timestamp/null semantics и version.
- `EntityIdentity`: stable identity для chain, venue, pool, token, contract, market и provider-specific aliases.

**Acceptance**
- Unknown не превращается в zero; missing coverage не считается 100%.
- Source mode и health имеют observed evidence, time window и freshness.
- Disagreement не решается случайным выбором "последнего" значения; policy даёт explicit ACCEPT / QUARANTINE / UNKNOWN и reason codes.
- Stale, incomplete, rate-limited или contradictory observations не могут незаметно проходить в strategy requirements.
- Повторные health transitions дедуплицируются, outages закрываются только по подтверждённому recovery.

### WEB3-INFRA-S3 — Chain identity, canonicality, finality and reorg-safe corrections

**Priority:** P0 · **Maps to:** OCA-W13 + OCA-W15 · **Depends on:** S1; can proceed alongside S2 with disjoint files.

**Задача агента**
Ввести chain-aware event identity. Не идентифицировать состояние только по адресу контракта или token/pool symbol.

**Обязательная модель**
- network/chain identity, включая genesis/network discriminator;
- block/slot number и block hash;
- transaction hash/signature и transaction index;
- log index для EVM logs, instruction/index или chain-native event index для Solana и соответствующие native coordinates для других семейств;
- program/contract address, deployment/version/code identity и relevant account/state generation;
- canonicality/finality state, observation time и source evidence.

**Acceptance**
- Модель допускает разные chain-native coordinates и не навязывает EVM `log_index` Solana/другим chain.
- Одинаковый address на разных chains/deployments не склеивается.
- Reorg/fork/finality change создаёт явный correction/retraction/replacement event, ссылку на отменённый факт и replay/invalidation requirement.
- История не переписывается незаметно; старое наблюдение остаётся проверяемым.
- Невыясненная canonicality/finality обозначается UNKNOWN и блокирует использование там, где стратегия требует подтверждённого state.

### WEB3-INFRA-S4 — StrategyDataRequirement + CompatibilityEvaluator

**Priority:** P0 · **Maps to:** OCA-W14 · **Depends on:** S1 + S2 + S3 + existing strategy qualification owners.

**Задача агента**
Каждая StrategyVersion описывает требования к данным/инфраструктуре декларативно, не привязываясь к реализации одного provider.

**Контракт содержит**
- required capabilities (например pool state, executable quote, historical replay, block identity, flash capital evidence);
- supported chains/protocols/venues/entity types;
- freshness, minimum coverage, source independence и observation consistency — только значения, выведенные из стратегии/tests/qualification evidence;
- обязательность replay/gap detection/canonicality/finality;
- policies для stale/missing/disagreement/correction/reorg;
- разрешённые research/paper/shadow modes; `live_allowed=false`.

**Результат evaluator**
`COMPATIBLE` / `PARTIAL` / `INCOMPATIBLE` / `UNKNOWN`, точные reason codes, provider/schema/strategy versions и evidence refs.

**Acceptance**
- Adapter presence ≠ strategy compatibility; compatibility ≠ qualification; qualification ≠ live authority.
- Универсальные freshness thresholds не выдумываются.
- Изменение provider/schema/health/normalizer/chain identity обнаруживает затронутые strategy versions.
- Unknown capability или missing evidence не может дать COMPATIBLE/QUALIFIED.
- В evaluator нет provider-specific branching для бизнес-логики стратегии.

### WEB3-INFRA-S5 — Evidence lineage from observation to outcome

**Priority:** P0 · **Maps to:** OCA-W1/W2/W3/W10 and PR #676 · **Depends on:** S0 + canonical event/observation owners; S1–S3 required before claiming full data lineage.

**Задача агента**
Связать доказательствами цепочку:

`raw provider payload → normalized observation → market/operation episode → strategy decision/rejection → quote → sizing → route/planner/compiler → sender-free simulation → reconciliation → paper/shadow outcome`.

**Модель**
- OpenLineage `Run → Job → Dataset` используется как совместимый внешний envelope/projection.
- Studious custom facets несут chain/block identity, strategy/version, source/adapter/schema/normalizer, cursor/watermark, freshness/quality, repo SHA/config generation, correlation/trace/event IDs.
- EventEnvelope остаётся каноническим operation-event owner; AGG-02 остаётся raw payload/cursor owner; MarketObservation — нормализованная data truth.
- Каждое lineage edge имеет provenance type, exact evidence refs, producer/consumer version и explicit confidence.
- `STATIC_POSSIBLE_CALL` не равен `RUNTIME_OBSERVED`; inferred/doc/LLM edges никогда не маскируются под verified.

**Acceptance**
- Нет lineage от одного лишь совпадения имён/полей; inputs/outputs задаются подтверждённым producer/consumer contract.
- Для каждого stage link есть exact IDs/hashes либо explicit MISSING/UNKNOWN.
- Decision/rejection/gap/correction/reconciliation/terminal events не теряются через sampling.
- Projection не копирует raw payloads и не меняет canonical stores.
- Paper/shadow vertical можно реконструировать с прежними code/config/schema/source evidence, а не только по fixture.

### WEB3-INFRA-S6 — Cursor-based backfill, deterministic replay and recovery

**Priority:** P0 · **Maps to:** OCA-W10/W11 + existing AGG-02 replay · **Depends on:** S1 + S3 + S5.

**Задача агента**
Проверить и закрыть полный цикл ingestion recovery: cursor commit, crash, reconnect, gap discovery, backfill, dedup, correction/reorg replay и restored state.

**Deliverables**
- provider-specific cursor/backfill/replay capability matrix;
- deterministic replay receipt с source/schema/normalizer/code versions;
- restart/reconnect/gap-fill and correction test fixtures;
- backup/restore certification for the canonical data owners actually used.

**Acceptance**
- Cursor and payload commit semantics are atomic where current owner guarantees them; otherwise uncertainty is surfaced.
- Replay idempotent; duplicates are detected, not silently applied twice.
- Missing range remains a visible gap until backfilled and verified.
- Reorg/correction causes downstream invalidation and recomputation of affected observations/episodes/strategy qualification where policy requires it.
- Restore occurs to a copy/test namespace first and proves hash/count/identity; never overwrite production state automatically.
- No "exactly once" claim unless formally guaranteed by the actual transport/store path.

### WEB3-INFRA-S7 — Read-only catalogue and operations query facade

**Priority:** P1 · **Maps to:** OCA-W11 + PR #673 + PR #676 · **Depends on:** S1 + S5; S6 for replay queries.

**Задача агента**
Сделать единый bounded read-only query facade поверх canonical owners: provider/source, adapter, schema, quality episode, chain identity, dataset, strategy requirement, lineage, operation episode, replay and evidence refs.

**Acceptance**
- DataHub-style catalogue остаётся projection, не второй metadata DB и не копия payload rows.
- Query reports freshness, coverage, truncation, evidence refs и UNKNOWN gaps.
- Provider listings не запускают network probes и не включают provider.
- Read-only profile не имеет shell/edit/delete/admin/market-write/signing/submission tools.
- DataHub server/hosted ingestion не ставится, пока число owners/teams/integrations не создаёт измеренную необходимость.

### WEB3-INFRA-S8 — Verification, schema evolution, license and resource guardrails

**Priority:** P0 cross-cutting · **Maps to:** OCA-W12/OCA-W18 and PR #672.

**Задача агента**
- Schema evolution: backward/forward fixture compatibility + archived real payload fixtures + consumer migration/replay tests; fixture check прямо маркируется как sampled evidence, не formal schema-subsumption proof.
- Positive/negative tests для invalid schemas, decimal/unit/time semantics, missing cursors, duplicate payloads, source outage, reorg, correction and stale data.
- Always-run critical Web3 safety/invariant/strategy regression tests; affected-test selection никогда не отменяет их.
- Path-level license/SBOM/advisory/secret checks; transitive dependencies and nested license files.
- Resource governor: indexing/analytics не вытесняют source capture, paper/shadow pipeline, DB writer или recovery.
- Receipts содержат base/head SHA, changed contracts, affected adapters/strategies, tests, pass/fail/skip, benchmark and unresolved gaps.

**Acceptance**
- Любое schema/adapter/normalizer change выявляет downstream consumers и требуемую requalification.
- Нет auto-promotion и скрытого downgrade качества.
- Critical suites не могут быть пропущены affected-test selector.
- Unknown license/dependency/secret finding не объявляется разрешённым автоматически.
- Resource pressure приводит к defer/pause low-priority analytics до нарушения критических ingestion/operations budgets.

### WEB3-INFRA-S9 — Conditional infrastructure bake-off (не обязательная установка)

**Priority:** P2 · **Maps to:** OCA-W19 · **Depends on:** S1–S8 and measured bottleneck.

Проверять только по необходимости:

| Кандидат | Заимствуемая роль | Adoption trigger |
|---|---|---|
| OpenLineage / Marquez | Run/Job/Dataset lineage | Нативная projection достигла границы обмена с внешними consumers; не заменяет EventEnvelope/AGG-02. |
| Apicurio Registry | Hosted schema/API registry | Git + CI compatibility gates не справляются с независимыми publishers/consumers и runtime schema distribution. |
| DataHub | Enterprise metadata catalogue/ingestion | Множество teams/owners/derived datasets требуют ownership workflows и ingestion framework; сначала доказать конкретные DEX/RPC connectors. |
| NATS JetStream | Multi-process event delivery/replay | Текущие journals/queues не дают требуемый fanout/backpressure/retention; не является canonical fact store. |
| Debezium | CDC между независимыми databases | Есть конкретные authoritative DB change streams; не используется для замены blockchain RPC/DEX adapters. |
| Temporal | Durable long-running workflows | Текущие workflow receipts/retries/checkpoints не проходят recovery/SLA tests. |
| Glean | Large-scale typed code facts/search | Native SQLite graph не проходит измеренные scale/query/cross-language requirements. |
| LadybugDB | Embedded property graph/Cypher | Существующее graph owner не проходит одинаковые Web3 graph workload benchmarks. |
| Zoekt / Tantivy | Large-scale lexical search | FTS/trigram search подтверждённо является bottleneck. |
| Qdrant / DiskANN / ColBERT | Vector/late-interaction retrieval | Golden set показывает recall bottleneck после exact/lexical/graph retrieval. |
| Salsa / Buck2 DICE / CocoIndex | Incremental computation ideas | Собственный content-addressed invalidation не проходит consistency/latency benchmarks. |
| Firecracker / Wasmtime | Stronger untrusted-code sandbox | Текущая process/container isolation не выполняет threat/resource model. |
| DuckDB / ClickHouse / Iceberg / lakeFS | Analytics and data-lake scale | Measured Parquet volume, concurrency, retention или query SLA оправдывают новую storage owner. |

**Acceptance для любого adoption:** pinned commit/tag, exact license and transitive SBOM, same-workload benchmark, operating cost, security/network surface, migration/rollback plan, owner, tested failure/recovery behavior. Zero adoption — корректный результат.

## 3. Исполнительная последовательность и параллелизм

1. S0 сначала — owners, актуальные PR и test/CI baseline.
2. S1 — provider/data contracts.
3. S2 и S3 могут идти параллельно только при disjoint write scopes: health/quality и chain-native identity/reorg.
4. S4 — strategy compatibility после S1–S3.
5. S5 — реальные lineage joins; OpenLineage projection не засчитывается как production capture до доказанных producer callsites.
6. S6 — replay/backfill/recovery после cursor, chain identity и event links.
7. S7 — catalogue/query projection после появления реальных links.
8. S8 — CI/quality/resource gates сопровождают каждый implementation PR; dedicated הרחение выполняется по конкретным gaps.
9. S9 — только при измеренном bottleneck.

Не создавать PR "универсальная платформа". Каждый assignment — узкий PR с одним owner, чёткими изменёнными путями, тестами, replay/receipt и незакрытыми UNKNOWN.

## 4. Метрики готовности

Не сводить их к одному score:

- Provider: freshness/lag, coverage, gap duration, reconnect/recovery, rate-limit evidence, observed mode.
- Blockchain identity: chain/deployment collision rate, canonicality unknowns, reorg correction propagation.
- Contracts: schema compatibility findings, consumer coverage, normalization version drift.
- Strategy compatibility: correct COMPATIBLE/PARTIAL/INCOMPATIBLE/UNKNOWN classification and evidence coverage.
- Lineage: stage link coverage, missing IDs, provenance precision, runtime-observed vs static edge confusion.
- Replay: cursor resume, duplicate detection, backfill completeness, replay hash consistency, backup restore proof.
- Operations: p50/p95/p99 ingestion-to-store latency, queue depth, dropped critical events, CPU/RAM/IO/storage contention.
- Agent safety: write-scope violation, secret leakage, unapproved tools, skipped mandatory tests.

## 5. Непереговорные инварианты

- No new provider is enabled by registration, catalogue entry, schema pass, lineage projection or agent suggestion.
- No live execution, signing, submission, borrowing, spending, deployment or production mutation is introduced.
- Chain finality/canonicality remains explicit; reorgs/corrections never rewrite evidence silently.
- Missing, stale, incomplete, contradictory and unverified data remain distinguishable.
- Economic eligibility, data availability, flash-capital availability, simulation, paper qualification and live authority remain separate.
- Source contracts cannot invent universal numeric thresholds; each StrategyDataRequirement uses its strategy-specific qualification/tests.
- Intelligence, catalogue and MCP are read-only projections over canonical owners.
- Token/context compression cannot remove identifiers, decimal/unit semantics, evidence refs, risk constraints or code needed to validate a Web3 change.

## 6. Relationship to A–H and OCA-W12–W19

A–H in `AGENT_W0_START_TRIGGER_RU.md` remain the general repository/agent infrastructure backlog. This Web3 assignment set makes the domain-critical foundations explicit; it does not activate all A–H.

Crosswalk:
- S0 → OCA-W0.
- S1/S2/S3 → OCA-W13 + provider/source owners.
- S4 → OCA-W14 + existing strategy/qualification owners.
- S5 → OCA-W1/W2/W3/W10 + PR #676 projection.
- S6 → OCA-W10/W11 + AGG-02 and Observability replay.
- S7 → OCA-W11 + PR #673 projection.
- S8 → OCA-W12/W18 + PR #672 schema gate.
- S9 → OCA-W19 conditional bake-off.
