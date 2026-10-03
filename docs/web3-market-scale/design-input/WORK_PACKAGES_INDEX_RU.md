# 28 пакетов будущих работ

WG-02/06/07/10/11 частично представлены PR562; remaining scope остаётся planned. Остальные карточки описывают будущий объём поверх уже имеющихся owners. Dependencies относятся к полному результату. Старый09 slice — история; текущий следующий шаг описан в [21_CURRENT_MAIN_AND_NEXT_SLICE_RU.md](21_CURRENT_MAIN_AND_NEXT_SLICE_RU.md).

| ID | Задание | Этап | Зависимости | Карточка |
| --- | --- | --- | --- | --- |
| WG-01 | Повторная сверка main и карта владельцев | A | — | [Открыть](work_packages/WG-01.md) |
| WG-02 | Идентичность активов, прав, рынков и доказательств | A | WG-01 | [Открыть](work_packages/WG-02.md) |
| WG-03 | Каталог бесплатного доступа и доказанное покрытие | A | WG-01 | [Открыть](work_packages/WG-03.md) |
| WG-04 | Governed read-only discovery и подписки | A | WG-03 | [Открыть](work_packages/WG-04.md) |
| WG-05 | Согласованный локальный state engine | A | WG-02, WG-04 | [Открыть](work_packages/WG-05.md) |
| WG-06 | Контракт точного edge evaluation | B | WG-02 | [Открыть](work_packages/WG-06.md) |
| WG-07 | Квалификация CPMM и stable pool математики | B | WG-06 | [Открыть](work_packages/WG-07.md) |
| WG-08 | Квалификация CLMM и DLMM | B | WG-05, WG-06 | [Открыть](work_packages/WG-08.md) |
| WG-09 | Проверенные orderbook subscriptions и depth adapters | B | WG-04, WG-05, WG-06 | [Открыть](work_packages/WG-09.md) |
| WG-10 | Полная экономика и financing evidence | B | WG-02, WG-06 | [Открыть](work_packages/WG-10.md) |
| WG-11 | Capacity curves и детерминированный circular search | B | WG-06, WG-07, WG-10 | [Открыть](work_packages/WG-11.md) |
| WG-12 | Интеграция существующего split-flow | C | WG-08, WG-10, WG-11 | [Открыть](work_packages/WG-12.md) |
| WG-13 | Stable/correlated market pack | C | WG-07, WG-10, WG-11 | [Открыть](work_packages/WG-13.md) |
| WG-14 | DEX ↔ wrapper / mint / redeem | C | WG-02, WG-06, WG-10, WG-11 | [Открыть](work_packages/WG-14.md) |
| WG-15 | Ликвидации + collateral unwind | C | WG-05, WG-10, WG-11 | [Открыть](work_packages/WG-15.md) |
| WG-16 | PT/YT и финансовые hyperedges | D | WG-02, WG-06, WG-10, WG-18 | [Открыть](work_packages/WG-16.md) |
| WG-17 | Intent / batch solver | D | WG-02, WG-10, WG-12, WG-18 | [Открыть](work_packages/WG-17.md) |
| WG-18 | EVM и последующие settlement domains | D | WG-02, WG-03, WG-05, WG-06, WG-10 | [Открыть](work_packages/WG-18.md) |
| WG-19 | CEX и derivatives market data | D | WG-03, WG-04, WG-05, WG-22 | [Открыть](work_packages/WG-19.md) |
| WG-20 | Cross-chain, CEX–DEX, spot–perp basis | D | WG-14, WG-18, WG-19, WG-21 | [Открыть](work_packages/WG-20.md) |
| WG-21 | Replay corpus и квалификация стратегий | A | WG-01, WG-02 | [Открыть](work_packages/WG-21.md) |
| WG-22 | Trace, покрытие и стоимость данных/вычислений | A | WG-02, WG-03 | [Открыть](work_packages/WG-22.md) |
| WG-23 | Интерфейс market-of-markets graph | C | WG-02, WG-11, WG-22 | [Открыть](work_packages/WG-23.md) |
| WG-24 | Масштабирование и непрерывное улучшение | E | WG-05, WG-11, WG-12, WG-21, WG-22 | [Открыть](work_packages/WG-24.md) |
| WG-25 | Рынок проверяемых расчётов и данных | E | WG-21, WG-22 | [Открыть](work_packages/WG-25.md) |
| WG-26 | Общий clearing solver как продукт | E | WG-12, WG-16, WG-17, WG-25 | [Открыть](work_packages/WG-26.md) |
| WG-27 | Market mechanism lab и критерии L1/L2/L3 | E | WG-21, WG-25, WG-26 | [Открыть](work_packages/WG-27.md) |
| WG-28 | Поэтапная shadow release qualification | E | WG-09, WG-13, WG-14, WG-15, WG-16, WG-17, WG-20, WG-23, WG-24, WG-25, WG-26, WG-27 | [Открыть](work_packages/WG-28.md) |
