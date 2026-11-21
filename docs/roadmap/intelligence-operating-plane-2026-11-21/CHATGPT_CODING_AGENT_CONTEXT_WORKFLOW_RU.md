# Рабочий процесс ChatGPT + coding agents для Studious Pancake
## MVP без автономных AI agents: task packs, Git worktrees, автоиндексация и обмен контекстом

**Целевая стадия:** человек формирует стратегическую задачу с ChatGPT; coding agent клонирует GitHub repo, получает задание/pack, изменяет код в изолированной ветке, запускает tests и возвращает receipt; ChatGPT анализирует изменения и следующий шаг. Автономный agent swarm не требуется.

---

# 1. Принцип MVP

Нужны пять автоматически поддерживаемых артефактов:

1. **Repository Intelligence Index** — карта кода, файлов, символов, зависимостей, configs, tests, owners и coverage.
2. **Operation Intelligence Index** — projection runtime events, market observations, candidates, attempts, episodes и outcomes.
3. **Task/Worktree Ledger** — какие coding agents над чем работают, с каким base SHA, какие файлы владеют, какие dependencies и результаты.
4. **Context Pack** — точный bounded пакет для конкретного запроса ChatGPT или coding agent.
5. **Work Result Receipt** — exact commits, изменённые файлы, tests, evidence, blockers и suggested next task.

Все артефакты машиночитаемые, версионируемые и привязаны к Git SHA. Индексы и runtime data не хранятся в Git как большие бинарные blobs.

## 1.1 Роли

| Участник | Ответственность | Не делает |
|---|---|---|
| Человек/оператор | Утверждает цель, риск, приоритет, PR merge и operational approvals | Не обязан вручную искать каждую функцию или читать все logs |
| ChatGPT | Анализирует packs, исследует рынки/протоколы, проектирует стратегии, составляет задания, сравнивает отчёты | Не имеет скрытого права менять код, live risk или совершать финансовые действия |
| Coding agent | Клонирует repo, выполняет одно ограниченное задание в worktree, меняет код/tests, возвращает receipt | Не меняет чужие owners и execution authority |
| Repo automation | Индексирует commits, обновляет manifests/graphs/reports, проверяет receipts | Не вызывает LLM и не принимает финансовые решения |
| Runtime bot | Публикует structured operation events и source evidence в existing owners | Не удаляет evidence по совету LLM |

---

# 2. Полный цикл разработки

~~~text
HUMAN + CHATGPT STRATEGY SESSION
 goal / constraints / hypothesis / acceptance
             |
             v
REPO CONTEXT REQUEST
 exact main SHA + relevant code + tests + source/strategy graph
             |
             v
TASK PACK
 TASK_PACKET.json + CONTEXT_PACK + evidence refs
             |
             v
CODING AGENT CLONES GITHUB
 fetch latest main -> verify SHA -> worktree/branch
             |
             v
IMPLEMENT ONE TASK
 owned files only; code/tests/config/docs
             |
             v
AUTOMATIC REPO INDEX UPDATE
 incremental AST/graph/labels/manifest (zero LLM)
             |
             v
TEST + WORK RESULT RECEIPT
 WORK_RESULT.json + test counts + evidence + blockers
             |
             v
CHATGPT REVIEW
 compare base/head packs, inspect diff, tests, impact
             |
             v
HUMAN REVIEW / MERGE
 update main, CI, task board, rebuild fresh context
             |
             v
NEXT TASK PACK
 fresh SHA + fresh context + next dependency-ready work
~~~

Один агент — одна задача — одна ветка/worktree — один reviewable PR. Независимые задачи выполняются параллельно; общие владельцы файлов изменяются последовательно.

---

# 3. Как новый код автоматически проходит через Index и Label Store без LLM

**Да, это возможно и должно быть default pipeline.** Но это работает только если явно подключить Git hooks/CI/CLI. Простое наличие Graphify/Mimir не создаёт автоматический цикл.

## 3.1 Детерминированно, без LLM, можно извлекать

