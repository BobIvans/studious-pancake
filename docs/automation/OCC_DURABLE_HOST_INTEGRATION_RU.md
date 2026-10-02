# OCC durable host integration — studious-pancake

База реализации: `main@b31fa445218900702c0d0c4202481488a259c6f8`.

Исходный пакет был подготовлен для другого репозитория и ссылался на
`content-lab/automation_core.py`. В `studious-pancake` такого owner нет, поэтому
пути не копировались механически. Fresh owner audit нашёл уже принятые поверхности:

- context/evidence policy: `src/mega_context_wave3.py`;
- durable/idempotent qualification task: `scripts/run_qualification_task.py`;
- bounded installed qualification receipt: `src/qualification_report.py`.

## Что добавлено

`src/occ_durable_library.py` — отдельный OCC content/provenance owner, не торговый
runtime state. Он хранит namespace/source/version, append-only sync history и текущую
head-версию в SQLite. Идентичный sync — no-op; новая версия не удаляет предыдущую.
Доступ к данным проверяется по разрешённому namespace до чтения.

`scripts/run_occ_native_host.py` — строгий Native Messaging/JSON transport. Он принимает
только versioned typed request `occ.native-host-request.v1` и только action
`qualification.audit`. Shell/path/permission из входного JSON не принимаются. Job
делегируется существующему `scripts.run_qualification_task`; отдельной очереди или
scheduler не создаётся.

Host request привязан к:

- `job_id`;
- namespace/source;
- durable context version SHA-256;
- exact 40-char source commit;
- release id;
- bounded repeat 2..5.

Новый dispatch требует текущую head-версию контекста. Исторический завершённый job
может replay-иться после изменения источника, потому что старый version record остаётся
в append-only store. Незавершённый job не повторяется вслепую и возвращает
`NEEDS_RECONCILIATION`.

Файл `STOP` рядом с job отменяет его до dispatch. Mid-audit external cancellation не
заявляется: делегированный action остаётся offline/audit-only и не даёт signer/send/live
authority.

## Receipt truth

OCC receipt показывает:

- action/job/source/context version;
- делегированного owner;
- delegated receipt digest;
- job state;
- local verdict;
- blocker и `next_action`;
- CI evidence как `EXTERNAL_EXACT_HEAD`, а не как локальный PASS;
- `live_authorized=false` и `release_authorized=false`.

`CHECKED_REVIEW_ELIGIBLE` не означает production readiness или live authorization.

## Проверки

```sh
python -m compileall -q src/occ_durable_library.py scripts/run_occ_native_host.py scripts/verify_occ_durable_host.py tests/test_occ_durable_host.py
python scripts/verify_occ_durable_host.py
python -m pytest -q tests/test_occ_durable_host.py tests/test_qualification_task_adapter.py
```

Full repository verification и exact-head GitHub Actions остаются merge authority.
Installed Windows Chrome Native Host, real ASR/Laya, browser action execution и live
Web3 сознательно `NOT_RUN`/out of scope.
