# VRC-03 — Какие расчёты выгодно проверять и покупать

**PLANNED_NOT_RUN.** Код не написан, experiment не запущен.

Зависимости: VRC-02. Связанные задания: WG-25.

## Гипотеза

Для дорогих задач отношение стоимости generation к verification может быть лучше, чем для простой quote.

## Переиспользовать

- `src/research/product.py`
- `src/research/pr359_wave15_institution.py`
- `src/mechanism_discovery/research_resources.py`
- `src/research/benchmarks.py`

## Дизайн эксперимента

1. Отдельно оценить decoder, fixed-route exact replay и bounded route search. Не аукционировать их как одну взаимозаменяемую homogeneous услугу.
2. У fixed-route result доказать feasibility; у search quality сравнить с exhaustive tiny-universe baseline при одинаковых caps. Не называть validity proof доказательством global optimality.
3. Сравнить full independent recomputation, restricted verification и cache reuse с указанным остаточным риском; sampled check не даёт полной correctness guarantee.
4. Подготовить спросовой эксперимент: внешний добровольный пользователь получает реальную полезность, выбирает повторное использование и готовность платить без субсидии. Только дизайн; никаких сообщений, платежей или набора участников сейчас.
5. Не добавлять token, staking, slashing, ZK network или rollup до доказательства bottleneck. Возможность изучить proof system остаётся условным следующим dossier.

## Измерения

- generation/verification cost ratio
- proof scope vs residual uncertainty
- repeat use without subsidy (not yet measured)
- willingness to pay (not yet measured)
- retention and gross margin hypothesis

## Когда продолжать

Выбрана услуга с проверяемым quality boundary и measured cost advantage; реальный спрос остаётся UNKNOWN до отдельного исследования.

## Когда остановить или изменить гипотезу

Synthetic utility или signed result не доказывает рыночную цену/спрос. При отсутствии преимущества продукт = internal service, не новый marketplace.

## Результат будущей работы

Service ranking, verification modes и demand-study protocol без fabricated observations.

Все outcomes сейчас NOT_RUN, demand UNKNOWN. Любой внешне наблюдаемый результат должен иметь scope/evidence; synthetic profiles не выдаются за реальных клиентов или providers.
