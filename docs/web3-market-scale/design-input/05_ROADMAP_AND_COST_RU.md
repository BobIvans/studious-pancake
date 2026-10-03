# Этапы реализации и эффективность затрат

Одна агрегированная спецификация не требует одного гигантского diff. Каждая следующая реализация должна давать ограниченный reviewable результат и переиспользовать текущие owners. Сроки и человеко-дни не оценены без выбранного venue, доступа к state и обновлённого baseline.

| Этап | Содержание | Exit evidence |
| --- | --- | --- |
| A — основание | WG-01..05, WG-21..22: owners, identity, catalog, governance, coherent state, replay/trace | Source/state contracts и воспроизводимый bounded corpus |
| B — точность | WG-06..11: exact evaluators, AMM/CLMM/DLMM/orderbook qualification, costs, capacity | Bit-exact protocol vectors + amount/slot/identity regressions |
| C — масштаб объёма | WG-12..15, WG-23: split-flow, correlated, primary, liquidations, UI | Shared-state conservation, after-cost comparison и coherent trace |
| D — новые продукты/domains | WG-16..20: PT/YT, intents, EVM, CEX/derivatives, asynchronous basis | Отдельные rights/finality/funding dossiers; неподтверждённое остаётся blocked |
| E — продукт и устойчивость | WG-24..28: performance, services, clearing, mechanism lab, qualification matrix | Measured repeatable benefit и отчёт по каждому capability |

Это логические группы, не строгая линейная очередность: точный dependency DAG — в data/dependencies.json. Например, EVM qualification предшествует EVM PT/YT. A bounded offline pilot может использовать готовый fixture state и не ждать всех внешних подписок; он не получает real-data status.

## Что именно масштабировать

1. **Размер**: exact net-capacity points и funding/resource caps. Bigger input может уменьшить прибыль.
2. **Независимые возможности**: количество свежих неконфликтующих routes после dedup underlying liquidity.
3. **Типы продуктов**: проверенные transformations и rights. Иной payoff требует другой модели, не переименования swap.
4. **Пользовательский поток**: clearing и improvement чужих целей. Доступ к intents и спрос нужно доказать.

Выбор следующего market pack: заранее зафиксировать минимально нужные данные и proof, оценить access/hosting effort, затем измерить marginal coverage и полезность на held-out corpus. Не ранжировать только по TVL, числу тикеров или рекламным TPS.

## Метрики и расходы

| Метрика | Определение |
| --- | --- |
| Data cost | Provider charges + node/RPC hosting + bandwidth + storage; free quota не означает нулевой общий cost |
| Compute cost | CPU seconds, memory peak, exact evaluations, state recomputations и replay storage |
| Useful evidence | Заранее определённый прошедший quality gate result, не обязательно прибыльная сделка |
| Cost per useful result | Все расходы периода / число useful results; при denominator0 значение undefined |
| Coverage | Fresh qualified markets / объявленный universe; raw, bound, decoded, quoted counts дополнительно |
| Capacity | Конечные exact sampled inputs с conservative net и assumptions; интерполяция не даёт executable quote |
| Latency | Event→available→state→candidate p50/p95/p99 на фиксированном hardware/corpus |
| Rejection health | Причины stale, gap, unknown fees/rights, missing model, budget exhausted, resource limits |

First target — небольшой read-only pilot, пригодный для обычного компьютера. Full-market raw data не держать целиком в RAM/browser. Hotset + disk replay, incremental invalidation, bounded parallelism, compressed receipts и retention tiers выбирать после измерения. Не дублировать provider caches/spend authority.

Повторять comparison при изменении source schema, decoder/model/token rules, fees, rights, block finality или catalog tier. Continuous evolution означает versioned experiments, regression gates и rollback, а не автоматическое добавление непроверенных рынков.

## Application / L2 / L3 / L1

| Слой | Что исследовать | Доказательство необходимости |
| --- | --- | --- |
| Приложение существующей сети | Solver, data graph, contracts/rules experiments | Подходит первым: требуемый outcome достижим при existing settlement |
| L2 | Специализированные execution/data-availability/ordering параметры | Existing chain ограничивает измеренный workload при доказанном спросе |
| L3 | Изоляция application workload и настройки поверх parent L2 | Изоляция/стоимость полезнее дополнительной инфраструктуры и settlement зависимостей |
| L1 | Собственный consensus/execution/settlement | Нужные свойства невозможно получить на доступных слоях; учтены security и operating costs |

Новая сеть сама по себе не создаёт ликвидность, спрос или arbitrage profit. Launch, contracts deployment, bridge/sequencer/validator operations и token issuance не входят в этот архив. Здесь только criteria memo и offline mechanism experiments.
