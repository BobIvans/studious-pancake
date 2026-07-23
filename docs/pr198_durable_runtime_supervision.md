# PR-198 durable runtime supervision slice

This slice extends the already-merged PR-198 sender-free evidence gate with a
focused offline contract for the runtime defects identified in the July 23
production-readiness pass.

## Boundary

The module `src/paper_shadow/durable_runtime_supervision_pr198.py` is deliberately
sender-free. It does not import a signer, sender, wallet, Jito client, RPC send
transport, live permit, or live trading surface. It only validates already
materialized supervision evidence.

## Findings covered

This slice maps to the PR-198 acceptance boundary for:

- strategy task failure must immediately make readiness false;
- the installed paper/shadow surface must be one real production factory, not
  placeholder dependencies;
- opportunity expiry must release pending lifecycle eligibility;
- queue drain must be durable and have exactly one consumer owner;
- shutdown must have structured concurrency, cancellation acknowledgement and
  bounded fallback behavior;
- terminal queue actions must be durable outcome, durable requeue or durable
  abandon records;
- memory-only trackers/results and sender/live/signer surfaces remain release
  blockers.

## What readiness means

A clean `RuntimeSupervisionReadiness` means only:

```text
ready_for_sender_free_shadow=true
live_execution_allowed=false
sender_import_allowed=false
signing_allowed=false
```

It does not authorize PR-199 live submission. It provides a narrower evidence
contract that PR-199 can require before any isolated signer or finality boundary
is connected.

## Evidence artifacts

The evaluator requires hashes for:

- `runtime_trace_sha256`
- `shutdown_trace_sha256`
- `queue_lifecycle_sha256`

These are intentionally hash identities, not raw logs, so the report can remain
redacted and immutable while still binding the reviewer to concrete artifacts.
