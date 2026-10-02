# FAST-Q2/Q3/Q4 — детерминированный automation loop

Этот слой расширяет уже слитый FAST-Q1 v3 и не создаёт второй runtime, signer,
sender или release authority.

Канонический путь:

`versioned request -> closed router -> existing FAST-Q1 inspection -> current
blocker -> bounded repair task -> fixed validation -> receipt-derived state`.

## Команда

```bash
flashloan-checks automation-request inspect \
  --request /outside/checkout/request.json \
  --repo-root /clean/checkout \
  --output-root /outside/checkout/fast-q-runs \
  --expected-sha <exact-40-char-git-sha>
```

Разрешены только reviewed actions из `config/fast_q_actions.json`. Неизвестные,
неоднозначные, negated и live/sign/send/private-key запросы fail closed. Поле
`proposal` от model/Laya/operator является только advisory.

Action receipts находятся вне checkout в
`actions/<idempotency_key>/receipt.json`. Reuse допускается только при том же
request digest и source SHA; corrupt/incomplete/stale evidence останавливает
исполнение.

Архивный трёхполевый `occ.qualification-action.v1` поддерживается только для
канонических qualification-фраз. Четырёхполевый OCC envelope с `action_id`
нужно отправлять через `scripts/run_occ_memory_qualification.py` с отдельным
operator profile: FAST-Q2 не удаляет его provenance и не подменяет этот мост.
Остальные действия используют `fast-q2.action-request.v1`.

При обновлении состояния action receipt должен принадлежать текущему SHA и
указанному idempotency key. TEST_PASSED подтверждается непустыми записями всех
команд фиксированного validation set с целыми exit codes. Проверяются result
digest/status и effect flags; самосогласованный хеш не удостоверяет истинность
импортного результата. State также связывает ID и bytes hash дочерней FAST-Q1
квитанции с текущими schema/action/profile и manifest input digest.

Полная карта владельцев и очередь развития OCC:
[RECONCILIATION_AND_NEXT_RU_2026-10-03.md](../occ/RECONCILIATION_AND_NEXT_RU_2026-10-03.md).

Fresh pre-implementation probe PR #553 на commit
`540cab87df3b6017b26b18d389673b70f94768a0` подтвердил current blocker:

`paper-shadow:blocked_missing_wallet_public_key`

Это operator/config evidence. Система не подставляет синтетический wallet:
`prepare_repair_task` привязывает owner к
`src/runtime_discovery_coordinator.py`, запрещает automatic patch и выдаёт
`EXTERNAL_OPERATOR_INPUT_REQUIRED`.

`run_focused_validation` использует только fixed argv sets
`fast_q_automation` и `fast_q1_v3`; arbitrary shell отсутствует.

`update_receipt_state` пишет `state.json` и `STATUS_RU.txt` из проверенных
receipts, сохраняя раздельные состояния
`planned -> implemented -> test_passed -> inspected -> qualified ->
live_authorized`. Test PASS не повышает qualification/live state.

OCC/content/ASR actions являются contracts внешнего worker boundary. Core не
подключает heavy ASR/OCR/model dependencies и не принимает model-supplied roots.
