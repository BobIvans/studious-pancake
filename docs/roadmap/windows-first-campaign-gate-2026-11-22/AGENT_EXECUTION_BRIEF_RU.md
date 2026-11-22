# PR #679 — Windows-first governed CAPTURE_ONLY: задание агенту

**Тип PR:** task/coordination pack. Это не implementation PASS и не разрешение на campaign run.  
**Target platform:** native Windows 11 x64, General Availability Channel, version 26H2; зафиксировать фактический build через PowerShell на машине проверки.  
**Main на момент создания:** 0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54.  
**Документы и backlog:** соседние файлы этого каталога.

## 1. Цель

Подготовить реальный, воспроизводимый и machine-enforced путь от одобренного CAPTURE_ONLY manifest до ограниченного read-only запуска на Windows. Система должна до первого внешнего запроса доказать, что:

1. запускается именно одобренная конфигурация;
2. manifest и runtime identity привязаны к точной версии кода и конфигурации;
3. операторская авторизация действительно проверяется существующим authority/release mechanism;
4. каждый provider и источник имеет текущие docs/schema/provenance pins;
5. общий и provider-level бюджеты физически enforced и переживают restart;
6. RPC quorum не может получить PASS от correlated/smoke-only источников;
7. Windows-specific runtime, storage, event loop и verification проходят на native Windows, а не только в Linux CI;
8. replay не делает сетевых запросов.

Это не production launch. В этой работе нельзя включать live trading, отправку, подпись, borrow, создание аккаунтов, relay tips, платные feeds или автоматическое расширение бюджетов.

## 2. Исходное состояние, которое нельзя потерять

Проверено по GitHub на 2026-11-22:

- #664 merged: campaign-preparation pack в main, merge commit 2628041a.
- #668 merged: live-data baseline и DIN-01 pins, merge commit 0a0c8ad9.
- #671 open: V2 manifest, два RPC profile templates, CS-01..CS-10 mapping и source recheck. Сам документ прямо говорит, что CS-01..CS-10 пока не реализованы одним исполняемым gate.
- #670 open: Windows smoke receipt. Он честно показывает, что Windows verify_repo ещё не зелёный.
- #665 Draft: GitHub CI на проверенном HEAD 548d5c06 завершил verifier как 15/17. Не считать локальные 17/17 подтверждёнными GitHub.

Основные текущие владельцы:

- src/qualification_campaign/cli.py — capture/replay entrypoint;
- src/qualification_campaign/identity.py — CampaignManifest identity;
- src/qualification_campaign/profiles.py — ProviderProfile и sender-free RPC method set;
- src/qualification_campaign/sources.py — SourceDossier и discovery intake;
- src/qualification_campaign/rpc.py — rooted RPC capture/quorum;
- src/qualification_campaign/evidence.py — durable journal, evidence, attempt ledger;
- src/provider_governance/ — provider entitlements, physical attempt policy, quotas;
- src/market/source_catalog.py + src/market/discovery.py — canonical source IDs and discovery adapters.

Не создавай параллельный campaign engine, provider registry, quote kernel, capital graph, signer, sender или paper runner.

## 3. P0 — исправить путь авторизованного запуска до первого сетевого запроса

### CAM-01. Исполняемый CAMPAIGN_START_V1 gate

Сейчас CAMPAIGN_START_V1 существует как acceptance_gates.json и ручная mapping-документация. В текущем src/qualification_campaign/cli.py capture path принимает source config и optional RPC profiles, генерирует свой runtime CampaignManifest и непосредственно начинает intake. Он не загружает и не сверяет одобренный V2 campaign plan как единый authorization contract.

Нужно:

