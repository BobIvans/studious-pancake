# Параллельность: расчёт, выбор и будущий lifecycle

Цель оптимизации — полезный экономический результат после расходов при соблюдении freshness и ресурсов. Максимальное число одновременно работающих workers — промежуточная метрика. Flashloan не устраняет общие account locks или конкуренцию за одну глубину.

## Три разных уровня

| Уровень | Что распараллеливается | Ограничение |
| --- | --- | --- |
| Data I/O | Независимые разрешённые feeds и bounded repairs | Общая квота и connection semantics |
| CPU research | Independent frames/routes/amount grids, independent replay folds | Memory, CPU, dependency invalidation и deadline |
| Предполагаемое исполнение | Только допустимые независимые resource sets; иначе последовательные волны | Protocol state, chain order, authority и капитал |

В Python CPU-bound tasks сначала измерять с process workers; asyncio помогает I/O, но не является доказательством ускорения exact integer math. Передавать jobs по immutable manifest IDs, избегая копирования всего рынка в каждый process. Offload/Rust/vectorization выбираются только после профиля. Approximate/GPU screening не подменяет integer final evaluation.

## Существующий владелец

`src/strategy/conflict_scheduler.py` уже содержит ConflictAwareScheduler, WorkResourceSet, WorkerFence и ReservationPort. Он проверяет pools, writable_accounts, economic_resources, fee_payer, nonce_or_object_ids и max_in_flight. Его active map и lock локальны процессу. Он получает reservations извне и не должен становиться новым ledger.

Планируемое расширение — полная карта read/write/access-mode, generation-bound identities и интеграция с выбранной canonical authority. Существующий route footprint содержит oracles отдельно; это не полный runtime read set. Все дополнительные аккаунты из qualified adapter/instruction behavior включаются до допуска. Неизвестный динамический hook или неполный footprint отклоняется.

## Модель конфликтов

Пусть Rᵢ/Wᵢ — физические read/write resources, Eᵢ — экономические требования. Пара несовместима в одной одновременной волне, если:

`Wᵢ ∩ (Wⱼ ∪ Rⱼ) ≠ ∅` или `Wⱼ ∩ Rᵢ ≠ ∅`, либо нарушается общий capacity/eligibility constraint.

R/R сам по себе не lock conflict. Resource identity включает chain/genesis, contract/account/object, revision и тип ресурса. Economic resources дополнительно включают общий lender token balance, virtual wallet balances, order nonce, margin account, fee budget и provider quota. Пара маршрутов может не делить pools и всё же использовать один reserve или payer.

[Jito](https://docs.jito.wtf/lowlatencytxnsend/) документирует read/write lock conflicts в auctions. В [Ethereum](https://ethereum.org/developers/docs/transactions/) nonce относится к аккаунту; несколько RPC workers не снимают его порядок. В [Sui](https://docs.sui.io/develop/sui-architecture/object-model) binding к object version/digest требует учитывать object dependencies. Конкретный chain runtime может обрабатывать независимые операции по-разному; одинаковый offchain scheduler не обещает одинаковый onchain throughput.

Добавление payer/accounts допустимо как отдельный будущий проект управления средствами, но само по себе не снимает pool/lender/margin bottleneck. Архив не создаёт wallets и не распределяет деньги.

## Выбор набора

Сначала отсеять stale, incomplete, unavailable и debt-unclosed candidates. Разбить оставшийся conflict graph на компоненты, учитывая также общие количественные бюджеты: раздельные компоненты locks всё равно связаны общим capital/data budget. Для маленьких наборов использовать существующий bounded PR356 allocator после unit/budget qualification; для больших — детерминированную heuristic с оценкой качества на небольших контрольных случаях.

Иллюстративная objective в одной валюте: сумма консервативных модельных net scores. В будущем вероятности landing и failure cost можно добавить только после калибровки на подходящих наблюдениях; неизвестная вероятность хранится как UNKNOWN. Нельзя суммировать SOL atoms и USDC atoms или выбирать по максимальному borrowed notional. Tail constraints требуют совместных сценариев, а не сложения независимых CVaR-подобных чисел.

## Проверяемый пример

`data/parallel_selection_fixture.json` содержит шесть вымышленных кандидатов и capacity max_selected=3. A конфликтует с B по pool и с C по reserve; C конфликтует с D. Все читают O, что не является конфликтом. Жадный выбор A,E,F даёт 18 условных единиц. B,C,E даёт 20. Если всем добавить общий writable payer, одновременно допустим только A с 9.

Арифметика этого fixture проверена при упаковке без импорта repository solver. Это не benchmark и не прибыль на реальном рынке. Для следующей волны необходимо заново оценить изменившееся состояние; складывать прибыли несовместимых путей из одного snapshot нельзя.

## Recovery и authority

Начальный масштаб — один host, одна canonical authority, много stateless compute workers. Работы получают idempotent identity, state generation, deadline и fencing token. Результат принимается лишь при действительном authoritative fence и том же допустимом state. Delivery может быть at-least-once; экономическое резервирование должно оставаться идемпотентным.

`src/durability/lifecycle.py` явно поддерживает только single-node SQLite. Нельзя выдать общий SQLite файл на NFS за distributed authority. Для remote workers нужен проверенный service boundary к одной logical authority; multi-host writer/sharding требует отдельной миграции existing owners и доказательства атомарности. Несколько локальных dict/RLock на разных hosts не дают общей защиты.

Монотонные timestamps разных процессов/hosts нельзя напрямую сравнивать. Authority задаёт lease generation и серверную expiry policy; worker deadlines переводятся в локальный бюджет с явными границами clock skew. Deadline возможности и lease ownership — разные вещи.

Pre-submission compute expiry может освободить только соответствующее допустимое резервирование. После неизвестного внешнего исхода будущий lifecycle обязан удерживать economic commitment до reconciliation. `reap_expired()` compute scheduler не является доказательством, что средства снова свободны.

## Где заканчивается этот пакет

Shadow jobs заканчиваются evidence и metrics. Будущее подключение существующего execution owner — отдельная работа с его approval/authorization contract. В ZIP нет такого подключения. Lender repayment не переносится между транзакциями только потому, что они находятся в одном bundle; bundle-level и lender-level условия различны.
