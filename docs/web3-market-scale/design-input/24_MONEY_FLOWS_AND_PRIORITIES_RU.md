# Где искать большие потоки

Публичные dashboards дают карту внимания. Для решения о размере сделки нужны доступный cash конкретного lender и exact capacity конкретных преобразований. Эти величины измеряются отдельно.

## Снимок обзора

Прочитано 2026-10-03, UTC. Значения округлены источником, точное время окончания каждого окна не опубликовано в сохранённом отображении. Страницы менялись во время работы: perpetual headline вырос с $25.979b до $26.631b. Поэтому таблица — асинхронный исследовательский snapshot; её нельзя использовать как единое торговое состояние.

| Показатель | Отображённое значение | Тип | Источник |
| --- | --- | --- | --- |
| DEX volume, 24h | $7.606b | Оборот | [DefiLlama DEX](https://defillama.com/dexs) |
| Perpetual volume headline, 24h | $26.631b | Номинальный оборот | [DefiLlama perps](https://defillama.com/perps) |
| Perpetual open interest | $14.129b | Открытый номинал | [DefiLlama perps](https://defillama.com/perps) |
| Stablecoin capitalization | $306.792b | Stock | [DefiLlama stablecoins](https://defillama.com/stablecoins) |
| Lending TVL | $54.986b | Stock по методике источника | [DefiLlama lending](https://defillama.com/protocols/lending) |

Выборочные ориентиры: Uniswap $2.141b, PancakeSwap $978.96m и Aerodrome $511.22m DEX turnover за 24h; Orca $305.07m и Raydium $195.45m. Hyperliquid perp reported volume $10.382b. Aave TVL $19.186b, Morpho $11.316b, Kamino Lend $1.387b. Числа и ссылки с типами метрик находятся в `data/money_flow_snapshot.json`; это не суммы, которые доступны нашему боту.

## Как из обзора выбрать инженерную работу

| Кластер | Что изучать | Почему может масштабироваться | Первый критерий |
| --- | --- | --- | --- |
| DEX spot и stable pairs | Exact curves, multi-path, CLOB/AMM | Несколько независимых глубин | Инкрементальная after-cost capacity |
| Lending + collateral markets | Liquidation/unwind, refinance | Событийные преобразования прав | Корректное состояние долга, repay и unwind |
| Perps и CEX–DEX | Funding/basis, RFQ и hedge | Более широкий поток клиентов и продуктов | Inventory и margin-adjusted result |
| Claims и первичные рынки | LP shares, SY/PT/YT, wrapper, immediate redeem | Экономические тождества вместо ticker correlation | Реальное право и момент расчёта |
| Intent flow | Netting, batch clearing, routing | Полезность для чужих сделок | Индивидуальные ограничения и платящий спрос |
| Новые venues/chains | Qualification dossiers | Раннее покрытие новых продуктов | Устойчивый поток, доступ и воспроизводимая модель |

Это порядок исследований, а не рейтинг доходности. Приоритет в конкретной неделе определяется ожидаемой ценностью информации на единицу расходов, подтверждёнными ограничениями и недостающими данными. Не задавать фиктивный ROI, пока нет независимых наблюдений.

## Деноминаторы и двойной счёт

Сохранять gross DEX volume, пользовательский net flow, bridge transfers, mint/burn и lending stock как разные серии. Один маршрут может породить несколько swap events; aggregator volume может уже содержать те же fills. Cross-chain lock/mint — две записи перемещения одной стоимости, не два независимых притока.

Сравнение во времени требует одинакового definition_revision, окна, валютной оценки и coverage. Token supply change может включать изменения valuation и состава источников; это не автоматически новый fiat demand. Wallet labels и биржевые адреса — атрибуции с уверенностью и историей, не доказательство владельца или причины сделки. Личности пользователей для этого не нужны.

DefiLlama поясняет определения в [Data Definitions](https://defillama.com/data-definitions). Агрегированные totals могут включать стимулированную активность и многократный оборот капитала; полезность для нас проверяется отдельно через depth, fees и state evidence.

## Маршрут сбора денег как данных

Для каждого наблюдения хранить metric, stock/flow, timestamp доступности, окно, asset, chain, protocol, venue, parent/child relationship, source, revision и coverage. На UI показывать пять отдельных views: потоки; исполнимые преобразования; funding; конфликты; доказательства. Толстое ребро money-flow графа не должно выглядеть как исполнимая swap-функция.

Архив содержит каталог, а не доказательство полного охвата Web3. Число поддерживаемых рынков должно выводиться из успешно восстановленных и квалифицированных состояний, а не из количества URL.