1. Исследовать существующие canonical human/release authorization owners и точку, где они уже подтверждаются runtime. Начать с src/release_gate/, src/runtime_authority.py, src/resources/runtime_authority.json, src/provider_governance/ и существующего acceptance gate loader. Не предполагать, что любое непустое поле operator_approval является доказательством авторизации.
2. Сделать capture fail-closed до открытия транспорта и до любого DNS/HTTP/RPC физического вызова. При отсутствии или несоответствии approval возвращать typed blocker и подтверждать 0 network attempts.
3. Использовать именно CAMPAIGN_START_V1 и все blocking CS-01..CS-10. Отобразить verdict и evidence каждого gate отдельно; нельзя автоматически переводить PARTIAL/UNKNOWN/REQUIRES_REAL_CAPTURE в PASS.
4. Привязать approval к точному digest manifest, source config/generations, RPC profiles, policy bundle, runtime authority, code/release SHA, budget, retention и capture window. Любое изменение после approval аннулирует approval.
5. Если canonical human approval/signature path в репозитории отсутствует или не подключён к CLI — не придумывать слабую замену из boolean/string полей. Сделать блокирующее состояние, зафиксировать точный missing owner/contract и предложить отдельную задачу для этого механизма. Никакого сетевого вызова при неизвестной авторизации.
6. Не выполнять настоящую кампанию в этом PR. Только offline fixtures и negative tests.

### CAM-02. Identity и manifest schema

В V2 есть static campaign_id = 20261121-market-capture-001, тогда как CampaignManifest.campaign_id в runtime — криптографический digest. Не смешивать human label и cryptographic identity.

Нужно:

- Разделить campaign label/reference и cryptographic manifest ID.
- Использовать существующий canonical JSON digest из src/qualification_campaign/identity.py.
- Не делать циклический self-hash. Если approval нужно связать с полным manifest, использовать detached approval envelope или другой существующий non-circular mechanism, который содержит точный digest manifest.
- Исправить release.git_commit, который в V2 указывает ea204222..., хотя main на момент создания этого задания уже 0a0c8ad9...
- Не хардкодить SHA текущего main в исполняемом коде. На runtime проверять актуальный release/commit согласно canonical policy. Запрещать stale code/config и dirty checkout.
- Сравнить actual runtime CampaignManifest с approved plan до любого сетевого запроса.
- Сохранить независимую provenance template -> V1 -> V2 -> approval -> capture receipt.

### CAM-03. Source config и provider IDs

Сверить три сущности byte/schema level: V2 manifest, market_source_catalog и фактический config, передаваемый в CLI.

Известные расхождения:

- config/qualification/representative-sources.json содержит три источника, а не все четыре действующих discovery adapters.
- Его checked_at для старых записей — 2026-10-06, TTL — 86400 секунд; они не должны считаться fresh сейчас.
- V2 использует имена raydium_api_v3 и meteora_dlmm_data, тогда как DiscoveryRequest в src/market/discovery.py использует raydium и meteora-dlmm.
- GeckoTerminal documentation URL был зафиксирован как redirect/drift в source recheck; обновить именно official-doc pin и schema evidence.
- Meteora adapter поддерживается кодом, но отсутствует в representative source config.

Нужно:

1. Составить точную crosswalk-таблицу: manifest source ID -> catalog source ID -> DiscoveryRequest ID -> adapter -> endpoint -> owner -> docs pin -> request/response schema hash.
2. Не переименовывать registry IDs механически. Использовать явные aliases с тестами, если это принято существующим каталогом.
3. Перепроверить все четыре источника: DexScreener, GeckoTerminal/CoinGecko, Raydium API V3 и Meteora DLMM.
4. Обновить timestamps, документацию, endpoint, schema fingerprint, terms URL и quotas. Если docs или terms недоступны — BLOCKED, не CURRENT.
5. Оставить discovery-only статус. Indexed data, priceUsd и liquidity metadata не должны становиться exact quote или executable edge.

### CAM-04. RPC profiles, quorum и allowlists

Изучи src/qualification_campaign/rpc.py, src/qualification_campaign/profiles.py, src/data_plane/rpc.py и connections registry.

Требуется:

