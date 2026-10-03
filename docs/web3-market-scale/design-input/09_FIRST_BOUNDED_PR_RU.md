# Первый будущий bounded PR

> Обновление baseline 2026-10-03: PR562 уже добавлен в main; ниже сохранено историческое описание предыдущего baseline. Текущие owners и следующий slice: [21_CURRENT_MAIN_AND_NEXT_SLICE_RU.md](21_CURRENT_MAIN_AND_NEXT_SLICE_RU.md). Для09: не создавать дубликат уже имеющейся capacity slice.

**Предлагаемый scope:** exact amount/state adapter и sampled capacity evidence для одного pinned Solana CPMM, одного WSOL-settled 3-hop и одного4-hop synthetic/replay route. PR сейчас не создан. Это scoped subset WG-01/02/06/07/10/11/21/22, не завершение всех этих больших карточек.

## Входы

Текущий main и owner diff; immutable complete snapshot fixtures; program/model revision и token semantics; PR118 bounded amount grid; coherent observation batch; cost/repayment fixture evidence. Никаких новых сетевых подписок для этого первого offline slice.

## Изменения

- Тонкий exact evaluator adapter вызывает существующую закреплённую CPMM math, выводит consumed/residual/output/state evidence.
- Мост создаёт exact `MarketObservationV2` для конкретного amount и связывает результат с PR559 graph. Frozen quote на другую сумму не переиспользуется.
- Каждая PR118 сумма пересчитывает legs с гарантированным coupling. Full cost/financing fixture ledger использует существующий owner.
- Capacity report сохраняет points, reasons, route/evaluation identity и budget status. Если текущий ledger не может выразить семантику, добавить минимальную совместимую поправку в его owner; не писать второй optimizer.
- Existing PR559/561 regression coverage сохраняется. Новые tests доказывают cross-owner coupling, rounding/nonlinear sizes, cost identity и invalidation.

## За пределами этого diff

Новые live collectors, orderbook enable, CLMM/DLMM, EVM, arbitrary settlement assets, split-flow state extension, UI, financial hyperedges, transaction building/sending. Они остаются явными карточками backlog, а не скрытыми TODO, объявленными finished.

## Приёмка

Применимы T03–05, T14–15, T17–23, T32–40, T68–69, T71, T88. Для scenarios вне выбранного CPMM (например stable math) отразить not-in-slice, не имитировать покрытие. Вместо одного generic expected-output number используются независимые integer vectors и complete ordered evidence.

При amount10/20/30 с допустимым максимумом на20 bridge выбирает20 без monotonic pruning. Любой stale/slot/venue/identity mismatch отклоняется. Изменение quote amount/revision вызывает новый evaluation ID. После diff OrderbookAmmStrategy disabled, imports/startup/live config неизменны.

Merge-ready определяется действующими repo gates и фактическим review. Архив не даёт автоматической merge/live authority. Следующий bounded slice выбирается из blockers/measurements, а не из желания увеличить число PR.
