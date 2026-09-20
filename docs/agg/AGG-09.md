# AGG-09 — эксплуатация, восстановление и выпуск проверенных профилей

## Current dependency truth

AGG-09 code was merged in PR #505 before all master-DAG prerequisites were
merged. That historical order is preserved as evidence, not treated as current
dependency state.

Current reconciliation baseline: `main@27875850a88edf102c904e31955e0df8b78b13b4`.

Now merged:

- AGG-04 / qualification framework — PR #497;
- AGG-05 / parallel scheduler and bounded search — PR #498;
- AGG-08 / isolated signing/submission/finalized settlement closure — PR #504.

Therefore the old blockers “AGG-04/05/08 prerequisite not on starting main” are
obsolete and must not appear in current readiness output.

## Code state

AGG-09 continues to reuse the existing owners:

- MPR-2613 guarded operations;
- MPR-2616 HA/DR and fencing;
- MPR-2618 credential rotation;
- PR-077/PR-201 observability/readiness;
- MPR-2614 continuous conformance.

It does not create a second ledger, signer, sender, lifecycle authority or live
OMS. Code merge remains default-off.

## Remaining operational qualification blockers

The following are **not code-order debt** and cannot be closed by synthetic CI:

1. **AGG09_LIVE03_OBSERVED_LANDING_EVIDENCE_MISSING** — AGG-08 code can produce
   finalized-only labels, but no real sent/finalized campaign is claimed here.
2. **AGG09_REAL_OPERATIONAL_SOAK_MISSING** — NF-254 requires a predeclared real
   soak with busy/quiet windows, incidents, restart/failover and exact recovery.
3. **AGG09_CROSS_HOST_RECOVERY_EVIDENCE_MISSING** — production coordinator /
   signer failover requires external host/service evidence.
4. **AGG09_REAL_WORKLOAD_PERFORMANCE_EVIDENCE_MISSING** — p50/p95/p99,
   backpressure, gaps, dropped work and quotas must come from a real scoped
   workload.
5. **AGG09_CURRENT_PROFILE_CAMPAIGN_REQUIRED** — AGG-03/04 evidence must be
   regenerated for the exact merged source, wheel, profile, lender deployment,
   config and data generations after the tech-debt closure.

A future positive verdict remains `qualified-default-off`; it does not imply
live authorization or automatic capital growth.

## Status

- implementation: **MERGED_CODE**
- operational: **BLOCKED**
- live_enabled: **false**
- automatic_scale_up_allowed: **false**

The machine-readable current blocker set is maintained in
`release_artifacts/agg/AGG-09/coverage.json`.
