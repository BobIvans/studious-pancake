# VRC-01 — Первая полезная проверяемая услуга

**PLANNED_NOT_RUN.** Код не написан, experiment не запущен.

Зависимости: RD-00. Связанные задания: WG-25.

## Гипотеза

INST-01 можно расширить с sum-int-v1 на точное вычисление с реальной полезностью для графа.

## Переиспользовать

- `src/research/pr359_wave15_institution.py`
- `src/research/product.py`
- `src/research/benchmarks.py`
- `src/ingest/amm_math_dispatcher.py`

## Дизайн эксперимента

1. Выбрать ровно один service kind: exact quote для pinned CPMM на immutable validated state и конкретном input; decoding и simulation — отдельные следующие service kinds.
2. Task binding включает state/model/fee/token revisions, amount/direction, output schema, deadline и resource cap.
3. Существующий calculator против независимых pinned protocol vectors/implementation. Hash и два экземпляра одного кода не считаются независимым oracle.
4. Развести CORRECT_FOR_DECLARED_STATE, FRESH_ENOUGH, AUTHENTIC_SOURCE и OPTIMAL_WITHIN_UNIVERSE. Correct computation на stale state не свежая quote; valid route не proof optimal route.
5. Корпус ошибок:1atom rounding, wrong fee, wrong amount, substituted state, copied receipt, late result, corrupted payload.

## Измерения

- exact correctness
- false accept/reject by corruption type
- freshness
- verification cost
- end-to-end latency
- state/task binding coverage

## Когда продолжать

Все заведомо неверные golden/adversarial cases отклонены; корректные результаты exact; scope proof явно ограничен corpus/model.

## Когда остановить или изменить гипотезу

Если проверка стоит столько же или больше локального вычисления, торговый marketplace этой услуги пока не оправдан; использовать как reproducibility API.

## Результат будущей работы

Qualified service contract и verifier dossier; no provider registration/payment/network marketplace.

Все outcomes сейчас NOT_RUN, demand UNKNOWN. Любой внешне наблюдаемый результат должен иметь scope/evidence; synthetic profiles не выдаются за реальных клиентов или providers.
