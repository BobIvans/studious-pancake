# OCC + Laya local tooling — интеграция в studious-pancake

Эта интеграция добавляет **изолированный локальный tooling слой**. Она не входит
в latency-critical trading runtime и не создаёт второй paper runtime, journal,
source registry, action router или release authority.

## Канонический routing owner

Единственный router/action registry этого PR:

`src/fast_q_automation.py`

Текущий executable qualification path:

`qualify_and_report -> src.qualification_report.qualify_and_report`

Он использует существующий sender-free FAST-Q1 owner. Exit 0 в inspect означает
завершённую диагностику, а не готовность к торговле. Квитанции этого orchestration
слоя всегда сохраняют `qualified=false`, `live_authorized=false`,
`transactions_sent=0`; существующие release authorities не изменяются.

PR #554 уже владеет memory -> qualification bridge. PR #556 отдельно владеет
draft durable library/native host. Этот PR не дублирует и не поглощает их.

## Текущий известный blocker

Historical exact FAST-Q evidence сохраняет:

`paper-shadow:blocked_missing_wallet_public_key`

Он не заменяется fake wallet или секретом. `prepare_repair_task` оставляет
`patch_allowed=false` и требует operator-owned public wallet configuration /
evidence через существующий owner.

## Laya / voice

`laya_request.example.json` — advisory proposal. Laya proposal не меняет
explicit action и не выдаёт permission.

`voice_tools.responses.json` использует тот же закрытый action registry:
`qualify_and_report`, blocker/repair/validation/state actions и external-only
intake/search/ASR contracts. Transcript/model output не превращается в
shell/argv/transaction command.

## Local intake

`occ_local.py` читает только explicit workspace/inbox и optional repo,
ограничивает размер/количество, дедуплицирует по SHA-256 и не сохраняет raw
private text в generated report. Репозиторный Python анализ — только AST/static
heuristics, не execution. Network/model/subprocess imports отсутствуют.

## ASR

`asr_cpu_experiment.py` — opt-in эксперимент. `faster-whisper` импортируется
только внутри реального operator-run вызова; dependency не добавлена в bot
runtime. CI использует только injected test double и не скачивает weights.
Output создаётся только новым файлом, вход хешируется до и после inference.

## Design-only paper plan

`paper_campaign.plan.json` имеет schema
`occ-paper-campaign-proposal.v1`, статус `BLOCKED_NOT_STARTED` и
`native_adapter_compatible=false`. Эта схема не является
`fast-q2.action-request.v1` и не принимается action router.

## Проверка

```bash
python -m unittest discover -s tools/occ_automation -p 'test_*.py' -v
python -m compileall -q tools/occ_automation
python scripts/verify_occ_automation.py
python scripts/verify_fast_q_automation.py
```

GitHub exact-head CI является merge authority. CI не скачивает ASR weights и не
выполняет network/model/market calls.

MERGED != QUALIFIED != LIVE_AUTHORIZED.