- минимум два действительно независимых provider, operator и correlation_group для rooted PASS;
- mainnet genesis, finalized/rooted commitment, explicit context slots, freshness/skew и одинаковое состояние/запрос должны проверяться существующим RootedRpcQuorumGate;
- публичный smoke endpoint может быть использован только как exploratory negative evidence, не как rooted PASS;
- сверить RPC методы, которые реально вызываются в rpc.py (включая getMultipleAccounts, getSlot, getVersion и genesis check), с ProviderProfile.READ_RPC_METHODS и MPR2602 connections-registry enum;
- не расширять sender-free enum ради удобства; не добавлять getBlock или другие методы, если их нет в реальном read path;
- каждый профиль должен быть привязан к approved manifest и своим operator/provider/correlation identity.

### CAM-05. Реально enforce budgets и retention

V2 предлагает rpc_physical_attempts_max=200, storage_bytes_max=104857600, per-source 12 requests / 60 sec / max 100 attempts, spend=0. Эти значения пока PROPOSED, а не операторское разрешение.

Проверить существующий CampaignEvidenceStore.claim_attempt(profile), ProviderSpendAuthority и durable quota pool. Сейчас attempt accounting привязан к profile; этого недостаточно само по себе для глобального cap при нескольких профилях.

Требуется:

- atomic durable campaign-global cap 200, считающий все физические запросы всех discovery/RPC providers;
- independent per-profile caps (не более утверждённого campaign_attempt_cap);
- 12/60s rate limit на профиль/provider по утверждённому контракту;
- retries/backoff тоже расходуют physical attempt budget;
- restart/replay не сбрасывают бюджет и не позволяют повторно тратить лимит;
- storage ceiling 100 MiB enforced на совокупный campaign artifact footprint: journal DB, WAL/SHM, blobs, temp/staging и retained payloads, а не только на один blob;
- нулевой paid spend; если провайдер требует платный план или неизученную подписку — BLOCKED;
- overflow/unknown quota/storage state -> typed BLOCKED до следующего физического вызова.

Проверить race condition и multi-process/restart tests; не полагаться только на in-memory counter.

## 4. P0 — Windows является основной средой разработки и исполнения

### WIN-01. Lock и uvloop

Факты из #670:

- pyproject.toml уже ограничивает uvloop условием platform_system != Windows.
- requirements.lock содержит uvloop==0.22.1 без platform marker.
- на Windows uvloop wheel отсутствует, поэтому package_smoke wheelhouse stage падает с WINDOWS_LOCK_UVLOOP_NO_MARKER.

Исправить источник генерации/скрипт scripts/lock_requirements.py и пересобрать lock штатным способом. Не редактировать огромный lock вручную и не удалять uvloop для Unix. Проверить Windows wheelhouse install с --require-hashes --only-binary=:all: и Linux runtime install; Python target остается из pyproject.toml (>=3.13,<3.14), если отдельный compatibility audit не обоснует изменение.

### WIN-02. ProactorEventLoop и pytest-socket

Факты из #670:

- Windows Python 3.13 использует ProactorEventLoop по умолчанию.
- 327 Windows pytest errors были fixture-setup SocketBlockedError: pytest-socket блокирует AF_INET socketpair/self-pipe Proactor loop; --allow-unix-socket разрешает только AF_UNIX.
- Большинство 288 reported test failures также загрязнено этим environment failure, поэтому нельзя считать их все самостоятельными ошибками или все объявлять false positives.

Исправить tests/conftest.py / test bootstrap узко и доказуемо. Запрещено просто отключать --disable-socket или разрешать весь outbound internet. Нужны тесты, которые подтверждают одновременно:
1. ProactorEventLoop и asyncio pytest fixtures запускаются;
2. локальный loopback/self-pipe допускается только там, где это нужно;
3. внешний TCP/UDP/DNS к неразрешённым адресам всё ещё блокируется;
4. Linux SelectorEventLoop behavior не регрессирует.

### WIN-03. SQLite cleanup / WinError 32

