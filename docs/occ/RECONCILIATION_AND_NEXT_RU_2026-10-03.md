# Сверка агрегаций и следующий шаг OCC

Срез: 3 октября 2026, Рига. Проверенные исходные версии:
Studious `4087d58104bc9cbb2cda56b7c951b35cc76235ab`,
OCC `23d14fa351e56c89b916c6853f955d562335e8f1`.
Это фиксированный аудит этих версий, а не автоматически обновляемый статус.

## Что уже вошло в код

| Область | Реализация / PR | Что действительно есть | Что этим не доказано |
| --- | --- | --- | --- |
| Studious контекст | #550, `src/mega_context_wave3.py` | Offline inventory, Python symbols/imports, бюджет, файловые chunks, staleness, policy/evidence primitives | Полный пользовательский OCC UI, семантическая проверка всего репозитория |
| Studious диагностика | #552, `src/qualification_report.py` | Установленный FAST-Q1, четыре preflight и ограниченный paper-shadow, receipts | Рыночная готовность или прибыль |
| Межрепозиторный мост | Studious #554 + OCC #34 | `qualification.inspect` → OCC adapter → Studious memory bridge → FAST-Q1; профиль связывает SHA и source refs | Доступ к произвольным действиям ПК |
| Studious durable host | #556, `src/occ_durable_library.py`, `scripts/run_occ_native_host.py` | Отдельная Studious библиотека и `qualification.audit` через существующий qualification task owner | Это не OCC Content Lab и не взаимозаменяемый FAST-Q1 endpoint |
| Studious FAST-Q loop | #558, `src/fast_q_automation.py` | Закрытый action registry, blocker/repair metadata, фиксированные проверки, receipt state | OCC intake/search/ASR исполняются только за внешней границей; схема инструмента сама не является handler |
| OCC intake/review | #35, `content-lab/occ_local.py`, `context_review.py` | Intake metadata и review versions в существующей `content.sqlite3`; import/list/get/create | Готовые review-кнопки, voice binding, criterion-specific closure |
| Arbitrage graph | #559, `docs/shadow_arbitrage_graph.md` | Ограниченные shadow-кандидаты 3/4-hop по точным наблюдениям | Полная карта рынков, orderbook feed, net-profit approval или execution |

Статус #550 в checked-in каталоге: 205 IMPLEMENTED и 58 BLOCKED из 263 строк.
Это классификация offline capabilities: строки каталога не равны 205
независимо проверенным пользовательским сценариям или 205 новым PR.
Историческая разница BASE Markdown=95 / JSON=94 сохраняется.

## Подтверждённые исправления этого изменения

1. `update_receipt_state` отклоняет action receipt другого source SHA и другого
   idempotency key. Старый TEST_PASSED не подтверждает текущий checkout.
2. Самосогласованный хеш не заменяет проверку структуры: сверяются result digest,
   status, запрет эффектов и фактически записанные argv/exit codes фиксированного
   validation set. Пустой список проверок не считается TEST_PASSED.
3. Дочерняя FAST-Q1 квитанция сверяется с текущими schema/action/profile,
   manifest input digest, request ID, SHA и receipt bytes; release/live flags
   должны быть false, transactions_sent — целым 0. Возвращённый результат
   должен совпасть с сохранённой квитанцией, кроме transport-флага reused.
4. Архивный трёхполевый `occ.qualification-action.v1` теперь проверяется
   каноническим memory-bridge intent validator и допускает только qualification.
   Современный четырёхполевый OCC запрос должен идти через memory bridge с
   отдельным operator profile; FAST-Q2 возвращает явный указатель на этот путь.
5. EXTERNAL_ADAPTER_REQUIRED больше не подтверждает `implemented`: наличие
   контракта intake/search/ASR не означает выполненную интеграцию или проверку.

Хеши проверяют целостность и привязку, а не независимую достоверность импортного
утверждения. Нового router/store/scheduler не добавлено.

## Граница владения для следующих PR

Для пользовательской контекстной библиотеки основной владелец — OCC
`content-lab/content_lab.py` + `automation_core.py` и существующая SQLite.
UI и Native Messaging используют текущие OCC adapters.
Studious остаётся владельцем торговых контрактов и доменной квалификации.
Не копировать Studious durable store в OCC и не синхронизировать две базы
как будто у них уже есть общий контракт миграции.

`qualification.audit` Studious host делегирует
`scripts/run_qualification_task.py` → `run_mpr2611_clean_qualification.run_repeated`.
`qualification.inspect` OCC делегирует
`agent-bridge/qualification_adapter.py` → `scripts/run_occ_memory_qualification.py`
→ `occ_memory_qualification_bridge` → FAST-Q1.
Эти действия имеют разные входы и evidence. Переключать одно на другое
переименованием action или схемы нельзя.

