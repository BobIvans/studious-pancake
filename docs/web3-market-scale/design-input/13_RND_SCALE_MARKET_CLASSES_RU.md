# R&D: от трёх продуктов к классам торговли

**Предлагаемое направление — повторно использовать модели прав, преобразований и проверки для целых классов задач.** Общий graph/solver не может автоматически считать любые рынки взаимозаменяемыми. Масштабирование происходит через новые квалифицированные adapters и клиентские workflows.

Это продолжение планового ZIP:12 market-class dossiers и5 исследований масштабирования. Ничего не реализовано и не запущено. Все оценки приоритета — инженерные гипотезы без оценок TAM, доходности или реального спроса.

## Куда расширяться

P1 — наиболее близкие по reusable owners и понятному первому продукту; P2 — после exact/replay и time/risk qualification; P3 — более дальние rights/fulfillment исследования. Это не рейтинг ожидаемой инвестиционной доходности.

| Класс | Приоритет | Продукт | За счёт чего масштабируется |
| --- | --- | --- | --- |
| Stablecoin-платежи, FX и treasury liquidity | P1 | Read-only treasury optimizer: сравнение маршрутов, взаимозачёт платежей, прогноз дефицита ликвидности и reconciliation; возможная модель оплаты за API/аналитику. | Число recurring payment flows и клиентов с одним reusable model, а не только размер собственного flashloan. |
| Vault shares, cash management и redemption queues | P1 | Liquidity-aware cash planner: когда asset доступен, какие withdrawal costs и capacity; API evidence по vaults. | Повторное использование интерфейсов и qualification по многим vault implementations; customer goals вместо общего highest-APY рейтинга. |
| Collateral, refinancing и liquidation operations | P2 | Debt/collateral planner: смена financing source, collateral conversion, liquidation/unwind evidence. | Переиспользуемые lender adapters и recurring risk/treasury workflows; не удваивать общий borrow capacity. |
| Доходность, PT/YT и fixed/floating rates | P2 | Rate/claim optimizer: сравнение фиксированных и плавающих cashflows, maturity exposure и collateral needs. | Большое число recurring rate exposures и risk customers; объем не гарантирован и определяется глубиной и доступом. |
| Spot–perp, options и hedge baskets | P2 | Scenario-based hedge/basis research engine; портфель альтернатив с фактическими constraints. | Reuse contract identity/risk models across families; реальные exposures и data rights ограничивают universe. |
| Conditional claims и complete sets | P2 | Проверка complete-set parity и объяснение resolution/condition risks; read-only market integrity API. | Many conditions через одну grammar; forecasts и ставку на исход не выдавать за доказанный arbitrage. |
| RWA, tokenized funds/equities и NAV rights | P3 | Rights-aware NAV/redemption monitor и сравнение доступных преобразований. | Multi-product rights evidence tooling; не обещать unlimited access к tokenized securities. |
| Cross-domain liquidity и inventory rebalancing | P2 | Read-only rebalancing planner с trapped inventory/timeout scenarios и quality/cost comparison. | Customer intents и reuse resolver adapters; capacity constrained общим inventory и доступом к исполнению. |
| Compute, inference и storage procurement | P1 | Resource broker: выбрать допустимую вычислительную услугу по delivered result cost, deadline и quality. | Множество клиентов и workloads при reuse task contracts; capacity по quality/location/time, не одному GPU ticker. |
| Данные, freshness и evidence services | P1 | Market-state/evidence API: reproducible snapshots, exact route evaluation и provenance bundles. | Subscription/API customers и reusable evidence; предельная стоимость новой coherent coverage важнее числа API. |
| Blockspace, inclusion и execution-quality services | P2 | Inclusion-cost/latency research advisor и monitoring SLA; без sender. | Распределение ресурсов многих application workloads; преимущество только после after-cost deadline benchmark. |
| Физическая B2B-торговля: закупки, logistics, energy capacity | P3 | Delivery-aware procurement planner и проверка supplier evidence; сначала digital twin одного procurement class. | Повторяющиеся procurement workflows и SaaS-клиенты; отраслевой adapter обязателен, universal commerce ещё не реализован. |

