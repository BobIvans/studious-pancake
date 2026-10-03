# Исполнение Web3 future-work ZIP

Design input: `studious-pancake-web3-future-work-plan.zip`, SHA256
`8a0799c35f0404f8fd5290418db2abd01e9ce31ef054f52a090e1aa7c331138d`.
Сверен с main `67d3852cbc4cb1b24582df45adbf6a42d4da2af0`.
В `design-input/` сохранены все 170 исходных файлов без изменения их статусов.

Это реализация bounded offline/shadow foundations из архива. **Весь ZIP ещё
не закрыт по acceptance**: полный corpus из 189 сценариев не заменён числом
unit tests, а новые protocol adapters и forward data campaigns не объявлены
реализованными по наличию каталога. Точное покрытие и оставшийся scope находятся
в `execution_matrix.json`. Live authorization, sender, signer, transaction
submission, payments и enabling orderbook strategy не добавлены.

## Что реализовано

- PR118 остаётся владельцем integer/non-monotonic sizing. Expected amount-local
  rejection учитывается в общем budget и не прекращает остальные точки.
  Повреждённое состояние/неожиданная ошибка не маскируется как экономический reject.
- CPMM qualification проверяет genesis, SPL program, canonical mint и WSOL decimals.
  Semantic route identity включает промежуточные asset revisions; reserves и amount
  остаются частью evaluation identity. Все snapshots проверяются до sizing.
- Два CPMM пути используют immutable общий reserve vector и существующий
  `solve_joint_split_flow`. Проверены оба порядка, conflicting aliases и независимый
  finite integer oracle. Добавлен accounting protocol/fund/creator fees по pinned
  upstream source, input/output creator-fee direction, arbitrary integer ppm и
  сохранение fee counters в shared fork. `raydium_math_review.json` хранит revision
  и hashes первичных файлов. Deployment bytecode/raw-account conformance требуют
  отдельной квалификации; source math review не выдаётся за deployed proof.
- PR559 detector получил affected-neighborhood recomputation, сохраняя
  completeness/generation исходного batch. Caller обязан retract старые кандидаты
  затронутых или удалённых venues; здесь нет hidden cache с устаревшими результатами.
- `RecoverableStreamJournal` хранит raw envelopes/snapshots/deltas/retractions
  атомарно в одном local data store. Gap/fork требует repair snapshot. Restart
  восстанавливает state из evidence, а не cursor. Ограничены payload, record count
  и logical stored payload bytes. Absolute-level book owner применяет 7→3 как replacement,
  zero как deletion и блокирует frame после sequence gap до resync. Это не
  conformance реальной orderbook subscription.
- Stock/flow observatory отделяет TVL/stock от flow, underlying от routed aggregate,
  считает события один раз, применяет corrections по availability и сохраняет
  UNKNOWN при конфликте, отсутствии данных или несогласованном coverage.
- Claims owner получил versioned vector conversion/hyperedge с access, capacity,
  expiry, availability и delayed-settlement predicates. Empirical correlation
  не даёт права преобразовать активы.
- Scheduler различает R/R и R/W. Ресурсные claims и terminals используют существующую
  PR02 SQLite authority: два connections/threads не могут получить общий ресурс.
  Worker death не освобождает удержанный claim без reconciliation. Это single-node
  authority, без distributed ownership и без нового capital/quota ledger.
- Process workers 1/2/4/8 выполняют только immutable local replay. Queue bounded,
  deadline прекращает batch, исправленный frame отклоняет старый результат.
- Existing PR356 allocator получает conflict pairs и полный resource budget.
  Неизвестная dimension, float/bool, duplicate identity и forged proposal запрещены.
  Joint empirical CVaR считается по общим equal-weight scenario loss vectors с
  conservative integer rounding; legacy additive tail proxy не выдается за joint CVaR.
- Financing arithmetic считает fee/rounding и закрывает debt отдельно по каждому
  asset identity. Native wallet costs нельзя оплатить незакрытым долгом другого актива.
- Research protocol добавляет precommit, purged holdout, latency usability, null
  comparator и Bonferroni family control. P-values являются supplied evidence;
  код не создаёт доказательство доходности из synthetic sample.
- MM experiment использует AGG13 inventory ledger, synthetic FIFO queue, arrival,
  cancel acknowledgement, adverse markout, fees и hedge cost. Resting flash financing
  отвергается; модель не является подтверждённой venue fill model.
- Три продукта получили offline slices: finite opposing-intent clearing по
  per-user limits и conservation; independently verified route-calculation offers
  с existing Wave15 supplier allocation и полной verification cost; finite mechanism
  experiment с elastic participation, subsidy removal и existing strategic deviations.
- Installed source inventory содержит 53 records. Десять новых interface records
  UNVERIFIED, connectors не включены. Archived primary pages — evidence для R&D,
  а не доказательство subscriptions, лицензии на redistribution или unlimited free API.
- Read-only HTML показывает каждый exact leg, amount, asset identity и evidence hash.

## Как воспроизвести

После установки проекта и его pinned dependencies, Python 3.13:

```sh
python -m src.paper_shadow.market_scale_replay \
  tests/fixtures/market_scale_replay.json \
  --authority-db /tmp/market-scale-authority.sqlite3 \
  --output /tmp/market-scale-report.json \
  --html-review /tmp/market-scale-review.html \
  --workers 4
```

Fixture synthetic; output имеет `MODEL_REPLAY_ONLY`, `connected_feeds: 0`,
`verified_subscriptions: 0`, `execution_right: false`. Вход, authority и артефакты
должны иметь разные paths. Неожиданная ошибка оставляет durable claims удержанными
для reconciliation. Новая конфигурация/release требует подходящего authority identity;
нельзя менять старый authority manifest, чтобы обойти lease/policy mismatch.

Required local verification:

```sh
python scripts/verify_repo.py --skip-dependency-audit
```

Флаг пропускает online vulnerability audit. Остальные repository gates, build,
package smoke, mypy, format/security checks и configured tests выполняются.
Одна configured test deselection не считается passed case.

## Что остаётся

1. Реальная qualification protocol math/fee accounting по pinned deployed revisions,
   rooted raw vectors, coherent account versions и independently reviewed decoders.
2. Verified read-only subscriptions, source rights/entitlements, реальный depth/reorg
   corpus и end-to-end journal-to-buffer publication wiring для каждого feed schema.
3. Полные adapter packs stable/CLMM/DLMM, wrappers/claims, liquidations, PT/YT,
   heterogeneous intents, EVM и derivatives. Existing owners переиспользуются,
   но наличие их contracts/tests не закрывает каждый WG acceptance.
4. Полные read/write/economic footprints и один authority bridge для capital/quota
   admission на production path. Shadow claims этого PR не резервируют настоящие деньги.
5. Traces/campaigns DP/PS, cost/latency/coverage measurements и новый domain dossier
   с положенным forward-shadow corpus. Offline determinism не измеряет live p99.
6. Procurement demand, независимые реальные suppliers, audits и strategic market
   response. Synthetic subsidy-removal test не устанавливает рыночный спрос.
7. Mapping и исполнение всех 189 ZIP acceptance scenarios; числовое сравнение общего
   pytest count с 189 не является такой mapping.

Merge, live deployment и экономическая qualification этим изменением не объявляются.
