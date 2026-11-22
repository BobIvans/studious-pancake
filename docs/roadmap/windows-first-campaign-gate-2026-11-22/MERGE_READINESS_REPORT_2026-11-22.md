# MERGE READINESS REPORT — PR #679 execution set (2026-11-22)

**Base main:** `0a0c8ad9b58d866eab3e8dbac5e7b9d6c241fb54`. Все P0 CAM/WIN задачи task-pack исполнены отдельными Draft-PR. Никакой разработки сверх task-pack; lanes #666/#683 не затронуты. **Merge не выполняется** — только ваше явное merge-решение по каждому PR.

## 1. PR-таблица (exact SHA / base / changed paths / CI / review / mergeability)

GitHub API: `mergeStateStatus=CLEAN`, `mergeable=MERGEABLE` для всех 10 PR (на момент отчёта).

| PR | Head SHA | Base (branch @ SHA) | Changed paths | CI | Review | Mergeability |
|---|---|---|---|---|---|---|
| #691 CAM-01+02 | `154e783f` | main @ `0a0c8ad9` | src/qualification_campaign/{campaign_start_gate.py*, approval_replay_ledger.py*, cli.py}, config/format_targets.txt, tests/test_cam01* (2) | PASS 27/27 | Draft/OPEN | MERGEABLE, CLEAN |
| #692 WIN-01 | `9c81f706` | main @ `0a0c8ad9` | scripts/lock_requirements.py, requirements.lock, requirements-dev.lock, config/requirements-lock.json, tests/test_win01*, receipt, format_targets | PASS 7/7 | Draft/OPEN | MERGEABLE, CLEAN |
| #693 WIN-02 | `63482e34` | main @ `0a0c8ad9` | tests/conftest.py, tests/test_win02*, receipt, format_targets | PASS 26/26 | Draft/OPEN | MERGEABLE, CLEAN |
| #694 CAM-04 | `6e11d25b` | **#691-branch @ `154e783f`** | src/qualification_campaign/{evidence.py, cli.py}, tests/test_cam04*, format_targets | PASS 19/19 | Ready/OPEN | MERGEABLE, CLEAN |
| #695 WIN-03 | `dba369d7` | main @ `0a0c8ad9` | src/occ_durable_library.py, tests/test_win03*, receipt, format_targets | PASS 26/26 | Draft/OPEN | MERGEABLE, CLEAN |
| #696 CAM-05 | `b1c00e74` | main @ `0a0c8ad9` | src/resources/schema_registry.json, tests/test_cam05*, format_targets | PASS 29/29 | Draft/OPEN | MERGEABLE, CLEAN |
| #697 CAM-03 | `6e4492cc` | main @ `0a0c8ad9` | config/qualification/representative-sources.json, CAM_SOURCE_CROSSWALK_V1.md, tests/{test_cam03*, test_qpr03_source_intake.py}, format_targets | PASS 26/26 | Draft/OPEN | MERGEABLE, CLEAN |
| #699 DOC-01 | `7d22697f` | main @ `0a0c8ad9` | docs/roadmap/paper-data-campaign-universe-2026-11-21/DATA_CAPTURE_RUNBOOK_V1.md | PASS 6/6 | Draft/OPEN | MERGEABLE, CLEAN |
| #701 WIN-04 probe | `ca15ce88` | main @ `0a0c8ad9` | scripts/mpr2602_installed_default_probe.py | см. PR | Draft/OPEN | MERGEABLE, CLEAN |
| #698 integration | `80ddc7bc` | main @ `0a0c8ad9` | merge-коммиты #691–#697 + native receipt + probe-фиксы (дублируют #701) | PASS | Draft/OPEN | MERGEABLE, CLEAN — **NOT FOR MERGE** |

(* = новый файл.) Review status: reviewer не назначен; main без branch protection — гейт процедурный. Mergeability подтверждена GitHub API на момент отчёта; перед каждым merge — перепроверка.

## 2. Dependency-aware merge train

**Волна 1 (независимые, рекомендуемый порядок от наименьшего риска):**
1. `#692` → 2. `#693` → 3. `#695` → 4. `#701` → 5. `#696` → 6. `#697` → 7. `#699`

**Волна 2 (stacked):**
8. `#691` (после волны 1)
9. `#694` — **сразу после #691** (base уже = head #691; после merge #691 в main GitHub переквалифицирует base; при необходимости — один rebase на main, конфликтов нет: пересечение cli.py уже поглощено #691)

**Волна 3:**
10. `#679` (docs/backlog/report — последним)
11. `#698` — **НЕ мержить**: после волн 1–2 rebuild на новом main → authoritative WIN-04 native receipt на post-merge SHA → закрыть

## 3. Независимые vs stacked

- **Независимые:** #692, #693, #695, #696, #697, #699, #701.
- **Stacked:** #694 → #691; #698 → все семь; #679 — координационный docs-only, самодостаточен.

## 4. Rebase-проверка #694

GitHub `baseRefOid` #694 = `154e783f` = exact head #691 → rebase после интеграции #691 выполнен корректно до отчёта; mergeState CLEAN. После merge #691: если GitHub переквалифицирует base на main — действий нет; иначе один `git rebase main` (беспроблемно).

## 5. #701 vs #698

