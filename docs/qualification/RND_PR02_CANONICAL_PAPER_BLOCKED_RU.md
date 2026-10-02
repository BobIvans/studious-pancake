# RND-PR-02: установленная canonical paper-сборка — BLOCKED_EXTERNAL

Проверена чистая сборка `main` на
`b31fa445218900702c0d0c4202481488a259c6f8` в Python 3.13.15.
Результат — **BLOCKED_EXTERNAL**. Кампания не допущена и не запускалась.
Этот PR сохраняет реальные диагностические доказательства; runtime-патч отсутствует.

## Выбранный владелец

Использован уже merged FAST-Q1 v3 (#552):
`flashloan-checks -> src.automation_cli_pr189:main -> src.qualification_report`.
`flashloan-bot` остаётся `src.cli_pr189:main`.
Старые #545 и #547 закрыты без merge и заменены текущим владельцем.
Их diff проверен: это альтернативные инспекторы, которые нельзя добавлять
как второй execution owner. Открытый #553 расширяет FAST-Q orchestration;
этот PR добавляет только собственный каталог доказательств и данный документ.

Wheel построен через `python -m build --wheel --no-isolation` и установлен
не в editable-режиме. Вызовы console scripts выполнены из каталога вне checkout.
Все 856 Python-файлов `src/`, включённых в wheel, совпали с исходниками
зафиксированного checkout. Четыре файла CLI/инспектора дополнительно проверены
самим FAST-Q baseline; `dirty=false`, `installed_source_matches=true`.

## Что воспроизведено

Четыре offline preflight прошли: status, capabilities, config doctor и
runtime-admission. Единственный диагностический paper-shadow pass завершился
с `paper-shadow:blocked_missing_wallet_public_key` (child exit 5).
`inspect` вернул exit 0 с `ready=false` и domain `BLOCKED`:
это завершённая диагностика, а не успешная рыночная квалификация.

Дополнительная установленная команда `flashloan-checks paper-vertical inspect`
вернула `blocked_pr_a1_canonical_paper_vertical_unwired`.
В startup существующего paper-shadow владельца сохранён
`blocked_pr_a_canonical_vertical_unwired`.

| Обязательная поверхность | До | После |
| --- | --- | --- |
| atomic_stage_suite | missing | missing |
| exact_fee_workflow | missing | missing |
| verified_marginfi_provider | missing | missing |
| jupiter_v2_build | missing | missing |

`invalid_surfaces=[]`. Это не разрешение на исполнение: все четыре зависимости
отсутствуют. Конфигурационный fingerprint:
`2ad88c5b277fc0b63e7119df0669dde20c4d40dcc5aa658989948fb3e542b11e`.

## Почему runtime не изменён

Пакет RND-PR-02 требует менять только воспроизведённый пробел и прямо требует
`NEEDS_DATA / BLOCKED_EXTERNAL` при отсутствии внешних данных, конфигурации
или идентичности. Его campaign plan сам имеет статус
`NOT_EXECUTED_NEEDS_BINDINGS`. Он не предоставляет квалифицированный набор
market snapshots и проверенные runtime bindings.

Первый наблюдённый blocker — отсутствие публичной идентичности fee payer/wallet
в намеренно очищенном offline-профиле. Нельзя подставлять фиктивный адрес,
унаследованные credentials или тестовые зависимости для получения READY.
Отсутствие четырёх bindings сохранено как отдельный последующий блокер.
Тестовые doubles доказывают контракты, но не становятся runtime evidence.

MarginFi остаётся **PAUSED**. Историческое обязательное имя
`verified_marginfi_provider` не переименовано и не удовлетворяется созданием
live provider. Финансирование остаётся lender-neutral. Slumlord нужен только
при временной rent/ATA ликвидности и доказанной совместимости.

## Кампания и экономика

Плановые пределы сохранены: ≤900 секунд, ≤100 кандидатов, concurrency 1,
provider spend 0, live RPC calls 0. Кампания не стартовала:
considered=0, rejected=0, simulated=0, campaign duration=0.
Диагностический paper pass записал два существующих journal event;
он не считается запуском market campaign.

Provider requests=0, transactions_sent=0, signer_access=false.
Economic unit и modeled edge отсутствуют. Landing, fill и realized PnL —
`NOT_MEASURED`. Пустые данные не обозначены как прибыль или отрицательный edge.
Candidate rejections, unsigned simulation receipts и cost ledger не созданы:
ни один кандидат не был допущен. Это явно указано в `campaign_verdict.json`.

## Проверки и replay

72 существующих теста прошли с отключёнными сетевыми sockets:
FAST-Q, canonical startup, A1 preflight, type-safe composition, amount coupling,
PR-189 exits, exact fee, exact money/atomic evidence и journal/runner.
Также прошли существующие FAST-Q contract и installed-smoke verifiers.

Первый запуск тестов из родительского каталога дал два отказа из-за относительных
путей к исходникам. Повтор из repository root прошёл полностью; source-патч
для исправления пути не требовался.

Тот же установленный request ID и input digest переиспользовал квитанцию
(`reused=true`), не повторяя child steps. Все сохранённые артефакты проверены
по SHA-256. Incomplete/unknown outcome требует reconciliation до retry —
это покрыто существующими тестами. Полноценный crash/resume рыночной кампании
не заявляется, поскольку она не была допущена.

В detector подтверждены exact amount coupling, freshness и slot skew.
Он выставляет `final_requote_required_before_planning=true`; сам marker
не доказывает фактический end-to-end final requote на этом заблокированном пути.

## Доказательства и повтор

Артефакты: `release_artifacts/rnd_pr02/2026-10-02/`.
Начать с `receipt.json`, `campaign_verdict.json`, `acceptance_matrix.json`.
`installed-run/` содержит неизменённые baseline, manifest, raw stdout/stderr,
per-step records, qualification receipt и canonical paper journal.
Архивные абсолютные пути отражают среду исходного запуска; хеши файлов
сохраняются после копирования. `MANIFEST_SHA256.json` покрывает весь пакет.

Для воспроизведения используйте чистый checkout указанного tested SHA,
соберите/установите wheel и из каталога вне checkout вызовите:

```bash
flashloan-checks qualify-and-report inspect \
  --repo-root /absolute/clean/checkout \
  --output-root /absolute/outside/checkout/runs \
  --request-id rnd-pr02-new-probe \
  --expected-sha b31fa445218900702c0d0c4202481488a259c6f8 \
  --profile offline_sender_free --timeout-seconds 30
flashloan-checks paper-vertical inspect
```

Второй вызов инспекции vertical должен использовать тот же очищенный профиль
окружения, который задаёт `src.qualification_report._environment()`, с отключёнными
провайдерами и live. Исходный запуск обеих команд использовал именно этот профиль.
Повтор на новой сборке обязан указывать её реальный SHA и новый request ID.
Доказательства здесь относятся к tested SHA, а не к будущему merge commit.
Exact-head CI проверяется отдельно в PR metadata; квитанция не заявляет
успех CI, который ещё не наблюдался на момент её создания.

## Следующая одна задача

Предоставить и проверить один recorded sender-free evidence bundle:
публичную fee-payer identity (без private key), quote/state snapshots
с source/version/units/slot/available_at, lender/repayment и prefix liquidity,
exact fee/rent timeline и нужную compatibility proof. Затем связать его через
существующий canonical owner и повторить pinned startup. Только actual READY
позволяет допустить ограниченную кампанию. `production_ready=false`,
`live_enabled=false` остаются текущим результатом.
