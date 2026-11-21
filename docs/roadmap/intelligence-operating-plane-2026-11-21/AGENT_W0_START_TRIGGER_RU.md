# Coding Agent Start Trigger — OCA W0
## Скопировать этот документ в coding agent как стартовое задание

Ты работаешь в репозитории BobIvans/studious-pancake. Твоя задача сейчас — только W0: read-only audit текущих владельцев, event correlation, code intelligence и реального состояния CLI/runtime. Не реализуй W1-W9.

## 1. Подготовка

1. Клонируй или обнови BobIvans/studious-pancake.
2. Прочитай этот handoff из ветки codex/intelligence-operating-plane-design-2026-11-21:
   - docs/roadmap/intelligence-operating-plane-2026-11-21/CODEX_START_HERE_RU.md
   - docs/roadmap/intelligence-operating-plane-2026-11-21/OPERATIONS_CONTEXT_AGGREGATOR_RU.md
   - docs/roadmap/intelligence-operating-plane-2026-11-21/CHATGPT_CODING_AGENT_CONTEXT_WORKFLOW_RU.md
   - docs/roadmap/intelligence-operating-plane-2026-11-21/TOOL_ACCESS_PROFILES_RU.md
   - docs/roadmap/intelligence-operating-plane-2026-11-21/WORK_PACKAGE_MATRIX.json
3. Сначала проверь актуальные origin/main SHA, open PRs, CI/checks, branches и ownership. Не доверяй design baseline как current main автоматически.
4. Запиши exact base SHA, OS, Python version, worktree status и tool versions.
5. Создай отдельную audit branch/worktree. Не работай в чужой active worktree.

## 2. Ограничения

- Audit only. Не меняй production/runtime code.
- Не добавляй dependency, database, index backend, queue, scheduler, signer, sender, live mode или provider enablement.
- Не добавляй новые raw market/observability stores.
- Не удаляй/перепаковывай event evidence.
- Не запускай network RPC/transactions, signing, submission, borrowing, account creation или spending.
- Не запускай массовую переиндексацию, пока не измерены её ресурсы и output location.
- Не считай docs, fixtures, class names или тестовые mocks доказательством supported runtime.
- Все неизвестные значения маркируй UNKNOWN/NOT_OBSERVED, не заменяй нулём.
- Human approval требуется для любых будущих implementation PR merges.

## 3. Обязательные зоны аудита

### A. Operational event stream

Проверить путь от producer до persisted/exported/replayed row:
- src/observability/events.py;
- src/observability/store.py;
- src/observability/authoritative_store_pr195.py;
- src/observability/replay.py;
- src/observability/export.py и archive modules;
- src/observability/cross_plane_pr196.py;
- src/operations/operator_readiness.py;
- event producers/tests across src/ and tests/.

Для каждого поля EventEnvelope выяснить:
- кто его заполняет;
- является ли значение real или default/placeholder;
- где persist/export/replay происходит;
- какая доля event streams его реально содержит;
- есть ли exact repo SHA, strategy ID/version, config hash, observation refs, chain identity, provider/venue, attempt and terminal evidence.

Не предполагай, что наличие field в dataclass означает полную заполненность в runtime.

### B. Market data and episodes

Проверить:
- src/agg02/storage.py and contracts.py;
- src/market/observations.py and streams.py;
- src/market_data_evolution/contracts.py;
- src/strategy/market_graph_ingest.py;
- src/intelligence/episode_builder.py;
- evidence refs/pins, cursor/gap/watermark/reconnect/correction/retraction;
- current production_qualification and provider_utility reports.

Составить таблицу какие IDs и evidence связывают raw market event → observation → candidate → decision → simulation → reconciliation → paper outcome.

### C. Strategies, providers and resource conflicts

Проверить:
- src/strategy/registry.py, strategy_contract.py, strategies.py;
- src/strategy/opportunity_identity.py;
- src/strategy/conflict_scheduler.py;
- src/strategy/shadow_workers.py and shadow_portfolio.py;
- src/economics/flash_capital_graph/;
- src/market/source_catalog.py, src/resources/market_source_catalog.json;
- QPR/DIN/source governance and strategy inventory docs;
- provider/venue/admission state and capability manifest.

