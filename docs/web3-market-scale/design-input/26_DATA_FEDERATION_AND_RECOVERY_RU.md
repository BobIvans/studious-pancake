# Как наблюдать много рынков без полного пересчёта всего Web3

Предлагается федерация данных: широкий дешёвый catalog, небольшой квалифицированный hot set и расширяемый warm research set. Один provider stream принимается один раз и раздаётся потребителям локально. Стратегия не открывает собственную копию каждого feed.

## Слои

| Слой | Данные | Обновление | Назначение |
| --- | --- | --- | --- |
| Cold | Directories, TVL/volume/fees, contracts, specifications | По bounded refresh policy | Discovery и приоритет qualification |
| Warm | Trades, funding, claims, исторические книги, flows | По событиям и доступной квоте | Features, исследования, выбор hot markets |
| Hot | Полное достаточное состояние выбранных pools/books/reserves | По валидным updates | Exact amount evaluation |
| Evidence | Raw manifests, decoder versions, timestamps, rights, outcomes | Append-only | Replay, independent verification и audit |

Cold quote/price не повышается до exact edge из-за частого polling. Hot market допускается только при доказанном объёме state coverage. Raw logs хранить по domain/source/date/partition; проекции должны быть восстанавливаемыми. Конкретный storage/streaming stack выбирается после измерения: один локальный process и append log сначала, distributed broker и columnar store — когда доказана необходимость. Архив не устанавливает Kafka, Redpanda, ClickHouse или платные сервисы.

## Приём и восстановление

1. Проверить source identity, entitlement generation, schema и byte/depth limits до обработки payload.
2. Сохранить raw hash, source cursor, observed_at и available_at. Provider event-time хранить отдельно.
3. Дедуплицировать delivery по правилам источника. Для некоторых feeds повторное сообщение — correction, а не duplicate.
4. Применить update одним writer к partition state; emit immutable frame только после проверки completeness и continuity.
5. Связать frame с raw manifest, decoder/math revision, block/fork/version vector и expiry policy.
6. При gap, reconnect или fork отозвать frame и зависимые candidate evidence, затем выполнить bounded repair или полную rebootstrap.
7. Commit cursor вместе с достаточным восстановимым состоянием или replay boundary. Cursor без состояния не является успешным recovery.

Подход опирается на `src/market/streams.py`, `src/market_data_evolution/contracts.py` и `src/strategy/market_graph_ingest.py`. Дополнительный universal state engine с другим источником истины не нужен.

## Особенности источников

| Домен/feed | Что связывать | Что нельзя предполагать |
| --- | --- | --- |
| Solana accounts | Genesis, owner program, slot/fork, account write version, decoded revision | Один slot автоматически означает согласованный snapshot всех аккаунтов |
| EVM logs/state | Chain identity, block hash/parent, tx/log index, pinned calls | log подписка сама backfill-ит всё после disconnect |
| Sui | Checkpoint, object ID/version/digest, package version | Текущий object совпадает с версией, прочитанной ранее |
| Binance depth | Venue session, snapshot/update IDs и правила continuity конкретного feed | Один универсальный порядок delta updates для всех exchanges |
| Coinbase level2 | Snapshot и абсолютные размеры уровней | Новый size нужно прибавлять к старому |
| Hyperliquid l2Book | Market identity, precision/depth mode, timestamp | 5/20 видимых уровней доказывают полную глубину |
| Индексаторы | Indexed block, schema/revision, lag, query rights | Latest indexer response пригоден для точного текущего исполнения |

