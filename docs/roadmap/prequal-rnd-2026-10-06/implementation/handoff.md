# Handoff: QPR-01, QPR-02 и campaign-start QPR-03

Эта фаза завершена. Машинный handoff — [handoff.json](handoff.json), отдельный реестр новых проблем — [new-problems.json](new-problems.json). QPR-04…QPR-10 не реализованы. Изменения разделены на три последовательных implementation PR поверх planning PR #567; `main` не изменён.

## A. Campaign readiness

`READ_ONLY_REAL_DATA_CAMPAIGN_V1`: **PASS** для bounded read-only сбора и offline replay. Реальная кампания получила HTTP 200 от DEX Screener, GeckoTerminal и Raydium, сохранила 72 candidate observations и сформировала 69 уникальных candidates с provenance. Raydium ответ принят с явными program-filter rejections. Replay воспроизвёл campaign identity и результат без сети.

Qualification verdict: **BLOCKED**. Production promotion: **false**. Настроен один публичный smoke-only RPC; quorum verdict — `BLOCKED_SINGLE_SOURCE`. Выбранный реальный CPMM pool отклонён native decoder: `Token-2022/unknown token program is unqualified`. Все четыре предшествующих RPC ответа и отрицательный результат сохранены. Этот запуск не доказывает успешный независимый mainnet quorum или exact strategy economics. Независимый quorum, disagreement, correlation, timeout и 429 проверены через настоящий collector и governed mock transport в тестах.

Точная identity реального запуска:

| Поле | Значение |
| --- | --- |
| repository SHA | `921e4fa1dfaaacc69b2f2ca202e449c3d2b44755` |
| main SHA | `ac6297e3f174d073c524099f599490edfe30f7b1` |
| runtime authority SHA256 | `abafb600a140f7808f8b744bd67946d0624f62865771444c28f366d8a27dacf1` |
| campaign ID | `07565d8ce89b247ffb1b0b62535f584a22d0813bc00bee4af6c72e49377389b6` |
| journal head | `1b71b248362f87147b9c60e9f4a7e7307c2933ae8e3ce20b24fbd5ef1292ac45` |

Это executable commit до добавления handoff. Полные configuration/source digests, raw hashes и observations находятся в `handoff.json`. Итоговые HEAD/base SHA трёх PR фиксируются после documentation commit в `/workspace/shared/qpr/phase-receipts.json`, чтобы избежать самоссылки SHA.

## B. Завершённые гарантии

**QPR-01:** runtime, release qualification и campaign factory читают один canonical `src/resources/runtime_authority.json`. Config mirror проверяется побайтно; authority связывает поколения capabilities, catalog, rooted policy и chain registry. Исторический map/PR queue не задаёт release identity. Campaign manifest связывает чистый точный repository SHA, ancestor main SHA, config и source generations. Несовместимые поколения не объединяются. CLI adapters и inspection используют общую parsed command identity.

**QPR-02:** native path принимает reviewed RPC profiles вместо единственного URL в collector. Для 1…4 профилей фиксируются provider/operator/correlation, credential references, generation, quota и campaign cap. Canonical rooted gate проверяет genesis, node identity/features, finalized slot/root, exact account bytes и block identity. Failed/correlated/disagreeing/single/smoke sources не квалифицируются. Raw replies, negative outcomes, attempts и replayable gate inputs сохраняются через существующие journal/governance owners. Квоты и attempt cap переживают restart; transport не делает скрытых retry.

**QPR-03 campaign-start:** generic dossier/profile/adapter intake проверяет docs freshness, request/schema/profile generations и discovery capabilities до I/O. Raw envelope содержит request/response hashes, observed/available time, supplied source context и negative quality. Credentials остаются references и редактируются при отражении в response. Candidate identity и dedup детерминированы, provenance сохраняется. Связь с verification требует retained candidate, canonical gate replay и pool/mint identity. Даже `ROOTED_REFERENCE` не предоставляет executable quote authority. Три representative источника доказывают текущий путь; тест нового plugin source проходит через тот же evidence model. Все 64 исходных FREE-SOURCE slots сохранены.

## C. Оставшиеся блокеры

