# PR-193 — Explicit resource ownership and deterministic shutdown

This slice introduces the first active resource-ownership boundary for long-lived
SQLite resources without enabling live trading or changing provider behavior.

## Ownership contract

Every resource registered in `ResourceGraph` is classified explicitly:

- `owned`: the graph closes it exactly once;
- `borrowed`: the graph records it but never closes it;
- `shared`: lifetime is controlled by an external shared owner.

The graph closes owned resources in reverse registration order. It supports both
synchronous `close()` and asynchronous `aclose()` resources and records stable,
non-sensitive close failures by resource ID and exception type.

## SQLite lifecycle

`SQLiteAttemptJournal` now provides:

- idempotent `close()`;
- synchronous and asynchronous context-manager support;
- rollback of an active transaction before shutdown;
- a bounded WAL truncate checkpoint for file-backed databases;
- explicit `closed` and `resource_id` state.

`ClosableLiveControlStore` supplies the same lifecycle contract for the existing
live control SQLite store. `LiveControlResources` is the composition-owned seam
that opens the journal and control store, registers them as owned, closes them in
reverse order, and cleans up already-opened resources when later startup fails.

Injected resources remain borrowed unless the caller explicitly transfers
ownership. This prevents resource hardening from introducing double-close bugs
for shared transports, quota managers, discovery planes, or stores.

## Verification

Focused tests cover:

- reverse close order;
- borrowed/shared lifetime preservation;
- duplicate ownership rejection;
- mixed sync/async resources;
- live-control journal/store composition;
- borrowed SQLite composition;
- failed-start cleanup;
- forty repeated WAL open/close cycles with a bounded file-descriptor budget.

Suggested repository verification:

```bash
python -m pytest tests/test_pr193_resource_ownership.py -q
python -m compileall -q src tests
python scripts/verify_repo.py
```

## Parallel compatibility

The slice is additive except for the narrow lifecycle extension in
`src/execution/journal.py`. It deliberately avoids active high-churn discovery,
paper-runtime, Helius ingress, CLI-contract, workflow, packaging, and dependency
files being changed by parallel PRs.

## Non-goals

This slice does not claim all PR-193 acceptance criteria are complete. Follow-up
integration must migrate remaining direct `LiveControlStore` construction sites,
add explicit lifecycle contracts to every other long-lived client/store/task
owner, connect process-wide composition and shutdown ordering, and produce the
72-hour soak and repeated failover evidence.