- **#701** — ровно один файл `scripts/mpr2602_installed_default_probe.py`; отдельный самодостаточный mergeable fix (cherry-pick 3a28d75f + ca15ce88).
- **#698** — только integration receipt + merge-коммиты семи PR; NOT FOR MERGE в заголовке и теле; probe-фиксы в нём дублируют #701 — поэтому #698 не мержить, чтобы не задвоить фикс.

## 6. Ownership-проверка changed paths

Чужих canonical owners НЕ задето:
- #691: campaign-runtime lane ✓; #692: lock lane ✓; #693: conftest ✓; #694: evidence/cli (CAM-04) ✓; #695: occ durable ✓; #696: schema registry (mpr2602) ✓; #697: prequal config + crosswalk + spec-тест 3→4 источников (CAM-03 acceptance) ✓; #699: runbook ✓; #701: probe ✓.
- Ранее откаченные правки (`market_source_catalog.json`, `src/solana_parallel_radar/cli.py`) не присутствуют ни в одном PR; integration CI это доказал (`RUNTIME_AUTHORITY_GENERATION_MISMATCH` и `RESEARCH_REFERENCE_REVIEW_HASH_MISMATCH` пойманы, правки убраны → AUTH-02/PIN-01 в backlog).

## 7. Пост-merge чек-лист (повторять после КАЖДОГО merge)

1. `git fetch origin && git rev-parse origin/main` — зафиксировать новый main SHA.
2. GitHub CI на новом main: CI (Repository verification), package-smoke, secret-scan — все PASS.
3. Оставшиеся PR: `gh pr view N --json mergeStateStatus` — по-прежнему CLEAN; base пересчитан.
4. #694: base переквалифицирован GitHub'ом на main? если нет — rebase на новый main + push (CI перегон).
5. Локально на Windows повторить focused-набор: tests/test_cam01*, test_cam03*, test_cam04*, test_cam05*, test_win01*, test_win02*, test_win03* — все зелёные.
6. Обновить `TASK_BACKLOG_V1.json` на ветке #679 (executed_pr → merged SHA).
7. После волн 1–2: rebuild `integration/windows-receipt-2026-11-22` на новом main → authoritative native receipt (WIN-04a).

## 8. Сохранённые артефакты

- **Native Windows receipt:** `docs/roadmap/windows-first-campaign-gate-2026-11-22/receipts/NATIVE_WINDOWS_RECEIPT_INTEGRATION_2026-11-22.md` на `integration/windows-receipt-2026-11-22` @ `80ddc7bc` (+ локальные копии стадийных логов/SHA-256/os_inventory в `.zcode/pr679/native-receipt/`).
- **43 remaining failures:** exact test IDs — `receipts/.../failed_tests.txt` (тот же коммит); классификация по кластерам с root causes и owners в теле receipt: POSIX mode-bit/ACL → GPR-01a (platform/durability/management/config lanes); TON OpenAPI CRLF-фикстура → ton/r02 lane; 2 focused-фейла test_pr120 → WIN-04b.
- Результаты верификации на SHA `7d3c693d`: pip check 0, compileall 0, quality_gate/validate_authority_map pass, **package_smoke PASS на Windows**, полный офлайн-suite 43 failed / 6217 passed / 9 skipped / **0 pytest-socket ошибок** (baseline 288F/327E устранён).

## Addendum (2026-11-22, post owner-review)

- **#694 обновлён до `6e11d25b`**: universal storage budget reservation для КАЖДОГО append (inline+blob), reconciliation после commit, manifest append под budget, approval ledger (+WAL/SHM) включён в единый `storage_bytes_max` scope. CI PASS 19/19. Security review addendum опубликован на #694 (risks R-A..R-D задекларированы).
- Все 10 PR переведены в Ready for Review (#698 остаётся Draft/NOT FOR MERGE).

## 9. Блокеры реального CAPTURE_ONLY

1. **CAM-06 (P0):** нет production operator trust anchor → gate возвращает typed `OPERATOR_TRUST_ANCHOR_MISSING`; нужен ACTIVE anchor (usage=operator-approval) + его generation в утверждённом плане. Без него capture невозможен by design.
2. **Операторское approval-действие:** подписанный approved-plan (V2-контракт) с binding на точный manifest digest/budgets/window — отдельный явный шаг владельца.
3. **AUTH-02:** refresh `market_source_catalog.json` требует координированного runtime-authority rebind.
4. **PIN-01:** stale Meteora URL в hash-пинутом `solana_parallel_radar/cli.py` — обновление только вместе с review-hash.
5. **DOC-02 (#671):** V2-артефакты (campaign_label / stale git_commit / MPR2602 note) — владелец #671; после merge — compatibility-тест loader'а #691.
6. **WIN-04b / GPR-01a:** 43 Windows-debt фейла (не блокируют capture; блокируют полный Windows PASS).
7. **CS-06 quorum:** минимум 2 независимых RPC-профиля (distinct operator/correlation) — REQUIRES_REAL_CAPTURE_HUMAN_GATED до реального evidence.
8. JUPITER/ZEROX credentials — comparator-этап, не для первого capture.

## Final recommendation

- Волна 1 (все семь) — ready to merge после вашего явного одобрения каждого.
- Волна 2 — #691 ready; #694 ready сразу за #691.
- #679 — docs, ready последним; #698 — закрыть после authoritative receipt.
- На момент отчёта ни один merge не выполнен; execution authority не изменена; CAPTURE_ONLY не запускался.
