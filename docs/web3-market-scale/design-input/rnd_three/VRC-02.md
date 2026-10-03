# VRC-02 — Конкуренция поставщиков с полной ценой проверки

**PLANNED_NOT_RUN.** Код не написан, experiment не запущен.

Зависимости: VRC-01. Связанные задания: WG-25.

## Гипотеза

Конкуренция может улучшать delivered correctness/cost/deadline outcome относительно одного local provider.

## Переиспользовать

- `src/research/pr359_wave15_institution.py`
- `src/research/benchmarks.py`
- `src/research/product.py`

## Дизайн эксперимента

1. Local virtual providers на одном homogeneous task: быстрый дорогой, медленный дешёвый, ошибочный/просроченный. Их профили помечены simulated.
2. Сравнить local baseline, posted price и existing reverse-auction policies INST-01. Не считать finite bid enumeration общим proof incentive compatibility.
3. Сначала отсечь неверные/stale/late outputs, затем оценить money cost с verification/retries/transfer/compute. Seconds и currency не складывать без заранее объявленной valuation.
4. Latency измеряет caller monotonic clock; provider сам не заверяет собственную скорость. Equal-hardware algorithm benchmark и real heterogeneous infrastructure benchmark разделить.
5. Включить duplicate receipts, colluding identical outputs, provider dropout и shared upstream outage. Same source alias не новая независимая проверка.

## Измерения

- cost per correct timely result
- deadline hit rate
- p95 end-to-end latency
- verification/production cost ratio
- simulated buyer/supplier utility
- correlated failure rate

## Когда продолжать

Есть Pareto improvement по полной стоимости/latency при сохранении correctness; иначе single-provider baseline остаётся предпочтительным.

## Когда остановить или изменить гипотезу

Если network+verification уничтожают savings, pivot к cached corpus/managed API или более дорогой проверяемой задаче.

## Результат будущей работы

Procurement comparison report с failure cases и simulation-only demand labels.

Все outcomes сейчас NOT_RUN, demand UNKNOWN. Любой внешне наблюдаемый результат должен иметь scope/evidence; synthetic profiles не выдаются за реальных клиентов или providers.
