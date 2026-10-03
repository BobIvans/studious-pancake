# Актуальные owners и границы расширения

Повторный fetch origin/main: `67d3852cbc4cb1b24582df45adbf6a42d4da2af0`, tree `825db4ed329a66deff295b57636f9dff4965c9a9`. Main не изменился относительно предыдущей версии этого ZIP. Рабочая ветка не переключалась, repo code не изменён; repository tests в этом обновлении не запускались. Статический обзор дополнен существующими scheduler/durable/provider owners.

| Роль | Путь на main |
| --- | --- |
| sizing | src/economics/non_monotonic_sizing.py |
| graph | src/strategy/arbitrage_graph.py |
| exact | src/strategy/exact_cpmm_capacity.py |
| math | src/direct_venue/cpmm_math.py |
| split | src/economics/split_flow.py |
| scheduler | src/strategy/conflict_scheduler.py |
| footprint | src/routing/route_graph.py |
| streams | src/market/streams.py |
| ingest | src/strategy/market_graph_ingest.py |
| observations | src/market/observations.py |
| quota | src/provider_governance/authority.py |
| admission | src/provider_governance/scheduler.py |
| durable | src/durability/lifecycle.py |
| capital | src/economics/durable_reservations.py |
| authority_review | src/durability/mpr19_economic_authority.py |
| single_truth | src/durability/single_truth.py |
| allocation | src/research/pr356_allocation.py |
| quality | src/mechanism_discovery/research_quality.py |
| claims | src/mechanism_discovery/claims.py |
| raw | src/market_data_evolution/contracts.py |
| inventory | src/inventory/non_atomic.py |
| families | src/inventory/research.py |
| lending | src/lending/financing.py |
| evm_lending | src/multichain/evm_financing.py |
| liquidations | src/liquidation/agg07.py |
| primary | src/strategy_evolution/primary_market.py |
| orderbook | src/providers/orderbook/quote.py |
| strategy_gate | src/strategy/strategies.py |
| procurement | src/research/pr359_wave15_institution.py |
| service | src/research/product.py |
| benchmarks | src/research/benchmarks.py |
| causal | src/mechanism_discovery/causal_twin.py |

## Критические отличия между foundation и готовым runtime

- PR118 владеет integer/non-monotonic sizing. Текущая economics привязана к SOL/WSOL lamports; расширение на другие активы должно сохранять units, а не маскировать USDC как SOL.
- PR559 уже имеет typed graph/route identity и bounded deterministic 3/4-hop detection. Условия exact amount coupling, freshness/slot и repeated venue сохраняются.
- PR562 exact CPMM bridge использует decoded immutable state и canonical math. Qualification identifiers не являются сами по себе raw/deployed-code proof; identity/fee/parity и amount-local failure всё ещё требуют DP-01.
- AGG05 split_flow — existing owner для joint finite allocation. Capacity map не является полным состоянием AMM ticks/hooks; сначала DP-02 на двух paths.
- WorkResourceSet не представляет общий read-only account set. from_route_footprint копирует pools/writable_accounts; oracles в route footprint не превращаются автоматически в полную access-mode карту.
- ConflictAwareScheduler использует локальный RLock и active dict. Он не владеет capital/quota/lifecycle. Receipt generation checks и локальный WorkerFence не доказывают multi-host exclusive ownership.
- DurableLifecycleStore явно разрешает single-node topology и запрещает сетевой shared-file путь как substitute distributed fencing. DurableCapitalCoordinator уже связывает этот store с capital policy.
- MPR19 economic authority и single_truth содержат отдельные existing checkpoints. Документация описывает remaining cutover; перед новым bridge надо проследить фактический installed runtime path и выбрать одну truth authority. Нельзя автоматически объявить старый и новый store одновременно canonical.
- Scheduler expiry/reap относится к work admission. Для неизвестного будущего внешнего исхода нельзя освободить деньги только по TTL; это задача canonical lifecycle reconciliation.
- PR356 finite allocator и research_quality — исследовательские helpers. Полнота budget dimensions, строгие input types, joint tail scenarios и statistical controls требуют qualification; название функции не является доказательством свойства.
- Orderbook quote owner уже различает requested/consumed/residual и integer lot semantics. OrderbookAmmStrategy остаётся disabled до verified subscriptions.

## Изменения внешних документов

Актуальный [Balancer guide](https://docs.balancer.fi/concepts/vault/flash-loans.html) описывает V3. [marginfi docs](https://docs.marginfi.com/) теперь представляют Project 0 / mrgnLendv2. Старый GeckoTerminal guide перенаправляет к CoinGecko API. Эти изменения — причины перепроверить ABI/SDK/access, а не включить новые integrations автоматически.

Старые обзоры 01/14 относятся к их baseline. Раздел 21 остаётся точным обзором PR562. Этот раздел дополняет его областью параллелизма; ни одна старая DONE/PLANNED отметка не повышена без нового implementation evidence.

## Порядок следующей работы

1. Refresh main и прочитать применимые AGENTS/instructions перед кодом.
2. Найти фактические callsites владельцев, сопоставить изменения с этим обзором и пропустить уже завершённый scope.
3. Взять DP-01 как следующий exact qualification slice. Для parallel track после dependencies взять PM-08 offline resource footprints.
4. Повторно выполнить релевантные существующие tests в окружении репозитория. В этом ZIP их прохождение не заявлено.
5. Сохранить shadow-only результат и evidence; merge/deployment/live действия не следуют из этого handoff.

Blob IDs и SHA-256 32 связанных файлов сохранены в `data/parallel_owner_review.json`. Это fingerprint, не доказательство runtime qualification.