Первичные источники: [Geth subscriptions](https://geth.ethereum.org/docs/interacting-with-geth/rpc/pubsub), [Sui object model](https://docs.sui.io/develop/sui-architecture/object-model), [Binance](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/ws-streams/~), [Coinbase](https://docs.cdp.coinbase.com/exchange/websocket-feed/channels), [Hyperliquid](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions).

Для Solana processed и provisional states допустимы как отдельные research views, но их evidence нельзя незаметно заменить finalized evidence. Для EVM removed logs отменяют ранее сделанные выводы. Между chains нет единого глобального slot: нужен вектор состояний и отдельная модель времени/финальности.

## Бесплатный старт и его границы

`data/unified_source_catalog.json` объединяет исходные 43 records с текущими профилями. Это 53 записей интерфейсов, не 53 независимо подключённых поставщиков. Старые записи без нового чтения отмечены как historical catalog evidence. Все новые live probes отсутствуют; `connected_count_added=0`.

| Источник | Слой | Проверенный access class / граница |
| --- | --- | --- |
| defillama | COLD | PUBLIC_LIMITED: Parent/child and routed-volume deduplication; not raw reserves |
| dexscreener | COLD | PUBLIC_RATE_LIMITED: Promotions and trending are not exact liquidity |
| geckoterminal | COLD | PLAN_AND_ENDPOINT_SPECIFIC: Guide redirect; verify exact endpoint family and quota |
| yellowstone-grpc | HOT | OPEN_SOURCE_HOSTING_REQUIRED: Persistent gaps/replay and fork ancestry must be qualified |
| helius-laserstream | HOT | PAID_MAINNET_OPTIONAL: No subscription purchased; validate available replay window |
| binance-spot | WARM | PUBLIC_WITH_LIMITS: Venue snapshot+sequence recovery; public data does not grant trading access |
| coinbase-exchange | WARM | PUBLIC_WITH_LIMITS: Absolute level replacement; account/region eligibility separate |
| hyperliquid | WARM | PUBLIC_WITH_LIMITS: Depth/precision cap; no certified full market depth |
| geth-pubsub | HOT | OWN_NODE_OR_PROVIDER: Reorg removals and getLogs backfill; RPC capacity not unlimited |
| sui-objects | HOT | OWN_NODE_OR_PROVIDER: Version+digest consistency and owned/shared resource classification |
| thegraph | COLD | PLAN_SPECIFIC: Query cost, index lag, block pin and subgraph revision |
| dune | COLD | KEY_AND_CREDITS: Metadata free does not mean all execution or export free |
| jito-market-structure | WARM | ACCESS_AND_INFRA_SPECIFIC: Docs are not a live signal; no submission endpoint is enabled |
| aave | HOT | RPC_REQUIRED: Cash, flags, premium, callback and chain revision |
| morpho-blue | HOT | RPC_REQUIRED: Shared contract cash must not be counted once per market |
| balancer | HOT | RPC_REQUIRED: Pin V3; old V2 examples are a different integration |
| uniswap-v3-flash | HOT | RPC_REQUIRED: Pool lock/callback and fees; source is not additional independent pool cash |
| kamino-klend | WARM | RPC_AND_REVISION_REQUIRED: Deployment and flash capacity unverified |
| project0 | COLD | INTEGRATION_UNQUALIFIED: Map Project 0 / mrgnLendv2 to actual programs before adapter reuse |

Практический бесплатный старт — разрешённые public discovery endpoints, bounded public market-data streams и offline replay. [DefiLlama](https://api-docs.defillama.com/) различает Free и Pro. [Helius LaserStream](https://www.helius.dev/docs/laserstream) требует платный mainnet plan; [Yellowstone](https://github.com/rpcpool/yellowstone-grpc) предоставляет software, эксплуатация требует ресурсов. [Dune](https://docs.dune.com/api-reference/overview/introduction) и [The Graph](https://thegraph.com/docs/en/subgraphs/providers/subgraph-studio/introduction/) имеют отдельные модели доступа/стоимости. Не обещать весь realtime рынок бесплатно.

У каждого endpoint нужны: source owner, terms/license revision, разрешённое хранение/перепродажа, rate/byte/credit quota, retention, stale/gap policy и fallback. Наличие бесплатного API не означает право перепродажи исторических данных. Недоступность источника отражается в coverage и UNKNOWN, а не компенсируется выдуманной котировкой.

## Быстрый fanout

Индекс зависимостей связывает market/account → affected relations → routes → cached evaluations. Update invalidates только затронутый подграф; reorg — все зависимые поколения. Coalescing допустим для очереди пересчёта последних состояний, если все промежуточные raw updates уже надёжно учтены. Нельзя выбрасывать orderbook deltas, liquidation events или corrections и продолжать считать состояние полным.

Кеш exact result включает amount, ordered route identity, state version vector, decoder/math revision, fees, token semantics и funding terms. Один result на pool или ticker — неверная гранулярность. CPU jobs используют immutable frames; решение о допуске повторно проверяет актуальность.

## UI «весь рынок на ладони»

Верхний экран — агрегаты и coverage по chain/product. Zoom открывает qualified markets, затем relations, exact capacity и resource conflicts. Каждый элемент показывает источник, available_at, depth coverage, evidence tier и причину UNKNOWN. Граф не рисует миллионы объектов одновременно: cluster/summarize/search, с точным drilldown и сохранённым фильтром. Это дизайн интерфейса, не развёрнутый dashboard.