| Категория | Состояние |
| --- | --- |
| Блокирует текущую real-data campaign | Подтверждённых нерешённых блокеров нет. Admission требует clean checkout, fresh dossiers, approved network/credentials при необходимости и доступные storage/quota budgets. |
| Блокирует stronger qualification | В реальном запуске: single smoke RPC и Token-2022 отказ. Также не доказаны deployment/source binding, continuous capture, forward holdout, cost/financing и неизвестные token/oracle semantics. |
| Блокирует production promotion | Active persistence cutover, release-bound 72h soak, security/deployment/rollback evidence и отдельно разрешённая live authority. Существующий dependency-audit finding также блокирует общий CI/merge check. |

Signer, sender, submission и live capital остаются недоступными для campaign composition. Эта фаза не предоставляет automatic promotion.

## D. Как подключить следующий источник

1. Создать skeleton: `python -m src.qualification_campaign.cli intake-template --slot FREE-SOURCE-001 --output /workspace/shared/qpr/next-source-template.json`. Выбрать действительно свободный исходный slot; planning package не переписывать.
2. Проверить текущие official API/docs/terms, auth, quotas и license/commercial/redistribution status. Заполнить timezone-aware `checked_at`, SHA256 документа, TTL, schema versions и явные UNKNOWN там, где условия не установлены. Representative dossiers действуют 24 часа после проверки; обновление создаёт новое поколение.
3. Добавить один reviewed adapter factory под `src.market.*` или `src.qualification_campaign.*`. Он реализует `request() -> SourceReadRequest`, `schema_contract()`, `normalize() -> (tuple[Candidate], rejection counts)` и optional `context()`. Adapter не содержит credential values и не вызывает signer/sender.
4. Заполнить dossier с `DISCOVERY_ONLY`, уникальными source/profile IDs, provider/operator/correlation, HTTPS endpoint/docs, `schema_fingerprint = digest(schema_contract())`, bounded quotas и slot_id для нового catalog source. Config задаёт `adapter.kind=plugin`, `factory=module:callable`. Admission принадлежит существующему MarketSourceCatalog.
5. Проверить success/empty/schema/auth/429/timeout, raw hashes, replay, dedup и provenance существующим intake suite. Review и commit adapter/config перед capture. Для обновлённой внешней конфигурации использовать новый файл вне checkout и новый output directory.
6. Разрешить только нужные домены и безопасные credential bindings в settings. Credential rotation меняет generation. Для stronger data evidence нужны два подтверждённо независимых provider/operator/correlation identity; два aliases одного backend не дают независимость.
7. Выполнить bounded capture с новым output и reviewed configs. Пример команды и все шаги находятся в `handoff.json:D_source_onboarding`.
8. Выполнить replay без сети, исследовать negatives и только затем предложить следующий targeted PR.

## E. Где находится evidence

Реальный output: `/workspace/shared/qpr/campaign-reviewed/`. Full raw evidence сохранено в текущей cloud instance вне Git; tracked handoff содержит manifest, outcomes и hash receipts. Восстановление новой задачи независимо не проверено.

| Артефакт | Содержание |
| --- | --- |
| `campaign-manifest.json` | Exact repository/main SHA, canonical authority digest, config/source generations, CAPTURE_ONLY и safety flags. |
| `campaign-evidence.sqlite` | Existing RecoverableStreamJournal; partition = campaign ID, cursors, payload/hash/parent, observation/availability timestamps. Manifest/dossiers, raw discovery/RPC, attempts, failures, candidates/universe и quorum bundle. |
| `campaign-evidence.sqlite.blobs/<sha256>.json` | Immutable large payloads; bounded storage, atomic write и replay hash verification. |
| `authority.sqlite` | Existing UnifiedLifecycleAuthority/ProviderGovernance durable window/quota state; permanent campaign attempt cap находится в journal. |
| `report.json` | Readiness, blocked verdict, candidate/source outcomes, negative evidence, quorum и physical-request counts. |

Raw hashes относятся к canonical JSON. При credential redaction original response hash и retained payload hash различаются явно. Indexed API slot/root/finality в текущем sample отсутствуют (`null`); никакой bank identity из них не выводится. Provenance chain: candidate → raw source observation → verification bundle → native capture → RPC receipts. Exact event IDs, hashes и schema описаны в machine handoff.

## F. Следующая реальная кампания

Текущий bounded probe уже выполнен: 3 discovery + 4 RPC physical requests, 93 retained events, 69 unique candidates, отрицательная native verification и offline replay. Повторять его как независимое qualification proof нельзя.