## Как все три продукта работают в каждом классе

| ID | Clearing | Проверяемые расчёты | Mechanism lab |
| --- | --- | --- | --- |
| MC-01 | Встречные платежные obligations и остаточные swaps; сохранять owner/recipient/asset/domain identity. | Exact FX/route comparisons, fees, idempotent payment-state reconstruction. | Compare batch interval, liquidity reservation и fee allocation; deadlines клиентов — hard constraints. |
| MC-02 | Сопоставить liquidity deadlines со shares и допустимыми immediate conversions. | Pinned preview/max/fee/rounding checks плюс воспроизводимый request lifecycle. | Compare queue batching и withdrawal fee policy с одинаковыми obligations. |
| MC-03 | Композиция repayment/unlock/swap и netting совместимых obligations. | Exact health/cap/rate/oracle/unwind evaluation с общим collateral state. | Compare liquidation batching, auction incentives и close-factor regimes офлайн. |
| MC-04 | Netting совместимых cashflow obligations по asset/time/index, не произвольных доходностей. | Индексы, maturity, margin и protocol payoff replay; existing Boros owner fixture-only. | Compare rate-auction, collateral/margin schedules и settlement interval sensitivity. |
| MC-05 | Net exposure и bounded multi-leg hedge; нельзя считать все CEX fills simultaneous. | Mark/index/book differences, funding/borrow terms и stress replay. | Compare margin netting, batch hedge allocation и quote priority rules. |
| MC-06 | Совместимые outcome bundles дают общий collateral claim; condition IDs и collateral обязательны. | Outcome partitions, exact lot/fee/depth и split/merge rights. | Compare batch matching, fees и allocation с per-user constraints. |
| MC-07 | Net compatible issuer obligations только с доказанными правами; token ≠ underlying title автоматически. | NAV vintage, eligibility/session, custody, corporate action and redemption evidence. | Compare redemption windows, queue allocation и inventory buffers на офлайн модели. |
| MC-08 | Сопоставлять встречные domain obligations, чтобы реже переносить inventory. | Finality, settlement assumptions, refund/timeout and exact fee evidence. | Compare inventory reservation, filler auctions и failure allocation policies. |
| MC-09 | Совместить batch задач с доступными time/resource slots; сохранять deadline/privacy/data locality constraints. | Повторяемый результат и actual end-to-end resource usage; stochastic inference требует task-specific quality, не просто identical bytes. | Compare posted/reverse auction, cancellation/refund и reservation policy на synthetic providers. |
| MC-10 | Batch одинаковых запросов, deduplicate raw fetches и allocate shared quotas без двойной продажи обещанной freshness. | State authenticity, amount-specific correctness, freshness и completeness проверять раздельно. | Compare freshness SLA tiers, pay-per-verified-result и query budgets в offline buyer model. |
| MC-11 | Batch совместимых demands for resources; конфликтующие writes/deadlines не объединять механически. | Calibrated inclusion/latency evidence и независимый receipt, не provider self-reported guarantee. | Compare fee bid/deadline allocation и service guarantee models. |
| MC-12 | Консолидировать спрос только для одинаковых спецификаций, места/времени поставки и прав; не складывать разные качества товара. | Evidence о происхождении/поставке и invoice matching; цифровая запись не доказывает физическую истину сама по себе. | Compare supplier auctions, partial delivery, cancellations, deposits и penalties на модели. |

## Что действительно новое и что уже существует

Stablecoin payment rails, vault standards, rate products, conditional claims и compute marketplaces уже имеют реальные технические интерфейсы. Возможность для исследования — слой сравнения, rights-aware planning и проверяемых outcomes поверх них. Публичная документация не доказывает достаточную ликвидность, бесплатный production API или доступ конкретного клиента.

