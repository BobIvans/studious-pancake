# OCC Memory → Qualification bridge

Этот bridge реализует bot-side часть пакета `OCC_MEMORY_TO_QUALIFICATION_ONE_PR_2026-10-02` для `studious-pancake` без создания второго qualification engine.

Он принимает только native OCC envelope:

```json
{
  "schema_version": "occ.qualification-action.v1",
  "request_id": "rnd-inspection-20261002-001",
  "action_id": "qualify_and_report",
  "text": "Проверь готовность бота"
}
```

Путь к репозиторию, output path, точный bot SHA, timeout и OCC provenance передаются отдельно через reviewed operator profile. Текст команды и импортированный source content не могут их переопределять. Source references содержат только bounded metadata (`source_id`, `version`, `sha256`) и проецируются в bridge receipt; содержимое источников не становится executable input.

Bridge делегирует выполнение существующему FAST-Q1 v3 owner `src.qualification_report.qualify_and_report` с фиксированным профилем `offline_sender_free`. Он не добавляет вторую очередь, scheduler, signer, sender, wallet path, network campaign или live permission.

Пример operator profile:

```json
{
  "schema_version": "studious-pancake.occ-qualification-profile.v1",
  "repo_root": "C:/reviewed/studious-pancake",
  "output_root": "C:/reviewed/qualification-receipts",
  "expected_bot_sha": "REPLACE_WITH_40_HEX_BOT_SHA",
  "timeout_seconds": 30,
  "occ_repository": "BobIvans/scaling-chrome-extensions",
  "occ_base_sha": "REPLACE_WITH_40_HEX_OCC_BASE_SHA",
  "occ_head_sha": "REPLACE_WITH_40_HEX_OCC_HEAD_SHA",
  "source_refs": [
    {
      "source_id": "chat:qualification-goal",
      "version": "2026-10-02",
      "sha256": "REPLACE_WITH_64_HEX_SOURCE_SHA256"
    }
  ]
}
```

Запуск из reviewed checkout:

```bash
python scripts/run_occ_memory_qualification.py \
  --request ../occ-request.json \
  --operator-profile ../occ-operator-profile.json
```

Коды выхода: `0` — bounded FAST-Q1 sender-free paper pass завершён; `3` — diagnostic завершён с `BLOCKED`; `2` — bridge отклонил request/profile или получил input/runtime error. Ни один из этих исходов не выдаёт production qualification или live authorization.

Replay semantics fail-closed. Завершённый request с теми же request/profile hashes переиспользует сохранённый bridge receipt. Изменённый payload под тем же request ID отклоняется. Прерванный или неизвестный исход помечается `RECONCILIATION_REQUIRED` и не запускается повторно автоматически.

Projected receipt связывает request ID, bounded source refs, OCC base/head SHAs, expected/observed bot SHA, canonical inspector owner, domain verdict, reason codes, receipt hash, limitations и next blocker. Source bodies намеренно не сохраняются в bridge receipt, а исторические source files не переписываются.
