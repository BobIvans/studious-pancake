# Existing owners и конкретные ограничения

Targeted static review baseline main72ae95fd; не полный аудит и не новый запуск tests. Код не исправлялся. Ни одна карточка не должна создавать параллельный solver или ledger для того, что уже имеет владельца.

| Файл | Область | Результат чтения |
| --- | --- | --- |
| src/inventory/non_atomic.py | AGG-13 durable reconciliation | Idempotent receipts/partial fills/unknown exposure across restart. Не sender. |
| src/inventory/research.py | Non-atomic families and qualification | Funding/basis/options/complete sets/RWA/commodity families уже перечислены. Право trade не выводится из read-only данных. |
| src/research/pr356_allocation.py | Shared resource research portfolio | Exact subset search≤18 candidates. solve_cvar_constrained_allocation вызывает общий solver и суммирует supplied tail_loss_units; это не вычисление CVaR совместного loss distribution. Unknown resource key отсутствует в loop budget, поэтому qualification должна доказать полноту budget dimensions. |
| src/research/pr356_ecology.py | Synthetic competitive ecology | Crowding/competition/half-life research owner; его output synthetic, не observed market advantage. |
| src/mechanism_discovery/boros.py | Rate cashflow fixture vertical | Детерминированные fixtures, не подключение Boros и не исполнимая hedge position. |
| src/mechanism_discovery/rwa.py | RWA access/custody/NAV lifecycle | Owner уже есть; actual issuer rights и доступ требуют отдельного evidence. |
| src/mechanism_discovery/programmable_cash.py | Cash identity/claims/redemption | В model_earning_and_claim_modes index_ppm ограничен require_ppm≤1e6, а claim считает max(index-1e6,0): для принятых значений claim всегда0. Проверить intended units и исправлять у этого owner до reuse growth-index semantics; сейчас код не менялся. |
| src/mechanism_discovery/research_resources.py | Research service economy | Mock/testnet/zero-cost boundary; real purchases этим R&D не включаются. |
| src/strategy_evolution/blockspace_option.py | Inclusion/settlement timing research | Claim о guarantee требует enforceable terms; historical calibration не future inclusion promise. |
| src/external_resources/engine.py | Existing remote mutation owner | Обнаружен apply_plan с remote mutation capability. Он не входит в proposed read-only R&D path; schema/catalog discovery не вызывает apply_plan. |

## Что проверить перед portfolio-scale

- Strict integer/unit validation до int coercion: bool/float/numeric text не скрывают ошибку units.
- Все consumed resource dimensions входят в явный budget; unknown key не получает implicit unlimited capacity.
- Сценарии учитывают общий issuer/custodian/oracle/chain/provider risk. Суммирование заявленных tail-loss values не заменяет распределение совместных потерь.
- Сохранять конечные exact evaluated sizes. Scale policy не превращает confidence/risk coefficients в разрешение линейно масштабировать quote.
- Pending cashflow/claim не становится доступным collateral, пока его права и сроки не допускают это.

Эти проверки относятся к будущим bounded owner changes. В этом архиве исправления не выполнены, найденные ограничения не превращены в pass. Файл служит точной точкой продолжения работы.