- Git commit/branch/parent SHA;
- файлы, extensions, sizes, hashes, renames/deletions;
- language/parser coverage;
- Python AST, imports, class/function/method definitions, signatures, byte ranges;
- call/import/dependency edges, которые parser доказывает;
- SCC/logical groups;
- configs, JSON/YAML keys, schemas, dependency pins, workflows;
- path-based ownership and test heuristics;
- strategy/provider/source IDs из canonical registries/manifests;
- stable event/reason codes;
- runtime event IDs, trace IDs, attempt IDs, operation IDs and evidence refs;
- deterministic relations из exact source/manifests/event fields;
- changed files, affected dependents and query-specific context packs.

API key для LLM не нужен.

## 3.2 Нельзя надёжно вывести только из статического индекса

Требуют runtime evidence или явно записанной metadata:
- dynamic imports/plugins;
- actual runtime call paths and execution frequency;
- provider request/results and market state;
- exact transaction/quote/route outcome;
- event-to-function mapping when callsite ID is absent/ambiguous;
- strategy capability if only documented but not wired;
- actual PnL/finality without reconciliation evidence.

Требуют LLM или human semantic review:
- intent незнакомой функции, если он не encoded;
- grouping unfamiliar functions into a new strategy;
- interpreting external research/conflicting docs;
- proposing new semantic labels.

Такие suggestions должны храниться как PROPOSED, не VERIFIED.

## 3.3 Автоматизация в трёх режимах

### A. Local command

После pull/commit/branch switch агент запускает deterministic repo index update. Локальный index лежит вне source tree, привязан к exact SHA и incremental file hashes.

### B. Git hooks

Post-commit/post-checkout hook обновляет локальную projection или ставит её на debounce refresh. Hook — convenience; его можно пропустить, поэтому это не единственная гарантия.

Graphify поддерживает commit hooks/incremental update и может быть optional sidecar. Не запускать полный extraction при каждом file save. Использовать debounce/batch; полный scan — initial bootstrap или scheduled reconciliation.

### C. GitHub Actions / CI

На push/PR:
1. checkout exact commit SHA;
2. restore cache by content hash/version;
3. scan changed files and dependencies;
4. update deterministic manifests/index;
5. run index invariants and coverage checks;
6. publish compact index/report as CI artifact;
7. fail/warn if index is stale or parser coverage regressed.

CI не требует LLM auth. Не отправлять proprietary source/docs внешнему semantic indexer без явной policy.

## 3.4 Как обновляется Label Store

Label Store — versioned taxonomy + derived typed relation projection, не свободный список tags.

Источники:
- strategy registry/manifests → strategy labels;
- source catalog/provider governance → source/provider labels;
- capabilities/qualification receipts → capability status;
- AST/static graph → code/dependency labels;
- EventEnvelope → operation stage/outcome/reason;
- MarketObservation/MarketEpisode → source/data quality and episode labels;
- task/PR manifests → work ownership/status.

Пример labels:
- STRATEGY:STRAT_X;
- SOURCE:SQD_PORTAL;
- PROVIDER:PROVIDER_X;
- STAGE:SIMULATION;
- OUTCOME:REJECTED;
- REASON:STALE_QUOTE;
- CAPABILITY:BLOCKED;
- EVIDENCE:REPLAY_VERIFIED.

Каждая метка имеет namespace, value, schema version, owner, source ref и provenance. Если код только похож на strategy, но нет canonical manifest/runtime proof, сохранять POSSIBLE/PROPOSED, не confirmed strategy.

## 3.5 Автоматическая связь code ↔ runtime

1. Static scanner строит Symbol Index на точный commit.
2. High-value event producers получают stable logsite_id / statement_id.
3. EventEnvelope сохраняет trace/opportunity/attempt/plan/tx/provider/venue IDs, producer code version и config checksum.
4. OCA присоединяет logsite_id + repo SHA к Symbol Index.
5. Episode builder соединяет observations, decisions, simulation, reconciliation и paper outcome.
6. Projection обновляется автоматически.
7. По запросу строится context pack.

Если event не имеет code mapping, сохранять UNKNOWN/AMBIGUOUS и показывать gap. Не угадывать по времени или тексту сообщения.

---

# 4. Как ChatGPT получает данные

Есть три рабочих способа.

## 4.1 GitHub repo link

Coding agent клонирует GitHub repo и использует локальные pinned indexes. ChatGPT может работать с GitHub через подключённый repository connector/integration, если он включён. Для большого repo ChatGPT должен запросить конкретный context pack, а не читать всё дерево.

Repo link сам по себе не даёт доступа к локальным runtime DB, WAL, Parquet, RPC credentials или workstation state.

