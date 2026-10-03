# Текущий main и следующий bounded slice

На 2026-10-03 выполнен `git fetch origin main`. Проверенный ref: `67d3852cbc4cb1b24582df45adbf6a42d4da2af0`, tree `825db4ed329a66deff295b57636f9dff4965c9a9`. Локальная рабочая ветка и HEAD не менялись; чтение нового кода выполнено через `git show`. Working tree clean. Это targeted static review, не полный security audit и не новый запуск repository tests.

## Что появилось после предыдущего ZIP

[PR #562](https://github.com/BobIvans/studious-pancake/pull/562) находится в fetched main. Он добавил `src/direct_venue/cpmm_math.py`, `src/strategy/exact_cpmm_capacity.py`, tests и переиспользование primitive в SUPER03. PR559/561 graph/discovery owners сохранились.

Bridge строит integer output/state transition, повторно рассчитывает 3/4-hop legs для конкретной суммы, передаёт observations PR559 и sampled points в `evaluate_pr118_non_monotonic_sizing`. Test source включает nonlinear sizes, coupling, stale/repeated venue, identity и grid10/20/30. Эти tests в текущем R&D не запускались; наличие tests не помечено PASS.

Финансирование этой capacity slice ограничено SOL/WSOL; новых EVM/Sui adapters или verified market subscriptions данный diff не добавил. `OrderbookAmmStrategy` по-прежнему disabled с причиной ожидания verified market subscriptions.

## Конкретные статические ограничения перед масштабированием

1. **Proof boundary.** `QualifiedCpmmState` получает уже декодированные поля. Model/decoder revision strings и program label не заменяют проверку исходного account evidence, ownership и protocol parity. Fixture observation помечен `offline-state-fixture`/`fixture`.
2. **Asset binding.** `CapacityEconomics` допускает label SOL/WSOL, но нужен явный binding к реальному mint/token program/genesis/decimals settlement asset. Текстовое совпадение и fixture WSOL недостаточны для иных assets.
3. **Per-amount outcomes.** Route bridge требует допущенного nonnegative-gross PR559 candidate. Если amount даёт отсутствие такого candidate/zero output, evaluator бросает исключение; PR118 candidate_factory path не перехватывает его. Это статически выявленный риск прекращения всего sampled report, а не измеренный regression. Экономический reject конкретной суммы должен отличаться от повреждённого state.
4. **Fee/state parity.** Current transition прибавляет input к reserve. До reuse на protocol state нужна независимая проверка fee precision, protocol/fund-fee segregation и token transfer behavior. Простая integer CPMM-модель не доказывает все конфигурации Raydium.
5. **Shared state.** AGG05 уже решает finite split allocation/orders, но capacity map не является полным reserve/tick/bin/book/hook state. Доработка должна принадлежать ему и существующим evaluators.

Также сохраняются ранее найденные ограничения `14_SCALE_OWNERS_AND_GAPS_RU.md`: cash index range, completeness resource dimensions и отсутствие настоящего joint CVaR в named helper. Diff PR562 эти файлы не менял. Исправления здесь не выполнены.

## Следующий один PR, предлагаемый для будущей сессии

**DP-01: усилить qualification boundary и per-amount rejection в текущем CPMM capacity bridge.** Scope: только offline fixtures, один pinned model, existing PR118/PR559. Добавить строгий settlement identity mapping, различение unsupported state и ожидаемого economic reject, независимые vectors для поддержанного fee model. Неподдержанные режимы явно отклонять.

Обязательные будущие проверки: DT-01..03; существующие amount coupling/stale/slot/repeated-venue/identity checks должны сохраниться. Negative-net test текущего fixture не заменяет отдельный gross-negative/zero-output case. Unknown exception нельзя скрывать как обычную невыгодную сумму.

После этого отдельный bounded DP-02: 2 paths с одним shared pool, 8 exact amount points,оба порядка paths; AGG05 общий state extension и сравнение с single path. Он не входит автоматически в первый PR. Evidence всех невычисленных вариантов помечается budget-truncated, не optimum.

## Что не писать заново

- Integer/non-monotonic sizing: `src/economics/non_monotonic_sizing.py`.
- Integer CPMM: `src/direct_venue/cpmm_math.py`; SUPER03 uses same primitive.
- Exact route/capacity bridge: `src/strategy/exact_cpmm_capacity.py`.
- Bounded graph: `src/strategy/arbitrage_graph.py`; shortlist: `src/strategy/multihop_solver.py`.
- Joint split: `src/economics/split_flow.py`.
- Stream epochs/gaps/cursors: `src/market/streams.py`.
- Async reconciliation: `src/inventory/non_atomic.py`.
- Evidence service: `src/research/product.py`, `src/research/pr359_wave15_institution.py`.

Полный перечень прочитанных/привязанных owners с SHA и git blobs: `data/deep_web3_baseline_review.json`. Это snapshot основного дерева на указанном commit, не обещание, что main не изменится позже. Перед реализацией снова fetch/diff/AGENTS review.
