# OCC + Laya local tooling — интеграция в studious-pancake

Эта интеграция добавляет **изолированный локальный tooling слой**. Она не входит
в latency-critical trading runtime и не создаёт второй paper runtime, journal,
source registry или release authority.

## Канонический путь qualification

Единственный executable action этого слоя:

`qualification_audit -> flashloan-checks qualify-and-report inspect`

Adapter передаёт только фиксированный argv и проверяет текущий
`pr189.command-result.v1`. Exit 0 в inspect означает завершённую диагностику,
а не готовность к торговле. Поля `qualified`, `release_authorized` и
`live_authorized` обязаны оставаться false; `transactions_sent=0`.

Текущий известный historical blocker из FAST-Q:

`paper-shadow:blocked_missing_wallet_public_key`

Он не заменяется fake wallet или секретом. Repair metadata разрешает только
operator-owned public identity/configuration и повтор focused verification.

## Laya / voice

`laya_request.example.json` — advisory proposal. Даже confidence=1.0 не
выдаёт permission и не меняет explicit registered action.

`voice_tools.responses.json` описывает schema будущего tool call. Transcript
или model output не становятся shell/argv/transaction командой.

## Local intake

`occ_local.py` читает только explicit workspace/inbox и optional repo,
ограничивает размер/количество, дедуплицирует по SHA-256 и не сохраняет raw
private text в generated report. Репозиторный Python анализ — только AST/static
heuristics, не execution.

## ASR

`asr_cpu_experiment.py` — opt-in эксперимент. `faster-whisper` импортируется
только внутри реального вызова; dependency не добавлена в bot runtime. Output
создаётся только новым файлом, вход хешируется до/после inference.

## Design-only paper plan

`paper_campaign.plan.json` имеет schema
`occ-paper-campaign-proposal.v1` и статус `BLOCKED_NOT_STARTED`. Adapter
намеренно отклоняет этот schema как executable input.

## Проверка

```bash
python -m unittest discover -s tools/occ_automation -p 'test_*.py' -v
python -m compileall -q tools/occ_automation
python scripts/verify_occ_automation.py
```

CI не скачивает ASR weights и не выполняет network/model/market calls.