## Что внедрять дальше в BobIvans/scaling-chrome-extensions

Это порядок следующих изменений, а не уже созданные GitHub PR.

| Шаг | Конкретная поставка | Владелец, который переиспользуется | Приёмка |
| --- | --- | --- | --- |
| OCC-NEXT-01 | Review UI: список прошлых сессий, создание от выбранных источников, import JSON, карточка findings/coverage/stale и следующий запрос к Codex | `context_review.py`, Native `durable.review.*`, `library/durable-ui.mjs` | После перезапуска сессия доступна; identical import не дублирует; изменённый источник показывает STALE/NEEDS_CONTEXT; import не закрывает finding |
| OCC-NEXT-02 | Полный bounded repo inventory с resumable cursor и coverage ledger | `occ_local.py`; namespace/profile, существующая SQLite | Каждый eligible файл accounted: scanned/excluded/failed/pending; лимит 2000 не изображается как полный анализ; нет исполнения кода или чтения credentials |
| OCC-NEXT-03 | Repo chunker по symbols + import graph + SCC, с contract context и бюджетом; JS/TS явно supported либо UNSUPPORTED | Расширить repo intake; адаптировать проверенные primitives #550 без копии trading runtime | Interface/import dependencies сохраняются; oversized SCC явно reported; manifest связывает repo SHA + bytes + chunks; partial/parse errors видны |
| OCC-NEXT-04 | Incremental Git indexing и repo-aware stale invalidation | Тот же индекс и review ledger | Два SHA: additions/deletions/renames и dependent chunks; cached и cold index дают одинаковый coverage/hash; source drift не сохраняет VERIFIED |
| OCC-NEXT-05 | Findings board + независимый evidence verifier + PR handoff | Review ledger, GitHub CI snapshot owner | AST smells остаются candidates; закрытие только по criterion + exact SHA/receipt; экспорт owner/files/symbols/test command/blocker/next step, защита от повторного PR |
| OCC-NEXT-06 | Selected-chat capture и ask через текущий page/action owner; voice сначала создаёт preview плана | Текущий browser stack и durable attempts; re-audit открытых #31/#32 | Navigation drift/composer conflict блокируют send; unknown outcome после restart требует reconciliation; установленный Windows Chrome выдаёт transport receipt |
| OCC-NEXT-07 | Бounded автоматический цикл collect → context pack → review → imported result → next task | Существующие queue/scheduler/cancel; voice preview и Laya proposal | Один job ref, лимит попыток/времени, STOP, restart; model output не становится shell/merge/торговой authority |

Сейчас `occ_local.py` делает metadata scan и простые Python AST counts,
а не dependency-aware chunking всего codebase. `automation_core.context_pack`
собирает выбранные сохранённые источники; это не symbol/import graph.
OCC review ledger хранит optional base repo SHA как metadata, но сам не проверяет
Git checkout. Поэтому шаги 02–05 нужны до заявления «анализ всего репозитория».

Открытые OCC #25–#32 — стек draft-функций Laya/ASR/budget/providers/browser.
Открытый #33 — portable archive lineage. Перед продолжением смотреть diff
от текущего main и переиспользовать эквиваленты #35. Не merge всего стека
только потому, что отдельно прошли его исторические тесты.

## Внешние блокеры и границы результата

Последний checked-in Studious RND-PR-02 receipt:
`paper-shadow:blocked_missing_wallet_public_key`, BLOCKED_EXTERNAL,
`market_run_performed=false`, `transactions_sent=0`.
Это историческое evidence конкретного запуска; текущий runtime нужно повторно
проверить после операторской конфигурации. Адрес кошелька не подставляется
фиктивно, gate не отключается. Rooted protocol/deployment/provider receipts
и установленный Windows Chrome остаются внешними предпосылками.

Подключённый проект Supabase на момент аудита INACTIVE. В проверенных
контекстных компонентах canonical store — локальная SQLite; нет доказанного
runtime binding к этому Supabase project. Облачная sync — отдельная задача
после определения namespace/ownership/privacy/offline conflict contract.
В этом изменении БД не создавалась и не менялась.

Для следующего запроса: «Реализуй OCC-NEXT-01 на текущем main
BobIvans/scaling-chrome-extensions. Переиспользуй durable.review.* и SQLite,
добавь UI для review/create/import/list/get, coverage и STALE. Затем делай
OCC-NEXT-02/03: coverage-first inventory и dependency-aware repo chunker.
Каждый PR должен содержать diff текущих владельцев, exact SHA, tests и
явные непроверенные сценарии».
