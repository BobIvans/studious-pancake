# AGG-15 — итоговый аудит покрытия и release handoff

AGG-15 реализует RELEASE-01 как fail-closed слой аудита поверх существующих
owners. Он не становится вторым release authority: production promotion остаётся
у MPR-2612, а live не включается этим пакетом.

## Current base and dependency truth

AGG-15 code был merged как PR #503, merge commit
`991f961bc41fd2af95b878969d6a9fe3afe9ea87`.

Post-AGG dependency reconciliation выполнен против
`main@27875850a88edf102c904e31955e0df8b78b13b4`.
На этом baseline все AGG-01…AGG-15 имеют canonical merge receipts, включая
AGG-08. Поэтому historical merge-order inversions больше не являются текущими
missing-dependency blockers.

Это не означает full-target operational completion. AGG-15 остаётся fail-closed
до реальных profile-scoped evidence: lender deployment/decoder qualification,
AGG-04 exact campaign на текущей generation, LIVE-03 landing evidence, AGG-09
operational soak/recovery и прочих REQUIRED NF blockers. Структурное наличие
всех 15 merge receipts отделено от external qualification.

## NF-324…NF-328

- **NF-324 / full_coverage_audit** — canonical manifest обязан содержать ровно
  NF-001…NF-328 без duplicate IDs. `mapped=328` считается только структурным
  покрытием. Completion считается лишь для строк с implementation status,
  test refs и evidence refs; `MERGED_CODE` дополнительно требует merge commit.
- **NF-325 / full_integrated_campaign** — campaign evidence должно принадлежать
  одной release generation; unknown-outcome и shared-capacity stress должны быть
  явно подтверждены. Parallel strategies не получают отдельную capital/release
  authority.
- **NF-326 / production_human_handoff** — handoff содержит bootstrap/status/
  stop/recovery команды, remaining scopes и не содержит secrets. Live-default
  запрещён.
- **NF-327 / release_full_target** — AGG-15 формирует reviewable handoff, но не
  подменяет MPR-2612. `production_ready`, `release_claim_allowed`,
  `live_enabled` и automatic scale-up в AGG-15 report всегда false.
- **NF-328 / continuous_evolution** — допустим только цикл
  `record → analyse → hypothesis → reviewed_change → test → qualification →
  scoped_deploy` с независимым promotion gate. Model/research layer не может
  переписать risk authority или auto-enable live.

## Installed command

После установки wheel:

```bash
flashloan-checks release-handoff inspect --manifest /path/to/agg15-handoff.json
flashloan-checks release-handoff check --manifest /path/to/agg15-handoff.json
```

`inspect` показывает точные blockers; `check` остаётся fail-closed, если
manifest неполный или selected profile не qualified.

Минимальная схема manifest:

```json
{
  "schema_version": "agg15.release-handoff.v1",
  "release_id": "immutable-release-id",
  "source_commit": "40-or-64-hex-git-object-id",
  "coverage": [],
  "selected_profiles": [],
  "integrated_campaign": null,
  "operator_handoff": null,
  "continuous_evolution": null,
  "live_enabled": false,
  "automatic_scale_up_allowed": false
}
```

Пустые sections намеренно дают BLOCKED, а не synthetic success.

## Operator bootstrap and recovery boundary

Проверяемые read-only/installed команды текущего продукта:

```bash
flashloan-bot status
flashloan-bot capabilities
flashloan-checks production-debt inspect
flashloan-checks provider-readiness inspect
```

Перед запуском paper/shadow оператор сверяет exact wheel/source/config identity и
AGG-15 manifest. Shutdown выполняется через фактический service manager
deployment profile с сохранением durable SQLite/WAL; после restart сначала
reconcile pending/unknown outcomes и release generation, затем возобновляется
admission. В этот PR не добавляется новый daemon manager и не придумывается
универсальная stop-команда, которой нет у supported entrypoint.

## Evidence and rollback

Focused code evidence:

- `config/agg_merge_receipts.json` — canonical merge/dependency receipts;
- `src/release_gate/agg_debt_closure.py` — historical-order/current-dependency audit;
- `src/release_gate/agg15_release_handoff.py`;
- `tests/test_agg15_release_handoff.py`;
- installed `flashloan-checks release-handoff` command;
- `.github/workflows/agg-15-release-handoff.yml`.

Rollback — revert isolated AGG-15 commits. Он не удаляет lifecycle/release rows,
не переоткрывает settled/unknown attempts и не включает live.
