# PR-199 — Operations, observability, signed releases and disaster recovery

This PR starts the V3 roadmap meaning of **PR-199**. The V3 audit supersedes the prior implementation grouping and defines PR-199 as the operations boundary before any default-off live boundary can be reviewed.

## Scope

`src/production_operations_pr199.py` adds a deterministic offline validator for `pr199.operations-release-dr.v1` evidence. The gate checks that a release candidate has:

- signed release-manifest evidence;
- independent review identity;
- source, wheel, image, SBOM, provenance, config, policy, capability and database-schema hash binding;
- separated liveness and readiness semantics;
- readiness closure on dead strategy, stale rooted data, DB degradation, admission latch and outbox backlog;
- authenticated management/readiness control plane evidence;
- redacted, low-cardinality observability export;
- trace binding to attempt, release and config generation;
- signed and generation-bound backup evidence;
- atomic restore via temporary sibling validation rather than direct overwrite;
- previous-generation preservation;
- event replay matched against materialized state;
- SLO budgets and fault-drill evidence for the V3 PR-199/DR failure modes;
- deployment hardening evidence while keeping live disabled.

## Safety boundary

This module does **not** perform deployment, rollback, database restore, signer access, private-key access, transaction construction, simulation, RPC/Jito submission, live trading or cutover.

Both safety functions are hard-denied by construction:

```python
live_capability_allowed() is False
cutover_capability_allowed() is False
```

## Why this is PR-199 and not PR-200

The uploaded V3 roadmap moves live signer/sender/finalized settlement into PR-200 and defines PR-199 as:

> Operations, observability, signed releases and disaster recovery.

This PR therefore intentionally stops before live signing and focuses on the evidence that must exist before the live boundary can be reviewed.

## Local verification

```bash
python -m pytest \
  tests/test_pr199_production_operations.py \
  -q --disable-socket --allow-unix-socket
python -m compileall -q \
  src/production_operations_pr199.py \
  tests/test_pr199_production_operations.py
```

## Remaining PR-199 work

This is a safe foundation slice, not a full operations cutover claim. Remaining work includes wiring the validator into release qualification, capturing real signed release manifests, real backup/restore artifacts, alert snapshots, SLO dashboard exports, chaos-run outputs and merge-commit evidence after PR-194…PR-198 are accepted.
