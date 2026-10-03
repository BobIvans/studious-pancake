# CLR-03 — Преобразования прав поверх clearing

**PLANNED_NOT_RUN.** Код не написан, experiment не запущен.

Зависимости: CLR-02. Связанные задания: WG-14, WG-16, WG-26.

## Гипотеза

Одна проверенная mint/redeem/wrapper transformation иногда дешевле последовательности spot swaps.

## Переиспользовать

- `src/mechanism_discovery/claims.py`
- `src/strategy_evolution/primary_market.py`
- `src/economics/split_flow.py`

## Дизайн эксперимента

1. Добавить одну pinned immediate conversion с точными fees/caps/rights; сначала wrapper, composite PT/YT позже при qualified EVM profile.
2. A: clearing spot-only; B: clearing+conversion. Один и тот же исходный state и outcomes; проверить input/output vectors и capacity changes.
3. Asynchronous redemption только separate scenario, не допустимая нога atomic funding. Rights hashes, maturity и eligibility входят в result identity.
4. Ablation: убрать новую transformation; посчитать marginal gain и дополнительную data/verification cost.

## Измерения

- marginal net improvement
- removed swaps
- peak funding
- rights/obligation failures
- additional model/data cost

## Когда продолжать

Сохранение прав и конечных обязательств плюс positive incremental after-cost improvement на declared corpus.

## Когда остановить или изменить гипотезу

Если выгода требует предположить мгновенный unstaking или объединить разные maturities — invalid hypothesis.

## Результат будущей работы

Один воспроизводимый transformation recipe и отрицательные controls; без обещания поддержать любой financial product.

Все outcomes сейчас NOT_RUN, demand UNKNOWN. Любой внешне наблюдаемый результат должен иметь scope/evidence; synthetic profiles не выдаются за реальных клиентов или providers.
