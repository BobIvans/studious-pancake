# PR-031 — Jupiter account-wide quota and bounded route scheduler

## Purpose

PR-031 introduces the shared Jupiter quota boundary required before route
discovery, route refinement and final build/finalization are wired into one
runtime.  The goal is to avoid the pre-audit problem where different Jupiter
callers could each believe they were under quota while collectively exhausting
the same account/API-key budget.

## Runtime boundary

All active Jupiter callers must share one `JupiterQuotaManager` instance:

- discovery and refinement cannot spend the protected finalization reserve;
- finalization can use the protected reserve because it is proof-critical;
- `429` and `Retry-After` move the manager into a temporary fail-closed circuit;
- identical request fingerprints can use a short TTL cache instead of spending
  another upstream request;
- metrics are redaction-safe and expose only counters, state and timing.

This PR intentionally does **not** add live execution, transaction sending,
unbounded route search or a second Jupiter HTTP client.

## Route attempts

`JupiterRouteAttemptScheduler` creates a deterministic finite attempt plan from:

- a universal safety envelope;
- configured account-budget steps;
- bounded include/exclude DEX profiles;
- deadline, quote age, edge and quota stop conditions.

Fallback profiles cannot relax the safety envelope.  If the scheduler returns an
exhausted stop reason, the correct downstream decision is retry later or
`NO_TRADE`, not continued probing.

## Parallel PR compatibility

This branch starts from `main` and avoids external-contract registry,
MarginFi binary layout and canonical execution-domain files that are being
changed in parallel PR-027/PR-029 tracks.  The scheduler is transport-neutral and
can be connected by PR-030/PR-033 once the discovery plane and detector runtime
are merged.
