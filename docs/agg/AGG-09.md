# AGG-09 — эксплуатация, восстановление и выпуск проверенных профилей

## Scope

AGG-09 реализован как default-off operational evidence layer поверх существующих владельцев:
MPR-2613 guarded operations, MPR-2616 HA/DR, MPR-2618 credential rotation,
PR-077/PR-201 observability/readiness и MPR-2614 continuous conformance.
Новый ledger, signer, sender, submission authority или live OMS не создаётся.

Исторический base при старте: `0c4f216a62d62b20f6fb4ec4bbd0548cea58df65`.
AGG-09 был merged как PR #505, merge commit
`5d1d8177c933221dcb31baf0753924c4f32e3313`.
Post-AGG reconciliation выполнен против
`main@27875850a88edf102c904e31955e0df8b78b13b4`, где AGG-04, AGG-05 и
AGG-08 уже имеют canonical merge receipts.

## Work packages

### OPS-01

`src/operations/agg09_ops01.py` связывает NF-240/243/244/245/246:

- portfolio budget считает только owned equity и агрегирует reservations, unknown exposure,
  worst-failure exposure и provider spend по общему asset cap;
- collateral, lender capacity и client capital не становятся equity;
- recovery использует MPR-2616 `RestoreEvidence`/`CoordinatorCapabilities`, требует новый
  fence generation и quarantine unknown dispatches;
- production HA квалифицируется отдельно от безопасного default-off restore;
- security conformance требует endpoint/SSRF/DNS/TLS/redirect/input/archive/filesystem
  hardening evidence от существующих transport/filesystem owners;
- credential recovery не допускает rollback rotation/revocation epochs или resurrection
  revoked versions.

### OPS-02

`src/operations/agg09_ops02.py` связывает NF-247/248/249/250:

- p50/p95/p99, gaps, dropped work, quota, errors, stalled state и unresolved reconciliation;
- process liveness не повышает market readiness;
- operator actions ограничены inspect/pause/resume-shadow/stop и делегируются в
  MPR-2613 durable state/audit owner;
- отсутствует команда перехода в ACTIVE/live;
- performance change допускается только при том же semantic hash и измеримом tail uplift;
- data-platform scale обязан сохранять replay, identity, cursor, quota и economic authorities.

### OPS-03

`src/operations/agg09_ops03.py` связывает NF-251/252/253/254/255/256:

- CI matrix не превращает blocked/not-authorized network/live suites в pass;
- release artifact связывает exact source/tree/wheel/image/lock/SBOM/NOTICE/config/policy;
- MPR-2614 continuous conformance перенесён из stacked PR #492 в достижимый `main`-path;
- soak требует заранее объявленной длительности, busy/quiet windows, restart/failover drills,
  полного incident accounting и точного ledger recovery;
- capital progression всегда manual: measured blocker + fee reserve + canary + explicit approval;
- production-readiness verdict fail-closed требует AGG-04, AGG-05, AGG-08, LIVE-03,
  OPS-01/02, CI, release, current conformance lease, soak и известные rights/reserves.

Даже положительный verdict остаётся `qualified-default-off`; `live_enabled=false` и
`automatic_scale_up_allowed=false`.

## Current disposition

Кодовый пакет AGG-09 уже merged и все его package prerequisites (AGG-04,
AGG-05, AGG-08) присутствуют в текущем reconciliation baseline. Исторические
"prerequisite not on starting main" больше не являются текущими blockers.

`implementation_status`: `MERGED_CODE`.
`operational_status`: `BLOCKED`.

Оставшиеся blockers являются evidence/operations, а не отсутствующими AGG PR:

- реальные LIVE-03 landing/finalized labels для выбранного exact profile;
- predeclared operational soak NF-254 с busy/quiet windows и incident accounting;
- production cross-host coordinator/signer recovery evidence;
- измеренный workload/scale evidence;
- новая post-merge qualification generation, связывающая source/wheel/config/data/
  financing deployment и release artifacts.

Synthetic duration/PnL, старые branch-head результаты и сам факт merge не закрывают
эти требования.

## Focused verification

```bash
python -m pytest \
  tests/test_agg09_ops01.py \
  tests/test_agg09_ops02.py \
  tests/test_mpr2614_continuous_conformance.py \
  tests/test_agg09_ops03.py \
  tests/test_mpr2613_guarded_operations.py \
  tests/test_mpr2616_executable_ha_dr.py \
  tests/test_mpr2618_credential_trust_rotation.py \
  tests/security/test_mpr_td_04_security.py
python -m compileall -q src/operations/agg09_ops01.py src/operations/agg09_ops02.py \
  src/operations/agg09_ops03.py src/operations/mpr2614_continuous_conformance.py
```

Repository-wide `verify` and package smoke remain required before merge.

## Rollback

Revert the AGG-09 PR. No migration rewrites existing MPR-2613/2616/2618 durable state.
Removing the evidence/composition layer must not delete settled or unknown attempts,
reservations, revocation history or recovery evidence.
