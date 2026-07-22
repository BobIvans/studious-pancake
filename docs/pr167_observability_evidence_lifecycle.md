# PR-167 — Observability, evidence lifecycle and data-governance scalability

This PR starts the PR-167 work as a review-safe, side-effect-free governance
contract. It does **not** change trading logic, runtime execution, alert delivery,
database writers, object-store uploads, CLI commands, or live/canary behaviour.

## Why this exists

PR-156 is intended to make the paper runtime durable, and PR-164 is intended to
route alerts. PR-167 covers the long-term data lifecycle after events, evidence,
metrics and logs exist. The goal is to prevent observability and evidence from
becoming unbounded, unaffordable, unqueryable, unsafe to correct, or unsafe to
purge.

## Scope

The patch adds `src/pr167_observability_governance.py`, a pure evaluator and data
model covering:

- field-level data classification;
- retention classes and minimum audit/financial retention;
- storage budgets for lifecycle DB, observability DB, WAL, evidence objects,
  logs, metric series and traces;
- tiered evidence object policy with encryption, content-addressing and verified
  retrieval;
- immutable evidence correction / supersession chains;
- Prometheus-safe metric label policy and estimated series budget;
- required SLO histogram inventory;
- WAL checkpoint / compaction / fail-closed policy;
- signed archive/delete manifests;
- access audit and operational cost-budget evidence.

The evaluator can only return `ready-for-manual-review` or `blocked`. It always
keeps runtime execution disabled:

```text
runtime_live_enabled = false
write_path_can_purge_financial_evidence = false
```

## Safety boundary

This PR deliberately avoids:

- database schema migrations;
- retention deletes;
- object-store writes;
- metrics endpoint changes;
- logging/tracing integration;
- live admission;
- trading economics;
- signer/sender/provider calls;
- alert delivery.

## Acceptance mapping

| PR-167 requirement | Implemented review-safe contract |
|---|---|
| Every durable field has classification | `DataFieldPolicy` and `RetentionPolicy` |
| Growth remains bounded | `StorageBudget.evaluate(...)` |
| No high-cardinality metric labels | `MetricDefinition` and `MetricCardinalityPolicy` |
| Required SLO metrics cannot be `N/A` | `SLOMetricSet` requires populated histograms |
| Large evidence is content-addressed | `EvidenceObjectPolicy` for oversized payloads |
| Correction is immutable | `EvidenceCorrection` and authoritative view builder |
| Financial/audit evidence cannot be purged early | `validate_archive_delete_manifest(...)` |
| WAL/compaction fails closed | `WALCompactionPolicy` |
| Archive/delete has signed manifest | `ArchiveDeleteManifest` |
| Cost/access governance exists | `PR167GovernancePackage` blockers |

## Suggested verification

```bash
python -m pytest tests/test_pr167_observability_governance.py -q
python -m compileall -q src tests
```

## Deferred work

Future implementation work should wire this contract into the actual observability
store, lifecycle DB, object storage, metrics exporters, compaction job and access
audit system. This PR only creates the safe review boundary and tests the critical
fail-closed rules.
