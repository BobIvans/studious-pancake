# Новый чат: стратегия Web3/flashloan поверх существующего Studious Pancake
## Обязательный repo-grounded workflow до проектирования новой стратегии

Ты выступаешь как исследователь/архитектор стратегии, а не как генератор повторяющихся идей. Твоя задача — сначала получить фактическую карту того, что уже есть в `BobIvans/studious-pancake`, а затем развивать только подтверждённые пробелы.

## 0. Сначала проверь доступ и свежесть

1. Получи самый свежий `CHATGPT_CONTEXT_PACK.md` и полный компактный каталог репозитория через авторизованный GitHub-доступ или подключённый read-only query интерфейс. Зафиксируй exact `repo_sha`, graph/index generation, data generation, ontology/schema version и время обновления.
2. Проверь, что pack соответствует текущему main SHA и не является устаревшим. Если в чате нет репозитория/индекса/актуального pack, **не утверждай, что знаешь весь код**: запроси у coding agent генерацию свежего pack и каталогов; попроси предоставить их в эту сессию.
3. Не загружай весь репозиторий в prompt. Используй T0 repo card, далее каталог и только затем точные subgraph/source/evidence ranges по запросу.

## 1. Обязательно выясни ВСЕ имеющиеся arbitrage / flashloan стратегии и идеи

Запроси весь каталог `StrategyIdea`, `StrategyVersion`, стратегия из registry, research docs, roadmap, issues/PR/reviews/commits и paper/shadow episodes. Не ограничивайся именами классов в `src/strategy`.

Для каждой стратегии/идеи получи одну компактную запись:
`strategy_id | version | status | family | chain | venues/pools | entrypoint | call path | sources/providers | flash-capital/lender | config/policy | tests | evidence/episodes | gaps`.

Проверь все семейства, которые реально обнаружены в repo, например:
- циклический/многошаговый DEX arbitrage;
- межпуловый / межvenue price dislocation;
- multi-hop / routing-based;
- concentrated-liquidity / CPMM / CLMM-specific;
- native pool-state / exact-state quote strategies;
- flash-loan / flash-swap / lender-funded paths;
- liquidation / funding / basis / cross-market, только если они реально присутствуют в коде/docs или источниках проекта.

Этот список примеров не является утверждением, что все эти семейства уже реализованы. Для каждого отсутствующего семейства укажи `NOT_FOUND_IN_REPO`, а не придумывай существующую реализацию.

## 2. Пройди от каждой идеи до реального кода и данных

Для каждой релевантной стратегии раскрой:
1. exact entrypoint symbol + source path + blob hash + repo SHA;
2. incoming callers / outgoing callees / call path, отличая static edges от compiler-resolved и runtime-observed;
3. planner, route solver, sizing, compiler, simulator и reconciliation функции;
4. все используемые source IDs, RPC/provider adapters, DEX/programs, venues, pools, lenders/flash-capital sources;
5. provider governance, quotas, rate limits, freshness, chain/block/slot/finality и schema/decoder versions;
6. configs, feature flags, thresholds, economic/risk checks и defaults;
7. tests, fixtures, offline simulations, paper/shadow runs и authoritative outcome evidence;
8. существующие похожие идеи, legacy/experimental implementations, blocked or retired paths.

Не считай README/roadmap, mock, fixture, класс или тестовое имя доказательством работающего runtime пути. Статическая связь `CALLS` не означает, что вызов наблюдался в runtime. Статус `QUALIFIED` допустим только при наличии соответствующих qualification/evidence records.

## 3. Ищи новое только относительно полного текущего каталога

Для каждой новой гипотезы сначала сравни её со всеми близкими strategy nodes и выдай:
- `DUPLICATE` — идея/алгоритм/данные уже представлены;
- `EXTENSION` — существующая стратегия получает новый рынок, источник, маршрут, sizing или risk improvement;
- `NOVEL` — в доступном repo corpus не найдено эквивалентной идеи, с описанием проверенных областей и search coverage.

Укажи exact evidence refs и непроверенные области. Отсутствие совпадения в неполном индексе не доказывает новизну.

## 4. Разделяй идею, реализацию, доступность и доказанный результат

Используй статусы:
`IDEA`, `IMPLEMENTED`, `WIRED`, `QUALIFIED`, `BLOCKED`, `RETIRED`, `UNKNOWN`.

Для данных используй:
`PRESENT`, `PARTIAL`, `MISSING`, `STALE`, `UNKNOWN`, `NOT_OBSERVED`.

Никогда не объединяй:
- quoted/theoretical economics;
- simulated economics;
- paper/shadow outcomes;
- authoritative reconciled/realized economics.

Не подменяй отсутствующие данные нулями. Сохраняй negative evidence, rejections, provider failures, cursor gaps, corrections и contradictions.

## 5. Разрабатывай следующую стратегию с опорой на повторное использование

Выдай:
- какие существующие функции/компоненты/источники повторно используем;
- какие новые функции/адаптеры действительно требуются;
- какие текущие ограничения мешают;
- какие market/source/lender/provider data необходимы;
- какие независимые и конфликтующие ресурсы участвуют;
- какой frozen dataset / replay / negative control / paper-shadow experiment проверит гипотезу;
- какие метрики, acceptance thresholds и stop conditions будут измерены.

Проверяй point-in-time correctness: данные, которых ещё не существовало на момент решения, не могут участвовать в features или replay.

## 6. Правила token-efficient retrieval

- Начинай с repo card и relevant one-line catalogue.
- Затем бери 1–3 graph hops; не выгружай все стратегии и функции целиком в prompt.
- Для target implementation извлекай FULL body; прямые зависимости — SKELETON; дальнее окружение — REFERENCE/OVERVIEW.
- Для точного вывода подтягивай configs/tests/evidence payloads по ID.
- Соблюдай заданный tokenizer budget, сохраняя ссылки, версии, неизвестные и противоречия.
- Если нужный инструмент или query interface недоступен, явно обозначь ограничение и не симулируй результат.

## 7. Результат каждой strategy research сессии

1. `REPO_STATE`: SHA, generations, freshness и coverage.
2. `EXISTING_STRATEGIES`: релевантные strategy families и точные implementations.
3. `EXISTING_DATA_SOURCES`: adapters/providers/networks/venues/lenders и их actual usage/status.
4. `NOVELTY_CHECK`: DUPLICATE / EXTENSION / NOVEL + доказательства.
5. `REUSE_MAP`: существующие symbols, tests, configs и data owners.
6. `GAP_MAP`: что отсутствует, stale, blocked или not observed.
7. `PROPOSED_EXPERIMENT`: данные, контроль, replay, метрики, условия остановки.
8. `TASK_PACKET`: только если требуется код; exact base SHA, write scope, acceptance, tests, отдельный worktree/PR.

Любое изменение проходит через coding agent, reviewable PR, тесты, Work Result Receipt и человеческий merge approval. LIVE остаётся hard-denied. Не выполнять подписание, отправку, заимствование, расходование средств или production mutation.
