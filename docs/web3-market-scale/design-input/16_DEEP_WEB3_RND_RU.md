# Глубокий Web3 R&D: совместимые слои и масштабирование

**Следующий рычаг — находить и проверять композиции swaps, claims, credit и клиентских obligations на одном согласованном state.** Увеличение суммы flashloan или числа API само по себе не увеличивает полезную исполнимую ёмкость.

Обновление на 2026-10-03: primary-document research и static review `main@67d3852cbc4cb1b24582df45adbf6a42d4da2af0`. Добавлены 16 protocol dossiers, 9 комбинаций, 12 экспериментальных дизайнов и 36 будущих проверок. Они дополняют прежние 28 WG, 89 T, 10 R&D-карточек, 12 market classes и 5 scale studies. Ни одна новая гипотеза не измерена как прибыльная.

## Важное изменение baseline

PR #562 уже добавил exact CPMM capacity bridge. Сначала читать [обновлённые owners и следующий slice](21_CURRENT_MAIN_AND_NEXT_SLICE_RU.md). Старый `09_FIRST_BOUNDED_PR_RU.md` — историческая постановка уже имеющейся части, не задание повторить PR.

## Что исследовать в первую очередь

1. Доказать границы текущего exact CPMM bridge, затем соединить его с существующим AGG05 shared-state split-flow. Это ближайший путь от одного размера к достоверной sampled capacity.
2. Ускорить только изменившиеся зависимости через existing watermarks/invalidation; сравнить с full recomputation на одинаковом replay. Измерять p99 и пропущенные возможности, не один быстрый microbenchmark.
3. Добавить один immediate vault/claim transformation и один intent workflow. Переход к новому EVM/Sui рынку требует отдельной identity/model/domain qualification.
4. Выделить standalone evidence API. Общий clearing solver, рынок вычислений и mechanism lab используют один corpus и verifier, но получают разные экономические оценки.

Это порядок инженерного исследования, не ranking инвестиционной доходности. У новой цепи часто нет достаточной ликвидности, полезного потока или доступного hedge; большие spreads могут отражать эти ограничения.

## Связки, которые можно изучать как продукты

| ID | Комбинация | Приоритет | Класс результата |
| --- | --- | --- | --- |
| CB-01 | Exact cycles → shared-state split-flow | P0 | conditional atomic research |
| CB-02 | Vault conversion ↔ DEX ↔ credit | P1 | conditional atomic conversion; yield separate |
| CB-03 | Intents → netting → residual exact routing | P1 | clearing / service surplus |
| CB-04 | aToken / shared wallet liquidity → funding-aware mechanism lab | P2 | leveraged LP research, not guaranteed arbitrage |
| CB-05 | Cross-domain intents → inventory netting → settlement evidence | P2 | non-atomic inventory |
| CB-06 | Funding claims ↔ perps / new builder markets | P2 | carry / hedge research |
| CB-07 | Orderbooks / conditional claims → exact residual and parity checks | P2 | domain-specific market integrity |
| CB-08 | Low-latency state → dependency invalidation → bounded search | P0 after exact baseline | infrastructure economics |
| CB-09 | Evidence providers → exact verifier → API procurement | P1 | data/compute service economics |

Подробные задания находятся в `deep_combinations/CB-xx.md`. Они не подразумевают, что все названные protocols должны работать в одной транзакции или уже совместимы.

## Три продукта работают вместе

| Продукт | Общее ядро | Отличающийся критерий успеха |
| --- | --- | --- |
| Clearing solver | Exact conversions, shared resources, typed user obligations | Одинаковые выполненные обязательства при меньших costs/prefund; каждый пользователь соблюдает limits |
| Проверяемые расчёты | State capsules, amount-bound verifier, cost/rights ledger | Correct result к deadline дешевле local baseline с учётом verification; затем повторный платящий спрос |
| Market-mechanism lab | Те же market states, identities и economic ledgers | Улучшение объявленной цели при явных behavioural assumptions; LP/trader/solver результаты раздельно |

Первый технический поставляемый компонент — **Market Graph Evidence & Capacity API**. Клиентский workflow остаётся **Treasury & Liquidity Planning**: сколько активов можно получить к сроку и какой капитал для этого действительно нужен. Marketplace вычислений развивается только после доказанной потребности в покупаемой услуге.

## Быстро и крупно — разные оси

| Ось | Измерение | Ложный заместитель |
| --- | --- | --- |
| Размер сделки | Exact feasible capacity after costs по конечной сетке сумм | Quote × multiplier |
| Частота | Неконфликтующие qualified opportunities за единицу времени | Сырые positive spreads |
| Покрытие | Admitted fresh markets / объявленный universe с unknown и blocked | Сумма строк всех агрегаторов |
| Оборот капитала | Principal и collateral по domain, peak и capital-time до settlement | Время пользовательского fill |
| Скорость разработки | Цена квалификации второго адаптера того же класса | Число новых модулей/PR |
| Масштаб продукта | Повторные workflows, after-cost value и unsubsidized demand | TVL, адреса и объём incentives |

## Навигация

- [Свежие protocol dossiers и первичные источники](17_PROTOCOL_DOSSIERS_AND_SOURCES_RU.md).
- [Как слои соединяются](18_COMPOSITION_AND_RESOURCE_GRAPH_RU.md).
- [Автоматизация, latency и экономика](19_AUTOMATION_AND_SCALE_RU.md).
- [Эксперименты и будущие проверки](20_DEEP_EXPERIMENTS_AND_ACCEPTANCE_RU.md).
- [Актуальный main и следующий bounded slice](21_CURRENT_MAIN_AND_NEXT_SLICE_RU.md).
- [Handoff для будущей реализации](22_DEEP_RND_HANDOFF_RU.txt).

Этот ZIP содержит проект последующей работы. Sender/signer/submission, реальные оплаты, strategy enable и live authorization отсутствуют. `OrderbookAmmStrategy` остаётся disabled. Публичные документы не подтверждают доступ пользователя к API или полный рынок Web3.