Разделить:
- research catalogue item;
- source discovered;
- provider adapter implemented;
- provider wired;
- exact-state read proven;
- quote/build/simulation/paper qualified;
- blocked/unknown.

Для concurrency определить реальные ResourceSet owners и где есть duplicate strategy/route/pool risk. Не делать новый scheduler.

### D. Local Intelligence V2

Проверить весь src/intelligence module и:
- docs/strategy/local-intelligence-v2/MASTER_CONTEXT_RU.md;
- OPERATIONS.md;
- FUNCTION_BACKLOG.json;
- PR_ROADMAP_RU.md;
- CLI_AND_REPORTS_RU.md;
- CODEX_LOCAL_INTELLIGENCE_V2_START_HERE.md;
- CODEX_STORAGE_PRESSURE_START_HERE.md.

Запустить current documented CLI help/status/scan/export/benchmark/storage/report flows в безопасном local fixture/temporary output. Не выполнять destructive prune. Установить:
- какие функции реально работают;
- какие частично wired;
- что имеет только docs/backlog;
- exact parser language coverage;
- сколько source symbols/edges and coverage gaps;
- index refresh/pack sizes and time;
- какие reports доступны без LLM.

### E. Tool access and token benchmark

Не устанавливать платные или удалённые tools без необходимости. W0 должен:
- выяснить текущую наличность Git/uv/Python/Graphify/other CLI tools;
- определить есть ли existing MCP config and which client supports it;
- выяснить какие data/query tools реально доступны coding agent;
- подготовить proposed narrow profile, не подключая его без approval;
- разработать минимум 30 golden questions для дальнейшего token/retrieval benchmark;
- не использовать jCodeMunch для commercial workflow без paid-license decision;
- не включать all Antseer tools or unbounded SQD queries.

## 4. Deliverables

Сохранить только audit artifacts в:
docs/roadmap/intelligence-operating-plane-2026-11-21/audit/

Обязательные файлы:
1. AUDIT_CURRENT_OWNERS_RU.md
2. INTEGRATION_MATRIX.json
3. EVENT_CORRELATION_MATRIX.json
4. CLI_AND_TEST_BASELINE.json
5. SOURCE_AND_STRATEGY_COVERAGE.json
6. PARALLEL_RESOURCE_OWNER_MAP.json
7. TOOL_ACCESS_AND_RETRIEVAL_BASELINE_RU.md
8. GAP_PRIORITY_RU.md
9. WORK_RESULT.json

Каждый report фиксирует:
- exact main base SHA and head SHA;
- checked paths and source hashes;
- commands run and platform;
- pass/fail/skip counts;
- tests skipped and why;
- artifacts and SHA-256;
- UNKNOWN, NOT_OBSERVED and BLOCKED separately;
- duplicate owner risks and overlaps;
- smallest additive change recommendations.

## 5. Required answers

W0 не завершён, пока не ответит:
1. Какие operational EventEnvelope поля реально заполнены в supported paper/shadow path?
2. Есть ли полный event → strategy → source observation → code commit → function → test → episode correlation?
3. Какие stages имеют stable reason codes, IDs and evidence refs?
4. Какие producers имеют стабильные code callsites и какие нет?
5. Какие current indexes, labels, registries and reports уже работают?
6. Какие языки/artifact formats не покрыты?
7. Что уже есть для parallel candidate/resource scheduling и какие conflicts остаются невидимыми?
8. Какие tools реально подключены, какие требуют установки/лицензии/permissions?
9. Какой bounded context pack можно сформировать прямо сейчас без новых dependencies?
10. Какова минимальная sequence W1-W9, учитывающая ownership/dependencies and actual gaps?

## 6. Acceptance и остановка

- W0 должен быть reviewable и воспроизводимым.
- No runtime code changes.
- No duplicate database/registry/scheduler/authority.
- No unsupported live or profitability claims.
- Матрицы должны быть проверяемыми скриптом/fixture, где возможно.
- Любой вывод о capability подкреплён actual source + test/runtime evidence.
- После W0 остановиться и подготовить recommendations. Не переходить к W1 автоматически.

Цель W0 — не просто описать репозиторий, а найти точные недостающие связи, чтобы следующий implementation PR добавлял только те блоки, которые действительно отсутствуют.
