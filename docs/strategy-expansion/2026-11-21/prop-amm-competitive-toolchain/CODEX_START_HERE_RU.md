# Prop AMM Competitive Toolchain — точка входа для Codex

**Дата аудита источников:** 2026-11-21  
**Целевая среда:** Solana, flashloan bot, sender-free shadow/paper до отдельной авторизации  
**Статус пакета:** стратегия и реализационный контракт; не production-интеграция и не разрешение на live execution.

## Цель

Собрать проверяемый стек для конкуренции за реальные, исполнимые возможности против Prop AMM: раннее наблюдение за изменениями состояния, быстрая нормализация событий, аномалия как приоритет анализа, точная amount-specific оценка, сравнение прямых инструкций с Jupiter V2, полная атомарная flashloan-экономика и измеренная доставка.

Главный принцип: **конкурентное преимущество должно происходить из качества данных, корректности state/quote math, скорости валидного построения и управления риском — не из сокрытия назначения потока или обхода анти-abuse систем маркет-мейкера.**

## Репозиторий и зависимости

- Работать additive-only в новой ветке от актуального main.
- PR #664 — отдельный общий source-universe / CAPTURE_ONLY campaign pack. Этот пакет не дублирует его source catalog, campaign start gate или общий relay cost dossier; он ссылается на них.
- PR #660 владеет Raydium CLMM / Meteora DLMM exact-state qualification; не переписывать их account decoders или quote math.
- PR #659 уже владеет CPMM atomic exact route path.
- Сохранять R13 quote normalization, текущий MarketObservation / route graph, R02 FlashCapitalGraph, R03 unsigned builders, PR118 sizing, ConflictScheduler / resource reservation, canonical paper-shadow runtime и MPR-05.
- Не добавлять второй graph, quote kernel, scheduler, parser pipeline, source registry, journal, capital graph, sender runtime либо discovery engine.
- Текущий корневой README прямо говорит, что production end-to-end bot/live execution ещё недоступны; этот пакет не меняет этот статус.

## Архитектурная схема

1. **Sight / source feeds:** LocalShred Lite как бесплатный кандидат для теста; Yellowstone/Geyser gRPC и UDP shreds от независимых провайдеров — отдельные режимы наблюдения. DoubleZero, OrbitFlare, Triton, Helius LaserStream, GetBlock, ValidatorsDAO/ERPC — по подтверждённым планам и результатам собственного A/B. Источник не становится «раньше» только потому, что он UDP: измерять полезную задержку до корректного state, потери, reordering, slot/fork и replay.
2. **Detection / parsing:** переиспользовать текущий source governance и canonical market observations. 0xfnzero/sol-parser-sdk — возможный parser adapter после dependency compatibility и benchmark. KADES/CADES и Capture OS — только optional external signal leads, пока нет проверенной публичной API/репозитория/контракта. solana-arb-executor — code-generation skill reference, не runtime dependency.
3. **Microscope / simulation:** LimeChain/pmm-sim как изолированный offline differential harness для direct/single/multi/benchmark сценариев на pinned current account snapshots. LiteSVM и Mollusk — тестовые SVM harnesses; Pinocchio — низкоуровневая on-chain program library только после измеренного CU/binary bottleneck.
4. **Router / builders:** Jupiter Swap API V2 для benchmark quote/order и /build raw instructions; 1000xsh/swaps как прямой instruction builder (не quote engine). Сверять точный input, output mint, token program/extensions, pool/program identity, state slot, fees, slippage floor, accounts, CU и final balance guard.
5. **Delivery:** канонический путь из docs/pr130_jito_mev_policy.md остаётся первым разрешённым дизайном: одна стратегия-транзакция через JITO_SINGLE/sendTransaction, один tip в той же транзакции, без standalone tip tx и без multi-tx bundle на первой production-полосе. Helius/Astralane/Syncro — кандидаты для отдельной sender qualification. Никакой all-relay fan-out и никакого предположения «платим только победителю». Внутренний multipath одного поставщика (Helius Sender Max, Syncro, bloXroute) — отдельная функция самого сервиса.
6. **Atomic flashloan:** borrow → all swap legs → repayment → post-balance/economic invariants внутри того же атомарного transaction plan; builder обязуется доказать repayment coverage. Маршрутный split допускается лишь по измеренной ликвидности/impact и только если весь набор legs остаётся атомарным.

