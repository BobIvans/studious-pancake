# Источники, инструменты и orderbooks

Каталог содержит43 записи проверенной repo основы:12 public-rate-limited,2 free-tier-key-required,18 open-source-rpc-or-host-required,11 access-not-verified. Полный список, первичные ссылки и ограничения — в SOURCE_CATALOG_RU.md и data/source_catalog_baseline_43.json. Ещё7 кандидатов вынесены в отдельный watchlist; их free-access не подтверждён.

Это расширяемый реестр всех источников, рассмотренных в рамках этого задания, а не исчерпывающий реестр всех Web3 API. Доступность, тарифы и схемы нужно перепроверить на дате будущей реализации. Платный сервис не становится бесплатным из-за open-source SDK. Бесплатная подписка не означает отсутствие расходов на RPC/CPU/хранение и не гарантирует право перераспространять данные.

## Роли данных

| Группа | Что собирать | Как использовать |
| --- | --- | --- |
| DEX Screener, GeckoTerminal, CoinGecko, DefiLlama | Addresses, pools, products, liquidity/reference metadata | Discovery/prioritization; не exact execution depth |
| Solana RPC, Helius, Yellowstone и chain nodes | Raw state/events, slots, account ownership | Pinned decoder, coherent snapshots, backfill; host доступ и quota отдельно |
| Raydium, Orca, Meteora, PumpSwap и EVM AMM SDKs | Protocol rules, state layouts, ticks/bins/fees | Independent golden vectors и точные venue adapters |
| Phoenix, OpenBook, Manifest | Market/book accounts, lot/tick/fee rules | После verified subscriptions и conformance; текущая quarantine сохраняется |
| Jupiter, 0x,1inch, OpenOcean, Odos, OKX DEX | Amount-specific router quotes и route provenance | Сравнение/нормализация; opaque quote не invents underlying pools |
| Pyth, Switchboard | Oracle values, confidence, publish time | Reference/eligibility/risk checks; не исполнимый обмен |
| Kamino, MarginFi, Aave, Morpho, Sanctum, Pendle | Obligations, caps, rates, rights, liquidation/redemption state | Exact product adapters после qualification |
| CCXT/Cryptofeed и CEX public APIs | Venue-native market metadata, books/trades/funding | Read-only cross-domain packs; не Solana atomic route |
| The Graph, Dune, SQD, Envio | Historical/indexed state and analytics | Reproducible research/backfill с measured lag; не автоматически hot-path truth |

## Порядок подключения одного source

1. Зафиксировать primary URL, endpoint/version, доступ, key requirements, quota, retention и redistribution rights.
2. Выбрать роль данных и цепочку source receipt → raw payload → decoder → state.
3. Проверить restricted read-only transport profile в существующем provider_governance.
4. Записать bounded real read-only sample, если доступ разрешён и возможен; ошибка доступа остаётся blocker.
5. Зафиксировать fixture по schema и independent protocol truth; upstream package/code revision pin.
6. Доказать completeness/freshness/sequence/slots; только затем amount-specific evaluator.
7. Добавить capability record: discovered, schema-tested, raw-verified, decoded, exact-qualified, fresh. Каждый статус имеет evidence и срок перепроверки.

Source key используется только для чтения с минимальными правами. Не включать credentials в ZIP/config examples/receipts. Retry/spend/cache принадлежат существующим owners; новый collector не получает отдельный безлимитный HTTP loop.

## Orderbook qualification

Общее название «orderbook» не делает feeds взаимозаменяемыми. Solana account snapshots требуют program owner, pinned binary/layout, correct market mints, complete bid/ask accounts и coherent slots. CEX incremental feeds требуют конкретного snapshot/delta sequence protocol, resync/checksum где они предусмотрены, heartbeat и gap events. Нельзя переносить sequence rules Binance на Kraken или просто сортировать все timestamps.

Существующий integer quote engine переиспользовать. BUY_BASE может не потратить весь budget; SELL_BASE округляет вход к lots. Requested input, consumed input, fee asset и residual должны быть раздельными. Depth не доказывает queue priority, отсутствие конкурирующих fills или исполнимость в следующем slot.

Verified artifact/subscription evidence оформляется существующими registry/conformance/PR066 owners. Строка decoder_revision в PR561 — provenance annotation, не сертификат. Во всём объёме этого архива OrderbookAmmStrategy остаётся disabled: исследования подписок не являются задачей включения runtime стратегии.

## Честное покрытие

Count sources отдельно от physical venues, assets и amount-specific edges. Один pool, найденный через три aggregators, остаётся одной liquidity state. Completeness denominator — versioned configured universe; unknown global denominator не превращается в100%. Quoted и fresh counts раздельны, gaps видимы, unsupported markets доступны только в discovery/reference layer.

Расширение по networks: Solana qualified pilot → один EVM chain/venue → отдельные EVM profiles → Move/Cosmos/прочие domains после их state/settlement qualification. Объединённый экран показывает all configured domains, а atomic route всегда остаётся внутри доказанного settlement scope.
