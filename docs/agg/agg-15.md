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

## NF-324…NF-328

- **NF-324 / full_coverage_audit** — mapped coverage и completion остаются
  разными понятиями. Merge receipt без tests/evidence не равен completion.
- **NF-325 / full_integrated_campaign** — текущая integrated campaign должна
  принадлежать одной release/profile/program/data generation и включать
  unknown-outcome/shared-capacity stress.
- **NF-326 / production_human_handoff** — bootstrap/status/stop/recovery
  commands не содержат secrets и не включают live по умолчанию.
- **NF-327 / release_full_target** — canonical promotion остаётся у MPR-2612.
  `production_ready`, `release_claim_allowed`, `live_enabled` и automatic
  scale-up остаются false до реального evidence.
- **NF-328 / continuous_evolution** — только
  `record → analyse → hypothesis → reviewed_change → test → qualification →
  scoped_deploy` с независимым promotion gate.

## Remaining blockers are qualification debt

Current code/dependency ordering no longer blocks the aggregate program.
Remaining blockers require evidence that this code-only closure must not invent:

1. qualified Jupiter Lend deployment/account/fee evidence;
2. qualified Slumlord executable/PDA/deployment evidence;
3. post-simulation lender repayment decoder conformance on loaded state;
4. exact AGG-04 campaign regenerated on the merged source/wheel/profile;
5. observed LIVE-03 finalized landing evidence;
6. real AGG-09 operational soak and recovery/performance evidence;
7. external chain/venue/protocol evidence for optional/deferred AGG scopes where
   their own coverage says UNQUALIFIED/BLOCKED.

These stay visible in the current closure artifact rather than being relabelled
as code completion.

## Installed commands

```bash
flashloan-checks release-handoff inspect --manifest /path/to/agg15-handoff.json
flashloan-checks release-handoff check --manifest /path/to/agg15-handoff.json
flashloan-checks production-debt inspect
flashloan-checks provider-readiness inspect
```

A structurally complete handoff can still be operationally BLOCKED. That is the
intended state until the required real campaigns exist.

## Evidence

- `config/agg_merge_receipts.json`
- `src/release_gate/agg_debt_closure.py`
- `tests/test_agg_dependency_reconciliation.py`
- `release_artifacts/agg/AGG-15/tech_debt_closure.json`
- existing `src/release_gate/agg15_release_handoff.py`

Rollback of this closure must not delete lifecycle rows, reservations,
settlement history, or reinterpret old evidence under a new generation.
