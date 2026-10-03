# Стоимость, throughput и честные метрики масштаба

Система растёт только если дополнительные рынки/workers увеличивают полезные своевременные результаты быстрее, чем расходы и ошибки. Число рассмотренных routes, GB и RPC requests не является конечным KPI.

## Пример стоимости данных в объёмах

Это арифметические сценарии, не замеры инфраструктуры. При среднем encoded event 300 bytes:

| Events/s | Raw GB/day | GB/day при условном x4 replication+indexes |
| --- | --- | --- |
| 1000 | 25.92 | 103.68 |
| 10000 | 259.2 | 1036.8 |
| 100000 | 2592.0 | 10368.0 |

GB здесь decimal. Compression, резерв backups, retention и bandwidth pricing не заданы. Коэффициент x4 иллюстративный. Реальные raw transactions/accounts могут быть значительно больше 300 bytes. Для 100,000 events/s получается 2.592 TB/day raw — причина ограничивать universe и сохранять данные осмысленно, а не обещание бесплатной обработки всего рынка.

Compute estimate: `cores ≳ events/s × affected_candidates/event × mean_eval_cpu_ms / (1000 × utilization)`.

При условных 1,000 events/s, 4 candidates/event, 2 CPU ms/evaluation и 60% целевой загрузке нужно около 14 cores только на этот расчёт. Это не benchmark; I/O, state reconstruction, serialization, contention, retries и p99 queueing добавляются отдельно. Один aggregate update может менять тысячи routes, поэтому проверять tail fanout и bounded truncation.

## Начальные размеры экспериментов

| Ступень | Исследовательский target | Workers для сравнения | Условие роста |
| --- | --- | --- | --- |
| S0 | 20 рынков, fixtures/pinned replay | 1, 2 | Детерминизм, correct recovery, no stale admission |
| S1 | 100 выбранных рынков | 2, 4, 8 | Больше useful results на CPU/cost, стабильный p99 |
| S2 | 1,000 выбранных рынков | 4, 8, 16 | Источник/память/authority выдерживают измеренную нагрузку |

Это budgets/corpus targets. Ни одна ступень здесь не достигнута и не квалифицирована. CPU/RAM/IO выбрать после S0, не покупать «максимальную» инфраструктуру заранее. Полный raw stream и архивные nodes — отдельные затраты.

## Измерять каждый этап

| Метрика | Определение | Ограничение интерпретации |
| --- | --- | --- |
| qualified_coverage | Qualified markets / declared eligible catalog universe | Report both numerator and denominator, by depth/asset/domain; global universe unknown |
| state_freshness | decision_at minus latest complete usable state available_at | p50/p95/p99 plus maximum, separately from block age and provider timestamp |
| gap_exposure | Time partition was invalid / observed capture duration | Track dependent candidates suppressed and repair cost |
| useful_compute | Valid timely evidence records / CPU-second | Stable IDs deduplicated; raw candidate count excluded |
| deadline_survival | Qualified candidates still valid at admission / qualified candidates | No assumption that simulation success equals landing |
| incremental_capacity | Best exact modeled net result at added size minus baseline result | Same state, costs and budget; finite grid only |
| cost_per_useful_result | Data+compute+storage+verification cost / useful validated results | Report no denominator / no useful result explicitly; do not divide by zero |
| model_error | Quoted exact atoms minus independent evaluation atoms | Distribution and causes; not a USD floating tolerance |
| conflict_loss | Reference finite feasible objective minus chosen feasible objective | Only for bounded fixtures where optimum is known |
| capital_efficiency | Cost-adjusted outcome / time-weighted owned capital at risk | Separate flash principal turnover from owned fee/inventory capital |
| maker_markout | Signed fill-to-reference price move times quantity at each horizon | Show inventory and hedge PnL so markouts are not double charged |
| research_survival | Pre-registered hypotheses surviving independent holdout / all trials | Include abandoned trials and insufficient-evidence results |

Timeline записи: source event → local available_at → state ready → search complete → exact evaluation → shadow admission → evidence persisted. Clock domain и uncertainty хранить явно. CPU time отличается от wall time и queue age. p95 network latency не заменяет end-to-end p99 при bursts.

## Backpressure и прекращение работы

Переполненная очередь должна иметь bound и явные причины drop/coalesce. Сокращать speculative candidate work; raw state continuity сохранять или инвалидировать partition. При state gap, неизвестном decoder/asset identity, потерянной authority, истёкшем entitlement или неполном funding terms прекращается допуск зависимых работ.

Cost budget включает запросы, retries, bytes, storage/retention, CPU, simulation и independent verification. Paid fallback сам не активируется. Когда полезных результатов нет, cost per result показывается как «нет denominator», а не ноль. Для нового source считать marginal value против источников, которые он дублирует.

## Рост по доказательствам

План экспериментов: тот же corpus и размер бюджета при 1/2/4/8 workers, затем один дополнительный market family. Сравнивать decision equality, stale rate, tail latency и useful throughput. Если от большего числа workers растут conflicts/overhead без улучшения результата, уменьшить concurrency или изменить partitioning. Это корректный результат исследования.

Автоматизация сконструирована в JSON как disabled design. Периодический сбор, cron и автономная торговля этой работой не включаются.
