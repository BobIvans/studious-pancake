# PR-196 — Cross-plane terminal truth and projection reconciliation

## Safety invariant

An observability event is a candidate fact, not financial authority. A raw
`attempt_terminal`, `balance_reconciled`, or `reconciliation_completed` row may
remain in the append-only event ledger for forensic visibility, but it cannot
count as success, P&L, soak evidence, or release evidence until PR-196 verifies
it against all required authority planes.

## Truth hierarchy

- lifecycle state and reservation terminalization: lifecycle authority;
- finalized transaction/settlement: settlement authority;
- asset-denominated financial posting: ledger authority;
- release and PolicyBundle approval: release-policy evidence;
- observability: append-only candidate evidence;
- metrics: derived only from `CrossPlaneTruthStore`.

The verified projection uses a separate SQLite product. This is intentional: it
avoids silently extending the observability database while PR-195 establishes
one-product-per-database schema ownership and migration fencing.

## Verified success contract

A success candidate must bind the same attempt ID/generation, opportunity, plan
hash, message hash, lifecycle event/hash, consumed reservation, finalized
signature/slot, settlement digest, ledger posting/hash, exact mint and integer
base-unit amount, release hash, PolicyBundle hash, and non-placeholder producer
provenance. The structured `realized_pnl` and `EvidenceRef` must repeat the same
settlement and accounting identity.

Missing, malformed, stale, epoch-regressed, or cross-plane-mismatched evidence
produces `ambiguous`; opposite terminal outcomes produce `conflicted`. Neither
state is counted as financial success and both hold `release_ready=false`.

## Watermarks and rebuild

Each authoritative plane supplies an immutable database epoch and monotonic
sequence. Epoch changes and sequence regressions fail closed. Reconciliation
runs are append-only, projection rows are rebuildable in canonical event order,
and the projection checksum excludes wall-clock fields so repeated rebuilds are
deterministic.

## Metrics

`rejection_funnel()` remains operational-only and does not expose financial
success. `verified_terminal_summary()` reads only `CrossPlaneTruthStore` and
fails closed with zero successes when the reconciled projection is not wired.
`daily_shadow_summary()` adds terminal truth only when composition explicitly
provides the verified store, preserving the historical output otherwise.

## Verification

```bash
python -m pytest tests/test_pr196_cross_plane_terminal_truth.py -q
python -m compileall -q src tests
python scripts/verify_repo.py
```

Focused coverage includes fake terminal events, fully verified success,
ledger/settlement disagreement, explicit terminal conflict, watermark-backed
metrics, and deterministic projection rebuild.

## Parallel compatibility

The implementation is additive except for the narrow metrics/export surface in
`src/observability/__init__.py` and `src/observability/metrics.py`. It does not
modify the existing observability schema, lifecycle schema, settlement schema,
accounting schema, provider/runtime code, or live submission behavior. PR-195
can therefore establish authoritative database epochs without this branch
claiming ownership of its migration work.
