# AGG-15 — итоговый аудит покрытия и release handoff

AGG-15 остаётся fail-closed audit/handoff layer поверх MPR-2612. Он не является
вторым release authority и не включает live.

## Current dependency truth

Все AGG-01…AGG-15 теперь merged в `main`. Canonical receipts находятся в
`config/agg_merge_receipts.json`; `src/release_gate/agg_debt_closure.py`
проверяет:

- все 15 package identities;
- точные master-DAG dependencies;
- наличие merge commit для каждого AGG;
- historical merge-order inversions отдельно от current unresolved dependencies.

Historical inversions не стираются. Они объясняют, почему старые package docs
могут содержать “prerequisite missing”, но после reconciliation не считаются
текущими blockers автоматически.

SUPER-08 расширяет тот же canonical audit target с NF-328 до NF-352. NF-329…352
не создают нового AGG-15 ownership и сохраняют владельцев continuation crosswalk:

- NF-329…332 → TREASURY-01 / PR-073;
- NF-333…336 → BATCH-01 / PR-074;
- NF-337…340 → UNIVERSE-01 / PR-075;
- NF-341…344 → ALT-01 / PR-076;
- NF-345…348 → FORMAT-01 / PR-077;
- NF-349…352 → FORMAT-02 / PR-078.

Release-handoff schema поэтому остаётся текущей v2; legacy 328-row v1 manifest
не может быть молча повышен до current full-target evidence.

## Code-debt closure

Post-AGG reconciliation закрывает оставшийся code-side financing debt:

- lender-neutral FinancingPort adapters для Jupiter Lend и Slumlord;
- PRIMARY + RENT obligations в одном immutable plan;
- lender-bound planner provenance;
- post-simulation lender repayment decoder boundary;
- lender-neutral canonical economic reconciliation;
- generic CORE-V1 composition с теми же lifecycle/capital/runtime owners;
- installed default-off Jupiter Lend profile reachability;
- stale AGG-03/09/15 dependency records заменены current receipts.

Code closure не превращает отсутствующее network evidence в qualification.

## NF-324…NF-352

- **NF-324 / full_coverage_audit** — canonical current full-target manifest
  содержит NF-001…NF-352 без duplicate IDs. Mapped coverage и completion остаются
  разными понятиями; merge receipt без tests/evidence не равен completion.
- **NF-325 / full_integrated_campaign** — campaign должна принадлежать одной
  release/profile/program/data generation и включать unknown-outcome/shared-capacity
  stress.
- **NF-326 / production_human_handoff** — bootstrap/status/stop/recovery commands
  не содержат secrets и не включают live по умолчанию.
- **NF-327 / release_full_target** — canonical promotion остаётся у MPR-2612.
  `production_ready`, `release_claim_allowed`, `live_enabled` и automatic
  scale-up остаются false до реального evidence.
- **NF-328 / continuous_evolution** — только
  `record → analyse → hypothesis → reviewed_change → test → qualification →
  scoped_deploy` с независимым promotion gate.
- **NF-329…352** — учитываются через SUPER-08 continuation owners и v2 handoff;
  AGG-15 не присваивает себе их runtime/economic authority.

## SUPER-08 product boundary

W2-22 / PRODUCT-01 остаётся у уже merged AGG-14 research/product package.
RELEASE-01 только потребляет явное evidence, что product accounting и execution
authority разделены. V2 handoff включает `product_boundary` evidence, связывающий
существующего product owner и `RevenueAttributionLedger`, при этом доказывая:

- service/grant/rebate revenue не является arbitrage PnL;
- client funds не являются trading capital;
- product planning surface не может sign/submit;
- audit не выполняет remote product/service mutation.

Эти проверки не считаются внешней qualification Kora, keeper customer, data
product или grant и не дают trading permissions.

## Remaining blockers are qualification debt

Current code/dependency ordering больше не является blocker. Остаются evidence,
которые этот code-only closure не имеет права выдумывать:

1. qualified Jupiter Lend deployment/account/fee evidence;
2. qualified Slumlord executable/PDA/deployment evidence;
3. post-simulation lender repayment decoder conformance on loaded state;
4. exact AGG-04 campaign regenerated on merged source/wheel/profile;
5. observed LIVE-03 finalized landing evidence;
6. real AGG-09 operational soak and recovery/performance evidence;
7. external chain/venue/protocol evidence для optional/deferred AGG/SUPER scopes,
   где их собственная coverage остаётся UNQUALIFIED/BLOCKED.

## Installed commands

```bash
flashloan-checks release-handoff inspect --manifest /path/to/agg15-handoff.json
flashloan-checks release-handoff check --manifest /path/to/agg15-handoff.json
flashloan-checks production-debt inspect
flashloan-checks provider-readiness inspect
```

Текущая минимальная handoff schema использует
`schema_version = "agg15.release-handoff.v2"` и содержит `product_boundary`.
Структурно полный handoff всё ещё может быть operationally BLOCKED.

## Evidence and rollback

- `config/agg_merge_receipts.json`
- `src/release_gate/agg_debt_closure.py`
- `tests/test_agg_dependency_reconciliation.py`
- `release_artifacts/agg/AGG-15/tech_debt_closure.json`
- `src/release_gate/agg15_release_handoff.py`
- `tests/test_agg15_release_handoff.py`
- `.github/workflows/agg-15-release-handoff.yml`
- `.github/workflows/super-08-product-release.yml`

Rollback debt-closure/SUPER-08 layers не должен удалять lifecycle rows,
reservations, settlement history или reinterpret old evidence under a new
generation.