Следующий probe использует те же три discovery sources, свежие dossiers и два reviewed independent RPC profiles. Проверить один supported legacy-SPL CPMM control; отдельно сохранить unsupported Token-2022 sample. Максимум при успешном native capture: 3 discovery + 7 RPC calls на каждый из двух profiles = 17 physical requests; retries отсутствуют и все quota denials сохраняются. Campaign command допускает максимум два native candidates, но следующий probe планируется с `--verify-native 1`.

Сравнить finalized context slot, account bytes и block identity, явно сохранить disagreement/lag и источники без slot/time context. Проверить normalization/dedup, candidate-to-verification identity, raw/negative retention и socket-disabled replay. Отдельно отчитать schema drift, stale indexed state, 429 blind windows, исчезнувшие pools, token/oracle semantics и measured costs, когда они действительно наблюдаются. Завершить anomaly report и reprioritization; continuous capture/holdout остаются дальнейшей работой.

## G. Реестр новых проблем

В `new-problems.json` отдельно записаны: полный RPC genesis hash против сокращённого CAIP prefix (исправлено), реальный ProgramData сверх setup bounds (bounded limits/blob storage исправлены), negotiated compression против governed decoder (исправлено), drift official docs URLs (active dossiers обновлены). Token-2022 отказ отмечен как наблюдение уже известного semantic gap, а не искусственно объявленная новая roadmap задача. Исторические реальные captures не переписаны.

Отдельный validation finding `VAL-001`: online audit обнаружил `multidict==6.7.1`, GHSA-54p9-h82j-f925, fix version 6.9.1. Pin уже присутствует в обоих lockfiles исходного `main`; lockfiles в этой фазе не изменены. Это существующий CI blocker, а не новый market-data anomaly.

## H. Рекомендуемые следующие PR

До merge устранить `VAL-001` отдельным reviewed dependency PR и повторить strict audit. В этой трёх-PR фазе lockfiles не обновлялись и audit finding не исключался из CI.

1. Reviewed independent RPC configuration и bounded supported native control evidence — по фактическому `BLOCKED_SINGLE_SOURCE`.
2. Targeted Token-2022 semantic qualification либо явный restricted universe — после исследования extensions/owners из сохранённого отказа.
3. Bounded continuous capture/anomaly accounting — приоритизировать по новым измеренным timestamp/schema/lag/quota blind windows.
4. Deployment binding, forward holdout и measured cost/financing — порядок определить по реальным controls и экономическим блокерам.
5. Production-only persistence/soak/security/rollback — после stronger qualification и отдельно разрешённой promotion phase.

Эти шаги рекомендованы, но не реализованы. Исходный порядок QPR-04…QPR-10 не принят автоматически.

## Проверки и среда

Полный offline suite: **4913 passed, 0 failed, 1 deselected**, 38 секунд, network sockets disabled, Unix sockets allowed. После обнаружения регрессий обновлены только синтетические genesis fixtures и canonical authority fixture release test; runtime admission не ослаблен. Isolated wheel/package smoke, hash-locked installation, повторный install, pip check, installed disabled CLI и authority parity прошли. Local validation не заменяет hosted CI status — его нужно смотреть в PR checks.

После CI corrections: mypy — PASS для 206 source files; 75 focused campaign/native tests — PASS; 37 qualification regressions, authority verifier и repeated qualification — PASS. `scripts/verify_repo.py --skip-dependency-audit` полностью прошёл, включая format/type/security, package smoke, repository authority verifiers и повторный offline suite (4913 passed, 1 deselected). Полная команда без skip завершилась BLOCKED на существующем `VAL-001`; это не общий зелёный CI. Hosted campaign/qualification/wheel/runtime checks проходят, Repository verification остаётся red из-за strict dependency audit. Архив сохранён в `/workspace/shared/qpr/campaign-reviewed.tar.gz`; извлечённая копия воспроизведена с network sockets disabled и тем же journal head.

CPython 3.13.5 с ensurepip установлен в `/workspace/.python`, зависимости — в `.venv`. Tested install_script/start_skill и нужные custom network domains сохранены в environment draft; запись draft не является публикацией. Чтобы активировать reusable snapshot/config, требуется review/save в settings и Publish. Текущий saved repository selection `main` сохранён; implementation branches ещё находятся на review, main не изменён.
