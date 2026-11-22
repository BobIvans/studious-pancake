# Strategy / Function Performance Diagnostics — evidence-first specification

**Статус:** нормативное расширение operating-plane design от 2026-11-22.  
**Владелец реализации:** OCA-W20.  
**Зависимости:** OCA-W2, W10, W13, W14, W15, W18.  
**Потребитель:** дополнительная операция `performance_diagnostics` внутри существующего read-only MCP tool `web3_data_trace`; отдельная третья MCP-схема не добавляется.

## 1. Цель и границы

Система должна позволять восстановить не только *какие стратегии и функции существуют*, но и **как конкретная версия стратегии реально работала в каждом поддерживаемом paper/shadow runtime**, на каких стадиях терялись данные/кандидаты/возможности, где росли задержки и ошибки, какие функции или провайдеры связаны с деградацией и какие выводы подтверждены.

Нужен сквозной запрос:

`strategy family/version → operation/episode → lifecycle stage → runtime callsite → exact symbol + repo SHA → inputs/outputs/contracts → provider/observation/capital evidence → metrics/errors → simulation/reconciliation/outcome`.

Это производный read-only аналитический слой. Канонические факты остаются в `src/observability`, AGG-02, MarketObservation/MarketEpisode, provider governance/contracts, strategy registry, flash-capital graph, qualification и paper/shadow owners. Не создавать вторую базу сырых market payloads, логов или PnL.

**Граф всех обнаруженных функций не означает, что все функции исполняются или наблюдаются.** Статическая связь `CALLS` — не доказательство фактического вызова. Для каждого символа отдельно показывать STATIC_ONLY, RUNTIME_OBSERVED, NOT_OBSERVED, PARTIAL, AMBIGUOUS или UNKNOWN. Полнота runtime-coverage измеряется только относительно перечисленных и поддерживаемых runtime routes.

## 2. Что необходимо измерять

Собирать измерения на согласованных lifecycle boundaries и стабильных callsite IDs, а не включать подробный лог в каждую строку кода.

### 2.1 Техническая телеметрия функции и стадии

Там, где реально поддерживается producer, измерять:

- число вызовов и размер наблюдаемой выборки; завершения, ошибки, retry, timeout, cancellation и reason codes;
- wall time и queue/wait time; p50/p95/p99 latency по достаточно большой выборке;
- input/output counts и размер, schema/contract validation errors, missing/invalid/duplicate records;
- freshness, lag, cursor gaps, correction/reorg, source disagreement и observation coverage;
- queue depth, backpressure, append/store latency, drop/loss counters и replay/recovery status;
- stage transition counts: сколько объектов вошло на стадию, прошло её, было отклонено, потеряно или осталось UNKNOWN.

Каждое измерение несёт временной интервал, strategy/version, operation/episode/attempt, stage, stable callsite/symbol ID, repo SHA, config hash/generation, trace/span, provider/source и evidence refs там, где связь доказана. Недоступные поля остаются UNKNOWN; не восстанавливать их по имени функции или соседнему событию.

### 2.2 Экономические и стратегические результаты

Отдельно привязывать к той же operation/episode только подтверждённые canonical значения:

- quote/expected output, simulation output, reconciled outcome;
- gross/net result, fees, gas/priority costs, slippage, borrow fee/interest и repayment;
- expected-versus-realized differences и расхождения quote → simulation → reconciliation;
- rejected/expired/not-profitable/no-capital/no-route результаты с типизированными reason codes.

Соблюдать units, decimals, token identity, chain/deployment, timestamp/block semantics и источник каждого числа. Не смешивать модельные ожидания, simulated значения и reconciled/realized факты. Если авторитетного outcome нет, PnL и attribution должны быть UNKNOWN, а не оценочными числами.

### 2.3 Сегментация и корректное сравнение

Нельзя сравнивать произвольные вызовы функций. Сравнивать совместимые когорты с явным ключом/фильтрами: strategy family/version, repo SHA или совместимая версия кода, config generation, chain, venue/pool, provider, capital route, source mode, market/regime/time window и тип результата.

Отчёт должен показывать cohort definition, количество операций/вызовов, период, coverage и missingness. При малой выборке — LOW_SAMPLE/INSUFFICIENT_EVIDENCE, без рейтинга «плохих функций». Разделять деградацию latency/error/coverage и ухудшение финансового исхода.

## 3. Диагностический результат

Операция `performance_diagnostics` принимает ограниченный временной диапазон, strategy/version refs, operation/episode refs, stage/function/callsite refs, provider/venue/chain/config filters, baseline cohort и token/result budget.

Она возвращает evidence-backed отчёт:

