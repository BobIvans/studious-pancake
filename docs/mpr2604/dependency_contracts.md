# MPR-2604 dependency contracts

Observed 2026-09-09 (Europe/Riga).

| logical task | actual PR | base | head | status | ownership / integration rule |
|---|---:|---|---|---|---|
| MPR-2601 | #472 | prior main | merged as `68788d7f7f7da8a2e03b170f93c48af7421ee805` | merged | Preserve `UnifiedLifecycleAuthority` and `DurableCapitalCoordinator`; do not create competing lifecycle/capital owners. |
| MPR-2602 | #473 | `68788d7f7f7da8a2e03b170f93c48af7421ee805` | `f9cb2632c376839042199fefcf9255f64364031d` | open draft | Provider governance/offline connection profiles are predecessor-owned. MPR-2604 does not copy or activate them. Integrate only after accepted predecessor merge/rebase. |
| MPR-2603 | unknown | unknown | unknown | `UNOBSERVED_PREDECESSOR` | No public PR/ref was observed before this slice. Do not guess its ownership or overwrite future work. |
| MPR-2604 | this branch | `68788d7f7f7da8a2e03b170f93c48af7421ee805` | branch head | implementation slice | Owns readiness-report trust regression and explicit installed paper lifecycle controls in this slice only. |
| provider governance | #467 | inspect before integration | inspect before integration | open predecessor | Preserve its quota/deadline authority. |
| human intervention | #470 | inspect before integration | inspect before integration | open predecessor | Preserve one-shot human permit authority; do not emulate a second human approver. |

## Implemented in this slice

### F03 — unsafe qualification overlay

`scripts/production_debt_audit.py` now treats the legacy qualification file as non-authoritative metadata. A user-controlled `debt_resolution.*.resolved=true`, `qualified=true`, `product_state=production-ready`, or `live_mode_available=true` cannot delete canonical blockers or promote readiness. Claimed resolutions remain visible for diagnostics under `claimed_resolved_by_release_qualification`; `resolved_by_release_qualification` remains empty until a trusted release-bound verifier exists.

Regression coverage: `tests/test_production_debt_audit_release_qualification.py` and `tests/test_mpr2604_production_closure.py`.

### F04 — output/state arguments changed service lifetime

`flashloan-bot run --mode paper` now has explicit `--once` and `--max-cycles N` lifecycle controls. `--json` changes representation only. `--db-path` changes state location only. Neither implies one-cycle smoke behavior.

The existing internal `legacy_smoke` parameter remains only as a compatibility hook for tests/internal callers; the installed CLI does not derive it from `--json` or `--db-path`.

Regression coverage: `tests/test_mpr2604_production_closure.py` plus existing MPR-2601 supervisor/drain tests.

## Intentionally not claimed complete

This branch does **not** enable live mode, signing, submission, lender failover, external provider credentials, canary execution, or production approval. It does not claim MPR-2604 as globally complete.

Still open from the supplied MPR-2604 task include F01 (installed runtime dependency wiring), F02 (verification-backed generic debt disposition), F05 (semantic source/wheel parity), F06-F09, lender/deployed conformance, provider/soak evidence, finalized economic proof, image provenance, human/canary approvals, and remaining A01-A80 acceptance coverage.

## Merge discipline

Before merging, re-check #473 and any newly published MPR-2603 ref. If they touch `src/runtime/runtime_entrypoint.py`, `scripts/production_debt_audit.py`, shared schemas, manifests, or accepted authorities, reconcile their contract and tests rather than choosing `ours`/`theirs` blindly.