В #670 verify_occ_durable_host.py получил WINDOWS_SQLITE_TEMP_CLEANUP_PERMISSION (WinError 32 при удалении content.sqlite3 в TemporaryDirectory).

Проверить scripts/verify_occ_durable_host.py, src/occ_durable_library.py и все используемые UnifiedLifecycleAuthority/RecoverableStreamJournal connections. Установить точный открытый handle, добавить явный lifecycle/close/context manager там, где это требуется, закрыть connection и journal до удаления временного каталога. Не маскировать ошибку ignore_errors=True и не обходить cleanup.

### WIN-04. Native Windows verification

GitHub Linux CI не доказывает работу на клиентском Windows 11. Добавить воспроизводимый PowerShell smoke script/receipt и Windows CI job, где это возможно. Зафиксировать:
- Windows edition, DisplayVersion, OS build, architecture;
- PowerShell version;
- Python 3.13 x64 exact patch version;
- uv version;
- Git version и core.autocrlf;
- installed package hashes/lock result;
- exit code каждого verify stage;
- pytest summary с явной классификацией fail/error/skip;
- SHA256 test receipt и exact commit SHA.

Не объявлять Windows PASS, пока полный bounded verification не прошёл на native Windows. GitHub-hosted windows-latest/server runner — полезная дополнительная проверка, но не замена receipt на целевой Windows 11 client.

## 5. Обязательные связанные backlog tasks

### PMM-01 — отдельная починка #665

На проверенном PR head GitHub verifier scripts/verify_pmm_sim_caller_profile.py прошёл только 15/17:

- vendor_mirror_sha256sums: mismatch в .github/workflows/audit.yml, .github/workflows/ci.yml и .gitignore внутри pmm-sim mirror;
- results_digest_chain: SHA256 caller_profile_results.csv не совпадает с scenario_manifest_v1.json.

Повторить проверку на чистом Linux и native Windows checkout. Найти точную причину: line endings, manifest generation, stale SHA или неверный список mirror files. Добавить regression tests для проверки байтов из Git checkout. Обновить SUMMARY только после того, как GitHub CI на новом head действительно подтвердит 17/17 и все required workflows PASS.

Не переносить весь #665 diff в #679 и не переписывать его ветку без отдельного owner. Ссылка: https://github.com/BobIvans/studious-pancake/pull/665.

### PMM-02 — размер и происхождение pmm-sim evidence

#665 сейчас показывает 691 changed files: сотни JSONL, snapshots, binary fixtures и результаты benchmark. Провести sizing/retention review. Не удалять evidence и не ослаблять hashes. Предложить компактный tracked manifest + immutable evidence bundle только если в репозитории есть утверждённый storage/retention mechanism, иначе сохранить всё и документировать стоимость/ограничения.

### GPR-01 — реальные остатки Windows baseline

После исправления WIN-02 повторно прогнать полный baseline и выделить оставшиеся genuine failures. В #670 отмечены GPR failure cluster (146), MPR2602/TON errors и другие tests; отдельный #667/#N07 report также записывал ValueError unresolved synthetic path в registry.py. Сопоставить exact test names, traceback, current main и owner. Никакие старые counts не считать текущими без повторного запуска. На каждую root cause — отдельный issue/PR с regression test.

### DOC-01 — runbook/manifest consistency

В #671 REMAINING_BLOCKERS_TO_FIRST_CAPTURE ссылается на runbook S7 как место запуска capture, но S7 в DATA_CAPTURE_RUNBOOK_V1.md — раздел offline replay. Исправить ссылку и добавить отдельный точный Capture command section, prerequisites, expected typed outcomes и output receipt format.

## 6. Обязательные negative tests до любого capture PASS