## 4.2 ZIP + evidence/context bundle

Для передачи в ChatGPT:
- repo ZIP — нужный source snapshot;
- context pack — минимальные файлы и symbol slices;
- operation evidence bundle — timeline, selected event/observation JSONL, Parquet manifests, episode receipts, report;
- manifest — exact repo SHA, hashes, schema versions and coverage.

Чаще лучше загрузить pack, а затем точные файлы по refs. ZIP без runtime evidence не показывает, что бот реально сделал. Runtime bundle без repo SHA не доказывает, какой код исполнил операцию.

## 4.3 Local read-only MCP (позже)

Coding agent может настроить local stdio MCP, который читает index и reports. ChatGPT сможет использовать его только если текущий клиент/среда поддерживает и явно подключила этот MCP. Не предполагать скрытый доступ к компьютеру.

Не создавать remote MCP endpoint без auth, scopes, audit trail, read-only enforcement и явного setup.

Рекомендуется 6–8 узких composite tools вместо десятков низкоуровневых:
- repo_context(query, budget);
- strategy_explain(strategy_id);
- source_lineage(source_id);
- operation_trace(opportunity_or_attempt_id);
- episode_compare(experiment_a, experiment_b);
- code_impact(symbol_or_path);
- task_pack(task_id);
- index_status().

Каждый tool возвращает bounded structured data + evidence refs + coverage gaps, а не raw corpus.

---

# 5. Task Packet — что ChatGPT передаёт coding agent

Каждая задача хранится в repo под canonical roadmap/task owner. Пример обязательных полей:

~~~json
{
  "schema": "studious.coding-task.v1",
  "task_id": "OCA-W3-001",
  "title": "Map critical operational events to stable code callsites",
  "goal": "Add deterministic mapping for the candidate-to-reconciliation vertical",
  "priority": "P1",
  "base": {
    "repository": "BobIvans/studious-pancake",
    "branch": "main",
    "commit_sha": "exact-base-sha"
  },
  "scope": {
    "read_paths": ["src/observability", "src/strategy", "tests"],
    "write_paths": ["declared exclusive file set"],
    "forbidden_paths": ["canonical owners not assigned to this task"]
  },
  "owner": {
    "agent_id": "coding-agent-name",
    "worktree": "worktrees/OCA-W3-001"
  },
  "dependencies": ["OCA-W0", "OCA-W1"],
  "context_pack": {
    "path": "artifacts/context/OCA-W3-001",
    "manifest_sha256": "exact-manifest-hash",
    "max_bytes": 64000
  },
  "acceptance": [
    "stable ID survives line shifts",
    "ambiguous mapping is UNKNOWN",
    "exact repo SHA is required",
    "no LLM in runtime correlation path"
  ],
  "tests": ["exact commands"],
  "safety": {
    "read_only_market": true,
    "live_mutation_allowed": false,
    "signing_allowed": false,
    "submission_allowed": false
  }
}
~~~

Scope конкретный. Нельзя назначать двум worktrees один owner file одновременно.

---

# 6. Work Result Receipt — что coding agent возвращает

Текстовый summary без exact SHA/test receipts недостаточен.

~~~json
{
  "schema": "studious.coding-work-result.v1",
  "task_id": "OCA-W3-001",
  "repository": "BobIvans/studious-pancake",
  "base_sha": "exact-base-sha",
  "head_sha": "exact-head-sha",
  "branch": "agent/OCA-W3-001",
  "worktree": "worktrees/OCA-W3-001",
  "status": "IMPLEMENTED_UNQUALIFIED | BLOCKED | NO_CHANGE",
  "changed_files": [
    {
      "path": "src/example.py",
      "old_sha256": "hash",
      "new_sha256": "hash",
      "owner": "task-id"
    }
  ],
  "tests": [
    {
      "command": "exact command",
      "passed": 0,
      "failed": 0,
      "skipped": 0,
      "platform": "OS/Python",
      "artifact": "test output path"
    }
  ],
  "evidence": [
    {
      "kind": "schema/report/replay/benchmark",
      "path": "artifact path",
      "sha256": "hash"
    }
  ],
  "index": {
    "indexed_commit_sha": "exact-sha",
    "coverage_gaps": [],
    "stale": false
  },
  "blockers": [],
  "overlap_check": {
    "conflicting_owners": [],
    "shared_owner_changes": []
  },
  "next_task_candidates": []
}
~~~