Примеры первичных оснований: ERC4626 определяет vault share interface, ERC7540 — asynchronous request/claim lifecycle; Boros документирует fixed/floating funding-rate cashflows; conditional-token models поддерживают split/merge/redeem; Akash описывает bidding/lease lifecycle. Финансовая возможность каждого recipe ещё должна пройти amount/state/cost/access qualification.

## Общая модель целого trade class

Каждая заявка задаёт: кто имеет право распоряжаться входом, требуемый результат, количество и units, качество/срок/место поставки, допустимые substitutes, максимальные расходы и способ подтвердить completion. Model обязана отличать:

1. Немедленное преобразование asset→asset в одном settlement domain.
2. Преобразование asset→claim(s) или claims→asset с дополнительными правами.
3. Обязательство во времени: interest, maturity, margin, redemption queue.
4. Условное требование: outcome/resolver/dispute rules.
5. Услугу/поставку: resource capacity, качество результата, deadline, acceptance и dispute.

У этих типов общий язык inputs/outputs/rights/obligations/time/evidence, но разные exact evaluators. Нельзя заменить качество товара или GPU latency одним spot price; нельзя сделать одноимённые токены разных эмитентов одинаковым активом.

Task-level graph хранит typed transformations/hyperedges, а существующие canonical market/route/claims owners продолжают владеть своими контрактами. Не создавать рядом четвёртый универсальный solver. Дополнять projections и qualified adapters.

## Следующий практический продукт

Мой первый выбор — **Treasury & Liquidity Planning API** для одного клиентского workflow: получить заданные активы к deadlines с минимальными допустимыми costs и peak funding. Начать с same-domain stable payments/netting (MC-01), затем vault liquidity/claim deadlines (MC-02). Источник возможной выручки — полезная аналитика/оптимизация для клиента; спрос и готовность платить пока UNKNOWN.

Второй близкий продукт — **Market Evidence API** (MC-10): exact state/route replay и объяснение provenance/freshness. Existing INST-01 даёт основу для следующей проверки внешних поставщиков вычислений (MC-09). Marketplace нужен только если полная стоимость delivered result лучше local service и найден повторный спрос.

Rate/derivative/conditional markets (MC-04..06) исследовать отдельными packs. RWA и физические закупки (MC-07/12) требуют намного большего rights/settlement/fulfillment evidence; весь их предполагаемый объём нельзя записать в atomic flashloan liquidity.

## Автоматизация и непрерывное развитие

Предлагаемая future loop: admitted evidence → typed identities/rights → invalidation → bounded candidate/experiment → exact replay → baseline/holdout → cost/quality report → следующий dossier. LLM может предлагать гипотезы и адаптерные задания, но не заверять собственные финансовые claims и не повышать qualification по одному текстовому выводу.

data/market_class_automation_design.json — **не исполняемый workflow**, enabled=false, schedule=null. Он описывает разрешённые read/local-report эффекты будущего scope и обязательные budgets. В этом запросе нет запущенной automation, 24h campaign, внешних сообщений или trade execution.

## Измерения масштаба

Нужны четыре независимых ряда: exact feasible capacity по размерам, неконфликтующие opportunities, reuse economics новых market adapters и recurring customer workflows. Увеличение числа источников/тикеров/PR не является измерением масштаба продукта.

Для каждого следующего adapter: время qualification, дополнительная fresh coverage, compute/data cost, matched demand, per-user outcome и общий ресурсный конфликт. Для сервиса: revenue/customer пока UNKNOWN; unit economics оцениваются после данных о willingness to pay и эксплуатации, а не из TVL.

Типичный критерий выбора: новый класс проходит обязательные proof/rights/resource gates и даёт измеримую предельную пользу после затрат. Если caps/exposure/unknown state не позволяют доказать benefit, расширять coverage ради красивого total count не нужно.

