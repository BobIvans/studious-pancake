# MPR-07 operations authority and promotion gate

This slice starts **MPR-07 — Operations authority, signed promotion, legacy deletion and tiny canary** from the V4 runtime-cutover roadmap.

MPR-07 is the final review/promotion boundary after MPR-01...06. It must reject empty, stale, non-finite or unsigned evidence; verify approvals over the exact release bundle; enforce aggregate tiny-canary loss limits; require rollback to shadow; and keep live capability disabled until all prerequisite evidence has passed.

## Scope

This additive gate validates already-materialized promotion evidence for:

- typed finite observability/readiness telemetry;
- freshness against trusted evaluation time;
- secret-like telemetry key rejection;
- signed release/deployment/backup/soak/rollback artifacts;
- identity-backed operator/risk/security approvals bound to the exact bundle;
- current-time approval expiry and revocation checks;
- one-transaction tiny canary budget inequality;
- rollback triggers and post-canary independent review;
- legacy cleanup declaration;
- continued absence of live, signer and sender surfaces.

## Non-goals

This PR does **not** enable or implement:

- live trading;
- signer/private-key access;
- sender, RPC or Jito submission;
- provider network calls;
- canary transaction execution;
- production deployment or runtime cutover.

It is a review-only acceptance contract that future real MPR-05/MPR-06 evidence must satisfy before a manual tiny canary can even be reviewed.

## Verification

```bash
python -m py_compile \
  src/release_gate/mpr07_operations_promotion_gate.py \
  tests/test_mpr07_operations_promotion_gate.py
python -m pytest -q tests/test_mpr07_operations_promotion_gate.py
```

A clean report still returns:

```text
live_execution_allowed=false
signer_allowed=false
sender_allowed=false
```