- missing authorization -> typed BLOCKED, zero network;
- wrong approved manifest digest -> BLOCKED, zero network;
- stale runtime/main SHA -> BLOCKED, zero network;
- changed source config/profile/provider generation -> BLOCKED, zero network;
- docs TTL expired or schema drift -> source BLOCKED;
- one RPC, public smoke, same operator or same correlation group -> rooted verdict BLOCKED;
- wrong genesis, commitment mismatch, slot skew, payload hash mismatch -> BLOCKED;
- global attempt cap, per-profile cap or storage cap exceeded -> BLOCKED before physical call/write;
- retry and process restart do not reset budget;
- missing secret reference -> BLOCKED without printing a credential;
- replay -> zero outbound network;
- sender/signer/submission/borrow/account-creation/relay fields remain false;
- existing deterministic offline fixtures continue to replay byte-identically.

## 7. Windows target and commands

На 2026-11-22 Microsoft Release Health показывает Windows 11 26H2 как current GA x64 family, build 26300.9974 (2026-11-10). Перед тестом agent обязан получить фактическую версию с целевой машины, а не считать её равной версии по одному Kernel Version string.

PowerShell inventory:

~~~powershell
$ErrorActionPreference = "Stop"
Get-CimInstance Win32_OperatingSystem |
  Select-Object Caption, Version, BuildNumber, OSArchitecture
Get-ComputerInfo |
  Select-Object WindowsProductName, WindowsVersion, OsBuildNumber, OsArchitecture
$PSVersionTable
py -0p
python --version
uv --version
git --version
git config --get core.autocrlf
git rev-parse HEAD
git status --short
~~~

Native Windows verification после фиксов:

~~~powershell
..venvScriptspython.exe -m pip check
..venvScriptspython.exe -m compileall -q arb_bot.py src scripts tests
..venvScriptspython.exe scriptserify_repo.py --skip-dependency-audit
..venvScriptspython.exe -m pytest -m "not live and not manual" --disable-socket --allow-unix-socket -q
~~~

Команды можно адаптировать к штатному verify wrapper; нельзя пропускать failed stage, не указав его как blocker. Любой campaign network request запрещён во время этого verification.

## 8. Организация выполнения

1. Читать AGENTS.md и действующие repo instructions до изменения кода.
2. Работать только в отдельном worktree на отдельную задачу/PR. Не переключать общий IDE checkout, не делать reset чужой ветки и не восстанавливать чужой reflog.
3. Сначала сделать code map и tests map, затем минимальный implementation slice. Не писать новые kernels, registries и runners, пока не доказано отсутствие подходящего owner.
4. Все обнаруженные дефекты добавлять в TASK_BACKLOG_V1.json с ID, owner, exact file/test, root cause, acceptance criteria и отдельным PR owner. Не оставлять их только в комментариях.
5. Не менять main напрямую. Любой code fix — Draft PR с точными базой/head, tests, hashes и typed blockers.
6. Не запускать CAPTURE_ONLY, реальный RPC collection, quote API, подписку или paid endpoint в этой работе. Проверки исключительно offline.
7. Не утверждать PASS на основе локального результата, пока тот же exact commit не прошёл GitHub CI и native Windows receipt.
8. При завершении обновить TASK_BACKLOG статусы и записать SHA/CI/run receipts в report. Не закрывать blocker формулировкой «pre-existing» без воспроизводимого clean-main proof.

## 9. Definition of Done

- Исполняемый CAMPAIGN_START_V1 enforcement существует и fail-closed выполняется до первого сетевого вызова.
- Runtime actual inputs совпадают с human-approved manifest/profiles/budget digest.
- Source IDs, adapters, docs pins и source generations согласованы.
- Глобальные RPC/capture/storage quotas enforced durable образом.
- Rooted quorum semantics не ослаблены.
- Native Windows 11 26H2 validation зелёный, а все stage receipts привязаны к точному commit.
- #665 verifier repair отдельно закрывает 2 найденных failure.
- Все остальные найденные ошибки добавлены как отдельные задачи с владельцем.
- Никакой реальной campaign, signing, sending, borrowing или live promotion не выполнялось.

**Важное правило:** этот task pack сам по себе не даёт разрешения на capture. Авторизация и первый CAPTURE_ONLY остаются отдельным явным операторским действием после code review и всех gates.
