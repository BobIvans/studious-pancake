# CLR-01 — Clearing против отдельных обменов

**PLANNED_NOT_RUN.** Код не написан, experiment не запущен.

Зависимости: RD-00. Связанные задания: WG-17, WG-26.

## Гипотеза

Встречные требования могут уменьшать обращения к внешней ликвидности при сохранении user constraints.

## Переиспользовать

- `src/routing/route_graph.py`
- `src/strategy/multihop_solver.py`
- `src/mechanism_discovery/intent_graph.py`
- `src/mechanism_discovery/pr356_state_completion.py`

## Дизайн эксперимента

1. Одинаковые intents/state/fees и search budget. A: independent route evaluation на одном общем replay state; B: compatible netting + external routes только для unmatched residue.
2. Не считать independent baseline так, будто каждый order исполняется на исходном нетронутом pool. Зафиксировать order или сравнить одинаковый bounded set orderings.
3. Задать strict per-user quantity/limit/deadline/partial-fill constraints и baseline no-worse outcome. Не разрешать ухудшить одного участника ради total surplus.
4. Сравнение при одинаковом выполненном объёме; если объём разный — отдельная Pareto таблица fill/quality/cost, не ложная savings percentage.
5. Neutral controls: нет встречных orders; all intents same direction; expired intent; shared pool across router sources.

## Измерения

- external swaps count
- filled quantities by intent
- per-user surplus vector
- fees and data/compute cost
- gross vs conservative net
- search budget exhausted

## Когда продолжать

На held-out declared episodes есть положительное улучшение после costs при нуле нарушений user/conservation constraints; sample size/uncertainty указаны.

## Когда остановить или изменить гипотезу

Если экономия исчезает после fair shared-state baseline — оставить negative result и не продавать netting advantage.

## Результат будущей работы

A/B clearing dossier с per-intent outcomes, resource trace и причинами неудач.

Все outcomes сейчас NOT_RUN, demand UNKNOWN. Любой внешне наблюдаемый результат должен иметь scope/evidence; synthetic profiles не выдаются за реальных клиентов или providers.
