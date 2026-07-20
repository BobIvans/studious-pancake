# PR-077 Operator readiness runbook

PR-077 composes the earlier data-plane, lifecycle and health primitives into a
single offline operator-readiness evidence gate.  It is intentionally a review
surface, not a live activation path.

## Evidence inputs

The `OperatorReadinessGate` requires:

- one stable trace id shared by discovery, quota, candidate, planner,
  simulation and reconciliation stages;
- stage metrics for discovery, quota, candidate, planner, simulation and
  reconciliation;
- data-plane readiness from the PR-040 RPC/WebSocket/oracle boundary;
- HTTP `/health` and `/ready` state from the PR-042 status surface;
- lifecycle recovery evidence for discovery, capital reservation, planner,
  final simulation, reconciliation and paper outcome;
- backup/restore evidence with real SHA-256 artifacts;
- migration and corruption drill confirmation;
- proof that logs are redacted and no raw private data was emitted.

## Fail-closed cases

The gate blocks operator readiness when any of these happen:

- RPC stale/fork/divergence evidence is present;
- WebSocket gap, resubscribe or stale heartbeat evidence is present;
- oracle source, age or confidence evidence is not acceptable;
- reconciliation is indeterminate;
- `/health` or `/ready` is not OK;
- a lifecycle recovery stage is missing or replay is unsafe;
- restart produces a duplicate paper outcome or duplicate reservation;
- backup/restore evidence is missing, unreviewed or lacks migration/corruption
  drill coverage;
- logs are not redacted or raw private material is reported;
- any status payload says live, signing or submission has been enabled.

## Safety boundary

A passing PR-077 result means only:

```text
operator-ready-for-shadow-soak-review
```

It does not enable signing, submission, Jito/RPC transport, canary arming,
permit issuance, wallet mutation or live mode.