1. **Pipeline health:** входы и выходы по стадиям, gaps, rejection reasons, coverage и runtime availability.
2. **Function/callsite health:** invocation count, success/error/retry rates, latency quantiles, last-seen, sample size, missing telemetry и сравнение с baseline.
3. **Provider/data health:** freshness, gaps, contract/normalization failures, source disagreement, quota/backpressure/replay evidence.
4. **Strategy outcome:** только подтверждённые simulation/reconciliation/paper-shadow results, расходы и expected/realized deltas.
5. **Anomaly candidates:** точные stage/callsite/symbol refs, affected operations, event/evidence refs, baseline delta, sample size, confidence and severity.
6. **Dependency trace:** callers/callees, upstream data/provider evidence and downstream affected stages, all bound to the same repo/config/runtime generation.
7. **Unknowns and next evidence:** missing producers, unsupported parsers, insufficient cohorts, broken joins and deterministic expansion refs.

Каждая находка имеет один из статусов:

- `OBSERVED_ANOMALY` — измеренное отклонение;
- `ASSOCIATED_STAGE` — стадия/функция статистически связана с отклонением;
- `ROOT_CAUSE_HYPOTHESIS` — обоснованная, но не доказанная гипотеза;
- `CAUSALITY_SUPPORTED_BY_CONTROLLED_TEST` — воспроизводимое controlled fault/replay test подтверждает механизм;
- `CAUSALITY_PROVEN` — только при сильном контролируемом доказательстве и явной методике;
- `LOW_SAMPLE`, `INSUFFICIENT_EVIDENCE`, `UNKNOWN`.

**Корреляция не равна причинности.** Медленная функция может быть следствием медленного provider, очереди, RPC или backpressure. Плохой PnL может быть следствием рынка, fees, source freshness, capital constraints или конкуренции. Отчёт обязан показывать альтернативные upstream/downstream объяснения и не называть функцию причиной только потому, что она встречается в trace.

## 4. Верификация

Обязательны:

- deterministic fixtures для каждого event/join/metric shape и проверка единиц/десятичных значений;
- fault-injection/replay cases: stale provider, cursor gap, invalid decimals/schema, duplicate observation, timeout, retry storm, queue saturation, persistence failure, route/quote mismatch, capital unavailable, simulation/reconciliation divergence;
- тест, который находит точный injected failing callsite/stage и affected operations;
- negative tests: отсутствие корреляции не выдаёт root cause; low sample не выдаёт рейтинг; static CALLS не выдаётся за runtime invocation; missing telemetry не трактуется как zero failures;
- end-to-end реальный поддерживаемый offline/paper/shadow vertical с restart/replay; одних unit fixtures недостаточно;
- coverage по всем поддерживаемым strategy/provider/venue/capital routes с WIRED/PARTIAL/NO_RUNTIME_PATH/BLOCKED/UNKNOWN;
- измерение ingest/store lag, p50/p95/p99, drop/loss, query latency и overhead; bounded queues и resource budgets;
- regression/golden corpus: precision/recall anomaly localization, false attribution rate, evidence citation correctness, critical omissions.

Решение о порогах должно быть версионировано и привязано к конфигурации/когорте. Не использовать универсальный порог PnL или latency без соответствующего контекста.

## 5. Безопасность и эксплуатационная политика

- Только read-only диагностика существующих offline/paper/shadow данных.
- Никаких автоматических изменений стратегии, параметров, provider enablement, risk limits, signer, sender, nonce, капиталов или исполнения.
- Никаких LIVE действий, подписания, отправки, заимствования, трат, deployment или production mutation.
- Критические decisions/rejections/gaps/corrections/reconciliation/terminal outcomes не семплируются. Сэмплирование допускается только для шумных non-decision debug/heartbeat событий с отдельными counters и policy version.
- Ошибки durable capture становятся явными INCOMPLETE/DEGRADED событиями и блокируют qualification до replay/reconciliation.
- Не экспортировать secrets, private endpoints или чувствительные payload values; использовать canonical IDs/hashes и redaction.

## 6. Definition of done

Для выбранного реального supported paper/shadow run можно одной read-only диагностикой:

1. открыть strategy/version и exact repo/config generation;
2. проследить каждый наблюдаемый stage и реально вызванные functions/callsites;
3. увидеть invocation/latency/error/retry/data-quality/capture metrics и denominators;
4. связать конкретные отклонения с исходными events, observations, provider/capital evidence и downstream outcomes;
5. отличить observation, association, hypothesis и causal proof;
6. воспроизвести вывод после restart из canonical event/evidence owners;
7. получить полный список uncovered/UNKNOWN paths, а не ложное заявление о полном покрытии.

Full-bot diagnostics claim запрещён, пока каждый поддерживаемый runtime route не получил явный coverage status и доказанный capture path.