Разделять статусы:
- IMPLEMENTED — код существует;
- WIRED — достижим из поддерживаемого composition/runtime;
- QUALIFIED — acceptance evidence действительно пройден;
- BLOCKED — известна конкретная причина;
- UNKNOWN — evidence не хватает.

---

# 7. Параллельная разработка без autonomous orchestrator

## 7.1 Что запускать параллельно

Независимые workstreams:
- source/provider research and source pinning;
- разные chain/venue adapters;
- strategy research and replay;
- static indexing and coverage;
- tests/fixture design;
- retrospective reports and data analysis;
- context-pack/CLI components после freeze interfaces.

Сериализовать:
- strategy registry schema;
- EventEnvelope/schema migrations;
- central source/provider registry;
- AGG-02 storage owners;
- runtime composition root;
- resource/capital/lifecycle authority;
- shared config/package manifest.

## 7.2 Git worktree protocol

Перед запуском:
1. fetch latest main;
2. record base SHA;
3. inspect open PRs and CI;
4. allocate unique task_id;
5. declare read/write paths and owner;
6. create worktree/branch from exact SHA;
7. run baseline tests;
8. no writes outside assigned scope.

После работы:
1. run targeted tests and repo verification;
2. generate Work Result Receipt;
3. refresh index on head SHA;
4. compare graph and changed symbols;
5. open one focused PR;
6. require human review/approval;
7. update canonical task board and rebuild context for next task.

Без force-push в shared worker branch, без overlapping owner edits и без merge unqualified implementation.

## 7.3 Worktree collision matrix

Coordinator maintains:
- task_id;
- branch/worktree;
- agent;
- base/head SHA;
- exclusive write owner paths;
- shared interfaces touched;
- dependency tasks;
- status;
- PR number and CI status;
- tests/evidence receipt;
- stale/expired state.

Existing master roadmap/parallel PR/status files and owner maps — начальная система учёта. Не создавать вторую task database, если W0 не докажет, что текущая не покрывает worktree ownership.

---

# 8. Tool installation and MCP access policy

Coding agent может клонировать repo и ставить deterministic tooling как developer extras. Не vendoring third-party tool source и generated index blobs в trading package без license/package review.

Рекомендуемая модель:
- repo хранит pinned tool manifest/config, wrappers, parsers/adapters, fixtures и benchmarks;
- developer environment ставит внешние CLI tools exact pinned versions;
- CI cache binaries by version/checksum;
- indexes/artifacts лежат вне repo или в CI artifact storage;
- third-party MCPs конфигурируются в agent/client profile, не включаются бездумно каждому worker;
- credentials остаются в OS secret store/environment injection, никогда в task packets или packs.

Profiles:
- CODE: Graphify optional + native repo indexer + local CLI;
- OPERATIONS: local OCA query tools, no external writes;
- CHAIN RESEARCH: SQD Portal read-only, bounded pagination;
- MARKET RESEARCH: Antseer subset only where useful;
- CODING AGENT: task-scoped local read-only packs, no production secrets;
- HUMAN OPERATOR: health/status/report/approval.

Для jCodeMunch коммерческую лицензию нужно согласовать до использования в revenue-supporting workflow. Для Graphify сначала запускать code-only/offline mode; semantic docs extraction требует явно выбранного LLM backend и data-residency approval.

---

# 9. MVP milestones для текущей стадии

## MVP-A — полезен без real AI agents

Доставить:
- deterministic repository index and task packs;
- existing runtime event/market evidence joined by existing IDs;
- strategy/source/provider catalog view;
- Git worktree ownership protocol;
- work result receipts;
- CLI-generated context and evidence bundle;
- manual ChatGPT upload / GitHub retrieval path;
- no external LLM required by indexing.

Это уже улучшит процесс: ChatGPT получает доказательства; coding agents — небольшие точные задания; parallel development становится управляемым.

## MVP-B — operational intelligence для paper/shadow

Добавить:
- end-to-end operation timeline;
- stable callsite correlation;
- strategy/episode retrospective;
- provider utility and resource conflict reports;
- source gaps/freshness/reconciliation truth;
- bounded incident context pack.

Это делает bot management и log/trade analysis практичными без autonomous agents.

## MVP-C — подготовка runtime operations

