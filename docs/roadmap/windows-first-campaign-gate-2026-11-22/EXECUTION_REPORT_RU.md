# PR #679 — отчёт об исполнении (2026-11-22, RU)

**Base main:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54` (перезfetch зафиксирован в начале исполнения).
**Статус:** все P0-задачи task-pack исполнены как отдельные Draft-PR; GitHub CI PASS на каждом exact head; нативный Windows-реceipt подготовлен; никакого CAPTURE_ONLY/paper/live-действия не выполнено. Merge — только по явному запросу владельца.

## 1. Карта PR

| PR | Задачи | Ветка (head) | CI |
|---|---|---|---|
| #691 | CAM-01 + CAM-02 (гейт + approval) | `codex/679-cam-gate-2026-11-22` (`154e783f`) | PASS 27/27 |
| #694 | CAM-04 (бюджеты), стек на #691 | `codex/679-cam-budget-2026-11-22` (`3d29f5b4`) | PASS 19/19 |
| #696 | CAM-05 (RPC-enum) | `codex/679-cam-rpc-2026-11-22` (`b1c00e74`) | PASS 29/29 |
| #697 | CAM-03 (источники) | `codex/679-cam-sources-2026-11-22` (`6e4492cc`) | PASS 26/26 |
| #692 | WIN-01 (lock) | `codex/679-win-lock-2026-11-22` (`9c81f706`) | PASS 7/7 |
| #693 | WIN-02 (socketpair) | `codex/679-win-socket-2026-11-22` (`63482e34`) | PASS 26/26 |
| #695 | WIN-03 (SQLite close) | `codex/679-win-occ-2026-11-22` (`dba369d7`) | PASS 26/26 |
| #701 | WIN-04 probe-фиксы | `codex/679-win04-probe-fixes-2026-11-22` (`ca15ce88`) | см. PR |
| #698 | WIN-04 интеграция + native receipt | `integration/windows-receipt-2026-11-22` (`80ddc7bc`) | PASS 31+/31+ — **NOT FOR MERGE** |
| #699 | DOC-01 (runbook) | `codex/679-doc01-runbook-capture-2026-11-22` (`7d22697f`) | PASS 6/6 |
| — | PMM-01 | коммиты в собственной ветке #665 (`fb22734b`, `5fb44158`, `ad297128`) | **#665 CI PASS 36/36** |

## 2. Что реализовано

### CAM-01/02 (#691) — исполняемый CAMPAIGN_START_V1
- Новый `src/qualification_campaign/campaign_start_gate.py`: versioned loader утверждённого плана (контракт V2, изолированные фикстуры — без импортов из #671), вердикты CS-01..CS-10, фазы PREFLIGHT_PASS → CAPTURE_AUTHORIZED, CS-06 всегда `CS06_PENDING_CAPTURE` до реального capture-evidence.
- Approval: Ed25519 `SignedEnvelope` через `TrustAnchorRegistry` (usage=operator-approval), generation реестра пинится; payload привязан к manifest digest, repository/main SHA, generations, allowlists, budget/retention/window, CAPTURE_ONLY.
- Durable single-use внешнего envelope: `src/qualification_campaign/approval_replay_ledger.py` (sibling pr201-механики: atomic reserve→finalize CAS, идемпотентный receipt, REPLAYED fail-closed). pr201 напрямую переиспользовать нельзя — он импортирует `src.signer_authorization_pr141`, что запрещено import-guard кампании (задача AUTH-01 в backlog).
- CLI: `--campaign-plan` обязателен, `--trust-registry` опционален; гейт выполняется после записи манифеста и ДО создания транспорта; при отказе — `campaign-start-blocked.json` c `physical_network_attempts: 0` (доказано transport-сентинелом).
- Без активного production trust anchor — typed BLOCKED (CAM-06 в backlog).

### CAM-04 (#694) — бюджеты
- `CampaignBudgets` из утверждённого плана (unbounded/paid → fail-closed).
- Campaign-global attempt cap по всем профилям + каждый retry; переживает restart/replay.
- Storage ceiling: DB+WAL+SHM+lock+blobs+staging; reservation до записи под тем же cross-process flock, reconciliation после commit; over-commit → typed BLOCKED.
- Все appends теперь в одном cross-process lock с `claim_attempt` (append-race гипотеза: CAM-07, REPRODUCTION_REQUIRED).

### CAM-05 (#696) — RPC-enum
- MPR2602 enum += `getBlock`, `getVersion` — только по call-site proof (native_cpmm_capture.py:363/368/390/411, rpc.py:59/61/63); `getBlockHeight` не добавлен; governance set не расширен; static-scan тест пересобирает фактическое множество из исходников (три-реестровый intersection).

### CAM-03 (#697) — источники
- Документы 4 источников перечеканы 2026-11-22T10:37:27Z (raw-byte SHA-256 пины в crosswalk); GeckoTerminal pin переведён с redirect-drift на `docs.coingecko.com/reference/introduction`; Meteora: старый URL 404 → текущий официальный reference (dlmm.datapi.meteora.ag, GET /pools, 30 RPS); `meteora-dlmm` добавлен четвёртым источником intake; `checked_at` = docs-pin freshness только (endpoint health не заявлялся); registry ID не переименовывались (alias-таблица).
- Интеграционный CI выявил два cross-owner ограничений: `market_source_catalog.json` digest-пинут в runtime_authority (AUTH-02) и `solana_parallel_radar/cli.py` review-hash-пинут (PIN-01) — обе правки откачены и записаны в backlog.

### WIN-01 (#692) — lock
- `uv pip compile --universal` несовместим с `--python-platform linux` (проверено на uv 0.13.4) → маркеры прямых зависимостей ре-применяются генератором к hash-lock; регенерация штатным скриптом; Windows wheelhouse PASS (0 uvloop), Linux сохраняет uvloop, повторная генерация — zero diff; platforms += windows.

### WIN-02 (#693) — socketpair
- Только `socket.socketpair` exemption (pristine class вокруг вызова); без --allow-hosts/loopback-connect; внешние И loopback connect остаются `SocketBlockedError`. Ранее падавшие representative-наборы (qpr02/qpr03/din01): 34/34 против 24 baseline-фейлов.

### WIN-03 (#695) — SQLite close
- 4 незакрытых соединения в `OCCDurableLibrary` (+: `_initialize`, `get_version`, `latest`, `history`) закрыты (`contextlib.closing` + transaction context; commit/rollback сохранены); `verify_occ_durable_host.py` PASS на Windows (был WinError 32).

### WIN-04 (#698/#701) — верификация
- Integration branch = main + merge всех семи PR; GitHub CI PASS; **NOT FOR MERGE** пометка.
- Probe-фиксы (#701): AF_UNIX sentinel + stdlib self-pipe connect exemption → `package_smoke` PASS на Windows.
- Native receipt (инвентаризация через Get-CimInstance, стадийные exit codes, SHA-256) закоммичен в integration.

### PMM-01 (в ветке #665)
- Побайтовый root cause: `core.autocrlf=true` нормализовал блобы в LF против CRLF-пинов + 49/170 пинутых файлов (Cargo.lock + parquet, ~1.3 МБ) были gitignored и отсутствовали в чистых checkout; удалённый detail обрезался `bad[:3]`.
- Фиксы: `.gitattributes -text` + `--renormalize` (блобы == пины, provenance не переписан), force-add недостающих, checkout-независимые blob-pin тесты, stub BlackHoleListener в оффлайн-тесте. **CI #665: PASS 36/36** (Repository verification + pr357 + pr358). Все 2700 evidence-строк сохранены. #357/#358 кода не менялись (их job-фейлы были от общего verifier).

### DOC-01 (#699)
- Runbook: новый раздел S6.5 с реальной capture-командой (`--campaign-plan`/`--trust-registry`), prerequisites, typed outcomes и артефактами; S7 помечен «replay — НЕ capture».

## 3. Нативная Windows-верификация (integration SHA `7d3c693d`, машина Windows 11 26H2 x64 build 26300)

- pip check 0; compileall 0; quality_gate/validate_authority_map pass; **package_smoke PASS** (впервые на Windows).
- Полный офлайн- suite (свежая классификация, без переноса старых counts): **43 failed / 6217 passed / 9 skipped; 0 pytest-socket ошибок** (baseline #670: 288F/327E — устранён #692/#693/#695).
- Все новые/фокусные тесты #679 зелёные; 43 остатка классифицированы по кластерам с root causes и owners (receipt + `failed_tests.txt`); полный PASS не заявляется — WIN-04b/GPR-01a в backlog.
- verify_repo exit 1 — только из-за 2 pre-existing POSIX-mode-bit тестов (test_pr120); Linux CI зелёный.

## 4. Backlog

TASK_BACKLOG_V1.json обновлён: статусы исполненных + новые записи CAM-06, CAM-07, AUTH-01, AUTH-02, PIN-01, PMM-01a, PMM-02a, DOC-02, DEP-01, GPR-01a, WIN-04a (каждая с root cause, files, owner, acceptance criteria).

## 5. Safety

Никакого CAPTURE_ONLY, paper/live, provider activation, credentials, paid вызовов; sign/send/borrow/live гейты не ослаблены (усилены: probe fail-closed восстановлен на Windows); unknown ≠ 0; fixtures ≠ live evidence; чужие ветки не переписывались; merge — только по явному запросу.
