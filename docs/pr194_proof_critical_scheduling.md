# PR-194 — Proof-critical quota and fair workload scheduling

## Problem

The existing Jupiter route scheduler applied the non-finalization quota cap to the
entire attempt plan. Once discovery occupied `limit - finalization_reserve`, the
plan stopped before constructing profiles even though the quota manager still
allowed finalization. Finalization profiles were also appended after discovery
and refinement and could be removed by `profiles[:max_attempts]`.

The strategy runtime additionally exposes one global priority queue without a
required-work reserve, per-strategy/provider caps, aging, deadline feasibility,
weighted fairness, or isolated concurrency for finalization and settlement.

## Active Jupiter correction

`src/providers/jupiter/scheduler.py` now:

- evaluates quota capacity for every profile's own purpose;
- skips discovery/refinement profiles when their shared cap is full;
- preserves finalization while the protected reserve is available;
- returns quota exhausted only when no profile remains eligible;
- validates that at least one finalization profile exists;
- allocates finalization profiles inside `max_attempts` before optional profiles.

## Fair scheduling boundary

`src/proof_critical_scheduler_pr194.py` adds a transport-neutral boundary with:

- explicit optional discovery, required discovery, refinement, finalization,
  settlement/status and emergency-reconciliation classes;
- a bounded queue with required-work reservation;
- per-strategy and per-provider admission caps;
- feasibility rejection when estimated cost cannot fit before the deadline;
- deterministic class ordering, aging, deadline urgency and weighted fair share;
- optional-work eviction for admitted proof-critical work;
- independent discovery, finalization and settlement semaphore pools;
- cancellation-safe pool acquisition and release;
- wait p50/p95/p99, starvation, fairness, eviction, deadline and denial metrics.

## Verification

Focused preparation in the isolated workspace:

```text
python -m py_compile: success
pytest tests/test_pr194_proof_critical_scheduling.py: 8 passed
```

The tests reproduce the reserved-finalization defect, verify `max_attempts`
protection, optional-flood reservation, low-volume strategy service, deadline
feasibility, pool isolation, cancellation safety and metrics.

## Safety and parallel-work boundary

This PR does not enable live trading, signing, submission, RPC traffic or
settlement mutation. The new fair scheduler is additive so parallel PR-152…193,
PR-195 and PR-197 work is not overwritten.

A later narrow composition cutover should replace the legacy global
`OpportunityQueue` at the active runtime boundary and wire the isolated pools to
real provider/finalization/settlement workers. PR-160 sustained-overload evidence
must still prove the production fairness and starvation SLOs.