## Важные корректировки исходного pasted text

- Jito официально объявил остановку ShredStream с 5 сентября 2026. Это не означает закрытие Jito Block Engine / transaction delivery; feed и sender — разные продукты.
- LocalShred Lite рекламируется как бесплатный вариант уровня прежнего Jito ShredStream. Не переносить на Lite скорость платного LocalShred bare-metal/его географическое преимущество и не использовать непроверенные «100–500 ms раньше».
- DoubleZero: актуальная опубликованная цена дифференцирована по metro и seat/month (около $450–$1,500), а не $30–$100 за устройство за эпоху. Условия тестового доступа проверять отдельно письменно.
- OrbitFlare: публичная страница показывает $500/$1,000 за месяц по регионам; 60-минутный trial из pasted text не подтверждён.
- Helius Sender 0.000005 SOL — SWQoS-only best-effort tier, не эквивалент Sender Max; Sender Max начинается с 0.001 SOL.
- pmm-sim подтверждён как реальный проект с single/multi/direct/benchmark; локальная симуляция не доказывает live fill.
- 1000xsh/swaps строит инструкции, не вычисляет quote/slippage. В notes описаны venue-specific caveats; HumidiFi min_amount_out игнорируется.
- Jupiter Quote API wording устарел/упрощён: этот пакет использует current Swap API V2 semantics и точно фиксирует версию endpoint.
- Параллельная отправка одной подписи может избежать повторного on-chain исполнения при дубликате, но не доказывает, что billing/tips/rebates у разных vendors взымаются только у победителя. Если меняется tip instruction, меняется signed message/signature и появляются несколько исполнимых вариантов.
- KADES/CADES, Capture OS, Supanode, Sanctum Gateway, BoltTx, Nozomi — не включать как готовые runtime adapters без canonical docs, endpoint contract, license/terms, current pricing и тестовых подтверждений.

## Необходимая последовательность реализации

См. PMM_SIM_CALLER_PROFILE_RESEARCH_RU.md, RELAY_PROVIDER_TIP_PROFILES_V1.json и IMPLEMENTATION_DAG_AND_ACCEPTANCE_RU.md. Сначала read-only источник и evidence, затем parser, simulation harness, direct builder + Jupiter differential, и только затем отдельная submission qualification. Этот pack сам по себе не включает платные endpoints, не создаёт аккаунты, не хранит credentials, не подписывает, не отправляет и не занимает flashloan.

## Hard stops

- Запрещено production impersonation aggregator identity и spoofed CPI caller. Разрешено только локальное LiteSVM исследование caller-dependent pricing через pmm-sim synthetic profiles Jupiter/DFlow/OKX/Titan на одном frozen snapshot; результаты не являются реальными aggregator routes и не дают права использовать чужой program ID в mainnet.
- Запрещены sandwich/front-running, victim targeting, unauthorized private order flow.
- Split только для price-impact/capacity/reservation correctness; никаких «рассыпных» non-atomic транзакций с заёмным капиталом без отдельной доказанной модели риска.
- Fixture/replay не считать live market evidence.
- Ни ACK, ни bundle id, ни simulated inclusion не являются settlement.
- При неизвестных fees/costs/state freshness/owner/program id ответ — BLOCKED/UNKNOWN, не zero.
- Не трогать PR130, MPR04, R02/R03/R05/R06/QPR, CAMPAIGN_START_V1, PR118 и MPR05 safety gates.

## Definition of done пакета

- В SOURCE_AUDIT_V1.json каждый источник имеет evidence status, URL, ограничения и рекомендованное применение.
- Для каждого потенциального adapter есть owner reuse и тестовые gates.
- Никакой новый parallel runtime / provider activation / send path.
- Все proposed paths сначала shadow/replay, с exact hashes and negative evidence.
- Отдельный reviewer принимает совместимость crate versions, license, program IDs и account layout до merge.