Только после отдельно одобренного execution mode:
- chain observation adapters and external finality/reconciliation;
- approved signer/submission evidence ingestion;
- account/nonce/resource lock and execution admission;
- read-only operations MCP and alerting.

Это не разрешает live mode. Existing security/release governance остаётся обязательным.

## MVP-D — optional autonomous agent orchestration

Отложить, пока human+coding-agent process не станет bottleneck. Только потом оценивать persistent coordinator, task dispatch, shared agent memory и policy-bounded tool routing.

Не строить autonomous agent runtime до того, как Task Packet, Work Result Receipt, owner graph и context pack станут надёжными.

---

# 10. Acceptance questions

Из одного pack ChatGPT должен иметь возможность:
1. перечислить стратегии и различить implemented/wired/qualified/blocked/unknown;
2. показать exact functions, configs, provider sources, venues, flash-capital dependencies и tests;
3. восстановить одну operation от source observation до terminal paper/reconciliation result;
4. показать все quotes/rejected alternatives и обосновать выбранный route;
5. определить конфликт двух стратегий по pool/account/reserve/nonce/quota;
6. найти точную функцию/callsite, выпустившую critical event;
7. сравнить стратегии на одинаковых frozen episodes без lookahead leakage;
8. назвать то, что не observed/indexed/reconciled;
9. построить task packet с exact base SHA, write scope, dependencies, tests и evidence;
10. проверить coding agent receipt и определить, какие files/strategies/tests изменились;
11. создать compact ZIP/Markdown/JSON evidence bundle для ChatGPT;
12. детерминированно пересобрать index/pack из того же SHA и query parameters.

Если вопрос неразрешим, pack сообщает, какой owner/field/source отсутствует. Не подменять gap LLM догадкой.

---

# 11. Required first work

Начать с W0 audit из CODEX_START_HERE_RU.md. Конкретно:
- inspect EventEnvelope producers and full path into ObservabilityStore;
- выяснить, что сейчас связывает events со strategy, source observations, config и code version;
- проверить repo scan/export/benchmark и storage reports;
- проверить текущие task ownership/worktree/PR queue;
- выяснить, может ли current CLI построить единый strategy/operation context pack;
- создать gap matrix с exact files, tests и current SHA;
- предложить самый маленький MVP-A implementation.

Не строить autonomous agent runtime, новую event database или новую trading authority в первой работе.


---

# 12. Универсальный task-context интерфейс для любой задачи

После подключения repo-intel MCP используй `task_context` как стандартную первую операцию для **любой** задачи по репозиторию — не только Web3/flashloan.

Пример вызова:
```text
task_context(
  task="<моя задача естественным языком>",
  repo_ref="main",
  depth="adaptive",
  dimensions="auto",
  budget_tokens=<доступный контекстный бюджет>
)
```

Сначала проверь в ответе requested SHA, indexed SHA, graph generation, freshness, coverage, confidence, included/omitted refs и token count. Работай только с актуальным snapshot либо явно помечай fallback.

Когда первичного пакета недостаточно:
```text
expand_context(
  refs=["stable-symbol-or-evidence-id"],
  dimensions=["source","callers","callees","configs","tests"],
  depth="full",
  repo_sha="<тот же SHA>"
)
```

Пользователь не обязан заранее знать, какие файлы нужно открыть. Router сам выбирает dimensions по задаче; точный исходный код, тесты, контракты и evidence загружаются по стабильным IDs. Одна реализация query backend используется из CLI, MCP и portable pack export.

**Постоянная инструкция для ChatGPT:**

> Для любой задачи по BobIvans/studious-pancake сначала используй подключённый repo-intel MCP через task_context и актуальный SHA-bound knowledge graph. Получай минимальный достаточный контекст, проверяй свежесть индекса, затем раскрывай точные функции, зависимости, конфиги, providers, тесты и evidence через expand_context по мере необходимости. Экономь токены progressive disclosure и дедупликацией, но не сжимай критическую логику или доказательства. Указывай SHA, source refs, UNKNOWN и omissions. Если MCP отсутствует или индекс устарел, используй разрешённый GitHub/source fallback и честно отметь ограничение.

Если repo-intel MCP ещё не реализован/не подключён в текущем ChatGPT-сеансе, эта команда является желаемым workflow, а не доказательством фактического доступа.
