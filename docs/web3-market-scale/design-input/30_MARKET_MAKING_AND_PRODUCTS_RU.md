# Как развивать крупный market-making и solver business

Технологический рычаг — доказанная глубина state coverage, точный расчёт, восстановление, низкая стоимость полезного результата и доступ к потоку клиентов. Число flashloans не является масштабом market-making бизнеса.

## Эволюция продуктов

| Этап | Продукт | Общий слой | Отдельное доказательство |
| --- | --- | --- | --- |
| 1 | Исследовательский market observatory | Raw state, rights, point-in-time data | Полезное покрытие, cost, replay |
| 2 | Solver for exact routes | Graph, integer amounts, joint state | Capacity и after-cost modeled result |
| 3 | Общий clearing solver | Claims, intents, route evaluation | Индивидуальные limits, surplus distribution, real eligible flow |
| 4 | Проверяемые расчёты | Evidence manifests, independent checker | Correct result, SLA/cost, willingness to pay |
| 5 | Mechanism laboratory | Сценарии и права | Устойчивость к изменению поведения участников |
| 6 | RFQ/CLOB/LP market making | Market state, hedging and capital system | Queue, inventory, access, adverse selection и полный PnL |

Последовательность — исследовательская, не обещанный business timeline. Три ранее выбранных продукта остаются частью одного пакета; их detailed CLR/VRC/MML designs сохранены в [11_RND_NEXT_3_PRODUCTS_RU.md](11_RND_NEXT_3_PRODUCTS_RU.md).

## Общий clearing solver

Объединять совместимые обязанности и сводить встречный flow до внешних swaps. Проверять conservation по каждому asset, user limit, deadline, eligibility, partial-fill rule и fairness policy конкретного механизма. Batch-level выгода не может скрывать нарушение отдельного пользователя. Сравнивать route-only, simple netting и full clearing на одном corpus и одном compute budget.

Увеличение client flow иногда даёт больше устойчивой ценности, чем увеличение собственного principal, но это гипотеза о спросе. Нужны eligible channels, измеримая экономия пользователя, прозрачное распределение выгоды и реальные повторные обращения. Архив не получает частные заявки и не отправляет предложения клиентам.

## Рынок проверяемых расчётов

Первый товар должен иметь однозначную спецификацию: decode state revision X; evaluate route+amount on manifest Y; produce a reproducible simulation evidence record. Consumer передаёт deadline, maximum cost и verification rule. Provider answer связывает input hash, artifact/version, deterministic result и measured latency.

Подпись доказывает происхождение ответа, а не правильность. Проверяющий использует независимый evaluator или согласованную witness/replay procedure; сравнение двух провайдеров одного upstream не даёт независимости. Sampling проверок не считается достаточным для high-value decisions без анализа ошибок. Разница цены и SLA сравнивается на одной задаче, включая verification cost.

`pr359_wave15_institution.py` сейчас представляет узкий offline toy service. Нельзя считать его наличие доказанным procurement market. Следующий R&D измеряет качество и cost; demand study проверяет спрос после отмены subsidies. No-subsidy результат UNKNOWN до реального исследования. В этой сессии оплаты и outreach не проводятся.

## Лаборатория механизмов

Сравнивать auction format, fees, allocation, netting и LP rules на одинаковых inputs. Не ограничиваться средним aggregate surplus: отдельные группы пользователей, tail execution quality, budget balance, inventory needs и manipulation sensitivity могут ухудшаться. Frozen historical flow даёт условный replay, поэтому добавить несколько моделей стратегического ответа и stress regimes.

Uniswap v4 hooks и другие programmable markets из предыдущих dossiers — площадка для будущих экспериментов. Каждый hook имеет конкретный code/permissions/state footprint. Hook existence не означает готовый reusable economic model. До deployment полезнее проверить offchain mechanism hypothesis и спрос.

## Market making как отдельная capital model

Resting CLOB/RFQ quotes, LP positions и hedge collateral финансируются inventory/допустимым credit, который существует достаточно долго. Flashloan можно исследовать для конкретного atomic rebalance/hedge, а не как постоянное обеспечение всех quotes.

Обязательная replay-модель включает queue position bounds, partial fills, cancel/replace delay, self-match rules, inventory persistence, funding/borrow, venue outages и adverse markouts. Для LP считать price-path inventory revaluation, fees и rebalance costs. Fee revenue без inventory PnL не является доходностью.

Измерять сначала contribution после data/compute/verification и trading costs, затем capital-days, drawdown и concentration. Реальные limits и положения accounts не подменяются synthetic data. CEX public book доступ не доказывает право торговать на площадке; RFQ flow может быть private/permissioned.

## Нужна ли своя L1/L2/L3

Начать с application/evidence layer на существующей инфраструктуре. Dedicated chain становится предметом R&D, когда измерено, что execution rules, isolation или settlement architecture ограничивают доказанный продукт. Тогда сравнить operating cost, liquidity fragmentation, bridge/settlement delay, validator/sequencer requirements и migration demand. Новая сеть без organic flow не добавляет rentable arbitrage capacity.

Цель «крупнейший market maker» не подтверждается архитектурой. Контролируемые этапы — qualified markets, полезный flow, положительная полная economics и доказанная надёжность на каждом увеличении масштаба.
