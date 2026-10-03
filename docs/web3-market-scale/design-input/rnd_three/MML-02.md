# MML-02 — Правила batch auction и allocation

**PLANNED_NOT_RUN.** Код не написан, experiment не запущен.

Зависимости: CLR-01, MML-01. Связанные задания: WG-17, WG-27.

## Гипотеза

Правило выбора compatible solutions влияет на fairness, fill и устойчивость к стратегическим bids.

## Переиспользовать

- `src/mechanism_discovery/intent_graph.py`
- `src/research/pr359_wave15_institution.py`
- `src/mechanism_discovery/research_quality.py`

## Дизайн эксперимента

1. Чётко разделить аукцион пользовательских intents и procurement auction вычислительной услуги; INST-01 policy не переносить механически на settlement.
2. На одинаковых batch/problem/budget сравнить baseline individual solutions, batched netting и fair selection с no-worse per-order constraint.
3. Указать deterministic tie-break, per-user limit/deadline, duplicate/conflict rules. No double fill/inventory consumption.
4. Проверить omission, bid splitting, delayed arrival, duplicate identity, known collusion scenarios и boundary budgets. Это finite robustness tests, не механизм с доказанной strategy-proofness.

## Измерения

- surplus by participant
- fill ratio
- worst-order degradation
- allocation stability
- strategic deviation gains within tested set
- compute cost

## Когда продолжать

No-worse guardrails и conservation соблюдены; advantage после costs устойчив в declared scenarios.

## Когда остановить или изменить гипотезу

Больший total surplus, купленный ухудшением отдельного order за пределами policy, отклоняется.

## Результат будущей работы

Allocation rule comparison с formal constraints и ограниченным набором deviation tests.

Все outcomes сейчас NOT_RUN, demand UNKNOWN. Любой внешне наблюдаемый результат должен иметь scope/evidence; synthetic profiles не выдаются за реальных клиентов или providers.