## Пять исследований масштабирования

| ID | Исследование | Эксперимент | Gate |
| --- | --- | --- | --- |
| SCALE-01 | Перенос одной market grammar на вторую площадку | Выбрать MC-01 или MC-02 и2 независимых implementations. Одинаковая semantics suite, но собственные rights/state/fee adapters. Измерить время квалификации и долю переиспользованного кода; наличие общего интерфейса не substitute protocol proof. | Каждый adapter проходит same invariants и свои independent vectors; missing model остаётся blocked. |
| SCALE-02 | Портфель возможностей и общие ограничения | До18 уже проверенных candidate points как существующий exact portfolio bound. Общие provider quotas, collateral, inventory, pool/custody/issuer exposure и compute. Compare greedy vs existing allocator; joint scenarios считать отдельно, не называть сумму tail numbers CVaR. | Неизвестный resource key запрещён; один shared pool не расходуется дважды; scenario risk подтверждён выбранной явной моделью. |
| SCALE-03 | Ограниченная автоматизация R&D | Finite source snapshots → typed candidate dossier → reproducible experiment plan → replay → measured report. Новая source/schema/model revision инвалидирует связанные results. Пределы IO/CPU/storage устанавливаются до запуска. | Proposed hypothesis не становится qualified сама из-за уверенного текста; никаких remote mutations, pay/order/send действий. |
| SCALE-04 | Устойчивость преимущества при конкуренции | Использовать existing synthetic ecology owner: stress competing solvers, latency, same-source crowding, inventory congestion и external demand response. Compare benefit per customer/useful result after data/compute/verification cost. | Synthetic crowding не выдаётся за измеренный live market; positive result переживает объявленные holdout regimes либо записывается negative. |
| SCALE-05 | Проверка продукта и выбор следующего класса | План исследования willingness to pay/повторного использования: выбрать одного типа клиента и measurable workflow. Сравнить benefit с интеграционными/operation/support затратами. Без сообщений/платежей сейчас; demand UNKNOWN. | Следующий класс выбирается по measured marginal value и доступным evidence, а не по TVL/числу функций/числу PR. |

## Источники

- [Circle Payments Network](https://developers.circle.com/cpn) — reference `circle`.
- [ERC-4626](https://eips.ethereum.org/EIPS/eip-4626) — reference `vaults`.
- [ERC-7540](https://eips.ethereum.org/EIPS/eip-7540) — reference `async-vaults`.
- [ERC-7683](https://eips.ethereum.org/EIPS/eip-7683) — reference `crosschain`.
- [Boros funding-rate settlement](https://docs.pendle.finance/boros-docs/about-boros/funding-rate-settlement) — reference `boros`.
- [Polymarket positions](https://docs.polymarket.com/trading/positions/how-positions-work) — reference `conditional`.
- [Ondo product/rights documentation](https://docs.ondo.finance/) — reference `ondo`.
- [Akash deployment lifecycle](https://akash.network/docs/learn/core-concepts/deployments/) — reference `akash`.
- [GS1 EPCIS2.0](https://ref.gs1.org/standards/epcis/) — reference `gs1`.
- [Aave flash-loan concepts](https://www.aave.com/docs/aave-v3/guides/flash-loans) — reference `aave`.
- [Deribit API documentation](https://docs.deribit.com/) — reference `deribit`.
- [CoW fair combinatorial auction](https://docs.cow.fi/cow-protocol/concepts/introduction/fair-combinatorial-auction) — reference `cow`.
- [Uniswap v4 hooks](https://developers.uniswap.org/docs/protocols/v4/concepts/hooks) — reference `hooks`.

Новые ссылки проверялись3 октября2026 по Риге. Цены, yields, тарифы и рыночные объёмы в план не подставлялись. Некоторые source landing pages не раскрывают детали конкретного продукта; перед adapter implementation нужен pinned полный dossier. Каждый market class — proposed research, не подключённый рынок.
