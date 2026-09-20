# AGG-15 — итоговый аудит покрытия и release handoff

AGG-15 реализует RELEASE-01 как fail-closed слой аудита поверх существующих
owners. Он не становится вторым release authority: production promotion остаётся
у MPR-2612, а live не включается этим пакетом.

## Current base and dependency truth

Clean rebase base:

`main@baedd8c0697c0bf789e582dab8acf5bbc113c123`.

На этом base код AGG-14/RND-04 уже слит через PR #509, но остаётся
offline/default-off и operationally UNQUALIFIED. AGG-09/OPS-03 ещё не принят
как merged operational prerequisite. Поэтому merge этого PR означает
code-level availability AGG-15 audit contracts, а не full-target completion,
external qualification, production promotion или live admission.

## NF-324…NF-328

SUPER-08 extends the same canonical audit target through NF-352.  NF-329…352
are not new AGG-15 ownership: they retain their primary owners from the
PR-073…078 continuation crosswalk:

- NF-329…332 → TREASURY-01 / PR-073;
- NF-333…336 → BATCH-01 / PR-074;
- NF-337…340 → UNIVERSE-01 / PR-075;
- NF-341…344 → ALT-01 / PR-076;
- NF-345…348 → FORMAT-01 / PR-077;
- NF-349…352 → FORMAT-02 / PR-078.

The release-handoff schema is therefore v2. A legacy 328-row v1 manifest is not
silently promoted into current full-target evidence.

- **NF-324 / full_coverage_audit** — canonical manifest обязан содержать ровно
  NF-001…NF-352 без duplicate IDs. `mapped=352` считается только структурным
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
  "schema_version": "agg15.release-handoff.v2",
  "release_id": "immutable-release-id",
  "source_commit": "40-or-64-hex-git-object-id",
  "coverage": [],
  "selected_profiles": [],
  "integrated_campaign": null,
  "operator_handoff": null,
  "continuous_evolution": null,
  "product_boundary": null,
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

- `src/release_gate/agg15_release_handoff.py`;
- `tests/test_agg15_release_handoff.py`;
- installed `flashloan-checks release-handoff` command;
- `.github/workflows/agg-15-release-handoff.yml`.

Rollback — revert isolated AGG-15 commits. Он не удаляет lifecycle/release rows,
не переоткрывает settled/unknown attempts и не включает live.


## SUPER-08 product boundary

W2-22 / PRODUCT-01 remains owned by the already merged AGG-14 research/product
package. RELEASE-01 only consumes explicit evidence that product accounting and
execution authority remain separated. A v2 handoff therefore includes
`product_boundary` evidence binding the existing product owner and
`RevenueAttributionLedger` while proving:

- service/grant/rebate revenue is not arbitrage PnL;
- client funds are not trading capital;
- the product planning surface cannot sign or submit;
- this audit does not perform remote product/service mutation.

These checks do not externally qualify Kora, a keeper customer, a data product,
or a grant. Their external blockers remain explicit and do not become trading
permissions.
